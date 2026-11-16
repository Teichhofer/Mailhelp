"""7.2: Google Tasks against a simulated Tasks API (Planung 7.2, 4 and 6)."""
import json

import httpx
import pytest

from mailhelp.domain.proposal import ProposalStatus
from mailhelp.external.confirmed import execute_confirmed
from mailhelp.external.contracts import AuthenticationError, ExternalUncertain, TargetAccessError
from mailhelp.domain.proposal import Proposal
from mailhelp.external.google_tasks import DUE_NOTE, MAX_PAGES, NOTES_LIMIT, TITLE_LIMIT, GoogleTasks, _link, _reason
from mailhelp.llm.adapter import RetryPolicy
from tests.fakes.log_fakes import RecordingLogger
from tests.fakes.shared_core import proposal
from tests.fakes.shared_write_improvements import event

LIST = "/tasks/v1/lists/@default/tasks"


class StaticToken:
    def __init__(self):
        self.invalidated = 0

    def access_token(self):
        return "access-synthetic"

    def invalidate(self):
        self.invalidated += 1


class FakeTasks:
    """A list of tasks with paging; every request is recorded."""

    def __init__(self, tasks=None, page_size=100):
        self.tasks, self.page_size, self.requests, self.routes = list(tasks or []), page_size, [], {}

    def __call__(self, request):
        self.requests.append(request)
        path = request.url.path
        if (request.method, path) in self.routes:
            answer = self.routes[(request.method, path)]
            return answer(request) if callable(answer) else answer
        if request.method == "GET" and path == "/tasks/v1/users/@me/lists/@default":
            return httpx.Response(200, json={"id": "LIST-REAL", "title": "Meine Aufgaben"})
        if request.method == "GET" and path == LIST:
            return self._page(request)
        if request.method == "POST" and path == LIST:
            body = json.loads(request.content)
            task = {"id": f"t{len(self.tasks) + 1}", "webViewLink": "https://tasks.google.com/task/x", **body}
            self.tasks.append(task)
            return httpx.Response(200, json=task)
        if request.method == "GET" and path.startswith(LIST + "/"):
            found = next((task for task in self.tasks if task["id"] == path.rsplit("/", 1)[1]), None)
            return httpx.Response(200, json=found) if found else httpx.Response(404)
        return httpx.Response(404)

    def _page(self, request):
        params = request.url.params
        visible = [task for task in self.tasks
                   if (params.get("showCompleted") != "false" or task.get("status") != "completed")
                   and (params.get("showDeleted") == "true" or not task.get("deleted"))]
        start = int(params.get("pageToken") or 0)
        page = visible[start:start + self.page_size]
        answer = {"items": page}
        if start + self.page_size < len(visible):
            answer["nextPageToken"] = str(start + self.page_size)
        return httpx.Response(200, json=answer)


def writer(api, logger=None, policy=None, timezone="Europe/Berlin"):
    return GoogleTasks(StaticToken(), "@default", transport=httpx.MockTransport(api), logger=logger, policy=policy,
                       timezone=timezone)


def confirm(item, target_writer):
    saved = []
    result, _ = execute_confirmed(item, target_writer, saved.append)
    return result, [value.status.value for value in saved]


def task(**changes):
    return proposal(status="confirmed", target="@default", **changes)


def test_a_dated_task_is_created_once_with_its_day_and_marker():
    api = FakeTasks()
    created, states = confirm(task(description="Formular abgeben", due="2026-05-12"), writer(api))
    assert created.status == ProposalStatus.CREATED and created.external_id == "t1"
    assert created.external_link == "https://tasks.google.com/task/x" and states[-1] == "created"
    body = json.loads(api.requests[-1].content)
    assert body["due"] == "2026-05-12T00:00:00.000Z" and body["status"] == "needsAction"
    assert body["notes"].startswith("Formular abgeben\n\n[mailhelp:") and body["title"] == "Tun"
    assert "Frist:" not in body["notes"]
    assert api.requests[-1].headers["Authorization"] == "Bearer access-synthetic"


def test_an_exact_deadline_keeps_its_local_day_and_stands_in_the_notes():
    """Google keeps only a day; 23:30 in Berlin is the 12th there, the 12th stays the confirmed day."""
    api = FakeTasks()
    confirm(task(id="p2", due="2026-05-12T23:30:00+02:00"), writer(api))
    body = json.loads(api.requests[-1].content)
    assert body["due"] == "2026-05-12T00:00:00.000Z"
    assert "Frist: 12.05.2026, 23:30 Uhr (Europe/Berlin)" in body["notes"]
    other = FakeTasks()
    confirm(task(id="p3", due="2026-05-12T23:30:00+02:00"), writer(other, timezone="UTC"))
    assert json.loads(other.requests[-1].content)["due"] == "2026-05-12T00:00:00.000Z"  # 21:30 UTC
    confirm(task(id="p4"), writer(api))
    assert "due" not in json.loads(api.requests[-1].content)  # no invented "today"
    assert DUE_NOTE.startswith("Google Tasks übernimmt das Datum")


def test_the_day_of_a_time_is_taken_in_the_configured_zone():
    api = FakeTasks()
    confirm(task(id="p5", due="2026-05-12T23:30:00+00:00"), writer(api))
    assert json.loads(api.requests[-1].content)["due"] == "2026-05-13T00:00:00.000Z"


def test_reconciliation_finds_the_marker_also_in_completed_and_deleted_tasks():
    api = FakeTasks([{"id": "a", "title": "Alt", "notes": "x\n\n[k1]", "status": "completed"},
                     {"id": "b", "title": "Weg", "notes": "[k2]", "deleted": True}])
    target = writer(api)
    assert target.reconcile("k1") == {"id": "a", "htmlLink": None}
    assert target.reconcile("k2") == {"id": "b", "htmlLink": None}
    assert target.reconcile("k3") is None
    params = api.requests[-1].url.params
    assert (params["showCompleted"], params["showHidden"], params["showDeleted"]) == ("true", "true", "true")


def test_a_marker_found_twice_is_a_conflict_not_a_new_write():
    api = FakeTasks([{"id": "a", "notes": "[k1]"}, {"id": "b", "notes": "[k1]"}])
    logger = RecordingLogger()
    with pytest.raises(ExternalUncertain, match="mehrfach"):
        writer(api, logger=logger).reconcile("k1")
    assert ("ERROR", "google_tasks", "reconcile_conflict") in [item[0] for item in logger.events]


def test_all_pages_are_read_and_an_endless_list_is_incomplete(monkeypatch):
    api = FakeTasks([{"id": str(number), "notes": f"[k{number}]"} for number in range(5)], page_size=2)
    assert writer(api).reconcile("k4") == {"id": "4", "htmlLink": None}
    assert [request.url.params.get("pageToken") for request in api.requests] == [None, "2", "4"]
    endless = FakeTasks()
    endless.routes[("GET", LIST)] = lambda request: httpx.Response(200, json={
        "items": [], "nextPageToken": f"p{request.url.params.get('pageToken', '')}x"})
    with pytest.raises(ExternalUncertain, match="vollständig"):
        writer(endless).reconcile("k")
    assert len(endless.requests) == MAX_PAGES


@pytest.mark.parametrize("answer", [{"items": "kaputt"}, {"items": [], "nextPageToken": 5}, [1],
                                    {"items": [{"title": "ohne id"}]}])
def test_damaged_list_answers_are_refused(answer):
    api = FakeTasks()
    api.routes[("GET", LIST)] = httpx.Response(200, json=answer)
    with pytest.raises(ValueError, match="Schlüsselpfad"):
        writer(api).reconcile("k")


def test_a_repeated_page_token_is_refused_and_invalid_json_too():
    api = FakeTasks()
    api.routes[("GET", LIST)] = httpx.Response(200, json={"items": [], "nextPageToken": "same"})
    with pytest.raises(ValueError, match="nextPageToken"):
        writer(api).reconcile("k")
    api.routes[("GET", LIST)] = httpx.Response(200, content=b"<html>")
    with pytest.raises(ValueError, match="<json>"):
        writer(api).reconcile("k")


def test_access_binding_and_open_tasks():
    api = FakeTasks([{"id": "a", "title": "Offen", "notes": "n", "webViewLink": "https://evil.example/x"},
                     {"id": "b", "title": "Fertig", "status": "completed"}])
    target = writer(api)
    assert target.check_access() is None and target.account_binding() == "LIST-REAL"
    open_tasks = target.fetch_active_tasks()
    assert [(item.id, item.content, item.url) for item in open_tasks] == [("a", "Offen", None)]
    count = len(api.requests)
    assert target.fetch_active_tasks() == open_tasks and len(api.requests) == count  # cached
    assert target.fetch_active_tasks(strict=True) == open_tasks and len(api.requests) == count + 1
    assert target.fetch_events_in_window(None, None) == [] and target.supports_remove is False
    api.routes[("GET", "/tasks/v1/users/@me/lists/@default")] = httpx.Response(200, json={"title": "ohne"})
    with pytest.raises(ValueError, match="Schlüsselpfad id"):
        target.account_binding()
    target.close()


def test_a_failed_read_is_never_an_empty_list_when_strict():
    api = FakeTasks()
    api.routes[("GET", LIST)] = httpx.Response(500)
    logger = RecordingLogger()
    target = writer(api, logger=logger)
    assert target.fetch_active_tasks() == []
    assert logger.events[-1][0] == ("WARNING", "google_tasks", "fetch_tasks_failed")
    with pytest.raises(Exception):
        target.fetch_active_tasks(strict=True)


def test_written_tasks_are_read_back_for_verification():
    api = FakeTasks([{"id": "a", "title": "Tun", "notes": "x", "due": "2026-05-12T00:00:00.000Z",
                      "status": "completed", "webViewLink": "https://tasks.google.com/task/a"},
                     {"id": "d", "title": "Weg", "deleted": True}])
    target = writer(api)
    entry = target.read_entry("a")
    assert entry.completed and entry.facts["due"] == "2026-05-12" and entry.link == "https://tasks.google.com/task/a"
    assert target.read_entry("d") is None and target.read_entry("fehlt") is None
    expected = target.expected_facts(task(due="2026-05-12", description="x"), "k")
    assert expected["due"] == "2026-05-12" and expected["description"] == "x\n\n[k]"
    assert target.expected_facts(event(status="confirmed", target="@default"), "k") is None
    api.tasks.append({"id": "n", "title": "ohne Datum"})
    assert target.read_entry("n").facts["due"] is None


def _limit(field):
    return next(item.max_length for item in Proposal.model_fields[field].metadata if hasattr(item, "max_length"))


def test_only_tasks_are_written_and_the_longest_proposal_fits_without_cutting():
    api = FakeTasks()
    with pytest.raises(ValueError, match="nur Aufgaben"):
        writer(api).prepare(event(status="confirmed", target="@default"), "k")
    assert api.requests == []
    assert _limit("title") <= TITLE_LIMIT
    longest = task(title="t" * _limit("title"), description="x" * _limit("description"),
                   due="2026-05-12T23:30:00+02:00")
    confirm(longest, writer(api))
    body = json.loads(api.requests[-1].content)
    assert len(body["notes"]) <= NOTES_LIMIT and body["notes"].startswith("x" * _limit("description"))


def test_an_unclear_create_is_never_repeated_blindly():
    api = FakeTasks()
    api.routes[("POST", LIST)] = httpx.Response(503)
    uncertain, states = confirm(task(), writer(api))
    assert uncertain.status == ProposalStatus.UNCERTAIN and states == ["writing", "uncertain"]
    posts = [request for request in api.requests if request.method == "POST"]
    again, _ = execute_confirmed(uncertain, writer(api), lambda value: None)
    assert again.status == ProposalStatus.UNCERTAIN
    assert [request for request in api.requests if request.method == "POST"] == posts


@pytest.mark.parametrize(("status", "body", "error", "reason"), [
    (403, {"error": {"errors": [{"reason": "accessNotConfigured"}]}}, TargetAccessError, "api_disabled"),
    (403, {"error": {"details": [{"reason": "SERVICE_DISABLED"}]}}, TargetAccessError, "api_disabled"),
    (403, {"error": {"errors": [{"reason": "insufficientPermissions"}]}}, TargetAccessError, "forbidden"),
    (403, {"error": {}}, TargetAccessError, "forbidden"),
    (404, None, TargetAccessError, "not_found"),
])
def test_access_errors_are_classified_by_their_structured_reason(status, body, error, reason):
    api = FakeTasks()
    api.routes[("GET", "/tasks/v1/users/@me/lists/@default")] = httpx.Response(status, json=body)
    with pytest.raises(error) as raised:
        writer(api).check_access()
    assert raised.value.reason == reason


def test_a_refused_token_is_dropped_and_retryable_errors_are_retried():
    api = FakeTasks()
    api.routes[("GET", "/tasks/v1/users/@me/lists/@default")] = httpx.Response(401)
    target = writer(api)
    with pytest.raises(AuthenticationError, match="erneut anmelden"):
        target.check_access()
    assert target.token.invalidated == 1
    answers = iter([httpx.Response(503), httpx.Response(200, json={"id": "L"})])
    api.routes[("GET", "/tasks/v1/users/@me/lists/@default")] = lambda request: next(answers)
    writer(api, policy=RetryPolicy(1, 0, 0, lambda delay: False)).check_access()


def test_links_and_reasons_are_only_taken_from_trusted_structure():
    assert _link("https://tasks.google.com/task/1") == "https://tasks.google.com/task/1"
    assert _link("https://google.com.evil.example/x") is None and _link(None) is None
    assert _link('https://tasks.google.com/"><script>') is None
    assert _reason(httpx.Response(403, content=b"nicht json")) == ""
    assert _reason(httpx.Response(403, json={"error": {"errors": []}})) == ""
