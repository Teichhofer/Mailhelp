"""Real queue composition over synthetic persisted decisions and transport failures."""
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS

import httpx
import pytest
import requests
from pywebpush import WebPushException
from shared_services import proposal
from shared_web_actions import MAIL1
from shared_web_auth import SECRET
from shared_web_details import with_mail

from mailhelp.adapter import PermanentError, RetryableError
from mailhelp.models import MailState, ProposalStatus
from mailhelp.notification_config import Categories, NotificationSettings
from mailhelp.notification_context import web_reply
from mailhelp.notification_runtime import NotificationRuntime
from mailhelp.notifications import Delivery, QueueFull
from mailhelp.review.commands import CommandKind, CommandSource, ReviewCommand
from mailhelp.review.results import ResultStatus, ReviewResult
from mailhelp.telegram import TelegramClient
from mailhelp.webpush import PushService

# Since 2.3 the writers are built in mailhelp.external.providers.
MOVED_WRITERS = ("HttpWriter", "GoogleOAuthTokenProvider")


@pytest.fixture
def runtime(configured):
    app, web = configured.app, configured.web
    app.settings.notifications = NotificationSettings(categories=Categories(
        decisions=["telegram"], daily_briefing=["telegram"], action_results=["telegram"], system_errors=["telegram"]))
    app.settings.daily_briefing.include_calendar = app.settings.daily_briefing.include_tasks = False
    result = NotificationRuntime(app, web.site)
    web.site.notification_runtime = result
    return NS(runtime=result, web=web, app=app, cfg=app.settings)


def test_runtime_neutral_profile_respects_categories_and_does_not_repeat_on_restart(runtime):
    svc, web = runtime.runtime, runtime.web
    before = list(web.telegram.sent)
    svc.tick()
    assert len(web.telegram.sent) == len(before) + 1
    assert "Entscheidungen warten" in web.telegram.sent[-1][1]
    assert "Elternabend" not in web.telegram.sent[-1][1]
    svc.tick()
    restarted = NotificationRuntime(runtime.app, web.site)
    restarted.tick()
    assert len(web.telegram.sent) == len(before) + 1
    assert web.site.notification_runtime.queue.state().entries
    page = web.browser.request("GET", "/benachrichtigungen")
    assert page.status == 200 and "an den Dienst übergeben" in page.body.decode() and "sent" in page.body.decode()
    runtime.cfg.notifications.categories.decisions = []
    assert svc.destinations("decisions") == []
    runtime.cfg.telegram.enabled = False
    runtime.cfg.notifications.categories.decisions = ["telegram"]
    assert svc.destinations("decisions") == []


def test_queued_old_messages_are_transferred_and_background_outbox_cannot_bypass_quiet(runtime):
    svc, web = runtime.runtime, runtime.web
    runtime.cfg.notifications.quiet_hours.enabled = True
    svc.queue.clock = lambda: datetime(2026, 10, 13, 23, tzinfo=UTC)
    p = web.dialog.repository.load_current(MAIL1, "elternabend")
    identity = web.dialog.outbox.enqueue_proposal(p)
    assert len(identity) == 32 and web.dialog.outbox.load().entries == []
    web.dialog.outbox.enqueue_message("private mail summary")
    web.dialog.outbox.enqueue_relevance(NS(mail_id=MAIL1, version=3), "private sender", "private subject")
    before = list(web.telegram.sent)
    svc.tick()
    assert web.telegram.sent == before
    assert "private" not in (runtime.app.store.directory / "notification-queue.json").read_text()


def test_current_revision_and_finished_decisions_are_checked_at_dispatch(runtime):
    svc, web = runtime.runtime, runtime.web
    runtime.cfg.notifications.batching.enabled = True
    svc.queue.clock = lambda: datetime(2026, 10, 13, 10, tzinfo=UTC)
    svc.tick()
    p = web.dialog.repository.load_current(MAIL1, "elternabend")
    web.dialog.repository.save_revision(p.model_copy(update={"status": ProposalStatus.REJECTED}))
    svc.queue.clock = lambda: datetime(2026, 10, 13, 12, tzinfo=UTC)
    svc.tick()
    entries = list(svc.queue.state().entries.values())
    assert any(item.reference == f"{MAIL1}:elternabend" and item.status == "cancelled" for item in entries)


def test_legacy_delivery_markers_seed_sent_and_uncertain_without_replaying(configured):
    app, web = configured.app, configured.web
    from mailhelp.models import ProposalNotification
    state = web.store.load_model("mail-" + MAIL1, MailState)
    state.proposal_notifications = [ProposalNotification(proposal_id=p.id, proposal_version=p.version,
                                                         status="completed" if p.id == "elternabend" else "sending")
                                    for p in state.proposals]
    web.store.save("mail-" + MAIL1, state.model_dump(mode="json"))
    svc = NotificationRuntime(app, web.site)
    svc.tick()
    statuses = {item.reference: item.status for item in svc.queue.state().entries.values()}
    assert statuses[f"{MAIL1}:elternabend"] == "sent"
    assert "uncertain" in statuses.values()
    svc.tick()
    assert not any("Elternabend" in text for _, text, *_ in web.telegram.sent)
    assert app.store.load("notifications-backup")["schema_version"] == 1


def test_briefing_goes_through_quiet_policy_and_keeps_legacy_day_markers(runtime):
    svc, cfg, web = runtime.runtime, runtime.cfg, runtime.web
    cfg.daily_briefing.enabled, cfg.daily_briefing.time = True, "00:00"
    fixed = datetime(2026, 10, 13, 10, tzinfo=UTC)
    svc.queue.clock = svc.briefing.clock = lambda: fixed
    web.store.save("daily-briefing", {"day": "2026-10-13", "channels": {"telegram": "sent"}})
    svc.tick()
    briefings = [item for item in svc.queue.state().entries.values() if item.category == "daily_briefing"]
    assert len(briefings) == 1 and briefings[0].status == "sent"
    assert web.store.load("briefing-latest") is not None
    cfg.notifications.telegram_content = "summary"
    fixed += timedelta(days=1)
    svc.tick()
    assert any("Guten Morgen!" in text for _, text, *_ in web.telegram.sent)
    cfg.daily_briefing.enabled = False
    assert not svc.relevant(briefings[0])


def test_action_result_is_not_queued_before_execution_and_is_idempotent(runtime):
    web, svc = runtime.web, runtime.runtime
    sid = web.auth.sessions()[0].id
    command = ReviewCommand(kind=CommandKind.REJECT, source=CommandSource.WEB, actor="web:" + sid,
                            idempotency_key="action-001", mail_id=MAIL1, proposal_id="elternabend", version=1)
    entry, _ = web.commands.submit(command)
    svc.tick()
    assert not any(item.category == "action_results" for item in svc.queue.state().entries.values())
    web.commands.finish(entry.id, ReviewResult(status=ResultStatus.DONE, message="Synthetic result"))
    svc.tick()
    results = [item for item in svc.queue.state().entries.values() if item.category == "action_results"]
    assert len(results) == 1 and results[0].status == "sent"
    cfg = runtime.cfg.notifications
    cfg.telegram_content = "summary"
    svc.send(results, cfg)
    assert "Synthetic result" in web.telegram.sent[-1][1]
    assert not svc.relevant(results[0].model_copy(update={"reference": "0" * 32}))
    cfg.telegram_content = "neutral"
    svc.tick()
    assert len([item for item in svc.queue.state().entries.values() if item.category == "action_results"]) == 1


def test_summary_messages_use_current_subjects_and_daily_briefing_stays_separate(runtime):
    svc = runtime.runtime
    runtime.cfg.notifications.telegram_content = "summary"
    svc.tick()
    assert any("Elternabend" in text for _, text, *_ in runtime.web.telegram.sent)
    item = next(iter(svc.queue.state().entries.values())).model_copy(update={"category": "system_errors"})
    assert not svc.relevant(item)
    svc.send([item], runtime.cfg.notifications)
    assert "Betriebsproblem" in runtime.web.telegram.sent[-1][1]


def test_capacity_keeps_decisions_in_source_and_scheduler_failure_isolated(runtime, monkeypatch):
    svc = runtime.runtime
    svc.queue.enqueue = lambda *args, **kwargs: (_ for _ in ()).throw(QueueFull())
    svc.tick()
    assert svc.decisions()
    svc.stop()
    other = NotificationRuntime(runtime.app, runtime.web.site)
    def failed():
        other.stop_event.set()
        raise OSError("secret")
    monkeypatch.setattr(other, "tick", failed)
    other.start()
    other.thread.join(2)
    other.stop()
    assert not other.thread.is_alive()
    assert runtime.web.logger.events[-1][0][2] == "background_failed"


def test_without_web_scheduler_uses_the_same_policy(configured):
    svc = NotificationRuntime.without_web(configured.app)
    assert svc.site.experience.push is None and svc.destinations("decisions") == [("telegram", "")]
    svc.stop_event.set()
    svc.run()
    svc.stop()


def test_push_destinations_and_per_device_delivery_are_neutral_and_rechecked(runtime):
    from push_fakes import sub
    web, cfg, svc = runtime.web, runtime.cfg, runtime.runtime
    sent = []
    push = PushService(web.store, web.auth, "mailto:synthetic@test", lambda **kw: sent.append(kw))
    sid = web.auth.sessions()[0].id
    push.change(sid, "push-0001", sub())
    web.site.experience.push = push
    cfg.push.enabled = True
    cfg.notifications.categories.decisions = ["web_push"]
    svc.tick()
    assert len(sent) == 1
    data = json.loads(sent[0]["data"])
    assert data["body"] == "Neue Informationen in Mailhelp." and "Elternabend" not in sent[0]["data"]
    device = push.destinations()[0]
    push.change(sid, "push-0002", None)
    with pytest.raises(PermanentError):
        push.deliver(device, "decisions")


@pytest.mark.parametrize("status,expected", [(410, PermanentError), (429, RetryableError), (403, PermanentError),
                                             (500, WebPushException), (None, WebPushException)])
def test_push_failure_propagates_to_durable_delivery_status(runtime, status, expected):
    from push_fakes import sub
    web = runtime.web
    response = requests.Response() if status is not None else None
    if response is not None:
        response.status_code = status
    def failure(**kw):
        raise WebPushException("provider response with secret", response=response)
    push = PushService(web.store, web.auth, "mailto:synthetic@test", failure)
    sid = web.auth.sessions()[0].id
    push.change(sid, "push-0001", sub())
    device = push.destinations()[0]
    with pytest.raises(expected):
        push.deliver(device, "decisions")
    assert bool(push.destinations()) == (status != 410)


def test_revoked_device_and_subscription_revision_are_checked_before_push(runtime):
    from push_fakes import sub
    web = runtime.web
    push = PushService(web.store, web.auth, "mailto:synthetic@test", lambda **kw: pytest.fail("must not send"))
    sid = web.auth.sessions()[0].id
    push.change(sid, "push-0001", sub())
    device = push.destinations()[0]
    with pytest.raises(PermanentError):
        push.deliver(device[:-1] + ("0" if device[-1] != "0" else "1"), "decisions")
    web.auth.revoke(sid)
    assert push.destinations() == []
    with pytest.raises(PermanentError):
        push.deliver(device, "decisions")


def test_web_triggered_results_use_web_reply_without_telegram_leakage():
    calls = []
    client = TelegramClient("synthetic", 2, transport=httpx.MockTransport(
        lambda request: calls.append(request) or httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})))
    client.route_background = True
    token = web_reply.set(True)
    try:
        client.send(2, "private details from a web confirmation")
    finally:
        web_reply.reset(token)
    assert calls == []
    client.send(2, "direct Telegram reply")
    assert len(calls) == 1
    client.close()


def test_regression_migration_of_an_interrupted_old_outbox_cannot_resend(configured):
    web, app = configured.web, configured.app
    web.store.save("telegram-outbox", {"schema_version": 1, "active": None, "entries": [{
        "id": "a" * 32, "kind": "proposal", "mail_id": MAIL1, "proposal_id": "elternabend",
        "version": 1, "status": "sending", "created_at": "2026-10-13T10:00:00+00:00"}]})
    svc = NotificationRuntime(app, web.site)
    svc.tick()
    item = next(item for item in svc.queue.state().entries.values() if item.reference == f"{MAIL1}:elternabend")
    assert item.status == "uncertain"
    svc.tick()
    assert svc.queue.state().entries[item.id].attempts == 0


def test_legacy_push_markers_are_imported_per_device_without_new_push(configured):
    from push_fakes import sub
    web, app = configured.web, configured.app
    sent = []
    app.settings.push.enabled = True
    push = PushService(web.store, web.auth, "mailto:synthetic@test", lambda **kw: sent.append(kw))
    push.change(web.auth.sessions()[0].id, "push-0001", sub())
    web.site.experience.push = push
    overview = web.site.views.overview()
    identities = [f"{row.mail_id}:{row.proposal_id}:{row.version}" for row in overview.open]
    identities += [f"{row.mail_id}:relevance:{row.version}" for row in overview.relevance]
    web.store.save("push-decisions", identities)
    svc = NotificationRuntime(app, web.site)
    svc.tick()
    assert sent == []
    assert {item.status for item in svc.queue.state().entries.values() if item.channel == "web_push"} == {"sent"}


def test_a_queued_old_relevance_question_is_pending_and_source_survives_a_full_migration(configured):
    from web_scenario import mail_id
    web, app = configured.web, configured.app
    app.settings.notifications = NotificationSettings(categories=Categories(decisions=["telegram"]),
        delivery={"max_pending": 1})
    web.store.save("telegram-outbox", {"schema_version": 1, "active": None, "entries": [
        {"id": "a" * 32, "kind": "relevance", "mail_id": mail_id(7), "version": 1,
         "sender": "synthetic", "subject": "synthetic", "status": "queued",
         "created_at": "2026-10-13T10:00:00+00:00"},
        {"id": "b" * 32, "kind": "proposal", "mail_id": MAIL1, "proposal_id": "elternabend", "version": 1,
         "status": "queued", "created_at": "2026-10-13T10:00:00+00:00"}]})
    svc = NotificationRuntime(app, web.site)
    assert len(svc.queue.state().entries) == 1 and len(svc.decisions()) > 1
    for _ in range(8):
        svc.tick()
    entry = next(item for item in svc.queue.state().entries.values() if item.reference == f"{mail_id(7)}:relevance")
    assert entry.status == "sent" and entry.attempts == 1
    assert len(svc.queue.state().entries) == len(svc.decisions())


def test_migration_after_a_prepared_backup_keeps_the_original_backup(configured):
    backup = {"schema_version": 1, "decision_markers": {}, "original": True}
    configured.web.store.save("notifications-backup", backup)
    svc = NotificationRuntime(configured.app, configured.web.site)
    svc.tick()
    assert configured.web.store.load("notifications-backup") == backup


def test_system_errors_are_deduplicated_and_follow_the_same_policy(runtime, monkeypatch):
    svc, web = runtime.runtime, runtime.web
    error = NS(mail_id=MAIL1, stage="relevance", cause="network")
    monkeypatch.setattr(web.site.views, "system", lambda now: NS(errors=[error]))
    svc.tick()
    svc.tick()
    entries = [item for item in svc.queue.state().entries.values() if item.category == "system_errors"]
    assert len(entries) == 1 and entries[0].status == "sent" and entries[0].attempts == 1
    assert not svc.relevant(entries[0].model_copy(update={"reference": "different"}))


def test_experience_uses_shared_delivery_without_running_old_schedulers(runtime):
    from mailhelp.experience import ExperienceRuntime
    experience = ExperienceRuntime(runtime.app, NS(site=runtime.web.site, auth=runtime.web.auth), None)
    experience.notifications = runtime.runtime
    experience.briefing.tick = lambda: pytest.fail("old briefing scheduler must not deliver")
    experience.tick()
    assert any(item.status == "sent" for item in runtime.runtime.queue.state().entries.values())


def test_a_push_subscription_renewed_while_sending_is_not_removed(runtime):
    from push_fakes import sub
    web = runtime.web
    sid = web.auth.sessions()[0].id
    renewed = sub()
    response = requests.Response()
    response.status_code = 410
    def failed(**kw):
        push.change(sid, "push-0002", renewed)
        raise WebPushException("gone", response=response)
    push = PushService(web.store, web.auth, "mailto:synthetic@test", failed)
    push.change(sid, "push-0001", sub())
    old = push.destinations()[0]
    with pytest.raises(PermanentError):
        push.deliver(old, "decisions")
    assert len(push.destinations()) == 1 and push.destinations()[0] != old


def test_regression_a_full_queue_with_new_results_still_delivers_existing_items(runtime):
    svc, web = runtime.runtime, runtime.web
    runtime.cfg.notifications.delivery.max_pending = 1
    assert any(item.status == "pending" for item in svc.queue.state().entries.values())
    sid = web.auth.sessions()[0].id
    command = ReviewCommand(kind=CommandKind.REJECT, source=CommandSource.WEB, actor="web:" + sid,
                            idempotency_key="action-001", mail_id=MAIL1, proposal_id="elternabend", version=1)
    entry, _ = web.commands.submit(command)
    web.commands.finish(entry.id, ReviewResult(status=ResultStatus.DONE, message="Synthetic result"))
    svc.tick()
    assert any(item.status == "sent" for item in svc.queue.state().entries.values())
    for _ in range(8):
        svc.tick()
    assert any(item.category == "action_results" and item.status == "sent"
               for item in svc.queue.state().entries.values())


def test_persistent_access_failure_is_not_repeated_and_recovery_cancels_deferred_notice(runtime):
    svc, store = runtime.runtime, runtime.app.store
    store.save("service-health", {"schema_version": 1, "version": 1, "errors": {"imap": "auth"}})
    svc.tick()
    svc.tick()
    entries = [item for item in svc.queue.state().entries.values() if item.reference == "service:imap"]
    assert len(entries) == 1 and entries[0].attempts == 1
    assert svc.relevant(entries[0])
    store.save("service-health", {"schema_version": 1, "version": 2, "errors": {"imap": "auth"}})
    assert not svc.relevant(entries[0])
    svc.tick()
    assert len([item for item in svc.queue.state().entries.values() if item.reference == "service:imap"]) == 2
    store.save("service-health", {"schema_version": 1, "version": 3, "errors": {}})
    assert not svc.relevant(entries[0])


def test_setup_remains_available_when_the_mailbox_cannot_authenticate(tmp_path, monkeypatch):
    import imaplib

    import yaml
    from shared_application import settings
    from shared_core import prompt_config

    from mailhelp.application import build_application
    from mailhelp.config import Secrets
    cfg = settings(tmp_path)
    cfg.web.enabled = True
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(cfg.model_dump(mode="json")), encoding="utf-8")
    secret = Secrets(**{name: "s" * 40 for name in Secrets.model_fields if name not in {"imap", "profiles"}},
                     imap={1: {"username": "s" * 40, "password": "s" * 40}})
    class Resource:
        def __init__(self, *args, **kw):
            pass
        def close(self):
            pass
    for name in ("OpenRouterClient", "HttpWriter", "GoogleOAuthTokenProvider"):
        monkeypatch.setattr(("mailhelp.external.providers." if name in MOVED_WRITERS else "mailhelp.composition.") + name, Resource)
    monkeypatch.setattr("mailhelp.composition.ImapReader",
                        lambda *args, **kw: (_ for _ in ()).throw(imaplib.IMAP4.error("private provider answer")))
    with build_application(cfg, secret, [], prompt_config(), "a" * 64, tmp_path, use_jev_relevance=False) as app:
        site = app.experience.site
        assert app.web is not None and site.setup_page.runtime.diagnostics.state().results["imap"].code == "auth"
        report = json.dumps(site.setup_page.runtime.diagnostics.report())
        assert "private provider answer" not in report
        for method in (app.imap.discover_since, app.imap.fetch_uid, app.imap.fetch_since,
                       app.imap.determine_start_uid):
            with pytest.raises(RuntimeError, match="nicht bereit"):
                method()
        assert app.store.load("service-health")["errors"] == {"imap": "auth"}
        app.notifications.tick()
        assert any(item.category == "system_errors" for item in app.notifications.queue.state().entries.values())


def test_telegram_results_reach_other_selected_channels_without_repeating_the_direct_reply(runtime):
    from push_fakes import sub
    web, app, svc = runtime.web, runtime.app, runtime.runtime
    sent = []
    app.settings.push.enabled = True
    app.settings.notifications.categories.decisions = []
    app.settings.notifications.categories.action_results = ["telegram", "web_push"]
    push = PushService(web.store, web.auth, "mailto:synthetic@test", lambda **kw: sent.append(kw))
    push.change(web.auth.sessions()[0].id, "push-0001", sub())
    web.site.experience.push = push
    command = ReviewCommand(kind=CommandKind.REJECT, source=CommandSource.TELEGRAM, actor="telegram:1:2",
                            idempotency_key="telegram-001", mail_id=MAIL1, proposal_id="elternabend", version=1)
    result = web.dialog.review.execute(command)
    assert result.status == ResultStatus.DONE and not web.commands.queued()
    before = list(web.telegram.sent)
    svc.tick()
    assert len(sent) == 1 and web.telegram.sent == before
    entries = [item for item in svc.queue.state().entries.values() if item.category == "action_results"]
    assert len(entries) == 1 and entries[0].channel == "web_push"
    web.dialog.review.execute(command)
    svc.tick()
    assert len(sent) == 1 and web.writer.created == 0


def test_completed_records_cannot_be_executed_or_overtake_pending_commands(runtime, monkeypatch):
    from mailhelp.review.inbox import CommandStatus
    web = runtime.web
    command = ReviewCommand(kind=CommandKind.REJECT, source=CommandSource.TELEGRAM, actor="telegram:1:2",
                            idempotency_key="telegram-001", mail_id=MAIL1, proposal_id="elternabend", version=1)
    entry = web.commands.record_completed(command, ReviewResult(status=ResultStatus.FAILED, message="Synthetic failure"))
    assert entry.status == CommandStatus.FAILED and entry.finished_at is not None
    assert web.commands.recover(lambda command: pytest.fail("completed command must not execute")) == 0
    assert web.commands.queued() == []
    assert web.commands.record_completed(command, ReviewResult(status=ResultStatus.DONE, message="replay")) == entry
    monkeypatch.setattr("mailhelp.review.inbox.MAX_QUEUED", 0)
    other = command.model_copy(update={"idempotency_key": "telegram-002"})
    entry = web.commands.record_completed(other, ReviewResult(status=ResultStatus.UNAUTHORIZED, message="No session"))
    assert entry.status == CommandStatus.REJECTED


def test_configuration_results_are_not_copied_into_action_result_notifications(runtime):
    from mailhelp.configuration import AdminCommand, AdminKind
    web, svc = runtime.web, runtime.runtime
    before = web.store.load("command-inbox")
    command = AdminCommand(kind=AdminKind.SETTINGS, actor="web:" + web.auth.sessions()[0].id,
                           idempotency_key="settings-001", expected_hash="a" * 64, patch={}, acknowledged=True)
    svc.completed(command, ReviewResult(status=ResultStatus.DONE, message="settings saved"))
    assert web.store.load("command-inbox") == before


def test_regression_migration_metadata_does_not_keep_old_mail_content_forever(configured):
    web, app = configured.web, configured.app
    private = "PRIVATE_MAIL_CONTENT_NO_RETENTION_COPY"
    web.store.save("telegram-outbox", {"schema_version": 1, "active": None, "entries": [{
        "id": "a" * 32, "kind": "message", "text": private, "status": "queued",
        "created_at": "2026-10-13T10:00:00+00:00"}]})
    NotificationRuntime(app, web.site)
    assert private not in json.dumps(web.store.load("notifications-backup"))
    assert private not in json.dumps(web.store.load("notification-queue"))


def test_several_mailboxes_are_built_labelled_and_fail_independently(tmp_path, monkeypatch):
    """Planung 3.1: one reader per mailbox; labels in web and Telegram; one failure stays local."""
    import imaplib

    import yaml
    from shared_application import settings
    from shared_core import prompt_config

    from mailhelp.application import build_application
    from mailhelp.config import Secrets, Settings
    from mailhelp.imap import account_id
    data = settings(tmp_path).model_dump(mode="json")
    data["web"]["enabled"] = True
    data["imap"] = {"mailboxes": [
        {"id": 1, "label": "Privat", "host": "a.test", "port": 993, "folders": ["INBOX"]},
        {"id": 2, "label": "Arbeit", "host": "b.test", "port": 993, "folders": ["INBOX"]}]}
    cfg = Settings.model_validate(data)
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(cfg.model_dump(mode="json")), encoding="utf-8")
    secret = Secrets(**{name: "s" * 40 for name in Secrets.model_fields if name not in {"imap", "profiles"}},
                     imap={1: {"username": "privat", "password": "p" * 8}, 2: {"username": "arbeit", "password": "q" * 8}})

    class Resource:
        def __init__(self, *args, **kw):
            pass

        def close(self):
            pass

    class Reader(Resource):
        def __init__(self, host, port, user, *args, **kw):
            if host == "a.test":
                raise imaplib.IMAP4.error("private provider answer")
            self.account_id = account_id(host, port, user)
    for name in ("OpenRouterClient", "HttpWriter", "GoogleOAuthTokenProvider"):
        monkeypatch.setattr(("mailhelp.external.providers." if name in MOVED_WRITERS else "mailhelp.composition.") + name, Resource)
    monkeypatch.setattr("mailhelp.composition.ImapReader", Reader)
    with build_application(cfg, secret, [], prompt_config(), "a" * 64, tmp_path, use_jev_relevance=False) as app:
        assert [source.mailbox.label for source in app.sources] == ["Privat", "Arbeit"]
        assert app.imap is app.sources[0].reader and isinstance(app.sources[1].reader, Reader)
        site = app.experience.site
        expected = {account_id("a.test", 993, "privat"): (1, "Privat"), account_id("b.test", 993, "arbeit"): (2, "Arbeit")}
        assert site.views.mailboxes == site.archive.queries.mailboxes == expected
        assert app.dialog.presenter.mailbox_of(NS(source_mail_id="f" * 24)) == ""
        assert app.store.load("service-health")["errors"] == {"imap": "auth"}
