"""4.2: local closure and minimal command polling, including lost connectivity."""
from threading import Event

import pytest
from playwright.sync_api import expect

from checks import audit
from conftest import Page, sign_in
from mailhelp.web.pages import layout
from tests.scenarios.web_scenario import mail_id


@pytest.mark.smoke
def test_already_done_progress_polls_json_and_returns_to_the_overview(page, mailhelp, monkeypatch):
    sign_in(page, mailhelp)
    release = Event()
    execute = mailhelp.dialog.review.execute
    def held(command):
        assert release.wait(30)
        return execute(command)
    monkeypatch.setattr(mailhelp.dialog.review, "execute", held)
    page.goto(f"{mailhelp.url}/vorschlag/{mail_id(1)}/elternabend")
    try:
        with page.expect_response("**/api/aktion/*") as response:
            page.get_by_role("button", name="Schon erledigt", exact=True).click()
        assert response.value.json()["status"] in {"queued", "running"}
        expect(page.locator("[data-card-command-status]").first).to_contain_text("Wird verarbeitet")
        assert audit(page, f"aktion-42-{page.device}", page.mobile) == []
        assert page.locator('head meta[http-equiv="refresh"]').count() == 0
        release.set()
        expect(page.locator("[data-command-result] .notice:visible").filter(has_text="Als schon erledigt erfasst").first).to_contain_text("Als schon erledigt erfasst", timeout=10000)
        assert mailhelp.writer.created == []
        assert mailhelp.store.load(f"proposal-{mail_id(1)}-elternabend")["resolution"] == "already_done"
        assert page.errors == []
    finally:
        release.set()


def test_status_polling_retries_reads_after_errors_without_resubmitting(page, mailhelp, monkeypatch):
    sign_in(page, mailhelp)
    release = Event()
    execute = mailhelp.dialog.review.execute
    def held(command):
        assert release.wait(30)
        return execute(command)
    monkeypatch.setattr(mailhelp.dialog.review, "execute", held)
    calls = []
    def status(route):
        calls.append(route.request.method)
        if len(calls) == 1:
            route.fulfill(status=503, content_type="application/json", body='{"error":"synthetic"}')
        elif len(calls) == 2:
            route.fulfill(status=200, content_type="application/json", body="null")
        else:
            route.continue_()
    page.route("**/api/aktion/*", status)
    page.goto(f"{mailhelp.url}/vorschlag/{mail_id(1)}/elternabend")
    try:
        page.get_by_role("button", name="Schon erledigt", exact=True).click()
        expect(page.get_by_role("status").filter(has_text="Verbindung unterbrochen")).to_be_visible()
        with page.expect_response("**/api/aktion/*"):
            page.wait_for_timeout(100)
        release.set()
        expect(page.locator("[data-command-result] .notice:visible").filter(has_text="Als schon erledigt erfasst").first).to_contain_text("Als schon erledigt erfasst", timeout=10000)
        assert len(mailhelp.site.commands._entries()) == 1
        assert set(calls) == {"GET"} and mailhelp.writer.created == []
    finally:
        release.set()


@pytest.mark.parametrize("navigation_fails", [False, True])
def test_expired_status_poll_redirects_without_reposting(page, mailhelp, navigation_fails):
    sign_in(page, mailhelp)
    mailhelp.auth.revoke_all()
    reads = []
    def expired(route):
        reads.append(route.request.method)
        route.fulfill(status=401, content_type="application/json", body="{}")
    page.route("**/api/aktion/*", expired)
    if navigation_fails:
        page.route(mailhelp.url + "/anmelden", lambda route: route.abort("aborted"))
    # Keep the command pending independently of the operator's execution speed.
    page.route(mailhelp.url + "/aktion/" + "a" * 32, lambda route: route.fulfill(
        status=200, content_type="text/html", body=layout("Aktion läuft",
            '<div data-command-status="/api/aktion/' + "a" * 32 + '"></div>')))
    target = mailhelp.url + "/aktion/" + "a" * 32
    with page.expect_request(mailhelp.url + "/anmelden"):
        page.goto(target, wait_until="domcontentloaded")
    if navigation_fails:
        page.wait_for_timeout(1100)
        expect(page.page).to_have_url(target)
        page.collect()
    else:
        page.wait_for_url("**/anmelden", timeout=10000)
    assert reads == ["GET"]


def test_already_done_without_javascript_uses_the_reload_fallback(browser, mailhelp):
    context = browser.new_context(java_script_enabled=False, locale="de-DE")
    page = Page(context.new_page(), "no-javascript")
    try:
        sign_in(page, mailhelp)
        page.goto(f"{mailhelp.url}/vorschlag/{mail_id(1)}/elternabend")
        page.get_by_role("button", name="Schon erledigt", exact=True).click()
        expect(page.locator("[data-command-result] .notice:visible").filter(has_text="Als schon erledigt erfasst").first).to_contain_text("Als schon erledigt erfasst", timeout=15000)
        assert mailhelp.writer.created == []
    finally:
        context.close()
