"""Scheduled mailbox briefings: strict settings, live authorized editing and safe defaults."""
import pytest
from pydantic import ValidationError

from mailhelp.config import Settings
from mailhelp.configuration import file_hash
from mailhelp.llm.fingerprints import config_fingerprint, legacy_fingerprints
from mailhelp.web.settings_pages import _input
from tests.fakes.shared_core import prompt_config
from tests.fakes.shared_web_v12 import configure


def test_briefings_are_disabled_by_default_and_operational(configured):
    settings = configured.cfg
    assert not settings.briefings.enabled
    assert settings.briefings.times == ["07:00", "13:00", "18:00"]
    assert settings.briefings.mailbox == "default" and settings.briefings.skip_empty
    before = (config_fingerprint(settings, prompt_config(), []), legacy_fingerprints(settings, prompt_config(), []))
    settings.briefings.enabled = True
    assert (config_fingerprint(settings, prompt_config(), []), legacy_fingerprints(settings, prompt_config(), [])) == before


@pytest.mark.parametrize("patch", [
    {"times": ["7:00"]}, {"times": ["24:00"]}, {"times": ["07:00", "07:00"]},
    {"enabled": True, "times": []}, {"mailbox": 0}, {"mailbox": True},
    {"enabled": True, "mailbox": 99}, {"enabled": "true"}, {"times": "07:00"},
])
def test_invalid_settings_are_rejected(configured, patch):
    raw = configured.cfg.model_dump(mode="json")
    raw["briefings"] = patch
    with pytest.raises(ValidationError):
        Settings.model_validate(raw)


def test_disabled_briefings_may_have_no_times_and_valid_times_are_sorted(configured):
    raw = configured.cfg.model_dump(mode="json")
    raw["briefings"] = {"times": []}
    assert Settings.model_validate(raw).briefings.times == []
    raw["briefings"] = {"times": ["18:00", "07:00"]}
    assert Settings.model_validate(raw).briefings.times == ["07:00", "18:00"]


@pytest.mark.parametrize("name,value,expected", [
    ("briefings.enabled", "true", True),
    ("briefings.times", "07:00, 13:00; 18:00", ["07:00", "13:00", "18:00"]),
    ("briefings.skip_empty", "false", False),
    ("briefings.mailbox", "1", 1),
    ("briefings.mailbox", "default", "default"),
])
def test_web_edits_require_confirmation_and_apply_without_restart(web, tmp_path, name, value, expected):
    _, _, _, active, _ = configure(web, tmp_path)
    path, route = "/einstellungen?bereich=briefing", "/einstellungen/speichern"
    form = web.form(path, action=route, name=name)
    form["value"] = value
    assert web.browser.request("POST", route, form).status == 200 and not active
    form["confirm"] = "yes"
    submitted = web.browser.request("POST", route, form)
    assert submitted.status == 303
    web.run()
    assert getattr(active[-1].briefings, name.split(".")[1]) == expected
    # Reuse of the same submitted key never performs the change again.
    response = web.browser.request("POST", route, form)
    assert response.status == (303 if file_hash(tmp_path / "config.yaml") == form["expected_hash"] else 409)
    if response.status == 303:
        assert dict(response.headers)["Location"] == dict(submitted.headers)["Location"]
    web.run()
    assert len(active) == 1


def test_editor_has_times_and_enabled_mailbox_choices_and_keeps_auth_guards(profiled):
    web = profiled.web
    html = web.browser.request("GET", "/einstellungen?bereich=briefing").body.decode()
    assert 'value="default"' in html and 'value="1"' in html and 'value="2"' in html
    assert "07:00, 13:00, 18:00" in html
    form = web.form("/einstellungen?bereich=briefing", action="/einstellungen/speichern", name="briefings.enabled")
    form.update(value="true", confirm="yes")
    assert web.browser.request("POST", "/einstellungen/speichern", {**form, "csrf": "bad"}).status == 403
    web.auth.revoke_all()
    assert web.browser.request("POST", "/einstellungen/speichern", form).status == 403


def test_editor_handles_absent_saved_values_and_excludes_disabled_mailboxes():
    assert 'value=""' in _input("briefings.times", None)
    html = _input("briefings.mailbox", None, {"imap": {"mailboxes": [
        {"id": 2, "label": "Aktiv"}, {"id": 9, "label": "Ausgeschaltet", "enabled": False}]}})
    assert 'value="2"' in html and 'value="9"' not in html and 'value="default" selected' in html
