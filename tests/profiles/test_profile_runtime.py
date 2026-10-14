"""Mailbox briefing, maintenance and diagnostics use real persisted origin information."""
import json
from datetime import UTC, datetime
from types import SimpleNamespace as NS

import pytest
from shared_decision_test import secrets
from shared_profiles import ACCOUNT_ONE, ACCOUNT_TWO, settings
from shared_telegram_dialog import proposal

from mailhelp.briefing import DailyBriefingService
from mailhelp.config import Secrets
from mailhelp.external.providers import Writers
from mailhelp.logging import JsonlLogger
from mailhelp.mailbox_briefing import configure, sections
from mailhelp.mailbox_settings import merge_policy
from mailhelp.models import MailState
from mailhelp.notification_runtime import NotificationRuntime
from mailhelp.review.views import ReviewViews
from mailhelp.target_profiles import ProfileLogger, ProfileWriters, UnavailableWriter, build_profile_writers


def test_mailbox_briefing_sections_include_only_own_decisions_and_configured_targets(profiled):
    app, web = profiled.app, profiled.web
    item = proposal(source_mail_id="a" * 24)
    app.store.save("proposal-" + item.source_mail_id + "-" + item.id, item.model_dump(mode="json"))
    mail = MailState(id=item.source_mail_id, config_fingerprint="f" * 64,
        imap={"account_id": ACCOUNT_TWO, "folder": "INBOX", "uidvalidity": 1, "uid": 1})
    app.store.save("mail-" + mail.id, mail.model_dump(mode="json"))
    one = NS(calendar=app.calendar, tasks=app.todoist)
    app.profile_writers = ProfileWriters({1: one, 2: one})
    svc = DailyBriefingService(app.store, app.settings.daily_briefing, "UTC", None, None, web.site.views, {"local": lambda _: None},
        clock=lambda: datetime(2026, 10, 14, 9, tzinfo=UTC))
    app.settings.daily_briefing.enabled = True
    app.settings.daily_briefing.time = "00:00"
    configure(app, svc, web.site.views)
    entries = sections(app, web.site.views)
    assert len(entries) == 2
    assert any(row.proposal_id == item.id for row in entries[1][4].overview().open)
    assert all(row.proposal_id != item.id for row in entries[0][4].overview().open)
    svc.tick()
    assert svc.sections.keys() == {"1", "2"} and "Arbeit" in app.store.load("briefing-latest")["text"]
    app.profile_writers = None
    assert isinstance(sections(app, web.site.views)[1][2], UnavailableWriter)
    app.settings.imap.mailboxes[1].daily_briefing = False
    assert len(sections(app, web.site.views)) == 1
    app.settings.imap.mailboxes[0].daily_briefing = False
    assert sections(app, web.site.views) == []
    assert svc.build(svc.clock()).startswith("Guten Morgen")


def test_profile_logger_removes_nested_credentials_addresses_and_urls(tmp_path):
    logger = JsonlLogger(tmp_path, secrets=secrets().known_values())
    profile = ProfileLogger(logger, secrets(), 2)
    profile.event("ERROR", "provider", "failed", status=401, nested={"values": [
        "https://user:pass@example.test/private", "person@example.test", secrets().todoist_token.get_secret_value()],
        "flag": True, "missing": None})
    text = (tmp_path / "application.jsonl").read_text()
    assert "example.test" not in text and "synthetic-todoist_token" not in text
    event = json.loads(text)
    assert event["profile"] == 2
    assert merge_policy({"one": "global"}, {"one": None}) == {"one": "global"}


def test_diagnosis_reads_only_selected_profile_and_closes_every_adapter(profiled, monkeypatch):
    runtime = profiled.runtime
    assert runtime.profile_check(2, "calendar") == ("failed", "auth")
    runtime.secrets = secrets().model_copy(update={"profiles": {2: {"microsoft_client_id": secrets().microsoft_client_id}}})
    runtime.update_profile_checks()
    runtime.update_profile_checks()
    assert {"calendar:1", "tasks:1", "calendar:2", "tasks:2"} <= runtime.diagnostics.checks.keys()
    calls = []
    def adapter(role):
        return NS(check_access=lambda: calls.append((role, "read")), close=lambda: calls.append((role, "close")))
    monkeypatch.setattr("mailhelp.setup_runtime.build_writers", lambda cfg, creds, directory, **kw: Writers(adapter("calendar"), adapter("tasks")))
    assert runtime.profile_check(2, "calendar") == runtime.profile_check(2, "tasks") == ("ready", "")
    assert calls.count(("calendar", "close")) == calls.count(("tasks", "close")) == 2
    assert "MICROSOFT_2_CLIENT_ID" in runtime.secret_status()
    runtime.secrets = None
    assert runtime.secret_status()["MICROSOFT_2_CLIENT_ID"] == "fehlt"


def test_native_profile_adapters_are_built_even_if_only_profile_two_is_active(tmp_path):
    cfg = settings(tmp_path)
    cfg.imap.mailboxes[0].enabled = False
    cfg.target_profiles[0].calendar_provider = "google"
    cfg.target_profiles[0].task_provider = "todoist"
    creds = secrets()
    creds.profiles = {2: {name: value for name, value in creds if name.startswith(("google_", "todoist_"))}}
    pairs = build_profile_writers(cfg, creds, tmp_path)
    assert pairs.default_profile == 2 and set(pairs.profiles) == {2}
    assert pairs.tasks.target_profile == pairs.calendar.target_profile == 2
    pairs.close()


def test_disabling_mailbox_briefing_cancels_a_previously_queued_section(profiled):
    app, web = profiled.app, profiled.web
    app.settings.daily_briefing.enabled = True
    runtime = NotificationRuntime(app, web.site)
    day = runtime.queue.clock().astimezone(runtime.briefing.zone).date().isoformat()
    runtime.queue.enqueue("daily_briefing", day + ":2", mailbox_id=2)
    queued = next(item for item in runtime.queue.state().entries.values() if item.reference == day + ":2")
    app.settings.imap.mailboxes[1].daily_briefing = False
    assert not runtime.relevant(queued)
    app.settings.imap.mailboxes[1].daily_briefing = True
    assert runtime.relevant(queued)
    app.settings.imap.mailboxes[1].enabled = False
    assert not runtime.relevant(queued)
    app.settings.imap.mailboxes = app.settings.imap.mailboxes[:1]
    assert not runtime.relevant(queued)
