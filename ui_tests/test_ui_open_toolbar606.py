"""6.0.6: the compact tool row of the open decisions on phones, desktop and wide screens."""
from __future__ import annotations

from playwright.sync_api import expect

from checks import audit
from conftest import sign_in
from tests.scenarios.web_scenario import mail_id


def test_toolbar606_search_sort_and_group_keep_each_other_and_survive_reload(page, mailhelp):
    sign_in(page, mailhelp)
    toolbar = page.locator(".open-toolbar")
    if page.mobile:  # 6.2.8: on phones search and sort start folded
        toolbar.locator(".open-more > summary").click()
    toolbar.get_by_label("Suchen", exact=True).fill("klassenleitung")
    toolbar.get_by_label("Sortierung", exact=True).select_option("datum")
    toolbar.get_by_label("Nach Bearbeitungsbedarf gruppieren", exact=True).check()
    toolbar.get_by_role("button", name="Anzeigen", exact=True).click()
    expect(page.locator("h1 .count")).to_have_text("2 von 6")
    expect(page.get_by_role("heading", name="Bereit zum Bestätigen 2")).to_be_visible()
    # The task with the earlier due date comes first.
    ids = page.locator(".open-items article.card").evaluate_all("(nodes) => nodes.map((node) => node.id)")
    assert ids == [f"v-{mail_id(1)}-formular", f"v-{mail_id(1)}-elternabend"]
    if page.device == "desktop":
        # The split view shows a visible decision, never a filtered-out one.
        expect(page.locator(".detail-pane")).to_contain_text("Einverständniserklärung")
    # A quick filter keeps search, sort and grouping.
    toolbar.get_by_role("link", name="Termine", exact=True).click()
    expect(page.locator("h1 .count")).to_have_text("1 von 6")
    page.reload()
    expect(page.locator("h1 .count")).to_have_text("1 von 6")
    expect(page.locator(".open-toolbar").get_by_label("Suchen", exact=True)).to_have_value("klassenleitung")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert audit(page, "toolbar606-" + page.device, page.mobile) == []
    page.locator(".open-toolbar").get_by_role("link", name="Zurücksetzen", exact=True).click()
    expect(page.locator("h1 .count")).to_have_text("6")
    assert mailhelp.writer.created == []
    assert page.errors == []


def test_toolbar606_no_match_and_wide_screens(page, mailhelp):
    if page.device != "desktop":
        return
    page.set_viewport_size({"width": 2560, "height": 1440})
    sign_in(page, mailhelp)
    # Two compact lines: the quick filters, then search, sort, grouping and buttons side by side.
    search, reset = page.locator("#open-q").bounding_box(), page.locator(".open-search a.button").bounding_box()
    assert reset["x"] > search["x"] and abs((search["y"] + search["height"]) - (reset["y"] + reset["height"])) < 8
    chips, form = page.locator(".filter-chips").bounding_box(), page.locator(".open-search").bounding_box()
    assert 0 <= form["y"] - (chips["y"] + chips["height"]) < 16 and form["height"] < 90
    assert audit(page, "toolbar606-wide", False) == []
    page.goto(mailhelp.url + "/?q=gibtsnicht")
    expect(page.get_by_text("Keine passenden Entscheidungen.", exact=False)).to_be_visible()
    expect(page.locator(".open-toolbar")).to_be_visible()


def test_toolbar606_works_without_javascript(page, mailhelp):
    page.cdp.send("Emulation.setScriptExecutionDisabled", {"value": True})
    sign_in(page, mailhelp)
    page.locator("#open-q").fill("zahnarzt")
    page.get_by_role("button", name="Anzeigen", exact=True).click()
    expect(page.locator("h1 .count")).to_have_text("1 von 6")
    page.go_back()
    expect(page.locator("h1 .count")).to_have_text("6")
