"""4.8 settings are validated, authorized, live and independent of mail analysis."""
from contextlib import nullcontext
from types import SimpleNamespace as NS

import pytest
import yaml
from pydantic import ValidationError

from mailhelp.config import ImapSettings, Settings
from mailhelp.configuration import file_hash
from mailhelp.llm.fingerprints import config_fingerprint
from mailhelp.mailbox.mailbox_settings import effective_settings
from mailhelp.runtime.experience import ExperienceRuntime
from tests.fakes.shared_core import prompt_config
from tests.fakes.shared_web_v12 import configure
from tests.scenarios.web_scenario import mail_id


def test_drafts_default_to_available_but_automatic_writes_still_need_opt_in(configured):
    cfg = configured.cfg
    assert cfg.drafts.enabled is True and cfg.drafts.folder is None
    assert cfg.auto_draft is False and cfg.smart_reply is False
    original = config_fingerprint(cfg, prompt_config(), [])
    cfg.drafts.enabled, cfg.drafts.folder = False, "Entwürfe"
    assert config_fingerprint(cfg, prompt_config(), []) == original


@pytest.mark.parametrize("folder", ["", "Bad\r\nFolder", "Bad\x00Folder", "x" * 501])
def test_invalid_manual_folder_is_rejected(configured, folder):
    raw = configured.cfg.model_dump(mode="json")
    raw["drafts"] = {"enabled": True, "folder": folder}
    with pytest.raises(ValidationError) as caught:
        Settings.model_validate(raw)
    assert caught.value.errors()[0]["loc"] == ("drafts", "folder")


@pytest.mark.parametrize("name,value", [("drafts.enabled", "false"), ("drafts.folder", '"Entwürfe"'),
                                       ("drafts.folder", "null"), ("auto_draft", "true")])
def test_web_settings_require_confirmation_and_activate_without_restart(web, tmp_path, name, value):
    configuration, _, _, active, _ = configure(web, tmp_path)
    path = "/einstellungen?bereich=antworten"
    form = web.form(path, action="/einstellungen/speichern", name=name)
    form["value"] = value
    preview = web.browser.request("POST", "/einstellungen/speichern", form)
    assert preview.status == 200 and not active
    form["confirm"] = "yes"
    submitted = web.browser.request("POST", "/einstellungen/speichern", form)
    assert submitted.status == 303
    web.run()
    assert active and yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    root, _, child = name.partition(".")
    actual = getattr(active[-1], root)
    assert (getattr(actual, child) if child else actual) == yaml.safe_load(value)
    # Replayed submissions use the original idempotency key and do not execute twice.
    response = web.browser.request("POST", "/einstellungen/speichern", form)
    # A no-op preserves an already normalized LF file on Linux. That replay returns
    # the original queue entry; a changed file is rejected by the optimistic guard.
    assert response.status == (303 if file_hash(tmp_path / "config.yaml") == form["expected_hash"] else 409)
    if response.status == 303:
        assert dict(response.headers)["Location"] == dict(submitted.headers)["Location"]
    web.run()
    assert len(active) == 1
    assert configuration.active == active[-1]


def test_settings_reject_invalid_session_and_csrf(web, tmp_path):
    configure(web, tmp_path)
    form = web.form("/einstellungen?bereich=antworten", action="/einstellungen/speichern", name="drafts.enabled")
    form.update(value="false", confirm="yes")
    assert web.browser.request("POST", "/einstellungen/speichern", {**form, "csrf": "invalid"}).status == 403
    web.auth.revoke_all()
    assert web.browser.request("POST", "/einstellungen/speichern", form).status == 403


def test_a_mailbox_can_save_and_reset_its_automatic_draft_override(profiled):
    web = profiled.web
    path = "/einstellungen/postfaecher/1?tab=replies"
    route = "/einstellungen/postfaecher/speichern"
    form = web.form(path, action=route, field="auto_draft", number="1")
    assert web.browser.request("POST", route, {**form, "value": "true"}).status == 303
    assert profiled.runtime.setup.draft_settings().imap.mailbox(1).auto_draft is True
    form = web.form(path, action=route, field="auto_draft", number="1", index=1)
    assert web.browser.request("POST", route, form).status == 303
    assert profiled.runtime.setup.draft_settings().imap.mailbox(1).auto_draft is None


def test_runtime_rechecks_switches_and_uses_live_folder(configured):
    cfg = configured.cfg
    cfg.smart_reply, cfg.auto_draft = True, True
    # Exercise the runtime policy against the configured mailbox, without opening IMAP.
    runtime = ExperienceRuntime.__new__(ExperienceRuntime)
    runtime.app = configured.app
    runtime.mailbox_numbers = {"known": 1, "removed": 99}
    target = NS(connection=lambda: nullcontext(None), sender="me@example.test", folder="Drafts")
    from mailhelp.notifications.drafts import DraftTarget
    runtime.draft_targets = {"known": DraftTarget(target.connection, target.sender, target.folder)}
    assert runtime.draft_policy("known")[0] and runtime.auto_draft_policy("known")
    assert runtime.draft_target("known").folder == cfg.imap.mailbox(1).drafts_folder
    cfg.drafts.folder = "Antworten"
    assert runtime.draft_target("known").folder == "Antworten"
    cfg.drafts.enabled = False
    assert not runtime.draft_policy("known")[0] and not runtime.auto_draft_policy("known")
    assert runtime.draft_target("unknown") is None and runtime.draft_target("removed") is None
    box = cfg.imap.mailbox(1)
    cfg.imap = ImapSettings(mailboxes=[box.model_copy(update={"enabled": False}), box.model_copy(update={"id": 2})])
    assert runtime.draft_target("known") is None
    cfg.imap.mailboxes[0].enabled = True
    runtime.draft_targets = None
    assert runtime.draft_target("known") is None
    assert effective_settings(cfg, 1).drafts.enabled is False


def test_disabling_automatic_drafts_during_connection_prevents_append(configured):
    from mailhelp.notifications.drafts import DraftService, ReplyDraft
    from tests.scenarios.web_scenario import save_mail

    save_mail(configured.app.store, 80, "person@example.test", "Frage", text="Wann?")
    allowed, writes = [True], []
    class Imap:
        def select(self, *args, **kwargs):
            return "OK", []

        def uid(self, *args):
            allowed[0] = False  # the setting changes after generation, before APPEND
            return "OK", [b""]

        def append(self, *args):
            writes.append(args)
            return "OK", []

    drafts = DraftService(configured.app.store, lambda _: False, lambda: nullcontext(Imap()),
                          "me@example.test", analyzer=NS(draft_reply=lambda *a, **k: ("call", ReplyDraft(text="Danke"))))
    drafts.auto_policy = lambda _: allowed[0]
    assert drafts.auto_draft(mail_id(80), "Antwort") == "editing"
    assert writes == [] and drafts.get(mail_id(80))["text"] == "Danke"
