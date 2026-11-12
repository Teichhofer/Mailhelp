import json
from dataclasses import replace

import pytest

from mailhelp.rule_learning.models import RuleAnalysis
from mailhelp.rule_learning.service import STATE
from mailhelp.web.rule_compare import shown
from mailhelp.web.rule_learning_site import RuleLearningSite
from tests.fakes.rule_learning import RuleHarness, proposal, record, topic
from tests.fakes.shared_web_actions import web as web
from tests.fakes.shared_web_auth import Browser


@pytest.mark.parametrize("key,value,expected", [
    ("enabled", True, "Ja"), ("enabled", False, "Nein"), ("mailboxes", None, "alle Postfächer"),
    ("mailboxes", [], "keine"), ("mailboxes", [1, 2], "Postfach 1, Postfach 2"), ("examples", [], "Keine"),
    ("examples", ["A", "B"], "A" + chr(10) + "B"), ("name", "Schule", "Schule")])
def test_previous_rule_values_are_readable_without_python_representations(key, value, expected):
    # 5.7.3: the shared comparison replaced value_text; values still never show as Python reprs.
    assert shown(key, value) == expected


@pytest.fixture
def page(web, tmp_path):
    harness = RuleHarness(tmp_path, web.store, web.dialog.review.web_authorizer)
    web.site.rule_learning.service = harness.service
    session = web.auth.sessions()[0]
    return web, harness, session


def form(page, action="analyze", **changes):
    web, harness, session = page
    state = harness.service.state("web:" + session.id)
    return {"csrf": web.auth.csrf_token(session.id), "key": "browser-key-" + str(state.version),
            "version": str(state.version), "action": action, "confirm": "yes", **changes}


def analyze(page, scope="all"):
    # 5.7.6: "all" re-uses decisions of an earlier analysis; "new" would find none left.
    web, harness, _session = page
    harness.log(record())
    fields = form(page, scope=scope)
    assert web.browser.request("POST", "/lernen/entscheidungen", fields).status == 303
    assert harness.service.tick()


def choice_form(page, **changes):
    return form(page, "apply", **{"selected-0": "yes", "id-0": "school", "name-0": "Von Hand",
        "description-0": "Manuell korrigiert", "examples-0": "Eigener Fall", "exclusions-0": "Kein Newsletter",
        "enabled-0": "true", **changes})


def test_routes_require_authentication_and_post_requires_csrf(page):
    web, harness, _session = page
    stranger = Browser(web.app)
    assert stranger.request("GET", "/lernen/entscheidungen").status == 303
    assert stranger.request("POST", "/lernen/entscheidungen", form(page)).status == 403
    assert web.browser.request("POST", "/lernen/entscheidungen", {**form(page), "csrf": "bad"}).status == 403
    assert harness.analyzer.calls == []


def test_service_unavailable_and_initial_page_have_no_model_side_effects(web):
    assert web.browser.request("GET", "/lernen/entscheidungen").status == 503
    assert web.browser.request("POST", "/lernen/entscheidungen", {
        "csrf": web.auth.csrf_token(web.auth.sessions()[0].id)}).status == 503


def test_review_has_old_new_edit_fields_and_safe_evidence(page):
    web, harness, _session = page
    assert "Entscheidungen analysieren" in web.browser.request("GET", "/lernen/entscheidungen").body.decode()
    harness.analyzer.result = RuleAnalysis(proposals=[proposal(rationale="<script>evil</script>"), proposal(
        action="create", category="irrelevant", topic_id="noise", proposed=topic(id="noise", name="Werbung"))])
    analyze(page)
    html = web.browser.request("GET", "/lernen/entscheidungen").body.decode()
    assert 'class="rule-diff"' in html and "Bisherige Regel" in html
    assert "Vorgeschlagene Regel" in html and "Neues Thema" in html and "geändert" in html
    assert "&lt;script&gt;evil" in html and "<script>evil" not in html
    assert "Synthetischer Elternbrief" in html and "secret-token" not in html
    fields = choice_form(page)
    assert web.browser.request("POST", "/lernen/entscheidungen", fields).status == 303
    assert web.browser.request("POST", "/lernen/entscheidungen", fields).status == 303
    assert len(harness.activated) == 1
    assert harness.activated[0][0].name == "Von Hand"


@pytest.mark.parametrize("changes,needle", [
    ({"yaml-0": "id: ["}, "YAML-Syntaxfehler"),
    ({"id-0": "Ungültige ID!"}, "id"),
    ({"enabled-0": "false"}, "aktiviert"),
    ({"examples-0": "one\n\ntwo"}, "leer"),
    ({"confirm": ""}, "bestätigt"),
    ({"enabled-0": "invalid"}, "invalid"),
])
def test_validation_errors_preserve_input_and_do_not_change_files(page, changes, needle):
    web, harness, _session = page
    analyze(page)
    before = harness.service.hashes()
    fields = choice_form(page, **changes)
    response = web.browser.request("POST", "/lernen/entscheidungen", fields)
    assert response.status == 422 and needle in response.body.decode()
    assert "Von Hand" in response.body.decode() and harness.service.hashes() == before
    assert harness.activated == []


def test_raw_yaml_fully_replaces_field_values_and_skip_is_respected(page):
    import yaml
    web, harness, _session = page
    analyze(page)
    fields = choice_form(page, **{"yaml-0": yaml.safe_dump(topic(name="Aus YAML").model_dump())})
    assert web.browser.request("POST", "/lernen/entscheidungen", fields).status == 303
    assert harness.activated[0][0].name == "Aus YAML"
    analyze(page)
    fields = form(page, "apply")
    response = web.browser.request("POST", "/lernen/entscheidungen", fields)
    assert response.status == 422 and "Mindestens" in response.body.decode()


def test_revision_and_session_failures_do_not_save_rule_files(page, monkeypatch):
    web, harness, session = page
    analyze(page)
    fields = choice_form(page)
    (harness.directory / "topics.yaml").write_text("topics: []\n", encoding="utf-8")
    before = harness.service.hashes()
    assert web.browser.request("POST", "/lernen/entscheidungen", fields).status == 409
    monkeypatch.setattr(harness.service, "check", lambda _: (_ for _ in ()).throw(PermissionError()))
    assert web.browser.request("POST", "/lernen/entscheidungen", fields).status == 403
    assert harness.service.hashes() == before


def test_io_errors_offer_recovery_with_no_duplicate_model_call(page, monkeypatch):
    from mailhelp.rule_learning import service
    web, harness, _session = page
    analyze(page)
    original = service.atomic_replace
    monkeypatch.setattr(service, "atomic_replace", lambda *_: (_ for _ in ()).throw(OSError()))
    response = web.browser.request("POST", "/lernen/entscheidungen", choice_form(page))
    assert response.status == 503 and "Übernahme abschließen" in response.body.decode()
    monkeypatch.setattr(service, "atomic_replace", original)
    assert web.browser.request("POST", "/lernen/entscheidungen", form(page, "resume")).status == 303
    assert len(harness.analyzer.calls) == 1


def test_malformed_submissions_and_foreign_job_bodies_are_safe(page):
    web, harness, _session = page
    response = web.browser.request("POST", "/lernen/entscheidungen", {**form(page), "version": "not-an-int"})
    assert response.status == 422 and harness.analyzer.calls == []
