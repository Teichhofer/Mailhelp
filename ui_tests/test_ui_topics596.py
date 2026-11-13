"""5.9.6: the topic list uses wide screens and never breaks words inside the table."""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from checks import audit
from conftest import sign_in
from tests.fakes import ui_topics

topic_catalog = ui_topics.topic_catalog

# Number of rendered text lines of each node: distinct line boxes of its text, padding ignored.
LINES = """(nodes) => nodes.map((node) => {
  const range = document.createRange();
  range.selectNodeContents(node);
  const tops = new Set(Array.from(range.getClientRects()).filter((rect) => rect.width > 0)
    .map((rect) => Math.round(rect.top)));
  return tops.size;
})"""


@pytest.mark.parametrize("width", [1920, 1366, 1024, 800, 390])
@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_regression_topic_headers_and_edit_buttons_stay_whole(page, mailhelp, topic_catalog, width, scheme):
    """Regression 5.9.6: "Geltun/gsbere/ich", "Ausschlü/sse" and a three-line "Bear/beit/en"."""
    if page.device != "desktop":
        return
    page.emulate_media(color_scheme=scheme)
    page.set_viewport_size({"width": width, "height": 900})
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/themen")
    buttons = page.locator(".topic-action a.button")
    expect(buttons).to_have_count(48)
    assert set(buttons.evaluate_all(LINES)) == {1}
    if width > 800:
        for name in ("Thema", "Status", "Geltungsbereich", "Beschreibung"):
            assert page.locator("thead th", has_text=name).evaluate_all(LINES) == [1]
        main = page.locator("main").bounding_box()
        assert main["width"] <= 1320 + 1
        if width >= 1920:  # below, the sidebar leaves less room than 1320 px
            assert main["width"] >= 1300
        toolbar = page.locator(".topic-toolbar")
        new = toolbar.get_by_role("link", name="Neues Thema", exact=True)
        query = toolbar.get_by_label("Themen durchsuchen", exact=True)
        # One tool row: search field and "Neues Thema" share their line.
        assert abs(new.bounding_box()["y"] + new.bounding_box()["height"]
                   - query.bounding_box()["y"] - query.bounding_box()["height"]) < 12
    no_overflow = page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert no_overflow
    assert audit(page, f"topics596-{width}-{scheme}", width < 801) == []


def test_the_editor_pages_stay_narrow(page, mailhelp, topic_catalog):
    if page.device != "desktop":
        return
    page.set_viewport_size({"width": 1920, "height": 900})
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/themen/relevant/neu")
    assert page.locator("main form").first.bounding_box()["width"] <= 760 + 1
