"""5.8: effective snapshots, preparation without side effects, accessible errors."""
import json
from urllib.parse import urlencode

import pytest
import yaml

from mailhelp.rule_learning.models import RuleAnalysis
from mailhelp.storage import CorruptState
from mailhelp.web.rule_learning_site import RuleLearningSite
from mailhelp.web.rule_preview import preview_name
from mailhelp.web.settings_pages import settings_confirmation
from tests.fakes.learning_harness import learning as learning
from tests.fakes.rule_learning import proposal, topic
from tests.fakes.rule_learning_web import analyze, choice_form
from tests.fakes.rule_learning_web import page as page
from tests.fakes.shared_web_auth import Browser
from tests.fakes.topic_editor_web import topics as topics
from tests.fakes.topic_forms import hidden, preview


def snapshot(page, **changes):
    web, _, _ = page
    fields = {**choice_form(page, **changes), "action": "preview"}
    response = web.browser.request("POST", "/lernen/entscheidungen", fields)
    assert response.status == 200
    return response, {**hidden(response.body.decode(), "/lernen/entscheidungen"), "confirm": "yes"}


def test_confirmation_uses_only_the_previewed_yaml_even_after_a_restart(page):
    web, harness, _ = page
    analyze(page)
    topic = harness.service.state().proposals[0].proposed.model_dump(mode="json")
    topic["name"] = "<Geprüfter YAML-Stand>"
    response, confirmation = snapshot(page, **{"yaml-0": yaml.safe_dump(topic)})
    assert "&lt;Geprüfter YAML-Stand&gt;" in response.body.decode()
    assert harness.activated == []
    # Replace the web controller; the snapshot is on disk, not in its memory.
    restarted = RuleLearningSite(web.site)
    restarted.service = harness.service
    confirmation.update({"selected-0": "yes", "name-0": "Nicht geprüft", "yaml-0": "id: ["})
    assert web.browser.request("POST", "/lernen/entscheidungen", confirmation).status == 303
    assert harness.activated[0][0].name == "<Geprüfter YAML-Stand>"
    assert web.browser.request("POST", "/lernen/entscheidungen", confirmation).status == 303
    assert len(harness.activated) == 1 and len(harness.analyzer.calls) == 1


@pytest.mark.parametrize("change", [{"preview_key": "replaced"}, {"key": "other-key"}, {"version": "999"},
                                   {"confirm": ""}])
def test_only_the_exact_confirmed_snapshot_can_write(page, change):
    web, harness, _ = page
    analyze(page)
    _, confirmation = snapshot(page)
    before = harness.service.hashes()
    result = web.browser.request("POST", "/lernen/entscheidungen", confirmation | change)
    assert result.status in {409, 422}
    assert harness.service.hashes() == before and harness.activated == []


def test_new_preview_replaces_old_and_direct_apply_is_refused(page):
    web, harness, _ = page
    analyze(page)
    assert web.browser.request("POST", "/lernen/entscheidungen", choice_form(page)).status == 409
    _, first = snapshot(page)
    _, second = snapshot(page, **{"name-0": "Zweiter Prüfstand"})
    assert web.browser.request("POST", "/lernen/entscheidungen", first).status == 409
    assert web.browser.request("POST", "/lernen/entscheidungen", second).status == 303
    assert harness.activated[0][0].name == "Zweiter Prüfstand"


def test_continue_editing_retains_manual_fields_and_yaml(page):
    web, harness, _ = page
    analyze(page)
    edited = harness.service.state().proposals[0].proposed.model_dump(mode="json")
    edited["name"] = "YAML bleibt erhalten"
    snapshot(page, **{"name-0": "Manuelle Eingabe behalten", "yaml-0": yaml.safe_dump(edited)})
    html = web.browser.request("GET", "/lernen/entscheidungen").body.decode()
    assert 'name="name-0" value="Manuelle Eingabe behalten"' in html
    assert "YAML bleibt erhalten" in html and 'data-rule-select checked' in html


def test_a_new_topic_is_previewed_and_confirmed_alongside_an_existing_one(page):
    web, harness, _ = page
    harness.analyzer.result = RuleAnalysis(proposals=[proposal(), proposal(
        action="create", category="irrelevant", topic_id="noise", proposed=topic(id="noise", name="Werbung"))])
    analyze(page)
    fields = {**choice_form(page), "action": "preview", "selected-1": "yes", "id-1": "noise",
              "name-1": "Nur Werbung", "description-1": "Synthetischer Ausschluss",
              "examples-1": "", "exclusions-1": "", "enabled-1": "true"}
    response = web.browser.request("POST", "/lernen/entscheidungen", fields)
    assert response.status == 200 and "Nur Werbung" in response.body.decode()
    assert harness.activated == []
    confirmed = hidden(response.body.decode(), "/lernen/entscheidungen") | {"confirm": "yes"}
    assert web.browser.request("POST", "/lernen/entscheidungen", confirmed).status == 303
    saved = yaml.safe_load((harness.directory / "irrelevant_topics.yaml").read_text(encoding="utf-8"))
    assert saved["topics"][0]["name"] == "Nur Werbung"


def test_a_new_analysis_invalidates_the_previous_preview(page):
    web, harness, session = page
    analyze(page)
    _, confirmation = snapshot(page)
    harness.service.change("web:" + session.id, harness.service.state().version, "new-analysis-58", "analyze",
                           {"confirm": True, "scope": "all"})
    assert web.browser.request("POST", "/lernen/entscheidungen", confirmation).status == 409
    assert harness.activated == []


def test_file_and_session_rechecked_after_the_preview(page, monkeypatch):
    web, harness, _ = page
    analyze(page)
    _, confirmation = snapshot(page)
    (harness.directory / "topics.yaml").write_text("topics: []\n", encoding="utf-8")
    assert web.browser.request("POST", "/lernen/entscheidungen", confirmation).status == 409
    monkeypatch.setattr(harness.service, "check", lambda _: (_ for _ in ()).throw(PermissionError()))
    assert web.browser.request("POST", "/lernen/entscheidungen", confirmation).status == 403
    assert harness.activated == []


def test_preview_refuses_a_stale_version_and_an_expired_session_during_preparation(page, monkeypatch):
    web, harness, session = page
    analyze(page)
    fields = {**choice_form(page), "action": "preview", "version": "0"}
    assert web.browser.request("POST", "/lernen/entscheidungen", fields).status == 409
    fields["version"] = str(harness.service.state().version)
    calls = []

    def check(_):
        calls.append(1)
        if len(calls) == 2:
            raise PermissionError()

    monkeypatch.setattr(harness.service, "check", check)
    assert web.browser.request("POST", "/lernen/entscheidungen", fields).status == 403
    assert harness.store.load(preview_name("web:" + session.id), {}) == {}


def test_corrupt_preview_never_writes(page, monkeypatch):
    web, harness, _ = page
    analyze(page)
    _, confirmation = snapshot(page)
    original = harness.store.load

    def load(name, *args):
        if name.startswith("rule-preview-"):
            raise CorruptState("synthetic")
        return original(name, *args)

    monkeypatch.setattr(harness.store, "load", load)
    assert web.browser.request("POST", "/lernen/entscheidungen", confirmation).status == 503
    assert harness.activated == []


def test_unreadable_saved_edits_are_reported_without_writing(page, monkeypatch):
    web, harness, _ = page
    analyze(page)
    snapshot(page)
    original = harness.store.load

    def load(name, *args):
        if name.startswith("rule-preview-"):
            raise CorruptState("synthetic")
        return original(name, *args)

    monkeypatch.setattr(harness.store, "load", load)
    response = web.browser.request("GET", "/lernen/entscheidungen")
    assert response.status == 503 and "Prüfstand nicht lesbar" in response.body.decode()
    assert harness.activated == []


def test_a_malformed_saved_editor_never_overrides_the_original_proposal(page):
    web, harness, session = page
    analyze(page)
    harness.store.save(preview_name("web:" + session.id), ["invalid draft"])
    response = web.browser.request("GET", "/lernen/entscheidungen")
    assert response.status == 200 and "Vorgeschlagene Regel" in response.body.decode()
    assert harness.activated == []


def test_folder_preparation_is_read_only_and_estimate_retains_errors(learning):
    h = learning
    box = h.app.settings.imap.enabled_mailboxes()[0]
    h.app.settings.imap.mailboxes = [box, box.model_copy(update={"id": 2, "label": "Zweites", "folders": ["Other"]})]
    h.store.save("mailbox-folders", {"mailboxes": {"2": {"folders": [{"name": "Other"}, {"name": "Archive"}]}}})
    url = "/lernen/postfach?" + urlencode({"mailbox": 2, "prepare": 1, "count": 7, "price": 0.75,
                                         "budget": 9, "folders": "Custom"})
    html = h.browser.request("GET", url).body.decode()
    assert '<option value="2" selected>Zweites' in html
    assert 'name="folder" value="Archive"' in html and '>Custom</textarea>' in html
    assert "Typische Schätzung" not in html
    bad = h.browser.request("GET", "/lernen/postfach?" + urlencode({
        "mailbox": 1, "count": "bad", "price": 0.75, "budget": 9, "folder": "INBOX"})).body.decode()
    assert 'value="bad"' in bad and "Angaben für die Schätzung prüfen" in bad
    assert h.client.calls == [] and h.reader.reads == []
    assert "Angaben für die Schätzung prüfen" in h.browser.request(
        "GET", "/lernen/postfach?" + "&".join(f"x{i}=1" for i in range(121))).body.decode()


def test_checked_and_additional_folders_are_the_confirmed_selection(learning):
    h = learning
    query = urlencode({"mailbox": 1, "folder": ["INBOX", "INBOX"], "folders": "Archive\nCustom",
                       "count": 7, "price": 0.75, "budget": 9}, doseq=True)
    html = h.browser.request("GET", "/lernen/postfach?" + query).body.decode()
    selection = json.loads(hidden(html, "/lernen/postfach")["selection"])
    assert selection["folders"] == ["INBOX", "Archive", "Custom"] and selection["count"] == 7
    assert 'name="folder" value="INBOX" checked' in html
    assert h.client.calls == []


def test_initial_selection_uses_configured_folders_not_the_entire_catalog(learning):
    h = learning
    h.store.save("mailbox-folders", {"mailboxes": {"1": {"folders": [{"name": "INBOX"}, {"name": "Junk"}]}}})
    html = h.browser.request("GET", "/lernen/postfach").body.decode()
    assert 'name="folder" value="INBOX" checked' in html
    assert 'name="folder" value="Junk">' in html and 'value="Junk" checked' not in html


def test_missing_and_disabled_mailboxes_cannot_be_estimated(learning):
    h = learning
    html = h.browser.request("GET", "/lernen/postfach?" + urlencode({
        "mailbox": 99, "folders": "INBOX", "count": 7, "price": 0.75, "budget": 9})).body.decode()
    assert "Postfach nicht verfügbar" in html and 'name="selection"' not in html
    h.app.settings.imap.mailboxes = []
    html = h.browser.request("GET", "/lernen/postfach").body.decode()
    assert "Kein aktives Postfach" in html and 'name="selection"' not in html
    assert h.client.calls == []


def test_learning_summary_api_is_authenticated_and_reads_only(learning):
    h = learning
    route = "/api/lernen/uebersicht"
    assert Browser(h.web, host="localhost:8765").request("GET", route).status == 303
    before = json.loads(h.browser.request("GET", route).body)["fingerprint"]
    h.change("start", h.selection)
    after = json.loads(h.browser.request("GET", route).body)["fingerprint"]
    assert before != after
    assert json.loads(h.browser.request("GET", route).body)["fingerprint"] == after
    assert h.client.calls == []


@pytest.mark.parametrize("values,expected", [
    ({"name": "x" * 201, "description": "gut"}, "Höchstens 200 Zeichen"),
    ({"name": "Gut", "description": "gut", "examples": "\n".join(str(i) for i in range(31))},
     "Höchstens 30 Einträge"),
    ({"name": "Gut", "description": " "}, "Text darf nicht leer"),
    ({"id": "!!!", "name": "Gut", "description": "gut"}, "Ungültige Angabe"),
])
def test_german_errors_preserve_the_input(topics, values, expected):
    web, _ = topics
    response = preview(web, "/themen/relevant/neu", **values)
    assert response.status == 422 and expected in response.body.decode()


@pytest.mark.parametrize("name,value,warning", [
    ("retention.full_mail_days", 10, "unwiderruflich"),
    ("logging.llm.include_requests", True, "vollständige LLM-Inhalte"),
    ("test_mode", False, "Produktivbetrieb"), ("timezone", "UTC", "Neustart"),
])
def test_setting_confirmation_has_old_new_and_only_relevant_warning(name, value, warning):
    html = settings_confirmation({"name": name, "value": str(value), "key": "key"}, "/save", "csrf",
                                 {"timezone": "Europe/Berlin", "test_mode": True}, value)
    assert "Bisher gespeichert" in html and "Neu" in html and warning in html
    if name == "timezone":
        assert "Europe/Berlin" in html and "UTC" in html
        assert "unwiderruflich" not in html and "Maildaten" not in html


def test_setting_preview_does_not_truncate_long_personal_information():
    before, after = "Alt " * 50, "Neu " * 50
    html = settings_confirmation({"name": "personal_info", "value": after}, "/save", "csrf",
                                 {"personal_info": before}, after)
    assert before in html and after in html


def test_an_empty_personal_information_value_is_shown_as_not_set():
    html = settings_confirmation({"name": "personal_info", "value": ""}, "/save", "csrf", {}, "")
    assert html.count("nicht gesetzt") == 2 and ">None<" not in html
