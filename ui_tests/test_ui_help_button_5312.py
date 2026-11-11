"""5.3.12: the floating chat button at the bottom right of the settings pages opens the help chat."""
from playwright.sync_api import expect

from checks import audit
from conftest import sign_in


def test_the_chat_button_sits_bottom_right_and_opens_the_help_chat(page, mailhelp):
    sign_in(page, mailhelp)
    page.goto(f"{mailhelp.url}/einstellungen")
    button = page.get_by_role("button", name="Hilfschat öffnen")
    expect(button).to_be_visible()
    # Regression: below 720 px the general rule hiding navigation icons emptied the button.
    icon = button.locator("svg").bounding_box()
    assert icon is not None and icon["width"] >= 20 and icon["height"] >= 20
    box = button.bounding_box()
    width, height = page.viewport_size["width"], page.viewport_size["height"]
    assert box["width"] >= 44 and box["height"] >= 44
    assert width - (box["x"] + box["width"]) <= 32 and box["x"] > width / 2
    bar = page.locator("nav.tab-bar")
    if bar.is_visible():
        # On phones the button stays above the tab bar instead of covering it.
        assert box["y"] + box["height"] <= bar.bounding_box()["y"]
    else:
        assert height - (box["y"] + box["height"]) <= 32
    assert audit(page, "help-button-5312-" + page.device, page.mobile) == []
    button.click()
    expect(page.page).to_have_url(mailhelp.url + "/einstellungen")
    expect(page.get_by_role("heading", name="Hilfe zu Einstellungen")).to_be_visible()
    # The help page itself and other areas have no floating button.
    expect(page.get_by_role("region", name="Hilfe zu Einstellungen")).to_be_visible()
    page.goto(f"{mailhelp.url}/")
    expect(page.locator(".help-fab")).to_have_count(0)
    assert page.errors == []
