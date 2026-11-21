"""8.2: real-browser test of the 3-step self-service onboarding (/onboarding)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from playwright.sync_api import expect

from checks import audit
from mailhelp.web.server import WebServer
from tests.fakes.initial_harness import InitialHarness


@pytest.fixture
def onboarding_server(tmp_path):
    harness = InitialHarness(tmp_path)
    server = WebServer("127.0.0.1", 0, harness.app, SimpleNamespace(event=lambda *a, **kw: None))
    server.start()
    host, port = server.address
    harness.app.allowed_hosts = frozenset({f"{host}:{port}"})
    harness.url = f"http://{host}:{port}"
    harness.code = harness.auth.issue_code()
    try:
        yield harness
    finally:
        server.stop()
        harness.close()


def test_guided_three_step_onboarding_in_browser(page, onboarding_server):
    h = onboarding_server
    page.goto(h.url + "/onboarding")
    page.get_by_label("Code aus der Mailhelp-Konsole").fill(h.code)
    page.get_by_role("button", name="Gerät koppeln", exact=True).click()
    page.goto(h.url + "/onboarding")
    expect(page.get_by_role("heading", name="Mailhelp einrichten (3 Schritte)")).to_be_visible()

    # Step 1: Mailbox check with provider detection
    page.get_by_label("E-Mail-Adresse des Postfachs").fill("synthetic@web.de")
    page.get_by_role("button", name="Postfach prüfen und weiter", exact=True).click()
    expect(page.get_by_text("WEB.DE")).to_be_visible()
    expect(page.get_by_text("Postfach geprüft")).to_be_visible()

    # Step 2: Target check
    page.get_by_role("button", name="Zielsystem prüfen und weiter", exact=True).click()
    expect(page.get_by_text("Zielsystem geprüft")).to_be_visible()

    # Step 3: Choose topics & test-mode dry run
    page.get_by_role("button", name="5 aktuelle Mails probeweise im Testmodus auswerten", exact=True).click()
    preview_text = "Testmodus-Vorschau: Es wurden keine externen Termine oder Aufgaben angelegt."
    expect(page.get_by_text(preview_text)).to_be_visible()
    assert audit(page, "onboarding-" + page.device, page.mobile) == []

    # Explicit activation
    page.get_by_role("checkbox", name="Einrichtung übernehmen und produktiven Betrieb aktivieren").check()
    page.get_by_role("button", name="Produktiven Betrieb aktivieren", exact=True).click()
    assert (h.directory / "topics.yaml").is_file()
    assert page.errors == []
