"""Planung 5.3, step H3: a link to one setting opens it, also after a direct page load."""
from playwright.sync_api import expect

from checks import audit
from conftest import sign_in


def test_a_setting_anchor_opens_its_row(page, mailhelp):
    sign_in(page, mailhelp)
    page.goto(f"{mailhelp.url}/einstellungen?suche=Zeitzone")
    expect(page.locator("#einstellung-timezone")).to_be_visible()
    page.goto(f"{mailhelp.url}/einstellungen?bereich=abruf#einstellung-timezone")
    expect(page.locator("#einstellung-timezone details")).to_have_attribute("open", "")
    assert audit(page, "settings-anchor-53-" + page.device, page.mobile) == []
    assert page.errors == []
