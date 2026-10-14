"""Pure rendering of validated proposals for Telegram."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..domain.proposal_sources import ProposalReference
from ..external.contracts import proposal_is_writable
from ..models import Proposal, ProposalKind
from .callbacks import Decision, DecisionAction, validate_callback_markup
from .formatting import format_proposal, numbered_message_parts, revision_summary


@dataclass(frozen=True)
class ProposalPresentation:
    parts: tuple[str, ...]
    reply_markup: dict[str, object]


class ProposalPresenter:
    """Create message parts and controls without persistence or networking."""

    def __init__(
        self,
        configured_timezone: str,
        encode: Callable[[Decision], str],
        test_mode: bool = False,
    ):
        self.configured_timezone = configured_timezone
        self.encode = encode
        self.test_mode = test_mode

    def present(
        self, proposal: Proposal, sender: str = "—", subject: str = "—",
        previous: Proposal | None = None,
        additional: Proposal | None = None,
    ) -> ProposalPresentation:
        parts = tuple(
            numbered_message_parts(
                sender,
                subject,
                ((revision_summary(previous, proposal, self.configured_timezone) + "\n\n")
                 if previous is not None else "")
                + format_proposal(proposal, self.configured_timezone, self.test_mode)
                + (f"\n\nUngeprüfter Zusatz: {additional.title}\n{additional.evidence}" if additional else ""),
            )
        )

        def button(text: str, action: DecisionAction) -> dict[str, str]:
            decision = Decision(
                mail_id=proposal.source_mail_id,
                proposal_id=proposal.id,
                version=proposal.version,
                action=action,
            )
            return {"text": text, "callback_data": self.encode(decision)}

        if not proposal_is_writable(proposal):
            buttons = [
                [
                    button("Manuell prüfen", DecisionAction.EDIT),
                    button("Verwerfen", DecisionAction.REJECT),
                ]
            ]
        elif proposal.open_questions:
            buttons = [
                [
                    button("Klären", DecisionAction.EDIT),
                    button("Verwerfen", DecisionAction.REJECT),
                ]
            ]
        else:
            confirm = button(
                (
                    "Simulieren"
                    if self.test_mode
                    else ("Termin absagen" if proposal.is_cancellation else "Termin aktualisieren")
                    if proposal.target_event_id is not None
                    else "Im Kalender anlegen" if proposal.kind == ProposalKind.EVENT
                    else "Als Aufgabe anlegen"
                ),
                DecisionAction.CONFIRM,
            )
            reject = button("Verwerfen", DecisionAction.REJECT)
            buttons = [[confirm, button("Ändern", DecisionAction.EDIT), reject]]
        markup: dict[str, object] = {"inline_keyboard": buttons}
        if additional is not None:
            choices = []
            for label, action in (("Zusatz zuordnen", DecisionAction.MERGE_SOURCE),
                                  ("Separat behalten", DecisionAction.SEPARATE_SOURCE)):
                decision = Decision(mail_id=proposal.source_mail_id, proposal_id=proposal.id,
                    version=proposal.version, action=action,
                    additional_ref=ProposalReference(mail_id=additional.source_mail_id, proposal_id=additional.id),
                    additional_version=additional.version)
                choices.append({"text": label, "callback_data": self.encode(decision)})
            buttons.insert(0, choices)
        validate_callback_markup(markup)
        return ProposalPresentation(parts=parts, reply_markup=markup)


__all__ = ["ProposalPresentation", "ProposalPresenter"]
