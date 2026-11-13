"""6.0.4: rule proposals can be rejected; rejections are stored with the confirmation and can be lifted."""
import re

import pytest

from mailhelp.rule_learning.models import RuleAnalysis
from mailhelp.rule_learning.service import HISTORY, DecisionRuleLearning
from mailhelp.rule_learning.validation import RuleConflict
from mailhelp.web.rule_preview import confirmed, preview_name
from tests.fakes.rule_learning import proposal, topic
from tests.fakes.rule_learning_web import analyze, form
from tests.fakes.rule_learning_web import page as page
from tests.fakes.shared_web_actions import web as web  # noqa: F401  (fixture)
from tests.fakes.topic_forms import hidden

URL = "/lernen/entscheidungen"


def two_proposals(page):
    _web, harness, _session = page
    harness.analyzer.result = RuleAnalysis(proposals=[proposal(), proposal(
        action="create", category="irrelevant", topic_id="noise", proposed=topic(id="noise", name="Werbung"))])
    analyze(page)


def preview(page, **decisions):
    web, _, _ = page
    fields = form(page, "preview", **decisions)
    fields.pop("confirm")
    return web.browser.request("POST", URL, fields)


def confirm(page, response):
    web, _, _ = page
    return web.browser.request("POST", URL, {**hidden(response.body.decode(), URL), "confirm": "yes"})


def history(page):
    return page[1].service.history()


def test_regression_a_rejected_proposal_is_stored_and_no_rule_file_changes(page):
    """Regression 6.0: there was no way to reject a proposal; unticked ones simply came back."""
    web, harness, _session = page
    two_proposals(page)
    html = web.browser.request("GET", URL).body.decode()
    assert html.count('name="decision-0"') == 3 and 'value="open" data-rule-decision checked' in html
    before = harness.service.hashes()
    shown = preview(page, **{"decision-0": "reject", "decision-1": "open"})
    assert shown.status == 200 and "Wird verworfen und nicht wieder vorgeschlagen" in shown.body.decode()
    assert history(page).rejected == []  # the preview stores nothing
    assert confirm(page, shown).status == 303
    stored = history(page)
    assert [item.topic_id for item in stored.rejected] == ["school"] and stored.rejected_version == 1
    assert harness.service.hashes() == before and harness.activated == []
    state = harness.service.state("web:" + page[2].id)
    assert state.status == "done" and "1 Vorschlag verworfen" in state.message
    # The same confirmation again (double click, retried request) has no second effect.
    assert confirm(page, shown).status in {303, 409}
    assert history(page).rejected_version == 1


def test_accepting_one_and_rejecting_another_in_one_confirmation(page):
    web, harness, _session = page
    two_proposals(page)
    fields = {"decision-0": "accept", "decision-1": "reject", "id-0": "school", "name-0": "Schule",
              "description-0": "Verbindliche Schulaufgaben", "examples-0": "", "exclusions-0": "Unverbindliche Werbung",
              "enabled-0": "true", "mailboxes-0": "null"}
    shown = preview(page, **fields)
    body = shown.body.decode()
    assert "Unverbindliche Werbung" in body and "<strong>Werbung</strong> · Neues Thema" in body
    assert confirm(page, shown).status == 303
    assert [item.topic_id for item in history(page).rejected] == ["noise"]
    assert len(harness.activated) == 1


def test_nothing_chosen_or_both_chosen_is_rejected_without_effect(page):
    web, harness, session = page
    two_proposals(page)
    response = preview(page, **{"decision-0": "open", "decision-1": "open"})
    assert response.status == 422 and "Mindestens einen Vorschlag übernehmen oder verwerfen" in response.body.decode()
    state = harness.service.state("web:" + session.id)
    with pytest.raises(ValueError, match="Ungültige oder doppelte"):
        harness.service.rejections(state, [0, 0], [])
    with pytest.raises(ValueError, match="Ungültige oder doppelte"):
        harness.service.rejections(state, [0], [{"index": 0}])
    with pytest.raises(ValueError, match="Ungültige oder doppelte"):
        harness.service.rejections(state, [7], [])
    assert history(page).rejected == []


def test_a_preview_saved_before_6_0_has_no_rejections(page):
    web, harness, session = page
    actor = "web:" + session.id
    harness.store.save(preview_name(actor), {"version": 3, "key": "k" * 32, "choices": [], "values": {}})
    assert confirmed(harness.service, actor, {"preview_key": "k" * 32, "key": "k" * 32, "version": "3"}) == ([], [])


def readmit_form(page):
    web, _, _ = page
    html = web.browser.request("GET", URL).body.decode()
    return html, hidden(html[html.index('id="verworfen"'):], URL)


def test_a_rejection_can_be_lifted_once_with_version_session_and_csrf(page):
    web, harness, session = page
    two_proposals(page)
    confirm(page, preview(page, **{"decision-0": "reject", "decision-1": "reject"}))
    assert "2 Vorschläge verworfen; sie werden" in harness.service.state("web:" + session.id).message
    html, fields = readmit_form(page)
    assert "Zuvor verworfene Vorschläge anzeigen (2)" in html and "+ Ausschluss: unverbindliche werbung" in html
    assert fields["action"] == "readmit" and fields["rejected_version"] == "1"
    # Without CSRF or with an outdated version nothing changes.
    assert web.browser.request("POST", URL, {**fields, "csrf": "falsch"}).status == 403
    outdated = web.browser.request("POST", URL, {**fields, "rejected_version": "0"})
    assert outdated.status == 409 and "inzwischen geändert" in outdated.body.decode()
    assert web.browser.request("POST", URL, fields).status == 303
    assert len(history(page).rejected) == 1 and history(page).rejected_version == 2
    # The same request again is answered from its receipt; another fingerprint with that key is a conflict.
    assert web.browser.request("POST", URL, fields).status == 303 and history(page).rejected_version == 2
    other = history(page).rejected[0].fingerprint
    assert web.browser.request("POST", URL, {**fields, "fingerprint": other}).status == 409
    gone = web.browser.request("POST", URL, {**fields, "key": "neuer-schluessel-1", "rejected_version": "2",
                                             "fingerprint": "a" * 64})
    assert gone.status == 409 and "nicht mehr gesperrt" in gone.body.decode()
    assert web.browser.request("POST", URL, {**fields, "key": "x"}).status == 422


def test_an_expired_session_cannot_lift_a_rejection_and_a_restart_keeps_the_list(page):
    web, harness, session = page
    two_proposals(page)
    confirm(page, preview(page, **{"decision-0": "reject"}))
    _html, fields = readmit_form(page)
    calls = []

    def expire_on_second_check(actor):
        calls.append(actor)
        return len(calls) < 2
    harness.service.active = expire_on_second_check
    with pytest.raises(PermissionError):
        harness.service.readmit("web:" + session.id, 1, fields["key"], fields["fingerprint"])
    assert len(history(page).rejected) == 1
    restarted = DecisionRuleLearning(harness.configuration, lambda: harness.analyzer, lambda actor: True)
    assert restarted.history().rejected == history(page).rejected
    assert harness.store.load(HISTORY)["rejected_version"] == 1


def test_the_rejected_list_is_escaped_and_names_every_kind_of_change(page):
    web, harness, _session = page
    harness.analyzer.result = RuleAnalysis(proposals=[proposal(proposed=topic(
        name="<b>Schule</b>", description="Neu", enabled=False, examples=["Fest"]).model_dump(), action="disable")])
    analyze(page)
    confirm(page, preview(page, **{"decision-0": "reject"}))
    html = web.browser.request("GET", URL).body.decode()
    assert "&lt;b&gt;Schule&lt;/b&gt;" in html and "<b>Schule</b>" not in html
    assert "Deaktivierung · relevant" in html and "Aktiv: Nein" in html and "Beschreibung: neu" in html
    assert "+ Beispiel: fest" in html and re.search(r"verworfen am \d\d\.\d\d\.\d{4}", html)
    with pytest.raises(RuleConflict):
        harness.service.readmit("web:" + page[2].id, 9, "schluessel-12", history(page).rejected[0].fingerprint)
