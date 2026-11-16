"""4.4: immediate return to the overview and several actions in a row on real browsers."""
import pytest
from playwright.sync_api import expect

from checks import audit
from conftest import Page, hold, sign_in
from tests.scenarios.web_scenario import mail_id

MAIL = mail_id(1)


def already_done(page, mailhelp, proposal_id):
    """Submit from the detail page; returns the browser-measured POST response time."""
    page.goto(f"{mailhelp.url}/vorschlag/{MAIL}/{proposal_id}")
    with page.expect_response(lambda response: response.request.method == "POST"
                              and response.url.endswith("/aktion")) as posted:
        page.get_by_role("button", name="Schon erledigt", exact=True).click()
    page.wait_for_url(f"{mailhelp.url}/?aktion=*")
    timing = posted.value.request.timing
    return timing["responseStart"] - timing["requestStart"]


def card(page, proposal_id):
    return page.locator(f'[id$="v-{MAIL}-{proposal_id}"]')


@pytest.mark.smoke
def test_two_cards_are_handled_in_a_row_while_the_operator_is_busy(page, mailhelp, monkeypatch):
    sign_in(page, mailhelp)
    release = hold(mailhelp, monkeypatch)
    try:
        first = already_done(page, mailhelp, "elternabend")
        expect(card(page, "elternabend").locator("[data-card-command-status]").first).to_contain_text(
            "Wird verarbeitet")
        # A second command to the same card is not offered until the first has a result.
        assert card(page, "elternabend").get_by_role("button", name="Schon erledigt").count() == 0
        second = already_done(page, mailhelp, "formular")
        expect(card(page, "formular").locator("[data-card-command-status]").first).to_contain_text(
            "Wird verarbeitet")
        # The first command is running (held), the second waits behind it.
        assert sorted(entry.status.value for entry in mailhelp.site.commands._entries()) == ["queued", "running"]
        assert max(first, second) < 300, (first, second)
        print(f"V44_BROWSER_POST {page.device} {first:.1f} {second:.1f}")
        assert audit(page, f"uebersicht-44-{page.device}", page.mobile) == []
        release.set()
        for proposal_id in ("elternabend", "formular"):
            expect(card(page, proposal_id).locator("[data-command-result] .notice").first).to_contain_text(
                "Als schon erledigt erfasst", timeout=15000)
        assert mailhelp.writer.created == []
        statuses = [mailhelp.store.load(f"proposal-{MAIL}-{pid}")["resolution"]
                    for pid in ("elternabend", "formular")]
        assert statuses == ["already_done", "already_done"]
        assert page.errors == []
    finally:
        release.set()


def test_without_javascript_the_overview_reloads_until_both_results_are_shown(browser, mailhelp, monkeypatch):
    context = browser.new_context(java_script_enabled=False, locale="de-DE")
    page = Page(context.new_page(), "no-javascript")
    release = hold(mailhelp, monkeypatch)
    try:
        sign_in(page, mailhelp)
        already_done(page, mailhelp, "elternabend")
        expect(card(page, "elternabend").get_by_text("Wird verarbeitet").first).to_be_visible()
        already_done(page, mailhelp, "formular")
        release.set()
        for proposal_id in ("elternabend", "formular"):
            expect(card(page, proposal_id).get_by_text("Als schon erledigt erfasst").first).to_be_visible(
                timeout=15000)
        assert mailhelp.writer.created == []
    finally:
        release.set()
        context.close()
