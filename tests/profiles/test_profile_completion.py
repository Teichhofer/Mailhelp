"""Failure paths and restart integration of the mailbox settings workflow."""
import json
from types import SimpleNamespace as NS

import pytest
import yaml
from shared_profiles import ACCOUNT_TWO, TOPICS
from shared_telegram_dialog import proposal

from mailhelp.application import Application
from mailhelp.configuration import AdminCommand, AdminKind, file_hash
from mailhelp.decisions import load_relevance_prompts
from mailhelp.drafts import DraftService
from mailhelp.experience import ExperienceRuntime
from mailhelp.external.providers import Writers
from mailhelp.models import MailState
from mailhelp.notification_runtime import NotificationRuntime
from mailhelp.review.commands import CommandKind, CommandSource, ReviewCommand
from mailhelp.review.results import ResultStatus
from mailhelp.setup_runtime import SetupRuntime
from mailhelp.target_profiles import ProfileWriters


@pytest.mark.parametrize(("method", "path"), [
    ("GET", "/einstellungen/postfaecher"), ("GET", "/einstellungen/postfaecher/1"),
    ("GET", "/einstellungen/zielprofile"), ("POST", "/einstellungen/postfaecher/speichern"),
    ("POST", "/einstellungen/zielprofile/speichern"), ("POST", "/einstellungen/postfaecher/thema"),
    ("POST", "/einstellungen/postfaecher/filter"), ("POST", "/einstellungen/postfaecher/verwerfen")])
def test_missing_setup_runtime_reports_unavailable_instead_of_writing(web, method, path):
    form = {"csrf": web.auth.csrf_token(web.auth.sessions()[0].id), "key": "unavailable-01"}
    assert web.browser.request(method, path, form if method == "POST" else None).status == 503


def test_mailbox_add_remove_and_invalid_filter_or_discard_preserve_versions(profiled):
    web, setup = profiled.web, profiled.runtime.setup
    form = web.form("/einstellungen/postfaecher", action="/einstellungen/postfaecher/speichern")
    values = dict(id="3", label="Weitere", host="third.example.test", port="993", folders="INBOX, Projekte")
    assert web.browser.request("POST", "/einstellungen/postfaecher/speichern", {**form, **values}).status == 303
    assert setup.draft_settings().imap.mailbox(3).folders == ["INBOX", "Projekte"]
    remove = web.form("/einstellungen/postfaecher/3", action="/einstellungen/postfaecher/speichern", index=-1)
    assert web.browser.request("POST", "/einstellungen/postfaecher/speichern", remove).status == 303
    discard = web.form("/einstellungen/postfaecher", action="/einstellungen/postfaecher/verwerfen")
    assert web.browser.request("POST", "/einstellungen/postfaecher/verwerfen", {**discard, "version": "999"}).status == 409
    assert web.browser.request("POST", "/einstellungen/postfaecher/verwerfen", discard).status == 303
    form = web.form("/einstellungen/postfaecher/2?tab=filters", action="/einstellungen/postfaecher/filter")
    assert web.browser.request("POST", "/einstellungen/postfaecher/filter", {**form, "value": "bad", "action": "add"}).status == 409
    assert web.browser.request("POST", "/einstellungen/postfaecher/filter", {**form, "value": "example.test", "action": "add"}).status == 303


def test_impact_counts_removed_mailboxes_and_jev_fingerprint_changes(profiled, monkeypatch):
    app, page = profiled.app, profiled.web.site.mailbox_page
    mail = MailState(id="a" * 24, config_fingerprint="f" * 64,
        imap={"account_id": ACCOUNT_TWO, "folder": "INBOX", "uidvalidity": 1, "uid": 1})
    app.store.save("mail-" + mail.id, mail.model_dump(mode="json"))
    boxes = [app.settings.imap.mailbox(1).model_dump(mode="json")]
    profiled.runtime.setup.save("web:" + profiled.web.auth.sessions()[0].id, 0, "remove-001", 6, {"imap.mailboxes": boxes})
    assert page.affected()[2] == 1
    profiled.runtime.setup.discard("web:" + profiled.web.auth.sessions()[0].id, 1, "discard-001")
    app.orchestrator.mailbox_jev = load_relevance_prompts(profiled.tmp_path)
    assert page.affected()[2] == 1
    original = app.store.peek_model
    monkeypatch.setattr(app.store, "peek_model", lambda name, model: None if name == "mail-" + mail.id else original(name, model))
    assert 2 not in page.affected()


def test_live_configuration_merge_checks_revoked_session_and_safe_yaml_semantics(profiled, monkeypatch):
    cfg = profiled.app.configuration
    boxes = [box.model_dump(mode="json") for box in cfg.active.imap.configured_mailboxes()[:1]]
    command = AdminCommand(kind=AdminKind.SETUP, actor="web:" + profiled.web.auth.sessions()[0].id,
        expected_hash=file_hash(profiled.tmp_path / "config.yaml"), idempotency_key="mixed-0001", acknowledged=True,
        patch={"imap.mailboxes": boxes, "timezone": "Europe/Berlin", "notifications.categories.decisions": ["telegram"]})
    assert yaml.safe_load(cfg.render(command, cfg.candidate(command)))["timezone"] == "Europe/Berlin"
    assert cfg.execute(command).status == ResultStatus.DONE
    assert cfg.active.imap.mailbox(2) is not None
    path = profiled.tmp_path / "config.yaml"
    command = command.model_copy(update={"expected_hash": file_hash(path)})
    monkeypatch.setattr("mailhelp.configuration.replace_block", lambda text, *args: text)
    changed = command.model_copy(update={"patch": {"imap.mailboxes": [dict(boxes[0], label="changed")]}})
    assert cfg.execute(changed).status == ResultStatus.INVALID
    monkeypatch.undo()
    checks = iter([True, False])
    cfg.authorize = lambda _: next(checks)
    assert cfg.execute(command).status == ResultStatus.UNAUTHORIZED


def test_removing_profile_with_an_open_proposal_is_denied_even_without_mailbox_reference(profiled):
    cfg = profiled.app.configuration
    boxes = [dict(box.model_dump(mode="json"), target_profile=1) for box in cfg.active.imap.configured_mailboxes()]
    raw = cfg.active.model_dump(mode="json")
    raw["imap"]["mailboxes"] = boxes
    (profiled.tmp_path / "config.yaml").write_text(yaml.safe_dump(raw))
    cfg.active.imap.mailboxes[1].target_profile = 1
    item = proposal(target_profile=2)
    profiled.web.dialog.persist(item)
    command = AdminCommand(kind=AdminKind.SETUP, actor="web:" + profiled.web.auth.sessions()[0].id,
        expected_hash=file_hash(profiled.tmp_path / "config.yaml"), idempotency_key="remove-001", acknowledged=True,
        patch={"target_profiles": []})
    assert cfg.execute(command).status == ResultStatus.INVALID
    profiled.runtime.secrets = None
    assert profiled.runtime.credentials(cfg.active) is None


def test_profile_access_diagnostics_keep_all_enabled_profiles_in_the_report(profiled):
    app = profiled.app
    calls = []
    def adapter(role):
        return NS(check_access=lambda: calls.append(role), label=role)
    app.profile_writers = ProfileWriters({1: Writers(adapter("calendar"), adapter("tasks")),
                                         2: Writers(adapter("calendar"), adapter("tasks"))})
    app.sources = []
    app.openrouter.service_name, app.openrouter.check_access = "OpenRouter", lambda: None
    app._check_telegram_access = lambda: None
    app.telegram.check_access = lambda: None
    app.settings.telegram.enabled = False
    result = Application.check_access(app)
    assert len(calls) == 4 and any("2 (Arbeit)" in key for key in result)


def test_notification_restart_assigns_origin_and_rebuilds_legacy_briefing_sections(profiled):
    app, web = profiled.app, profiled.web
    item = proposal(source_mail_id="a" * 24)
    web.dialog.persist(item)
    mail = MailState(id=item.source_mail_id, config_fingerprint="f" * 64,
        imap={"account_id": ACCOUNT_TWO, "folder": "INBOX", "uidvalidity": 1, "uid": 1}, proposal_policy={"mailbox_id": 2})
    app.store.save("mail-" + mail.id, mail.model_dump(mode="json"))
    runtime = NotificationRuntime(app, web.site)
    runtime.queue.enqueue("decisions", item.source_mail_id + ":" + item.id)
    review = ReviewCommand(kind=CommandKind.REJECT, source=CommandSource.WEB,
        actor="web:" + web.auth.sessions()[0].id, mail_id=item.source_mail_id, proposal_id=item.id,
        version=1, idempotency_key="result-0001")
    identity = web.commands.submit(review)[0].id
    runtime.queue.enqueue("action_results", identity)
    runtime.queue.enqueue("action_results", "missing-command")
    runtime.queue.enqueue("system_errors", "service:calendar:2")
    app.store.delete("notifications-mailboxes")
    restarted = NotificationRuntime(app, web.site)
    assert all(entry.mailbox_id == 2 for entry in restarted.queue.state().entries.values()
               if entry.reference == item.source_mail_id + ":" + item.id or entry.reference == identity)
    assert restarted.mailbox_of("unknown") == 1
    app.settings.daily_briefing.enabled = True
    app.settings.daily_briefing.include_calendar = app.settings.daily_briefing.include_tasks = False
    day = restarted.queue.clock().astimezone(restarted.briefing.zone).date().isoformat()
    app.store.save("daily-briefing", {"day": day, "channels": {"local": "sent"}})
    app.store.save("briefing-latest", {"day": day, "text": "old"})
    restarted.tick()
    assert app.store.load("briefing-latest")["sections"].keys() == {"1", "2"}


def test_configuration_sender_validation_uses_active_config_if_file_temporarily_absent(profiled):
    cfg = profiled.app.configuration
    path = profiled.tmp_path / "config.yaml"
    path.unlink()
    command = AdminCommand(kind=AdminKind.SENDERS, actor="web:" + profiled.web.auth.sessions()[0].id,
        idempotency_key="sender-001", patch={"action": "add", "mailbox_id": 2, "addresses": ["a@example.test"]})
    assert cfg.execute(command).status == ResultStatus.DONE


def test_decision_comparison_sender_prefilter_calls_no_language_model(tmp_path):
    from shared_core import prompt_config
    from shared_decision_test import RAW, Reader, settings

    from mailhelp.decision_test import ComparisonRecorder, DecisionTestMode
    from mailhelp.models import IrrelevantSenders
    output = tmp_path / "comparison.json"
    report = {"mails": [], "selection_errors": []}
    mode = DecisionTestMode(Reader(), object(), object(), settings(), TOPICS, report, output,
        ComparisonRecorder(tmp_path / "comparison.jsonl", ()), relevance_only=True,
        blocked_senders=IrrelevantSenders(addresses=["sender@example.test"]))
    assert mode.run(1) == 0
    assert all(path["stages"]["relevance"]["call_id"] == "prefilter" for path in report["mails"][0]["paths"].values())
