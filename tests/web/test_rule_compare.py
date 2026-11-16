"""5.7.3 (S4): the shared before/after comparison and the tidier rule review."""
import pytest
import yaml

from mailhelp.rule_learning.models import RuleAnalysis
from mailhelp.web.rule_compare import compare, lines
from tests.fakes.rule_learning import RuleHarness, proposal, record, topic
from tests.fakes.shared_web_actions import web as web  # noqa: F401

BEFORE = {"id": "school", "name": "Schule", "description": "Alt", "examples": ["Bleibt", "Weg"],
          "exclusions": [], "enabled": True, "mailboxes": None}


def test_changed_fields_are_open_lists_are_marked_line_by_line_and_the_rest_is_folded():
    after = {**BEFORE, "description": "Neu <b>", "examples": ["Bleibt", "Dazu"]}
    html = compare(BEFORE, after)
    assert "Geänderte Felder (2)" in html and html.count('<span class="badge warn">geändert</span>') == 2
    assert "<li>Bleibt</li>" in html and '<span class="diff-mark">+ neu:</span> Dazu' in html
    assert '<span class="diff-mark">− entfernt:</span> <del>Weg</del>' in html
    assert "Neu &lt;b&gt;" in html and "<b>" not in html
    folded = html.split('<details class="compare-unchanged">')[1]
    assert "Unveränderte Felder anzeigen (4)" in folded
    for label in ("Name", "Ausschlüsse", "Aktiv", "Geltungsbereich"):
        assert f"<dt>{label} " in folded
    assert "alle Postfächer" in folded and "unverändert" in folded


def test_a_new_topic_shows_all_fields_as_new_and_an_unchanged_one_says_so():
    html = compare(None, {**BEFORE, "mailboxes": [2]})
    assert "Neues Thema: alle Felder" in html and html.count('<span class="badge accent">neu</span>') == 6
    assert '<td data-label="Bisher">—</td>' in html and "Postfach 2" in html and "compare-unchanged" not in html
    same = compare(BEFORE, dict(BEFORE))
    assert "Keine Feldänderung" in same and "<table" not in same and "Unveränderte Felder anzeigen (6)" in same
    assert lines([], []) == '<ul class="line-diff"><li>Keine</li></ul>'


@pytest.fixture
def review(web, tmp_path):
    harness = RuleHarness(tmp_path, web.store, web.dialog.review.web_authorizer)
    web.site.rule_learning.service = harness.service
    session = web.auth.sessions()[0]
    (tmp_path / "topics.yaml").write_text(yaml.safe_dump({"topics": [
        topic().model_dump(), topic(id="club", name="Verein").model_dump()]}), encoding="utf-8")
    harness.log(record(), record("decision-2", "already_done", recorded_at="2026-11-10T08:00:00Z",
                                 mail={"headers": {}, "content": {"text": ""}}),
                record("decision-3", "edit", proposal={"changes": {"title": "Elternabend"}}, answer="Ja, bitte"))
    harness.analyzer.result = RuleAnalysis(proposals=[
        proposal(evidence=["decision-1", "decision-2", "decision-3"]),
        proposal(action="create", category="irrelevant", topic_id="noise", proposed=topic(id="noise", name="Werbung")),
        proposal(action="disable", topic_id="club", proposed=topic(id="club", name="Verein", enabled=False))])
    state = harness.service.state("web:" + session.id)
    harness.service.change("web:" + session.id, state.version, "analyze-573", "analyze", {"confirm": True})
    assert harness.service.tick()
    return web, harness, session


def test_the_review_starts_with_a_summary_and_jump_links(review):
    web, _harness, _session = review
    html = web.browser.request("GET", "/lernen/entscheidungen").body.decode()
    assert "3 Vorschläge: 1 Änderung, 1 neues Thema, 1 Deaktivierung · aus 3 Entscheidungen" in html
    for index in (1, 2, 3):
        assert f'href="#vorschlag-{index}"' in html and f'id="vorschlag-{index}"' in html
    assert '<span class="badge accent">Neues Thema</span>' in html and "Deaktivierung</span>" in html
    # The selection is in the head of every card; the action bar counts it (also without script).
    # 6.0.4: accept, reject or open per proposal (three choices each).
    assert html.count("data-rule-decision") == 9 and "0 zur Übernahme ausgewählt · 0 zum Verwerfen markiert." in html
    assert '<div class="confirm-bar">' in html and "/static/learning.js" in html
    assert "Bisherige Regel und Vorschlag" in html and "Unveränderte Felder anzeigen" in html


def test_evidence_is_a_short_list_with_the_excerpt_on_demand(review):
    web, _harness, _session = review
    html = web.browser.request("GET", "/lernen/entscheidungen").body.decode()
    evidence = html.split('<details class="rule-evidence">')[1].split("</ul></details>")[0]
    assert "Entscheidungsbelege (3)" in evidence
    assert "<strong>Synthetischer Elternbrief</strong> · Vorschlag abgelehnt" in evidence
    assert "<strong>Ohne Betreff</strong> · Bereits erledigt (relevant) · 2026-11-10" in evidence
    assert "Von Hand korrigiert" in evidence and "<dt>title</dt><dd>Elternabend</dd>" in evidence
    assert "Antwort: Ja, bitte" in evidence and "Kein Textauszug." in evidence
    assert "secret-token" not in evidence and "<summary>Auszug anzeigen</summary>" in evidence


def test_a_rejected_form_keeps_the_selection_count(review):
    web, harness, session = review
    state = harness.service.state("web:" + session.id)
    form = {"csrf": web.auth.csrf_token(session.id), "key": "k" * 32, "version": str(state.version),
            "action": "preview", "confirm": "yes", "selected-0": "yes", "selected-2": "yes",
            "id-0": "school", "name-0": "", "description-0": "x", "examples-0": "", "exclusions-0": "",
            "enabled-0": "true"}
    response = web.browser.request("POST", "/lernen/entscheidungen", form)
    assert response.status == 422 and "2 zur Übernahme ausgewählt · 0 zum Verwerfen markiert." in response.body.decode()
