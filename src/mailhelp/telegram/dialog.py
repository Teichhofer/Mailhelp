"""Telegram dialog orchestration."""

from __future__ import annotations

import traceback
from typing import Any

from pydantic import ValidationError

from ..integrations import ExternalWriter
from ..models import Proposal, ProposalStatus, RelevanceDialog, TelegramOffset
from ..storage import JsonStore

from .authorization import AuthorizedUpdateValidator, UpdateValidation
from .callbacks import Decision, RelevanceDecision, validate_callback_markup
from .client import TelegramTransport, _validation_path
from .ledger import ActionLedgerPort, ActionLedgerService
from .models import TelegramUpdate
from .persistence import proposal_version_name
from .relevance import RelevanceDialogProcessor, RelevanceHandler
from .revisions import (
    EventLogger,
    ProposalRevisions,
    ProposalRevisionProcessor,
    ProposalRevisionService,
)
from .writes import ConfirmedWriteExecutor, WriteExecution


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
    ):
        from .delivery import ProposalDeliveryService
        from .decisions import ProposalDecisionService
        from .persistence import ProposalRepository
        from .presenter import ProposalPresenter

        self.store, self.telegram, self.user_id, self.chat_id, self.logger = (
            store,
            telegram,
            user_id,
            chat_id,
            logger,
        )
        self.writers, self.test_mode = writers or {}, test_mode
        self.configured_timezone = configured_timezone
        self.revision_service = revision_service
        self.interpretation_attempts = interpretation_attempts
        self.interpretation_backoff_seconds = interpretation_backoff_seconds
        self.revision_attempts = revision_attempts
        self.revision_backoff_seconds = revision_backoff_seconds
        self.validator: UpdateValidation = AuthorizedUpdateValidator(
            store, user_id, chat_id
        )
        self.relevance = RelevanceDialogProcessor(store, telegram, chat_id)
        self.ledger: ActionLedgerPort = ActionLedgerService(store)
        self.repository = ProposalRepository(store)
        self.presenter = ProposalPresenter(
            configured_timezone, lambda decision: decision.encode(store)
        )
        self.delivery = ProposalDeliveryService(
            self.repository, self.presenter, telegram, chat_id
        )
        self.write_executor: WriteExecution = ConfirmedWriteExecutor(
            store, self.writers, self, telegram, chat_id, test_mode, self.ledger
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
        )
        self.revisions: ProposalRevisions = ProposalRevisionProcessor(
            store,
            revision_service,
            self,
            telegram,
            chat_id,
            logger,
            configured_timezone,
            interpretation_attempts=interpretation_attempts,
            interpretation_backoff_seconds=interpretation_backoff_seconds,
            revision_attempts=revision_attempts,
            revision_backoff_seconds=revision_backoff_seconds,
        )

    @property
    def relevance_handler(self) -> RelevanceHandler | None:
        return self.relevance.handler

    @relevance_handler.setter
    def relevance_handler(self, value: RelevanceHandler | None) -> None:
        self.relevance.handler = value

    def send_relevance(
        self, dialog: RelevanceDialog, sender: str, subject: str
    ) -> None:
        buttons = [
            [
                {
                    "text": "Relevant",
                    "callback_data": RelevanceDecision(
                        mail_id=dialog.mail_id,
                        version=dialog.version,
                        decision="relevant",
                    ).encode(),
                },
                {
                    "text": "Irrelevant",
                    "callback_data": RelevanceDecision(
                        mail_id=dialog.mail_id,
                        version=dialog.version,
                        decision="irrelevant",
                    ).encode(),
                },
            ]
        ]
        text = "\n".join(
            [
                f"Absender: {sender}",
                f"Betreff: {subject}",
                "Relevanz bitte bestätigen:",
            ]
        )
        validate_callback_markup({"inline_keyboard": buttons})
        self.telegram.send(self.chat_id, text, {"inline_keyboard": buttons})

    @staticmethod
    def _version_name(mail_id: str, proposal_id: str, version: int) -> str:
        """Deprecated compatibility alias for the repository naming rule."""
        return proposal_version_name(mail_id, proposal_id, version)

    def persist(self, proposal: Proposal) -> None:
        """Compatibility port; persistence itself belongs to the repository."""
        self.repository.save_revision(proposal)
        if proposal.status == ProposalStatus.CREATED:
            self._book_created(proposal)

    def _book_created(self, proposal: Proposal) -> None:
        self.ledger.book_created(proposal)

    def send(self, chat_id: int, text: str) -> None:
        if chat_id != self.chat_id:
            raise PermissionError(
                "Nachrichten dürfen nur an den konfigurierten Chat gesendet werden"
            )
        self.telegram.send(chat_id, text)

    def send_proposal(self, proposal: Proposal) -> None:
        """Compatibility port delegating delivery to its dedicated service."""
        self.delivery.deliver(proposal)

    def awaiting_decision(self) -> bool:
        """Return whether processing must wait for an explicit Telegram answer.

        Only authoritative proposal records are inspected; immutable version
        snapshots must not keep the application paused after a decision.
        """
        if self._open_relevance_dialogs():
            return True
        names = getattr(self.store, "names", None)
        if names is None:
            return False
        for name in names("proposal-"):
            if "-v" in name:
                continue
            proposal = self.store.load_model(name, Proposal)
            if isinstance(proposal, Proposal) and proposal.status in {
                ProposalStatus.PENDING_CONFIRMATION,
                ProposalStatus.NEEDS_CLARIFICATION,
            }:
                return True
        return False

    def awaiting_relevance_decision(self) -> bool:
        """Return whether an unfinished mail analysis needs a relevance answer."""
        return bool(self._open_relevance_dialogs())

    def poll_once(self, timeout: int | None = None) -> None:
        self.write_executor.resume()
        self.revisions.resume()
        offset_state = self.store.load_model(
            "telegram-offset", TelegramOffset, TelegramOffset()
        )
        assert isinstance(offset_state, TelegramOffset)
        offset = max(offset_state.offset, self._durable_dialog_offset())
        updates = self.telegram.poll(offset, timeout=timeout)
        self.logger.event(
            "DEBUG",
            "telegram.dialog",
            "updates_received",
            offset=offset,
            count=len(updates),
        )
        for raw in updates:
            raw_id = raw.get("update_id") if isinstance(raw, dict) else None
            if (
                not isinstance(raw_id, int)
                or isinstance(raw_id, bool)
                or raw_id < offset
            ):
                self.logger.event(
                    "WARNING",
                    "telegram.dialog",
                    "invalid_update",
                    update_id=raw_id
                    if isinstance(raw_id, int) and not isinstance(raw_id, bool)
                    else None,
                    reason="missing_or_stale_update_id",
                )
                if (
                    isinstance(raw_id, int)
                    and not isinstance(raw_id, bool)
                    and raw_id < offset
                ):
                    self._reject_duplicate_relevance(raw)
                continue
            try:
                update = TelegramUpdate.model_validate(raw)
                update_kind = (
                    "callback_query" if update.callback_query is not None else "message"
                )
                self.logger.event(
                    "INFO",
                    "telegram.dialog",
                    "update_processing",
                    update_id=raw_id,
                    update_kind=update_kind,
                )
                self._handle(update)
            except ValidationError as exc:
                self.logger.event(
                    "WARNING",
                    "telegram.dialog",
                    "invalid_update",
                    update_id=raw_id,
                    reason="schema_validation",
                    validation_path=_validation_path(exc),
                )
                self.telegram.send(
                    self.chat_id,
                    "Telegram-Eingabe ist syntaktisch ungültig und wurde verworfen.",
                )
            except Exception as exc:
                # Do not acknowledge an update that failed operationally.  It
                # remains queued and can be retried after a transient provider,
                # network, or persistence problem has recovered.
                self.logger.event(
                    "ERROR",
                    "telegram.dialog",
                    "update_processing_failed",
                    update_id=raw_id,
                    error_class=type(exc).__name__,
                )
                raise
            offset = raw_id + 1
            self.store.save(
                "telegram-offset", TelegramOffset(offset=offset).model_dump()
            )
            self.logger.event(
                "INFO",
                "telegram.dialog",
                "update_processed",
                update_id=raw_id,
                next_offset=offset,
            )

    def _reject_duplicate_relevance(self, raw: dict[str, Any]) -> None:
        """Make a replayed relevance answer visible without trusting raw fields."""
        try:
            update = TelegramUpdate.model_validate(raw)
        except ValidationError:
            return
        callback = update.callback_query
        if (
            callback is not None
            and callback.data.startswith("relevance:")
            and self._authorized(callback.sender.id, callback.message.chat.id)
        ):
            self.telegram.answer_callback(
                callback.id, "Diese Relevanzantwort wurde bereits verarbeitet."
            )
            return
        message = update.message
        if (
            message is not None
            and message.text.strip().lower() in {"relevant", "irrelevant"}
            and self._authorized(message.sender.id, message.chat.id)
        ):
            self.telegram.send(
                self.chat_id, "Diese Relevanzantwort wurde bereits verarbeitet."
            )

    def _handle(self, update: TelegramUpdate) -> None:
        if update.callback_query is not None:
            callback = update.callback_query
            # Stop Telegram's loading indicator before potentially slow state,
            # LLM, or external-service work begins.
            self.telegram.answer_callback(callback.id, "Aktion wird verarbeitet …")
            if not self._authorized(callback.sender.id, callback.message.chat.id):
                self.logger.event(
                    "WARNING",
                    "telegram.dialog",
                    "unauthorized_update",
                    update_id=update.update_id,
                    update_kind="callback_query",
                    user_id=callback.sender.id,
                    chat_id=callback.message.chat.id,
                )
                self.telegram.send(self.chat_id, "❌ Nicht autorisierte Aktion.")
                return
            try:
                if callback.data.startswith("relevance:"):
                    try:
                        relevance = self.validator.relevance_decision(callback.data)
                    except (ValueError, ValidationError):
                        self.telegram.send(
                            self.chat_id,
                            "❌ Relevanzantwort ist syntaktisch ungültig; bitte erneut versuchen.",
                        )
                        return
                    confirmation = self._decide_relevance(
                        relevance, update.update_id + 1
                    )
                else:
                    try:
                        decision = self.validator.decision(callback.data)
                    except (ValueError, ValidationError):
                        self.telegram.send(
                            self.chat_id,
                            "❌ Aktion ist syntaktisch ungültig; bitte erneut versuchen.",
                        )
                        return
                    confirmation = self.decision_service.decide(
                        decision, callback.sender.id, callback.message.chat.id
                    )
            except Exception as exc:
                self.logger.event(
                    "ERROR",
                    "telegram.dialog",
                    "callback_processing_failed",
                    update_id=update.update_id,
                    error=exc,
                    stacktrace=traceback.format_exc(),
                )
                self.telegram.send(
                    self.chat_id,
                    "❌ Aktion konnte nicht verarbeitet werden. Bitte erneut versuchen.",
                )
                return
            assert confirmation is not None
            self.telegram.remove_inline_keyboard(
                callback.message.chat.id, callback.message.message_id
            )
            self.telegram.send(self.chat_id, confirmation)
            return
        message = update.message
        assert message is not None
        if not self._authorized(message.sender.id, message.chat.id):
            self.logger.event(
                "WARNING",
                "telegram.dialog",
                "unauthorized_update",
                update_id=update.update_id,
                update_kind="message",
                user_id=message.sender.id,
                chat_id=message.chat.id,
            )
            return
        normalized = message.text.strip().lower()
        if normalized in {"relevant", "irrelevant"}:
            dialogs = self._open_relevance_dialogs()
            if len(dialogs) != 1:
                self.telegram.send(
                    self.chat_id,
                    "Freitext ist nicht eindeutig zuordenbar; bitte die Schaltfläche der gewünschten Mail verwenden.",
                )
                return
            dialog = dialogs[0]
            self._decide_relevance(
                RelevanceDecision(
                    mail_id=dialog.mail_id, version=dialog.version, decision=normalized
                ),
                update.update_id + 1,
                notify=True,
            )
            return
        self.revisions.answer(message.text)

    def _open_relevance_dialogs(self) -> list[RelevanceDialog]:
        return self.relevance.open()

    def _durable_dialog_offset(self) -> int:
        return self.relevance.durable_offset()

    def _decide_relevance(
        self, decision: RelevanceDecision, offset: int, notify: bool = False
    ) -> str | None:
        return self.relevance.decide(decision, offset, notify)

    def _authorized(self, user_id: int, chat_id: int) -> bool:
        return self.validator.authorized(user_id, chat_id)

    def _decide(self, decision: Decision) -> str:
        """Compatibility entry point for already-authorized internal callers."""
        return self.decision_service.decide(decision, self.user_id, self.chat_id)
