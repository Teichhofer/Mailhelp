"""Planung 5.0, step 21.5 (5.0.9): "A" confirms, and the shortcuts are found in the sidebar."""
from playwright.sync_api import expect

from checks import audit
from conftest import item, sign_in
from pages import Overview
from tests.scenarios.web_scenario import mail_id


def test_a_confirms_like_c_and_enter(page, mailhelp):
    if page.device != "desktop":
        return
    sign_in(page, mailhelp)
    item(page, f"#v-{mail_id(1)}-elternabend")
    page.locator("body").focus()
    with page.expect_request("**/aktion"):
        page.keyboard.press("a")
    expect(Overview(page).notice).to_contain_text("Angelegt.", timeout=15000)
    assert mailhelp.writer.created == ["Elternabend Klasse 4b"] and page.errors == []


def test_the_sidebar_offers_the_shortcut_help(page, mailhelp):
    sign_in(page, mailhelp)
    hint = page.get_by_role("button", name="Tastenkürzel")
    if page.device != "desktop":
        # Phones have no keyboard shortcuts in reach; the hint lives in the sidebar only.
        expect(hint).to_be_hidden()
        return
    expect(hint).to_be_visible()
    assert hint.bounding_box()["height"] >= 44
    hint.click()
    dialog = page.get_by_role("dialog", name="Tastenkürzel")
    expect(dialog).to_contain_text("A / C / Enter")
    expect(dialog).to_contain_text("Bestätigen")
    assert audit(page, "shortcuts-50", False) == []
    dialog.get_by_role("button", name="Schließen").click()
    # Collapsed to icons, the hint keeps its accessible name.
    page.get_by_role("button", name="Navigation einklappen").click()
    expect(page.get_by_role("button", name="Tastenkürzel")).to_be_visible()
    assert page.errors == []

