"""6.2.5: the shared tool row on history, mails and evaluation – one row, works without JavaScript."""
from __future__ import annotations

from playwright.sync_api import expect

from checks import audit
from conftest import sign_in

BOTTOMS = """() => Array.from(document.querySelectorAll('.toolbar-row > *'))
  .map((node) => Math.round(node.getBoundingClientRect().bottom))"""


def test_toolbar625_history_filters_in_one_row_and_kept_in_the_address(page, mailhelp):
    page.cdp.send("Emulation.setScriptExecutionDisabled", {"value": True})
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/verlauf")
    toolbar = page.locator("form.toolbar")
    if page.device == "desktop":
        bottoms = page.evaluate(BOTTOMS)
        assert max(bottoms) - min(bottoms) < 12, bottoms  # search, status, kind and button share one row
    toolbar.locator("select[name=status]").select_option(label="Verworfen")
    toolbar.locator("select[name=proposal_kind]").select_option(label="Aufgabe")
    toolbar.get_by_role("button", name="Filtern", exact=True).click()
    query = "/verlauf?q=&status=rejected&proposal_kind=task&kind=&since=&until="
    page.wait_for_url(mailhelp.url + query, timeout=10000)
    expect(page.locator("form.toolbar select[name=status]")).to_have_value("rejected")
    page.locator(".toolbar-more > summary").click()
    expect(page.locator("select[name=kind]")).to_be_visible()
    page.get_by_role("link", name="Zurücksetzen", exact=True).click()
    page.wait_for_url(mailhelp.url + "/verlauf", timeout=10000)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    # The accessibility audit needs JavaScript; the next test runs it on this page.


def test_toolbar625_mails_and_evaluation_have_one_primary_action(page, mailhelp):
    sign_in(page, mailhelp)
    for path, label in (("/verlauf", "Filtern"), ("/mails", "Suchen"), ("/auswertung", "Auswerten")):
        page.goto(mailhelp.url + path)
        primary = page.locator("form.toolbar .button.primary")
        expect(primary).to_have_count(1)
        expect(primary).to_have_text(label)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert audit(page, "toolbar625" + path.replace("/", "-") + "-" + page.device, page.mobile) == []
    assert page.errors == []
