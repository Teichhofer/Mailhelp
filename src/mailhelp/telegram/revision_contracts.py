"""Ports for answer interpretation, revision and safe event logging."""
from __future__ import annotations

from datetime import date as calendar_date
from typing import Protocol

from ..domain.extraction import TelegramAnswerInterpretation, TelegramClarification
from ..domain.proposal import Proposal
from ..logging import EventLogger


class ProposalRevisionService(Protocol):
    def interpret_telegram_answer(
        self, proposal: Proposal, question: str, authorized_answer: str
    ) -> tuple[str, TelegramAnswerInterpretation]: ...
    def clarify_telegram_answer(
        self,
        question: str,
        authorized_answer: str,
        reason: str,
        *,
        current_date: calendar_date | None = None,
    ) -> tuple[str, TelegramClarification]: ...
    def revise_proposal(
        self, proposal: Proposal, question: str, authorized_answer: str
    ) -> tuple[str, Proposal]: ...


__all__ = ["EventLogger", "ProposalRevisionService"]

