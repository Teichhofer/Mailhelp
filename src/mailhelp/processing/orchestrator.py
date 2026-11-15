"""Zentrale, schema-validierte und wiederaufnehmbare Ablaufsteuerung."""
from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from threading import Event
from typing import Any, Literal, Protocol

from .. import state_names
from ..config import (
    EventDefaultsSettings,
    OriginalAttachmentSettings,
    ProposalReconciliationSettings,
    Settings,
    TargetSettings,
    Topic,
)
from ..domain.duplicate import MailImapIdentity
from ..domain.mail import MailState, next_updated_at
from ..domain.processing import ProcessingErrorCode, ProcessingStage
from ..domain.proposal import Proposal
from ..domain.relevance import IrrelevantSenders, RelevanceDialog
from ..llm.decisions import relevance_fingerprint
from ..logging import EventLogger, NullLogger
from ..mailbox.imap import FetchedMail
from ..mailbox.mailbox_settings import effective_settings, effective_topics, mailbox_fingerprint, mailbox_topic_policy
from ..persistence.archive import record_analysis
from ..persistence.storage import JsonStore
from ..proposals.precheck import DuplicatePreCheckService
from ..proposals.proposal_reconciliation import ProposalReconciliationService
from . import orchestrator_failures, orchestrator_proposals
from .analysis import Analyzer
from .identity import addresses_in
from .mail_duplicates import DuplicateMailCheck
from .mail_pipeline import MailPipeline, ProcessingOutcome, ProcessingResult, ProcessingRun
from .mail_questions import MailQuestions
from .retry import blocked, succeeded
from .stage_timing import StageClock
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
                 vision: VisionExtractor | None = None, event_defaults: EventDefaultsSettings | None = None,
                 reconciliation_settings: ProposalReconciliationSettings | None = None, proposal_matcher=None):
        self.analyzer, self.store, self.notifier, self.chat_id = analyzer, store, notifier, chat_id
        self.topics, self.max_bytes = topics, mime_limits or max_mail_bytes
        self.stop_event = Event()
        self.logger = logger or NullLogger()
        self.clock = clock
        self.config_fingerprint = config_fingerprint
        self.topic_policy: str | None = None
        # Normal application construction always supplies validated settings;
        # these defaults retain the small dependency-injected test surface.
        self.targets = targets or TargetSettings(todoist_project="inbox", google_calendar="primary")
        self.user_timezone = user_timezone
        # Unlike processing state, the sender filter is configuration shared by
        # test and production mode.
        self.sender_store = sender_store or store
        self.precheck = precheck or DuplicatePreCheckService(logger=self.logger)
        # 4.8: the reply draft service when smart replies are configured (set by the runtime).
        self.drafts: Any = None
        self.vision = vision
        self.event_defaults = event_defaults or EventDefaultsSettings()
        self.reconciliation_settings = reconciliation_settings or ProposalReconciliationSettings()
        self.proposal_matcher = proposal_matcher
        self.reconciliation = ProposalReconciliationService(
            store, proposal_matcher, self.reconciliation_settings.max_semantic_candidates)
        self.pipeline = MailPipeline(self)
        self.duplicates = DuplicateMailCheck(self)
        self.questions = MailQuestions(self)
        self.mailbox_settings: Settings | None = None
        self.mailbox_numbers: dict[str, int] = {}
        # IMAP user names per mailbox number: the user's own sender addresses (4.5).
        self.mailbox_usernames: dict[int, str] = {}
        # Accounts whose mail is relevant without a check: IServ parent letters (3.3.7).
        self.always_relevant: frozenset[str] = frozenset()
        self.mailbox_prompts = self.mailbox_jev = None

    def configure_mailboxes(self, settings, prompts, numbers, jev=None):
        self.mailbox_settings, self.mailbox_prompts = settings, prompts
        self.mailbox_numbers, self.mailbox_jev = numbers, jev

    def mailbox_number(self, account_id: str) -> int:
        return self.mailbox_numbers.get(account_id, 1)

    def own_addresses(self, account_id: str) -> frozenset[str]:
        """The user's sender addresses for the mailbox of *account_id* (4.5).

        The IMAP user name, configured aliases and addresses in personal_info.
        """
        if self.mailbox_settings is None:
            return frozenset()
        number = self.mailbox_number(account_id)
        mailbox = self.mailbox_settings.imap.mailbox(number)
        aliases = mailbox.own_addresses if mailbox is not None else []
        personal = self.effective_settings(account_id).personal_info if mailbox is not None else ""
        return addresses_in([self.mailbox_usernames.get(number), *aliases, personal])

    def effective_settings(self, account_id: str):
        assert self.mailbox_settings is not None
        return effective_settings(self.mailbox_settings, self.mailbox_number(account_id))

    def fingerprint_for(self, account_id: str) -> str:
        if self.mailbox_settings is None:
            return self.config_fingerprint
        value = mailbox_fingerprint(self.mailbox_settings, self.mailbox_prompts, self.topics,
                                    self.mailbox_number(account_id))
        return relevance_fingerprint(value, self.mailbox_jev) if self.mailbox_jev is not None else value

    def policy_for(self, account_id: str) -> str | None:
        if self.mailbox_settings is None:
            return self.topic_policy
        return mailbox_topic_policy(self.mailbox_settings, self.mailbox_prompts, self.mailbox_number(account_id))

    def build_proposals(self, state: MailState) -> list[Proposal]:
        return orchestrator_proposals.build_proposals(self, state)

    def record_count_conflict(self, name: str, state: MailState, category: Literal["task", "event"],
                               expected: int, actual: int, router_call_id: str | None,
                               extractor_call_id: str) -> None:
        return orchestrator_proposals.record_count_conflict(self, name, state, category, expected, actual, router_call_id, extractor_call_id)

    # Original documents for download (2.3); composition applies ``attachments`` from config.yaml.
    original_attachments: OriginalAttachmentSettings = OriginalAttachmentSettings()

    def stop(self) -> None: self.stop_event.set()

    def load_model(self, name: str, model: type[Any], default: Any = None) -> Any:
        return self.store.load_model(name, model, default)

    def cache_previews(self, state: MailState, raw: bytes) -> None:
        return orchestrator_proposals.cache_previews(self, state, raw)

    def blocked_senders(self) -> IrrelevantSenders:
        blocked = (
            self.load_model("irrelevant-senders", IrrelevantSenders, IrrelevantSenders())
            if self.sender_store is self.store else
            self.sender_store.load_model("irrelevant-senders", IrrelevantSenders, IrrelevantSenders())
        )
        assert isinstance(blocked, IrrelevantSenders)
        return blocked

    def read_images(self, name: str, state: MailState, raw: bytes) -> None:
        return orchestrator_proposals.read_images(self, name, state, raw)

    def _future_deadlines(self, state: MailState) -> list[str]:
        return orchestrator_proposals._future_deadlines(self, state)

    def notification_text(self, state: MailState) -> str:
        return orchestrator_proposals.notification_text(self, state)

    def accepts_configuration(self, fingerprint: str, account_id: str | None = None) -> bool:
        current = self.fingerprint_for(account_id) if account_id is not None else self.config_fingerprint
        policy = self.policy_for(account_id) if account_id is not None else self.topic_policy
        if fingerprint == current:
            return True
        if policy is None:
            return False
        record = self.store.load(f"processing-topics-{fingerprint}", {})
        if account_id is not None and any(topic.mailboxes is not None for topic in self.topics):

            previous = [Topic.model_validate(item).model_copy(update={"mailboxes": None})
                        for item in record.get("topics", [])]
            selected = [topic.model_copy(update={"mailboxes": None})
                        for topic in effective_topics(self.topics, self.mailbox_number(account_id))]
            if previous != selected:
                return False
        return record.get("policy") == policy

    def topics_for(self, fingerprint: str, account_id: str | None = None) -> list[Topic]:
        if account_id is not None and fingerprint == self.fingerprint_for(account_id):
            return effective_topics(self.topics, self.mailbox_number(account_id))
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
        state.updated_at = next_updated_at(state)
        self.store.save(name, state.model_dump(mode="json"))
        names = {topic.id: topic.name for topic in self.topics_for(state.config_fingerprint)}
        record_analysis(self.store, state, names, getattr(self.analyzer, "last_relevance_source", "unknown"))
        self.logger.event("DEBUG", "orchestrator", "state_persisted", mail_id=state.id,
                          state=state.steps.model_dump(mode="json"), awaiting_relevance=state.awaiting_relevance,
                          failed=state.error is not None)

    def failure(self, name: str, state: MailState, code: ProcessingErrorCode,
                 stage: ProcessingStage, text: str, retryable: bool | None = None) -> None:
        return orchestrator_failures.failure(self, name, state, code, stage, text, retryable)

    def resolve_relevance(self, mail_id: str, version: int, decision: str, telegram_offset: int) -> MailState:
        return orchestrator_failures.resolve_relevance(self, mail_id, version, decision, telegram_offset)

    def resume_mail(self, state: MailState) -> ProcessingResult:
        return self.process(FetchedMail(state.imap.folder, state.imap.uidvalidity, state.imap.uid, b"",
                                        state.imap.account_id))

    def process(self, fetched: FetchedMail) -> ProcessingResult:
        run = self._begin(fetched)
        if isinstance(run, ProcessingResult):
            return run
        self._time(run)
        try:
            early = self.pipeline.advance(run, fetched)
            if early is not None:
                self._stop(run, early.outcome)
                return early
            run.stage = ProcessingStage.COMPLETION
            run.state.steps.completion = "completed"
            run.state.error = None
            succeeded(run.state)
            self.save(run.name, run.state)
            self.logger.event("INFO", "orchestrator", "processing_completed", mail_id=run.state.id,
                              duration_ms=round((time.perf_counter() - run.started) * 1000, 3))
        except Exception as exc:
            outcome = self.pipeline.handle_failure(run, exc)
        else:
            outcome = ProcessingOutcome.COMPLETED
        self._stop(run, outcome)
        return ProcessingResult(outcome, run.state.model_dump(mode="json"))

    def _time(self, run: ProcessingRun) -> None:
        """6.1.6: one clock per pass; a mail whose preparation is already done is resumed."""
        state = run.state
        run.timer = StageClock(lambda record: self.logger.event("INFO", "orchestrator", "stage_finished", **record),
                               state.id, state.analysis_round, state.steps.preparation == "completed")
        run.timer.enter(run.stage.value)

    @staticmethod
    def _stop(run: ProcessingRun, outcome: ProcessingOutcome) -> None:
        assert run.timer is not None  # set by _time() before the pipeline runs
        if outcome == ProcessingOutcome.COMPLETED:
            run.timer.finish("completed", final=True)
        else:
            run.timer.finish("deferred" if outcome == ProcessingOutcome.WAITING else "failed")

    def remember_topics(self, state: MailState) -> None:
        """Keep the topics of the state's configuration, so a resumed mail uses the same ones."""
        if self.mailbox_settings is None:
            return
        account = state.imap.account_id
        self.store.save(
            f"processing-topics-{state.config_fingerprint}",
            {
                "schema_version": 1,
                "policy": self.policy_for(account),
                "topics": [topic.model_dump() for topic in self.topics_for(state.config_fingerprint, account)],
            },
        )

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
            imap=MailImapIdentity(account_id=fetched.account_id, folder=fetched.folder,
                                  uidvalidity=fetched.uidvalidity, uid=fetched.uid),
            config_fingerprint=self.fingerprint_for(fetched.account_id),
        )
        if existing is None:
            self.remember_topics(state)
        if state.steps.completion != "completed" and not self.accepts_configuration(
            state.config_fingerprint, fetched.account_id
        ):
            self.logger.event("WARNING", "orchestrator", "configuration_changed", mail_id=state.id,
                              state_fingerprint=state.config_fingerprint, active_fingerprint=self.config_fingerprint)
            return ProcessingResult(ProcessingOutcome.WAITING, state.model_dump(mode="json"))
        retry = state.processing_retry
        if retry is not None and retry.abandoned:
            self.logger.event("WARNING", "orchestrator", "processing_abandoned", mail_id=state.id)
            return ProcessingResult(ProcessingOutcome.FAILED, state.model_dump(mode="json"))
        if blocked(state, self.fingerprint_for(state.imap.account_id), datetime.fromtimestamp(self.clock(), UTC)):
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
        return orchestrator_failures.failure_outcome(self, name, state, stage)

    def run(self, poll: Any, interval: float, wait: Any = None) -> None:
        waiter = wait or self.stop_event.wait
        while not self.stop_event.is_set():
            for mail in poll():
                if self.stop_event.is_set(): break
                self.process(mail)
            waiter(interval)
