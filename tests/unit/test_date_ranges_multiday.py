"""7.4: multi-day dates and ranges – weekdays, short forms, month and year changes, timed spans."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from mailhelp.proposals.action_normalization import NormalizationReason, TemporalValue, normalize_event
from tests.fakes.shared_action_normalization import context, event

BERLIN = ZoneInfo("Europe/Berlin")


def timed(**changes):
    return event(**{"time_requirement": "timed", **changes})


def test_the_original_case_needs_no_date_question():
    """Regression 7.4 (Vlf Schulungstagung): a range with weekdays and times spanning two days."""
    result = normalize_event(timed(title="Vlf Schulungstagung Bad Waldsee",
                                   date_text="Donnerstag 07. bis Freitag 08. Januar 2027",
                                   time_text="11.30 Uhr", end_time_text="12.30 Uhr"), context())
    assert result.reason is None and result.question is None
    assert result.value == TemporalValue(datetime(2027, 1, 7, 11, 30, tzinfo=BERLIN),
                                         datetime(2027, 1, 8, 12, 30, tzinfo=BERLIN), False)
    assert result.value.start.isoformat() == "2027-01-07T11:30:00+01:00"
    assert result.temporal_fact.normalized_date == date(2027, 1, 7)


@pytest.mark.parametrize("raw", [
    "Donnerstag 07. bis Freitag 08. Januar 2027",
    "Donnerstag, 7. bis Freitag, 8. Januar 2027",
    "Do 07. – Fr 08.01.2027",
    "Do. 07. bis Fr. 08.01.2027",
    "07./08.01.2027",
    "07.-08.01.2027",
    "7./8.1.2027",
    "7./8. Januar 2027",
    "7.-8. Januar 2027",
    "Do 07.01.2027 bis Fr 08.01.2027",
    "vom 7. bis 8. Januar 2027",
])
def test_every_spelling_of_a_two_day_range_is_one_all_day_interval(raw):
    result = normalize_event(event(date_text=raw), context())
    assert result.value == TemporalValue(date(2027, 1, 7), date(2027, 1, 9), True), raw


@pytest.mark.parametrize(("raw", "start", "end"), [
    ("28. Januar bis 2. Februar 2027", date(2027, 1, 28), date(2027, 2, 2)),
    ("28.01. bis 02.02.2027", date(2027, 1, 28), date(2027, 2, 2)),
    ("28. Dezember bis 2. Januar 2027", date(2026, 12, 28), date(2027, 1, 2)),
    ("28.12. – 02.01.2027", date(2026, 12, 28), date(2027, 1, 2)),
    ("Montag, 28. Dezember bis Samstag, 2. Januar 2027", date(2026, 12, 28), date(2027, 1, 2)),
])
def test_ranges_across_months_and_years(raw, start, end):
    result = normalize_event(event(date_text=raw), context())
    assert result.value.start == start and result.value.end == date.fromordinal(end.toordinal() + 1)


@pytest.mark.parametrize("raw", ["Freitag 07. bis Samstag 08. Januar 2027", "Do 07. – Sa 08.01.2027",
                                 "Mittwoch, 28. Dezember bis Samstag, 2. Januar 2027"])
def test_a_contradicting_weekday_asks_instead_of_guessing(raw):
    result = normalize_event(event(date_text=raw), context())
    assert result.value is None and result.reason == NormalizationReason.INVALID_DATE
    assert result.question == "Wochentag und Kalenderdatum widersprechen sich."
    assert result.temporal_fact.status == "unresolved"


def test_compact_ranges_with_times_are_timed_spans():
    result = normalize_event(timed(date_text="07./08.01.2027", time_text="09:00", end_time_text="16:00"), context())
    assert result.value == TemporalValue(datetime(2027, 1, 7, 9, tzinfo=BERLIN),
                                         datetime(2027, 1, 8, 16, tzinfo=BERLIN), False)
    # A clock range copied into time_text is split as for single days.
    split = normalize_event(timed(date_text="7.-8. Januar 2027", time_text="13:00 - 12:00"), context())
    assert split.value.end == datetime(2027, 1, 8, 12, tzinfo=BERLIN)


def test_a_timed_span_with_a_duration_or_without_an_end():
    with_duration = normalize_event(timed(date_text="07./08.01.2027", time_text="10:00", duration_minutes=90),
                                    context())
    assert with_duration.value.end == datetime(2027, 1, 7, 11, 30, tzinfo=BERLIN)
    open_end = normalize_event(timed(date_text="07./08.01.2027", time_text="10:00"), context())
    assert open_end.reason == NormalizationReason.MISSING_END_TIME
    assert open_end.question == "Wann endet der Termin am 08.01.2027?"
    assert open_end.known_start == datetime(2027, 1, 7, 10, tzinfo=BERLIN) and open_end.known_date == date(2027, 1, 7)
    no_start = normalize_event(timed(date_text="07./08.01.2027", end_time_text="12:00"), context())
    assert no_start.reason == NormalizationReason.MISSING_TIME


def test_an_explicitly_all_day_range_ignores_clock_fragments_and_a_single_day_keeps_its_question():
    all_day = normalize_event(event(date_text="07./08.01.2027", time_text="10:00"), context())
    assert all_day.value == TemporalValue(date(2027, 1, 7), date(2027, 1, 9), True)
    single = normalize_event(timed(date_text="07.01.2027", time_text="10:00"), context())
    assert single.question == "Wann endet der Termin?"


def test_a_timed_span_whose_end_precedes_its_start_is_refused():
    result = normalize_event(timed(date_text="07./07.01.2027", time_text="13:00", end_time_text="12:00"), context())
    assert result.reason == NormalizationReason.END_NOT_AFTER_START


@pytest.mark.parametrize("raw", ["31./32.01.2027", "30. Februar bis 2. März 2027", "07.13.2027 – 08.13.2027",
                                 "30./31. Februar 2027"])
def test_impossible_calendar_days_are_no_range(raw):
    result = normalize_event(event(date_text=raw), context())
    assert result.value is None


def test_text_around_a_range_and_repeated_mentions_stay_one_range():
    result = normalize_event(event(date_text=None, evidence="Tagung 07./08.01.2027 (Do 07. – Fr 08.01.2027)"),
                             context())
    assert result.value == TemporalValue(date(2027, 1, 7), date(2027, 1, 9), True)
