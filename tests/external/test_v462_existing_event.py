"""4.6, step 17.3: every calendar adapter reads one event by id; gone or cancelled is None."""
import httpx
import pytest

from mailhelp.external.caldav import CalDavCalendar
from mailhelp.external.microsoft import OutlookCalendar
from mailhelp.llm.adapter import PermanentError
from tests.fakes.calendar_fakes import FakeGoogleCalendar, google_writer, timed, vevent
from tests.fakes.dav_fakes import COLLECTION, FakeDav

ENTRY = timed("e1", "Elternabend", "2026-11-24T19:30:00+01:00", "2026-11-24T21:00:00+01:00")


def test_google_reads_an_event_and_treats_gone_or_cancelled_as_missing():
    calendar = FakeGoogleCalendar(ENTRY, {**ENTRY, "id": "c1", "status": "cancelled"})
    writer = google_writer(calendar)
    assert writer.existing_event("e1").summary == "Elternabend"
    assert writer.existing_event("c1") is None
    assert writer.existing_event("missing") is None  # 410 Gone
    calendar.fail[("GET", "get")] = httpx.Response(404)
    assert writer.existing_event("e1") is None


def test_google_reports_an_unreadable_answer_and_access_errors():
    calendar = FakeGoogleCalendar(ENTRY)
    calendar.fail[("GET", "get")] = httpx.Response(200, json={"summary": "ohne id"})
    with pytest.raises(ValueError, match="ungültige Antwort"):
        google_writer(calendar).existing_event("e1")
    calendar.fail[("GET", "get")] = httpx.Response(401)
    with pytest.raises(Exception, match="Access-Token"):
        google_writer(calendar).existing_event("e1")


def caldav(server):
    return CalDavCalendar(COLLECTION, "anna", "app-password", transport=httpx.MockTransport(server),
                          calendar_timezone="Europe/Berlin")


def test_caldav_reads_an_event_and_treats_gone_or_cancelled_as_missing():
    server = FakeDav()
    server.resources[COLLECTION + "a.ics"] = vevent("a", "Elternabend", "20261124T183000Z", "20261124T200000Z")
    server.resources[COLLECTION + "c.ics"] = vevent("c", "Elternabend", "20261124T183000Z", "20261124T200000Z").replace(
        b"END:VEVENT", b"STATUS:CANCELLED\r\nEND:VEVENT")
    server.resources[COLLECTION + "t.ics"] = (b"BEGIN:VCALENDAR\r\nBEGIN:VTODO\r\nUID:t\r\nSUMMARY:Aufgabe\r\n"
                                              b"END:VTODO\r\nEND:VCALENDAR\r\n")
    writer = caldav(server)
    found = writer.existing_event(COLLECTION + "a.ics")
    assert (found.id, found.summary) == (COLLECTION + "a.ics", "Elternabend")
    assert writer.existing_event(COLLECTION + "c.ics") is None
    assert writer.existing_event(COLLECTION + "weg.ics") is None
    # Regression 4.6.4: a resource without one plain event exists and is not "gone".
    with pytest.raises(PermanentError, match="nicht sicher ändern"):
        writer.existing_event(COLLECTION + "t.ics")
    with pytest.raises(ValueError, match="außerhalb der konfigurierten Sammlung"):
        writer.existing_event("https://fremd.example.test/x.ics")


def test_caldav_refuses_an_entry_that_became_a_series_between_check_and_write():
    from mailhelp.external.confirmed import execute_confirmed
    from mailhelp.models import Proposal, ProposalStatus
    server = FakeDav()
    url = COLLECTION + "a.ics"
    plain = vevent("a", "Elternabend", "20261124T183000Z", "20261124T200000Z")
    server.resources[url] = plain
    reads = []

    def get(request):
        if str(request.url) != url:
            return httpx.Response(404)  # the reconciliation resource of the key does not exist
        reads.append(request)
        content = plain if len(reads) == 1 else plain.replace(b"END:VEVENT", b"RRULE:FREQ=WEEKLY\r\nEND:VEVENT")
        return httpx.Response(200, content=content, headers={"ETag": '"e1"'})

    server.fail["GET"] = get
    change = Proposal.model_validate(dict(
        schema_version=3, id="p1", version=1, kind="event", responsibility="user", certainty="certain",
        classification="change", title="Elternabend", evidence="x", source_mail_id="a" * 24, target=COLLECTION,
        status="confirmed", target_event_id=url, confirmed_web_actor=None,
        start="2026-11-25T18:30:00+00:00", end="2026-11-25T20:00:00+00:00"))
    result, _ = execute_confirmed(change, caldav(server), lambda _: None)
    assert result.status == ProposalStatus.FAILED and len(reads) == 2
    assert not any(request.method == "PUT" for request in server.requests)


class Token:
    def access_token(self):
        return "graph-token"

    def invalidate(self):
        return None


def outlook(answer):
    return OutlookCalendar(Token(), "default", transport=httpx.MockTransport(answer))


GRAPH_EVENT = {"id": "o1", "subject": "Elternabend", "isAllDay": False, "isCancelled": False,
               "start": {"dateTime": "2026-11-24T18:30:00.0000000", "timeZone": "UTC"},
               "end": {"dateTime": "2026-11-24T20:00:00.0000000", "timeZone": "UTC"}}


def test_outlook_reads_an_event_and_treats_gone_or_cancelled_as_missing():
    requests = []

    def graph(request):
        requests.append(request)
        return httpx.Response(200, json=GRAPH_EVENT)

    assert outlook(graph).existing_event("o/1").summary == "Elternabend"
    assert requests[0].url.raw_path.decode().startswith("/v1.0/me/calendar/events/o%2F1?")
    assert outlook(lambda request: httpx.Response(200, json={**GRAPH_EVENT, "isCancelled": True})).existing_event(
        "o1") is None
    assert outlook(lambda request: httpx.Response(404)).existing_event("o1") is None
    assert outlook(lambda request: httpx.Response(410)).existing_event("o1") is None


def test_outlook_reports_an_unreadable_answer():
    with pytest.raises(ValueError, match="ungültige Antwort"):
        outlook(lambda request: httpx.Response(200, content=b"kein json")).existing_event("o1")
    with pytest.raises(ValueError, match="ungültige Antwort"):
        outlook(lambda request: httpx.Response(200, json={"subject": "ohne id"})).existing_event("o1")
