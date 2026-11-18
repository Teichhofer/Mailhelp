"""7.9: one comparison of a proposal's conference link with an existing calendar entry.

The pre-check, the target lookup of changes and the re-check before a write all use it, so
an entry is "already there" only when its content is: a later mail with the access link for
an entry that has none yields a confirmable supplement instead of a duplicate (Planung 7.9).
"""
from __future__ import annotations

from dataclasses import dataclass

from ..domain.conference import LinkAssessment, assess, normalized
from ..domain.proposal import (
    CalendarSupplement,
    ConflictVariant,
    FieldConflict,
    Proposal,
    ProposalClassification,
    ProposalKind,
    ProposalStatus,
)
from ..external.contracts import CalendarOverlapEvent
from ..i18n import de
from ..logging import EventLogger

CONFLICT_ID = "video_link-1"


@dataclass(frozen=True)
class SupplementPlan:
    """The outcome of the comparison; *supplement* is None when nothing is to be written."""

    assessment: LinkAssessment | None
    supplement: CalendarSupplement | None = None

    @property
    def conflict(self) -> bool:
        return self.assessment is not None and self.assessment.state == "conflict"


def plan(proposal: Proposal, existing: CalendarOverlapEvent) -> SupplementPlan:
    """Compare the proposal's link with the entry; cancellations and tasks never supplement."""
    if (proposal.kind != ProposalKind.EVENT or proposal.video_link is None or proposal.is_cancellation
            or proposal.classification == ProposalClassification.CANCELLATION):
        return SupplementPlan(None)
    link = str(proposal.video_link)
    found = assess(link, [existing.description, existing.location], existing.conference_links)
    if found.state not in {"missing", "conflict"}:
        return SupplementPlan(found)
    supplement = CalendarSupplement(
        operation="replace" if found.state == "conflict" else "add", previous=found.previous, proposed=link,
        target_event_id=existing.id, target_profile=proposal.target_profile,
        target_provider=proposal.target_provider, source_mail_id=proposal.source_mail_id)
    return SupplementPlan(found, supplement)


def _chosen(proposal: Proposal, supplement: CalendarSupplement) -> bool:
    """The user already settled this very conflict, or it is still asked."""
    stored = proposal.calendar_supplement
    return (stored is not None and stored.operation == "replace" and stored.previous == supplement.previous
            and normalized(stored.proposed) == normalized(supplement.proposed)
            and stored.target_event_id == supplement.target_event_id)


def apply(proposal: Proposal, result: SupplementPlan) -> Proposal:
    """Store the supplement; a new conflict asks which link applies (needs_clarification)."""
    supplement = result.supplement
    if supplement is None:
        return proposal.model_copy(update={"calendar_supplement": None})
    reopened = ({"status": ProposalStatus.PENDING_CONFIRMATION, "duplicate_match": None}
                if proposal.status == ProposalStatus.ALREADY_EXISTS else {})
    updated = proposal.model_copy(update={"calendar_supplement": supplement, **reopened})
    if not result.conflict or _chosen(proposal, supplement):
        return updated
    assert supplement.previous is not None  # a conflict always names the entry's link
    conflict = FieldConflict(id=CONFLICT_ID, field="video_link", question="-", variants=[
        ConflictVariant(id="a", origin="current", text=supplement.previous),
        ConflictVariant(id="b", origin="source", text=supplement.proposed)])
    asked = de("Widerspruch beim Videolink: im Kalender „{previous}“, laut Mail „{proposed}“. "
               "Welcher Videolink soll gelten?", previous=supplement.previous, proposed=supplement.proposed)
    conflict = conflict.model_copy(update={"question": asked})
    others = [item for item in proposal.field_conflicts if item.id != CONFLICT_ID]
    questions = list(dict.fromkeys([*proposal.open_questions, asked]))
    return updated.model_copy(update={"field_conflicts": [*others, conflict], "open_questions": questions,
                                      "status": ProposalStatus.NEEDS_CLARIFICATION})


def log(logger: EventLogger, proposal: Proposal, existing: CalendarOverlapEvent, result: SupplementPlan) -> None:
    """Content-free diagnosis: ids and the comparison state only, never the link itself."""
    if result.assessment is None:
        return
    event = {"missing": "video_link_missing", "same": "video_link_identical", "conflict": "video_link_conflict",
             "not_conference": "video_link_not_conference"}[result.assessment.state]
    logger.event("INFO", "precheck", event, proposal_id=proposal.id, existing_event_id=existing.id)


__all__ = ["CONFLICT_ID", "SupplementPlan", "apply", "log", "plan"]
