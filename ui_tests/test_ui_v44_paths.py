"""4.4: every script path of card polling, the progress page and form submission.

Paths that end in a navigation abort it, so the document and its script coverage stay
(see test_ui_v20.test_script_steps_that_end_in_a_navigation).
"""
from playwright.sync_api import expect

from conftest import hold, item, sign_in
from mailhelp.domain.processing import ProcessingSteps
from mailhelp.review.commands import CommandKind, CommandSource, ReviewCommand
from tests.scenarios.web_scenario import mail_id, save_mail

MAIL = mail_id(1)
CARD = f"v-{MAIL}-formular"


def submit(mailhelp, key):
    """A queued web command of the signed-in browser, as if sent from another tab."""
    session = mailhelp.auth.sessions()[-1].id
    entry, _ = mailhelp.site.commands.submit(ReviewCommand(
        kind=CommandKind.ALREADY_DONE, source=CommandSource.WEB, actor=f"web:{session}",
        mail_id=MAIL, proposal_id="formular", version=1, idempotency_key=key))
    mailhelp.site.refresh_overview()
    return entry


def documents(url_part):
    return lambda request: request.resource_type == "document" and url_part in request.url


def abort_documents(page, pattern):
    page.route(pattern, lambda route: route.abort("aborted") if route.request.resource_type == "document"
               else route.fallback())


def test_progress_page_retries_errors_waits_and_then_follows_its_result(page, mailhelp, monkeypatch):
    if page.device != "desktop":
        return
    sign_in(page, mailhelp)
    release = hold(mailhelp, monkeypatch)
    try:
        entry = submit(mailhelp, "synthetic-progress-1")
        replies = []
        def status(route):
            replies.append(1)
            if len(replies) == 1:
                route.fulfill(status=503, content_type="application/json", body="{}")
            else:
                route.fallback()
        page.route("**/api/aktion/*", status)
        page.goto(f"{mailhelp.url}/aktion/{entry.id}")
        expect(page.locator("[data-command-status]")).to_contain_text("Verbindung unterbrochen", timeout=10000)
        with page.expect_response(lambda response: "/api/aktion/" in response.url and response.status == 200):
            pass
        abort_documents(page, f"{mailhelp.url}/aktion/{entry.id}")
        with page.expect_request(documents(f"/aktion/{entry.id}"), timeout=15000):
            release.set()
        page.collect()
        assert mailhelp.writer.created == []
        page.errors[:] = [error for error in page.errors if "503" not in error and "ERR_ABORTED" not in error]
        assert page.errors == []
    finally:
        release.set()


def test_an_expired_session_while_a_card_polls_returns_to_sign_in(page, mailhelp, monkeypatch):
    if page.device != "desktop":
        return
    sign_in(page, mailhelp)
    release = hold(mailhelp, monkeypatch)
    try:
        submit(mailhelp, "synthetic-expired-1")
        page.route("**/api/aktion/*", lambda route: route.fulfill(status=401, body="{}"))
        abort_documents(page, "**/anmelden")
        with page.expect_request(documents("/anmelden"), timeout=10000):
            page.goto(f"{mailhelp.url}/")
        page.collect()
    finally:
        release.set()


def test_a_card_polled_on_its_detail_page_returns_to_the_overview(page, mailhelp, monkeypatch):
    if page.device != "desktop":
        return
    sign_in(page, mailhelp)
    release = hold(mailhelp, monkeypatch)
    try:
        entry = submit(mailhelp, "synthetic-detail-1")
        abort_documents(page, f"{mailhelp.url}/?aktion=*")
        with page.expect_request(documents(f"/?aktion={entry.id}"), timeout=10000):
            page.goto(f"{mailhelp.url}/vorschlag/{MAIL}/formular")
        page.collect()
    finally:
        release.set()


def test_an_unavailable_overview_is_retried_until_the_card_shows_its_result(page, mailhelp, monkeypatch):
    if page.device != "desktop":
        return
    sign_in(page, mailhelp)
    release = hold(mailhelp, monkeypatch)
    try:
        submit(mailhelp, "synthetic-overview-1")
        page.goto(f"{mailhelp.url}/")
        failed = []
        def overview(route):
            if route.request.resource_type == "fetch" and not failed:
                failed.append(1)
                route.fulfill(status=503, body="weg")
            else:
                route.fallback()
        page.route(f"{mailhelp.url}/", overview)
        release.set()
        result = page.locator(f"#{CARD} [data-command-result]")
        expect(result).to_contain_text("Als schon erledigt erfasst", timeout=15000)
        assert failed == [1] and len(mailhelp.site.commands._entries()) == 1
        page.errors[:] = [error for error in page.errors if "503" not in error]
        assert page.errors == []
    finally:
        release.set()


def test_a_refused_post_unlocks_the_card_and_a_second_submit_is_ignored(page, mailhelp):
    sign_in(page, mailhelp)
    page.goto(f"{mailhelp.url}/")
    page.evaluate("""(card) => {
        const form = document.querySelector('#' + card + ' input[name="kind"][value="reject"]').form;
        form.querySelector('input[name="version"]').value = '0';
        form.requestSubmit();
        form.requestSubmit();
    }""", CARD)
    refused = page.locator(f"#{CARD} [role=alert]")
    expect(refused).to_contain_text("unvollständig oder ungültig", timeout=10000)
    assert page.evaluate("""(card) => Array.from(document.querySelectorAll('#' + card + ' button'))
        .every((button) => !button.disabled)""", CARD)
    assert mailhelp.site.commands._entries() == []
    page.errors[:] = [error for error in page.errors if "422" not in error]
    assert page.errors == []


def test_a_form_outside_any_card_returns_to_the_overview_after_admission(page, mailhelp):
    if page.device != "desktop":
        return
    steps = ProcessingSteps(
        preparation="completed", relevance="completed", summary="skipped", summary_notification="skipped",
        action_detection="skipped", action_router="skipped", task_extraction="skipped",
        event_extraction="skipped", normalization="skipped", proposal_building="skipped",
        duplicate_precheck="skipped", proposal_notification="skipped", completion="completed")
    save_mail(mailhelp.store, 7, "Amt <amt@example.test>", "Synthetische Bestätigung", steps=steps)
    sign_in(page, mailhelp)
    page.goto(f"{mailhelp.url}/mail/{mail_id(7)}")
    abort_documents(page, f"{mailhelp.url}/?aktion=*")
    with page.expect_request(documents("/?aktion="), timeout=10000):
        page.get_by_role("button", name="Erneut prüfen").click()
    page.collect()
    assert len(mailhelp.site.commands._entries()) == 1


def test_a_dirty_detail_pane_keeps_the_list_during_a_background_refresh(page, mailhelp):
    if page.device != "desktop":
        return
    sign_in(page, mailhelp)
    pane = item(page, f"#{CARD}")
    pane.get_by_text("Ändern", exact=True).click()
    field = pane.get_by_label("Was soll geändert werden?")
    field.fill("x")
    field.fill("")  # Edited (dirty), but no typed text remains that would block the check.
    page.evaluate("document.querySelector('.master-pane').dataset.old = 'yes'")
    mailhelp.store.save("synthetic-background-state", {"revision": 1})
    mailhelp.site.refresh_overview()
    with page.expect_response(lambda response: response.url == f"{mailhelp.url}/"
                              and response.request.resource_type == "fetch"):
        page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    page.wait_for_timeout(200)
    expect(page.locator(".master-pane[data-old]")).to_have_count(1)
    assert page.errors == []


def test_an_action_on_the_detail_page_returns_to_its_card_on_the_overview(page, mailhelp, monkeypatch):
    if page.device != "desktop":
        return
    sign_in(page, mailhelp)
    release = hold(mailhelp, monkeypatch)
    try:
        page.goto(f"{mailhelp.url}/vorschlag/{MAIL}/formular")
        abort_documents(page, f"{mailhelp.url}/?aktion=*")
        with page.expect_request(documents("/?aktion="), timeout=10000):
            page.get_by_role("button", name="Schon erledigt", exact=True).click()
        page.collect()
        assert len(mailhelp.site.commands._entries()) == 1
    finally:
        release.set()


def test_a_refusal_without_details_outside_a_card_still_explains_and_unlocks(page, mailhelp):
    if page.device != "desktop":
        return
    steps = ProcessingSteps(
        preparation="completed", relevance="completed", summary="skipped", summary_notification="skipped",
        action_detection="skipped", action_router="skipped", task_extraction="skipped",
        event_extraction="skipped", normalization="skipped", proposal_building="skipped",
        duplicate_precheck="skipped", proposal_notification="skipped", completion="completed")
    save_mail(mailhelp.store, 7, "Amt <amt@example.test>", "Synthetische Bestätigung", steps=steps)
    sign_in(page, mailhelp)
    page.goto(f"{mailhelp.url}/mail/{mail_id(7)}")
    page.route(f"{mailhelp.url}/aktion", lambda route: route.fulfill(
        status=400, content_type="application/json", body="{}"))
    page.get_by_role("button", name="Erneut prüfen").click()
    expect(page.get_by_role("alert")).to_contain_text("Die Aktion wurde nicht angenommen.")
    expect(page.get_by_role("button", name="Erneut prüfen")).to_be_enabled()
    assert mailhelp.site.commands._entries() == []
    page.errors[:] = [error for error in page.errors if "400" not in error]
    assert page.errors == []
