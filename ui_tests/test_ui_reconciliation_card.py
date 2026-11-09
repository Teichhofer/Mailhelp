"""A blocked card leads to the Vorschlagsabgleich in an actual browser (5.0.3)."""
from playwright.sync_api import expect

from checks import audit
from conftest import sign_in
from mailhelp.domain.proposal import MATCHING_QUESTION, SOURCE_QUESTION
from mailhelp.domain.proposal_sources import ProposalReference
from tests.scenarios.web_scenario import mail_id, proposal, save_mail


def test_blocked_task_offers_the_reconciliation_and_no_answer_field(page, mailhelp):
    save_mail(mailhelp.store, 8, "Seminar <seminar@x.test>", "Erinnerung", [
        proposal(8, "frueher", title="Mitarbeiterqualifikation prüfen", description="Erste Mail")])
    save_mail(mailhelp.store, 9, "Seminar <seminar@x.test>", "Einladung", [
        proposal(9, "blockiert", title="Mitarbeiterqualifikation prüfen", description="Zweite Mail",
                 open_questions=[MATCHING_QUESTION, SOURCE_QUESTION],
                 matching_candidates=[ProposalReference(mail_id=mail_id(8), proposal_id="frueher")])])
    sign_in(page, mailhelp)
    page.goto(f"{mailhelp.url}/vorschlag/{mail_id(9)}/blockiert")
    card = page.locator(f"#v-{mail_id(9)}-blockiert")
    expect(card.get_by_role("link", name="Im Vorschlagsabgleich entscheiden")).to_be_visible()
    expect(card.locator("textarea")).to_have_count(0)
    assert audit(page, "reconciliation-card-" + page.device, page.mobile) == []
    card.get_by_role("link", name="Im Vorschlagsabgleich entscheiden").click()
    # 5.0.5: the reconciliation opens focused on this proposal.
    page.wait_for_url(f"{mailhelp.url}/abgleich?mail={mail_id(9)}&vorschlag=blockiert")
    expect(page.get_by_role("link", name="Alle Vorschläge im Abgleich anzeigen")).to_be_visible()
    # 5.0.6: the proposal of the card next to its candidate, side by side on wide screens.
    sides = page.locator(".compare-side")
    expect(sides).to_have_count(2)
    expect(sides.nth(0)).to_contain_text("Um diesen Vorschlag geht es")
    expect(sides.nth(0)).to_contain_text("Zweite Mail")
    expect(sides.nth(1)).to_contain_text("Möglicherweise dasselbe")
    # 5.0.7: the proposal in question is framed in the accent colour, the candidate is not.
    frame = sides.nth(0).evaluate("node => getComputedStyle(node).borderTopWidth")
    other_frame = sides.nth(1).evaluate("node => getComputedStyle(node).borderTopStyle")
    assert frame == "3px" and other_frame == "dashed"
    expect(sides.nth(1)).to_contain_text("Erste Mail")
    first, second = sides.nth(0).bounding_box(), sides.nth(1).bounding_box()
    assert (first["y"] == second["y"]) == (page.viewport_size["width"] >= 720)
    assert audit(page, "reconciliation-focus-" + page.device, page.mobile) == []
    assert mailhelp.writer.created == []
