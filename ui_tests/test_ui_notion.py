"""7.2.6: Notion data source and property mapping in real browsers, against a simulated Notion."""
from __future__ import annotations

import json
from types import SimpleNamespace as NS

import httpx
import pytest
from playwright.sync_api import expect

from checks import audit
from conftest import sign_in
from mailhelp.app.browser_accounts import attach_accounts
from mailhelp.app.setup_runtime import SetupRuntime
from mailhelp.config import Settings, read_yaml
from mailhelp.processing.orchestrator import Orchestrator
from mailhelp.runtime import notion_sources
from tests.fakes.shared_core import prompt_config

SOURCE = "a" * 32
SCHEMA = {"id": SOURCE, "properties": {
    "Aufgabe": {"id": "title", "name": "Aufgabe", "type": "title"},
    "Text": {"id": "d1", "name": "Text", "type": "rich_text"},
    "Vorgang": {"id": "k1", "name": "Vorgang", "type": "rich_text"},
    "Frist": {"id": "f1", "name": "Frist", "type": "date"},
    "Quelle": {"id": "u1", "name": "Quelle", "type": "url"},
    "Status": {"id": "s1", "name": "Status", "type": "status",
               "status": {"options": [{"id": "o1", "name": "Offen"}, {"id": "o2", "name": "Fertig"}]}}}}


def notion_api(request):
    if request.url.path == "/v1/search":
        assert json.loads(request.content)["filter"] == {"property": "object", "value": "data_source"}
        return httpx.Response(200, json={"results": [{"id": SOURCE, "title": [{"plain_text": "Familienaufgaben"}]}],
                                         "has_more": False, "next_cursor": None})
    assert request.method == "GET" and request.url.path == f"/v1/data_sources/{SOURCE}"
    return httpx.Response(200, json=SCHEMA)


@pytest.fixture
def notion(mailhelp, tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("NOTION_TOKEN=synthetic-notion\n", encoding="utf-8")
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    original = notion_sources._client
    monkeypatch.setattr(notion_sources, "_client",
                        lambda token, transport: original(token, httpx.MockTransport(notion_api)))
    cfg = Settings.model_validate(read_yaml(tmp_path / "config.yaml"))
    analyzer = NS(prompts=prompt_config())
    app = NS(settings=cfg, store=mailhelp.store, dialog=mailhelp.dialog, logger=mailhelp.site.logger,
             telegram=NS(check_access=lambda: None), calendar=NS(check_access=lambda: None),
             todoist=NS(check_access=lambda: None), analyzer=analyzer, services=NS(),
             openrouter=NS(complete=lambda *args, **kw: None, check_access=lambda: None),
             configuration=mailhelp.site.archive.configuration)
    app.orchestrator = Orchestrator(analyzer, mailhelp.store, object(), 2, [], 1024)
    app.orchestrator.configure_mailboxes(cfg, analyzer.prompts, {"0" * 24: 1})
    runtime = SetupRuntime(app, mailhelp.site, None, target_probe=lambda service, settings: None)
    mailhelp.site.setup_page.runtime = runtime
    attach_accounts(app, mailhelp.site, tmp_path)
    mailhelp.runtime = runtime
    return mailhelp


def test_a_notion_source_and_mapping_are_saved_as_a_draft(page, notion):
    sign_in(page, notion)
    page.goto(notion.url + "/einstellungen/zielprofile")
    page.get_by_role("link", name="Notion-Datenquelle für Profil 1 auswählen", exact=True).click()
    expect(page.get_by_role("heading", name="Notion-Datenquelle auswählen", exact=True)).to_be_visible()
    page.get_by_role("combobox", name="Datenquelle", exact=True).select_option(SOURCE)
    page.get_by_role("button", name="Als Entwurf speichern", exact=True).click()
    expect(page.get_by_role("heading", name="Notion-Eigenschaften zuordnen", exact=True)).to_be_visible()
    for label, value in (("Titel", "title"), ("Beschreibung", "d1"), ("Frist", "f1"),
                         ("Quelle (Link zur Mail)", "u1"), ("Vorgangsschlüssel", "k1"),
                         ("Status (optional)", "s1"), ("Status neuer Seiten", "o1")):
        page.get_by_role("combobox", name=label, exact=True).select_option(value)
    page.get_by_role("checkbox", name="Status: Fertig", exact=True).check()
    assert audit(page, "notion-zuordnung-" + page.device, page.mobile) == []
    page.get_by_role("button", name="Als Entwurf speichern", exact=True).click()
    page.wait_for_url("**/einrichtung")
    expect(page.locator("main")).to_contain_text("notion_data_source_id")
    patch = notion.runtime.setup.state().patch
    assert patch["targets.notion_data_source_id"] == SOURCE
    assert patch["targets.notion_properties"]["status"] == "s1" and patch["targets.notion_done_statuses"] == ["o2"]
    assert page.errors == []


def test_a_text_column_as_due_date_is_refused_in_the_browser(page, notion):
    sign_in(page, notion)
    page.goto(notion.url + "/notion/datenquelle?profile=1")
    page.get_by_role("button", name="Als Entwurf speichern", exact=True).click()
    expect(page.get_by_role("heading", name="Notion-Eigenschaften zuordnen", exact=True)).to_be_visible()
    # Only date properties are offered for the due date; a forged value is refused by the server.
    expect(page.get_by_role("combobox", name="Frist", exact=True).locator("option")).to_have_count(2)
    page.evaluate("document.querySelector('select[name=due]').add(new Option('Text', 'd1', true, true))")
    for label, value in (("Titel", "title"), ("Beschreibung", "d1"), ("Quelle (Link zur Mail)", "u1"),
                         ("Vorgangsschlüssel", "k1")):
        page.get_by_role("combobox", name=label, exact=True).select_option(value)
    page.get_by_role("button", name="Als Entwurf speichern", exact=True).click()
    expect(page.get_by_role("heading", name="Notion-Auswahl nicht möglich", exact=True)).to_be_visible()


def test_the_notion_mapping_works_in_webkit_on_a_phone(browser_runtime, notion):
    webkit = browser_runtime.webkit.launch()
    try:
        context = webkit.new_context(**browser_runtime.devices["iPhone 13"])
        phone = context.new_page()
        phone.goto(f"{notion.url}/anmelden")
        phone.get_by_role("button", name="Code per Telegram senden").click()
        # The code is read only once it was sent; WebKit returns from the click earlier than Chrome.
        expect(phone.get_by_label("Code aus Telegram")).to_be_visible()
        phone.get_by_label("Code aus Telegram").fill(notion.pairing_code())
        phone.get_by_role("button", name="Gerät koppeln").click()
        phone.wait_for_url(f"{notion.url}/")
        phone.goto(notion.url + "/notion/datenquelle?profile=1")
        phone.get_by_role("button", name="Als Entwurf speichern", exact=True).click()
        expect(phone.get_by_role("heading", name="Notion-Eigenschaften zuordnen", exact=True)).to_be_visible()
        expect(phone.get_by_role("combobox", name="Titel", exact=True).locator("option")).to_have_count(2)
        context.close()
    finally:
        webkit.close()
