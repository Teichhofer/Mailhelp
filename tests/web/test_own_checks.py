"""8.8.4 (Planung 8.8 AP4, Abnahme 7): "Eigene Verbindungen prüfen" in a customer session.

Regression: until 8.8.3 the check buttons of a mailbox draft showed the diagnosis hints to customers,
e.g. "Zugangsdaten oder App-Passwort in .env … prüfen" – an operator detail. Synthetic checks only.
"""
from __future__ import annotations

import re
import threading

import pytest

from mailhelp.runtime.diagnostics import DiagnosticResult
from mailhelp.web.demo_site import BLOCKED
from mailhelp.web.factory import WebComponents
from mailhelp.web.own_checks import BUDGET_SECONDS, COOLDOWN_SECONDS, PATH, label, status
from mailhelp.web.permissions import customer_may
from tests.fakes.customer_mode import signed_in

MAILBOXES, TARGETS = "/einstellungen/postfaecher", "/einstellungen/zielprofile"
INTERNALS = (".env", "IMAP_", "OPENROUTER", "Token", "openrouter", "TELEGRAM", "/config", "App-Passwort")


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def customer(profiled):
    web = profiled.web
    web.auth.enter_customer_mode("kunde-a")
    web.browser = signed_in(web)
    components = WebComponents(None, web.auth, lambda: "", web.site)  # type: ignore[arg-type]
    profiled.app.configuration.restricted = lambda actor: not components.authorize_operator(actor)
    profiled.checked, profiled.answers = [], {}
    checks = profiled.runtime.diagnostics.checks
    for name in checks:
        checks[name] = lambda actor, name=name: profiled.checked.append(name) or profiled.answers.get(
            name, ("ready", ""))
    profiled.clock = Clock()
    own = web.site.mailbox_page.own_checks
    own.clock = profiled.clock
    return profiled


def check(profiled, back=MAILBOXES, **extra):
    form = profiled.web.form(back, action=PATH)
    return profiled.web.browser.request("POST", PATH, {**form, **extra})


def test_regression_a_customer_checks_own_connections_without_operator_details(customer):
    web = customer.web
    page = web.browser.request("GET", MAILBOXES).body.decode()
    assert "Eigene Verbindungen prüfen" in page and customer_may("POST", PATH)
    customer.answers.update({"imap": ("failed", "auth"), "calendar": ("failed", "timeout")})
    response = check(customer)
    assert response.status == 303 and response.headers["Location"] == MAILBOXES + "?geprueft=1"
    assert set(customer.checked) <= {"imap", "calendar", "todoist", "calendar:2", "tasks:2"}
    assert "imap" in customer.checked and not {"llm", "llm_test", "telegram", "filesystem"} & set(customer.checked)
    page = web.browser.request("GET", MAILBOXES).body.decode()
    section = page[page.index("Eigene Verbindungen</h2>"):]
    assert "Postfächer</strong>: Anmeldung erneuern" in section
    assert "Kalender (Zielprofil 1)</strong>: vorübergehend nicht erreichbar" in section
    assert not any(word in section for word in INTERNALS)
    assert web.writer.created == 0


def test_the_draft_check_buttons_show_the_customer_words(customer):
    web = customer.web
    form = web.form(f"{MAILBOXES}/2?tab=targets", action=MAILBOXES + "/speichern", field="target_profile")
    web.browser.request("POST", MAILBOXES + "/speichern", {**form, "value": "1"})
    state = customer.runtime.diagnostics.state()
    state.results["calendar"] = DiagnosticResult(status="failed", code="auth")
    customer.runtime.diagnostics._save(state)
    page = web.browser.request("GET", MAILBOXES).body.decode()
    draft = page[page.index("Vor dem Übernehmen"):]
    assert "Kalender (Zielprofil 1): Anmeldung erneuern" in draft and ".env" not in draft  # 8.8.3: ".env prüfen"


def test_acceptance_7_a_second_click_waits_and_one_pass_runs_at_a_time(customer):
    assert check(customer).status == 303
    runs = len(customer.checked)
    again = check(customer)
    assert again.status == 429 and again.headers["Retry-After"] == str(int(COOLDOWN_SECONDS))
    assert "gerade geprüft" in again.body.decode() and len(customer.checked) == runs
    customer.clock.now += COOLDOWN_SECONDS
    own = customer.web.site.mailbox_page.own_checks
    own._running.acquire()
    try:
        busy = check(customer)
        assert busy.status == 429 and "läuft bereits" in busy.body.decode()
    finally:
        own._running.release()
    customer.clock.now += COOLDOWN_SECONDS
    assert check(customer).status == 303 and len(customer.checked) == 2 * runs


def test_acceptance_7_the_total_time_limit_and_a_hanging_check(customer):
    diagnostics = customer.runtime.diagnostics
    released = threading.Event()
    diagnostics.timeout = 0.05
    first = next(name for name in diagnostics.checks if name == "imap")

    def slow(actor):
        customer.clock.now += BUDGET_SECONDS  # the pass is out of time after this one
        released.wait(1)
        return "ready", ""
    diagnostics.checks[first] = slow
    try:
        assert check(customer).status == 303
    finally:
        released.set()
    assert customer.checked == []  # nothing after the first one
    page = customer.web.browser.request("GET", MAILBOXES).body.decode()
    assert "Postfächer</strong>: vorübergehend nicht erreichbar" in page


def test_target_profiles_page_bad_input_and_unavailable_runtime(customer, monkeypatch):
    web = customer.web
    page = web.browser.request("GET", TARGETS).body.decode()
    assert 'name="zurueck" value="/einstellungen/zielprofile"' in page
    assert check(customer, TARGETS).headers["Location"] == TARGETS + "?geprueft=1"
    customer.clock.now += COOLDOWN_SECONDS
    assert check(customer, zurueck="https://example.invalid/").headers["Location"] == MAILBOXES + "?geprueft=1"
    customer.clock.now += COOLDOWN_SECONDS
    assert check(customer, key="x").status == 409
    diagnostics = customer.runtime.diagnostics
    monkeypatch.setattr(diagnostics, "run", lambda *args: (_ for _ in ()).throw(ValueError("busy")))
    assert check(customer).status == 303  # a check running elsewhere is skipped
    customer.clock.now += COOLDOWN_SECONDS
    monkeypatch.setattr(diagnostics, "run", lambda *args: (_ for _ in ()).throw(PermissionError("expired")))
    assert check(customer).headers["Location"] == "/anmelden"
    customer.clock.now += COOLDOWN_SECONDS
    form = web.form(MAILBOXES, action=PATH)
    web.site.setup_page.runtime = None
    assert web.browser.request("POST", PATH, form).status == 503


def test_every_status_has_customer_words():
    for state in ("ready", "unchecked", "running", "disabled", "limited"):
        text, _step = status(DiagnosticResult(status=state))
        assert text and not any(word in text for word in INTERNALS)
    for code, expected in (("auth", "Anmeldung erneuern"), ("permission", "Anmeldung erneuern"),
                           ("unauthorized", "Anmeldung erneuern"), ("network", "vorübergehend nicht erreichbar"),
                           ("tls", "vorübergehend nicht erreichbar"), ("service", "vorübergehend nicht erreichbar"),
                           ("interrupted", "vorübergehend nicht erreichbar"), ("configuration", "Einstellung prüfen"),
                           ("", "Einstellung prüfen")):
        assert status(DiagnosticResult(status="failed", code=code))[0] == expected
    assert [label(name) for name in ("imap", "calendar", "todoist", "calendar:3", "tasks:3")] == [
        "Postfächer", "Kalender (Zielprofil 1)", "Aufgaben (Zielprofil 1)", "Kalender (Zielprofil 3)",
        "Aufgaben (Zielprofil 3)"]


def test_the_demo_keeps_the_new_customer_routes_closed():
    for path in (PATH, "/einstellungen/allgemein"):
        assert BLOCKED.fullmatch(path), path
    assert re.fullmatch(r"/einstellungen/verbindungen/pruefen", PATH)
