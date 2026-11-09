"""Navigation for every width (Planung 5.0, 21.2) in an actual browser."""
from playwright.sync_api import expect

from checks import audit
from conftest import Page, sign_in


def test_more_menu_opens_and_marks_the_current_area(page, mailhelp):
    sign_in(page, mailhelp)
    if not page.mobile:
        expect(page.get_by_role("navigation", name="Schnellnavigation")).to_be_hidden()
        return
    tabs = page.get_by_role("navigation", name="Schnellnavigation")
    expect(tabs.locator(".nav-count")).to_be_visible()
    tabs.get_by_text("Mehr", exact=True).click()
    assert audit(page, "navigation-more-" + page.device, page.mobile) == []
    tabs.get_by_role("link", name="Einstellungen").click()
    page.wait_for_url(f"{mailhelp.url}/einstellungen")
    expect(page.locator(".tab-more.has-current > summary")).to_be_visible()
    # The sticky actions of a card stay above the bar.
    page.goto(mailhelp.url + "/")
    actions = page.locator(".card .actions").first
    actions.scroll_into_view_if_needed()
    bar, box = tabs.bounding_box(), actions.bounding_box()
    assert bar is not None and box is not None and box["y"] + box["height"] <= bar["y"] + 1
    assert mailhelp.writer.created == []


def test_tablet_shows_an_icon_rail_with_accessible_names(browser, mailhelp):
    context = browser.new_context(viewport={"width": 1000, "height": 800})
    try:
        page = Page(context.new_page(), "tablet")
        page.mobile = False
        sign_in(page, mailhelp)
        nav = page.get_by_role("navigation", name="Hauptnavigation")
        box = nav.bounding_box()
        assert box is not None and box["width"] <= 76
        expect(nav.get_by_role("link", name="Einstellungen")).to_be_visible()
        expect(page.locator(".nav-toggle")).to_be_hidden()
        expect(page.get_by_role("navigation", name="Schnellnavigation")).to_be_hidden()
        assert audit(page, "navigation-rail", False) == []
    finally:
        page.collect()
        context.close()


def test_desktop_sidebar_collapses_and_keeps_the_choice(page, mailhelp):
    sign_in(page, mailhelp)
    if page.mobile:
        expect(page.locator(".nav-toggle")).to_be_hidden()
        return
    nav = page.get_by_role("navigation", name="Hauptnavigation")
    toggle = page.get_by_role("button", name="Navigation einklappen")
    expect(toggle).to_have_attribute("aria-expanded", "true")
    toggle.click()
    expect(page.get_by_role("button", name="Navigation ausklappen")).to_have_attribute("aria-expanded", "false")
    assert nav.bounding_box()["width"] <= 76
    assert audit(page, "navigation-collapsed", False) == []
    page.reload()
    expect(page.locator("body.nav-collapsed")).to_have_count(1)
    page.get_by_role("button", name="Navigation ausklappen").click()
    expect(page.get_by_role("button", name="Navigation einklappen")).to_be_visible()
    page.reload()
    expect(page.locator("body.nav-collapsed")).to_have_count(0)
    assert nav.bounding_box()["width"] >= 200


def test_blocked_storage_only_loses_the_remembered_choice(page, mailhelp):
    page.add_init_script("""
        Storage.prototype.getItem = function () { throw new Error('blocked'); };
        Storage.prototype.setItem = function () { throw new Error('blocked'); };
    """)
    sign_in(page, mailhelp)
    if page.mobile:
        return
    page.get_by_role("button", name="Navigation einklappen").click()
    expect(page.locator("body.nav-collapsed")).to_have_count(1)
    page.reload()
    expect(page.locator("body.nav-collapsed")).to_have_count(0)


def test_more_menu_works_without_javascript(browser, mailhelp):
    context = browser.new_context(java_script_enabled=False, viewport={"width": 390, "height": 844})
    try:
        page = context.new_page()
        sign_in(page, mailhelp)
        page.get_by_text("Mehr", exact=True).click()
        page.get_by_role("link", name="Lernen").click()
        page.wait_for_url(f"{mailhelp.url}/lernen")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    finally:
        context.close()
