"""6.1.5: "Prüfen" in the first setup – result box, links to the field and values kept, in a real browser."""
from __future__ import annotations

import re
from types import SimpleNamespace

import pytest
from playwright.sync_api import expect

from checks import audit
from mailhelp.runtime.setup_messages import SetupProblem
from mailhelp.web.server import WebServer
from tests.fakes.initial_harness import InitialHarness


@pytest.fixture
def setup_server(tmp_path):
    h = InitialHarness(tmp_path)
    server = WebServer("127.0.0.1", 0, h.app, SimpleNamespace(event=lambda *a, **kw: None))
    server.start()
    host, port = server.address
    h.app.allowed_hosts = frozenset({f"{host}:{port}"})
    h.url = f"http://{host}:{port}"
    h.code = h.auth.issue_code()
    try:
        yield h
    finally:
        server.stop()
        h.close()


def login(page, h):
    page.goto(h.url + "/einrichtung/start")
    page.get_by_label("Code aus der Mailhelp-Konsole").fill(h.code)
    page.get_by_role("button", name="Gerät koppeln", exact=True).click()
    expect(page.get_by_role("heading", name=re.compile("^Mailhelp einrichten: "))).to_be_visible()


def test_initial615_a_problem_is_explained_above_the_form_and_links_to_its_field(page, setup_server):
    h = setup_server
    login(page, h)
    page.get_by_label("Zeitzone", exact=True).fill("Europe/Vienna")
    page.get_by_label("Web-Passwort (mindestens 12 Zeichen)").fill("kurz")
    page.get_by_role("button", name="Prüfen", exact=True).click()
    box = page.locator("#pruefergebnis")
    expect(box).to_be_focused()
    expect(box).to_have_attribute("role", "alert")
    expect(box).to_contain_text("Das Web-Passwort ist zu kurz.")
    # Entered values stay, the password does not come back.
    expect(page.get_by_label("Zeitzone", exact=True)).to_have_value("Europe/Vienna")
    password = page.get_by_label("Web-Passwort (mindestens 12 Zeichen)")
    expect(password).to_have_value("")
    expect(password).to_have_attribute("aria-invalid", "true")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert audit(page, "initial615-problem-" + page.device, page.mobile) == []
    box.get_by_role("link", name="Feld „Web-Passwort“").click()
    assert page.evaluate("location.hash") == "#feld-password"
    assert h.setup.state().completed_step == 0  # checking saved nothing
    assert page.errors == []


def test_initial615_the_mailbox_check_says_it_is_running_and_offers_the_folders(page, setup_server):
    h = setup_server
    h.advance()
    login(page, h)
    page.goto(h.url + "/einrichtung/schritt/2")

    # While the server checks, the page says so; the submission is held back here to read it.
    hint = page.evaluate("""() => {
        const button = document.querySelector('[data-check]');
        button.form.addEventListener('submit', (event) => event.preventDefault());
        button.click();
        return document.querySelector('[data-check-status]').textContent; }""")
    assert hint.startswith("Wird geprüft")
    page.collect()
    page.reload()
    h.checks.imap = lambda *args: {"folders": ["INBOX", "Entwürfe"], "inbox": "INBOX", "drafts": "Entwürfe",
                                   "server": "imap.example.test:993 (ssl)"}
    page.get_by_role("button", name="Prüfen", exact=True).click()
    expect(page.locator("#pruefergebnis")).to_contain_text("Das Postfach ist erreichbar und lesbar.")
    expect(page.get_by_role("combobox", name="Entwurfsordner", exact=True)).to_have_value("Entwürfe")
    assert audit(page, "initial615-ok-" + page.device, page.mobile) == []
    h.checks.imap = lambda *args: (_ for _ in ()).throw(SetupProblem("imap.auth_failed"))
    page.get_by_role("button", name="Prüfen", exact=True).click()
    expect(page.locator("#pruefergebnis")).to_contain_text("App-Passwort")
    expect(page.get_by_label("IMAP_PASSWORD", exact=True)).to_have_attribute("aria-invalid", "true")


def test_initial615_overview_and_checks_without_javascript(page, setup_server):
    h = setup_server
    h.advance()
    page.cdp.send("Emulation.setScriptExecutionDisabled", {"value": True})
    login(page, h)
    page.goto(h.url + "/einrichtung/schritt/5")
    h.checks.llm = lambda *args: (_ for _ in ()).throw(SetupProblem("llm.no_credit"))
    page.get_by_role("button", name="Alles prüfen", exact=True).click()
    box = page.locator("#pruefergebnis")
    expect(box).to_contain_text("✗ Schritt 3: KI-Anbieter")
    expect(box).to_contain_text("✓ Schritt 2: Postfach")
    box.get_by_role("link", name="Zu Schritt 3").click()
    expect(page.get_by_role("heading", name="Mailhelp einrichten: KI-Anbieter")).to_be_visible()
