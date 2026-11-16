"""The audit's observable failures, reproduced before the 5.8 fixes."""
from urllib.parse import urlencode

import yaml

from tests.fakes.learning_harness import learning as learning
from tests.fakes.rule_learning_web import analyze, choice_form
from tests.fakes.rule_learning_web import page as page
from tests.fakes.topic_editor_web import topics as topics
from tests.fakes.topic_forms import preview


def test_estimate_preserves_the_visible_selection(learning):
    response = learning.browser.request("GET", "/lernen/postfach?" + urlencode({
        "mailbox": 1, "folders": "Archive", "count": 7, "price": 0.75, "budget": 9}))
    html = response.body.decode()
    assert 'name="count"' in html and 'value="7"' in html
    assert 'value="0.75"' in html and 'value="9"' in html
    assert learning.client.calls == []


def test_edited_rule_requires_an_effective_preview_before_writing(page):
    web, harness, _ = page
    analyze(page)
    before = harness.service.hashes()
    fields = choice_form(page, **{"confirm": "", "exclusions-0": "Manueller Ausschluss"})
    fields["action"] = "preview"
    response = web.browser.request("POST", "/lernen/entscheidungen", fields)
    assert response.status == 200
    assert "Manueller Ausschluss" in response.body.decode()
    assert 'name="preview_key"' in response.body.decode()
    assert harness.service.hashes() == before and harness.activated == []


def test_topic_errors_are_german_and_associated_with_the_field(topics):
    web, _ = topics
    response = preview(web, "/themen/relevant/school", name="Schule", description="")
    html = response.body.decode()
    assert response.status == 422
    assert 'aria-describedby="topic-description-help topic-description-error"' in html
    assert 'id="form-errors"' in html and 'autofocus' in html
    assert "mindestens 1 Zeichen" in html and "String should" not in html


def test_learning_overview_distinguishes_no_run_from_unknown_old_date(learning):
    html = learning.browser.request("GET", "/lernen").body.decode()
    assert "Noch kein Lernlauf gestartet" in html
    assert "Datum früherer Läufe" not in html


def test_last_active_topic_error_is_associated_with_its_checkbox(topics):
    web, path = topics
    document = yaml.safe_load((path / "topics.yaml").read_text(encoding="utf-8"))
    document["topics"] = document["topics"][:1]
    (path / "topics.yaml").write_text(yaml.safe_dump(document), encoding="utf-8")
    response = preview(web, "/themen/relevant/school", name="Schule", description="Schulpost", enabled="")
    html = response.body.decode()
    assert response.status == 422
    assert 'aria-describedby="topic-enabled-error"' in html
    assert 'id="topic-enabled-error"' in html
