"""7.2: a Notion data source as task target against a simulated Notion API (Planung 7.2, 5 and 6)."""
import json

import httpx
import pytest

from mailhelp.config import NotionProperties
from mailhelp.domain.proposal import ProposalStatus
from mailhelp.external.confirmed import execute_confirmed
from mailhelp.external.contracts import AuthenticationError, ExternalUncertain, TargetAccessError
from mailhelp.external.notion import MAX_PAGES, NO_STATUS_NOTE, VERSION, NotionTasks, _chunks, _link, _moment
from mailhelp.llm.adapter import RetryPolicy
from tests.fakes.log_fakes import RecordingLogger
from tests.fakes.shared_core import proposal
from tests.fakes.shared_write_improvements import event

SOURCE = "0" * 32
FIELDS = NotionProperties(title="title", description="d1", due="d2", source="u1", operation_key="k1", status="s1")
SCHEMA = {"id": SOURCE, "properties": {
    "Aufgabe": {"id": "title", "name": "Aufgabe", "type": "title"},
    "Beschreibung": {"id": "d1", "name": "Beschreibung", "type": "rich_text"},
    "Frist": {"id": "d2", "name": "Frist", "type": "date"},
    "Quelle": {"id": "u1", "name": "Quelle", "type": "url"},
    "Vorgang": {"id": "k1", "name": "Vorgang", "type": "rich_text"},
    "Status": {"id": "s1", "name": "Status", "type": "status",
               "status": {"options": [{"id": "open", "name": "Offen"}, {"id": "done", "name": "Erledigt"}]}}}}


def page(identifier, *, title="Tun", description="", key="", due=None, status="open", in_trash=False,
         url="https://www.notion.so/Tun-1"):
    return {"id": identifier, "url": url, "in_trash": in_trash, "properties": {
        "Aufgabe": {"id": "title", "type": "title", "title": [{"plain_text": title}]},
        "Beschreibung": {"id": "d1", "type": "rich_text", "rich_text": [{"plain_text": description}]},
        "Frist": {"id": "d2", "type": "date", "date": None if due is None else {"start": due}},
        "Vorgang": {"id": "k1", "type": "rich_text", "rich_text": [{"plain_text": key}]},
        "Status": {"id": "s1", "type": "status", "status": {"id": status}}}}


class FakeNotion:
    def __init__(self, pages=(), page_size=100, schema=None):
        self.pages, self.page_size, self.requests = list(pages), page_size, []
        self.schema, self.routes, self.archived = schema or SCHEMA, {}, []

    def __call__(self, request):
        self.requests.append(request)
        assert request.headers["Notion-Version"] == VERSION
        key = (request.method, request.url.path)
        if key in self.routes:
            answer = self.routes[key]
            return answer(request) if callable(answer) else answer
        if key == ("GET", f"/v1/data_sources/{SOURCE}"):
            return httpx.Response(200, json=self.schema)
        if key == ("POST", f"/v1/data_sources/{SOURCE}/query"):
            return self._query(json.loads(request.content))
        if key == ("POST", "/v1/pages"):
            body = json.loads(request.content)
            created = {"id": f"page-{len(self.pages) + 1}", "url": "https://www.notion.so/neu", "properties": {}}
            self.pages.append({**created, "body": body})
            return httpx.Response(200, json=created)
        if request.method == "GET" and request.url.path.startswith("/v1/pages/"):
            found = next((item for item in self.pages if item["id"] == request.url.path.rsplit("/", 1)[1]), None)
            return httpx.Response(200, json=found) if found else httpx.Response(404, json={"code": "object_not_found"})
        return httpx.Response(404, json={"code": "object_not_found"})

    def _query(self, body):
        pool = self.archived if body.get("is_archived") else self.pages
        wanted = (body.get("filter") or {}).get("rich_text", {}).get("equals")
        matches = [item for item in pool if wanted is None or any(
            part.get("plain_text") == wanted
            for value in item.get("properties", {}).values() if value.get("id") == "k1"
            for part in value.get("rich_text", []))]
        start = int(body.get("start_cursor") or 0)
        chunk = matches[start:start + self.page_size]
        more = start + self.page_size < len(matches)
        return httpx.Response(200, json={"results": chunk, "has_more": more,
                                         "next_cursor": str(start + self.page_size) if more else None})


def writer(api, fields=FIELDS, open_status="open", done=("done",), logger=None, policy=None):
    return NotionTasks("secret-token", SOURCE, fields, open_status, done, transport=httpx.MockTransport(api),
                       logger=logger, policy=policy)


def task(**changes):
    return proposal(status="confirmed", target=SOURCE, **changes)


def confirm(item, target_writer):
    saved = []
    result, _ = execute_confirmed(item, target_writer, saved.append)
    return result, [value.status.value for value in saved]


def test_a_task_page_is_created_once_with_every_mapped_property():
    api = FakeNotion()
    created, states = confirm(task(description="Formular abgeben", due="2026-05-12",
                                   mail_link="https://mail.google.com/mail/u/0/#search/rfc822msgid%3Aabc"), writer(api))
    assert created.status == ProposalStatus.CREATED and created.external_id == "page-1" and states[-1] == "created"
    assert created.external_link == "https://www.notion.so/neu"
    body = json.loads(api.requests[-1].content)
    assert body["parent"] == {"type": "data_source_id", "data_source_id": SOURCE}
    values = body["properties"]
    assert values["title"]["title"][0]["text"]["content"] == "Tun"
    assert values["d1"]["rich_text"][0]["text"]["content"] == "Formular abgeben"
    assert values["k1"]["rich_text"][0]["text"]["content"].startswith("mailhelp:")
    assert values["d2"] == {"date": {"start": "2026-05-12"}} and values["s1"] == {"status": {"id": "open"}}
    assert values["u1"] == {"url": "https://mail.google.com/mail/u/0/#search/rfc822msgid%3Aabc"}
    assert api.requests[-1].headers["Authorization"] == "Bearer secret-token"
    # The schema was read again right before the write.
    assert [request.method + request.url.path for request in api.requests][-2] == f"GET/v1/data_sources/{SOURCE}"


def test_times_keep_their_offset_and_missing_values_stay_empty():
    api = FakeNotion()
    confirm(task(id="p2", due="2026-05-12T18:00:00+02:00", mail_link="message://%3Cx@example.org%3E"), writer(api))
    values = json.loads(api.requests[-1].content)["properties"]
    assert values["d2"] == {"date": {"start": "2026-05-12T18:00:00+02:00"}} and values["u1"] == {"url": None}
    confirm(task(id="p3"), writer(api))
    assert json.loads(api.requests[-1].content)["properties"]["d2"] == {"date": None}


def test_status_as_select_or_checkbox_and_without_status():
    select = json.loads(json.dumps(SCHEMA))
    select["properties"]["Status"] = {"id": "s1", "type": "select", "select": {"options": [{"id": "open"}]}}
    api = FakeNotion(schema=select)
    confirm(task(), writer(api, done=()))
    assert json.loads(api.requests[-1].content)["properties"]["s1"] == {"select": {"id": "open"}}
    checkbox = json.loads(json.dumps(SCHEMA))
    checkbox["properties"]["Status"] = {"id": "s1", "type": "checkbox"}
    api = FakeNotion(schema=checkbox)
    confirm(task(), writer(api, open_status="", done=()))
    assert json.loads(api.requests[-1].content)["properties"]["s1"] == {"checkbox": False}
    plain = writer(FakeNotion(), fields=FIELDS.model_copy(update={"status": ""}))
    assert plain.limitation == NO_STATUS_NOTE and writer(FakeNotion()).limitation is None
    api = FakeNotion()
    confirm(task(), writer(api, fields=FIELDS.model_copy(update={"status": ""})))
    assert "s1" not in json.loads(api.requests[-1].content)["properties"]


@pytest.mark.parametrize(("change", "message"), [
    (lambda schema: schema["properties"].pop("Vorgang"), "„operation_key“ fehlt"),
    (lambda schema: schema["properties"]["Frist"].update(type="rich_text"), "Typ rich_text, erwartet date"),
    (lambda schema: schema["properties"]["Status"]["status"].update(options=[{"id": "done"}]), "Statusoption"),
    (lambda schema: schema["properties"]["Status"]["status"].update(options=[{"id": "open"}]), "Statusoption"),
])
def test_a_changed_schema_stops_new_writes(change, message):
    schema = json.loads(json.dumps(SCHEMA))
    change(schema)
    api = FakeNotion(schema=schema)
    with pytest.raises(TargetAccessError, match=message):
        writer(api).check_access()
    item = task()
    saved = []
    with pytest.raises(TargetAccessError):
        execute_confirmed(item, writer(api), saved.append)
    assert not [request for request in api.requests if request.url.path == "/v1/pages"]


def test_a_renamed_column_keeps_working_because_ids_are_used():
    schema = json.loads(json.dumps(SCHEMA))
    schema["properties"]["Neuer Name"] = schema["properties"].pop("Aufgabe")
    writer(FakeNotion(schema=schema)).check_access()


def test_reconciliation_searches_open_and_archived_pages_by_key():
    api = FakeNotion([page("a", key="k-1")])
    api.archived = [page("b", key="k-2")]
    target = writer(api)
    assert target.reconcile("k-1") == {"id": "a", "url": "https://www.notion.so/Tun-1"}
    assert target.reconcile("k-2") == {"id": "b", "url": "https://www.notion.so/Tun-1"}
    assert target.reconcile("k-3") is None
    body = json.loads(api.requests[-1].content)
    assert body["filter"] == {"property": "k1", "rich_text": {"equals": "k-3"}} and body["is_archived"] is True


def test_a_key_found_twice_or_an_incomplete_query_stays_unclear():
    logger = RecordingLogger()
    with pytest.raises(ExternalUncertain, match="mehrfach"):
        writer(FakeNotion([page("a", key="k"), page("b", key="k")]), logger=logger).reconcile("k")
    assert ("ERROR", "notion", "reconcile_conflict") in [item[0] for item in logger.events]
    cut = FakeNotion()
    cut.routes[("POST", f"/v1/data_sources/{SOURCE}/query")] = httpx.Response(200, json={
        "results": [], "has_more": False, "next_cursor": None, "request_status": {"type": "incomplete"}})
    with pytest.raises(ExternalUncertain, match="unvollständig"):
        writer(cut).reconcile("k")
    endless = FakeNotion()
    endless.routes[("POST", f"/v1/data_sources/{SOURCE}/query")] = httpx.Response(200, json={
        "results": [], "has_more": True, "next_cursor": "weiter"})
    with pytest.raises(ExternalUncertain, match="zu groß"):
        writer(endless).reconcile("k")
    assert len(endless.requests) == MAX_PAGES


def test_every_page_of_results_is_read():
    api = FakeNotion([page(str(number), key=f"k{number}") for number in range(3)] + [page("x", key="k")],
                     page_size=1)
    api.pages[3]["properties"]["Vorgang"]["rich_text"] = [{"plain_text": "k"}]
    assert writer(api).reconcile("k")["id"] == "x"


@pytest.mark.parametrize("answer", [{"results": "x", "has_more": False}, {"results": [], "has_more": "ja"},
                                    {"results": [], "has_more": True, "next_cursor": None},
                                    {"results": [{"url": "ohne id"}], "has_more": False}])
def test_damaged_query_answers_are_refused(answer):
    api = FakeNotion()
    api.routes[("POST", f"/v1/data_sources/{SOURCE}/query")] = httpx.Response(200, json=answer)
    with pytest.raises(ValueError, match="Schlüsselpfad"):
        writer(api).reconcile("k")


def test_pages_are_read_back_and_open_tasks_skip_done_and_trashed_ones():
    api = FakeNotion([page("a", description="x", due="2026-05-12", status="open"),
                      page("b", status="done"), page("t", in_trash=True),
                      page("c", due="2026-05-12T18:00:00.000+02:00", url="https://evil.example/c")])
    target = writer(api)
    entry = target.read_entry("a")
    assert entry.facts["title"] == "Tun" and entry.facts["description"] == "x" and entry.facts["due"] == "2026-05-12"
    assert not entry.completed and entry.link == "https://www.notion.so/Tun-1"
    assert target.read_entry("b").completed and target.read_entry("t") is None
    assert target.read_entry("c").link is None and target.read_entry("fehlt") is None
    open_tasks = target.fetch_active_tasks()
    assert [item.id for item in open_tasks] == ["a", "c"] and open_tasks[0].url == "https://www.notion.so/Tun-1"
    count = len(api.requests)
    assert target.fetch_active_tasks() == open_tasks and len(api.requests) == count
    assert target.account_binding() == SOURCE and target.supports_remove is False
    expected = target.expected_facts(task(due="2026-05-12", description="x"), "k")
    assert expected["description"] == "x" and expected["due"] == "2026-05-12"
    assert target.expected_facts(event(status="confirmed", target=SOURCE), "k") is None
    target.close()


def test_done_detection_with_checkbox_select_and_without_status():
    checked = page("a")
    checked["properties"]["Status"] = {"id": "s1", "type": "checkbox", "checkbox": True}
    chosen = page("b")
    chosen["properties"]["Status"] = {"id": "s1", "type": "select", "select": {"id": "done"}}
    empty = page("c")
    empty["properties"]["Status"] = {"id": "s1", "type": "select", "select": None}
    target = writer(FakeNotion([checked, chosen, empty]))
    assert target.read_entry("a").completed and target.read_entry("b").completed
    assert not target.read_entry("c").completed
    plain = writer(FakeNotion([chosen]), fields=FIELDS.model_copy(update={"status": ""}))
    assert not plain.read_entry("b").completed


def test_a_failed_read_is_never_an_empty_list_when_strict():
    api = FakeNotion()
    api.routes[("POST", f"/v1/data_sources/{SOURCE}/query")] = httpx.Response(500)
    logger = RecordingLogger()
    target = writer(api, logger=logger)
    assert target.fetch_active_tasks() == []
    assert logger.events[-1][0] == ("WARNING", "notion", "fetch_tasks_failed")
    with pytest.raises(Exception):
        target.fetch_active_tasks(strict=True)


def test_only_tasks_are_written_and_an_unclear_create_is_never_repeated():
    api = FakeNotion()
    with pytest.raises(ValueError, match="nur Aufgaben"):
        writer(api).prepare(event(status="confirmed", target=SOURCE), "k")
    api.routes[("POST", "/v1/pages")] = httpx.Response(529, headers={"Retry-After": "1"})
    uncertain, states = confirm(task(), writer(api))
    assert uncertain.status == ProposalStatus.UNCERTAIN and states == ["writing", "uncertain"]
    posts = len([request for request in api.requests if request.url.path == "/v1/pages"])
    again, _ = execute_confirmed(uncertain, writer(api), lambda value: None)
    assert again.status == ProposalStatus.UNCERTAIN
    assert len([request for request in api.requests if request.url.path == "/v1/pages"]) == posts


@pytest.mark.parametrize(("status", "error", "reason"), [(403, TargetAccessError, "forbidden"),
                                                          (404, TargetAccessError, "not_found")])
def test_access_errors(status, error, reason):
    api = FakeNotion()
    api.routes[("GET", f"/v1/data_sources/{SOURCE}")] = httpx.Response(status, json={"code": "restricted_resource"})
    with pytest.raises(error) as raised:
        writer(api).check_access()
    assert raised.value.reason == reason


def test_a_refused_token_and_retried_overload():
    api = FakeNotion()
    api.routes[("GET", f"/v1/data_sources/{SOURCE}")] = httpx.Response(401, content=b"kein json")
    with pytest.raises(AuthenticationError, match="Verbindung erneuern"):
        writer(api).check_access()
    answers = iter([httpx.Response(529), httpx.Response(200, json=SCHEMA)])
    api.routes[("GET", f"/v1/data_sources/{SOURCE}")] = lambda request: next(answers)
    writer(api, policy=RetryPolicy(1, 0, 0, lambda delay: False)).check_access()


def test_damaged_schema_or_page_answers_are_refused():
    api = FakeNotion()
    api.routes[("GET", f"/v1/data_sources/{SOURCE}")] = httpx.Response(200, content=b"<html>")
    with pytest.raises(ValueError, match="<json>"):
        writer(api).check_access()
    api.routes[("GET", f"/v1/data_sources/{SOURCE}")] = httpx.Response(200, json=[1])
    with pytest.raises(ValueError, match="<root>"):
        writer(api).account_binding()
    api.routes[("GET", f"/v1/data_sources/{SOURCE}")] = httpx.Response(200, json={"properties": {}})
    with pytest.raises(ValueError, match="Schlüsselpfad id"):
        writer(api).check_access()


def test_helpers():
    assert _link("https://notion.so/x") == "https://notion.so/x" and _link("https://notion.so.evil/x") is None
    assert _link(None) is None
    assert [len(part["text"]["content"]) for part in _chunks("x" * 4001)] == [2000, 2000, 1]
    assert _chunks("") == []
    assert _moment(None) is None and str(_moment("2026-05-12")) == "2026-05-12"
    assert _moment("2026-05-12T18:00:00.000+02:00").hour == 18


def test_an_oauth_grant_is_asked_per_request_and_renewed_after_a_refusal():
    """7.2.5: a refused access token marks the grant stale; the next request carries the renewed one."""
    class Grant:
        def __init__(self):
            self.tokens, self.invalidated = iter(["alt", "neu"]), 0
            self.current = next(self.tokens)

        def access_token(self):
            return self.current

        def invalidate(self):
            self.invalidated += 1
            self.current = next(self.tokens)

    grant, seen = Grant(), []

    def handler(request):
        seen.append(request.headers["Authorization"])
        return httpx.Response(401) if request.headers["Authorization"] == "Bearer alt" else httpx.Response(200, json=SCHEMA)
    target = NotionTasks(grant, SOURCE, FIELDS, "open", ("done",), transport=httpx.MockTransport(handler))
    with pytest.raises(AuthenticationError):
        target.check_access()
    target.check_access()
    assert grant.invalidated == 1 and seen == ["Bearer alt", "Bearer neu"]
