"""5.9.5: the source mail is open from 1024 px, collapsed below and without JavaScript."""
from __future__ import annotations

from playwright.sync_api import expect

from conftest import item, sign_in
from tests.scenarios.web_scenario import mail_id

SOURCE = "details[data-source-mail]"


def test_regression_a_task_from_a_text_mail_shows_its_mail_in_the_split_view(page, mailhelp):
    """Regression 5.9.5: only image previews opened the source; a task from a plain text mail
    showed no mail in the split view until the section was clicked."""
    sign_in(page, mailhelp)
    if page.device == "desktop":
        item(page, f"#v-{mail_id(1)}-formular")
        source = page.locator(f".detail-pane {SOURCE}")
        expect(source).to_have_attribute("open", "")
        expect(source.locator("#detail-mail")).to_contain_text("Einverständniserklärung")
        # A later resize does not close what the user is reading.
        page.set_viewport_size({"width": 800, "height": 900})
        page.wait_for_timeout(200)
        expect(source).to_have_attribute("open", "")
        page.set_viewport_size({"width": 1366, "height": 900})
    page.goto(f"{mailhelp.url}/vorschlag/{mail_id(1)}/formular")
    source = page.locator(SOURCE)
    expect(source).to_contain_text("Mail von Klassenleitung 4b")
    if page.device == "desktop":
        expect(source).to_have_attribute("open", "")
    else:
        assert source.get_attribute("open") is None
        source.locator("summary").click()
        expect(page.locator("#mail")).to_be_visible()
    assert page.errors == []


def test_without_javascript_the_source_stays_collapsed(page, mailhelp, browser):
    if page.device != "desktop":
        return
    sign_in(page, mailhelp)
    context = browser.new_context(java_script_enabled=False, viewport={"width": 1366, "height": 900})
    try:
        context.add_cookies(page.context.cookies())
        plain = context.new_page()
        plain.goto(f"{mailhelp.url}/vorschlag/{mail_id(1)}/formular")
        source = plain.locator(SOURCE)
        expect(source).to_have_count(1)
        assert source.get_attribute("open") is None
    finally:
        context.close()
