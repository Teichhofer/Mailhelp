"""Pure rendering of validated proposals for Telegram."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..integrations import proposal_is_writable
from ..models import Proposal, ProposalKind
from ._core import (
    Decision, DecisionAction, format_proposal, numbered_message_parts,
    validate_callback_markup,
)


@dataclass(frozen=True)
class ProposalPresentation:
    parts: tuple[str, ...]
    reply_markup: dict[str, object]


class ProposalPresenter:
    """Create message parts and controls without persistence or networking."""

    def __init__(self, configured_timezone: str,
                 encode: Callable[[Decision], str]):
        self.configured_timezone = configured_timezone
        self.encode = encode

    def present(self, proposal: Proposal, sender: str = "—",
                subject: str = "—") -> ProposalPresentation:
        parts = tuple(numbered_message_parts(
            sender, subject, format_proposal(proposal, self.configured_timezone)))

        def button(text: str, action: DecisionAction) -> dict[str, str]:
            decision = Decision(
                mail_id=proposal.source_mail_id, proposal_id=proposal.id,
                version=proposal.version, action=action)
            return {"text": text, "callback_data": self.encode(decision)}

        if not proposal_is_writable(proposal):
            buttons = [[button("Manuell prüfen", DecisionAction.EDIT),
                        button("Verwerfen", DecisionAction.REJECT)]]
        elif proposal.open_questions:
            buttons = [[button("Klären", DecisionAction.EDIT),
                        button("Verwerfen", DecisionAction.REJECT)]]
        else:
            confirm = button(
                "Anlegen" if proposal.kind == ProposalKind.EVENT else "Bestätigen",
                DecisionAction.CONFIRM)
            reject = button("Verwerfen", DecisionAction.REJECT)
            buttons = ([[confirm, reject]] if proposal.kind == ProposalKind.EVENT
                       else [[confirm, button("Ändern", DecisionAction.EDIT), reject]])
        markup: dict[str, object] = {"inline_keyboard": buttons}
        validate_callback_markup(markup)
        return ProposalPresentation(parts=parts, reply_markup=markup)


__all__ = ["ProposalPresentation", "ProposalPresenter"]
