"""Validated successor construction, independent of persistence and delivery."""
from __future__ import annotations

from ..analysis import validate_revision_successor
from ..models import Proposal
from .revision_contracts import ProposalRevisionService
from .temporal import deterministic_classification_revision, deterministic_temporal_revision


def build_revision_successor(original: Proposal, question: str, normalized_answer: str,
                             configured_timezone: str,
                             revision_service: ProposalRevisionService) -> tuple[Proposal, bool]:
    candidate = deterministic_classification_revision(
        original, question, normalized_answer
    )
    if candidate is None:
        candidate = deterministic_temporal_revision(
            original,
            question,
            normalized_answer,
            configured_timezone,
        )
    deterministic = candidate is not None
    if candidate is None:
        _, candidate = revision_service.revise_proposal(
            original, question, normalized_answer
        )
    revised = validate_revision_successor(original, candidate)
    return revised, deterministic
