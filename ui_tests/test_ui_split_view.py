"""Planung 5.0, step 21.4 (5.0.8): the split view keeps the decision row in reach."""
from playwright.sync_api import expect

from checks import audit
from conftest import sign_in
from pages import MASTER, PANE
from tests.scenarios.web_scenario import mail_id, proposal, save_mail

LONG = " ".join(f"Absatz {number}: Die Unterlagen liegen im Sekretariat bereit." for number in range(60))


def test_the_decision_row_stays_visible_while_the_detail_scrolls(page, mailhelp):
    if page.device != "desktop":
        return
    save_mail(mailhelp.store, 70, "Verein <verein@x.test>", "Unterlagen", [
        proposal(70, "lang", title="Unterlagen abholen", description=LONG, evidence=LONG[:1900])])
    page.set_viewport_size({"width": 1280, "height": 560})
    sign_in(page, mailhelp)
    page.locator(f"{MASTER} #v-{mail_id(70)}-lang").click(position={"x": 12, "y": 12})
    card = page.locator(f"{PANE} #detail-v-{mail_id(70)}-lang")
    expect(card).to_be_visible()
    card.locator("details").first.evaluate("node => node.open = true")
    bar = card.locator(".decision-bar")
    expect(bar.get_by_role("button", name="Verwerfen")).to_be_visible()
    # The card is taller than the window; its decision row sits at the bottom edge anyway.
    assert card.bounding_box()["height"] > 560
    page.mouse.wheel(0, 200)
    box = bar.bounding_box()
    assert 0 <= box["y"] and box["y"] + box["height"] <= 560 + 1
    assert audit(page, "split-view-50", False) == []


def test_the_list_shows_kind_and_status_of_each_item(page, mailhelp):
    if page.device != "desktop":
        return
    sign_in(page, mailhelp)
    item = page.locator(f"{MASTER} article.card.kind-event").first
    expect(item.locator(".kind-label")).to_be_visible()
    expect(item.locator(".labels .badge").first).to_be_visible()
    for hidden in ("blockquote", ".decision-bar"):
        expect(item.locator(hidden)).to_have_count(0) if item.locator(hidden).count() == 0 else \
            expect(item.locator(hidden).first).to_be_hidden()
