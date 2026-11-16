"""7.1 (D5): prepared answers – the demo replays what the real answer path produced, without a model.

``answers.json`` holds the recorded calls of the revision service from the generation run. A recorded
answer to the same question of the same proposal version gets exactly the recorded result; any other
answer is declined with a note on the demo limit instead of calling a model or inventing a result.
"""
from __future__ import annotations

import json
from datetime import date as calendar_date
from pathlib import Path
from typing import Any

from ..domain.extraction import TelegramAnswerInterpretation, TelegramClarification
from ..domain.proposal import Proposal
from ..domain.revision_errors import TechnicalRevisionError

DEMO_ONLY = ("In der Demo werden nur die vorbereiteten Beispielantworten ausgewertet; "
             "eine freie Antwort bräuchte eine KI-Auswertung.")
CALL = "demo"

Key = tuple[str, str, int, str, str]


def _key(record: dict[str, Any]) -> Key:
    mail_id, proposal_id, version = record["proposal"]
    question, answer = record["arguments"][:2]
    return mail_id, proposal_id, int(version), question, answer


class DemoRevisions:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self.recorded: dict[tuple[str, Key], dict[str, Any]] = {
            (record["method"], _key(record)): record["result"] for record in records if record["proposal"]}

    @classmethod
    def load(cls, dataset: Path) -> DemoRevisions:
        """Read the answers of a dataset that ``demo_dataset.verify`` has already checked."""
        return cls(json.loads((dataset / "answers.json").read_text(encoding="utf-8")))

    def prepared(self) -> dict[tuple[str, str, int], str]:
        """The answer offered for each proposal version: the first recorded one."""
        offered: dict[tuple[str, str, int], str] = {}
        for method, (mail_id, proposal_id, version, _question, answer) in self.recorded:
            if method == "interpret_telegram_answer":
                offered.setdefault((mail_id, proposal_id, version), answer)
        return offered

    def _lookup(self, method: str, proposal: Proposal, question: str, answer: str) -> dict[str, Any] | None:
        return self.recorded.get((method, (proposal.source_mail_id, proposal.id, proposal.version, question, answer)))

    def interpret_telegram_answer(self, proposal: Proposal, question: str,
                                  authorized_answer: str) -> tuple[str, TelegramAnswerInterpretation]:
        result = self._lookup("interpret_telegram_answer", proposal, question, authorized_answer)
        if result is None:
            return CALL, TelegramAnswerInterpretation(usable=False, reason=DEMO_ONLY)
        return CALL, TelegramAnswerInterpretation.model_validate(result)

    def clarify_telegram_answer(self, question: str, authorized_answer: str, reason: str, *,
                                current_date: calendar_date | None = None) -> tuple[str, TelegramClarification]:
        return CALL, TelegramClarification(message=f"{reason} Bitte die vorbereitete Beispielantwort verwenden.")

    def revise_proposal(self, proposal: Proposal, question: str, authorized_answer: str) -> tuple[str, Proposal]:
        result = self._lookup("revise_proposal", proposal, question, authorized_answer)
        if result is None:
            raise TechnicalRevisionError(DEMO_ONLY)
        return CALL, Proposal.model_validate(result)
