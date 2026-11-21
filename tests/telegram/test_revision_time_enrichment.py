"""A known clock must survive adding its missing calendar date (8.1)."""
from datetime import time

import pytest

from mailhelp.domain.revision_errors import ContradictoryRevision
from mailhelp.processing.analysis import validate_revision_successor
from mailhelp.telegram.revision_successor import build_revision_successor
from tests.fakes.shared_telegram_dialog import RevisionService, proposal


class NoModel(RevisionService):
    def revise_proposal(self, item, question, answer):
        raise AssertionError("A complete normalized answer needs no model")


@pytest.mark.parametrize("day,offset", [("2027-01-07", "+01:00"), ("2027-07-07", "+02:00")])
def test_date_completes_known_clock_without_changing_it(day, offset):
    original = proposal(kind="event", status="needs_clarification",
                        known_temporal_facts={"start_time": "11:30:00"},
                        open_questions=["Wann beginnt der Termin?", "Wann endet der Termin?"])
    revised, deterministic = build_revision_successor(
        original, original.open_questions[0], day + " 11:30", "Europe/Berlin", NoModel())
    assert deterministic
    assert revised.version == original.version + 1
    assert revised.known_temporal_facts.start.isoformat() == day + "T11:30:00" + offset
    assert revised.known_temporal_facts.date.isoformat() == day
    assert revised.open_questions == ["Wann endet der Termin?"]
    assert revised.status == "needs_clarification"
    assert revised.end is None
    assert "known_temporal_facts" in revised.protected_fields
    assert original.known_temporal_facts.start_time == time(11, 30)


def test_date_enrichment_still_refuses_a_different_known_clock():
    original = proposal(kind="event", status="needs_clarification",
                        known_temporal_facts={"start_time": "11:30:00"},
                        open_questions=["Wann beginnt der Termin?"])
    with pytest.raises(ContradictoryRevision) as refused:
        build_revision_successor(original, original.open_questions[0],
                                 "2027-01-07 12:30", "Europe/Berlin", NoModel())
    assert refused.value.code == "known_clock_changed"


def test_complete_interval_cannot_discard_a_known_clock():
    original = proposal(kind="event", status="needs_clarification",
                        known_temporal_facts={"start_time": "11:30:00"},
                        open_questions=["Wann beginnt der Termin?"])
    candidate = original.model_copy(update={"version": 2, "known_temporal_facts": None,
        "start": "2027-01-07T12:30:00+01:00", "end": "2027-01-07T13:30:00+01:00",
        "open_questions": [], "status": "pending_confirmation"})
    with pytest.raises(ContradictoryRevision):
        validate_revision_successor(original, candidate.model_dump(mode="json"))


@pytest.mark.parametrize("day,start,end", [
    ("2027-01-07", "2027-01-06T23:30:00Z", "2027-01-07T00:30:00Z"),
    ("2027-07-07", "2027-07-06T22:30:00Z", "2027-07-06T23:30:00Z"),
])
def test_complete_utc_interval_preserves_local_known_dates(day, start, end):
    original = proposal(kind="event", status="needs_clarification",
                        known_temporal_facts={"date": day, "start_time": "00:30:00", "end_date": day},
                        open_questions=["Wann endet der Termin?"])
    candidate = {**original.model_dump(mode="json"), "version": 2, "known_temporal_facts": None,
                 "start": start, "end": end, "open_questions": [], "status": "pending_confirmation"}
    result = validate_revision_successor(original, candidate, configured_timezone="Europe/Berlin")
    assert result.version == 2 and result.known_temporal_facts is None
