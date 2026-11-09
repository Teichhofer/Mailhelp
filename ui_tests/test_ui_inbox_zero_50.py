"""Planung 5.0, step 21.6 (5.0.10): inbox zero tiles and a motion-aware entrance."""
from playwright.sync_api import expect

from checks import audit
from conftest import sign_in
from mailhelp.models import MailState, Proposal
from tests.scenarios.web_scenario import mail_id


def decide_everything(store):
    for number, pid in ((1, "elternabend"), (1, "formular"), (2, "zahnarzt"), (3, "fest"), (4, "boese")):
        name = f"proposal-{mail_id(number)}-{pid}"
        store.save(name, {**store.load_model(name, Proposal).model_dump(mode="json"), "status": "rejected"})
    state = store.load_model(f"mail-{mail_id(7)}", MailState)
    state.awaiting_relevance, state.relevance_dialog = False, None
    store.save(f"mail-{mail_id(7)}", state.model_dump(mode="json"))


def test_tiles_use_tabular_figures_and_respect_reduced_motion(page, mailhelp):
    decide_everything(mailhelp.store)
    sign_in(page, mailhelp)
    tiles = page.locator(".inbox-zero .kpi")
    expect(tiles).to_have_count(4)
    expect(tiles.nth(0)).to_contain_text("Termine")
    number = tiles.nth(0).locator("dd")
    assert number.evaluate("node => getComputedStyle(node).fontVariantNumeric") == "tabular-nums"
    card = page.locator(".inbox-zero")
    assert card.evaluate("node => getComputedStyle(node).animationName") == "inbox-zero-in"
    assert audit(page, "inbox-zero-50-" + page.device, page.mobile) == []
    page.emulate_media(reduced_motion="reduce")
    assert card.evaluate("node => getComputedStyle(node).animationName") == "none"
    assert page.errors == []
