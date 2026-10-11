"""Login, pairing and device management in the browser (desktop and iPhone)."""
from __future__ import annotations

from playwright.sync_api import expect

from checks import audit
from conftest import sign_in


def test_pairing_flow_is_usable(page, mailhelp):
    page.goto(f"{mailhelp.url}/anmelden")
    assert page.get_by_role("heading", name="Gerät koppeln").is_visible()
    assert audit(page, f"anmelden-start-{page.device}", page.mobile) == []
    page.get_by_role("button", name="Code per Telegram senden").click()
    assert page.get_by_label("Code aus Telegram").is_visible()
    assert audit(page, f"anmelden-code-{page.device}", page.mobile) == []
    real_code = mailhelp.pairing_code()
    assert len(real_code) == 4 and real_code.isdecimal()
    page.get_by_label("Code aus Telegram").fill("0000" if real_code != "0000" else "0001")
    page.get_by_role("button", name="Gerät koppeln").click()
    assert page.get_by_role("alert").inner_text() == "Der Code stimmt nicht."
    assert audit(page, f"anmelden-fehler-{page.device}", page.mobile) == []
    page.get_by_label("Code aus Telegram").fill(mailhelp.pairing_code())
    page.get_by_label("Gerätename").fill(f"Test-{page.device}")
    page.get_by_role("button", name="Gerät koppeln").click()
    page.wait_for_url(f"{mailhelp.url}/")
    assert any("Neues Gerät" in text for text in mailhelp.telegram.sent)
    assert page.errors == []


def test_devices_page_and_sign_out(page, mailhelp):
    sign_in(page, mailhelp, f"Mein {page.device}")
    page.get_by_role("link", name="Geräte").click()
    assert page.get_by_text(f"Mein {page.device}").is_visible()
    assert page.get_by_text("dieses Gerät").is_visible()
    assert audit(page, f"geraete-{page.device}", page.mobile) == []
    page.get_by_role("button", name="Abmelden", exact=True).click()
    page.wait_for_url(f"{mailhelp.url}/anmelden")
    page.goto(f"{mailhelp.url}/geraete")
    page.wait_for_url(f"{mailhelp.url}/anmelden")
    assert page.errors == []


def test_connection_indicator_and_double_submit_protection(page, mailhelp):
    sign_in(page, mailhelp)
    badge = page.locator("#verbindung")
    badge.filter(has_text="Verbunden").wait_for()
    page.context.set_offline(True)
    page.evaluate("window.dispatchEvent(new Event('offline'))")
    assert badge.inner_text() == "PC nicht erreichbar"
    page.evaluate("window.dispatchEvent(new Event('online'))")
    expect(badge).to_have_attribute("data-state", "offline")
    page.context.set_offline(False)
    page.route("**/health", lambda route: route.fulfill(status=503, body="down"))
    page.evaluate("window.dispatchEvent(new Event('online'))")
    expect(badge).to_have_text("PC nicht erreichbar")
    page.unroute("**/health")
    page.evaluate("window.dispatchEvent(new Event('online'))")
    badge.filter(has_text="Verbunden").wait_for()
    assert audit(page, f"verbindung-{page.device}", page.mobile) == []
    # A tap while the request is still on its way must not send the form twice.
    page.goto(f"{mailhelp.url}/geraete")
    page.evaluate("""document.querySelector('form[action="/geraete/alle-abmelden"]')
        .addEventListener('submit', (event) => event.preventDefault())""")
    button = page.get_by_role("button", name="Alle Geräte abmelden")
    button.click()
    expect(button).to_be_disabled()
    assert page.url == f"{mailhelp.url}/geraete"


def test_link_from_telegram_command_signs_in_with_one_tap(page, mailhelp):
    """/web: the link opens the login page with the code already filled in."""
    code = mailhelp.auth.issue_code()
    page.goto(f"{mailhelp.url}/anmelden?code={code}")
    expect(page.get_by_label("Code aus Telegram")).to_have_value(code)
    assert audit(page, f"anmelden-link-{page.device}", page.mobile) == []
    page.get_by_role("button", name="Gerät koppeln").click()
    page.wait_for_url(f"{mailhelp.url}/")
    expect(page.get_by_role("heading", name="Offene Entscheidungen")).to_be_visible()
    assert page.errors == []
