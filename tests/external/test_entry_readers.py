"""5.2 V3/V4: the fresh reads of Google Calendar and Todoist through the real HTTP adapter.

The providers are simulated by ``httpx.MockTransport``; every value is synthetic.
"""
import json
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from mailhelp import state_names
from mailhelp.domain.verification import VerificationState
from mailhelp.external.confirmed import execute_confirmed
from mailhelp.external.contracts import AuthenticationError, CalendarAccessError
from mailhelp.external.http_writer import HttpWriter
from mailhelp.llm.adapter import PermanentError
from mailhelp.models import ProposalStatus
from mailhelp.processing.write_verification import WriteVerifications
from mailhelp.storage import JsonStore
from tests.scenarios.web_scenario import proposal

BERLIN = ZoneInfo("Europe/Berlin")


class Service:
    """A minimal provider: stores what is posted and answers reads by id."""

    def __init__(self, provider):
        self.provider, self.items, self.requests = provider, {}, []
        self.override = {}
        self.completed = []
        self.raw_paths = []

    def handle(self, request):
        self.requests.append((request.method, request.url.path, dict(request.url.params)))
        self.raw_paths.append(request.url.raw_path)
        path = request.url.path
        if path in self.override:
            answer = self.override[path]
            return answer(request) if callable(answer) else answer
        if request.method == "POST":
            body = json.loads(request.content)
            body["id"] = f"id{len(self.items) + 1}"
            if self.provider == "todoist":
                due = body.pop("due_date", None) or body.pop("due_datetime", None)
                # Todoist keeps a fixed time point in UTC with Z.
                if due and "T" in due:
                    due = datetime.fromisoformat(due).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
                body["due"] = None if due is None else {"date": due, "is_recurring": False}
            else:
                body["htmlLink"] = f"https://calendar.example.invalid/{body['id']}"
            self.items[body["id"]] = body
            return httpx.Response(200, json=body)
        if path == "/api/v1/user":
            return httpx.Response(200, json={"id": "4711", "full_name": "Synthetisch"})
        if path.startswith("/api/v1/projects/"):
            return httpx.Response(200, json={"id": path.rsplit("/", 1)[1]})
        if path == "/api/v1/tasks/completed/by_completion_date":
            return httpx.Response(200, json={"items": self.completed, "next_cursor": None})
        if path.startswith("/api/v1/tasks/") or "/events/" in path:
            item = self.items.get(path.rsplit("/", 1)[1])
            return httpx.Response(200, json=item) if item else httpx.Response(404)
        if path.startswith("/calendar/v3/calendars/") and path.count("/") == 4:
            return httpx.Response(200, json={"id": "owner@example.test", "summary": "Kalender"})
        return httpx.Response(200, json={"results": [], "next_cursor": None, "items": []})

    def writer(self, target="Inbox"):
        return HttpWriter(self.provider, "synthetic-token", target, calendar_timezone="Europe/Berlin",
                          transport=httpx.MockTransport(self.handle))


def task(**fields):
    values = dict(status="confirmed", confirmed_web_actor=None, title="Unterlagen senden", due=date(2026, 11, 11))
    values.update(fields)
    return proposal(3, "a", **values)


def event(**fields):
    values = dict(status="confirmed", confirmed_web_actor=None, kind="event", title="Elternabend",
                  target="primary", start=datetime(2026, 7, 2, 19, tzinfo=BERLIN),
                  end=datetime(2026, 7, 2, 21, tzinfo=BERLIN), location="Aula", description="Agenda")
    values.update(fields)
    return proposal(3, "e", **values)


def write_and_check(tmp_path, service, item, target):
    with JsonStore(tmp_path / "data") as store:
        checks, saved = WriteVerifications(store), []
        writer = service.writer(target)

        def persist(value):
            saved.append(value)
            store.save(state_names.proposal(value.source_mail_id, value.id), value.model_dump(mode="json"))

        persist(item)
        verifying, result = execute_confirmed(item, writer, persist, verification=checks)
        assert verifying.status == ProposalStatus.VERIFYING and result["verifying"] is True
        created, record = checks.check(verifying, writer, persist)
        return created, record


@pytest.mark.parametrize("due", [date(2026, 11, 11), datetime(2026, 3, 29, 3, 30, tzinfo=BERLIN), None])
def test_a_todoist_task_is_verified_by_a_fresh_read(tmp_path, due):
    service = Service("todoist")
    created, record = write_and_check(tmp_path, service, task(due=due), "Inbox")
    assert created.status == ProposalStatus.CREATED and record.state == VerificationState.VERIFIED
    assert record.target.account == "4711" and record.target.container == "Inbox"
    methods = [(method, path) for method, path, _ in service.requests]
    assert methods.count(("POST", "/api/v1/tasks")) == 1 and ("GET", "/api/v1/tasks/id1") in methods


def test_a_todoist_task_with_another_due_date_is_a_mismatch(tmp_path):
    service = Service("todoist")
    service.override["/api/v1/tasks/id1"] = lambda request: httpx.Response(200, json={
        **service.items["id1"], "due": None})
    created, record = write_and_check(tmp_path, service, task(), "Inbox")
    assert created.status == ProposalStatus.VERIFYING and record.state == VerificationState.MISMATCH
    assert record.differences["due"].expected == "2026-11-11" and record.differences["due"].actual is None


def test_a_todoist_task_in_another_project_is_a_mismatch(tmp_path):
    service = Service("todoist")
    service.override["/api/v1/tasks/id1"] = lambda request: httpx.Response(200, json={
        **service.items["id1"], "project_id": 99})
    _created, record = write_and_check(tmp_path, service, task(), "Inbox")
    assert set(record.differences) == {"container"}


def test_a_completed_or_deleted_todoist_task(tmp_path):
    service = Service("todoist")
    writer = service.writer()
    service.items["t1"] = {"id": "t1", "content": "A", "project_id": "Inbox", "checked": True,
                           "due": {"datetime": "2026-11-11T09:00:00Z"}}
    service.items["t2"] = {"id": "t2", "content": "B", "project_id": "Inbox", "is_deleted": True}
    found = writer.read_entry("t1")
    assert found.completed and found.facts["due"] == "2026-11-11T09:00:00Z" and found.facts["title"] == "A"
    assert writer.read_entry("t2") is None
    service.items["t3"] = {"id": "t3", "content": "C", "project_id": "Inbox", "due": {"date": None}}
    assert writer.read_entry("t3").facts["due"] is None


def test_a_task_completed_before_its_check_is_not_missing(tmp_path):
    service = Service("todoist")
    writer = service.writer()
    pages = iter([{"items": [{"id": "x"}], "next_cursor": "c2"},
                  {"items": [{"id": 5, "content": "Erledigt", "project_id": "Inbox", "completed_at": "jetzt"}],
                   "next_cursor": None}])
    service.override["/api/v1/tasks/completed/by_completion_date"] = lambda request: httpx.Response(
        200, json=next(pages))
    found = writer.read_entry("5")
    assert found.completed and found.facts["title"] == "Erledigt"
    completed = [params for method, path, params in service.requests if path.endswith("by_completion_date")]
    assert completed[0]["project_id"] == "Inbox" and "since" in completed[0] and completed[1]["cursor"] == "c2"
    del service.override["/api/v1/tasks/completed/by_completion_date"]
    assert writer.read_entry("6") is None  # on no page of completed tasks either


def test_completed_pages_are_bounded_and_validated(tmp_path):
    service = Service("todoist")
    writer = service.writer()
    service.override["/api/v1/tasks/completed/by_completion_date"] = httpx.Response(
        200, json={"items": [], "next_cursor": "immer"})
    assert writer.read_entry("7") is None
    assert sum(path.endswith("by_completion_date") for _m, path, _p in service.requests) == 10
    service.override["/api/v1/tasks/completed/by_completion_date"] = httpx.Response(
        200, json={"items": [{"id": "8", "content": "x", "project_id": "Inbox", "is_deleted": True}]})
    assert writer.read_entry("8") is None
    service.override["/api/v1/tasks/completed/by_completion_date"] = httpx.Response(200, json={"items": "x"})
    with pytest.raises(ValueError, match="Todoist completed tasks"):
        writer.read_entry("9")


@pytest.mark.parametrize(("status", "error"), [(401, AuthenticationError), (403, PermanentError),
                                               (500, httpx.HTTPStatusError)])
def test_todoist_read_errors_are_not_a_missing_task(status, error):
    service = Service("todoist")
    service.override["/api/v1/tasks/1"] = httpx.Response(status)
    with pytest.raises(error):
        service.writer().read_entry("1")


def test_a_404_counts_only_while_the_project_is_reachable():
    service = Service("todoist")
    service.override["/api/v1/projects/Inbox"] = httpx.Response(404)
    with pytest.raises(PermanentError, match="Zielprojekt"):
        service.writer().read_entry("1")


def test_invalid_todoist_answers_and_identity():
    service = Service("todoist")
    service.override["/api/v1/tasks/1"] = httpx.Response(200, json={"id": "1"})
    writer = service.writer()
    with pytest.raises(ValueError, match="Todoist task"):
        writer.read_entry("1")
    assert writer.account_binding() == "4711"
    service.override["/api/v1/user"] = httpx.Response(200, json={"name": "ohne id"})
    with pytest.raises(ValueError, match="Todoist user"):
        writer.account_binding()
    assert writer.expected_facts(event(), "k") is None
    assert writer.expected_facts(task(), "k")["description"] == "[k]"
    assert writer.read_entry("../projects/x?y") is None  # an untrusted id stays one path segment
    assert b"/api/v1/tasks/..%2Fprojects%2Fx%3Fy" in service.raw_paths


@pytest.mark.parametrize("item", [
    event(),
    event(start=date(2026, 7, 2), end=date(2026, 7, 3), all_day=True, location=None),
    event(start=datetime(2026, 10, 25, 2, 30, tzinfo=BERLIN), end=datetime(2026, 10, 25, 3, 30, tzinfo=BERLIN)),
])
def test_a_google_event_is_verified_in_the_bound_calendar(tmp_path, item):
    service = Service("google_calendar")
    created, record = write_and_check(tmp_path, service, item, "primary")
    assert created.status == ProposalStatus.CREATED and record.state == VerificationState.VERIFIED
    assert record.target.account == "owner@example.test" and record.target.container == "primary"
    assert created.external_link == "https://calendar.example.invalid/id1"
    assert ("GET", "/calendar/v3/calendars/primary/events/id1", {}) in service.requests


def test_a_google_event_read_in_utc_is_the_same_time(tmp_path):
    service = Service("google_calendar")
    service.override["/calendar/v3/calendars/primary/events/id1"] = lambda request: httpx.Response(200, json={
        **service.items["id1"], "start": {"dateTime": "2026-07-02T17:00:00Z"},
        "end": {"dateTime": "2026-07-02T19:00:00Z", "timeZone": "UTC"}})
    _created, record = write_and_check(tmp_path, service, event(), "primary")
    assert record.state == VerificationState.VERIFIED


def test_a_google_event_with_another_time_or_all_day_flag_is_a_mismatch(tmp_path):
    service = Service("google_calendar")
    service.override["/calendar/v3/calendars/primary/events/id1"] = lambda request: httpx.Response(200, json={
        **service.items["id1"], "start": {"date": "2026-07-02"}, "end": {"date": "2026-07-03"}, "location": ""})
    _created, record = write_and_check(tmp_path, service, event(), "primary")
    assert set(record.differences) == {"start", "end", "all_day", "location"}


def test_the_expected_description_contains_what_was_sent():
    writer = Service("google_calendar").writer("primary")
    item = event(video_link="https://meet.example.invalid/abc", default_duration_minutes=60,
                 end_origin="standard", meeting_mode="video")
    facts = writer.expected_facts(item, "k")
    assert "[Mailhelp-Videolink]\nhttps://meet.example.invalid/abc" in facts["description"]
    assert "Standarddauer 60 Minuten" in facts["description"]
    assert writer.expected_facts(event(target_event_id="alt", classification="change", time_changes=["x"]),
                                 "k") is None
    assert writer.expected_facts(task(), "k") is None


@pytest.mark.parametrize("answer", [httpx.Response(404), httpx.Response(410),
                                    httpx.Response(200, json={"id": "1", "status": "cancelled"})])
def test_a_gone_or_cancelled_google_event_is_not_visible(answer):
    service = Service("google_calendar")
    service.override["/calendar/v3/calendars/primary/events/1"] = answer
    assert service.writer("primary").read_entry("1") is None


def test_google_read_errors_and_identity():
    service = Service("google_calendar")
    writer = service.writer("primary")
    service.override["/calendar/v3/calendars/primary/events/1"] = httpx.Response(404)
    service.override["/calendar/v3/calendars/primary"] = httpx.Response(404)
    with pytest.raises(CalendarAccessError):
        writer.read_entry("1")
    service.override["/calendar/v3/calendars/primary"] = httpx.Response(200, json={"kind": "ohne id"})
    with pytest.raises(ValueError, match="Google Calendar"):
        writer.account_binding()
    service.override["/calendar/v3/calendars/primary/events/1"] = httpx.Response(200, json={"id": "1"})
    with pytest.raises(ValueError, match="Google Calendar events"):
        writer.read_entry("1")
    service.override["/calendar/v3/calendars/primary/events/1"] = httpx.Response(200, content=b"kein json")
    with pytest.raises(ValueError, match="Google Calendar events"):
        writer.read_entry("1")
    service.override["/calendar/v3/calendars/primary/events/1"] = httpx.Response(401)
    with pytest.raises(AuthenticationError):
        writer.read_entry("1")


def test_a_cached_list_never_replaces_the_fresh_read(tmp_path):
    service = Service("google_calendar")
    writer = service.writer("primary")
    writer.fetch_events_in_window(datetime(2026, 7, 1, tzinfo=UTC), datetime(2026, 7, 3, tzinfo=UTC))
    service.items["c1"] = {"id": "c1", "summary": "X", "start": {"date": "2026-07-02"}, "end": {"date": "2026-07-03"}}
    assert writer.read_entry("c1").facts["title"] == "X"
    assert writer.read_entry("c1").facts["title"] == "X"
    assert sum(path.endswith("/events/c1") for _m, path, _p in service.requests) == 2
