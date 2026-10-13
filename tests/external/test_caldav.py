"""CalDAV calendars and task lists against a simulated server (Planung 2.3, 4.1/4.4/4.5)."""
from datetime import UTC, date, datetime

import httpx
import pytest
from dav_fakes import COLLECTION, FakeDav, item, multistatus
from log_fakes import RecordingLogger
from shared_core import proposal
from shared_write_improvements import event

from mailhelp.adapter import RetryableError, RetryPolicy
from mailhelp.external.caldav import AppleReminders, CalDavCalendar, CalDavTasks, _xml
from mailhelp.external.confirmed import execute_confirmed
from mailhelp.external.contracts import AuthenticationError, CalendarAccessError
from mailhelp.external.icalendar_data import resource_uid
from mailhelp.models import CalendarDuplicateDecision, ProposalStatus

TASKS = "https://dav.example.test/remote.php/dav/calendars/anna/tasks/"
KEY = "mailhelp:" + "a" * 24 + ":p1:v1"


def calendar(server, matcher=None, logger=None):
    return CalDavCalendar(COLLECTION, "anna", "app-password", transport=httpx.MockTransport(server),
                          logger=logger, calendar_timezone="Europe/Berlin", calendar_matcher=matcher)


def tasks(server, kind=CalDavTasks, logger=None, url=TASKS):
    return kind(url, "anna", "app-password", transport=httpx.MockTransport(server), logger=logger)


def confirm(item_, writer):
    saved = []
    result, _ = execute_confirmed(item_, writer, saved.append)
    return result, [value.status.value for value in saved]


def existing(server, summary="Elternabend", extra="", start="20260510T100000Z", end="20260510T110000Z",
             name="fremd.ics"):
    url = COLLECTION + name
    server.resources[url] = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Andere//DE\r\nBEGIN:VEVENT\r\nUID:fremd-1\r\n"
        f"SUMMARY:{summary}\r\nDTSTART:{start}\r\nDTEND:{end}\r\nX-FREMD:bleibt\r\n{extra}"
        "BEGIN:VALARM\r\nACTION:DISPLAY\r\nEND:VALARM\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n").encode()
    return url


def test_event_is_created_once_and_a_repeated_put_reconciles_instead_of_duplicating():
    server = FakeDav()
    logger = RecordingLogger()
    writer = calendar(server, logger=logger)
    item_ = event(status="confirmed", target=COLLECTION, description="Agenda", location="Aula",
                  video_link="https://meet.google.com/abc-defg-hij")
    created, statuses = confirm(item_, writer)
    assert created.status == ProposalStatus.CREATED and statuses == ["writing", "created"]
    url = COLLECTION + resource_uid(f"mailhelp:{item_.source_mail_id}:p1:v1") + ".ics"
    assert created.external_id == url and created.external_link is None
    put = next(request for request in server.requests if request.method == "PUT")
    assert put.headers["If-None-Match"] == "*" and put.headers["Authorization"].startswith("Basic ")
    body = server.resources[url].decode()
    assert "SUMMARY:Tun" in body and "LOCATION:Aula" in body and "DTSTART:20260510T100000Z" in body
    assert "meet.google.com" in body and "X-MAILHELP-KEY:mailhelp:" in body
    # A restart while WRITING only reconciles: GET finds the resource, nothing is written again.
    writing = item_.model_copy(update={"status": ProposalStatus.WRITING})
    again, _ = confirm(writing, writer)
    assert again.status == ProposalStatus.CREATED and [r.method for r in server.requests].count("PUT") == 1
    # The resource name is the idempotency: a second create answers 412 and counts as present.
    assert writer._put_new(f"mailhelp:{item_.source_mail_id}:p1:v1", b"x") == {"id": url,
                                                                               "operation": "already_present"}
    events = [entry[0][2] for entry in logger.events]
    assert "create_started" in events and "create_completed" in events and "reconcile_started" in events
    assert all("app-password" not in str(fields) for _, fields in logger.events)
    writer.close()


def test_all_day_event_and_timeout_leave_an_uncertain_write():
    server = FakeDav()
    writer = calendar(server)
    whole_day = proposal(kind="event", status="confirmed", target=COLLECTION, start="2026-05-10",
                         end="2026-05-11", all_day=True)
    created, _ = confirm(whole_day, writer)
    stored = next(iter(server.resources.values())).decode()
    assert "DTSTART;VALUE=DATE:20260510" in stored and "DTEND;VALUE=DATE:20260511" in stored

    def timeout(request):
        raise httpx.ReadTimeout("synthetic", request=request)

    server.fail["PUT"] = timeout
    pending, statuses = confirm(event(status="confirmed", target=COLLECTION, id="p2"), writer)
    assert pending.status == ProposalStatus.UNCERTAIN and statuses == ["writing", "uncertain"]
    del server.fail["PUT"]
    # Still uncertain after a restart: the resource is missing, so nothing is sent blindly.
    still, _ = confirm(pending, writer)
    assert still.status == ProposalStatus.UNCERTAIN


def test_target_kind_and_permanent_failures():
    server = FakeDav()
    writer = calendar(server)
    with pytest.raises(ValueError, match="Ziel weicht"):
        writer.prepare(event(status="confirmed", target="anderes"), KEY)
    with pytest.raises(ValueError, match="nur Termine"):
        writer.prepare(proposal(status="confirmed", target=COLLECTION), KEY)
    with pytest.raises(ValueError, match="nicht extern angelegt"):
        writer.prepare(event(status="confirmed", target=COLLECTION, responsibility="other"), KEY)
    server.fail["PUT"] = lambda request: httpx.Response(400)
    failed, _ = confirm(event(status="confirmed", target=COLLECTION), writer)
    assert failed.status == ProposalStatus.FAILED


@pytest.mark.parametrize(("status", "error", "event_name"), [
    (401, AuthenticationError, "authentication_failed"), (403, CalendarAccessError, "target_access_failed"),
    (404, CalendarAccessError, "target_access_failed"), (405, CalendarAccessError, "target_access_failed")])
def test_access_errors_are_classified_without_content(status, error, event_name):
    server = FakeDav()
    server.fail["PROPFIND"] = lambda request: httpx.Response(status, text="geheime Serverantwort")
    logger = RecordingLogger()
    with pytest.raises(error) as raised:
        calendar(server, logger=logger).check_access()
    assert "geheime" not in str(raised.value)
    assert logger.events[-1] == (("ERROR", "caldav_calendar", event_name), {"status": status})


def test_access_check_requires_a_calendar_collection_for_the_component():
    assert calendar(FakeDav()).check_access() is None
    with pytest.raises(CalendarAccessError, match="keine CalDAV-Kalendersammlung"):
        calendar(FakeDav(calendar=False)).check_access()
    with pytest.raises(CalendarAccessError, match="keine VTODO-Einträge"):
        tasks(FakeDav(components=("VEVENT",))).check_access()
    # Servers that do not report the supported components are accepted.
    assert tasks(FakeDav(components=())).check_access() is None
    with pytest.raises(CalendarAccessError, match="neuen iCloud-Erinnerungen"):
        tasks(FakeDav(components=("VEVENT",)), AppleReminders).check_access()
    missing = FakeDav()
    missing.fail["PROPFIND"] = lambda request: httpx.Response(404)
    with pytest.raises(CalendarAccessError, match="über CalDAV nicht erreichbar"):
        tasks(missing, AppleReminders).check_access()


def test_retryable_answers_are_retried_and_then_reported():
    server = FakeDav()
    server.fail["PROPFIND"] = lambda request: httpx.Response(503)
    waits = []
    writer = CalDavCalendar(COLLECTION, "u", "p", transport=httpx.MockTransport(server),
                            policy=RetryPolicy(2, 1, 4, lambda delay: waits.append(delay) or False))
    with pytest.raises(RetryableError):
        writer.check_access()
    assert waits == [1, 2] and len(server.requests) == 3


def test_untrusted_xml_and_foreign_resources_are_refused():
    with pytest.raises(ValueError, match="unzulässige"):
        _xml(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><x/>')
    with pytest.raises(ValueError, match="unzulässige"):
        _xml(b"<x>" + b" " * 5_000_001 + b"</x>")
    with pytest.raises(ValueError, match="ungültige XML"):
        _xml(b"<nicht-geschlossen>")
    writer = calendar(FakeDav())
    for href in ("https://andere.example/x.ics", "/remote.php/dav/calendars/anna/other/x.ics",
                 "/remote.php/dav/calendars/anna/personal/", "/remote.php/dav/calendars/anna/personal/../x.ics"):
        with pytest.raises(ValueError, match="außerhalb"):
            writer._member(href)
    assert writer._member("a.ics") == COLLECTION + "a.ics"


def test_duplicate_found_by_the_matcher_is_completed_with_if_match():
    server = FakeDav()
    url = existing(server)
    decisions = []

    def matcher(proposal_, safe):
        decisions.append(safe)
        return "call", CalendarDuplicateDecision(same_event=True, missing_fields=["description", "location"],
                                                 reason="synthetisch")

    writer = calendar(server, matcher)
    item_ = event(status="confirmed", target=COLLECTION, description="Agenda", location="Aula")
    result, statuses = confirm(item_, writer)
    assert result.status == ProposalStatus.CREATED and statuses == ["writing", "created"]
    assert result.external_id == url and decisions[0]["summary"] == "Elternabend"
    put = [request for request in server.requests if request.method == "PUT"][-1]
    assert put.headers["If-Match"].startswith('"')
    body = server.resources[url].decode()
    assert "X-FREMD:bleibt" in body and "BEGIN:VALARM" in body and "DESCRIPTION:Agenda" in body
    assert "LOCATION:Aula" in body and "SEQUENCE:1" in body and "SUMMARY:Elternabend" in body


def test_confirmed_new_time_moves_the_existing_event_and_notes_the_change():
    server = FakeDav()
    url = existing(server, start="20260510T090000Z", end="20260510T100000Z", extra="SEQUENCE:4\r\n")
    writer = calendar(server, lambda *_: ("call", CalendarDuplicateDecision(same_event=True, reason="x")))
    result, _ = confirm(event(status="confirmed", target=COLLECTION), writer)
    body = server.resources[url].decode()
    assert result.status == ProposalStatus.CREATED
    assert "DTSTART:20260510T100000Z" in body and "SEQUENCE:5" in body and "Zeit aktualisiert" in body


def test_identical_existing_event_is_not_written_again():
    server = FakeDav()
    existing(server, extra="SEQUENCE:x\r\n")
    writer = calendar(server, lambda *_: ("call", CalendarDuplicateDecision(same_event=True, reason="x")))
    result, statuses = confirm(event(status="confirmed", target=COLLECTION), writer)
    assert result.status == ProposalStatus.CREATED and statuses == ["created"]
    assert not any(request.method == "PUT" for request in server.requests)


def test_cancellation_and_concurrent_changes():
    server = FakeDav()
    url = existing(server)
    writer = calendar(server)
    cancel = event(status="confirmed", target=COLLECTION, classification="cancellation", target_event_id=url,
                   is_cancellation=True)
    result, _ = confirm(cancel, writer)
    body = server.resources[url].decode()
    assert result.status == ProposalStatus.CREATED and "STATUS:CANCELLED" in body and "SEQUENCE:1" in body
    # Someone changed the event between GET and PUT: nothing is overwritten.
    server.fail["PUT"] = lambda request: httpx.Response(412)
    changed, _ = confirm(cancel.model_copy(update={"id": "p2"}), writer)
    assert changed.status == ProposalStatus.FAILED
    del server.fail["PUT"]
    server.etags = False
    no_etag, _ = confirm(cancel.model_copy(update={"id": "p3"}), writer)
    assert no_etag.status == ProposalStatus.FAILED
    # Series are never changed.
    series = existing(server, name="serie.ics", extra="RRULE:FREQ=WEEKLY\r\n")
    server.etags = True
    moved, _ = confirm(cancel.model_copy(update={"id": "p4", "target_event_id": series}), writer)
    assert moved.status == ProposalStatus.FAILED and b"STATUS:CANCELLED" not in server.resources[series]


def test_events_in_window_skip_series_cancelled_and_incomplete_entries():
    server = FakeDav()
    existing(server, name="a.ics")
    existing(server, name="b.ics", extra="STATUS:CANCELLED\r\n")
    existing(server, name="c.ics", extra="RRULE:FREQ=DAILY\r\n")
    server.resources[COLLECTION + "d.ics"] = (
        b"BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:x\r\nSUMMARY:ohne Beginn\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    server.resources[COLLECTION + "e.ics"] = (
        b"BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:y\r\nDTSTART;VALUE=DATE:20260510\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    writer = calendar(server)
    events = writer.fetch_events_in_window(date(2026, 5, 9), date(2026, 5, 12))
    assert [entry.id for entry in events] == [COLLECTION + "a.ics", COLLECTION + "e.ics"]
    assert events[0].start == {"dateTime": "2026-05-10T10:00:00+00:00"}
    assert events[1].start == events[1].end == {"date": "2026-05-10"}
    report = [request for request in server.requests if request.method == "REPORT"][0]
    assert b'start="20260509T000000Z" end="20260512T000000Z"' in report.content
    count = len(server.requests)
    assert writer.fetch_events_in_window(date(2026, 5, 9), date(2026, 5, 12)) == events
    assert len(server.requests) == count


def test_unreadable_window_is_empty_unless_strict():
    server = FakeDav()
    server.fail["REPORT"] = lambda request: httpx.Response(207, content=b"<kaputt")
    logger = RecordingLogger()
    writer = calendar(server, logger=logger)
    start, end = datetime(2026, 5, 10, tzinfo=UTC), datetime(2026, 5, 11, tzinfo=UTC)
    assert writer.fetch_events_in_window(start, end) == []
    assert logger.events[-1][0] == ("WARNING", "caldav_calendar", "fetch_events_failed")
    with pytest.raises(ValueError):
        writer.fetch_events_in_window(start, end, strict=True)
    # Answers without address or data are ignored; foreign addresses stop the read.
    server.fail["REPORT"] = lambda request: httpx.Response(207, content=multistatus(
        item("/remote.php/dav/calendars/anna/personal/x.ics", None), "<d:response></d:response>"))
    assert writer.fetch_events_in_window(start, end, strict=True) == []
    server.fail["REPORT"] = lambda request: httpx.Response(207, content=multistatus(
        item("https://fremd.example/x.ics", "BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n")))
    with pytest.raises(ValueError, match="außerhalb"):
        writer.fetch_events_in_window(start, datetime(2026, 5, 12, tzinfo=UTC), strict=True)


def test_tasks_are_created_with_due_dates_and_open_tasks_listed():
    server = FakeDav(collection=TASKS)
    logger = RecordingLogger()
    writer = tasks(server, logger=logger)
    assert writer.fetch_events_in_window(None, None) == []
    created, _ = confirm(proposal(status="confirmed", target=TASKS, description="Formular", due="2026-05-12"),
                         writer)
    timed, _ = confirm(proposal(status="confirmed", target=TASKS, id="p2", due="2026-05-12T08:00:00+02:00"), writer)
    plain, _ = confirm(proposal(status="confirmed", target=TASKS, id="p3"), writer)
    assert created.status == timed.status == plain.status == ProposalStatus.CREATED
    bodies = [server.resources[value.external_id].decode() for value in (created, timed, plain)]
    assert "DUE;VALUE=DATE:20260512" in bodies[0] and "DESCRIPTION:Formular\\n\\n[mailhelp:" in bodies[0]
    assert "DUE:20260512T060000Z" in bodies[1] and "DUE" not in bodies[2]
    assert "STATUS:NEEDS-ACTION" in bodies[2]
    server.resources[TASKS + "erledigt.ics"] = (
        b"BEGIN:VCALENDAR\r\nBEGIN:VTODO\r\nUID:z\r\nSUMMARY:Alt\r\nSTATUS:COMPLETED\r\nEND:VTODO\r\nEND:VCALENDAR\r\n")
    server.resources[TASKS + "fertig.ics"] = (
        b"BEGIN:VCALENDAR\r\nBEGIN:VTODO\r\nUID:w\r\nSUMMARY:Alt\r\nCOMPLETED:20260101T000000Z\r\n"
        b"END:VTODO\r\nEND:VCALENDAR\r\n")
    server.resources[TASKS + "termin.ics"] = (
        b"BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:v\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    open_tasks = writer.fetch_active_tasks()
    assert sorted(task.content for task in open_tasks) == ["Tun", "Tun", "Tun"]
    assert writer.fetch_active_tasks() == open_tasks
    with pytest.raises(ValueError, match="nur Aufgaben"):
        writer.prepare(event(status="confirmed", target=TASKS), KEY)
    server_down = FakeDav(collection=TASKS)
    server_down.fail["REPORT"] = lambda request: httpx.Response(500)
    assert tasks(server_down, logger=logger).fetch_active_tasks() == []
    assert logger.events[-1][0] == ("WARNING", "caldav_tasks", "fetch_tasks_failed")
    assert writer.reconcile("unbekannt") is None
    writer.close()


def test_apple_reminders_use_the_icloud_preset_label():
    server = FakeDav(collection="https://p52-caldav.icloud.com/123/calendars/erinnerungen/")
    writer = tasks(server, AppleReminders, url="https://p52-caldav.icloud.com/123/calendars/erinnerungen/")
    assert (writer.service, writer.label, writer.role) == ("apple_reminders", "Apple Erinnerungen", "tasks")
    created, _ = confirm(proposal(status="confirmed", target=writer.target), writer)
    assert created.status == ProposalStatus.CREATED
