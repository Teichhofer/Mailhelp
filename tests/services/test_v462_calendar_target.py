"""4.6, step 17.3: a change or cancellation finds its existing calendar entry."""
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from mailhelp.external.contracts import CalendarOverlapEvent
from mailhelp.models import KnownTemporalFacts, ProposalClassification, ProposalStatus
from mailhelp.proposals.calendar_target import AMBIGUOUS, GONE, NOT_FOUND, CalendarTargetFinder, raw_moment
from mailhelp.proposals.precheck import DuplicatePreCheckService
from tests.fakes.calendar_fakes import FakeGoogleCalendar, google_writer, timed
from tests.fakes.log_fakes import RecordingLogger
from tests.fakes.proposal_builder_fakes import builder, event

BERLIN = ZoneInfo("Europe/Berlin")
MOVE = "Die Gemeinderatssitzung am 04.12.2026 wird auf den 11.12.2026 verschoben."
SESSION = timed("gr-1", "Gemeinderatssitzung", "2026-12-04T18:00:00+01:00", "2026-12-04T20:00:00+01:00",
                location="Rathaus, Saal 1")


def built(**changes):
    values = dict(title="Gemeinderatssitzung", evidence=MOVE, date_text="11.12.2026", time_text=None,
                  time_requirement="required_unknown", classification="change", original_date_text="04.12.2026")
    values.update(changes)
    (proposal,) = builder().build([], [event(**values)])
    return proposal


def check(proposal, *events):
    calendar = FakeGoogleCalendar(*events)
    return DuplicatePreCheckService(writer=google_writer(calendar)).check_proposal(proposal), calendar


def test_a_move_to_another_day_targets_the_entry_on_the_earlier_day():
    before = built()
    assert before.status == ProposalStatus.NEEDS_CLARIFICATION and before.start is None
    result, calendar = check(before, SESSION)
    assert result.target_event_id == "gr-1" and not result.is_cancellation
    # Only the new day was known: the entry keeps its time of day and duration.
    assert (result.start, result.end) == (datetime(2026, 12, 11, 18, tzinfo=BERLIN),
                                          datetime(2026, 12, 11, 20, tzinfo=BERLIN))
    assert result.end_origin == "calendar" and result.known_temporal_facts is None
    assert result.time_changes == ["Beginn 04.12.2026 18:00 Uhr → 11.12.2026 18:00 Uhr",
                                   "Ende 04.12.2026 20:00 Uhr → 11.12.2026 20:00 Uhr"]
    assert result.open_questions == [] and result.status == ProposalStatus.PENDING_CONFIRMATION
    assert result.is_creatable
    (request,) = calendar.requests  # one window query around the earlier day
    assert request.url.params["timeMin"].startswith("2026-12-03") and request.url.params["timeMax"].startswith(
        "2026-12-06")


def test_a_later_start_on_the_same_day_keeps_the_duration():
    proposal = built(evidence="Die Sitzung am 04.12.2026 beginnt erst um 19:30 Uhr statt 18:00 Uhr.",
                     date_text="04.12.2026", time_text="19:30 Uhr", time_requirement="timed")
    result, _ = check(proposal, SESSION)
    assert (result.start, result.end) == (datetime(2026, 12, 4, 19, 30, tzinfo=BERLIN),
                                          datetime(2026, 12, 4, 21, 30, tzinfo=BERLIN))
    assert result.status == ProposalStatus.PENDING_CONFIRMATION


def test_a_new_room_is_listed_as_a_change():
    proposal = built(date_text="04.12.2026", time_text="18:00 Uhr", end_time_text="20:00 Uhr",
                     time_requirement="timed", location="Rathaus, Saal 2")
    result, _ = check(proposal, SESSION)
    assert result.time_changes == ["Ort Rathaus, Saal 1 → Rathaus, Saal 2"]
    assert result.target_event_id == "gr-1" and result.status == ProposalStatus.PENDING_CONFIRMATION


def test_an_entry_already_moved_by_hand_needs_no_write():
    moved = timed("gr-1", "Gemeinderatssitzung", "2026-12-11T18:00:00+01:00", "2026-12-11T20:00:00+01:00")
    proposal = built(original_date_text="11.12.2026", time_text="18:00 Uhr", end_time_text="20:00 Uhr",
                     time_requirement="timed")
    result, _ = check(proposal, moved)
    assert result.status == ProposalStatus.ALREADY_EXISTS and result.target_event_id is None
    assert result.duplicate_match.external_id == "gr-1" and "bereits den neuen Stand" in result.duplicate_match.details


def test_two_matching_entries_are_offered_instead_of_guessed():
    twin = timed("gr-2", "Sitzung Gemeinderat (Vorbesprechung)", "2026-12-04T16:00:00+01:00",
                 "2026-12-04T17:00:00+01:00")
    result, _ = check(built(), SESSION, twin)
    assert result.target_event_id is None and result.status == ProposalStatus.NEEDS_CLARIFICATION
    assert result.open_questions[0] == AMBIGUOUS
    assert [item.event_id for item in result.calendar_candidates] == ["gr-1", "gr-2"]
    assert not result.is_creatable  # nothing is overwritten blindly


def test_without_a_matching_entry_the_user_is_asked():
    other = timed("x", "Zahnarzt", "2026-12-04T09:00:00+01:00", "2026-12-04T10:00:00+01:00")
    result, _ = check(built(), other)
    assert result.open_questions[0] == NOT_FOUND and result.calendar_candidates == []
    assert "Welcher bestehende Eintrag soll geändert werden?" not in result.open_questions


def test_without_an_earlier_date_the_title_is_searched_around_the_new_date():
    result, calendar = check(built(original_date_text=None), SESSION)
    assert result.target_event_id == "gr-1"
    params = calendar.requests[0].url.params
    assert params["timeMin"].startswith("2026-09-10") and params["timeMax"].startswith("2027-03-14")


def test_a_cancellation_takes_the_times_of_the_cancelled_entry():
    proposal = built(classification="cancellation", original_date_text=None, date_text="04.12.2026",
                     evidence="Die Gemeinderatssitzung am 04.12.2026 entfällt.")
    assert proposal.status == ProposalStatus.NEEDS_CLARIFICATION
    result, _ = check(proposal, SESSION)
    assert result.is_cancellation and result.target_event_id == "gr-1"
    assert (result.start, result.end, result.all_day) == (datetime(2026, 12, 4, 18, tzinfo=BERLIN),
                                                          datetime(2026, 12, 4, 20, tzinfo=BERLIN), False)
    assert result.status == ProposalStatus.PENDING_CONFIRMATION and result.open_questions == []


def test_an_all_day_entry_is_cancelled_and_moved_as_an_all_day_entry():
    fest = {"id": "fest", "summary": "Gemeinderatssitzung", "start": {"date": "2026-12-04"},
            "end": {"date": "2026-12-05"}}
    cancelled, _ = check(built(classification="cancellation", original_date_text=None, date_text="04.12.2026"), fest)
    assert (cancelled.start, cancelled.end, cancelled.all_day) == (date(2026, 12, 4), date(2026, 12, 5), True)
    moved, _ = check(built(), fest)
    assert (moved.start, moved.end, moved.all_day) == (date(2026, 12, 11), date(2026, 12, 12), True)


def test_a_chosen_target_is_verified_and_a_deleted_one_reopens_the_question():
    found, calendar = check(built(), SESSION)
    again = DuplicatePreCheckService(writer=google_writer(calendar)).check_proposal(found)
    assert again.target_event_id == "gr-1" and again.time_changes == found.time_changes
    assert calendar.requests[-1].url.path.endswith("/events/gr-1")  # read by id, not searched again
    del calendar.events["gr-1"]
    gone = DuplicatePreCheckService(writer=google_writer(calendar)).check_proposal(found)
    assert gone.target_event_id is None and gone.open_questions[0] == GONE
    assert gone.status == ProposalStatus.NEEDS_CLARIFICATION


def test_the_user_can_only_choose_an_offered_candidate():
    twin = timed("gr-2", "Gemeinderatssitzung Ausschuss", "2026-12-04T16:00:00+01:00", "2026-12-04T17:00:00+01:00")
    calendar = FakeGoogleCalendar(SESSION, twin)
    finder = CalendarTargetFinder(google_writer(calendar), RecordingLogger())
    offered = finder.check(built())
    chosen = finder.choose(offered, "gr-2")
    assert chosen.target_event_id == "gr-2" and chosen.calendar_candidates == []
    with pytest.raises(ValueError, match="angebotener Kalendertermin"):
        finder.choose(offered, "fremd")
    del calendar.events["gr-1"]
    gone = finder.choose(offered, "gr-1")
    assert gone.open_questions[0] == GONE and [item.event_id for item in gone.calendar_candidates] == ["gr-2"]


def test_a_change_without_any_day_is_left_as_it_is():
    proposal = built(date_text=None, original_date_text=None, evidence="Die Sitzung wird verschoben.")
    result, calendar = check(proposal)
    assert result == proposal and calendar.requests == []


def test_a_failed_search_marks_the_check_as_failed():
    calendar = FakeGoogleCalendar()
    calendar.fail[("GET", "list")] = httpx.Response(400)
    result = DuplicatePreCheckService(writer=google_writer(calendar)).check_proposal(built())
    assert result.duplicate_check_failed and result.target_event_id is None


def test_regression_a_cancelled_calendar_attachment_builds_and_finds_its_entry():
    """Before 4.6.2 a cancelled ICS attachment raised "Stornierung erfordert eine Ziel-Event-ID"."""
    (proposal,) = builder().build([], [], calendar_events=[{
        "uid": "u1", "summary": "Gemeinderatssitzung", "start": datetime(2026, 12, 4, 17, tzinfo=UTC),
        "end": datetime(2026, 12, 4, 19, tzinfo=UTC), "all_day": False, "status": "CANCELLED"}])
    assert proposal.classification == ProposalClassification.CANCELLATION and not proposal.is_cancellation
    assert proposal.status == ProposalStatus.NEEDS_CLARIFICATION
    result, _ = check(proposal, SESSION)
    assert result.is_cancellation and result.target_event_id == "gr-1"
    assert result.status == ProposalStatus.PENDING_CONFIRMATION


class Writer:
    """A calendar writer double for the times rules without HTTP."""

    calendar_timezone, label = "Europe/Berlin", "Testkalender"

    def __init__(self, *events):
        self.events = list(events)

    def search_events(self, title, start, end):
        return self.events

    def existing_event(self, event_id):
        return next((item for item in self.events if item.id == event_id), None)

    def time_changes(self, proposal, existing):
        return ["geändert"], {}


def overlap(event_id, start, end):
    return CalendarOverlapEvent(id=event_id, summary="Gemeinderatssitzung", start=start, end=end)


def test_entries_without_readable_times_are_neither_offered_nor_used_for_times():
    broken = overlap("b", {"timeZone": "UTC"}, {"timeZone": "UTC"})
    good = overlap("g", {"dateTime": "2026-12-04T17:00:00Z"}, {"dateTime": "2026-12-04T19:00:00Z"})
    finder = CalendarTargetFinder(Writer(broken, good), RecordingLogger())
    offered = finder.check(built())
    assert [item.event_id for item in offered.calendar_candidates] == ["g"]
    kept = CalendarTargetFinder(Writer(broken), RecordingLogger()).check(built())
    assert kept.target_event_id == "b" and kept.start is None  # times stay open, nothing is guessed
    assert "Wann beginnt der Termin?" in kept.open_questions


def test_partial_facts_only_complete_what_the_entry_can_supply():
    entry = overlap("g", {"dateTime": "2026-12-04T17:00:00Z"}, {"dateTime": "2026-12-04T19:00:00Z"})
    all_day = overlap("d", {"date": "2026-12-04"}, {"date": "2026-12-05"})
    clock_only = built().model_copy(update={"known_temporal_facts": KnownTemporalFacts(start_time="10:00")})
    assert CalendarTargetFinder(Writer(entry), RecordingLogger()).check(clock_only).start is None
    timed_new = built().model_copy(update={"known_temporal_facts": KnownTemporalFacts(
        start=datetime(2026, 12, 11, 9, tzinfo=BERLIN))})
    assert CalendarTargetFinder(Writer(all_day), RecordingLogger()).check(timed_new).start is None
    no_facts = built(date_text="11.12.2026", time_text="18:00 Uhr", time_requirement="timed").model_copy(
        update={"known_temporal_facts": None})
    assert CalendarTargetFinder(Writer(entry), RecordingLogger()).check(no_facts).end is None


def test_provider_neutral_moments_are_read_from_date_or_date_time():
    assert raw_moment({"dateTime": "2026-12-04T17:00:00Z"}) == datetime(2026, 12, 4, 17, tzinfo=UTC)
    assert raw_moment({"date": "2026-12-04"}) == date(2026, 12, 4)
    assert raw_moment({"timeZone": "UTC"}) is None
