"""5.7.6: the start form offers "only new" and "all" decisions; failures name their cause."""
import pytest

from mailhelp.processing.analysis import LlmTokenLimitExceeded
from mailhelp.rule_learning.models import RuleAnalysis
from tests.fakes.rule_learning import RuleHarness, proposal, record
from tests.fakes.shared_web_actions import web as web  # noqa: F401


@pytest.fixture
def page(web, tmp_path):
    harness = RuleHarness(tmp_path, web.store, web.dialog.review.web_authorizer)
    web.site.rule_learning.service = harness.service
    return web, harness, web.auth.sessions()[0]


def start(page, key, **fields):
    web, harness, session = page
    state = harness.service.state("web:" + session.id)
    return web.browser.request("POST", "/lernen/entscheidungen", {
        "csrf": web.auth.csrf_token(session.id), "key": key, "version": str(state.version),
        "action": "analyze", "confirm": "yes", **fields})


def test_the_form_offers_both_scopes_with_their_counts(page):
    web, harness, _session = page
    harness.log(record("decision-1"), record("decision-2"))
    html = web.browser.request("GET", "/lernen/entscheidungen").body.decode()
    assert "<legend>Welche Entscheidungen?</legend>" in html
    assert 'name="scope" value="new" checked> Nur neue Entscheidungen seit der letzten Analyse (2)' in html
    assert 'name="scope" value="all"> Alle bisherigen verwertbaren Entscheidungen (2)' in html
    assert "Höchstens 100" in html and "Höchstens 500" in html
    overview = web.browser.request("GET", "/lernen").body.decode()
    assert "2 neue verwertbare Entscheidungen seit der letzten Analyse, 2 verwertbare insgesamt." in overview


def test_all_reuses_analysed_decisions_and_new_explains_when_none_are_left(page):
    web, harness, session = page
    harness.log(record("decision-1"))
    assert start(page, "scope-key-1", scope="new").status == 303
    assert harness.service.tick()
    response = start(page, "scope-key-2", scope="new")
    assert response.status == 422 and "Alle bisherigen verwertbaren Entscheidungen" in response.body.decode()
    # The rejected form keeps the chosen scope.
    assert 'name="scope" value="new" checked' in response.body.decode()
    assert start(page, "scope-key-3", scope="other").status == 422
    assert start(page, "scope-key-4", scope="all").status == 303
    assert harness.service.state("web:" + session.id).scope == "all"
    assert harness.service.tick()
    html = web.browser.request("GET", "/lernen/entscheidungen").body.decode()
    assert "aus 1 Entscheidungen (alle bisherigen); " in html


def test_the_summary_names_decisions_left_out_by_the_payload_limit(page):
    web, harness, _session = page
    harness.log(*[record(f"decision-{index}", "edit", proposal={"changes": {"title": "Neu"}},
                         mail={"headers": {"subject": "S"}, "content": {"text": "x" * 3000}}) for index in range(3)])
    harness.analyzer.result = RuleAnalysis(proposals=[proposal(evidence=["decision-2"])])
    harness.limit = 2000
    assert start(page, "scope-key-5", scope="all").status == 303
    assert harness.service.tick()
    html = web.browser.request("GET", "/lernen/entscheidungen").body.decode()
    assert "(alle bisherigen; 2 ältere wegen der Nutzlastgrenze nicht übertragen)" in html


def test_a_failed_analysis_shows_its_cause_on_the_page(page):
    web, harness, _session = page
    harness.log(record())
    assert start(page, "scope-key-6").status == 303
    harness.analyzer.error = LlmTokenLimitExceeded("decision_rule_learning", "output_token_limit")
    assert harness.service.tick()
    html = web.browser.request("GET", "/lernen/entscheidungen").body.decode()
    assert "Analyse fehlgeschlagen" in html and "am Ausgabelimit abgeschnitten" in html
