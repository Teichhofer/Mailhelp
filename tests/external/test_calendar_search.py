"""4.6, step 17.1: title search in the calendar adapters (Google, CalDAV, Outlook)."""
from datetime import UTC, date, datetime

import httpx
import pytest

from mailhelp.domain.event_titles import significant_words, titles_related
from mailhelp.external.caldav import CalDavCalendar
from mailhelp.external.microsoft import OutlookCalendar
from mailhelp.llm.adapter import RetryableError
from tests.fakes.calendar_fakes import FakeGoogleCalendar, google_writer, timed, vevent
from tests.fakes.dav_fakes import COLLECTION, FakeDav

WINDOW = (datetime(2026, 9, 1, tzinfo=UTC), datetime(2027, 3, 1, tzinfo=UTC))


@pytest.mark.parametrize(("query", "summary", "related"), [
    ("Sitzung des Gemeinderats", "Gemeinderatssitzung", True),   # compound word
    ("Gemeinderatssitzung", "Sitzung Gemeinderat", True),
    ("Elternabend Klasse 3b", "ELTERNABEND", True),               # case and extra words
    ("Projektmeeting", "Projekt-Meeting Alpha", True),             # "projekt" occurs in the compound
    ("Projektmeeting", "Zahnarzt", False),
    ("Termin am 4.12.", "Termin Zahnarzt", False),                 # only stop words in the query
    ("Landesversammlung", "", False),
])
def test_titles_are_related_by_a_significant_word(query, summary, related):
    assert titles_related(query, summary) is related


def test_short_words_digits_and_stop_words_are_not_significant():
    assert significant_words("Die Sitzung am 04.12.2026 um 18 Uhr – neu: Raum B12") == {"sitzung", "raum"}


def test_google_search_returns_related_events_in_the_window_only():
    calendar = FakeGoogleCalendar(
        timed("a", "Gemeinderatssitzung", "2026-12-04T18:00:00+01:00", "2026-12-04T20:00:00+01:00"),
        timed("b", "Zahnarzt", "2026-12-05T09:00:00+01:00", "2026-12-05T10:00:00+01:00"),
        timed("c", "Gemeinderatssitzung", "2027-06-04T18:00:00+02:00", "2027-06-04T20:00:00+02:00"),
        timed("d", "Sitzung Gemeinderat", "2026-12-11T18:00:00+01:00", "2026-12-11T20:00:00+01:00",
              status="cancelled"))
    writer = google_writer(calendar)
    found = writer.search_events("Sitzung des Gemeinderats", *WINDOW)
    assert [item.id for item in found] == ["a"]  # outside the window and cancelled events are left out
    (request,) = calendar.requests
    assert "q" not in request.url.params  # the title never leaves Mailhelp


def test_a_failed_search_raises_instead_of_reporting_no_event():
    calendar = FakeGoogleCalendar()
    calendar.fail[("GET", "list")] = httpx.Response(500)
    with pytest.raises(RetryableError):  # retried by the policy, then reported
        google_writer(calendar).search_events("Sitzung", *WINDOW)


def test_caldav_search_filters_titles_of_the_report():
    server = FakeDav()
    server.resources[COLLECTION + "a.ics"] = vevent("a", "Elternabend 3b", "20261124T183000Z", "20261124T200000Z")
    server.resources[COLLECTION + "b.ics"] = vevent("b", "Zahnarzt", "20261124T080000Z", "20261124T090000Z")
    writer = CalDavCalendar(COLLECTION, "anna", "app-password", transport=httpx.MockTransport(server))
    found = writer.search_events("Einladung Elternabend", date(2026, 11, 1), date(2027, 1, 1))
    assert [item.id for item in found] == [COLLECTION + "a.ics"]


class Token:
    def access_token(self):
        return "graph-token"

    def invalidate(self):
        return None


def test_outlook_search_filters_titles_of_the_calendar_view():
    def graph(request):
        assert request.url.path.endswith("/me/calendar/calendarView")
        return httpx.Response(200, json={"value": [
            {"id": "o1", "subject": "Mitgliederversammlung", "isAllDay": False, "isCancelled": False,
             "start": {"dateTime": "2027-01-15T19:00:00.0000000", "timeZone": "UTC"},
             "end": {"dateTime": "2027-01-15T21:00:00.0000000", "timeZone": "UTC"}},
            {"id": "o2", "subject": "Mitgliederversammlung", "isAllDay": False, "isCancelled": True,
             "start": {"dateTime": "2027-01-16T19:00:00.0000000", "timeZone": "UTC"},
             "end": {"dateTime": "2027-01-16T21:00:00.0000000", "timeZone": "UTC"}},
            {"id": "o3", "subject": "Lauftreff", "isAllDay": False, "isCancelled": False,
             "start": {"dateTime": "2027-01-15T07:00:00.0000000", "timeZone": "UTC"},
             "end": {"dateTime": "2027-01-15T08:00:00.0000000", "timeZone": "UTC"}}]})

    writer = OutlookCalendar(Token(), "default", transport=httpx.MockTransport(graph))
    found = writer.search_events("Absage Mitgliederversammlung", *WINDOW)
    assert [item.id for item in found] == ["o1"]


def test_task_targets_have_no_calendar_events():
    from mailhelp.proposals.integrations import HttpWriter
    todoist = HttpWriter(service="todoist", token="tok", target="inbox", transport=httpx.MockTransport(
        lambda request: httpx.Response(500)))
    assert todoist.fetch_events_in_window(*WINDOW) == []
