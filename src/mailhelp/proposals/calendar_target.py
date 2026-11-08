"""Find the calendar entry a change or cancellation refers to (Planung 4.6, 17.3).

The duplicate matcher compares overlapping entries; a moved appointment is in another
window and often on another day. The existing entry is therefore located
deterministically: a related title in the window around the earlier date (change) or the
cancelled date (cancellation). Without an earlier date, the title is searched in a wider
window around the new date. Exactly one hit becomes the target; none or several leave
the proposal open with a concrete question and never overwrite a guessed entry.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ..domain.proposal import (
    CalendarCandidate,
    DuplicateMatchInfo,
    DuplicateSource,
    Proposal,
    ProposalClassification,
    ProposalStatus,
    required_revision_questions,
)
from ..external.calendar import CalendarOperations
from ..external.contracts import CalendarOverlapEvent
from ..logging import EventLogger

NEAR = timedelta(days=1)
WIDE = timedelta(days=92)
MAX_CANDIDATES = 10
TARGET_QUESTIONS = frozenset({"Welcher bestehende Eintrag soll geändert werden?",
                              "Welcher bestehende Eintrag soll storniert werden?"})
NOT_FOUND = "Im Kalender wurde kein passender Termin gefunden. Welcher Eintrag ist gemeint?"
AMBIGUOUS = "Mehrere passende Termine im Kalender gefunden. Welcher ist gemeint?"
GONE = "Der zugeordnete Kalendertermin existiert nicht mehr. Welcher Eintrag ist gemeint?"
_OWN_QUESTIONS = TARGET_QUESTIONS | {NOT_FOUND, AMBIGUOUS, GONE}
TARGETED = frozenset({ProposalClassification.CHANGE, ProposalClassification.CANCELLATION})


def raw_moment(raw: dict[str, str]) -> date | datetime | None:
    """A provider-neutral start or end (``dateTime`` or ``date``)."""
    if "dateTime" in raw:
        return datetime.fromisoformat(raw["dateTime"].replace("Z", "+00:00"))
    return date.fromisoformat(raw["date"]) if "date" in raw else None


def _midnight(day: date) -> datetime:
    return datetime.combine(day, datetime.min.time(), UTC)


class CalendarTargetFinder:
    """Resolve ``target_event_id`` for one change or cancellation proposal."""

    def __init__(self, writer: CalendarOperations, logger: EventLogger):
        self.writer, self.logger = writer, logger
        self.zone = ZoneInfo(writer.calendar_timezone or "UTC")

    def check(self, proposal: Proposal) -> Proposal:
        if proposal.target_event_id is not None:
            # A chosen or found target is only verified, never searched again:
            # otherwise a resolved ambiguity would reappear on every check.
            existing = self.writer.existing_event(proposal.target_event_id)
            if existing is None:
                return self._open(proposal, [], GONE)
            return self._targeted(proposal, existing)
        matches = self._matches(proposal)
        if matches is None:
            return proposal
        if len(matches) == 1:
            return self._targeted(proposal, matches[0])
        return self._open(proposal, matches[:MAX_CANDIDATES], AMBIGUOUS if matches else NOT_FOUND)

    def choose(self, proposal: Proposal, event_id: str) -> Proposal:
        """The user picked one of the stored candidates (17.4); anything else is refused."""
        if event_id not in {item.event_id for item in proposal.calendar_candidates}:
            raise ValueError("Nur ein angebotener Kalendertermin kann gewählt werden")
        existing = self.writer.existing_event(event_id)
        if existing is None:
            return self._open(proposal, [item for item in proposal.calendar_candidates if item.event_id != event_id],
                              GONE)
        return self._targeted(proposal, existing)

    def _day(self, value: date | datetime) -> date:
        return value.astimezone(self.zone).date() if isinstance(value, datetime) else value

    def _matches(self, proposal: Proposal) -> list[CalendarOverlapEvent] | None:
        """Related entries; ``None`` if the proposal names no day at all."""
        known = proposal.known_temporal_facts
        new_day = (self._day(proposal.start) if proposal.start is not None
                   else known.date if known is not None and known.date is not None
                   else self._day(known.start) if known is not None and known.start is not None else None)
        if proposal.classification == ProposalClassification.CHANGE and proposal.original_date is not None:
            reference, radius = proposal.original_date, NEAR
        elif proposal.classification == ProposalClassification.CANCELLATION and new_day is not None:
            reference, radius = new_day, NEAR
        elif new_day is not None:
            reference, radius = new_day, WIDE
        else:
            return None
        title = proposal.base_title or proposal.title
        return self.writer.search_events(title, _midnight(reference - radius), _midnight(reference + radius + NEAR))

    def _times(self, proposal: Proposal, existing: CalendarOverlapEvent) -> dict[str, Any]:
        """Times the confirmed write uses; missing ones are taken from the calendar entry."""
        old_start, old_end = raw_moment(existing.start), raw_moment(existing.end)
        if old_start is None or old_end is None:
            return {}
        if proposal.classification == ProposalClassification.CANCELLATION:
            return {"start": old_start, "end": old_end, "all_day": not isinstance(old_start, datetime)}
        known = proposal.known_temporal_facts
        if known is None:
            return {}  # complete times stay; a partial interval without facts is not guessed
        duration = old_end - old_start
        if isinstance(old_start, datetime):
            start = known.start
            if start is None and known.date is not None:
                # "verschoben auf den 11.12.": same local time of day as before.
                local = old_start.astimezone(self.zone).replace(tzinfo=None)
                start = datetime.combine(known.date, local.time(), self.zone)
            if start is None:
                return {}
            return {"start": start, "end": start + duration, "all_day": False}
        if known.date is None:
            return {}
        return {"start": known.date, "end": known.date + duration, "all_day": True}

    def _targeted(self, proposal: Proposal, existing: CalendarOverlapEvent) -> Proposal:
        times = self._times(proposal, existing)
        updated = proposal.model_copy(update={
            **times, **({"known_temporal_facts": None, "end_origin": "calendar"} if times else {}),
            "target_event_id": existing.id, "calendar_candidates": [],
            "is_cancellation": proposal.classification == ProposalClassification.CANCELLATION})
        changes: list[str] = []
        if updated.start is not None and updated.end is not None:
            changes, _interval = self.writer.time_changes(updated, existing)
        if (proposal.classification == ProposalClassification.CHANGE and proposal.location
                and proposal.location != (existing.location or "")):
            changes.append(f"Ort {existing.location or '—'} → {proposal.location}")
        if proposal.classification == ProposalClassification.CHANGE and not changes and updated.start is not None:
            # The entry already shows the new state, e.g. the user moved it by hand.
            self.logger.event("INFO", "precheck", "change_already_applied", proposal_id=proposal.id,
                              existing_event_id=existing.id)
            return proposal.model_copy(update={
                "status": ProposalStatus.ALREADY_EXISTS, "open_questions": [], "target_event_id": None,
                "calendar_candidates": [], "is_cancellation": False, "time_changes": [],
                "duplicate_match": DuplicateMatchInfo(
                    source=DuplicateSource.GOOGLE_CALENDAR, external_id=existing.id,
                    external_link=existing.htmlLink, matched_title=existing.summary or proposal.title,
                    details=f"Der Kalendertermin hat bereits den neuen Stand ({self.writer.label})")})
        self.logger.event("INFO", "precheck", "calendar_target_found", proposal_id=proposal.id,
                          existing_event_id=existing.id, cancellation=updated.is_cancellation)
        kept = [question for question in proposal.open_questions if question not in _OWN_QUESTIONS]
        if times:
            # The calendar supplied the missing times, so earlier time questions are answered.
            kept = []
        updated = updated.model_copy(update={"time_changes": changes})
        questions = list(dict.fromkeys([*kept, *required_revision_questions(updated)]))
        return updated.model_copy(update={
            "open_questions": questions,
            "status": ProposalStatus.NEEDS_CLARIFICATION if questions else ProposalStatus.PENDING_CONFIRMATION})

    def _open(self, proposal: Proposal, matches: list[CalendarOverlapEvent] | list[CalendarCandidate],
              question: str) -> Proposal:
        self.logger.event("INFO", "precheck", "calendar_target_open", proposal_id=proposal.id,
                          candidates=len(matches))
        candidates = [candidate for candidate in (
            item if isinstance(item, CalendarCandidate) else self._candidate(item) for item in matches)
            if candidate is not None]
        cleared = proposal.model_copy(update={"target_event_id": None, "is_cancellation": False,
                                              "time_changes": [], "calendar_candidates": candidates})
        kept = [item for item in proposal.open_questions if item not in _OWN_QUESTIONS]
        questions = list(dict.fromkeys([question, *kept, *(item for item in required_revision_questions(cleared)
                                                            if item not in TARGET_QUESTIONS)]))
        return cleared.model_copy(update={"open_questions": questions, "status": ProposalStatus.NEEDS_CLARIFICATION})

    @staticmethod
    def _candidate(item: CalendarOverlapEvent) -> CalendarCandidate | None:
        start, end = raw_moment(item.start), raw_moment(item.end)
        if start is None or end is None:
            return None  # an entry without readable times cannot be offered for selection
        return CalendarCandidate(event_id=item.id, title=item.summary[:500], start=start, end=end)


__all__ = ["AMBIGUOUS", "GONE", "NOT_FOUND", "TARGETED", "TARGET_QUESTIONS", "CalendarTargetFinder", "raw_moment"]
