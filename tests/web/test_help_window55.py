"""5.5: the tidier help window (cost notice, short answers)."""
import re

from tests.fakes.shared_web_actions import web as web  # noqa: F401


def test_window55_cost_notice_is_folded_behind_one_word(web):
    page = web.browser.request("GET", "/einstellungen").body.decode()
    folded = re.search(r'<details class="help-cost-hint"><summary>Kostenpflichtig</summary>(.*?)</details>', page)
    assert folded is not None
    # The complete warning is still there, only collapsed; never open by default.
    assert "können Kosten verursachen" in folded.group(1)
    assert "Keine Passwörter oder Tokens eingeben" in folded.group(1)
    assert '<details class="help-cost-hint" open' not in page
    assert page.count("können Kosten verursachen") == 1
