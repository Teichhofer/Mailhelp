"""A blocked card leads to the Vorschlagsabgleich in an actual browser (5.0.3)."""
from playwright.sync_api import expect

from checks import audit
from conftest import sign_in
from mailhelp.domain.proposal import MATCHING_QUESTION, SOURCE_QUESTION
from tests.scenarios.web_scenario import mail_id, proposal, save_mail


def test_blocked_task_offers_the_reconciliation_and_no_answer_field(page, mailhelp):
    save_mail(mailhelp.store, 9, "Seminar <seminar@x.test>", "Einladung", [
        proposal(9, "blockiert", title="Mitarbeiterqualifikation prüfen",
                 open_questions=[MATCHING_QUESTION, SOURCE_QUESTION])])
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
    assert audit(page, "reconciliation-focus-" + page.device, page.mobile) == []
    assert mailhelp.writer.created == []
