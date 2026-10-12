"""Unit-Tests für den deterministischen RFC 5545 Kalender-Parser."""
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from mailhelp.calendar_parser import MAX_CALENDAR_BYTES, parse_icalendar


def test_parse_simple_timed_event():
    ics = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Example Corp.//EN
BEGIN:VEVENT
UID:uid-123@example.com
SEQUENCE:1
DTSTART:20261015T100000Z
DTEND:20261015T113000Z
SUMMARY:Projekt-Meeting
DESCRIPTION:Besprechung der Release-Ziele
LOCATION:Raum 101
STATUS:CONFIRMED
END:VEVENT
END:VCALENDAR"""
    events = parse_icalendar(ics)
    assert len(events) == 1
    ev = events[0]
    assert ev.uid == "uid-123@example.com"
    assert ev.sequence == 1
    assert ev.summary == "Projekt-Meeting"
    assert ev.description == "Besprechung der Release-Ziele"
    assert ev.location == "Raum 101"
    assert ev.status == "CONFIRMED"
    assert ev.all_day is False
    assert ev.start == datetime(2026, 10, 15, 10, 0, tzinfo=UTC)
    assert ev.end == datetime(2026, 10, 15, 11, 30, tzinfo=UTC)


def test_parse_tzid_and_unfolding_and_escapes():
    ics = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:tzid-event@example.com\r\n"
        "DTSTART;TZID=Europe/Berlin:20261015T140000\r\n"
        "DTEND;TZID=Europe/Berlin:20261015T150000\r\n"
        "SUMMARY:Langer Betreff mit \r\n"
        " Komma\\, und Semikolon\\;\r\n"
        "DESCRIPTION:Zeile 1\\nZeile 2\\NZeile 3\r\n"
        "STATUS:TENTATIVE\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR"
    )
    events = parse_icalendar(ics.encode("utf-8"))
    assert len(events) == 1
    ev = events[0]
    berlin = ZoneInfo("Europe/Berlin")
    assert ev.start == datetime(2026, 10, 15, 14, 0, tzinfo=berlin)
    assert ev.end == datetime(2026, 10, 15, 15, 0, tzinfo=berlin)
    assert ev.summary == "Langer Betreff mit Komma, und Semikolon;"
    assert ev.description == "Zeile 1\nZeile 2\nZeile 3"
    assert ev.status == "TENTATIVE"


def test_parse_all_day_event():
    ics = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:allday-1@example.com
DTSTART;VALUE=DATE:20261020
DTEND;VALUE=DATE:20261021
SUMMARY:Ganztägige Konferenz
END:VEVENT
END:VCALENDAR"""
    events = parse_icalendar(ics)
    assert len(events) == 1
    ev = events[0]
    assert ev.all_day is True
    assert ev.start == date(2026, 10, 20)
    assert ev.end == date(2026, 10, 21)


def test_parse_video_links():
    ics = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:meet-1@example.com
DTSTART:20261015T100000Z
SUMMARY:Meet Call
DESCRIPTION:Einwahl via https://meet.google.com/abc-defg-hij
END:VEVENT
BEGIN:VEVENT
UID:zoom-1@example.com
DTSTART:20261015T120000Z
SUMMARY:Zoom Call
LOCATION:https://us02web.zoom.us/j/1234567890
END:VEVENT
BEGIN:VEVENT
UID:teams-1@example.com
DTSTART:20261015T140000Z
SUMMARY:Teams Call
X-GOOGLE-CONFERENCE:https://teams.microsoft.com/l/meetup-join/19%3ameeting_xyz
END:VEVENT
END:VCALENDAR"""
    events = parse_icalendar(ics)
    assert len(events) == 3
    assert str(events[0].video_link) == "https://meet.google.com/abc-defg-hij"
    assert str(events[1].video_link) == "https://us02web.zoom.us/j/1234567890"
    assert str(events[2].video_link).startswith("https://teams.microsoft.com/l/meetup-join/")


def test_parse_cancellation_and_missing_end():
    ics = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:cancel-1@example.com
DTSTART:20261015T100000Z
SUMMARY:Abgesagtes Treffen
STATUS:CANCELLED
END:VEVENT
END:VCALENDAR"""
    events = parse_icalendar(ics)
    assert len(events) == 1
    assert events[0].status == "CANCELLED"
    assert events[0].end == events[0].start


def test_parse_bounds_and_error_handling():
    # Exceeding size limit
    oversized = b"BEGIN:VCALENDAR\n" + b"X" * (MAX_CALENDAR_BYTES + 10)
    with pytest.raises(ValueError, match="Limit"):
        parse_icalendar(oversized)

    with pytest.raises(ValueError, match="Limit"):
        parse_icalendar("X" * (MAX_CALENDAR_BYTES + 10))

    # Invalid VEVENT missing DTSTART
    no_start = """BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:Kein Start
END:VEVENT
END:VCALENDAR"""
    assert parse_icalendar(no_start) == []

    # Corrupt date format
    bad_date = """BEGIN:VCALENDAR
BEGIN:VEVENT
DTSTART:nicht-ein-datum
SUMMARY:Bad Date
END:VEVENT
END:VCALENDAR"""
    assert parse_icalendar(bad_date) == []

    # Non-VEVENT elements
    no_events = """BEGIN:VCALENDAR
BEGIN:VTODO
SUMMARY:Aufgabe
END:VTODO
END:VCALENDAR"""
    assert parse_icalendar(no_events) == []


def test_parse_fallback_timezone_and_latin1():
    ics = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:latin-1@example.com
DTSTART;TZID=UnknownZone:20261015T100000
SUMMARY:Überraschung
END:VEVENT
END:VCALENDAR"""
    raw = ics.encode("latin-1")
    events = parse_icalendar(raw, default_timezone="Europe/Berlin")
    assert len(events) == 1
    assert events[0].summary == "Überraschung"
    assert events[0].start.tzinfo == ZoneInfo("Europe/Berlin")


def test_parse_edge_cases_and_branches():
    ics = """BEGIN:VCALENDAR
END:VEVENT
BEGIN:VEVENT
THIS_IS_A_LINE_WITHOUT_COLON
DTSTART;SOMEFLAG:20261015T100000
DTEND:20261015T110000Z
SUMMARY:
SEQUENCE:not_a_number
STATUS:UNKNOWN_STATUS
END:VEVENT
END:VCALENDAR"""
    # Test with invalid default timezone falling back to UTC
    events = parse_icalendar(ics, default_timezone="NonExistent/Zone")
    assert len(events) == 1
    assert events[0].summary == "Unbenannter Termin"
    assert events[0].sequence == 0
    assert events[0].status == "CONFIRMED"
    assert events[0].start.tzinfo == UTC

    # Test all-day date start with datetime end
    allday_ics = """BEGIN:VCALENDAR
BEGIN:VEVENT
DTSTART;VALUE=DATE:20261025
DTEND:20261026T120000Z
SUMMARY:Mischtermin
END:VEVENT
END:VCALENDAR"""
    events2 = parse_icalendar(allday_ics)
    assert len(events2) == 1
    assert events2[0].all_day is True
    assert events2[0].start == date(2026, 10, 25)
    assert events2[0].end == date(2026, 10, 26)


def test_an_escaped_backslash_before_n_stays_a_backslash():
    """Regression: unescaping replaced step by step, so an escaped backslash
    followed by "n" or "N" (a Windows path) turned into a line break."""
    ics = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
        "UID:path@example.com\r\nDTSTART:20261015T100000Z\r\n"
        r"SUMMARY:Ablage C:\\new" "\r\n"
        r"DESCRIPTION:Ordner C:\\new\\Nordsee\, Plan\; zweite\nZeile" "\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    (event,) = parse_icalendar(ics)
    assert event.summary == r"Ablage C:\new"
    assert event.description == "Ordner C:\\new\\Nordsee, Plan; zweite\nZeile"
