"""Zentrale, schema-validierte und wiederaufnehmbare Ablaufsteuerung."""
from __future__ import annotations

import hashlib
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from threading import Event
from typing import Any, Protocol

from .analysis import Analyzer, LlmSchemaValidationExceeded
from .adapter import PermanentError
from .config import Topic
from .imap import FetchedMail
from .mime import MimeLimitExceeded, prepare
from .models import (MailState, ProcessingError, ProcessingErrorCode, ProcessingStage,
                     Proposal, Relevance, RelevanceDialog, RelevanceDialogStatus)
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
    def __init__(self, analyzer: Analyzer, store: JsonStore, notifier: Notifier, chat_id: int, topics: list[Topic], max_mail_bytes: int, logger: EventLogger | None = None, clock: Any = time.time, mime_limits: object | None = None):
        self.analyzer, self.store, self.notifier, self.chat_id, self.topics, self.max_bytes = analyzer, store, notifier, chat_id, topics, mime_limits or max_mail_bytes
        self.stop_event = Event()
        self.logger = logger or NullLogger()
        self.clock = clock

    def stop(self) -> None: self.stop_event.set()

    def _save(self, name: str, state: MailState) -> None:
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
        return self.process(FetchedMail(state.imap.folder, state.imap.uidvalidity, state.imap.uid, b""))

    def process(self, fetched: FetchedMail) -> ProcessingResult:
        identity = f"{fetched.folder}:{fetched.uidvalidity}:{fetched.uid}"
        internal_id = hashlib.sha256(identity.encode()).hexdigest()[:24]
        started = time.perf_counter()
        self.logger.event("INFO", "orchestrator", "processing_started", mail_id=internal_id)
        name = f"mail-{internal_id}"
        existing = self.store.load_model(name, MailState) if hasattr(self.store, "load_model") else self.store.load(name)
        state = existing if isinstance(existing, MailState) else MailState.model_validate(existing) if existing is not None else MailState(
            id=internal_id,
            imap={"folder": fetched.folder, "uidvalidity": fetched.uidvalidity, "uid": fetched.uid},
        )
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
                state.mail = prepare(fetched.raw, self.max_bytes)
                state.mail["internal_id"] = internal_id
                state.steps.preparation = "completed"
                self._save(name, state)
                self.logger.event("INFO", "orchestrator", "preparation_completed", mail_id=state.id,
                                  preparation_metadata=state.mail["metadata"])
            assert state.mail is not None
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
                    state.proposals = actions.proposals
                    state.llm_call_ids.append(call)
                    state.steps.action_detection = "completed"
                    self._save(name, state)
                    self.logger.event("INFO", "orchestrator", "actions_completed", mail_id=state.id, call_id=call,
                                      proposal_ids=[item.id for item in state.proposals])
                stage = ProcessingStage.NOTIFICATION
                if state.steps.notification == "pending":
                    assert state.summary is not None
                    self.notifier.send(self.chat_id, f"{state.mail['headers']['subject']}\n" + " ".join(state.summary.sentences))
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
