"""Every status counter is a usable native link, including without JavaScript."""
import re

import pytest
from playwright.sync_api import expect

from checks import audit
from conftest import sign_in


@pytest.mark.parametrize("javascript", [True, False])
def test_status581_links_open_the_correct_filtered_records(page, mailhelp, javascript):
    if not javascript:
        page.cdp.send("Emulation.setScriptExecutionDisabled", {"value": True})
    sign_in(page, mailhelp)
    for label, path, heading in (
        ("Offene Vorschläge", "/status/vorschlaege", "Offene Vorschläge"),
        ("Relevanzfragen", "/status/relevanzfragen", "Relevanzfragen"),
        ("Mails mit Fehler", "/mails?state=failed", "Mails"),
        ("Wartende Web-Aktionen", "/status/web-aktionen", "Wartende Web-Aktionen"),
    ):
        page.goto(mailhelp.url + "/status")
        tile = page.get_by_role("navigation", name="Statusübersichten").get_by_role(
            "link", name=re.compile(re.escape(label) + "$"))
        expect(tile).to_have_attribute("href", path)
        box = tile.bounding_box()
        assert box["height"] >= 44 and box["width"] >= 44
        if javascript:
            assert audit(page, "status581-tiles-" + page.device, page.mobile) == []
        tile.focus()
        tile.press("Enter")
        expect(page.page).to_have_url(mailhelp.url + path)
        expect(page.get_by_role("heading", level=1)).to_have_text(heading)
        if javascript:
            assert audit(page, "status581-" + path.split("/")[-1].split("?")[0] + "-" + page.device,
                         page.mobile) == []
        else:
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert mailhelp.writer.created == []
