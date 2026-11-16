"""7.2.4: choosing a Notion data source and mapping its properties through the signed-in web pages."""
import json
from types import SimpleNamespace

import httpx
import pytest
import yaml

from mailhelp.app.browser_accounts import attach_accounts
from mailhelp.config import TargetProfileSettings
from mailhelp.runtime import notion_sources
from mailhelp.web import notion_site

SOURCE = "a" * 32
OTHER = "b" * 32
SCHEMA = {"id": SOURCE, "properties": {
    "Aufgabe": {"id": "title", "name": "Aufgabe", "type": "title"},
    "Text": {"id": "d1", "name": "Text", "type": "rich_text"},
    "Vorgang": {"id": "k1", "name": "Vorgang", "type": "rich_text"},
    "Frist": {"id": "f1", "name": "Frist", "type": "date"},
    "Quelle": {"id": "u1", "name": "Quelle", "type": "url"},
    "Status": {"id": "s1", "name": "Status", "type": "status",
               "status": {"options": [{"id": "o1", "name": "Offen"}, {"id": "o2", "name": "Fertig"}]}}}}
MAPPING = {"title": "title", "description": "d1", "due": "f1", "source": "u1", "operation_key": "k1"}


class Notion:
    def __init__(self):
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        assert request.headers["Authorization"] == "Bearer synthetic-notion"
        if request.url.path == "/v1/search":
            cursor = json.loads(request.content).get("start_cursor")
            if cursor is None:
                return httpx.Response(200, json={"results": [{"id": SOURCE, "title": [{"plain_text": "Aufgaben"}]}],
                                                 "has_more": True, "next_cursor": "2"})
            return httpx.Response(200, json={"results": [{"id": OTHER, "title": []}], "has_more": False,
                                             "next_cursor": None})
        if request.url.path == f"/v1/data_sources/{SOURCE}":
            return httpx.Response(200, json=SCHEMA)
        return httpx.Response(404)


@pytest.fixture
def notion(configured, monkeypatch):
    c = configured
    c.cfg.target_profiles = [TargetProfileSettings(id=2, label="Work", google_calendar="primary",
                                                   todoist_project="inbox")]
    (c.tmp_path / "config.yaml").write_text(yaml.safe_dump(c.cfg.model_dump(mode="json")))
    (c.tmp_path / ".env").write_text("NOTION_TOKEN=synthetic-notion\nNOTION_2_TOKEN=synthetic-notion\n")
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    c.app.services = SimpleNamespace()
    api = Notion()
    original = notion_sources._client
    monkeypatch.setattr(notion_sources, "_client",
                        lambda token, transport: original(token, httpx.MockTransport(api)))
    attach_accounts(c.app, c.web.site, c.tmp_path)
    c.api = api
    return c


def submit(c, path, changes):
    form = c.web.form(path, action=path.split("?")[0])
    return c.web.browser.request("POST", path.split("?")[0], {**form, **changes})


@pytest.mark.parametrize("number", [1, 2])
def test_a_data_source_and_its_mapping_become_a_settings_draft(notion, number):
    c = notion
    page = c.web.browser.request("GET", f"/notion/datenquelle?profile={number}").body.decode()
    assert "Aufgaben" in page and OTHER in page  # every page of the listing; an untitled one by its id
    response = submit(c, f"/notion/datenquelle?profile={number}", {"source": SOURCE})
    assert response.status == 303 and response.headers["Location"] == f"/notion/zuordnung?profile={number}"
    page = c.web.browser.request("GET", f"/notion/zuordnung?profile={number}").body.decode()
    assert "Aufgabe (title)" in page and "Status: Fertig" in page and "Frist (date)" in page
    response = submit(c, f"/notion/zuordnung?profile={number}",
                      {**MAPPING, "status": "s1", "open": "o1", "done_o2": "1"})
    assert response.status == 303 and response.headers["Location"] == "/einrichtung"
    assert c.web.browser.request("GET", "/einrichtung").status == 200
    patch = c.runtime.setup.state().patch
    values = ({key.removeprefix("targets."): value for key, value in patch.items()} if number == 1
              else patch["target_profiles"][0])
    assert values["notion_data_source_id"] == SOURCE
    assert values["notion_properties"] == {**MAPPING, "status": "s1"}
    assert values["notion_open_status"] == "o1" and values["notion_done_statuses"] == ["o2"]
    # Nothing was written to Notion: only searches and schema reads.
    assert {request.method + " " + request.url.path for request in c.api.requests} <= {
        "POST /v1/search", f"GET /v1/data_sources/{SOURCE}"}


def test_a_mapping_without_status_drops_status_options(notion):
    c = notion
    submit(c, "/notion/datenquelle?profile=1", {"source": SOURCE})
    assert submit(c, "/notion/zuordnung?profile=1", {**MAPPING, "status": "", "open": "o1", "done_o2": "1"}).status == 303
    patch = c.runtime.setup.state().patch
    assert patch["targets.notion_open_status"] == "" and patch["targets.notion_done_statuses"] == []


@pytest.mark.parametrize("changes", [
    {**MAPPING, "due": "d1"},                              # a text property is no date
    {**MAPPING, "title": ""},                              # required field missing
    {**MAPPING, "status": "s1", "open": "fremd"},          # option of no status property
    {**MAPPING, "status": "s1", "open": "o1", "done_x": "1"},
])
def test_wrong_mappings_are_refused(notion, changes):
    c = notion
    submit(c, "/notion/datenquelle?profile=1", {"source": SOURCE})
    version = c.runtime.setup.state().version
    assert submit(c, "/notion/zuordnung?profile=1", changes).status == 409
    assert c.runtime.setup.state().version == version


def test_unknown_sources_profiles_and_missing_choices_fail_safely(notion, monkeypatch):
    c = notion
    assert submit(c, "/notion/datenquelle?profile=1", {"source": "c" * 32}).status == 409
    assert c.web.browser.request("GET", "/notion/zuordnung?profile=1").status == 409  # no source chosen yet
    assert c.web.browser.request("GET", "/notion/datenquelle?profile=99").status == 409
    assert c.web.browser.request("GET", "/notion/datenquelle?profile=0").status == 409
    monkeypatch.setattr(notion_site, "schema", lambda *args: (_ for _ in ()).throw(ValueError("x")))
    submit(c, "/notion/datenquelle?profile=1", {"source": SOURCE})
    # The mapping page cannot load either; a posted mapping is still checked against a fresh read.
    assert c.web.browser.request("GET", "/notion/zuordnung?profile=1").status == 409
    form = c.web.form("/notion/datenquelle?profile=1", action="/notion/datenquelle")
    assert c.web.browser.request("POST", "/notion/zuordnung", {**form, **MAPPING}).status == 409


def test_listing_is_read_completely_or_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTION_TOKEN", "")
    (tmp_path / ".env").write_text("NOTION_3_TOKEN=drei\n")
    assert notion_sources.notion_token(tmp_path, 3) == "drei" and notion_sources.notion_token(tmp_path, 1) == ""
    # 7.2.5: without an internal token the access token of the saved OAuth grant serves.
    (tmp_path / "notion-token.json").write_text(json.dumps({"access_token": "oauth-access", "refresh_token": "r",
                                                            "workspace_id": "w", "bot_id": "b"}))
    assert notion_sources.notion_token(tmp_path, 1) == "oauth-access"
    with pytest.raises(ValueError, match="Token fehlt"):
        notion_sources.data_sources("")
    endless = httpx.MockTransport(lambda request: httpx.Response(200, json={
        "results": [], "has_more": True, "next_cursor": "weiter"}))
    with pytest.raises(ValueError, match="unvollständig"):
        notion_sources.data_sources("t", endless)
    for answer in ({"results": [{"id": ""}], "has_more": False}, {"results": [], "has_more": True, "next_cursor": 3}):
        broken = httpx.MockTransport(lambda request, answer=answer: httpx.Response(200, json=answer))
        with pytest.raises(ValueError, match="Ungültige"):
            notion_sources.data_sources("t", broken)
    refused = httpx.MockTransport(lambda request: httpx.Response(403))
    with pytest.raises(httpx.HTTPStatusError):
        notion_sources.schema("t", SOURCE, refused)
