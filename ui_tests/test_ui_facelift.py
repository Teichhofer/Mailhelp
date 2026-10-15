"""Navigation and page hierarchy stay clear on desktop and narrow phones."""
from playwright.sync_api import expect
from web_scenario import mail_id

from checks import audit
from conftest import sign_in


def test_navigation_leaves_room_for_the_work_area(page, mailhelp):
    sign_in(page, mailhelp)
    nav = page.get_by_role("navigation", name="Hauptnavigation")
    box = nav.bounding_box()
    main = page.locator("main").bounding_box()
    assert box is not None and main is not None
    if page.device == "desktop":
        assert box["x"] + box["width"] <= main["x"]
        assert box["height"] > 300
    else:
        header = page.locator("header.top").bounding_box()
        assert header is not None and header["height"] <= 125
        assert nav.evaluate("node => getComputedStyle(node).overflowX") == "auto"
    assert audit(page, "facelift-overview-" + page.device, page.mobile) == []
    assert mailhelp.writer.created == []


def test_phone_card_context_expands_without_creating_an_entry(page, mailhelp):
    sign_in(page, mailhelp)
    card = page.locator(f"#v-{mail_id(1)}-elternabend")
    if page.mobile:
        context = card.locator("details.card-context")
        expect(context).not_to_have_attribute("open", "")
        context.locator("summary").first.click()
        expect(context).to_have_attribute("open", "")
        context.get_by_text("Beleg vollständig anzeigen").click()
        expect(context.locator(".full")).to_be_visible()
        assert audit(page, "facelift-card-context-" + page.device, page.mobile) == []
        card.scroll_into_view_if_needed()
        page.screenshot(path=".test-tmp/ui-screens/facelift-phone-viewport-" + page.device + ".png")
    else:
        expect(card.locator(".card-context")).not_to_be_visible()
    assert mailhelp.writer.created == []


def test_page_context_precedes_the_decision_filters(page, mailhelp):
    sign_in(page, mailhelp)
    heading = page.get_by_role("heading", name="Offene Entscheidungen")
    filters = page.locator(".filter-chips").first
    title_box, filter_box = heading.bounding_box(), filters.bounding_box()
    assert title_box is not None and filter_box is not None
    assert title_box["y"] + title_box["height"] <= filter_box["y"]
    expect(page.get_by_text("Vorschläge prüfen, Rückfragen klären und Entscheidungen treffen.")).to_be_visible()


def test_settings_categories_can_be_reached_directly_in_both_themes(page, mailhelp):
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/einstellungen")
    categories = page.get_by_role("navigation", name="Einstellungsbereiche")
    from mailhelp.web.settings_pages import SETTING_GROUPS
    expect(categories.get_by_role("link")).to_have_count(len(SETTING_GROUPS) + 1)
    categories.get_by_role("link", name="Aufbewahrung", exact=True).click()
    retention = [title for title, _ in SETTING_GROUPS].index("Aufbewahrung")
    expect(page.locator(f"#settings-{retention}")).to_be_in_viewport()
    assert audit(page, "facelift-settings-" + page.device, page.mobile) == []
    page.emulate_media(color_scheme="dark")
    assert audit(page, "facelift-settings-dark-" + page.device, page.mobile) == []
    assert mailhelp.writer.created == []
