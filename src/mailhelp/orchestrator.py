"""Zentrale, schema-validierte und wiederaufnehmbare Ablaufsteuerung."""
from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from threading import Event
from typing import Any, Protocol

from . import state_names
from .action_normalization import MailDateContext
from .analysis import Analyzer
from .config import TargetSettings, Topic
from .imap import FetchedMail
from .logging import EventLogger, NullLogger
from .mail_duplicates import DuplicateMailCheck
from .mail_pipeline import MailPipeline, ProcessingOutcome, ProcessingResult, ProcessingRun
from .mail_questions import MailQuestions
from .models import (
    ExtractionCountConflict,
    IrrelevantSenders,
    MailState,
    ProcessingError,
    ProcessingErrorCode,
    ProcessingStage,
    Proposal,
    Relevance,
    RelevanceDialog,
    RelevanceDialogStatus,
)
from .precheck import DuplicatePreCheckService
from .proposal_builder import ProposalBuilder
from .sender_filter import is_irrelevant_sender
from .storage import JsonStore
from .telegram.formatting import mail_line
from .vision import VisionExtractor


class Notifier(Protocol):
    def send(self, chat_id: int, text: str) -> None: ...
    def send_proposal(self, proposal: Any) -> None: ...
    def send_relevance(self, dialog: RelevanceDialog, sender: str, subject: str) -> None: ...
    def awaiting_decision(self) -> bool: ...


class Orchestrator:
    def __init__(self, analyzer: Analyzer, store: JsonStore, notifier: Notifier, chat_id: int, topics: list[Topic],
                 max_mail_bytes: int, logger: EventLogger | None = None, clock: Any = time.time,
                 mime_limits: object | None = None, config_fingerprint: str = "0" * 64,
                 targets: TargetSettings | None = None, user_timezone: str = "UTC",
                 sender_store: JsonStore | None = None, precheck: DuplicatePreCheckService | None = None,
                 vision: VisionExtractor | None = None):
        self.analyzer, self.store, self.notifier, self.chat_id = analyzer, store, notifier, chat_id
        self.topics, self.max_bytes = topics, mime_limits or max_mail_bytes
        self.stop_event = Event()
        self.logger = logger or NullLogger()
        self.clock = clock
        self.config_fingerprint = config_fingerprint
        self.topic_policy = None
        # Normal application construction always supplies validated settings;
        # these defaults retain the small dependency-injected test surface.
        self.targets = targets or TargetSettings(todoist_project="inbox", google_calendar="primary")
        self.user_timezone = user_timezone
        # Unlike processing state, the sender filter is configuration shared by
        # test and production mode.
        self.sender_store = sender_store or store
        self.precheck = precheck or DuplicatePreCheckService(logger=self.logger)
        self.vision = vision
        self.pipeline = MailPipeline(self)
        self.duplicates = DuplicateMailCheck(self)
        self.questions = MailQuestions(self)

    def build_proposals(self, state: MailState) -> list[Proposal]:
        """Cross from untrusted extracted facts into application-owned proposals."""
        mail = state.prepared
        assert mail is not None
        context = MailDateContext(
            date_context_status=mail.date_context_status,
            date_header_parsed=mail.date_header_parsed,
            imap_received_at=mail.imap_received_at,
            user_timezone=mail.user_timezone or self.user_timezone,
        )
        headers = state.display_headers
        return ProposalBuilder(
            state.id, self.targets, context,
            source_sender=headers.sender if headers else "—",
            source_subject=headers.subject if headers else "—",
        ).build(
            state.task_extraction.tasks if state.task_extraction else [],
            state.event_extraction.events if state.event_extraction else [],
            state.extraction_count_conflicts,
            calendar_events=mail.calendar_events,
        )

    def record_count_conflict(self, name: str, state: MailState, category: str,
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
        self.save(name, state)
        self.logger.event("WARNING", "orchestrator", "extraction_count_conflict",
                          mail_id=state.id, category=category, expected_count=expected,
                          actual_count=actual, router_call_id=router_call_id,
                          extractor_call_id=extractor_call_id)

    def stop(self) -> None: self.stop_event.set()

    def load_model(self, name: str, model: type[Any], default: Any = None) -> Any:
        return self.store.load_model(name, model, default)

    def cache_previews(self, state: MailState, raw: bytes) -> None:
        """Image previews are optional; a failure never stops the analysis."""
        from .attachments import AttachmentCache
        try:
            AttachmentCache(self.store).prepare(state.id, raw, state.mail["extracted_attachments"])
        except (OSError, ValueError) as exc:
            self.logger.event("WARNING", "orchestrator", "preview_failed", mail_id=state.id,
                              error_class=type(exc).__name__)

    def blocked_senders(self) -> IrrelevantSenders:
        blocked = (
            self.load_model("irrelevant-senders", IrrelevantSenders, IrrelevantSenders())
            if self.sender_store is self.store else
            self.sender_store.load_model("irrelevant-senders", IrrelevantSenders, IrrelevantSenders())
        )
        assert isinstance(blocked, IrrelevantSenders)
        return blocked

    def read_images(self, name: str, state: MailState, raw: bytes) -> None:
        """Vision OCR before relevance; progress is saved per attachment.

        It runs at most once per mail, never for a blocked sender and only while
        the original message is available (a resumed mail has no raw bytes).
        """
        assert state.mail is not None and self.vision is not None
        metadata = state.mail["metadata"]
        if "vision" in metadata:
            return
        if not raw:
            metadata["vision"] = "unavailable"
        elif is_irrelevant_sender(state.prepared.headers.sender, self.blocked_senders()):
            metadata["vision"] = "skipped_sender"
        else:
            attachments = state.mail.get("extracted_attachments", [])
            for update in self.vision.extract(raw, attachments):
                attachments[update.index] = update.attachment
                if update.call_id is not None:
                    state.llm_call_ids.append(update.call_id)
                self.save(name, state)
                self.logger.event("WARNING" if update.error else "INFO", "orchestrator",
                                  "vision_attachment", mail_id=state.id, attachment=update.index,
                                  outcome=update.attachment["vision"], call_id=update.call_id,
                                  error_type=update.error,
                                  characters=update.attachment.get("character_count", 0))
            metadata["vision"] = "completed"
        self.save(name, state)

    def notification_text(self, state: MailState) -> str:
        """Format the compact mail notification from validated display values."""
        assert state.mail is not None and state.relevance is not None and state.summary is not None
        headers = state.prepared.headers
        sentences = "\n".join(f"• {sentence}" for sentence in state.summary.sentences)
        return f"{mail_line(headers.sender or '—', headers.subject or '—')}\n{sentences}"

    def accepts_configuration(self, fingerprint: str) -> bool:
        if fingerprint == self.config_fingerprint:
            return True
        if self.topic_policy is None:
            return False
        record = self.store.load(f"processing-topics-{fingerprint}", {})
        return record.get("policy") == self.topic_policy

    def topics_for(self, fingerprint: str) -> list[Topic]:
        if fingerprint == self.config_fingerprint:
            return self.topics
        record = self.store.load(f"processing-topics-{fingerprint}", {})
        return [Topic.model_validate(item) for item in record.get("topics", [t.model_dump() for t in self.topics])]

    def change_topics(self, topics: list[Topic]) -> None:
        self.store.save(f"processing-topics-{self.config_fingerprint}", {
            "schema_version": 1, "policy": self.topic_policy,
            "topics": [topic.model_dump() for topic in self.topics]})
        self.topics = topics
        self.config_fingerprint = hashlib.sha256(json.dumps(
            [self.topic_policy, [topic.model_dump() for topic in topics]], sort_keys=True).encode()).hexdigest()
        self.store.save(f"processing-topics-{self.config_fingerprint}", {
            "schema_version": 1, "policy": self.topic_policy,
            "topics": [topic.model_dump() for topic in topics]})

    def save(self, name: str, state: MailState) -> None:
        state.updated_at = datetime.now(UTC)
        self.store.save(name, state.model_dump(mode="json"))
        from .review.archive import record_analysis
        names = {topic.id: topic.name for topic in self.topics_for(state.config_fingerprint)}
        record_analysis(self.store, state, names, getattr(self.analyzer, "last_relevance_source", "unknown"))
        self.logger.event("DEBUG", "orchestrator", "state_persisted", mail_id=state.id,
                          state=state.steps.model_dump(mode="json"), awaiting_relevance=state.awaiting_relevance,
                          failed=state.error is not None)

    def failure(self, name: str, state: MailState, code: ProcessingErrorCode,
                 stage: ProcessingStage, text: str, retryable: bool | None = None) -> None:
        """Mark before sending, and retain a matching generation across restarts."""
        now = datetime.now(UTC)
        previous = state.error
        if previous is None or previous.code != code or previous.stage != stage:
            state.error = ProcessingError(code=code, stage=stage, occurred_at=now, retryable=retryable)
        if state.error.notification_marked_at is not None:
            self.save(name, state)
            return
        state.error.notification_marked_at = now
        self.save(name, state)
        if state.prepared is not None:
            sender, subject = state.prepared.headers.sender, state.prepared.headers.subject
        else:
            display = state.display_headers
            sender, subject = (display.sender, display.subject) if display else ("—", "—")
        self.notifier.send(
            self.chat_id,
            "\n".join([
                mail_line(sender or "—", subject or "—"),
                f"⚠️ Schritt {stage.value}: {text}",
            ]),
        )

    def resolve_relevance(self, mail_id: str, version: int, decision: str, telegram_offset: int) -> MailState:
        name = state_names.mail(mail_id)
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
        state.relevance_dialog = dialog.model_copy(update={
            "status": RelevanceDialogStatus.DECIDED, "decision": decision, "telegram_offset": telegram_offset})
        if decision == "irrelevant":
            state.steps.summary = state.steps.action_detection = "skipped"
            state.steps.action_router = state.steps.task_extraction = state.steps.event_extraction = "skipped"
            state.steps.normalization = state.steps.proposal_building = "skipped"
            state.steps.duplicate_precheck = "skipped"
            state.steps.summary_notification = state.steps.proposal_notification = "skipped"
            state.steps.completion = "completed"
        else:
            state.steps.summary_notification = "pending"
        self.save(name, state)
        return state

    def resume_mail(self, state: MailState) -> ProcessingResult:
        return self.process(FetchedMail(state.imap.folder, state.imap.uidvalidity, state.imap.uid, b"",
                                        state.imap.account_id))

    def process(self, fetched: FetchedMail) -> ProcessingResult:
        run = self._begin(fetched)
        if isinstance(run, ProcessingResult):
            return run
        try:
            early = self.pipeline.advance(run, fetched)
            if early is not None:
                return early
            run.stage = ProcessingStage.COMPLETION
            run.state.steps.completion = "completed"
            run.state.error = None
            self.save(run.name, run.state)
            self.logger.event("INFO", "orchestrator", "processing_completed", mail_id=run.state.id,
                              duration_ms=round((time.perf_counter() - run.started) * 1000, 3))
        except Exception as exc:
            outcome = self.pipeline.handle_failure(run, exc)
        else:
            outcome = ProcessingOutcome.COMPLETED
        return ProcessingResult(outcome, run.state.model_dump(mode="json"))

    def _begin(self, fetched: FetchedMail) -> ProcessingRun | ProcessingResult:
        """Load or create the mail state; a result means nothing is to be done now."""
        identity = f"{fetched.account_id}:{fetched.folder}:{fetched.uidvalidity}:{fetched.uid}"
        internal_id = hashlib.sha256(identity.encode()).hexdigest()[:24]
        started = time.perf_counter()
        self.logger.event("INFO", "orchestrator", "processing_started", mail_id=internal_id)
        name = state_names.mail(internal_id)
        existing = self.store.load_model(name, MailState)
        state = existing if isinstance(existing, MailState) else MailState(
            id=internal_id,
            imap={"account_id": fetched.account_id, "folder": fetched.folder, "uidvalidity": fetched.uidvalidity,
                  "uid": fetched.uid},
            config_fingerprint=self.config_fingerprint,
        )
        if state.steps.completion != "completed" and not self.accepts_configuration(state.config_fingerprint):
            self.logger.event("WARNING", "orchestrator", "configuration_changed", mail_id=state.id,
                              state_fingerprint=state.config_fingerprint, active_fingerprint=self.config_fingerprint)
            return ProcessingResult(ProcessingOutcome.WAITING, state.model_dump(mode="json"))
        if state.deferred_until is not None and state.deferred_until.timestamp() > self.clock():
            self.logger.event("INFO", "orchestrator", "processing_deferred", mail_id=state.id,
                              deferred_until=state.deferred_until)
            return ProcessingResult(ProcessingOutcome.WAITING, state.model_dump(mode="json"))
        state.deferred_until = None
        if state.steps.completion == "completed" and state.steps.action_detection != "failed":
            self.logger.event("DEBUG", "orchestrator", "processing_already_completed", mail_id=state.id)
            return ProcessingResult(ProcessingOutcome.COMPLETED, state.model_dump(mode="json"))
        return ProcessingRun(name, state, ProcessingStage.PREPARATION, started)

    def failure_outcome(self, name: str, state: MailState,
                         stage: ProcessingStage) -> ProcessingOutcome:
        """Complete the mail while retaining a retryable action-only failure."""
        action_stages = {ProcessingStage.ACTION_ROUTER, ProcessingStage.TASK_EXTRACTION,
                         ProcessingStage.EVENT_EXTRACTION, ProcessingStage.NORMALIZATION,
                         ProcessingStage.PROPOSAL_BUILDING, ProcessingStage.DUPLICATE_PRECHECK}
        if stage not in action_stages:
            return ProcessingOutcome.FAILED
        step_name = {
            ProcessingStage.ACTION_ROUTER: "action_router",
            ProcessingStage.TASK_EXTRACTION: "task_extraction",
            ProcessingStage.EVENT_EXTRACTION: "event_extraction",
            ProcessingStage.NORMALIZATION: "normalization",
            ProcessingStage.PROPOSAL_BUILDING: "proposal_building",
            ProcessingStage.DUPLICATE_PRECHECK: "duplicate_precheck",
        }[stage]
        setattr(state.steps, step_name, "failed")
        state.steps.action_detection = "failed"
        state.steps.proposal_notification = "pending"
        state.steps.completion = "completed"
        self.save(name, state)
        return ProcessingOutcome.COMPLETED_WITH_ACTION_ERROR

    def run(self, poll: Any, interval: float, wait: Any = None) -> None:
        waiter = wait or self.stop_event.wait
        while not self.stop_event.is_set():
            for mail in poll():
                if self.stop_event.is_set(): break
                self.process(mail)
            waiter(interval)
