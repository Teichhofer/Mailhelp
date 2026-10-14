"""Microsoft 365 via a simulated Graph and sign-in service (Planung 2.3, 4.2/4.3)."""
import json
import os
from urllib.parse import parse_qs

import httpx
import pytest
from log_fakes import RecordingLogger
from shared_core import proposal
from shared_write_improvements import event

from mailhelp.adapter import RetryableError, RetryPolicy
from mailhelp.external.confirmed import execute_confirmed
from mailhelp.external.contracts import AuthenticationError, CalendarAccessError, ExternalUnavailable, OAuthTokenError
from mailhelp.external.microsoft import (
    GRAPH,
    KEY_PROPERTY,
    MicrosoftTodo,
    MicrosoftTokenProvider,
    OutlookCalendar,
    TokenFile,
)
from mailhelp.models import CalendarDuplicateDecision, ProposalStatus


class StaticToken:
    def __init__(self):
        self.invalidated = 0

    def access_token(self):
        return "access-synthetic"

    def invalidate(self):
        self.invalidated += 1


def login(tmp_path, handler, seed="seed-token", secret="", clock=lambda: 1000.0, logger=None):
    return MicrosoftTokenProvider("client-id", secret, seed, "common", TokenFile(tmp_path / "microsoft-token.json"),
                                  transport=httpx.MockTransport(handler), clock=clock, logger=logger)


def token_answer(refresh="rotated-1", **extra):
    body = {"access_token": "access-1", "expires_in": 3600, "token_type": "Bearer", **extra}
    if refresh is not None:
        body["refresh_token"] = refresh
    return httpx.Response(200, json=body)


def test_refresh_rotation_is_persisted_and_preferred(tmp_path):
    forms = []
    now = [1000.0]

    def handler(request):
        forms.append(parse_qs(request.content.decode()))
        assert str(request.url) == "https://login.microsoftonline.com/common/oauth2/v2.0/token"
        return token_answer(refresh=f"rotated-{len(forms)}")

    logger = RecordingLogger()
    tokens = login(tmp_path, handler, clock=lambda: now[0], logger=logger)
    assert tokens.access_token() == "access-1" and tokens.access_token() == "access-1" and len(forms) == 1
    assert forms[0]["refresh_token"] == ["seed-token"] and "client_secret" not in forms[0]
    assert forms[0]["scope"] == ["offline_access Calendars.ReadWrite Tasks.ReadWrite"]
    stored = json.loads((tmp_path / "microsoft-token.json").read_text(encoding="utf-8"))
    assert stored["refresh_token"] == "rotated-1" and stored["schema_version"] == 1
    if os.name == "posix":
        assert (tmp_path / "microsoft-token.json").stat().st_mode & 0o777 == 0o600
    now[0] += 3600
    tokens.access_token()
    assert forms[1]["refresh_token"] == ["rotated-1"]
    tokens.invalidate()
    tokens.access_token()
    assert forms[2]["refresh_token"] == ["rotated-2"] and len(forms) == 3
    assert all("rotated-" not in str(fields) and "access-1" not in str(fields) for _, fields in logger.events)
    tokens.close()


def test_client_secret_is_sent_and_missing_rotation_keeps_the_token(tmp_path):
    forms = []

    def handler(request):
        forms.append(parse_qs(request.content.decode()))
        return token_answer(refresh=None)

    login(tmp_path, handler, secret="client-secret").access_token()
    assert forms[0]["client_secret"] == ["client-secret"] and not (tmp_path / "microsoft-token.json").exists()


@pytest.mark.parametrize("answer", [
    httpx.Response(400, json={"error": "invalid_grant"}), httpx.Response(200, json={"access_token": "x"}),
    httpx.Response(200, text="kein json"),
    httpx.Response(200, json={"access_token": "x", "expires_in": 1, "token_type": "mac"})])
def test_refused_or_invalid_answers_ask_for_a_new_sign_in(tmp_path, answer):
    logger = RecordingLogger()
    with pytest.raises(OAuthTokenError, match="--microsoft-login") as raised:
        login(tmp_path, lambda request: answer, logger=logger).access_token()
    assert raised.value.__cause__ is None and logger.events[-1][0][2] == "token_refresh_denied"


def test_temporary_sign_in_failures_and_missing_sign_in(tmp_path):
    with pytest.raises(ExternalUnavailable):
        login(tmp_path, lambda request: httpx.Response(503)).access_token()
    with pytest.raises(OAuthTokenError, match="keine Anmeldung"):
        login(tmp_path, lambda request: token_answer(), seed="").access_token()


@pytest.mark.parametrize("content", ["kaputt", "[]", '{"refresh_token": ""}', '{"refresh_token": 5}'])
def test_damaged_token_file_reads_as_absent(tmp_path, content):
    path = tmp_path / "microsoft-token.json"
    path.write_text(content, encoding="utf-8")
    assert TokenFile(path).load() is None
    assert TokenFile(tmp_path / "fehlt.json").load() is None


def device_flow(tmp_path, answers, clock_step=1.0):
    shown, sleeps, now = [], [], [0.0]

    def handler(request):
        if request.url.path.endswith("/devicecode"):
            return httpx.Response(200, json={"device_code": "device", "user_code": "ABCD-EFGH",
                                             "verification_uri": "https://microsoft.com/devicelogin",
                                             "expires_in": 30, "interval": 2})
        return answers.pop(0)

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += clock_step

    tokens = login(tmp_path, handler)
    return tokens, shown, sleeps, lambda: tokens.device_login(shown.append, sleep, lambda: now[0])


def test_device_login_waits_slows_down_and_stores_the_token(tmp_path):
    tokens, shown, sleeps, run = device_flow(tmp_path, [
        httpx.Response(400, json={"error": "authorization_pending"}),
        httpx.Response(400, json={"error": "slow_down"}), token_answer(refresh="device-refresh")])
    run()
    assert shown == ["Öffne https://microsoft.com/devicelogin und gib den Code ABCD-EFGH ein.",
                     "Microsoft-Anmeldung gespeichert."]
    assert sleeps == [2, 2, 7] and TokenFile(tmp_path / "microsoft-token.json").load() == "device-refresh"


@pytest.mark.parametrize("answers", [
    [httpx.Response(400, json={"error": "expired_token"})], [httpx.Response(400, text="kein json")],
    [httpx.Response(200, text="kein json")], [token_answer(refresh=None)],
    [httpx.Response(400, json={"error": ["liste"]})]])
def test_device_login_failures(tmp_path, answers):
    _tokens, _shown, _sleeps, run = device_flow(tmp_path, answers)
    with pytest.raises(OAuthTokenError, match="nicht abgeschlossen"):
        run()


def test_device_login_times_out_and_rejects_unusable_codes(tmp_path):
    pending = [httpx.Response(400, json={"error": "authorization_pending"}) for _ in range(20)]
    _tokens, _shown, sleeps, run = device_flow(tmp_path, pending, clock_step=10)
    with pytest.raises(OAuthTokenError):
        run()
    assert len(sleeps) == 3
    tokens = login(tmp_path, lambda request: httpx.Response(400, json={"error": "unauthorized_client"}))
    with pytest.raises(OAuthTokenError, match="Gerätecode-Anmeldung nicht möglich"):
        tokens.device_login(print)


class FakeGraph:
    def __init__(self):
        self.requests = []
        self.events = {}
        self.tasks = {}
        self.routes = {}

    def __call__(self, request):
        self.requests.append(request)
        path = request.url.raw_path.decode().split("?")[0].removeprefix("/v1.0")
        answer = self.routes.get((request.method, path), httpx.Response(404))
        return answer(request) if callable(answer) else answer


def outlook(graph, target="default", matcher=None, logger=None, policy=None):
    return OutlookCalendar(StaticToken(), target, transport=httpx.MockTransport(graph), logger=logger,
                           policy=policy, calendar_timezone="Europe/Berlin", calendar_matcher=matcher)


def confirm(item_, writer):
    saved = []
    result, _ = execute_confirmed(item_, writer, saved.append)
    return result, [value.status.value for value in saved]


def created_event(request):
    return httpx.Response(201, json={"id": "evt-1", "webLink": "https://outlook.office.com/x",
                                     "start": {}, "end": {}})


def test_outlook_event_with_idempotency_property_and_transaction_id():
    graph = FakeGraph()
    graph.routes[("GET", "/me/calendar/events")] = httpx.Response(200, json={"value": []})
    graph.routes[("POST", "/me/calendar/events")] = created_event
    writer = outlook(graph)
    item_ = event(status="confirmed", target="default", description="Agenda", location="Aula")
    result, statuses = confirm(item_, writer)
    assert result.status == ProposalStatus.CREATED and result.external_id == "evt-1"
    assert result.external_link == "https://outlook.office.com/x" and statuses == ["writing", "created"]
    reconcile, post = graph.requests
    assert KEY_PROPERTY in reconcile.url.params["$filter"] and "ep/value eq 'mailhelp:" in reconcile.url.params[
        "$filter"]
    body = json.loads(post.content)
    key = f"mailhelp:{item_.source_mail_id}:p1:v1"
    assert body["transactionId"] == key and body["singleValueExtendedProperties"] == [
        {"id": KEY_PROPERTY, "value": key}]
    assert body["subject"] == "Tun" and body["body"] == {"contentType": "text", "content": "Agenda"}
    assert body["location"] == {"displayName": "Aula"} and body["isAllDay"] is False
    assert body["start"] == {"dateTime": "2026-05-10T10:00:00", "timeZone": "UTC"}
    assert post.headers["Authorization"] == "Bearer access-synthetic"
    assert 'outlook.timezone="UTC"' in post.headers["Prefer"]
    writer.close()


def test_outlook_all_day_reconcile_and_named_calendar():
    graph = FakeGraph()
    graph.routes[("GET", "/me/calendars/AAk%2Fx%3D/events")] = httpx.Response(200, json={"value": [
        {"id": "evt-9", "webLink": "http://unsicher.example"}]})
    writer = outlook(graph, target="AAk/x=")
    found = writer.reconcile("mailhelp:x'y")
    assert found == {"id": "evt-9", "htmlLink": None}
    assert "ep/value eq 'mailhelp:x''y'" in graph.requests[0].url.params["$filter"]
    graph.routes = {("GET", "/me/calendars/AAk%2Fx%3D/events"): httpx.Response(200, json={"value": []}),
                    ("POST", "/me/calendars/AAk%2Fx%3D/events"): created_event,
                    ("GET", "/me/calendars/AAk%2Fx%3D"): httpx.Response(200, json={"id": "AAk/x="})}
    whole_day = proposal(kind="event", status="confirmed", target="AAk/x=", start="2026-05-10", end="2026-05-11",
                         all_day=True)
    confirm(whole_day, writer)
    body = json.loads(graph.requests[-1].content)
    assert body["isAllDay"] is True and body["start"] == {"dateTime": "2026-05-10T00:00:00", "timeZone": "UTC"}
    assert writer.check_access() is None
    with pytest.raises(ValueError, match="Schlüsselpfad"):
        writer._result({"id": ""})


def overlap(**changes):
    entry = {"id": "alt", "subject": "Elternabend", "body": {"content": "Text"},
             "location": {"displayName": "Aula"}, "start": {"dateTime": "2026-05-10T10:00:00.0000000"},
             "end": {"dateTime": "2026-05-10T11:00:00.0000000"}, "webLink": "https://outlook.office.com/alt"}
    entry.update(changes)
    return entry


def test_outlook_duplicates_are_completed_moved_or_deleted():
    graph = FakeGraph()
    graph.routes[("GET", "/me/calendar/events")] = httpx.Response(200, json={"value": []})
    graph.routes[("GET", "/me/calendar/calendarView")] = httpx.Response(200, json={"value": [overlap(
        start={"dateTime": "2026-05-10T09:00:00.0000000"})]})
    graph.routes[("PATCH", "/me/calendar/events/alt")] = httpx.Response(200, json={"id": "alt", "start": {},
                                                                                     "end": {}})
    graph.routes[("DELETE", "/me/calendar/events/alt")] = httpx.Response(204)
    writer = outlook(graph, matcher=lambda *_: ("c", CalendarDuplicateDecision(
        same_event=True, missing_fields=["description"], reason="x")))
    result, _ = confirm(event(status="confirmed", target="default", description="Neu"), writer)
    patch = json.loads(graph.requests[-1].content)
    assert result.status == ProposalStatus.CREATED and graph.requests[-1].method == "PATCH"
    assert patch["start"]["dateTime"] == "2026-05-10T10:00:00" and "Zeit aktualisiert" in patch["body"]["content"]
    assert "Text\n\nNeu" in patch["body"]["content"]
    # Same time: only the missing fields are added, the times stay untouched.
    graph.routes[("GET", "/me/calendar/calendarView")] = httpx.Response(200, json={"value": [overlap()]})
    confirm(event(status="confirmed", target="default", description="Neu", id="p9"), writer)
    completion = json.loads(graph.requests[-1].content)
    assert "start" not in completion and "isAllDay" not in completion and completion["body"]["content"]
    cancel =event(status="confirmed", target="default", classification="cancellation", target_event_id="alt",
                   is_cancellation=True, id="p2")
    deleted, _ = confirm(cancel, writer)
    assert deleted.status == ProposalStatus.CREATED and graph.requests[-1].method == "DELETE"


def test_outlook_window_paging_cancelled_entries_and_failures():
    graph = FakeGraph()
    pages = {"first": {"value": [overlap(), overlap(id="weg", isCancelled=True)],
                       "@odata.nextLink": GRAPH + "/me/calendar/calendarView?skip=1"},
             "second": {"value": [overlap(id="ganz", isAllDay=True, start={"dateTime": "2026-05-10T00:00:00"},
                                          end={"dateTime": "2026-05-11T00:00:00"}, body=None, location=None,
                                          webLink=None, subject=None)]}}
    graph.routes[("GET", "/me/calendar/calendarView")] = lambda request: httpx.Response(
        200, json=pages["second" if "skip" in str(request.url) else "first"])
    logger = RecordingLogger()
    writer = outlook(graph, logger=logger)
    from datetime import date
    events = writer.fetch_events_in_window(date(2026, 5, 10), date(2026, 5, 11))
    assert [item.id for item in events] == ["alt", "ganz"]
    assert events[0].start == {"dateTime": "2026-05-10T10:00:00+00:00"} and events[0].location == "Aula"
    assert events[1].start == {"date": "2026-05-10"} and events[1].summary == "" and events[1].htmlLink is None
    count = len(graph.requests)
    assert writer.fetch_events_in_window(date(2026, 5, 10), date(2026, 5, 11)) == events
    assert len(graph.requests) == count
    from datetime import UTC, datetime
    writer.fetch_events_in_window(datetime(2026, 5, 10, 8, tzinfo=UTC), datetime(2026, 5, 10, 9, tzinfo=UTC))
    assert graph.requests[-2].url.params["startDateTime"] == "2026-05-10T08:00:00+00:00"
    for broken in ({"value": "x"}, {"value": [1]}, {}, {"value": [], "@odata.nextLink": "https://fremd/x"},
                   {"value": [{"id": "ohne-zeit"}]}, [1]):
        graph.routes[("GET", "/me/calendar/calendarView")] = httpx.Response(200, json=broken)
        assert writer.fetch_events_in_window(date(2026, 6, 1), date(2026, 6, 2)) == []
        assert logger.events[-1][0] == ("WARNING", "outlook_calendar", "fetch_events_failed")
        with pytest.raises(ValueError, match="ungültige Antwort"):
            writer.fetch_events_in_window(date(2026, 6, 1), date(2026, 6, 2), strict=True)
    loop = {"value": [], "@odata.nextLink": GRAPH + "/me/calendar/calendarView?loop"}
    graph.routes[("GET", "/me/calendar/calendarView")] = httpx.Response(200, json=loop)
    with pytest.raises(ValueError, match="nextLink"):
        writer.fetch_events_in_window(date(2026, 7, 1), date(2026, 7, 2), strict=True)


def test_graph_errors_are_classified_and_retried():
    graph = FakeGraph()
    token = StaticToken()
    writer = OutlookCalendar(token, "default", transport=httpx.MockTransport(graph))
    graph.routes[("GET", "/me/calendar")] = httpx.Response(401, text="geheim")
    with pytest.raises(AuthenticationError) as raised:
        writer.check_access()
    assert token.invalidated == 1 and "geheim" not in str(raised.value)
    graph.routes[("GET", "/me/calendar")] = httpx.Response(403)
    with pytest.raises(CalendarAccessError):
        writer.check_access()
    waits = []
    graph.routes[("GET", "/me/calendar")] = httpx.Response(429, headers={"Retry-After": "3"})
    retried = outlook(graph, policy=RetryPolicy(1, 1, 10, lambda delay: waits.append(delay) or False))
    with pytest.raises(RetryableError):
        retried.check_access()
    assert waits == [3]
    graph.routes[("GET", "/me/calendar/events")] = httpx.Response(200, json={"value": []})
    graph.routes[("POST", "/me/calendar/events")] = httpx.Response(503)
    uncertain, _ = confirm(event(status="confirmed", target="default"), outlook(graph))
    assert uncertain.status == ProposalStatus.UNCERTAIN


def todo(graph, target="default", logger=None):
    return MicrosoftTodo(StaticToken(), target, transport=httpx.MockTransport(graph), logger=logger)


def test_todo_default_list_creation_reconciliation_and_open_tasks():
    graph = FakeGraph()
    graph.routes[("GET", "/me/todo/lists/L1/tasks")] = lambda request: httpx.Response(200, json={"value": [
        {"id": "t1", "title": "Alt", "body": {"content": "x"}, "linkedResources": [{"externalId": "k1"}]},
        {"id": "t2", "title": "Marker", "body": {"content": "Text\n\n[k2]"}}]})
    graph.routes[("GET", "/me/todo/lists/L1")] = httpx.Response(200, json={"id": "L1"})
    graph.routes[("GET", "/me/todo/lists")] = httpx.Response(200, json={"value": [
        {"id": "L0", "wellknownListName": "none"}, {"id": "L1", "wellknownListName": "defaultList"}]})
    graph.routes[("POST", "/me/todo/lists/L1/tasks")] = httpx.Response(201, json={"id": "t3", "title": "Tun"})
    writer = todo(graph)
    assert writer.check_access() is None and writer.check_access() is None
    assert [r.url.path for r in graph.requests].count("/v1.0/me/todo/lists") == 1
    assert writer.reconcile("k1") == {"id": "t1"} and writer.reconcile("k2") == {"id": "t2"}
    assert writer.reconcile("k3") is None
    created, _ = confirm(proposal(status="confirmed", target="default", description="Formular",
                                  due="2026-05-12"), writer)
    assert created.status == ProposalStatus.CREATED and created.external_id == "t3"
    body = json.loads(graph.requests[-1].content)
    assert body["dueDateTime"] == {"dateTime": "2026-05-12T00:00:00", "timeZone": "UTC"}
    assert body["linkedResources"][0]["externalId"].startswith("mailhelp:") and "[mailhelp:" in body["body"]["content"]
    confirm(proposal(status="confirmed", target="default", id="p2", due="2026-05-12T08:00:00+02:00"), writer)
    assert json.loads(graph.requests[-1].content)["dueDateTime"]["dateTime"] == "2026-05-12T06:00:00"
    confirm(proposal(status="confirmed", target="default", id="p3"), writer)
    assert "dueDateTime" not in json.loads(graph.requests[-1].content)
    open_tasks = writer.fetch_active_tasks()
    assert [task.content for task in open_tasks] == ["Alt", "Marker"]
    assert writer.fetch_active_tasks() == open_tasks
    assert writer.fetch_events_in_window(None, None) == []
    with pytest.raises(ValueError, match="nur Aufgaben"):
        writer.prepare(event(status="confirmed", target="default"), "k")


def test_todo_named_list_missing_default_and_failures():
    graph = FakeGraph()
    graph.routes[("GET", "/me/todo/lists")] = httpx.Response(200, json={"value": [{"id": 5}]})
    with pytest.raises(CalendarAccessError, match="Standardliste"):
        todo(graph).check_access()
    graph.routes[("GET", "/me/todo/lists/Eigene/tasks")] = httpx.Response(200, json={"value": [{"title": "x"}]})
    logger = RecordingLogger()
    named = todo(graph, target="Eigene", logger=logger)
    with pytest.raises(ValueError, match="Schlüsselpfad"):
        named.reconcile("k")
    assert named.fetch_active_tasks() == []
    with pytest.raises(ValueError):
        named.fetch_active_tasks(strict=True)
    assert logger.events[-1][0] == ("WARNING", "microsoft_todo", "fetch_tasks_failed")
