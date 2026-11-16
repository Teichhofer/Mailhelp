"""6.2.7: dense lists – at least twelve entries per 1920 × 1080 screen, short rows on phones."""
from __future__ import annotations

from playwright.sync_api import expect

from checks import audit
from conftest import sign_in

HEIGHTS = "() => Array.from(document.querySelectorAll('.row-item')).map((row) => row.getBoundingClientRect().height)"


def test_rows627_lists_are_dense_and_readable_on_every_screen(page, mailhelp):
    if page.device == "desktop":
        page.set_viewport_size({"width": 1920, "height": 1080})
    sign_in(page, mailhelp)
    for path in ("/mails", "/verlauf", "/abgleich"):
        page.goto(mailhelp.url + path)
        expect(page.locator(".row-item").first).to_be_visible()
        heights = page.evaluate(HEIGHTS)
        if page.device == "desktop":
            # 1080 px minus head and tool row leave about 860 px: twelve rows need at most 72 px each.
            assert max(heights) <= 72, (path, heights)
        else:
            # Title, sender/time and badges; long badges may wrap once more – never a tall card (was 600 px+).
            assert max(heights) <= 150, (path, heights)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert audit(page, "rows627" + path.replace("/", "-") + "-" + page.device, page.mobile) == []
    assert page.errors == []
