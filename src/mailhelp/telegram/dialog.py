"""Telegram dialog orchestration."""

from __future__ import annotations

import time
from collections.abc import Callable

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
from ..review.results import ResultStatus, ReviewResult
from ..storage import JsonStore
from .authorization import AuthorizedUpdateValidator, UpdateValidation
from .callbacks import RelevanceDecision
from .client import TelegramTransport
from .models import TelegramUpdate
from .outbox import TelegramOutbox, revision_paused
from .receiver import TelegramInbox
from .relevance import RelevanceDialogProcessor, RelevanceHandler
from .revisions import (
    EventLogger,
    ProposalRevisionProcessor,
    ProposalRevisions,
    ProposalRevisionService,
)
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
        # Web commands, executed here in the main thread like Telegram updates.
        self.commands = commands
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
        self.write_executor: WriteExecution = ConfirmedWriteExecutor(
            store,
            self.writers,
            self,
            telegram,
            chat_id,
            test_mode,
            self.ledger,
            configured_timezone,
        )
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
        self.stop_requested = lambda: False

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
        entry_id = self.outbox.enqueue_relevance(dialog, sender, subject)
        self.outbox.flush(raise_for=entry_id)

    def persist(self, proposal: Proposal) -> None:
        """Compatibility port; persistence itself belongs to the repository."""
        self.repository.save_revision(proposal)
        if proposal.status == ProposalStatus.CREATED:
            self.ledger.book_created(proposal)

    def send(self, chat_id: int, text: str) -> None:
        if chat_id != self.chat_id:
            raise PermissionError(
                "Nachrichten dürfen nur an den konfigurierten Chat gesendet werden"
            )
        entry_id = self.outbox.enqueue_message(text)
        self.outbox.flush(raise_for=entry_id)

    def send_proposal(self, proposal: Proposal) -> None:
        """Queue a new proposal; revisions are delivered directly instead."""
        self.delivery.enqueue(proposal)

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
        if self.stop_requested():
            return
        self.write_executor.resume()
        self.revisions.resume()
        if self.commands is not None and not self._commands_recovered:
            # Commands interrupted by a restart are reconciled, never repeated.
            self._commands_recovered = True
            self.commands.recover(self.review.reconcile)
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
        self.logger.event(
            "DEBUG",
            "telegram.dialog",
            "updates_received",
            offset=offset,
            count=len(updates),
        )
        self.updates.process(updates, acknowledged, offset)
        self._process_commands()
        # Answers above may have resolved the question that held messages back.
        self.outbox.flush()

    def _process_commands(self) -> None:
        """Execute queued web commands in arrival order."""
        if self.commands is None:
            return
        for entry in self.commands.queued():
            if self.stop_requested():
                break
            command = entry.command
            self.commands.start(entry.id)
            try:
                result = self.review.execute(command)
            except Exception as exc:
                self.logger.event("ERROR", "review", "command_failed", command_id=entry.id,
                                  source=command.source.value, kind=command.kind.value,
                                  error_class=type(exc).__name__)
                result = ReviewResult(status=ResultStatus.FAILED,
                                      message="Die Aktion ist fehlgeschlagen; Details stehen im Protokoll.")
            self.commands.finish(entry.id, result)
            self.logger.event("INFO", "review", "command_finished", command_id=entry.id,
                              source=command.source.value, kind=command.kind.value,
                              status=result.status.value)
            # Writes, revisions and clarifications report in Telegram by
            # themselves; a rejection or relevance decision is mirrored here.
            if (self.outbox.background is None and command.source == CommandSource.WEB
                    and result.status == ResultStatus.DONE
                    and command.kind in {CommandKind.REJECT, CommandKind.RELEVANCE}):
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
