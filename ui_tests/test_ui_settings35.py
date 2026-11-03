"""Settings overview, search and IMAP activation across desktop and phone widths."""
from types import SimpleNamespace as NS

from playwright.sync_api import expect
from shared_decision_test import secrets

from checks import audit
from conftest import sign_in
from mailhelp.config import Secrets


def test_overview_search_and_area_navigation(page, mailhelp):
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/einstellungen")
    expect(page.get_by_role("heading", name="Konten und Verbindungen", exact=True)).to_be_visible()
    assert audit(page, "settings35-overview-" + page.device, page.mobile) == []
    nav = page.get_by_role("navigation", name="Einstellungsbereiche")
    nav.get_by_role("link", name="Mailabruf", exact=True).click()
    expect(page.locator('a[aria-current="page"][href="/einstellungen?bereich=abruf"]')).to_be_visible()
    expect(page.get_by_role("heading", name="Mailabruf und Betrieb", exact=True)).to_be_visible()
    assert audit(page, "settings35-area-" + page.device, page.mobile) == []
    nav.get_by_role("link", name="Übersicht", exact=True).click()
    page.get_by_role("searchbox", name="Einstellung suchen").fill("Mailabruf Zeitzone")
    page.get_by_role("button", name="Suchen", exact=True).click()
    expect(page.locator("details.setting summary")).to_have_count(1)
    expect(page.locator("details.setting summary")).to_contain_text("Zeitzone")
    assert audit(page, "settings35-search-" + page.device, page.mobile) == []
    page.get_by_role("searchbox", name="Einstellung suchen").fill("ohnetreffer")
    page.get_by_role("button", name="Suchen", exact=True).click()
    expect(page.locator('.notice[role="status"]')).to_contain_text("Keine Einstellung")
    page.emulate_media(color_scheme="dark")
    assert audit(page, "settings35-search-dark-" + page.device, page.mobile) == []
    assert mailhelp.writer.created == [] and page.errors == []


def test_mailbox_activation_form_keeps_inputs_on_error_and_then_saves(page, setup_server, monkeypatch):
    runtime = setup_server.site.setup_page.runtime
    runtime.secrets = Secrets.model_validate(secrets().model_dump())
    activated = []
    runtime.app.mailbox_runtime = NS(request=lambda cfg, keys: activated.append((cfg, keys)))
    class Reader:
        fail = True
        def __init__(self, *args, **kwargs): pass
        def close(self): pass
        def list_folders(self): return [NS(name=name) for name in ("INBOX", "Drafts")]
        def check_access(self, folders):
            if self.fail:
                raise OSError("private-server-response")
    monkeypatch.setattr("mailhelp.runtime.experience.ImapReader", Reader)
    sign_in(page, setup_server)
    page.goto(setup_server.url + "/einstellungen/postfaecher")
    form = page.locator('form[action="/einstellungen/postfaecher/aktivieren"]')
    form.get_by_label("Anzeigename", exact=True).fill("Verein")
    form.get_by_label("IMAP-Server", exact=True).fill("imap.example.test")
    form.get_by_label("Benutzername", exact=False).fill("synthetic-user")
    form.get_by_label("Passwort oder App-Passwort", exact=True).fill("synthetic-password")
    assert audit(page, "settings35-mailbox-form-" + page.device, page.mobile) == []
    if page.mobile:
        heights = form.locator("input:not([type=hidden]), select, button").evaluate_all(
            "items => items.map(item => item.getBoundingClientRect().height)")
        assert all(height >= 48 for height in heights)
    form.get_by_role("button", name="Verbindung prüfen und Postfach aktivieren").click()
    expect(page.get_by_role("alert")).to_contain_text("Server nicht erreichbar")
    expect(form.get_by_label("IMAP-Server", exact=True)).to_have_value("imap.example.test")
    expect(form.get_by_label("Passwort oder App-Passwort", exact=True)).to_have_value("")
    assert "private-server-response" not in page.content() and not activated
    assert audit(page, "settings35-mailbox-error-" + page.device, page.mobile) == []
    Reader.fail = False
    form.get_by_label("Passwort oder App-Passwort", exact=True).fill("synthetic-password")
    form.get_by_role("button", name="Verbindung prüfen und Postfach aktivieren").click()
    expect(page.get_by_text("Verbindung geprüft und Postfach gespeichert.", exact=False)).to_be_visible()
    assert len(activated) == 1 and activated[0][0].imap.mailbox(2).label == "Verein"
    assert "synthetic-password" not in page.content() and setup_server.writer.created == []
    assert audit(page, "settings35-mailbox-active-" + page.device, page.mobile) == []
