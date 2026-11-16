"""5.5.1: the cost and privacy notice takes one quiet line until it is opened."""
from playwright.sync_api import expect

from checks import audit
from conftest import sign_in


def test_window55_cost_notice_opens_by_click_and_keyboard(page, mailhelp):
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/einstellungen")
    page.get_by_label("Hilfschat öffnen", exact=True).click()
    notice = page.locator("#help-window .help-cost-hint")
    summary = notice.locator("summary")
    warning = notice.get_by_text("können Kosten verursachen", exact=False)
    expect(summary).to_have_text("Kostenpflichtig")
    expect(warning).to_be_hidden()
    assert summary.bounding_box()["height"] < 60  # a single line, also on 320 pixels
    summary.click()
    expect(warning).to_be_visible()
    summary.click()
    expect(warning).to_be_hidden()
    summary.focus()
    page.keyboard.press("Enter")
    expect(warning).to_be_visible()
    assert audit(page, "help-window55-cost-" + page.device, page.mobile) == []
    assert page.errors == []
