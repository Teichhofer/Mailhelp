"""7.5.2: dates, times, numbers and durations in both languages; German stays exactly as before."""
from datetime import UTC, date, datetime, time

import pytest

from mailhelp.formatting import duration_text, format_datetime_local
from mailhelp.i18n import Locale, use_locale
from mailhelp.i18n.formatting import clock, clock_suffix, day, day_time, decimal, number
from mailhelp.review.cards import event_time
from mailhelp.review.views import german_number
from tests.fakes.factories import build_proposal

MOMENT = datetime(2027, 1, 7, 10, 30, tzinfo=UTC)


def test_german_and_english_dates_times_and_numbers():
    assert (day(date(2027, 1, 7)), clock(time(9, 5)), clock_suffix()) == ("07.01.2027", "09:05", " Uhr")
    assert number(1234567) == "1.234.567" and decimal(1234.5, 1) == "1.234,5" and german_number(1234) == "1.234"
    assert format_datetime_local(MOMENT, "Europe/Berlin") == "07.01.2027, 11:30 Uhr"
    with use_locale(Locale.EN):
        assert (day(date(2027, 1, 7)), clock_suffix()) == ("Jan 7, 2027", "")
        assert day(date(2026, 12, 24)) == "Dec 24, 2026" and day_time(datetime(2027, 5, 1, 14, 30)) == "May 1, 2027, 14:30"
        assert number(1234567) == "1,234,567" and decimal(1234.5, 1) == "1,234.5" and german_number(1234) == "1,234"
        assert format_datetime_local(MOMENT, "Europe/Berlin") == "Jan 7, 2027, 11:30"


@pytest.mark.parametrize(("seconds", "german", "english"), [
    (12.34, "12,3 s", "12.3 s"), (125, "2 Min. 5 s", "2 min 5 s"), (3600, "1 Std.", "1 h"),
    (5400, "1 Std. 30 Min.", "1 h 30 min"), (86400, "1 Tag", "1 day"), (3 * 86400 + 7200, "3 Tage 2 Std.", "3 days 2 h"),
])
def test_durations_in_both_languages(seconds, german, english):
    assert duration_text(seconds) == german
    with use_locale(Locale.EN):
        assert duration_text(seconds) == english


@pytest.mark.parametrize(("changes", "german", "english"), [
    ({"start": "2027-01-07", "end": "2027-01-09", "all_day": True},
     "07.01.2027 – 08.01.2027, ganztägig", "Jan 7, 2027 – Jan 8, 2027, all-day"),
    ({"start": "2027-01-07", "end": "2027-01-08", "all_day": True}, "07.01.2027, ganztägig", "Jan 7, 2027, all-day"),
    ({"start": "2027-01-07T11:30:00+01:00", "end": "2027-01-07T12:30:00+01:00"},
     "07.01.2027, 11:30–12:30 Uhr", "Jan 7, 2027, 11:30–12:30"),
    ({"start": "2027-01-07T11:30:00+01:00", "end": "2027-01-08T12:30:00+01:00"},
     "07.01.2027, 11:30 Uhr – 08.01.2027, 12:30 Uhr", "Jan 7, 2027, 11:30 – Jan 8, 2027, 12:30"),
    ({"start": None, "end": None, "known_temporal_facts": {"start": "2027-01-07T11:30:00+01:00"}, "duration_minutes": 90,
      "duration_is_upper_bound": True, "status": "needs_clarification", "open_questions": ["Wann endet der Termin?"]},
     "07.01.2027, 11:30 Uhr (höchstens 90 Min.)", "Jan 7, 2027, 11:30 (at most 90 min)"),
    ({"start": None, "end": None, "known_temporal_facts": {"start": "2027-01-07T11:30:00+01:00"}, "duration_minutes": 90,
      "status": "needs_clarification", "open_questions": ["Wann endet der Termin?"]},
     "07.01.2027, 11:30 Uhr (90 Min.)", "Jan 7, 2027, 11:30 (90 min)"),
    ({"start": "2027-01-07T11:30:00+01:00", "end": "2027-01-07T12:30:00+01:00", "default_duration_minutes": 60,
      "end_origin": "standard"},
     "07.01.2027, 11:30–12:30 Uhr · Ende angenommen: Standarddauer 60 Min.",
     "Jan 7, 2027, 11:30–12:30 · Assumed end: default duration 60 min"),
    ({"start": None, "end": None, "known_temporal_facts": {"date": "2027-01-07", "start_time": "11:30:00"},
      "status": "needs_clarification", "open_questions": ["Wann endet der Termin?"]},
     "07.01.2027, 11:30 Uhr", "Jan 7, 2027, 11:30"),
])
def test_event_times_on_cards_in_both_languages(changes, german, english):
    proposal = build_proposal(kind="event", **changes)
    assert event_time(proposal, "Europe/Berlin") == german
    with use_locale(Locale.EN):
        assert event_time(proposal, "Europe/Berlin") == english
