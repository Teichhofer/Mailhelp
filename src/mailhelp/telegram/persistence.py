"""Proposal persistence boundary used by Telegram dialogs."""

from ._core import ProposalPersistence


def proposal_name(mail_id: str, proposal_id: str) -> str:
    return f"proposal-{mail_id}-{proposal_id}"


def proposal_version_name(mail_id: str, proposal_id: str, version: int) -> str:
    return f"proposal-{mail_id}-{proposal_id}-v{version}"


def clarification_name(mail_id: str, proposal_id: str, version: int) -> str:
    return f"clarification-{mail_id}-{proposal_id}-v{version}"


__all__ = [
    "ProposalPersistence", "clarification_name", "proposal_name",
    "proposal_version_name",
]
