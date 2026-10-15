"""Validated successor construction, independent of persistence and delivery."""
from __future__ import annotations

from ..analysis import validate_revision_successor
from ..models import Proposal
from ..temporal_answers import deterministic_classification_revision, deterministic_temporal_revision
from .revision_contracts import ProposalRevisionService


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
    return protect_revision(original, revised), deterministic


def protect_revision(original: Proposal, revised: Proposal) -> Proposal:
    changed = [field for field in ("title", "description", "due", "start", "end", "known_temporal_facts",
                                   "location", "video_link", "classification", "responsibility", "certainty")
               if getattr(original, field) != getattr(revised, field)]
    protected = list(dict.fromkeys([*original.protected_fields, *changed]))
    revised = revised.model_copy(update={"protected_fields": protected})
    if "end" in changed:
        revised = revised.model_copy(update={"end_origin": "manual", "default_duration_minutes": None})
    return revised
