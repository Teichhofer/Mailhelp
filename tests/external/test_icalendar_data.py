"""iCalendar resources for CalDAV: bounded parsing and loss-free updates (Planung 2.3, 4.1)."""
import pytest

from mailhelp.external import provider
from mailhelp.external.icalendar_data import (
    MAX_RESOURCE_BYTES,
    event_resource,
    event_summary,
    master,
    open_todo,
    parse_calendar,
    resource_uid,
    updated_event,
)

KEY = "mailhelp:" + "b" * 24 + ":p1:v2"


def test_resource_uid_is_stable_and_differs_per_version():
    assert resource_uid(KEY) == resource_uid(KEY) and resource_uid(KEY) != resource_uid(KEY[:-1] + "3")
    assert resource_uid(KEY).startswith("mailhelp-") and len(resource_uid(KEY)) == 41


def test_texts_are_escaped_folded_and_read_back():
    title = "Sitzung; Raum 3, Haus „Süd“ " + "x" * 120
    body = {"summary": title, "description": "Zeile 1\nZeile 2", "location": "Aula",
            "start": {"dateTime": "2026-05-10T12:00:00+02:00"}, "end": {"dateTime": "2026-05-10T13:00:00+02:00"}}
    content = event_resource(resource_uid(KEY), body, KEY)
    assert all(len(line.encode()) <= 75 for line in content.decode().split("\r\n"))
    fields = event_summary(parse_calendar(content), "Europe/Berlin")
    assert fields == {"summary": title[:500], "description": "Zeile 1\nZeile 2", "location": "Aula",
                      "start": {"dateTime": "2026-05-10T10:00:00+00:00"},
                      "end": {"dateTime": "2026-05-10T11:00:00+00:00"}, "cancelled": False}


@pytest.mark.parametrize("content", [
    "x" * (MAX_RESOURCE_BYTES + 1), b"x" * (MAX_RESOURCE_BYTES + 1),
    "BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\nBEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n",
    "BEGIN:VCALENDAR\r\nEND:VEVENT\r\n", "END:VCALENDAR\r\n", "BEGIN:VEVENT\r\nEND:VEVENT\r\n",
    "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\n", "keine Kalenderdaten"],
    ids=["large-text", "large-bytes", "two-calendars", "wrong-end", "end-first", "no-calendar", "unclosed", "text"])
def test_incomplete_or_oversized_resources_are_refused(content):
    with pytest.raises(ValueError):
        parse_calendar(content)


def test_lines_outside_components_and_without_value_are_ignored():
    calendar = parse_calendar("X-VORHER:1\r\nBEGIN:VCALENDAR\r\nOHNE-DOPPELPUNKT\r\n"
                              "X-PARAM;A=1;B;c=2:wert\r\nEND:VCALENDAR\r\n")
    assert [(item.name, item.params, item.value) for item in calendar.properties] == [
        ("X-PARAM", {"A": "1", "C": "2"}, "wert")]
    assert calendar.get("FEHLT") is None and calendar.text("FEHLT") == ""


def test_update_keeps_unknown_lines_and_replaces_duration():
    original = (b"BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:x\r\nDTSTART;TZID=Europe/Berlin:20260510T100000\r\n"
                b"DURATION:PT1H\r\nX-KEEP:ja\r\nSEQUENCE:2\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    changed = updated_event(original, {"start": {"date": "2026-05-11"}, "end": {"date": "2026-05-12"},
                                       "status": "cancelled"}, KEY).decode()
    assert "DURATION" not in changed and "TZID" not in changed and "X-KEEP:ja" in changed
    assert "DTSTART;VALUE=DATE:20260511" in changed and "STATUS:CANCELLED" in changed and "SEQUENCE:3" in changed
    assert event_summary(parse_calendar(changed), "UTC")["cancelled"] is True
    # Only the start: the existing duration still defines the end.
    moved = updated_event(original, {"start": {"date": "2026-05-11"}}, KEY).decode()
    assert "DURATION:PT1H" in moved


def test_series_multi_part_and_incomplete_events():
    series = parse_calendar("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nRRULE:FREQ=DAILY\r\nDTSTART:20260510T100000Z\r\n"
                            "END:VEVENT\r\nEND:VCALENDAR\r\n")
    with pytest.raises(ValueError, match="Wiederkehrende"):
        master(series, "VEVENT")
    override = parse_calendar("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nRECURRENCE-ID:20260510T100000Z\r\n"
                              "END:VEVENT\r\nEND:VCALENDAR\r\n")
    two = parse_calendar("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nEND:VEVENT\r\nBEGIN:VEVENT\r\nEND:VEVENT\r\n"
                         "END:VCALENDAR\r\n")
    for calendar in (series, override, two):
        assert event_summary(calendar, "UTC") is None
    with pytest.raises(ValueError):
        updated_event(b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n", {}, KEY)


def test_open_todo_detection():
    def todo(lines):
        return parse_calendar(f"BEGIN:VCALENDAR\r\nBEGIN:VTODO\r\nSUMMARY:A\r\n{lines}END:VTODO\r\nEND:VCALENDAR\r\n")

    assert open_todo(todo("DESCRIPTION:B\r\nX-MAILHELP-KEY:k\r\n")) == {"content": "A", "description": "B", "key": "k"}
    assert open_todo(todo("STATUS:completed\r\n")) is None
    assert open_todo(todo("STATUS:CANCELLED\r\n")) is None
    assert open_todo(todo("COMPLETED:20260101T000000Z\r\n")) is None
    assert open_todo(parse_calendar("BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n")) is None


def test_provider_cache_expires_after_a_minute(monkeypatch):
    class Cached(provider.ProviderWriter):
        service, label, role, target = "x", "X", "tasks", "t"

        def __init__(self):
            self._read_cache = {}

        check_access = reconcile = close = _prepare = None

    now = [1000.0]
    monkeypatch.setattr(provider.time, "time", lambda: now[0])
    cached = Cached()
    cached._set_cached(("k",), [1])
    assert cached._get_cached(("k",)) == [1]
    now[0] += 61
    assert cached._get_cached(("k",)) is None and cached._get_cached(("anderer",)) is None
