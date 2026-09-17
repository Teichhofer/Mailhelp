"""Zentrale, schema-validierte und wiederaufnehmbare Ablaufsteuerung."""
from __future__ import annotations

import hashlib
import json
import re
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from threading import Event
from typing import Any, Protocol

from .analysis import Analyzer, LlmSchemaValidationExceeded
from .adapter import PermanentError
from .config import TargetSettings, Topic
from .imap import FetchedMail
from .mime import MimeLimitExceeded, prepare
from .models import (DuplicateDecision, DuplicateIndex, DuplicateIndexEntry, MailState, ProcessingError, ProcessingErrorCode, ProcessingStage,
                     Proposal, Relevance, RelevanceDialog, RelevanceDialogStatus,
                     ValidationIssue)
from .storage import JsonStore
from .openrouter import RateLimitExceeded
from .logging import EventLogger, NullLogger


class Notifier(Protocol):
    def send(self, chat_id: int, text: str) -> None: ...
    def send_proposal(self, proposal: Any) -> None: ...
    def send_relevance(self, dialog: RelevanceDialog) -> None: ...


class ProcessingOutcome(StrEnum):
    """Extern sichtbares Ergebnis eines Verarbeitungsversuchs."""

    COMPLETED = "completed"
    WAITING = "waiting"
    FAILED = "failed"


@dataclass(frozen=True)
class ProcessingResult:
    outcome: ProcessingOutcome
    state: dict[str, Any]

    def __getitem__(self, key: str) -> Any:
        """Keep state inspection concise while making the outcome explicit."""
        return self.state[key]

    def __contains__(self, key: object) -> bool:
        return key in self.state


class Orchestrator:
    def __init__(self, analyzer: Analyzer, store: JsonStore, notifier: Notifier, chat_id: int, topics: list[Topic], max_mail_bytes: int, logger: EventLogger | None = None, clock: Any = time.time, mime_limits: object | None = None, config_fingerprint: str = "0" * 64, targets: TargetSettings | None = None, user_timezone: str = "UTC"):
        self.analyzer, self.store, self.notifier, self.chat_id, self.topics, self.max_bytes = analyzer, store, notifier, chat_id, topics, mime_limits or max_mail_bytes
        self.stop_event = Event()
        self.logger = logger or NullLogger()
        self.clock = clock
        self.config_fingerprint = config_fingerprint
        self.targets = targets
        self.user_timezone = user_timezone

    def _normalize_proposals(self, state: MailState, proposals: list[Proposal]) -> list[Proposal]:
        """Replace all LLM-controlled identity/routing fields at the trust boundary."""
        supplied = [proposal.id for proposal in proposals]
        if len(supplied) != len(set(supplied)):
            raise ValueError("LLM lieferte doppelte Vorschlags-IDs")
        if proposals and self.targets is None:
            raise ValueError("Konfigurierte Vorschlagsziele fehlen")
        result = []
        for proposal in proposals:
            if proposal.source_mail_id != state.id:
                raise ValueError("LLM-Vorschlag gehört nicht zur verarbeiteten Mail")
            assert self.targets is not None
            target = (self.targets.todoist_project if proposal.kind.value == "task"
                      else self.targets.google_calendar)
            internal_id = "p_" + hashlib.sha256(
                f"{state.id}\0{proposal.id}".encode()
            ).hexdigest()[:16]
            update: dict[str, Any] = {"id": internal_id, "source_mail_id": state.id, "target": target}
            if proposal.kind.value == "event" and state.mail is not None and state.mail.get("date_context_status") != "valid":
                questions = list(proposal.open_questions)
                question = "Welcher Datumskontext soll für den Termin verwendet werden?"
                if question not in questions:
                    questions.append(question)
                update.update(open_questions=questions, status="needs_clarification")
            result.append(proposal.model_copy(update=update))
        return result

    def stop(self) -> None: self.stop_event.set()

    @staticmethod
    def _duplicate_identity(mail: dict[str, Any]) -> tuple[list[str], str, int]:
        """Derive bounded identifiers and a one-way digest, never stored content."""
        values = mail.get("message_ids", [mail["headers"].get("message_id", "")])
        normalized: list[str] = []
        for value in values:
            compact = re.sub(r"\s+", "", str(value)).casefold()
            if len(compact) <= 998 and re.fullmatch(r"<[^<>@\s]+@[^<>@\s]+>", compact) and compact not in normalized:
                normalized.append(compact)
        stable = {
            "from": str(mail["headers"].get("from", "")).casefold(),
            "subject": str(mail["headers"].get("subject", "")).casefold(),
            "date": str(mail["headers"].get("date", "")),
            "text": str(mail.get("text", "")),
        }
        digest = hashlib.sha256(json.dumps(stable, ensure_ascii=False, sort_keys=True,
                                           separators=(",", ":")).encode()).hexdigest()
        return normalized, digest, len(values)

    def _load_model(self, name: str, model: type[Any], default: Any = None) -> Any:
        if hasattr(self.store, "load_model"):
            return self.store.load_model(name, model, default)
        value = self.store.load(name, None)
        return default if value is None else model.model_validate(value)

    def _check_duplicate(self, name: str, state: MailState) -> bool:
        """Persist a conservative decision before any LLM call; return whether to skip."""
        assert state.mail is not None
        message_ids, fingerprint, message_id_headers = self._duplicate_identity(state.mail)
        index = self._load_model("duplicate-index", DuplicateIndex, DuplicateIndex())
        assert isinstance(index, DuplicateIndex)
        others = [entry for entry in index.entries
                  if entry.mail_id != state.id and entry.imap.account_id == state.imap.account_id]
        matching_ids = [entry for entry in others if set(entry.message_ids) & set(message_ids)]
        matching_fingerprints = [entry for entry in others if entry.content_fingerprint == fingerprint]

        if state.duplicate is None:
            candidate: DuplicateIndexEntry | None = None
            reason = "no_match"
            outcome = "new"
            if message_id_headers != 1 or len(message_ids) != 1:
                candidate = (matching_ids or matching_fingerprints or [None])[0]
                if candidate is not None:
                    outcome = "ambiguous"
                reason = "multiple_message_ids" if message_id_headers > 1 else "missing_message_id"
            elif matching_ids:
                candidate = matching_ids[0]
                completed = []
                for entry in matching_ids:
                    previous = self._load_model(f"mail-{entry.mail_id}", MailState)
                    completed.append(isinstance(previous, MailState) and previous.steps.completion == "completed")
                if all(entry.content_fingerprint == fingerprint for entry in matching_ids) and all(completed):
                    outcome, reason = "duplicate", "same_message"
                elif not all(completed):
                    outcome, reason = "ambiguous", "candidate_incomplete"
                else:
                    outcome, reason = "ambiguous", "message_id_reused"
            elif matching_fingerprints:
                candidate = matching_fingerprints[0]
                outcome, reason = "ambiguous", "fingerprint_collision"
            state.duplicate = DuplicateDecision(outcome=outcome, reason=reason,
                                                previous_mail_id=candidate.mail_id if candidate else None)
            if outcome == "duplicate":
                state.steps.relevance = state.steps.summary = state.steps.action_detection = "skipped"
                state.steps.notification = "skipped"
                state.steps.completion = "completed"
            self._save(name, state)
            self.logger.event("INFO", "orchestrator", "duplicate_checked", mail_id=state.id,
                              outcome=outcome, reason=reason,
                              previous_mail_id=candidate.mail_id if candidate else None)

        entry = DuplicateIndexEntry(mail_id=state.id, imap=state.imap, message_ids=message_ids,
                                    content_fingerprint=fingerprint)
        index.entries = [item for item in index.entries if item.mail_id != state.id] + [entry]
        self.store.save("duplicate-index", index.model_dump(mode="json"))
        return state.duplicate.outcome == "duplicate"

    def _notification_text(self, state: MailState) -> str:
        """Format only sanitized headers and schema-validated analysis results."""
        assert state.mail is not None and state.relevance is not None and state.summary is not None
        headers = state.mail["headers"]
        topic_names = {topic.id: topic.name for topic in self.topics}
        topics = ", ".join(topic_names[topic_id] for topic_id in state.relevance.topic_ids) or "Keine"
        deadlines = "\n".join(f"- {deadline}" for deadline in state.summary.deadlines) or "Keine"
        sentences = "\n".join(f"- {sentence}" for sentence in state.summary.sentences)
        action = (f"Ja – {len(state.proposals)} Vorschlag/Vorschläge zur Prüfung."
                  if state.proposals else "Nein – kein Vorschlag erkannt.")
        return "\n".join([
            f"Absender: {headers['from'] or '—'}",
            f"Betreff: {headers['subject'] or '—'}",
            f"Themen: {topics}",
            f"Zusammenfassung:\n{sentences}",
            f"Wichtige Fristen:\n{deadlines}",
            f"Handlungsbedarf: {action}",
        ])

    def _save(self, name: str, state: MailState) -> None:
        state.updated_at = datetime.now(timezone.utc)
        self.store.save(name, state.model_dump(mode="json"))
        self.logger.event("DEBUG", "orchestrator", "state_persisted", mail_id=state.id,
                          state=state.steps.model_dump(mode="json"))

    def _failure(self, name: str, state: MailState, code: ProcessingErrorCode,
                 stage: ProcessingStage, text: str, retryable: bool | None = None) -> None:
        """Mark before sending, and retain a matching generation across restarts."""
        now = datetime.now(timezone.utc)
        previous = state.error
        if previous is None or previous.code != code or previous.stage != stage:
            state.error = ProcessingError(code=code, stage=stage, occurred_at=now, retryable=retryable)
        if state.error.notification_marked_at is not None:
            self._save(name, state)
            return
        state.error.notification_marked_at = now
        self._save(name, state)
        self.notifier.send(
            self.chat_id,
            f"Mail-ID {state.id} · Stufe {stage.value}: {text}",
        )

    def resolve_relevance(self, mail_id: str, version: int, decision: str, telegram_offset: int) -> MailState:
        name = f"mail-{mail_id}"
        state = self.store.load_model(name, MailState)
        if not isinstance(state, MailState) or state.relevance_dialog is None:
            raise ValueError("Relevanzfrage wurde nicht gefunden")
        dialog = state.relevance_dialog
        if dialog.mail_id != mail_id or dialog.version != version or dialog.status != RelevanceDialogStatus.OPEN:
            raise ValueError("Die Relevanzfrage ist veraltet oder bereits beantwortet")
        if decision not in {"relevant", "irrelevant"}:
            raise ValueError("Ungültige Relevanzentscheidung")
        state.relevance = Relevance(decision=decision, reason="Telegram-Entscheidung")
        state.awaiting_relevance = False
        state.relevance_dialog = dialog.model_copy(update={"status": RelevanceDialogStatus.DECIDED, "decision": decision, "telegram_offset": telegram_offset})
        if decision == "irrelevant":
            state.steps.summary = state.steps.action_detection = state.steps.notification = "skipped"
            state.steps.completion = "completed"
        else:
            state.steps.notification = "pending"
        self._save(name, state)
        return state

    def resume_mail(self, state: MailState) -> ProcessingResult:
        return self.process(FetchedMail(state.imap.folder, state.imap.uidvalidity, state.imap.uid, b"", state.imap.account_id))

    def process(self, fetched: FetchedMail) -> ProcessingResult:
        identity = f"{fetched.account_id}:{fetched.folder}:{fetched.uidvalidity}:{fetched.uid}"
        internal_id = hashlib.sha256(identity.encode()).hexdigest()[:24]
        started = time.perf_counter()
        self.logger.event("INFO", "orchestrator", "processing_started", mail_id=internal_id)
        name = f"mail-{internal_id}"
        existing = self.store.load_model(name, MailState) if hasattr(self.store, "load_model") else self.store.load(name)
        state = existing if isinstance(existing, MailState) else MailState.model_validate(existing) if existing is not None else MailState(
            id=internal_id,
            imap={"account_id": fetched.account_id, "folder": fetched.folder, "uidvalidity": fetched.uidvalidity, "uid": fetched.uid},
            config_fingerprint=self.config_fingerprint,
        )
        if state.steps.completion != "completed" and state.config_fingerprint != self.config_fingerprint:
            self.logger.event("WARNING", "orchestrator", "configuration_changed", mail_id=state.id,
                              state_fingerprint=state.config_fingerprint, active_fingerprint=self.config_fingerprint)
            return ProcessingResult(ProcessingOutcome.WAITING, state.model_dump(mode="json"))
        if state.deferred_until is not None and state.deferred_until.timestamp() > self.clock():
            self.logger.event("INFO", "orchestrator", "processing_deferred", mail_id=state.id, deferred_until=state.deferred_until)
            return ProcessingResult(ProcessingOutcome.WAITING, state.model_dump(mode="json"))
        state.deferred_until = None
        if state.steps.completion == "completed":
            self.logger.event("DEBUG", "orchestrator", "processing_already_completed", mail_id=state.id)
            return ProcessingResult(ProcessingOutcome.COMPLETED, state.model_dump(mode="json"))
        stage = ProcessingStage.PREPARATION
        try:
            if state.steps.preparation == "pending":
                state.mail = prepare(fetched.raw, self.max_bytes, fetched.received_at, self.user_timezone)
                state.mail["internal_id"] = internal_id
                state.steps.preparation = "completed"
                self._save(name, state)
                self.logger.event("INFO", "orchestrator", "preparation_completed", mail_id=state.id,
                                  preparation_metadata=state.mail["metadata"])
            assert state.mail is not None
            if self._check_duplicate(name, state):
                self.logger.event("INFO", "orchestrator", "duplicate_skipped", mail_id=state.id,
                                  previous_mail_id=state.duplicate.previous_mail_id)
                return ProcessingResult(ProcessingOutcome.COMPLETED, state.model_dump(mode="json"))
            stage = ProcessingStage.RELEVANCE
            if state.steps.relevance == "pending":
                call, relevance = self.analyzer.relevance(state.mail, self.topics)
                state.relevance = relevance
                state.llm_call_ids.append(call)
                state.steps.relevance = "completed"
                self._save(name, state)
                self.logger.event("INFO", "orchestrator", "relevance_completed", mail_id=state.id, call_id=call)
            assert state.relevance is not None
            if state.relevance.decision == "irrelevant":
                state.steps.summary = "skipped"
                state.steps.action_detection = "skipped"
                state.steps.notification = "skipped"
            elif state.relevance.decision == "unclear":
                if state.steps.notification == "pending":
                    state.relevance_dialog = RelevanceDialog(mail_id=state.id)
                    state.awaiting_relevance = True
                    self._save(name, state)
                    self.notifier.send_relevance(state.relevance_dialog)
                    state.steps.notification = "completed"
                    self._save(name, state)
                    self.logger.event("INFO", "orchestrator", "notification_completed", mail_id=state.id)
                return ProcessingResult(ProcessingOutcome.WAITING, state.model_dump(mode="json"))
            else:
                stage = ProcessingStage.SUMMARY
                if state.steps.summary == "pending":
                    call, summary = self.analyzer.summary(state.mail)
                    state.summary = summary
                    state.llm_call_ids.append(call)
                    state.steps.summary = "completed"
                    self._save(name, state)
                    self.logger.event("INFO", "orchestrator", "summary_completed", mail_id=state.id, call_id=call)
                stage = ProcessingStage.ACTION_DETECTION
                if state.steps.action_detection == "pending":
                    call, actions = self.analyzer.actions(state.mail)
                    state.proposals = self._normalize_proposals(state, actions.proposals)
                    state.llm_call_ids.append(call)
                    state.steps.action_detection = "completed"
                    self._save(name, state)
                    self.logger.event("INFO", "orchestrator", "actions_completed", mail_id=state.id, call_id=call,
                                      proposal_ids=[item.id for item in state.proposals])
                stage = ProcessingStage.NOTIFICATION
                if state.steps.notification == "pending":
                    assert state.summary is not None
                    self.notifier.send(self.chat_id, self._notification_text(state))
                    for proposal in state.proposals:
                        self.notifier.send_proposal(proposal)
                        self.logger.event("INFO", "orchestrator", "proposal_notified", mail_id=state.id, proposal_id=proposal.id)
                    state.steps.notification = "completed"
                    self._save(name, state)
            stage = ProcessingStage.COMPLETION
            state.steps.completion = "completed"
            state.error = None
            self._save(name, state)
            self.logger.event("INFO", "orchestrator", "processing_completed", mail_id=state.id,
                              duration_ms=round((time.perf_counter() - started) * 1000, 3))
        except RateLimitExceeded as exc:
            state.deferred_until = datetime.fromtimestamp(exc.next_allowed_at, timezone.utc)
            self._failure(name, state, ProcessingErrorCode.LLM_RATE_LIMITED, stage,
                          f"LLM-Limit erreicht. Automatischer neuer Versuch nach {state.deferred_until.isoformat()}.", True)
            self.logger.event("WARNING", "orchestrator", "llm_rate_limited", mail_id=state.id, next_allowed_at=state.deferred_until.isoformat(),
                              duration_ms=round((time.perf_counter() - started) * 1000, 3), error=exc, stacktrace=traceback.format_exc())
            outcome = ProcessingOutcome.WAITING
        except MimeLimitExceeded as exc:
            self._failure(name, state, ProcessingErrorCode.MIME_LIMIT_EXCEEDED, stage,
                          "Die Nachricht überschreitet ein Sicherheitslimit. Bitte Anhänge oder Nachrichtengröße reduzieren.", False)
            self.logger.event("WARNING", "orchestrator", "mime_limit_exceeded", mail_id=state.id, stage=stage.value,
                              error=exc, stacktrace=traceback.format_exc())
            outcome = ProcessingOutcome.FAILED
        except LlmSchemaValidationExceeded as exc:
            state.validation_errors.append(ValidationIssue(
                stage=stage, code="llm_schema_validation_exhausted", occurred_at=datetime.now(timezone.utc)
            ))
            self._failure(name, state, ProcessingErrorCode.LLM_SCHEMA_VALIDATION_EXHAUSTED, stage,
                          "Die automatische Auswertung war nicht zuverlässig. Bitte die Nachricht manuell prüfen.", True)
            self.logger.event("ERROR", "orchestrator", "llm_schema_validation_exhausted", mail_id=state.id, stage=stage.value,
                              error=exc, stacktrace=traceback.format_exc())
            outcome = ProcessingOutcome.FAILED
        except PermanentError as exc:
            self._failure(name, state, ProcessingErrorCode.PERMANENT_ADAPTER_ERROR, stage,
                          "Ein externer Dienst hat die Anfrage dauerhaft abgelehnt. Bitte dessen Konfiguration prüfen.", False)
            self.logger.event("ERROR", "orchestrator", "permanent_adapter_error", mail_id=state.id, stage=stage.value,
                              error=exc, stacktrace=traceback.format_exc())
            outcome = ProcessingOutcome.FAILED
        except Exception as exc:
            self._failure(name, state, ProcessingErrorCode.INTERNAL_ERROR, stage,
                          "Ein interner Fehler ist aufgetreten. Bitte Protokoll und Konfiguration prüfen.")
            self.logger.event("ERROR", "orchestrator", "processing_failed", mail_id=state.id, stage=stage.value, error=exc,
                              duration_ms=round((time.perf_counter() - started) * 1000, 3), stacktrace=traceback.format_exc())
            outcome = ProcessingOutcome.FAILED
        else:
            outcome = ProcessingOutcome.COMPLETED
        return ProcessingResult(outcome, state.model_dump(mode="json"))

    def run(self, poll: Any, interval: float, wait: Any = None) -> None:
        waiter = wait or self.stop_event.wait
        while not self.stop_event.is_set():
            for mail in poll():
                if self.stop_event.is_set(): break
                self.process(mail)
            waiter(interval)
