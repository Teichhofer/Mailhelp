"""Relevance-dialog processing."""

from __future__ import annotations

from typing import Protocol

from ..models import MailState, RelevanceDialog, RelevanceDialogStatus
from ..state_names import MAIL_PREFIX, is_mail_state
from ..storage import CorruptState, JsonStore
from .callbacks import RelevanceDecision
from .client import TelegramTransport


def _dialog(state: MailState) -> RelevanceDialog | None:
    return state.relevance_dialog


class RelevanceHandler(Protocol):
    def resolve_relevance(
        self, mail_id: str, version: int, decision: str, telegram_offset: int
    ) -> MailState: ...
    def resume_mail(self, state: MailState) -> object: ...


class RelevanceDialogs(Protocol):
    def open(self) -> list[RelevanceDialog]: ...
    def durable_offset(self) -> int: ...
    def decide(
        self, decision: RelevanceDecision, offset: int, notify: bool
    ) -> str | None: ...


class RelevanceDialogProcessor:
    """Own relevance lookup, replay offsets, and relevance resolution."""

    def __init__(self, store: JsonStore, telegram: TelegramTransport, chat_id: int):
        self.store, self.telegram, self.chat_id = store, telegram, chat_id
        self.handler: RelevanceHandler | None = None

    def all(self) -> list[RelevanceDialog]:
        """Asked on every operator pass; unchanged mails are not read again (4.4.1)."""
        result = []
        for name, signature in self.store.scan(MAIL_PREFIX).items():
            if not is_mail_state(name):
                continue
            try:
                dialog = self.store.cached(name, MailState, _dialog, signature)
            except CorruptState:
                # Loading isolates and reports the damage, as before the cache.
                state = self.store.load_model(name, MailState)
                dialog = state.relevance_dialog if isinstance(state, MailState) else None
            if dialog is not None:
                result.append(dialog.model_copy())
        return result

    def open(self) -> list[RelevanceDialog]:
        return [
            item for item in self.all() if item.status == RelevanceDialogStatus.OPEN
        ]

    def durable_offset(self) -> int:
        return max((item.telegram_offset or 0 for item in self.all()), default=0)

    def decide(
        self, decision: RelevanceDecision, offset: int, notify: bool = False
    ) -> str | None:
        try:
            if self.handler is None:
                raise ValueError("Relevanzverarbeitung ist nicht verfügbar")
            state = self.handler.resolve_relevance(
                decision.mail_id, decision.version, decision.decision, offset
            )
        except ValueError as exc:
            if notify:
                self.telegram.send(self.chat_id, str(exc))
                return None
            raise
        if decision.decision == "relevant":
            self.handler.resume_mail(state)
        text = f"✅ E-Mail wurde als {decision.decision} eingestuft."
        if notify:
            self.telegram.send(self.chat_id, text)
            return None
        return text
