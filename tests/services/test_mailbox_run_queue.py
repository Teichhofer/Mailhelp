"""Mailbox runs: global order, budgets and the materialized UID queue."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from mailhelp.domain.run import MailRunCounters, MailRunEntry, MailRunState
from mailhelp.mailbox.imap import FetchedMail, MailCandidate
from mailhelp.mailbox.mailbox_run import _checkpoint_name, _RunSummary
from mailhelp.processing.orchestrator import ProcessingOutcome, ProcessingResult
from tests.fakes.shared_application import Orch, Store, Telegram, app

# Since 2.3 the writers are built in mailhelp.external.providers.


def test_global_mailbox_order_and_max_mail_budget(tmp_path):
    stamp = datetime(2026, 1, 1, tzinfo=UTC)

    class GlobalImap:
        account_id = "0" * 24
        last_uidvalidity = None
        def __init__(self): self.fetches = []
        def discover_since(self, folder, start, expected, ranges):
            self.last_uidvalidity = 7
            offsets = {"INBOX": [(1, 1)], "Archive": [(2, 3), (3, 2)]}[folder]
            return [MailCandidate(folder, 7, uid, self.account_id,
                                  stamp + timedelta(hours=hour))
                    for uid, hour in offsets]
        def fetch_uid(self, folder, uid, validity):
            self.fetches.append((folder, uid, validity))
            return FetchedMail(folder, validity, uid, b"x", self.account_id, stamp)

    imap = GlobalImap()
    service = app(tmp_path, imap, Telegram([]), Orch(), folders=("INBOX", "Archive"),
                  global_newest_first=True)
    results = service.mailbox.poll(max_mails=2)

    assert len(results) == 2
    assert imap.fetches == [("Archive", 2, 7), ("Archive", 3, 7)]
    assert service.orchestrator.seen == [2, 3]
    assert service.store.values[_checkpoint_name(imap.account_id, "Archive")][
        "completed_uid_ranges"
    ] == [(2, 3)]


def test_exhausted_uid_halts_queue_and_restart_retries_same_item(tmp_path):
    stamp = datetime(2026, 1, 1, tzinfo=UTC)

    class Reader:
        account_id = "0" * 24
        last_uidvalidity = 7
        def __init__(self, fail=True):
            self.fetches = []
            self.fail = fail
        def discover_since(self, folder, *_args):
            return [MailCandidate(folder, 7, uid, self.account_id, stamp)
                    for uid in (2, 3)]
        def fetch_uid(self, folder, uid, validity):
            self.fetches.append(uid)
            if uid == 2 and self.fail:
                raise RuntimeError("private server diagnostic")
            return FetchedMail(folder, validity, uid, b"x", self.account_id, stamp)

    reader, store = Reader(), Store()
    service = app(tmp_path, reader, Telegram([]), Orch(), store=store,
                  global_newest_first=True)

    results = service.mailbox.poll(max_mails=2)

    run = MailRunState.model_validate(store.values[f"mail-run-{reader.account_id}"])
    assert [entry.status.value for entry in run.entries] == ["processing", "queued"]
    assert [entry.failure_code for entry in run.entries] == [None, None]
    assert "private server diagnostic" not in str(store.values[f"mail-run-{reader.account_id}"])
    assert reader.fetches == [2]
    assert service.orchestrator.seen == []
    assert results == []
    assert service.mailbox.poll(max_mails=2) == []
    assert reader.fetches == [2]

    restarted_reader = Reader(fail=False)
    restarted = app(tmp_path, restarted_reader, Telegram([]), Orch(), store=store,
                    global_newest_first=True)
    assert len(restarted.mailbox.poll(max_mails=2)) == 2
    assert restarted_reader.fetches == [2, 3]
    assert restarted.orchestrator.seen == [2, 3]
    with pytest.raises(ValueError, match="Fehlermerkmal"):
        MailRunEntry(account_id="a", folder="INBOX", uidvalidity=1, uid=1,
                     status="completed", analysis_terminal="completed",
                     failure_code="processing_failed")


def test_terminal_processing_failure_is_persisted_and_counted(tmp_path):
    stamp = datetime(2026, 1, 1, tzinfo=UTC)

    class Reader:
        account_id = "0" * 24
        last_uidvalidity = 7
        def discover_since(self, folder, *_args):
            return [MailCandidate(folder, 7, uid, self.account_id, stamp)
                    for uid in (2, 3)]
        def fetch_uid(self, folder, uid, validity):
            return FetchedMail(folder, validity, uid, b"x", self.account_id, stamp)

    class Failed(Orch):
        def process(self, mail):
            self.seen.append(mail.uid)
            if mail.uid == 2:
                return ProcessingResult(ProcessingOutcome.FAILED, {
                    "error": {"code": "provider_response_invalid",
                              "reason": "output_token_limit", "retryable": True},
                })
            return ProcessingResult(ProcessingOutcome.COMPLETED, {})

    service = app(tmp_path, Reader(), Telegram([]), Failed(),
                  global_newest_first=True)

    results = service.mailbox.poll(max_mails=2)

    run = service.store.load_model("mail-run-" + "0" * 24, MailRunState)
    assert len(results) == 2
    assert service.orchestrator.seen == [2, 3]
    assert [entry.status.value for entry in run.entries] == ["failed", "completed"]
    assert run.entries[0].analysis_terminal == "failed"
    assert run.entries[0].failure_code == "processing_failed"
    assert run.counters.failed == 1
    assert _RunSummary.from_run(run) == _RunSummary(
        discovered=2, processed=2, relevant=1, failed=1, run_complete=True,
    )
    assert _checkpoint_name(service.imap.account_id, "INBOX") in service.store.values
    assert service.store.values[_checkpoint_name(
        service.imap.account_id, "INBOX"
    )]["completed_uid_ranges"] == [(3, 3)]


def test_persistent_run_records_duplicate_and_irrelevant_analysis(tmp_path):
    stamp = datetime(2026, 1, 1, tzinfo=UTC)

    class Reader:
        account_id = "0" * 24
        last_uidvalidity = 7
        def discover_since(self, folder, *_args):
            return [MailCandidate(folder, 7, uid, self.account_id, stamp)
                    for uid in (1, 2)]
        def fetch_uid(self, folder, uid, validity):
            return FetchedMail(folder, validity, uid, b"x", self.account_id, stamp)

    class Classified(Orch):
        def process(self, mail):
            state = ({"duplicate": {"outcome": "duplicate", "previous_mail_id": "a"}}
                     if mail.uid == 1 else
                     {"relevance": {"decision": "irrelevant"}})
            return ProcessingResult(ProcessingOutcome.COMPLETED, state)

    service = app(tmp_path, Reader(), Telegram([]), Classified(),
                  global_newest_first=True)
    service.mailbox.poll(max_mails=2)
    run = service.store.load_model("mail-run-" + "0" * 24, MailRunState)
    assert [entry.analysis_terminal for entry in run.entries] == [
        "duplicate", "irrelevant"
    ]


def test_repeated_global_max_mail_runs_continue_with_next_newest_batch(tmp_path):
    """A persisted newest-first batch must not hide the older backlog."""
    stamp = datetime(2026, 1, 1, tzinfo=UTC)

    class GlobalBacklogImap:
        account_id = "0" * 24
        last_uidvalidity = 7

        def __init__(self):
            self.fetches = []

        def discover_since(self, folder, start, expected, ranges):
            assert (folder, start, expected) == ("INBOX", 0, 7)
            return [
                MailCandidate(folder, 7, uid, self.account_id,
                              stamp + timedelta(seconds=uid))
                for uid in range(1, 206)
                if not any(first <= uid <= last for first, last in ranges)
            ]

        def fetch_uid(self, folder, uid, validity):
            self.fetches.append(uid)
            return FetchedMail(folder, validity, uid, b"x", self.account_id, stamp)

    key = _checkpoint_name("0" * 24, "INBOX")
    store = Store({key: {"uidvalidity": 7, "uid": 0, "start_uid": 0}})
    reader = GlobalBacklogImap()

    first = app(tmp_path, reader, Telegram([]), Orch(), store=store,
                global_newest_first=True)
    assert len(first.mailbox.poll(max_mails=100)) == 100
    assert reader.fetches == list(range(205, 105, -1))

    restarted = app(tmp_path, reader, Telegram([]), Orch(), store=store,
                    global_newest_first=True)
    assert len(restarted.mailbox.poll(max_mails=100)) == 100
    assert reader.fetches[100:] == list(range(105, 5, -1))
    assert store.values[key]["completed_uid_ranges"] == [(6, 205)]


@pytest.mark.parametrize(("available", "maximum", "expected"), ((86, 100, 86), (150, 100, 100)))
def test_run_materializes_exact_bounded_uid_queue_before_fetch(tmp_path, available, maximum, expected):
    stamp = datetime(2026, 1, 1, tzinfo=UTC)

    class Reader:
        account_id = "0" * 24
        last_uidvalidity = 7
        def __init__(self): self.fetches = []
        def discover_since(self, folder, *_args):
            return [MailCandidate(folder, 7, uid, self.account_id, stamp)
                    for uid in range(1, available + 1)]
        def fetch_uid(self, folder, uid, validity):
            run = MailRunState.model_validate(store.values[f"mail-run-{self.account_id}"])
            assert len(run.entries) == expected
            assert run.counters.processing == 1
            self.fetches.append(uid)
            return FetchedMail(folder, validity, uid, b"x", self.account_id, stamp)

    store = Store()
    reader = Reader()
    service = app(tmp_path, reader, Telegram([]), Orch(), store=store,
                  global_newest_first=True)

    assert len(service.mailbox.poll(max_mails=maximum)) == expected
    run = MailRunState.model_validate(store.values[f"mail-run-{reader.account_id}"])
    assert run.max_mails == maximum
    assert run.counters.completed == expected
    assert len({entry.key for entry in run.entries}) == expected


def test_interrupted_batch_resumes_fixed_queue_without_rediscovery_or_reanalysis(tmp_path):
    stamp = datetime(2026, 1, 1, tzinfo=UTC)

    class Crash(BaseException):
        pass

    class Reader:
        account_id = "0" * 24
        last_uidvalidity = 7
        def __init__(self):
            self.discoveries = 0
            self.fetches = []
        def discover_since(self, folder, *_args):
            self.discoveries += 1
            return [MailCandidate(folder, 7, uid, self.account_id, stamp)
                    for uid in (1, 2, 2, 3)]
        def fetch_uid(self, folder, uid, validity):
            self.fetches.append(uid)
            return FetchedMail(folder, validity, uid, b"x", self.account_id, stamp)

    class CrashOnTwo(Orch):
        def process(self, mail):
            self.seen.append(mail.uid)
            if mail.uid == 2:
                raise Crash()
            return ProcessingResult(ProcessingOutcome.COMPLETED, {})

    store = Store()
    reader = Reader()
    first = app(tmp_path, reader, Telegram([]), CrashOnTwo(), store=store,
                global_newest_first=True)
    with pytest.raises(Crash):
        first.mailbox.poll(max_mails=3)
    run_name = f"mail-run-{reader.account_id}"
    interrupted = MailRunState.model_validate(store.values[run_name])
    assert [entry.status for entry in interrupted.entries] == ["completed", "processing", "queued"]

    restarted = app(tmp_path, reader, Telegram([]), Orch(), store=store,
                    global_newest_first=True)
    assert len(restarted.mailbox.poll(max_mails=3)) == 2
    assert reader.discoveries == 1
    assert restarted.orchestrator.seen == [2, 3]
    assert reader.fetches == [1, 2, 2, 3]
    completed = MailRunState.model_validate(store.values[run_name])
    assert completed.counters.completed == 3


def test_run_model_rejects_inconsistent_terminals_identity_time_and_counters():
    with pytest.raises(ValueError, match="Analysezustand"):
        MailRunEntry(account_id="a", folder="INBOX", uidvalidity=1, uid=1,
                     status="completed")
    with pytest.raises(ValueError, match="Benutzeraktion"):
        MailRunEntry(account_id="a", folder="INBOX", uidvalidity=1, uid=1,
                     status="completed", analysis_terminal="completed",
                     user_action_open=True)
    queued = MailRunEntry(account_id="a", folder="INBOX", uidvalidity=1, uid=1,
                          status="queued")
    base = dict(run_id="00000000-0000-0000-0000-000000000001", max_mails=1,
                entries=[queued], counters=MailRunCounters(queued=1))
    with pytest.raises(ValueError, match="UTC-Offset"):
        MailRunState(created_at=datetime(2026, 1, 1), **base)
    with pytest.raises(ValueError, match="doppelten"):
        MailRunState(created_at=datetime.now(UTC), **{**base, "entries": [queued, queued]})
    with pytest.raises(ValueError, match="Zähler"):
        MailRunState(created_at=datetime.now(UTC),
                     **{**base, "counters": MailRunCounters()})
    assert MailRunState(created_at=datetime.now(UTC), **base).run_complete is False
    terminal = MailRunEntry(
        account_id="a", folder="INBOX", uidvalidity=1, uid=1,
        status="completed", analysis_terminal="completed",
    )
    assert MailRunState(
        created_at=datetime.now(UTC),
        **{**base, "entries": [terminal], "counters": MailRunCounters(completed=1)},
    ).run_complete is True


def test_reconnectable_timeout_resumes_same_materialized_queue(tmp_path):
    """Fall D: reconnecting must neither rediscover nor replace the fixed queue."""
    stamp = datetime(2026, 1, 1, tzinfo=UTC)

    class Reader:
        account_id = "0" * 24
        last_uidvalidity = 7
        def __init__(self, timeout=False):
            self.timeout=timeout
            self.discoveries=0
            self.fetches=[]
        def discover_since(self, folder, *_args):
            self.discoveries += 1
            return [MailCandidate(folder, 7, uid, self.account_id, stamp) for uid in (1, 2, 3)]
        def fetch_uid(self, folder, uid, validity):
            self.fetches.append(uid)
            if self.timeout and uid == 3:
                raise TimeoutError("synthetic reconnectable timeout")
            return FetchedMail(folder, validity, uid, b"x", self.account_id, stamp)

    store = Store()
    disconnected = Reader(timeout=True)
    first = app(tmp_path, disconnected, Telegram([]), Orch(), store=store,
                global_newest_first=True)
    with pytest.raises(TimeoutError, match="reconnectable"):
        first.mailbox.poll(max_mails=100)

    run_name = f"mail-run-{disconnected.account_id}"
    interrupted = MailRunState.model_validate(store.values[run_name])
    assert [entry.status for entry in interrupted.entries] == ["completed", "completed", "processing"]
    assert interrupted.run_complete is False

    reconnected = Reader()
    second = app(tmp_path, reconnected, Telegram([]), Orch(), store=store,
                 global_newest_first=True)
    assert len(second.mailbox.poll(max_mails=100)) == 1
    assert reconnected.discoveries == 0
    assert second.orchestrator.seen == [3]
    assert MailRunState.model_validate(store.values[run_name]).run_complete is True


def test_unhandled_analysis_failure_halts_the_materialized_queue(tmp_path):
    """One analysis failure must not be repeated for the remaining queue."""
    stamp = datetime(2026, 1, 1, tzinfo=UTC)

    class Reader:
        account_id = "0" * 24
        last_uidvalidity = 7
        def discover_since(self, folder, *_args):
            return [MailCandidate(folder, 7, uid, self.account_id, stamp) for uid in (1, 2)]
        def fetch_uid(self, folder, uid, validity):
            return FetchedMail(folder, validity, uid, b"x", self.account_id, stamp)

    class FailFirst(Orch):
        def process(self, mail):
            self.seen.append(mail.uid)
            if mail.uid == 1:
                raise RuntimeError("synthetic analysis failure")
            return ProcessingResult(ProcessingOutcome.COMPLETED, {})

    store = Store()
    service = app(tmp_path, Reader(), Telegram([]), FailFirst(), store=store,
                  global_newest_first=True)
    results = service.mailbox.poll(max_mails=100)
    run = MailRunState.model_validate(store.values[f"mail-run-{service.imap.account_id}"])

    assert results == []
    assert service.orchestrator.seen == [1]
    assert [entry.status for entry in run.entries] == ["processing", "queued"]
    assert run.run_complete is False


def test_acceptance_full_inbox_batch_survives_dialog_timeout_and_optional_folders(tmp_path):
    """Fälle A, C, D und F gemeinsam mit der geforderten 86-Mail-Abnahme."""
    stamp = datetime(2026, 1, 1, tzinfo=UTC)
    analyzed: list[int] = []

    class Reader:
        account_id = "0" * 24
        last_uidvalidity = 7
        def __init__(self, disconnect=False):
            self.disconnect=disconnect
            self.fetches=[]
        def discover_since(self, folder, *_args):
            if folder != "INBOX":
                raise RuntimeError(f"synthetic unreadable optional folder: {folder}")
            return [MailCandidate(folder, 7, uid, self.account_id,
                                  stamp - timedelta(seconds=uid))
                    for uid in range(1, 87)]
        def fetch_uid(self, folder, uid, validity):
            self.fetches.append((folder, uid))
            if self.disconnect and uid == 3:
                raise TimeoutError("synthetic one-shot timeout")
            return FetchedMail(folder, validity, uid, b"Subject: synthetic\n\nBody",
                               self.account_id, stamp)

    class Analyzer(Orch):
        def process(self, mail):
            analyzed.append(mail.uid)
            outcome = (ProcessingOutcome.WAITING if mail.uid == 2
                       else ProcessingOutcome.COMPLETED)
            return ProcessingResult(outcome, {})

    store = Store()
    folders = ("INBOX", "Drafts", "Sent", "Spam", "Trash")
    first_reader = Reader(disconnect=True)
    first = app(tmp_path, first_reader, Telegram([]), Analyzer(), folders=folders,
                store=store, global_newest_first=True)
    with pytest.raises(TimeoutError, match="one-shot"):
        first.mailbox.poll(max_mails=100)

    # A new adapter represents the newly established IMAP connection.  It must
    # consume the already persisted queue instead of running discovery again.
    second_reader = Reader()
    second = app(tmp_path, second_reader, Telegram([]), Analyzer(), folders=folders,
                 store=store, global_newest_first=True)
    resumed_results = second.mailbox.poll(max_mails=100)
    run = MailRunState.model_validate(store.values[f"mail-run-{second_reader.account_id}"])
    identities = [entry.key for entry in run.entries]
    processed = sum(entry.analysis_terminal is not None for entry in run.entries)

    assert len(resumed_results) == 84
    assert processed == 86
    assert len(identities) == len(set(identities)) == 86
    assert sorted(analyzed) == list(range(1, 87))
    assert len(analyzed) == len(set(analyzed))
    assert run.counters.waiting_for_user == 1
    assert run.entries[1].user_action_open is True
    assert run.run_complete is True
    assert sum(event[0][2] == "optional_folder_failed"
               for event in first.logger.events) == 4
    assert any("synthetic unreadable optional folder" in event[1]["error"]
               for event in first.logger.events
               if event[0][2] == "optional_folder_failed")
