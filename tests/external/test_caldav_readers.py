"""5.2 V6: CalDAV events and tasks (also Apple Erinnerungen) are verified by reading their resource again.

The server is the in-memory ``FakeDav``; every value is synthetic.
"""
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from mailhelp import state_names
from mailhelp.domain.verification import VerificationState
from mailhelp.external.caldav import AppleReminders, CalDavCalendar, CalDavTasks
from mailhelp.external.confirmed import execute_confirmed
from mailhelp.external.contracts import CalendarAccessError
from mailhelp.external.icalendar_data import resource_uid
from mailhelp.models import ProposalStatus
from mailhelp.processing.write_verification import WriteVerifications
from mailhelp.storage import JsonStore
from tests.fakes.dav_fakes import COLLECTION, FakeDav
from tests.scenarios.web_scenario import mail_id, proposal

BERLIN = ZoneInfo("Europe/Berlin")
TASKS = "https://dav.example.test/remote.php/dav/calendars/anna/tasks/"


def calendar(server):
    return CalDavCalendar(COLLECTION, "anna", "app-password", transport=httpx.MockTransport(server),
                          calendar_timezone="Europe/Berlin")


def tasks(server, kind=CalDavTasks):
    return kind(TASKS, "anna", "app-password", transport=httpx.MockTransport(server))


def event(**fields):
    values = dict(status="confirmed", confirmed_web_actor=None, kind="event", title="Elternabend; Klasse 4b",
                  target=COLLECTION, start=datetime(2026, 7, 2, 19, tzinfo=BERLIN),
                  end=datetime(2026, 7, 2, 21, tzinfo=BERLIN), location="Aula, Haus B",
                  description="Agenda\nZeile 2")
    values.update(fields)
    return proposal(3, "e", **values)


def task(**fields):
    values = dict(status="confirmed", confirmed_web_actor=None, title="Formular, unterschrieben", target=TASKS,
                  due=date(2026, 11, 11))
    values.update(fields)
    return proposal(3, "t", **values)


def write_and_check(tmp_path, writer, item):
    with JsonStore(tmp_path / "data") as store:
        checks = WriteVerifications(store)

        def persist(value):
            store.save(state_names.proposal(value.source_mail_id, value.id), value.model_dump(mode="json"))

        persist(item)
        verifying, _ = execute_confirmed(item, writer, persist, verification=checks)
        assert verifying.status == ProposalStatus.VERIFYING
        return checks.check(verifying, writer, persist)


def resource(item, base):
    return base + resource_uid(f"mailhelp:{mail_id(3)}:{item.id}:v1") + ".ics"


@pytest.mark.parametrize("item", [event(), event(start=date(2026, 7, 2), end=date(2026, 7, 3), all_day=True,
                                                 location=None, description="")])
def test_a_caldav_event_is_verified_with_its_uid(tmp_path, item):
    server = FakeDav()
    created, record = write_and_check(tmp_path, calendar(server), item)
    assert created.status == ProposalStatus.CREATED and record.state == VerificationState.VERIFIED
    assert record.expected["uid"] == resource_uid(f"mailhelp:{mail_id(3)}:e:v1")
    assert record.target.account == "anna@dav.example.test" and created.external_id == resource(item, COLLECTION)
    assert [request.method for request in server.requests].count("PUT") == 1


def test_a_changed_uid_or_time_is_a_mismatch(tmp_path):
    server = FakeDav()
    original = server.__call__

    def edited(request):
        answer = original(request)
        if request.method == "GET" and answer.status_code == 200:
            text = answer.content.decode().replace("UID:mailhelp-", "UID:fremd-").replace(
                "DTSTART:20260702T170000Z", "DTSTART:20260702T180000Z")
            return httpx.Response(200, content=text.encode())
        return answer

    _created, record = write_and_check(tmp_path, calendar(edited), event())
    assert record.state == VerificationState.MISMATCH and set(record.differences) == {"uid", "start"}


def test_a_cancelled_deleted_or_unreadable_event(tmp_path):
    server = FakeDav()
    writer = calendar(server)
    url = COLLECTION + "x.ics"
    server.resources[url] = (b"BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:x\r\nSUMMARY:A\r\nSTATUS:CANCELLED\r\n"
                             b"DTSTART:20260702T170000Z\r\nDTEND:20260702T180000Z\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    assert writer.read_entry(url) is None
    assert writer.read_entry(COLLECTION + "weg.ics") is None
    assert [request.method for request in server.requests][-1] == "PROPFIND"  # 404 counts with a reachable collection
    server.resources[url] = (b"BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:x\r\nRRULE:FREQ=WEEKLY\r\n"
                             b"DTSTART:20260702T170000Z\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    with pytest.raises(ValueError, match="Serie"):
        writer.read_entry(url)
    server.calendar = False
    with pytest.raises(CalendarAccessError):
        writer.read_entry(COLLECTION + "weg.ics")


def test_reads_stay_inside_the_bound_collection(tmp_path):
    server = FakeDav()
    writer = calendar(server)
    for foreign in ("https://anderer.example.test/x.ics", COLLECTION + "../anna/x.ics", COLLECTION):
        with pytest.raises(ValueError, match="außerhalb"):
            writer.read_entry(foreign)
    assert server.requests == []
    assert writer.expected_facts(task(), "k") is None


@pytest.mark.parametrize("kind", [CalDavTasks, AppleReminders])
@pytest.mark.parametrize("due", [date(2026, 11, 11), datetime(2026, 11, 11, 9, 30, tzinfo=BERLIN), None])
def test_a_caldav_task_is_verified(tmp_path, kind, due):
    server = FakeDav(TASKS)
    created, record = write_and_check(tmp_path, tasks(server, kind), task(due=due))
    assert created.status == ProposalStatus.CREATED and record.state == VerificationState.VERIFIED
    assert record.expected["description"].endswith(f"[mailhelp:{mail_id(3)}:t:v1]")


def test_a_completed_task_exists_and_a_cancelled_one_does_not():
    server = FakeDav(TASKS)
    writer = tasks(server)
    url = TASKS + "t.ics"
    server.resources[url] = (b"BEGIN:VCALENDAR\r\nBEGIN:VTODO\r\nUID:t\r\nSUMMARY:Erledigt\r\nSTATUS:COMPLETED\r\n"
                             b"END:VTODO\r\nEND:VCALENDAR\r\n")
    found = writer.read_entry(url)
    assert found.completed and found.facts["due"] is None and found.facts["uid"] == "t"
    server.resources[url] = (b"BEGIN:VCALENDAR\r\nBEGIN:VTODO\r\nUID:t\r\nCOMPLETED:20261110T090000Z\r\n"
                             b"DUE;VALUE=DATE:20261111\r\nEND:VTODO\r\nEND:VCALENDAR\r\n")
    found = writer.read_entry(url)
    assert found.completed and found.facts["due"] == "2026-11-11"
    server.resources[url] = (b"BEGIN:VCALENDAR\r\nBEGIN:VTODO\r\nUID:t\r\nSTATUS:CANCELLED\r\n"
                             b"END:VTODO\r\nEND:VCALENDAR\r\n")
    assert writer.read_entry(url) is None
    assert writer.read_entry(TASKS + "weg.ics") is None
    server.resources[url] = b"BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:t\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    with pytest.raises(ValueError, match="keine Aufgabe"):
        writer.read_entry(url)
    assert writer.expected_facts(event(), "k") is None


def test_an_existing_resource_of_the_same_version_is_checked_like_a_find(tmp_path):
    server = FakeDav(TASKS)
    writer = tasks(server)
    execute_confirmed(task(), writer, lambda value: None)  # the same version was written before

    def missed_once(request):  # the lookup misses it; the guarded PUT then answers 412
        del server.fail["GET"]
        return httpx.Response(404)

    server.fail["GET"] = missed_once
    created, record = write_and_check(tmp_path, writer, task())
    assert record.state == VerificationState.VERIFIED and created.status == ProposalStatus.CREATED
    assert [request.method for request in server.requests].count("PUT") == 2  # the second one was refused


def test_every_online_writer_can_verify_its_entries():
    from mailhelp.external.http_writer import HttpWriter
    from mailhelp.external.microsoft import MicrosoftTodo, OutlookCalendar
    for cls in (HttpWriter, OutlookCalendar, MicrosoftTodo, CalDavCalendar, CalDavTasks, AppleReminders):
        assert all(callable(getattr(cls, name, None)) for name in ("account_binding", "expected_facts", "read_entry"))
