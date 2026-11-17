"""7.4 (M5): a timed event over two days is written as one span by Google Calendar, CalDAV and Outlook."""
import json

import httpx

from mailhelp.domain.proposal import ProposalStatus
from mailhelp.external.caldav import CalDavCalendar
from mailhelp.external.confirmed import execute_confirmed
from mailhelp.external.http_writer import HttpWriter
from mailhelp.external.microsoft import OutlookCalendar
from tests.fakes.dav_fakes import COLLECTION, FakeDav
from tests.fakes.shared_core import proposal

START, END = "2027-01-07T11:30:00+01:00", "2027-01-08T12:30:00+01:00"


class Token:
    def access_token(self):
        return "access-synthetic"

    def invalidate(self):
        return None


def span(target):
    return proposal(kind="event", status="confirmed", target=target, start=START, end=END,
                    title="Vlf Schulungstagung")


def test_google_calendar_writes_both_days():
    posted = []

    def google(request):
        if request.method == "POST":
            posted.append(json.loads(request.content))
            return httpx.Response(200, json={"id": "evt-1", "htmlLink": "https://calendar.google.com/x"})
        return httpx.Response(200, json={"items": []})
    writer = HttpWriter("google_calendar", "token", "primary", transport=httpx.MockTransport(google),
                        calendar_timezone="Europe/Berlin")
    created, _ = execute_confirmed(span("primary"), writer, lambda value: None)
    assert created.status == ProposalStatus.CREATED
    assert posted[0]["start"]["dateTime"].startswith("2027-01-07T11:30:00")
    assert posted[0]["end"]["dateTime"].startswith("2027-01-08T12:30:00")


def test_caldav_writes_both_days():
    server = FakeDav()
    writer = CalDavCalendar(COLLECTION, "anna", "app-password", transport=httpx.MockTransport(server),
                            calendar_timezone="Europe/Berlin")
    created, _ = execute_confirmed(span(COLLECTION), writer, lambda value: None)
    body = server.resources[created.external_id].decode()
    assert "DTSTART:20270107T103000Z" in body and "DTEND:20270108T113000Z" in body


def test_outlook_writes_both_days():
    posted = []

    def graph(request):
        if request.method == "POST":
            posted.append(json.loads(request.content))
            return httpx.Response(201, json={"id": "evt-1", "start": {}, "end": {}})
        return httpx.Response(200, json={"value": []})
    writer = OutlookCalendar(Token(), "default", transport=httpx.MockTransport(graph),
                             calendar_timezone="Europe/Berlin")
    created, _ = execute_confirmed(span("default"), writer, lambda value: None)
    assert created.status == ProposalStatus.CREATED and posted[0]["isAllDay"] is False
    assert posted[0]["start"] == {"dateTime": "2027-01-07T10:30:00", "timeZone": "UTC"}
    assert posted[0]["end"] == {"dateTime": "2027-01-08T11:30:00", "timeZone": "UTC"}
