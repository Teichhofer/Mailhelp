"""7.3.2: failed mails in real browsers – report dialog in the list, copying, fallbacks without JavaScript."""
from __future__ import annotations

import threading
from datetime import UTC, datetime

import pytest
from playwright.sync_api import expect

from checks import audit
from conftest import Page, navigate_collected, sign_in
from mailhelp.domain.mail import MailState
from mailhelp.domain.processing import ProcessingError
from mailhelp.domain.retry import ProcessingRetry
from mailhelp.web.http import Response
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


@pytest.mark.parametrize("answer", [Response.text(500, "Fehler"),
                                    Response.html(200, "<!doctype html><main>ohne Bericht</main>")])
def test_a_failed_read_falls_back_to_the_mail_page(page, mailhelp, answer):
    """The first read answers an error or a page without report; the link then navigates itself.

    The answer comes from the server, not from page.route: the fallback navigates at once, and the
    second request is held until the script coverage of the list page is taken.
    """
    if page.device != "desktop":
        pytest.skip("Der Rückfall ist geräteunabhängig")
    fail(mailhelp)
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/mails?state=failed")
    routes = mailhelp.site.app._routes
    path = f"/mail/{mail_id(7)}"
    index, (method, pattern, handler) = next(
        (index, route) for index, route in enumerate(routes) if route[0] == "GET" and route[1].fullmatch(path))
    calls, entered, release = [], threading.Event(), threading.Event()

    def staged(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            return answer
        entered.set()
        release.wait(10)
        return handler(*args, **kwargs)
    routes[index] = (method, pattern, staged)
    try:
        page.get_by_role("link", name="Details", exact=True).first.click(no_wait_after=True)
        for _ in range(200):
            if entered.is_set():
                break
            page.wait_for_timeout(50)
        assert entered.is_set() and len(calls) == 2
        page.collect()
    finally:
        routes[index] = (method, pattern, handler)
        release.set()
    page.wait_for_url(mailhelp.url + path + "#fehlerbericht")
    expect(page.get_by_role("heading", name="Verarbeitungsfehler")).to_be_visible()


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


def test_all_failed_mails_are_ignored_after_a_confirmation(page, mailhelp):
    """7.3.3: the batch names the count before anything happens and returns to the list."""
    fail(mailhelp, 7)
    fail(mailhelp, 2)
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/mails?state=failed")
    page.get_by_role("link", name="Alle ignorieren", exact=True).click()
    expect(page.get_by_text("Möchtest du alle 2 fehlgeschlagenen Mails als nicht verarbeitet ablegen?")).to_be_visible()
    assert audit(page, "sammelaktion-" + page.device, page.mobile) == []
    page.get_by_role("button", name="Alle ignorieren", exact=True).click()
    expect(page.get_by_text("2 Mails eingereiht.")).to_be_visible()
    # The operator thread executes the queued commands; reload until both left the list.
    for _ in range(50):
        page.reload()
        if page.get_by_role("link", name="Details", exact=True).count() == 0:
            break
        page.wait_for_timeout(200)
    expect(page.get_by_role("link", name="Details", exact=True)).to_have_count(0)
    assert page.errors == []


def test_an_action_in_the_dialog_returns_to_the_failure_list(page, mailhelp):
    """Review 7.3.4: the dialog's buttons come from the mail page and lead back to the list like the row ones."""
    if page.device != "desktop":
        pytest.skip("Der Rücksprung ist geräteunabhängig")
    fail(mailhelp)
    sign_in(page, mailhelp)
    dialog = open_report(page, mailhelp)
    dialog.get_by_role("button", name="Ignorieren", exact=True).click()
    page.wait_for_url("**/mails?state=failed&ergebnis=*")
    expect(page.locator(".notice").first).to_be_visible()
    assert page.errors == []


@pytest.mark.parametrize("start", ["list", "mail"])
def test_with_javascript_an_action_returns_where_it_started(page, mailhelp, start):
    """Regression 7.3.4: with JavaScript, retry and ignore jumped to the overview instead of back."""
    if page.device != "desktop":
        pytest.skip("Der Rücksprung ist geräteunabhängig")
    fail(mailhelp)
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + ("/mails?state=failed" if start == "list" else f"/mail/{mail_id(7)}"))
    # The script leaves at once for /aktion/<id>; hold that page until its coverage is taken.
    navigate_collected(page, mailhelp, page.get_by_role("button", name="Ignorieren", exact=True).first,
                       path="/aktion/" + "a" * 32)
    if start == "list":
        page.wait_for_url("**/mails?state=failed&ergebnis=*")
    else:
        page.wait_for_url(f"**/mail/{mail_id(7)}?ergebnis=*")
    expect(page.get_by_text("Nicht verarbeitet", exact=False).first).to_be_visible()
    assert page.errors == []
