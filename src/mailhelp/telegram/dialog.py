"""Telegram dialog orchestration."""

from __future__ import annotations

import time
from collections.abc import Callable
from threading import RLock

from .. import state_names
from ..domain.processing import (
    ProposalClarificationState,
    ProposalRevisionStatus,
    QuestionStatus,
)
from ..external.contracts import ExternalWriter
from ..models import Proposal, ProposalStatus, RelevanceDialog, TelegramOffset
from ..persistence.ledger import ActionLedgerPort, ActionLedgerService
from ..review.commands import CommandKind, CommandSource
from ..review.inbox import CommandInbox
from ..review.learning_log import DecisionLearningLog
from ..review.results import ResultStatus, ReviewResult
from ..runtime.lock_metrics import measure_lock_waits, measured_lock
from ..storage import JsonStore
from .authorization import AuthorizedUpdateValidator, UpdateValidation
from .callbacks import RelevanceDecision
from .client import TelegramTransport
from .models import TelegramUpdate
from .outbox import TelegramOutbox, revision_paused
from .receiver import TelegramInbox
from .relevance import RelevanceDialogProcessor, RelevanceHandler
from .revision_contracts import EventLogger, ProposalRevisionService
from .revisions import ProposalRevisionProcessor, ProposalRevisions
from .update_handling import (  # noqa: F401
    INBOX_MAX_ATTEMPTS,
    INBOX_RETRY_SECONDS,
    STALE_BUTTON,
    TelegramUpdateHandler,
    send_relevance_question,
)
from .writes import ConfirmedWriteExecutor, WriteExecution


class _DialogResponsePersistence:
    """Revisions answer the user directly and therefore bypass the outbox."""

    def __init__(self, controller: TelegramDialogController):
        self.controller = controller

    def persist(self, proposal: Proposal) -> None:
        self.controller.persist(proposal)

    def send_proposal(self, proposal: Proposal) -> None:
        self.controller.delivery.deliver(proposal)
        from .series import offer_confirmation
        offer_confirmation(self.controller, proposal)

    def delivered(self, proposal: Proposal) -> bool:
        """Whether this version was shown, i.e. is not held back in the outbox."""
        return (proposal.source_mail_id, proposal.id, proposal.version) not in (
            self.controller.outbox.queued_proposals())


class TelegramDialogController:
    """Validate updates, persist offsets, and enforce version-bound decisions."""

    manages_proposal_delivery = True

    def __init__(
        self,
        store: JsonStore,
        telegram: TelegramTransport,
        user_id: int,
        chat_id: int,
        logger: EventLogger,
        writers: dict[str, ExternalWriter] | None = None,
        test_mode: bool = False,
        configured_timezone: str = "UTC",
        revision_service: ProposalRevisionService | None = None,
        *,
        interpretation_attempts: int = 3,
        interpretation_backoff_seconds: int = 60,
        revision_attempts: int = 3,
        revision_backoff_seconds: int = 60,
        sequential_questions: bool = True,
        inbox: TelegramInbox | None = None,
        commands: CommandInbox | None = None,
    ):
        self.store, self.telegram, self.user_id, self.chat_id, self.logger = (
            store, telegram, user_id, chat_id, logger)
        # With an inbox, a receiver thread fetches updates; this controller
        # only processes them (see poll_once).
        self.inbox = inbox
        # Web commands, executed here like Telegram updates.
        self.commands = commands
        # The mail loop (notifications) and the operator thread (poll_once) both
        # reach this controller; it serves one of them at a time (3.6.4).
        self.lock = RLock()
        self._commands_recovered = False
        # Revokes every web session (Telegram command /web_abmelden).
        self.web_logout: Callable[[], int] | None = None
        # Link and one-time code for the web interface (Telegram command /web).
        self.web_invite: Callable[[], str] | None = None
        self.writers, self.test_mode = writers or {}, test_mode
        self.configured_timezone = configured_timezone
        self.revision_service = revision_service
        self.interpretation_attempts = interpretation_attempts
        self.interpretation_backoff_seconds = interpretation_backoff_seconds
        self.revision_attempts = revision_attempts
        self.revision_backoff_seconds = revision_backoff_seconds
        self.updates = TelegramUpdateHandler(self)
        self._compose(sequential_questions)

    def _compose(self, sequential_questions: bool) -> None:
        """Wire the services that share this dialog's state and transport."""
        from ..persistence.proposals import ProposalRepository
        from .decisions import ProposalDecisionService
        from .delivery import ProposalDeliveryService
        from .presenter import ProposalPresenter

        store, telegram, user_id, chat_id = self.store, self.telegram, self.user_id, self.chat_id
        logger, test_mode, configured_timezone = self.logger, self.test_mode, self.configured_timezone
        revision_service = self.revision_service
        interpretation_attempts = self.interpretation_attempts
        interpretation_backoff_seconds = self.interpretation_backoff_seconds
        revision_attempts, revision_backoff_seconds = self.revision_attempts, self.revision_backoff_seconds
        self.validator: UpdateValidation = AuthorizedUpdateValidator(
            store, user_id, chat_id
        )
        self.relevance = RelevanceDialogProcessor(store, telegram, chat_id)
        self.ledger: ActionLedgerPort = ActionLedgerService(store)
        self.repository = ProposalRepository(store)
        self.presenter = ProposalPresenter(
            configured_timezone, lambda decision: decision.encode(store), test_mode
        )
        self.delivery = ProposalDeliveryService(
            self.repository, self.presenter, telegram, chat_id
        )
        self.outbox = TelegramOutbox(
            store,
            telegram,
            chat_id,
            logger,
            self.repository,
            self.delivery.send_now,
            lambda dialog, sender, subject: send_relevance_question(
                telegram, chat_id, dialog, sender, subject),
            self.relevance,
            enabled=sequential_questions,
        )
        self.delivery.outbox = self.outbox
        write_executor = ConfirmedWriteExecutor(
            store,
            self.writers,
            self,
            telegram,
            chat_id,
            test_mode,
            self.ledger,
            configured_timezone,
        )
        write_executor.web_authorizer = self._web_write_authorized
        write_executor.telegram_authorizer = lambda actor: actor == f"telegram:{self.user_id}:{self.chat_id}"
        self.write_executor: WriteExecution = write_executor
        self.decision_service = ProposalDecisionService(
            store,
            self.repository,
            self,
            self.ledger,
            self.write_executor,
            telegram,
            user_id,
            chat_id,
            configured_timezone,
        )
        self.revisions: ProposalRevisions = ProposalRevisionProcessor(
            store,
            revision_service,
            _DialogResponsePersistence(self),
            telegram,
            chat_id,
            logger,
            configured_timezone,
            interpretation_attempts=interpretation_attempts,
            interpretation_backoff_seconds=interpretation_backoff_seconds,
            revision_attempts=revision_attempts,
            revision_backoff_seconds=revision_backoff_seconds,
        )
        from ..review.service import ReviewService

        self.review = ReviewService(self)
        # Set by the composition; records manual decisions as learning material.
        self.learning: DecisionLearningLog | None = None
        self.stop_requested: Callable[[], bool] = lambda: False

    def _web_write_authorized(self, actor: str) -> bool:
        return self.review.web_authorizer is not None and self.review.web_authorizer(actor)

    @property
    def relevance_handler(self) -> RelevanceHandler | None:
        return self.relevance.handler

    @relevance_handler.setter
    def relevance_handler(self, value: RelevanceHandler | None) -> None:
        self.relevance.handler = value

    def send_relevance(
        self, dialog: RelevanceDialog, sender: str, subject: str
    ) -> None:
        """Queue a relevance question behind a possibly open question."""
        with self.lock:
            entry_id = self.outbox.enqueue_relevance(dialog, sender, subject)
        self.outbox.flush(raise_for=entry_id)

    def persist(self, proposal: Proposal) -> None:
        """Compatibility port; persistence itself belongs to the repository."""
        self.repository.save_revision(proposal)
        if proposal.status == ProposalStatus.CREATED:
            self.ledger.book_created(proposal)

    def send(self, chat_id: int, text: str) -> None:
        with self.lock:
            if chat_id != self.chat_id:
                raise PermissionError(
                    "Nachrichten dürfen nur an den konfigurierten Chat gesendet werden"
                )
            entry_id = self.outbox.enqueue_message(text)
        self.outbox.flush(raise_for=entry_id)

    def send_proposal(self, proposal: Proposal) -> None:
        """Queue a new proposal; revisions are delivered directly instead."""
        with self.lock:
            entry_id = self.delivery.enqueue(proposal, flush=False)
        self.outbox.flush(raise_for=entry_id)
        from .series import offer_confirmation
        offer_confirmation(self, proposal)

    def flush_outbox(self) -> None:
        """Send held messages whose preceding question has been resolved."""
        self.outbox.flush()

    def awaiting_decision(self) -> bool:
        """Return whether processing must wait for an explicit Telegram answer.

        Only authoritative proposal records are inspected; immutable version
        snapshots must not keep the application paused after a decision.
        """
        if self._open_relevance_dialogs():
            return True
        for name in self.store.names(state_names.PROPOSAL_PREFIX):
            if "-v" in name:
                continue
            proposal = self.store.load_model(name, Proposal)
            if isinstance(proposal, Proposal) and proposal.status in {
                ProposalStatus.PENDING_CONFIRMATION,
                ProposalStatus.NEEDS_CLARIFICATION,
            }:
                if revision_paused(self.store, proposal):
                    continue
                return True
        return False

    def show_open_decisions(self) -> None:
        """Redisplay at startup: the current decision, held-back ones only as a count."""
        from .commands import TelegramCommands

        TelegramCommands(self.store, self.repository, self.presenter,
                         self.telegram, self.chat_id, self.relevance,
                         self.outbox, self.web_logout).overview(interactive=True, compact=True)

    def processing_blocked(self) -> bool:
        """Return whether an answered revision needs an operator restart."""
        return any(
            isinstance(
                state := self.store.load_model(name, ProposalClarificationState),
                ProposalClarificationState,
            )
            and state.question_status == QuestionStatus.ANSWERED
            and state.proposal_revision_status == ProposalRevisionStatus.PAUSED
            for name in self.store.names(state_names.CLARIFICATION_PREFIX)
        )

    def awaiting_relevance_decision(self) -> bool:
        """Wait globally only for relevance questions already sent or uncertain."""
        queued = self.outbox.queued_relevance()
        return any((dialog.mail_id, dialog.version) not in queued
                   for dialog in self._open_relevance_dialogs())

    def _processed_offset(self) -> int:
        offset_state = self.store.load_model(
            "telegram-offset", TelegramOffset, TelegramOffset()
        )
        assert isinstance(offset_state, TelegramOffset)
        return max(offset_state.offset, self.relevance.durable_offset())

    def receive_offset(self) -> int:
        """Where a receiver thread continues: after processed and stored updates."""
        stored = self.inbox.next_offset() if self.inbox is not None else 0
        return max(self._processed_offset(), stored)

    def poll_once(self, timeout: int | None = None) -> None:
        """Process new updates: from the inbox if a receiver fills it, else from Telegram.

        With an inbox this never waits; *timeout* only applies to direct polling.
        """
        # Only the operator executes decisions. Producers lock only durable enqueue;
        # no shared dialog/store lock spans a network, LLM or provider call.
        if self.stop_requested():
            return
        if self.commands is not None:
            for entry_id, accept_ms, repeated in self.commands.take_acceptances():
                self.logger.event("INFO", "web", "command_submitted", command_id=entry_id,
                                  repeated=repeated, accept_ms=accept_ms, store_lock_wait_ms=0.0)
            self.commands.drain()
            while self.commands.incoming.problems:
                message = self.commands.incoming.problems.pop(0)
                self.logger.event("ERROR", "review", "command_input_damaged", message=message)
        if self.commands is not None and not self._commands_recovered:
            # Reconcile interrupted commands before admitting any new execution.
            self.commands.recover(self.review.reconcile, self.review.resume_admitted)
            self._commands_recovered = True
        self._process_commands()
        self.write_executor.resume()
        self.revisions.resume()
        offset = self._processed_offset()
        if self.inbox is not None:
            now = time.time()
            entries = []
            for entry in self.inbox.pending():
                if not entry.ready(now):
                    break  # keep the order: later input waits for this retry
                entries.append(entry)
            updates = [entry.update for entry in entries]
            acknowledged = {entry.update_id for entry in entries if entry.acknowledged}
        else:
            updates = self.telegram.poll(offset, timeout=timeout)
            acknowledged = set()
        self.logger.event("DEBUG", "telegram.dialog", "updates_received", offset=offset, count=len(updates))
        self.updates.process(updates, acknowledged, offset)
        # New commands may have arrived during the resumption or Telegram input.
        self._process_commands()
        self.outbox.flush()

    def _process_commands(self) -> None:
        """Execute queued web commands in arrival order."""
        if self.commands is None:
            return
        self.commands.drain()
        for entry in self.commands.queued():
            if self.stop_requested():
                break
            command = entry.command
            with measure_lock_waits() as waits:
                with measured_lock(self.lock, "dialog"):
                    self.commands.start(entry.id)
                queue_wait = (self.commands.clock() - entry.received_at).total_seconds() * 1000
                started = time.perf_counter()
                try:
                    result = self.review.execute(command)
                except Exception as exc:
                    self.logger.event("ERROR", "review", "command_failed", command_id=entry.id,
                                      source=command.source.value, kind=command.kind.value,
                                      error_class=type(exc).__name__)
                    result = ReviewResult(status=ResultStatus.FAILED,
                                          message="Die Aktion ist fehlgeschlagen; Details stehen im Protokoll.")
                timings = {**waits, "queue_wait_ms": round(queue_wait, 3),
                           "latency_ms": round((self.commands.clock() - entry.received_at).total_seconds() * 1000, 3),
                           "execution_ms": round((time.perf_counter() - started) * 1000, 3)}
                self.commands.finish(entry.id, result, timings=timings)
            self.logger.event("INFO", "review", "command_finished", command_id=entry.id,
                              source=command.source.value, kind=command.kind.value,
                              status=result.status.value,
                              **timings)
            # Writes, revisions and clarifications report in Telegram by
            # themselves; a rejection or relevance decision is mirrored here.
            if (self.outbox.background is None and command.source == CommandSource.WEB
                    and result.status == ResultStatus.DONE
                    and command.kind in {CommandKind.REJECT, CommandKind.ALREADY_DONE, CommandKind.RELEVANCE}):
                try:
                    self.telegram.send(self.chat_id, f"🌐 Im Web: {result.message}")
                except Exception as exc:
                    self.logger.event("ERROR", "review", "web_notice_failed",
                                      error_class=type(exc).__name__)

    def _handle(self, update: TelegramUpdate, acknowledged: bool = False) -> None:
        self.updates.handle(update, acknowledged)

    def _open_relevance_dialogs(self) -> list[RelevanceDialog]:
        return self.relevance.open()

    def decide_relevance(
        self, decision: RelevanceDecision, offset: int, notify: bool = False
    ) -> str | None:
        return self.relevance.decide(decision, offset, notify)
