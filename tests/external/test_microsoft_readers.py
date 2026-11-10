"""5.2 V5: fresh reads of Outlook events and Microsoft To Do tasks through the real Graph adapter.

Microsoft Graph is simulated by ``httpx.MockTransport``; all values are synthetic.
"""
import json
from datetime import date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import httpx
import pytest

from mailhelp import state_names
from mailhelp.domain.verification import VerificationState
from mailhelp.external.confirmed import execute_confirmed
from mailhelp.external.contracts import CalendarAccessError
from mailhelp.external.microsoft import MicrosoftTodo, OutlookCalendar
from mailhelp.models import ProposalStatus
from mailhelp.processing.write_verification import WriteVerifications
from mailhelp.storage import JsonStore
from tests.scenarios.web_scenario import proposal

BERLIN = ZoneInfo("Europe/Berlin")
TOKEN = SimpleNamespace(access_token=lambda: "synthetic-token", invalidate=lambda: None)


class Graph:
    """Stores posted events and tasks and answers like Graph: UTC with seven decimals, text bodies."""

    def __init__(self):
        self.items, self.override, self.requests = {}, {}, []

    def handle(self, request):
        path = request.url.path
        self.requests.append((request.method, path))
        if path in self.override:
            answer = self.override[path]
            return answer(request) if callable(answer) else answer
        if request.method == "POST":
            body = json.loads(request.content)
            body["id"] = f"m{len(self.items) + 1}"
            for name in ("start", "end", "dueDateTime"):
                if name in body:
                    body[name] = {**body[name], "dateTime": body[name]["dateTime"] + ".0000000"}
            body["webLink"] = f"https://outlook.example.invalid/{body['id']}"
            self.items[body["id"]] = body
            return httpx.Response(201, json=body)
        if path == "/v1.0/me":
            return httpx.Response(200, json={"id": "graph-user-1", "displayName": "Synthetisch"})
        if "/events/" in path or "/tasks/" in path:
            item = self.items.get(path.rsplit("/", 1)[1])
            return httpx.Response(200, json=item) if item else httpx.Response(404)
        return httpx.Response(200, json={"value": [], "id": "liste"})

    def outlook(self, target="default"):
        return OutlookCalendar(TOKEN, target, transport=httpx.MockTransport(self.handle))

    def todo(self, target="liste-1"):
        return MicrosoftTodo(TOKEN, target, transport=httpx.MockTransport(self.handle))


def event(**fields):
    values = dict(status="confirmed", confirmed_web_actor=None, kind="event", title="Elternabend",
                  target="default", start=datetime(2026, 7, 2, 19, tzinfo=BERLIN),
                  end=datetime(2026, 7, 2, 21, tzinfo=BERLIN), location="Aula", description="Agenda")
    values.update(fields)
    return proposal(3, "e", **values)


def task(**fields):
    values = dict(status="confirmed", confirmed_web_actor=None, title="Formular abgeben", target="liste-1",
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


@pytest.mark.parametrize("item", [event(), event(start=date(2026, 7, 2), end=date(2026, 7, 3), all_day=True,
                                                 location=None, description="")])
def test_an_outlook_event_is_verified_by_a_fresh_read(tmp_path, item):
    graph = Graph()
    created, record = write_and_check(tmp_path, graph.outlook(), item)
    assert created.status == ProposalStatus.CREATED and record.state == VerificationState.VERIFIED
    assert record.target.account == "graph-user-1" and record.target.container == "default"
    assert ("GET", "/v1.0/me/calendar/events/m1") in graph.requests


def test_an_outlook_event_moved_by_hand_is_a_mismatch(tmp_path):
    graph = Graph()
    graph.override["/v1.0/me/calendar/events/m1"] = lambda request: httpx.Response(200, json={
        **graph.items["m1"], "start": {"dateTime": "2026-07-02T18:00:00.0000000", "timeZone": "UTC"}})
    created, record = write_and_check(tmp_path, graph.outlook(), event())
    assert created.status == ProposalStatus.VERIFYING and set(record.differences) == {"start"}


def test_a_cancelled_or_deleted_outlook_event_is_not_visible():
    graph = Graph()
    writer = graph.outlook("kal-1")
    graph.items["c1"] = {"id": "c1", "subject": "X", "start": {"dateTime": "2026-07-02T17:00:00.0000000"},
                         "end": {"dateTime": "2026-07-02T18:00:00.0000000"}, "isCancelled": True}
    assert writer.read_entry("c1") is None
    assert writer.read_entry("fehlt") is None
    assert ("GET", "/v1.0/me/calendars/kal-1") in graph.requests  # 404 only counts with a reachable calendar


def test_outlook_read_errors_and_identity():
    graph = Graph()
    writer = graph.outlook()
    graph.override["/v1.0/me/calendar"] = httpx.Response(404)
    with pytest.raises(CalendarAccessError):
        writer.read_entry("fehlt")
    graph.override["/v1.0/me/calendar/events/a"] = httpx.Response(200, content=b"kein json")
    with pytest.raises(ValueError, match="<json>"):
        writer.read_entry("a")
    graph.override["/v1.0/me/calendar/events/a"] = httpx.Response(200, json=["liste"])
    with pytest.raises(ValueError, match="<root>"):
        writer.read_entry("a")
    graph.override["/v1.0/me/calendar/events/a"] = httpx.Response(200, json={"id": "a"})
    with pytest.raises(ValueError, match="Outlook"):
        writer.read_entry("a")
    assert writer.account_binding() == "graph-user-1"
    graph.override["/v1.0/me"] = httpx.Response(200, json={"displayName": "ohne id"})
    with pytest.raises(ValueError, match="Outlook-Kalender: ungültige Antwort am Schlüsselpfad id"):
        writer.account_binding()
    assert writer.expected_facts(task(), "k") is None


@pytest.mark.parametrize("due", [date(2026, 11, 11), datetime(2026, 11, 11, 23, 30, tzinfo=BERLIN), None])
def test_a_todo_task_is_verified_at_the_day_precision_of_the_provider(tmp_path, due):
    graph = Graph()
    created, record = write_and_check(tmp_path, graph.todo(), task(due=due))
    assert created.status == ProposalStatus.CREATED and record.state == VerificationState.VERIFIED
    assert record.expected["due"] == (None if due is None else "2026-11-11")  # 23:30 Berlin is still the 11th
    assert ("GET", "/v1.0/me/todo/lists/liste-1/tasks/m1") in graph.requests


def test_a_todo_task_with_another_day_or_title_is_a_mismatch(tmp_path):
    graph = Graph()
    graph.override["/v1.0/me/todo/lists/liste-1/tasks/m1"] = lambda request: httpx.Response(200, json={
        **graph.items["m1"], "title": "Formular abgegeben", "dueDateTime": None})
    _created, record = write_and_check(tmp_path, graph.todo(), task())
    assert set(record.differences) == {"title", "due"}


def test_a_completed_todo_task_still_exists_and_a_deleted_one_does_not():
    graph = Graph()
    writer = graph.todo()
    graph.items["d1"] = {"id": "d1", "title": "Erledigt", "status": "completed",
                         "body": {"content": "Text", "contentType": "text"}}
    found = writer.read_entry("d1")
    assert found.completed and found.facts["description"] == "Text" and found.facts["due"] is None
    assert writer.read_entry("weg") is None
    assert ("GET", "/v1.0/me/todo/lists/liste-1") in graph.requests
    assert writer.expected_facts(event(), "k") is None
