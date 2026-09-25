"""Authorization boundary for untrusted Telegram updates."""

from __future__ import annotations

from typing import Protocol


from ..storage import JsonStore

from .callbacks import Decision, RelevanceDecision


class UpdateValidation(Protocol):
    def authorized(self, user_id: int, chat_id: int) -> bool: ...
    def decision(self, value: str) -> Decision: ...
    def relevance_decision(self, value: str) -> RelevanceDecision: ...


class AuthorizedUpdateValidator:
    """Validate Telegram identities and decode untrusted callback payloads."""

    def __init__(self, store: JsonStore, user_id: int, chat_id: int):
        self.store, self.user_id, self.chat_id = store, user_id, chat_id

    def authorized(self, user_id: int, chat_id: int) -> bool:
        return (user_id, chat_id) == (self.user_id, self.chat_id)

    def decision(self, value: str) -> Decision:
        return Decision.parse(value, self.store)

    @staticmethod
    def relevance_decision(value: str) -> RelevanceDecision:
        return RelevanceDecision.parse(value)
