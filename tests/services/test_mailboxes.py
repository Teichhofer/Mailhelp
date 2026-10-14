"""Several mailboxes in one service (Planung 3.1, phase 2): selection, queues, recovery, isolation."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from threading import Event

import pytest
from shared_application import Log, Orch, Store, Telegram
from shared_application import settings as app_settings

from mailhelp.application import Application
from mailhelp.composition import _FailedAccessAdapter
from mailhelp.config import Settings
from mailhelp.imap import FetchedMail, MailCandidate
from mailhelp.mailbox_run import MailboxSource, _checkpoint_name, _RunSummary
from mailhelp.models import MailRunState, MailState
from mailhelp.orchestrator import ProcessingOutcome, ProcessingResult

STAMP = datetime(2026, 10, 1, tzinfo=UTC)


class Reader:
    """A mailbox with fixed (uid, hour) messages in INBOX; records every body fetch."""

    def __init__(self, account: str, messages: list[tuple[int, int]]):
        self.account_id, self.messages = account * 24, messages
        self.last_uidvalidity, self.fetches, self.discoveries = None, [], 0

    def discover_since(self, folder, start, expected, ranges):
        self.discoveries += 1
        self.last_uidvalidity = 7
        done = {uid for low, high in ranges for uid in range(low, high + 1)}
        return [MailCandidate(folder, 7, uid, self.account_id, STAMP + timedelta(hours=hour))
                for uid, hour in self.messages if uid > start and uid not in done]

    def fetch_uid(self, folder, uid, uidvalidity):
        self.fetches.append(uid)
        return FetchedMail(folder, uidvalidity, uid, b"x", self.account_id, STAMP)

    def check_access(self, folders):
        if self.account_id.startswith("b"):
            raise RuntimeError("Anmeldung abgelehnt")


class SeenOrch(Orch):
    def process(self, mail):
        self.seen.append((mail.account_id[0], mail.uid))
        return ProcessingResult(ProcessingOutcome.COMPLETED, {})


@pytest.fixture
def two_mailboxes(tmp_path, monkeypatch):
    data = app_settings(tmp_path).model_dump(mode="json")
    data["imap"] = {"batch_size": 25, "global_newest_first": True, "mailboxes": [
        {"id": 1, "label": "Privat", "host": "a", "port": 993, "folders": ["INBOX"]},
        {"id": 2, "label": "Arbeit", "host": "b", "port": 993, "folders": ["INBOX"]}]}
    return Settings.model_validate(data)


def service(cfg: Settings, readers: list, store=None, orch=None) -> Application:
    sources = [MailboxSource(mailbox, reader) for mailbox, reader in zip(cfg.imap.mailboxes, readers, strict=True)]
    return Application(cfg, store or Store(), Log(), readers[0], object(), object(), Telegram([]), object(), object(),
                       orch or SeenOrch(), Event(), sources=sources)


def test_one_shared_budget_selects_the_newest_mail_of_all_mailboxes(two_mailboxes):
    private, work = Reader("a", [(1, 1), (2, 3)]), Reader("b", [(1, 2), (2, 4)])
    app = service(two_mailboxes, [private, work])
    assert len(app.mailbox.poll(max_mails=3)) == 3
    # Selected globally (b2, a2, b1); processed mailbox by mailbox in configuration order.
    assert app.orchestrator.seen == [("a", 2), ("b", 2), ("b", 1)]
    runs = {reader: MailRunState.model_validate(app.store.values[f"mail-run-{reader.account_id}"])
            for reader in (private, work)}
    assert [entry.uid for entry in runs[private].entries] == [2]
    assert [entry.uid for entry in runs[work].entries] == [2, 1]
    # Equal folder and UID in both mailboxes are separate identities with separate checkpoints.
    for reader, ranges in ((private, [(2, 2)]), (work, [(1, 2)])):
        assert app.store.values[_checkpoint_name(reader.account_id, "INBOX")]["completed_uid_ranges"] == ranges
    assert len(app.mailbox.poll(max_mails=3)) == 1
    assert app.orchestrator.seen[-1] == ("a", 1)


def test_an_unfinished_queue_continues_before_any_mailbox_is_searched_again(two_mailboxes):
    private, work = Reader("a", [(1, 1)]), Reader("b", [(1, 2), (2, 3)])
    stopped = SeenOrch()
    app = service(two_mailboxes, [private, work], orch=stopped)
    original = stopped.process

    def stop_after_first(mail):
        result = original(mail)
        app.stop_event.set()
        return result
    stopped.process = stop_after_first
    app.mailbox.poll(max_mails=3)
    assert stopped.seen == [("a", 1)] and private.discoveries == work.discoveries == 1
    app.stop_event.clear()
    stopped.process = original
    assert len(app.mailbox.poll(max_mails=3)) == 2
    # The stored queue of mailbox 2 was resumed without a new search.
    assert stopped.seen == [("a", 1), ("b", 2), ("b", 1)] and work.discoveries == 1


def test_a_mailbox_that_cannot_connect_does_not_stop_the_others(two_mailboxes):
    work = Reader("b", [(1, 1)])
    broken = _FailedAccessAdapter(RuntimeError("TLS-Fehler"), "a" * 24)
    app = service(two_mailboxes, [broken, work])
    assert len(app.mailbox.poll(max_mails=5)) == 1
    assert app.orchestrator.seen == [("b", 1)]
    failure = next(fields for (_, _, event), fields in app.logger.events if event == "poll_failed")
    assert failure["mailbox"] == 1 and "TLS" not in str(app.store.values)


def test_resumed_mail_uses_its_own_mailbox_and_a_removed_mailbox_waits(two_mailboxes):
    private, work = Reader("a", []), Reader("b", [])
    store = Store()
    for name, account in (("1" * 24, "b" * 24), ("2" * 24, "c" * 24)):
        state = MailState(id=name, config_fingerprint="0" * 64,
                          imap={"account_id": account, "folder": "INBOX", "uidvalidity": 7, "uid": 5})
        store.save(f"mail-{name}", state.model_dump(mode="json"))
    app = service(two_mailboxes, [private, work], store=store)
    app.mailbox.poll()
    app.mailbox.poll()
    assert work.fetches == [5, 5] and private.fetches == []
    unavailable = [fields for (_, _, event), fields in app.logger.events if event == "mailbox_unavailable"]
    assert unavailable == [{"account_id": "c" * 24}]


def test_access_check_and_run_summary_name_each_mailbox(two_mailboxes):
    private, work = Reader("a", [(1, 1)]), Reader("b", [(1, 2)])
    app = service(two_mailboxes, [private, work])
    app.openrouter = app.telegram = app.todoist = app.calendar = type(
        "Ok", (), {"check_access": lambda self: None, "service_name": "OpenRouter",
                   "send": lambda self, *args: None})()
    results = app.check_access()
    assert results["IMAP Postfach 1 (Privat)"] is None
    assert "Anmeldung abgelehnt" in results["IMAP Postfach 2 (Arbeit)"]
    app.telegram = Telegram([])
    app.mailbox.poll(max_mails=1)
    app._finish(max_mails=1)
    (_, text), = app.telegram.sent
    assert text.startswith("✅ Lauf abgeschlossen: 1 von 1 Mails geprüft") and text.endswith("\nArbeit: 1 von 1 Mails geprüft")


def test_one_mailbox_keeps_the_single_summary_line(tmp_path):
    summary = _RunSummary.from_runs([None])
    assert summary == _RunSummary() and not summary.run_complete
    app = Application(app_settings(tmp_path), Store(), Log(), Reader("a", []), object(), object(), Telegram([]),
                      object(), object(), Orch(), Event())
    assert app._mailbox_lines([None]) == ""
