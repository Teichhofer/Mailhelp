"""A reconciliation block on a card leads to the Vorschlagsabgleich, not to a text answer (5.0.3)."""
from mailhelp.domain.proposal import MATCHING_QUESTION, SOURCE_QUESTION
from tests.scenarios.web_scenario import mail_id, proposal, save_mail


def card(page, pid):
    start = page.index(f'id="v-{mail_id(9)}-{pid}"')
    return page[start:page.index("</article>", start)]


def test_a_blocked_card_offers_the_reconciliation_instead_of_an_answer_field(web):
    save_mail(web.store, 9, "Seminar <seminar@x.test>", "Einladung", [
        proposal(9, "blockiert", title="Mitarbeiterqualifikation prüfen",
                 open_questions=[MATCHING_QUESTION, SOURCE_QUESTION]),
        proposal(9, "frage", title="Zum Seminar anmelden", open_questions=[MATCHING_QUESTION, "Bis wann?"]),
    ])
    web.site.refresh_overview(force=True)
    page = web.browser.request("GET", "/").body.decode()
    blocked = card(page, "blockiert")
    link = f'href="/abgleich?mail={mail_id(9)}&amp;vorschlag=blockiert"'
    assert f'<a class="button primary" {link}>Im Vorschlagsabgleich entscheiden</a>' in blocked
    assert "<textarea" not in blocked and 'value="answer"' not in blocked
    assert "Verwerfen" in blocked and "Schon erledigt" in blocked
    # A further real question stays answerable; the block is not offered as the question.
    question = card(page, "frage")
    assert "Im Vorschlagsabgleich entscheiden" not in question
    assert "<textarea" in question and "Bis wann?" in question
    assert f">{MATCHING_QUESTION}</label>" not in question
