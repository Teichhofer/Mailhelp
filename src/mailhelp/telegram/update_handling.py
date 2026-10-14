"""Validate and dispatch single Telegram updates for the dialog controller."""
from __future__ import annotations

import traceback
from typing import TYPE_CHECKING, Any, Literal, cast

from pydantic import ValidationError

from ..adapter import PermanentError
from ..models import RelevanceDialog, TelegramOffset
from ..review.commands import CommandKind, CommandSource, ReviewCommand
from ..review.errors import StaleCommand
from .callbacks import DecisionAction, RelevanceDecision, validate_callback_markup
from .client import TelegramTransport, validation_path
from .models import TelegramCallbackQuery, TelegramUpdate

if TYPE_CHECKING:
    from .dialog import TelegramDialogController

# A failing inbox update is retried after 30 s, then 60 s, and dropped after
# the third attempt; a permanent error is dropped at once.  Retrying without
# limit repeated the side effects of the update (e.g. a resent question)
# before every mail.
INBOX_RETRY_SECONDS = 30.0
INBOX_MAX_ATTEMPTS = 3
STALE_BUTTON = ("ℹ️ Bereits entschieden oder geändert (z. B. in der Weboberfläche) – "
                "diese Schaltfläche ist veraltet. Aktueller Stand: /offen")
# Telegram buttons translated into channel-neutral review commands.
_COMMAND_KINDS = {
    DecisionAction.CONFIRM: CommandKind.CONFIRM,
    DecisionAction.CONFIRM_DUPLICATE: CommandKind.CONFIRM_DUPLICATE,
    DecisionAction.EDIT: CommandKind.START_CLARIFICATION,
    DecisionAction.REJECT: CommandKind.REJECT,
}


def send_relevance_question(telegram: TelegramTransport, chat_id: int, dialog: RelevanceDialog,
                            sender: str, subject: str) -> None:
    """Ask whether a mail is relevant, with one button per answer."""
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
    telegram.send(chat_id, text, {"inline_keyboard": buttons})


class TelegramUpdateHandler:
    """Owned by the dialog controller; reads its services through ``o``."""

    def __init__(self, owner: TelegramDialogController):
        self.o = owner

    def process(self, updates: list[Any], acknowledged: set[int], offset: int) -> None:
        """Handle updates in order, persisting the offset after each one."""
        for raw in updates:
            raw_id = raw.get("update_id") if isinstance(raw, dict) else None
            if self._stale(raw, raw_id, offset):
                continue
            assert isinstance(raw_id, int)  # _stale() rejected every other id
            self._process_one(raw, raw_id, acknowledged)
            offset = raw_id + 1
            self.o.store.save(
                "telegram-offset", TelegramOffset(offset=offset).model_dump()
            )
            if self.o.inbox is not None:
                self.o.inbox.remove(raw_id)
            self.o.logger.event(
                "INFO",
                "telegram.dialog",
                "update_processed",
                update_id=raw_id,
                next_offset=offset,
            )

    def _stale(self, raw: Any, raw_id: Any, offset: int) -> bool:
        """Missing or already processed ids are logged and skipped."""
        if isinstance(raw_id, int) and not isinstance(raw_id, bool) and raw_id >= offset:
            return False
        self.o.logger.event(
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
            self.reject_duplicate_relevance(raw)
            if self.o.inbox is not None:
                self.o.inbox.remove(raw_id)
        return True

    def _process_one(self, raw: Any, raw_id: int, acknowledged: set[int]) -> None:
        try:
            update = TelegramUpdate.model_validate(raw)
            update_kind = (
                "callback_query" if update.callback_query is not None else "message"
            )
            self.o.logger.event(
                "INFO",
                "telegram.dialog",
                "update_processing",
                update_id=raw_id,
                update_kind=update_kind,
            )
            if raw_id in acknowledged:
                self.handle(update, acknowledged=True)
            else:
                self.handle(update)
        except ValidationError as exc:
            self.o.logger.event(
                "WARNING",
                "telegram.dialog",
                "invalid_update",
                update_id=raw_id,
                reason="schema_validation",
                validation_path=validation_path(exc),
            )
            self.o.telegram.send(
                self.o.chat_id,
                "Telegram-Eingabe ist syntaktisch ungültig und wurde verworfen.",
            )
        except Exception as exc:
            # Do not acknowledge an update that failed operationally.  It
            # remains queued and can be retried after a transient provider,
            # network, or persistence problem has recovered.
            self.o.logger.event(
                "ERROR",
                "telegram.dialog",
                "update_processing_failed",
                update_id=raw_id,
                error_class=type(exc).__name__,
            )
            if self.o.inbox is None:
                raise
            attempts = self.o.inbox.record_failure(raw_id, INBOX_RETRY_SECONDS)
            if not isinstance(exc, PermanentError) and attempts < INBOX_MAX_ATTEMPTS:
                raise
            self.o.logger.event(
                "ERROR",
                "telegram.dialog",
                "update_abandoned",
                update_id=raw_id,
                attempts=attempts,
                error_class=type(exc).__name__,
            )
            self.o.telegram.send(
                self.o.chat_id,
                "❌ Eine Telegram-Eingabe konnte nicht verarbeitet werden und wurde "
                "verworfen. Bitte /offen öffnen und die Aktion erneut wählen.",
            )

    def handle(self, update: TelegramUpdate, acknowledged: bool = False) -> None:
        if update.callback_query is not None:
            self._callback(update, acknowledged)
            return
        message = update.message
        assert message is not None
        if not self.o.validator.authorized(message.sender.id, message.chat.id):
            self.o.logger.event(
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
        if normalized.startswith("/"):
            from .commands import TelegramCommands

            TelegramCommands(self.o.store, self.o.repository, self.o.presenter,
                             self.o.telegram, self.o.chat_id, self.o.relevance,
                             self.o.outbox, self.o.web_logout, self.o.web_invite).handle(normalized)
            return
        if normalized in {"relevant", "irrelevant"}:
            dialogs = self.o.relevance.open()
            if len(dialogs) != 1:
                self.o.telegram.send(
                    self.o.chat_id,
                    "Freitext ist nicht eindeutig zuordenbar; bitte die Schaltfläche der gewünschten Mail verwenden.",
                )
                return
            dialog = dialogs[0]
            self.o.decide_relevance(
                RelevanceDecision(
                    mail_id=dialog.mail_id, version=dialog.version, decision=normalized
                ),
                update.update_id + 1,
                notify=True,
            )
            return
        self.o.revisions.answer(message.text)

    def _callback(self, update: TelegramUpdate, acknowledged: bool) -> None:
        callback = update.callback_query
        assert callback is not None  # only callback updates are routed here
        # Stop Telegram's loading indicator before potentially slow state,
        # LLM, or external-service work begins, unless the receiver thread
        # already did so when the update arrived.
        if not acknowledged:
            self.o.telegram.answer_callback(callback.id, "Aktion wird verarbeitet …")
        if not self.o.validator.authorized(callback.sender.id, callback.message.chat.id):
            self.o.logger.event(
                "WARNING",
                "telegram.dialog",
                "unauthorized_update",
                update_id=update.update_id,
                update_kind="callback_query",
                user_id=callback.sender.id,
                chat_id=callback.message.chat.id,
            )
            self.o.telegram.send(self.o.chat_id, "❌ Nicht autorisierte Aktion.")
            return
        confirmation = self._confirmation(update, callback)
        if confirmation is None:
            return
        self.o.telegram.remove_inline_keyboard(
            callback.message.chat.id, callback.message.message_id
        )
        if confirmation:
            self.o.telegram.send(self.o.chat_id, confirmation)

    def _confirmation(self, update: TelegramUpdate, callback: TelegramCallbackQuery) -> str | None:
        """The confirmation text of the executed button; ``None`` when already answered."""
        actor = f"telegram:{callback.sender.id}:{callback.message.chat.id}"
        key = f"telegram-update-{update.update_id}"
        try:
            if callback.data.startswith("relevance:"):
                try:
                    relevance = self.o.validator.relevance_decision(callback.data)
                except (ValueError, ValidationError):
                    self.o.telegram.send(
                        self.o.chat_id,
                        "❌ Relevanzantwort ist syntaktisch ungültig; bitte erneut versuchen.",
                    )
                    return None
                confirmation = self.o.review.execute(ReviewCommand(
                    kind=CommandKind.RELEVANCE, source=CommandSource.TELEGRAM,
                    actor=actor, mail_id=relevance.mail_id, version=relevance.version,
                    # The callback pattern only admits these two values.
                    decision=cast(Literal["relevant", "irrelevant"], relevance.decision), idempotency_key=key,
                    replay_offset=update.update_id + 1,
                ), raise_errors=True).message
            else:
                try:
                    decision = self.o.validator.decision(callback.data)
                except (ValueError, ValidationError):
                    self.o.telegram.send(
                        self.o.chat_id,
                        "❌ Aktion ist syntaktisch ungültig; bitte erneut versuchen.",
                    )
                    return None
                association = decision.action in {DecisionAction.MERGE_SOURCE, DecisionAction.SEPARATE_SOURCE}
                extra: dict[str, Any] = {}
                identity = decision.mail_id, decision.proposal_id, decision.version
                if association:
                    assert decision.additional_ref is not None and decision.additional_version is not None
                    identity = (decision.additional_ref.mail_id, decision.additional_ref.proposal_id,
                                decision.additional_version)
                    extra = {"target_ref": {"mail_id": decision.mail_id, "proposal_id": decision.proposal_id},
                             "target_version": decision.version}
                confirmation = self.o.review.execute(ReviewCommand(
                    kind=(CommandKind.MERGE if decision.action == DecisionAction.MERGE_SOURCE else CommandKind.SEPARATE)
                         if association else _COMMAND_KINDS[decision.action], source=CommandSource.TELEGRAM,
                    actor=actor, mail_id=identity[0],
                    proposal_id=identity[1], version=identity[2],
                    idempotency_key=key,
                    **extra,
                ), raise_errors=True).message
        except StaleCommand:
            # Typically decided in the web interface after this card was sent.
            self.o.logger.event("INFO", "telegram.dialog", "stale_button",
                                update_id=update.update_id)
            self.o.telegram.remove_inline_keyboard(
                callback.message.chat.id, callback.message.message_id)
            self.o.telegram.send(self.o.chat_id, STALE_BUTTON)
            return None
        except Exception as exc:
            self.o.logger.event(
                "ERROR",
                "telegram.dialog",
                "callback_processing_failed",
                update_id=update.update_id,
                error=exc,
                stacktrace=traceback.format_exc(),
            )
            self.o.telegram.send(
                self.o.chat_id,
                "❌ Aktion konnte nicht verarbeitet werden. Bitte erneut versuchen.",
            )
            return None
        return confirmation

    def reject_duplicate_relevance(self, raw: dict[str, Any]) -> None:
        """Make a replayed relevance answer visible without trusting raw fields."""
        try:
            update = TelegramUpdate.model_validate(raw)
        except ValidationError:
            return
        callback = update.callback_query
        if (
            callback is not None
            and callback.data.startswith("relevance:")
            and self.o.validator.authorized(callback.sender.id, callback.message.chat.id)
        ):
            self.o.telegram.answer_callback(
                callback.id, "Diese Relevanzantwort wurde bereits verarbeitet."
            )
            return
        message = update.message
        if (
            message is not None
            and message.text.strip().lower() in {"relevant", "irrelevant"}
            and self.o.validator.authorized(message.sender.id, message.chat.id)
        ):
            self.o.telegram.send(
                self.o.chat_id, "Diese Relevanzantwort wurde bereits verarbeitet."
            )
