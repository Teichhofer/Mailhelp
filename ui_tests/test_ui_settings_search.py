"""Planung 5.3, step H3: a link to one setting opens it, also after a direct page load."""
from playwright.sync_api import expect

from checks import audit
from conftest import sign_in


def test_a_setting_anchor_opens_its_row(page, mailhelp):
    sign_in(page, mailhelp)
    page.goto(f"{mailhelp.url}/einstellungen?suche=Zeitzone")
    expect(page.locator("#einstellung-timezone")).to_be_visible()
    page.goto(f"{mailhelp.url}/einstellungen?suche=Zeitzone#einstellung-timezone")
    expect(page.locator("#einstellung-timezone details")).to_have_attribute("open", "")
    # 8.5: in a section form the link focuses the value, also a cell of the timeouts table.
    page.goto(f"{mailhelp.url}/einstellungen?bereich=allgemein#einstellung-timezone")
    expect(page.locator("#einstellung-timezone input, #einstellung-timezone select")).to_be_focused()
    page.goto(f"{mailhelp.url}/einstellungen?bereich=erweitert#einstellung-timeouts-imap-retries")
    expect(page.locator("#einstellung-timeouts-imap-retries")).to_be_focused()
    page.goto(f"{mailhelp.url}/einstellungen?bereich=erweitert#gibt-es-nicht")
    assert audit(page, "settings-anchor-53-" + page.device, page.mobile) == []
    assert page.errors == []
