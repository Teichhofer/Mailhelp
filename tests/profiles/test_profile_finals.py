"""Defaults, duplicate-copy notices and lazily refreshed credentials keep mailbox identity."""
import hashlib
import json
from types import SimpleNamespace as NS

import pytest
from shared_decision_test import secrets
from shared_profiles import ACCOUNT_TWO
from shared_telegram_dialog import proposal

from mailhelp.config import MailboxEventDefaults
from mailhelp.experience import ExperienceRuntime
from mailhelp.logging import JsonlLogger
from mailhelp.models import MailState
from mailhelp.review.commands import CommandKind, CommandSource, ReviewCommand
from mailhelp.review.results import ResultStatus


def test_default_reapplication_uses_origin_mailbox_and_bound_hash(profiled):
    app, web = profiled.app, profiled.web
    app.settings.imap.mailboxes[1].event_defaults = MailboxEventDefaults(video_duration_minutes=90)
    item = proposal(kind="event", start="2026-10-15T10:00:00+00:00", end="2026-10-15T11:00:00+00:00",
        meeting_mode="video", end_origin="standard", default_duration_minutes=60)
    web.dialog.persist(item)
    mail = MailState(id=item.source_mail_id, config_fingerprint="f" * 64,
        imap={"account_id": ACCOUNT_TWO, "folder": "INBOX", "uidvalidity": 1, "uid": 1}, proposal_policy={"mailbox_id": 2})
    app.store.save("mail-" + mail.id, mail.model_dump(mode="json"))
    defaults = web.site.reconciliation_page.defaults(item)
    assert defaults.video_duration_minutes == 90
    digest = hashlib.sha256(json.dumps(defaults.model_dump(), sort_keys=True).encode()).hexdigest()
    command = ReviewCommand(kind=CommandKind.DEFAULTS, source=CommandSource.WEB,
        actor="web:" + web.auth.sessions()[0].id, mail_id=item.source_mail_id, proposal_id=item.id,
        version=1, idempotency_key="defaults-001", proposal_hash=digest)
    assert web.dialog.review.execute(command).status == ResultStatus.DONE
    assert web.dialog.repository.load_current(item.source_mail_id, item.id).version == 2
    assert web.writer.created == 0


def test_duplicate_copy_with_another_target_profile_is_visible_without_an_action(profiled):
    from mailhelp.models import DuplicateDecision
    app, web = profiled.app, profiled.web
    previous = MailState(id="a" * 24, config_fingerprint="f" * 64,
        imap={"account_id": "1" * 24, "folder": "INBOX", "uidvalidity": 1, "uid": 1}, proposal_policy={"target_profile": 1})
    copy = previous.model_copy(update={"id": "b" * 24, "proposal_policy": {"target_profile": 2},
        "duplicate": DuplicateDecision(outcome="duplicate", previous_mail_id=previous.id, reason="same_message")})
    for mail in (previous, copy):
        app.store.save("mail-" + mail.id, mail.model_dump(mode="json"))
    assert "anderen Zielprofil" in web.site.reconciliation_page.mail_summary(copy.id)


def test_fresh_profile_credentials_join_log_redaction_and_report_default_folder(profiled):
    app, runtime = profiled.app, profiled.runtime
    app.logger = JsonlLogger(profiled.tmp_path / "logs")
    runtime.secrets = secrets()
    (profiled.tmp_path / ".env").write_text("MICROSOFT_2_CLIENT_ID=work-client\nMICROSOFT_2_REFRESH_TOKEN=work-refresh\n")
    refreshed = runtime.credentials(app.settings)
    assert refreshed.for_profile(2).microsoft_refresh_token.get_secret_value() == "work-refresh"
    assert "work-refresh" in app.logger.secrets
    runtime.secrets = refreshed
    app.settings.activity_report.enabled = True
    from activity_fakes import activity_prompts

    from mailhelp.analysis import Analyzer
    app.analyzer = Analyzer(object(), activity_prompts())
    app.settings.imap.mailboxes[1].activity_report_folder = "Projekte"
    ExperienceRuntime(app, NS(site=profiled.web.site, auth=profiled.web.auth), refreshed)
    assert profiled.web.site.activity.suggest_folders(2) == ["Projekte"]
