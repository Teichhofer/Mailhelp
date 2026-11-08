"""Synthetic IMAP delivery: durable MIME, account binding and crash reconciliation."""
import imaplib
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from email import policy
from email.parser import BytesParser
from types import SimpleNamespace as NS

import pytest
from pydantic import SecretStr

from mailhelp.config import ImapCredentials, Secrets
from mailhelp.mailbox.imap import FetchedMail
from mailhelp.notifications.briefing_drafts import BriefingDraftService, briefing_message
from mailhelp.notifications.briefing_identity import is_own_briefing
from mailhelp.notifications.briefing_scheduler import STATE, BriefingScheduler, BriefingState
from mailhelp.notifications.drafts import DraftTarget
from mailhelp.processing.orchestrator import Orchestrator
from mailhelp.runtime.experience import ExperienceRuntime
from tests.fakes.shared_services import AnalyzerStub, Notify


class Crash(BaseException):
    pass


class Imap:
    def __init__(self):
        self.writes, self.messages, self.selected = [], set(), []
        self.result, self.on_search = "OK", lambda: None

    def select(self, folder, readonly):
        assert readonly
        self.selected.append(folder)
        return "OK", []

    def uid(self, *args):
        self.on_search()
        return "OK", [b"91" if args[-1] in self.messages else b""]

    def append(self, *args):
        self.writes.append(args)
        if self.result == "OK" or isinstance(self.result, (OSError, EOFError, imaplib.IMAP4.abort, Crash)):
            self.messages.add(BytesParser(policy=policy.default).parsebytes(args[-1])["Message-ID"])
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result, []


@pytest.fixture
def delivery(configured):
    cfg, web = configured.cfg, configured.web
    for name in web.store.names("mail-") + web.store.names("proposal-"):
        web.store.delete(name)
    cfg.timezone = "Europe/Berlin"
    cfg.briefings.enabled, cfg.briefings.skip_empty, cfg.test_mode = True, False, False
    cfg.briefings.times = ["07:00"]
    imap, opens, account = Imap(), [], ["1" * 24]
    @contextmanager
    def connect():
        opens.append(True)
        yield imap
    target = [DraftTarget(connect, "Me <me@example.test>", "Drafts")]
    service = BriefingDraftService(web.store, lambda: cfg, web.site.views,
                                  lambda number: (account[0], target[0]), lambda: "https://mailhelp.example.test")
    now = [datetime(2026, 11, 8, 6, tzinfo=UTC)]
    scheduler = BriefingScheduler(web.store, lambda: cfg, service.deliver, lambda: now[0])
    return NS(cfg=cfg, store=web.store, service=service, scheduler=scheduler,
              imap=imap, opens=opens, target=target, account=account, now=now)


def run_of(d):
    return next(iter(d.store.load_model(STATE, BriefingState).runs.values()))


def retry(d):
    d.now[0] += timedelta(minutes=1)
    BriefingScheduler(d.store, lambda: d.cfg, d.service.deliver, lambda: d.now[0]).tick()


def test_multipart_draft_has_own_recipient_flags_and_one_append_after_restart(delivery):
    d = delivery
    d.scheduler.tick()
    retry(d)
    assert len(d.imap.writes) == len(d.opens) == 1
    folder, flags, stamp, raw = d.imap.writes[0]
    assert (folder, flags, stamp) == ("Drafts", r"(\Draft \Seen)", None)
    message = BytesParser(policy=policy.default).parsebytes(raw)
    assert message["To"] == "me@example.test" and message["From"] == "Me <me@example.test>"
    assert message["Subject"] == "[Mailhelp Briefing 07:00] 0 Termine, 0 Aufgaben"
    assert message["Message-ID"] == f"<mailhelp-briefing-{run_of(d).id}@draft.local>"
    assert {part.get_content_type() for part in message.iter_parts()} == {"text/plain", "text/html"}
    assert "Alles ruhig" in message.get_body(preferencelist=("plain",)).get_content()
    assert run_of(d).snapshot is None and run_of(d).status == "saved"


@pytest.mark.parametrize("mode,expected", [("empty", "skipped_empty"), ("test", "simulated")])
def test_empty_and_test_mode_never_open_an_imap_connection(delivery, mode, expected):
    d = delivery
    d.cfg.briefings.skip_empty = mode == "empty"
    d.cfg.test_mode = mode == "test"
    d.scheduler.tick()
    assert run_of(d).status == expected and not d.opens


@pytest.mark.parametrize("result", [OSError("synthetic private"), EOFError(), imaplib.IMAP4.abort(), Crash()])
def test_lost_reply_or_process_crash_recovers_by_message_id_without_second_append(delivery, result):
    d = delivery
    d.imap.result = result
    if isinstance(result, Crash):
        with pytest.raises(Crash):
            d.scheduler.tick()
    else:
        d.scheduler.tick()
    original = run_of(d)
    assert original.snapshot and original.draft["status"] == "uncertain"
    d.target[0] = d.target[0]._replace(folder="Changed")
    d.imap.result = "OK"
    retry(d)
    assert run_of(d).status == "saved" and len(d.imap.writes) == 1
    assert d.imap.selected == ["Drafts", "Drafts"]


@pytest.mark.parametrize("result", ["NO", imaplib.IMAP4.error("synthetic refusal")])
def test_refused_append_can_retry_the_same_frozen_snapshot(delivery, result):
    d = delivery
    d.imap.result = result
    d.scheduler.tick()
    original = run_of(d)
    assert original.status == "failed" and original.snapshot
    d.imap.messages.clear()  # An explicit refusal did not store anything.
    d.imap.result = "OK"
    d.service.aggregate.collect = lambda *args: pytest.fail("must reuse snapshot")
    retry(d)
    assert run_of(d).status == "saved" and len(d.imap.writes) == 2
    messages = [BytesParser(policy=policy.default).parsebytes(write[-1]) for write in d.imap.writes]
    assert messages[0]["Message-ID"] == messages[1]["Message-ID"]
    assert [part.get_content() for part in messages[0].iter_parts()] == [
        part.get_content() for part in messages[1].iter_parts()]


@pytest.mark.parametrize("change", ["disabled", "web", "time", "mailbox", "account", "missing"])
def test_changed_settings_or_account_before_append_prevent_writes(delivery, change):
    d = delivery
    def changed():
        if change == "disabled": d.cfg.briefings.enabled = False
        elif change == "web": d.cfg.web.enabled = False
        elif change == "time": d.cfg.briefings.times = ["18:00"]
        elif change == "mailbox": d.cfg.briefings.mailbox = 99
        elif change == "account": d.account[0] = "replaced-account"
        else: d.service.target = lambda number: None
    d.imap.on_search = changed
    d.scheduler.tick()
    assert not d.imap.writes and run_of(d).status == "uncertain"
    assert run_of(d).error in {"PermissionError", "ValueError"}


@pytest.mark.parametrize("address", ["invalid", "me@", "me@example.test\r\nBcc: other@example.test"])
def test_invalid_own_address_is_never_appended(delivery, address):
    d = delivery
    d.target[0] = d.target[0]._replace(sender=address)
    d.scheduler.tick()
    assert run_of(d).status == "failed" and not d.opens


def test_independent_runtime_uses_current_mailbox_credentials_and_folder(profiled, monkeypatch):
    app, web = profiled.app, profiled.web
    app.settings.web.enabled = True
    app.settings.smart_reply = False
    secrets = Secrets.model_construct(imap={number: ImapCredentials(
        username=f"me{number}@example.test", password=SecretStr("synthetic")) for number in (1, 2)})
    runtime = ExperienceRuntime(app, NS(site=web.site, auth=web.auth), secrets)
    assert web.site.experience.drafts is None
    seen, server = [], Imap()
    @contextmanager
    def reader(settings, credentials, mailbox):
        seen.append((settings, credentials, mailbox.id))
        yield NS(connection=server)
    monkeypatch.setattr("mailhelp.runtime.experience._reader", reader)
    app.settings.drafts.folder = "My Drafts"
    account, target = runtime.briefing_target(2)
    assert target.sender == "me2@example.test" and target.folder == "My Drafts"
    with target.connection() as connection:
        assert connection is server
    assert seen == [(app.settings, secrets, 2)]
    app.settings.drafts.folder = None
    assert runtime.briefing_target(1)[1].folder == app.settings.imap.mailbox(1).drafts_folder
    app.settings.imap.mailbox(2).enabled = False
    assert runtime.briefing_target(2) is runtime.briefing_target(99) is None
    app.settings.briefings.enabled, app.settings.briefings.skip_empty = True, False
    app.settings.test_mode = True
    runtime.mailbox_briefings.clock = lambda: datetime(2026, 11, 8, 19, tzinfo=UTC)
    runtime.tick()
    assert all(run.status == "simulated" for run in web.store.load_model(STATE, BriefingState).runs.values())


def test_own_briefing_in_scanned_drafts_folder_never_becomes_a_new_task(delivery):
    d = delivery
    d.scheduler.tick()
    raw = d.imap.writes[0][-1]
    notify = Notify()
    processor = Orchestrator(AnalyzerStub("relevant"), d.store, notify, 1, [], 1024 * 1024)
    result = processor.process(FetchedMail("Drafts", 1, 91, raw, d.account[0]))
    assert result["steps"]["completion"] == "completed"
    assert result["relevance"]["decision"] == "irrelevant"
    assert result["proposals"] == [] and result["llm_call_ids"] == [] and not notify.messages


@pytest.mark.parametrize("changed", ["content", "account"])
def test_subject_or_message_id_alone_cannot_hide_an_incoming_mail(delivery, changed):
    d = delivery
    d.scheduler.tick()
    raw, account = d.imap.writes[0][-1], d.account[0]
    if changed == "content":
        raw += b"\r\nAdded incoming content\r\n"
    else:
        account = "2" * 24
    processor = Orchestrator(AnalyzerStub("relevant"), d.store, Notify(), 1, [], 1024 * 1024)
    result = processor.process(FetchedMail("Drafts", 1, 92, raw, account))
    assert result["relevance"]["decision"] == "relevant" and result["proposals"] and result["llm_call_ids"]


def test_own_briefing_recognition_survives_restart_after_mime_preparation(delivery, monkeypatch):
    d = delivery
    d.scheduler.tick()
    processor = Orchestrator(AnalyzerStub("relevant"), d.store, Notify(), 1, [], 1024 * 1024)
    fetched = FetchedMail("Drafts", 1, 93, d.imap.writes[0][-1], d.account[0])
    def crash(run):
        raise Crash()
    with monkeypatch.context() as patch:
        patch.setattr(processor.pipeline, "_relevance", crash)
        with pytest.raises(Crash):
            processor.process(fetched)
    result = processor.process(FetchedMail("Drafts", 1, 93, b"", d.account[0]))
    assert result["steps"]["completion"] == "completed" and result["llm_call_ids"] == []


def test_corrupt_briefing_state_cannot_filter_untrusted_mail_and_is_not_modified(delivery):
    d = delivery
    path = d.store.directory / (STATE + ".json")
    path.write_bytes(b"{broken")
    assert not is_own_briefing(d.store, d.account[0], b"synthetic")
    assert path.read_bytes() == b"{broken"


def test_absent_briefing_state_never_filters_incoming_mail(delivery):
    assert not is_own_briefing(delivery.store, delivery.account[0], b"synthetic incoming mail")
