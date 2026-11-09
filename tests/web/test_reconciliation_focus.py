"""The card's reconciliation link shows only that proposal and its comparison candidates (5.0.5)."""
from mailhelp.domain.proposal import MATCHING_QUESTION, ProposalStatus
from mailhelp.domain.proposal_sources import ProposalReference
from mailhelp.web.reconciliation_pages import focus_link
from tests.scenarios.web_scenario import mail_id, proposal, save_mail


def prepared(web):
    """A blocked task remembering one candidate, and an unrelated open proposal."""
    candidate = proposal(40, "kandidat", title="Mitarbeiterqualifikation prüfen", description="Bisher",
                         evidence="Bitte bis Freitag prüfen")
    blocked = proposal(41, "neu", title="Mitarbeiterqualifikation prüfen", description="Neu",
                       evidence="Anmeldung zum Seminar", due="2026-11-17",
                       status=ProposalStatus.NEEDS_CLARIFICATION, open_questions=[MATCHING_QUESTION],
                       matching_candidates=[ProposalReference(mail_id=mail_id(40), proposal_id="kandidat")])
    other = proposal(42, "fremd", title="Rasen mähen", description="Garten")
    save_mail(web.store, 40, "seminar@example.test", "Seminar", [candidate])
    save_mail(web.store, 41, "seminar@example.test", "Einladung zum Seminar", [blocked])
    save_mail(web.store, 42, "garten@example.test", "Garten", [other])
    return candidate, blocked, other


def page(web, path):
    response = web.browser.request("GET", path)
    assert response.status == 200
    return response.body.decode()


def test_the_focused_view_shows_only_the_proposal_and_its_candidates(web):
    candidate, blocked, other = prepared(web)
    everything = page(web, "/abgleich")
    assert "Rasen mähen" in everything and "Mitarbeiterqualifikation prüfen" in everything
    focused = page(web, focus_link(blocked.source_mail_id, blocked.id))
    assert "Rasen mähen" not in focused
    assert f"/vorschlag/{mail_id(41)}/neu" in focused
    # 5.0.6: the proposal of the card is shown in full next to its candidate.
    this, other_side = focused.split('<div class="compare-side')[1:3]
    # 5.0.7: marked as the proposal in question, the candidate as a possible duplicate.
    assert this.startswith(' compare-this">') and other_side.startswith(' compare-other">')
    assert '<span class="compare-tag">Um diesen Vorschlag geht es</span>' in this
    assert f'href="/vorschlag/{mail_id(41)}/neu"' in this
    assert "Fällig: 17.11.2026" in this and "Neu" in this and "Anmeldung zum Seminar" in this
    assert "seminar@example.test · Einladung zum Seminar" in this and "Version 1 · " in this
    assert '<span class="compare-tag">Möglicherweise dasselbe</span>' in other_side
    assert f'href="/vorschlag/{mail_id(40)}/kandidat"' in other_side
    assert "Ohne Frist" in other_side and "Bitte bis Freitag prüfen" in other_side
    assert "seminar@example.test · Seminar" in other_side and "Ort" not in other_side
    # Only the blocked proposal's section, with both decisions for its candidate.
    assert focused.count('<section class="card">') == 1
    assert "Zusatz ausdrücklich zuordnen" in focused and "Als eigenen Vorschlag behalten" in focused
    assert '<a href="/abgleich">Alle Vorschläge im Abgleich anzeigen</a>' in focused
    assert web.writer.created == 0


def test_the_card_links_to_the_focused_view(web):
    _, blocked, _ = prepared(web)
    web.site.refresh_overview(force=True)
    overview = page(web, "/")
    assert f'href="/abgleich?mail={mail_id(41)}&amp;vorschlag=neu">Im Vorschlagsabgleich entscheiden' in overview


def test_an_unknown_or_settled_proposal_points_to_the_full_view(web):
    prepared(web)
    focused = page(web, focus_link(mail_id(41), "gibt-es-nicht"))
    assert "Dieser Vorschlag steht nicht mehr zum Abgleich an." in focused
    assert '<section class="card">' not in focused
    assert '<a href="/abgleich">Alle Vorschläge im Abgleich anzeigen</a>' in focused


def test_without_a_remaining_candidate_the_focused_view_says_so(web):
    prepared(web)
    focused = page(web, focus_link(mail_id(42), "fremd"))
    assert "Kein anderer Vorschlag steht mehr zum Vergleich an." in focused
    assert "Mitarbeiterqualifikation prüfen" not in focused
    # Without both parameters the full view stays as before.
    assert "Rasen mähen" in page(web, f"/abgleich?mail={mail_id(42)}")


def test_events_show_time_and_place_and_a_lost_mail_is_named(web):
    first = proposal(50, "erst", kind="event", title="Elternabend", location="Aula",
                     start="2026-11-20T19:00:00+01:00", end="2026-11-20T21:00:00+01:00")
    second = proposal(51, "zweit", kind="event", title="Elternabend", status=ProposalStatus.NEEDS_CLARIFICATION,
                      open_questions=[MATCHING_QUESTION],
                      matching_candidates=[ProposalReference(mail_id=mail_id(50), proposal_id="erst")])
    save_mail(web.store, 50, "schule@example.test", "Elternabend", [first])
    save_mail(web.store, 51, "schule@example.test", "Erinnerung", [second])
    web.store.delete(f"mail-{mail_id(51)}")
    focused = page(web, focus_link(mail_id(51), "zweit"))
    this, other_side = focused.split('<div class="compare-side')[1:3]
    assert "<dt>Zeit</dt><dd>Zeit nicht angegeben</dd>" in this
    assert "Herkunftsmail nicht mehr gespeichert" in this
    assert "📅 Termin" in other_side and "<dt>Ort</dt><dd>Aula</dd>" in other_side
    assert "20.11.2026" in other_side
