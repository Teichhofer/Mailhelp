"""The learning overview is read-only; stale forms never re-authorize an action."""
import json
import re

from mailhelp.rule_learning.models import RuleHistory
from mailhelp.rule_learning.service import HISTORY
from mailhelp.web.learning_overview import UPDATED, run_date
from tests.fakes.learning_harness import learning
from tests.fakes.rule_learning import RuleHarness, record
from tests.fakes.shared_web_actions import web as web
from tests.fakes.shared_web_auth import Browser


def attach(h):
    rules = RuleHarness(h.directory, h.store, h.jobs.active)
    h.site.rule_learning.service = rules.service
    return rules


def test_unavailable_cards_are_authenticated_read_only_and_offer_both_paths(web):
    assert Browser(web.app).request("GET", "/lernen").status == 303
    response = web.browser.request("GET", "/lernen")
    html = response.body.decode()
    assert response.status == 200 and "Aus dem Postfach lernen öffnen" in html
    assert "/lernen/entscheidungen" in html and "derzeit nicht verfügbar" in html
    cards = re.findall(r'<section class="card stack">(.*?)</section>', html, re.S)
    assert len(cards) == 2 and all('class="help-cost-hint"' in card for card in cards)
    assert "Hilfschat öffnen" in html and 'href="/lernen" aria-current="page"' in html


def test_overview_reports_progress_dates_counts_and_missing_prompt_without_calls(learning):
    h = learning
    rules = attach(h)
    rules.log(record())
    html = h.browser.request("GET", "/lernen").body.decode()
    assert "1 neue verwertbare Entscheidungen" in html and "Datum früherer Läufe" in html
    h.change("start", h.selection)
    assert h.jobs.state().started_at > 0
    html = h.browser.request("GET", "/lernen").body.decode()
    assert "Läuft: 0 Mails" in html and "von 2" in html and "Letzter Lauf:" in html
    assert rules.analyzer.calls == [] and h.client.calls == []
    rules.analyzer.prompts.prompts.clear()
    assert "fehlt decision_rule_learning" in h.browser.request("GET", "/lernen").body.decode()
    assert run_date(0, "UTC") == "01.01.1970, 00:00"


def test_analyzed_decision_metadata_survives_expiry_and_does_not_expose_foreign_evidence(learning):
    h = learning
    rules = attach(h)
    actor = h.actor
    rules.log(record())
    rules.service.change(actor, 0, "analyze-1", "analyze", {"confirm": True})
    rules.service.tick()
    html = h.browser.request("GET", "/lernen").body.decode()
    assert "Prüfentwurf mit 1 Vorschlägen" in html and "0 neue verwertbare" in html
    assert "Elternbrief" not in html and "secret-token" not in html
    foreign = rules.service.overview("web:other")
    assert foreign["proposals"] == 0 and not foreign["owned"]
    alternate = h.auth.issue_code()
    token = h.auth.redeem("other-browser", alternate, "Anderes Gerät")
    from mailhelp.web.login_site import SESSION_COOKIE
    other = Browser(h.web, host="localhost:8765")
    other.cookies[SESSION_COOKIE] = token
    assert "Prüfentwurf in einer anderen Sitzung" in other.request("GET", "/lernen").body.decode()
    rules.log(record(), record(identity="new"))
    assert rules.service.overview(actor)["new_decisions"] == 1
    rules.now += 86401
    assert rules.service.state().status == "empty"
    assert rules.service.history().decision_ids == ["decision-1"]
    assert rules.service.overview(actor)["new_decisions"] == 1
    h.store.save(HISTORY, {"corrupt": True})
    assert rules.service.history() == RuleHistory()


def test_old_forms_show_a_renewed_confirmation_without_executing(learning):
    h = learning
    rules = attach(h)
    rules.log(record())
    form = {"csrf": h.auth.csrf_token(h.initial.session.id), "version": "0", "key": "legacy-key",
            "action": "start", "selection": json.dumps(h.selection), "confirm": "yes"}
    assert h.browser.request("POST", "/lernen", form).status == 409
    assert h.jobs.state().status == "empty"
    result = h.browser.request("GET", "/themen/lernen")
    assert result.status == 308 and result.headers["Location"] == "/lernen/entscheidungen"
    result = h.browser.request("POST", "/themen/lernen", form | {"action": "analyze"})
    assert result.status == 409 and UPDATED in result.body.decode()
    assert rules.analyzer.calls == [] and rules.service.state().status == "empty"
    for url in ("/lernen", "/lernen/postfach", "/lernen/entscheidungen"):
        body = h.browser.request("GET", url).body.decode()
        assert 'href="/lernen" aria-current="page"' in body and "Hilfschat öffnen" in body
