"""7.3.2: failed mails in real browsers – report dialog in the list, copying, fallbacks without JavaScript."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from playwright.sync_api import expect

from checks import audit
from conftest import Page, sign_in
from mailhelp.domain.mail import MailState
from mailhelp.domain.processing import ProcessingError
from mailhelp.domain.retry import ProcessingRetry
from tests.scenarios.web_scenario import mail_id

NOW = datetime(2026, 11, 9, 15, 15, 20, tzinfo=UTC)


def fail(mailhelp, number=7):
    state = mailhelp.store.load_model("mail-" + mail_id(number), MailState)
    state.error = ProcessingError(code="llm_schema_validation_exhausted", stage="action_router", occurred_at=NOW)
    state.processing_retry = ProcessingRetry(fingerprint="f", attempts=5, first_failed_at=NOW, last_failed_at=NOW,
                                             abandoned=True)
    mailhelp.store.save("mail-" + mail_id(number), state.model_dump(mode="json"))


def open_report(page, mailhelp):
    page.goto(mailhelp.url + "/mails?state=failed")
    page.get_by_role("link", name="Details", exact=True).first.click()
    dialog = page.get_by_role("dialog", name="Fehlerbericht")
    expect(dialog).to_be_visible()
    return dialog


def test_the_report_opens_as_a_dialog_and_is_copied(page, mailhelp):
    fail(mailhelp)
    sign_in(page, mailhelp)
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    dialog = open_report(page, mailhelp)
    expect(dialog.get_by_role("heading", name="Verarbeitungsfehler")).to_be_visible()
    expect(dialog.get_by_text("Später erneut versuchen", exact=False)).to_be_visible()
    assert audit(page, "fehlerbericht-" + page.device, page.mobile) == []
    dialog.get_by_role("button", name="Bericht kopieren").click()
    expect(dialog.get_by_role("status")).to_have_text("Bericht kopiert.")
    assert page.evaluate("navigator.clipboard.readText()").startswith("=== Mailhelp Fehlerbericht ===")
    dialog.get_by_role("button", name="Schließen").click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    assert page.errors == []


@pytest.mark.parametrize(("script", "message"), [
    ("Object.defineProperty(navigator, 'clipboard', {value: undefined, configurable: true})",
     "Bitte den Bericht markieren und manuell kopieren."),
    ("void (navigator.clipboard.writeText = () => Promise.reject(new Error('verboten')))",
     "Kopieren nicht erlaubt. Bitte den Bericht manuell kopieren."),
])
def test_copying_explains_itself_when_the_clipboard_is_missing_or_refused(page, mailhelp, script, message):
    if page.device != "desktop":
        pytest.skip("Die Kopierfehler sind geräteunabhängig")
    fail(mailhelp)
    sign_in(page, mailhelp)
    page.goto(f"{mailhelp.url}/mail/{mail_id(7)}")
    page.evaluate(script)
    page.get_by_text("Fehlerbericht anzeigen").click()
    page.get_by_role("button", name="Bericht kopieren").click()
    expect(page.get_by_role("status").filter(has_text=message)).to_be_visible()


@pytest.mark.parametrize("answer", [{"status": 500, "body": "Fehler"},
                                    {"status": 200, "content_type": "text/html", "body": "<main>ohne</main>"}])
def test_a_failed_read_falls_back_to_the_mail_page(page, mailhelp, answer):
    if page.device != "desktop":
        pytest.skip("Der Rückfall ist geräteunabhängig")
    fail(mailhelp)
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/mails?state=failed")
    target = f"{mailhelp.url}/mail/{mail_id(7)}"
    calls = []

    def once(route):
        calls.append(route.request.url)
        if len(calls) == 1:
            route.fulfill(**answer)
        else:
            route.continue_()
    page.route(target, once)
    page.get_by_role("link", name="Details", exact=True).first.click()
    page.wait_for_url(target + "#fehlerbericht")
    expect(page.get_by_role("heading", name="Verarbeitungsfehler")).to_be_visible()
    assert len(calls) == 2


def test_without_javascript_the_details_link_leads_to_the_report(browser, mailhelp):
    fail(mailhelp)
    context = browser.new_context(java_script_enabled=False, locale="de-DE")
    page = Page(context.new_page(), "no-javascript")
    try:
        sign_in(page, mailhelp)
        page.goto(mailhelp.url + "/mails?state=failed")
        page.get_by_role("link", name="Details", exact=True).first.click()
        expect(page.get_by_role("heading", name="Verarbeitungsfehler")).to_be_visible()
        page.get_by_role("button", name="Ignorieren", exact=True).first.click()
        expect(page.get_by_role("heading", name="Verarbeitungsfehler")).to_have_count(0)
    finally:
        context.close()
