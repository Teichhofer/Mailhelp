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

from .analysis import (Analyzer, LlmInvalidJson, LlmProviderResponseInvalid,
                       LlmSchemaValidationExceeded)
from .adapter import PermanentError
from .config import TargetSettings, Topic
from .action_normalization import MailDateContext
from .proposal_builder import ProposalBuilder
from .imap import FetchedMail
from .mime import MimeLimitExceeded, extract_display_headers, prepare
from .models import (DisplayHeaders, DuplicateDecision, DuplicateIndex, DuplicateIndexEntry, ExtractionCountConflict, IrrelevantSenders, MailState, ProcessingError, ProcessingErrorCode, ProcessingStage,
                     Proposal, Relevance, RelevanceDialog, RelevanceDialogStatus,
                     ProposalNotification, ValidationIssue)
from .storage import JsonStore
from .openrouter import RateLimitExceeded
from .logging import EventLogger, NullLogger
from .sender_filter import is_irrelevant_sender


class Notifier(Protocol):
    def send(self, chat_id: int, text: str) -> None: ...
    def send_proposal(self, proposal: Any) -> None: ...
    def send_relevance(self, dialog: RelevanceDialog, sender: str, subject: str) -> None: ...
    def awaiting_decision(self) -> bool: ...


class ProcessingOutcome(StrEnum):
    """Extern sichtbares Ergebnis eines Verarbeitungsversuchs."""

    COMPLETED = "completed"
    COMPLETED_WITH_ACTION_ERROR = "completed_with_action_error"
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
    def __init__(self, analyzer: Analyzer, store: JsonStore, notifier: Notifier, chat_id: int, topics: list[Topic], max_mail_bytes: int, logger: EventLogger | None = None, clock: Any = time.time, mime_limits: object | None = None, config_fingerprint: str = "0" * 64, targets: TargetSettings | None = None, user_timezone: str = "UTC", sender_store: JsonStore | None = None):
        self.analyzer, self.store, self.notifier, self.chat_id, self.topics, self.max_bytes = analyzer, store, notifier, chat_id, topics, mime_limits or max_mail_bytes
        self.stop_event = Event()
        self.logger = logger or NullLogger()
        self.clock = clock
        self.config_fingerprint = config_fingerprint
        # Normal application construction always supplies validated settings;
        # these defaults retain the small dependency-injected test surface.
        self.targets = targets or TargetSettings(todoist_project="inbox", google_calendar="primary")
        self.user_timezone = user_timezone
        # Unlike processing state, the sender filter is configuration shared by
        # test and production mode.
        self.sender_store = sender_store or store

    def _build_proposals(self, state: MailState) -> list[Proposal]:
        """Cross from untrusted extracted facts into application-owned proposals."""
        assert state.mail is not None
        context = MailDateContext(
            date_context_status=str(state.mail.get("date_context_status", "missing")),
            date_header_parsed=state.mail.get("date_header_parsed"),
            imap_received_at=state.mail.get("imap_received_at"),
            user_timezone=state.mail.get("user_timezone") or self.user_timezone,
        )
        return ProposalBuilder(state.id, self.targets, context).build(
            state.task_extraction.tasks if state.task_extraction else [],
            state.event_extraction.events if state.event_extraction else [],
            state.extraction_count_conflicts,
        )

    def _resolve_questions_from_mail(self, name: str, state: MailState) -> None:
        """Resolve consecutive open questions from the source mail before Telegram."""
        assert state.mail is not None
        for index, initial in enumerate(state.proposals):
            proposal = initial
            while proposal.open_questions:
                question = proposal.open_questions[0]
                call, interpretation = self.analyzer.answer_question_from_mail(
                    state.mail, proposal, question)
                state.llm_call_ids.append(call)
                self._save(name, state)
                if not interpretation.usable:
                    self.logger.event(
                        "INFO", "orchestrator", "mail_question_unanswered",
                        mail_id=state.id, proposal_id=proposal.id,
                        proposal_version=proposal.version, question=question,
                        call_id=call,
                    )
                    break
                assert interpretation.normalized_answer is not None
                revision_call, proposal = self.analyzer.revise_proposal(
                    proposal, question, interpretation.normalized_answer)
                state.llm_call_ids.append(revision_call)
                state.proposals[index] = proposal
                self._save(name, state)
                self.logger.event(
                    "INFO", "orchestrator", "mail_question_resolved",
                    mail_id=state.id, proposal_id=proposal.id,
                    proposal_version=proposal.version, question=question,
                    interpretation_call_id=call, revision_call_id=revision_call,
                )

    def _record_count_conflict(self, name: str, state: MailState, category: str,
                               expected: int, actual: int, router_call_id: str,
                               extractor_call_id: str) -> None:
        if expected == actual:
            return
        key = (category, router_call_id, extractor_call_id)
        if any((item.category, item.router_call_id, item.extractor_call_id) == key
               for item in state.extraction_count_conflicts):
            return
        conflict = ExtractionCountConflict(
            category=category, expected_count=expected, actual_count=actual,
            router_call_id=router_call_id, extractor_call_id=extractor_call_id,
        )
        state.extraction_count_conflicts.append(conflict)
        self._save(name, state)
        self.logger.event("WARNING", "orchestrator", "extraction_count_conflict",
                          mail_id=state.id, category=category, expected_count=expected,
                          actual_count=actual, router_call_id=router_call_id,
                          extractor_call_id=extractor_call_id)

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
                state.steps.action_router = state.steps.task_extraction = state.steps.event_extraction = "skipped"
                state.steps.normalization = state.steps.proposal_building = "skipped"
                state.steps.summary_notification = state.steps.proposal_notification = "skipped"
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
        """Format the compact mail notification from validated display values."""
        assert state.mail is not None and state.relevance is not None and state.summary is not None
        headers = state.mail["headers"]
        sentences = "\n".join(f"- {sentence}" for sentence in state.summary.sentences)
        return "\n".join([
            f"Absender: {headers['from'] or '—'}",
            f"Betreff: {headers['subject'] or '—'}",
            f"Zusammenfassung:\n{sentences}",
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
        headers = state.mail.get("headers", {}) if state.mail is not None else {
            "from": state.display_headers.sender if state.display_headers else "—",
            "subject": state.display_headers.subject if state.display_headers else "—",
        }
        self.notifier.send(
            self.chat_id,
            "\n".join([
                f"Absender: {headers.get('from') or '—'}",
                f"Betreff: {headers.get('subject') or '—'}",
                f"Stufe {stage.value}: {text}",
            ]),
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
        state.relevance = Relevance(
            decision=decision, topic_ids=[], reason="Telegram-Entscheidung"
        )
        state.awaiting_relevance = False
        state.relevance_dialog = dialog.model_copy(update={"status": RelevanceDialogStatus.DECIDED, "decision": decision, "telegram_offset": telegram_offset})
        if decision == "irrelevant":
            state.steps.summary = state.steps.action_detection = "skipped"
            state.steps.action_router = state.steps.task_extraction = state.steps.event_extraction = "skipped"
            state.steps.normalization = state.steps.proposal_building = "skipped"
            state.steps.summary_notification = state.steps.proposal_notification = "skipped"
            state.steps.completion = "completed"
        else:
            state.steps.summary_notification = "pending"
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
        if state.steps.completion == "completed" and state.steps.action_detection != "failed":
            self.logger.event("DEBUG", "orchestrator", "processing_already_completed", mail_id=state.id)
            return ProcessingResult(ProcessingOutcome.COMPLETED, state.model_dump(mode="json"))
        stage = ProcessingStage.PREPARATION
        try:
            if state.steps.preparation == "pending":
                if state.display_headers is None:
                    display = extract_display_headers(fetched.raw, self.max_bytes)
                    state.display_headers = DisplayHeaders(sender=display["from"], subject=display["subject"])
                    self._save(name, state)
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
                blocked = (
                    self._load_model("irrelevant-senders", IrrelevantSenders,
                                     IrrelevantSenders())
                    if self.sender_store is self.store else
                    self.sender_store.load_model(
                        "irrelevant-senders", IrrelevantSenders, IrrelevantSenders()
                    )
                )
                assert isinstance(blocked, IrrelevantSenders)
                if is_irrelevant_sender(state.mail["headers"].get("from", ""), blocked):
                    state.relevance = Relevance(
                        decision="irrelevant", topic_ids=[], reason="Absender-Vorfilter"
                    )
                    call = None
                else:
                    call, state.relevance = self.analyzer.relevance(state.mail, self.topics)
                    state.llm_call_ids.append(call)
                state.steps.relevance = "completed"
                self._save(name, state)
                self.logger.event("INFO", "orchestrator", "relevance_completed", mail_id=state.id,
                                  call_id=call, sender_prefilter=call is None)
            assert state.relevance is not None
            if state.relevance.decision == "irrelevant":
                state.steps.summary = "skipped"
                state.steps.action_detection = "skipped"
                state.steps.action_router = state.steps.task_extraction = state.steps.event_extraction = "skipped"
                state.steps.normalization = state.steps.proposal_building = "skipped"
                state.steps.summary_notification = state.steps.proposal_notification = "skipped"
            elif state.relevance.decision == "unclear":
                if state.steps.summary_notification == "pending":
                    state.relevance_dialog = RelevanceDialog(mail_id=state.id)
                    state.awaiting_relevance = True
                    self._save(name, state)
                    headers = state.mail["headers"]
                    self.notifier.send_relevance(
                        state.relevance_dialog,
                        headers["from"] or "—",
                        headers["subject"] or "—",
                    )
                    state.steps.summary_notification = "completed"
                    state.steps.proposal_notification = "skipped"
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
                stage = ProcessingStage.SUMMARY_NOTIFICATION
                if state.steps.summary_notification == "pending":
                    # ``sending`` is a durable uncertainty marker.  A crash after
                    # Telegram accepted the call must not cause an automatic duplicate.
                    state.steps.summary_notification = "sending"
                    self._save(name, state)
                    self.notifier.send(self.chat_id, self._notification_text(state))
                    state.steps.summary_notification = "completed"
                    self._save(name, state)
                stage = ProcessingStage.ACTION_DETECTION
                if state.steps.action_detection in {"pending", "failed"}:
                    if state.steps.action_router in {"pending", "failed"}:
                        stage = ProcessingStage.ACTION_ROUTER
                        call, route = self.analyzer.action_route(state.mail)
                        state.action_route = route
                        state.action_router_call_id = call
                        state.llm_call_ids.append(call)
                        state.steps.action_router = "completed"
                        self._save(name, state)
                    else:
                        assert state.action_route is not None
                        route = state.action_route
                    assert state.action_router_call_id is not None
                    wants_tasks = route.action_state in {"task", "task_and_event"}
                    # An event candidate must not disappear merely because the
                    # router is unsure whether the message is an invitation.  The
                    # extractor and proposal boundary preserve that uncertainty,
                    # while Telegram still receives the detected appointment.
                    wants_events = (route.action_state in {"event", "task_and_event"}
                                    or route.event_count > 0)
                    if wants_tasks and state.steps.task_extraction in {"pending", "failed"}:
                        stage = ProcessingStage.TASK_EXTRACTION
                        call, extraction = self.analyzer.extract_tasks(
                            state.mail, expected_count=route.task_count)
                        state.task_extraction = extraction
                        state.llm_call_ids.append(call)
                        state.steps.task_extraction = "completed"
                        self._save(name, state)
                        self._record_count_conflict(name, state, "task", route.task_count,
                                                    len(extraction.tasks),
                                                    state.action_router_call_id, call)
                        if len(extraction.tasks) != route.task_count:
                            raise LlmSchemaValidationExceeded("task_extraction")
                    if not wants_tasks:
                        state.steps.task_extraction = "skipped"
                        self._save(name, state)
                    if wants_events and state.steps.event_extraction in {"pending", "failed"}:
                        stage = ProcessingStage.EVENT_EXTRACTION
                        call, extraction = self.analyzer.extract_events(
                            state.mail, expected_count=route.event_count)
                        state.event_extraction = extraction
                        state.llm_call_ids.append(call)
                        state.steps.event_extraction = "completed"
                        self._save(name, state)
                        self._record_count_conflict(name, state, "event", route.event_count,
                                                    len(extraction.events),
                                                    state.action_router_call_id, call)
                        if len(extraction.events) != route.event_count:
                            raise LlmSchemaValidationExceeded("event_extraction")
                    elif not wants_events:
                        state.steps.event_extraction = "skipped"
                        self._save(name, state)
                    stage = ProcessingStage.NORMALIZATION
                    if state.steps.normalization in {"pending", "failed"}:
                        state.normalized_proposals = self._build_proposals(state) if (wants_tasks or wants_events) else []
                        state.steps.normalization = "completed"
                        self._save(name, state)
                    stage = ProcessingStage.PROPOSAL_BUILDING
                    if state.steps.proposal_building in {"pending", "failed"}:
                        state.proposals = [Proposal.model_validate(item.model_dump(mode="json"))
                                           for item in state.normalized_proposals]
                        state.steps.proposal_building = "completed"
                        self._save(name, state)
                    self._resolve_questions_from_mail(name, state)
                    state.proposal_notifications = [ProposalNotification(
                        proposal_id=item.id, proposal_version=item.version)
                        for item in state.proposals]
                    state.steps.action_detection = "completed"
                    self._save(name, state)
                    self.logger.event("INFO", "orchestrator", "actions_completed", mail_id=state.id,
                                      action_state=route.action_state,
                                      proposal_ids=[item.id for item in state.proposals])
                stage = ProcessingStage.PROPOSAL_NOTIFICATION
                if state.steps.proposal_notification in {"pending", "sending"}:
                    first_attempt = state.steps.proposal_notification == "pending"
                    if first_attempt:
                        state.steps.proposal_notification = "sending"
                        self._save(name, state)
                    if (first_attempt and state.action_route is not None
                            and state.action_route.action_state == "unclear"):
                        self.notifier.send(
                            self.chat_id,
                            "Mögliche Aufgabe oder möglicher Termin benötigt fachliche Klärung: "
                            + state.action_route.reason,
                        )
                    for conflict in state.extraction_count_conflicts:
                        if conflict.notification_marked_at is not None:
                            continue
                        # Mark before delivery: an uncertain Telegram result must
                        # never lead to an automatic duplicate after restart.
                        conflict.notification_marked_at = datetime.now(timezone.utc)
                        self._save(name, state)
                        self.notifier.send(
                            self.chat_id,
                            f"Zählerabweichung für {conflict.category}: Router "
                            f"{conflict.expected_count}, Extraktion {conflict.actual_count}. "
                            "Bitte die tatsächliche Anzahl klären.",
                        )
                    for proposal, notification in zip(state.proposals, state.proposal_notifications, strict=True):
                        if notification.status != "pending":
                            continue
                        dedicated_delivery = bool(getattr(
                            self.notifier, "manages_proposal_delivery", False))
                        if not dedicated_delivery:
                            notification.status = "sending"
                            self._save(name, state)
                        self.notifier.send_proposal(proposal)
                        # ProposalDeliveryService owns the sending/completed
                        # transition.  Reload its authoritative projection so a
                        # later orchestrator save cannot overwrite that state.
                        state = MailState.model_validate(self.store.load(name))
                        current = next(item for item in state.proposal_notifications
                                       if (item.proposal_id, item.proposal_version) ==
                                       (proposal.id, proposal.version))
                        # Compatibility for simple notifier ports: the
                        # dedicated delivery service has already completed its
                        # own transition, while a synchronous legacy notifier
                        # reports success by returning normally.
                        if current.status == "pending" or (
                                not dedicated_delivery and current.status == "sending"):
                            current.status = "completed"
                            self._save(name, state)
                        # The production dialog persists the proposal before it
                        # exposes its buttons.  Stop at that durable boundary so
                        # no later proposal (or other processing) can overtake
                        # the user's version-bound decision.
                        if (dedicated_delivery
                                and self.notifier.awaiting_decision()):
                            self.logger.event(
                                "INFO", "orchestrator", "proposal_decision_pending",
                                mail_id=state.id, proposal_id=proposal.id,
                                proposal_version=proposal.version,
                            )
                            return ProcessingResult(
                                ProcessingOutcome.WAITING,
                                state.model_dump(mode="json"),
                            )
                    state.steps.proposal_notification = "completed"
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
                              limit=exc.limit, error=exc, stacktrace=traceback.format_exc())
            outcome = ProcessingOutcome.FAILED
        except LlmProviderResponseInvalid as exc:
            self._failure(name, state, ProcessingErrorCode.PROVIDER_RESPONSE_INVALID, stage,
                          "Der LLM-Anbieter hat keine verwendbare Antwort geliefert.", True)
            self.logger.event("ERROR", "orchestrator", "provider_response_invalid", mail_id=state.id,
                              stage=stage.value, reason=exc.reason, error=exc, stacktrace=traceback.format_exc())
            outcome = self._failure_outcome(name, state, stage)
        except LlmInvalidJson as exc:
            self._failure(name, state, ProcessingErrorCode.INVALID_JSON, stage,
                          "Die LLM-Antwort enthielt kein gültiges JSON.", True)
            self.logger.event("ERROR", "orchestrator", "invalid_json", mail_id=state.id, stage=stage.value,
                              error=exc, stacktrace=traceback.format_exc())
            outcome = self._failure_outcome(name, state, stage)
        except LlmSchemaValidationExceeded as exc:
            state.validation_errors.append(ValidationIssue(
                stage=stage, code="schema_validation_failed", occurred_at=datetime.now(timezone.utc)
            ))
            self._failure(name, state, ProcessingErrorCode.SCHEMA_VALIDATION_FAILED, stage,
                          "Die automatische Auswertung war nicht zuverlässig. Bitte die Nachricht manuell prüfen.", True)
            self.logger.event("ERROR", "orchestrator", "schema_validation_failed", mail_id=state.id, stage=stage.value,
                              error=exc, stacktrace=traceback.format_exc())
            outcome = self._failure_outcome(name, state, stage)
        except PermanentError as exc:
            self._failure(name, state, ProcessingErrorCode.PERMANENT_ADAPTER_ERROR, stage,
                          "Ein externer Dienst hat die Anfrage dauerhaft abgelehnt. Bitte dessen Konfiguration prüfen.", False)
            self.logger.event("ERROR", "orchestrator", "permanent_adapter_error", mail_id=state.id, stage=stage.value,
                              error=exc, stacktrace=traceback.format_exc())
            outcome = self._failure_outcome(name, state, stage)
        except Exception as exc:
            self._failure(name, state, ProcessingErrorCode.INTERNAL_ERROR, stage,
                          "Ein interner Fehler ist aufgetreten. Bitte Protokoll und Konfiguration prüfen.")
            self.logger.event("ERROR", "orchestrator", "processing_failed", mail_id=state.id, stage=stage.value, error=exc,
                              duration_ms=round((time.perf_counter() - started) * 1000, 3), stacktrace=traceback.format_exc())
            outcome = self._failure_outcome(name, state, stage)
        else:
            outcome = ProcessingOutcome.COMPLETED
        return ProcessingResult(outcome, state.model_dump(mode="json"))

    def _failure_outcome(self, name: str, state: MailState,
                         stage: ProcessingStage) -> ProcessingOutcome:
        """Complete the mail while retaining a retryable action-only failure."""
        action_stages = {ProcessingStage.ACTION_ROUTER, ProcessingStage.TASK_EXTRACTION,
                         ProcessingStage.EVENT_EXTRACTION, ProcessingStage.NORMALIZATION,
                         ProcessingStage.PROPOSAL_BUILDING}
        if stage not in action_stages:
            return ProcessingOutcome.FAILED
        step_name = {
            ProcessingStage.ACTION_ROUTER: "action_router",
            ProcessingStage.TASK_EXTRACTION: "task_extraction",
            ProcessingStage.EVENT_EXTRACTION: "event_extraction",
            ProcessingStage.NORMALIZATION: "normalization",
            ProcessingStage.PROPOSAL_BUILDING: "proposal_building",
        }[stage]
        setattr(state.steps, step_name, "failed")
        state.steps.action_detection = "failed"
        state.steps.proposal_notification = "pending"
        state.steps.completion = "completed"
        self._save(name, state)
        return ProcessingOutcome.COMPLETED_WITH_ACTION_ERROR

    def run(self, poll: Any, interval: float, wait: Any = None) -> None:
        waiter = wait or self.stop_event.wait
        while not self.stop_event.is_set():
            for mail in poll():
                if self.stop_event.is_set(): break
                self.process(mail)
            waiter(interval)
