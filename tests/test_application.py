from __future__ import annotations

from pathlib import Path
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest

from mailhelp.application import Application, _MailBudget, _RunSummary, _add_uid, _checkpoint_name, _safe_name, _state_directory, build_application, build_logger
from mailhelp.config import Secrets, Settings, Topic
from mailhelp.imap import FetchedMail, MailCandidate, UIDValidityChanged
from mailhelp.models import MailRunCounters, MailRunEntry, MailRunState, MailState
from mailhelp.orchestrator import ProcessingOutcome, ProcessingResult
from test_core import prompt_config


class Store:
    def __init__(self, values=None): self.values=values or {}; self.saved=[]
    def load(self, name, default=None): return self.values.get(name, default)
    def save(self, name, value): self.saved.append((name,value)); self.values[name]=value
    def names(self, prefix=""): return sorted(name for name in self.values if name.startswith(prefix))
    def load_model(self, name, model, default=None):
        value=self.values.get(name)
        return default if value is None else model.model_validate(value)


class Log:
    def __init__(self): self.events=[]
    def event(self,*args,**kwargs): self.events.append((args,kwargs))


class Imap:
    def __init__(self, outcomes): self.outcomes=iter(outcomes); self.last_uidvalidity=None; self.account_id="0"*24; self.calls=[]; self.uid_calls=[]
    def fetch_since(self,*args):
        self.calls.append(args); value=next(self.outcomes)
        if isinstance(value,Exception): raise value
        self.last_uidvalidity=value[0]
        if args[2] is not None and value[0] != args[2]:
            raise UIDValidityChanged(args[0], args[2], value[0])
        return value[1]
    def fetch_uid(self,*args):
        self.uid_calls.append(args)
        return FetchedMail(args[0],args[2],args[1],b"Subject: resumed\n\nBody")


class Telegram:
    def __init__(self, value): self.value=value; self.offsets=[]; self.sent=[]
    def poll(self, offset, timeout=None):
        self.offsets.append(offset)
        if isinstance(self.value,Exception): raise self.value
        return self.value
    def send(self, chat_id, text): self.sent.append((chat_id,text))


class Orch:
    def __init__(self, fail=False, stop=None, config_fingerprint="0"*64): self.fail=fail; self.stop_event=SimpleNamespace(set=lambda:None); self.stop_called=False; self.seen=[]; self._stop=stop; self.config_fingerprint=config_fingerprint
    def stop(self): self.stop_called=True
    def process(self, mail):
        self.seen.append(mail.uid)
        if self._stop: self._stop.set()
        if self.fail: raise RuntimeError("mail")
        return ProcessingResult(ProcessingOutcome.COMPLETED, {})


def settings(tmp_path, folders=("INBOX",), global_newest_first=False):
    return Settings(timezone="UTC",poll_interval_seconds=5,test_mode=True,data_directory=tmp_path/"data",imap={"host":"h","port":993,"folders":list(folders),"global_newest_first":global_newest_first},telegram={"user_id":1,"chat_id":2},targets={"todoist_project":"p","google_calendar":"c"},limits={"max_mail_bytes":1024,"llm_calls_per_minute":2},retries={"provider_retry":0,"json_repair":0,"schema_repair":0},timeouts={**{name:{"timeout_seconds":30.0,"retries":0,"initial_backoff_seconds":0.0,"max_backoff_seconds":1.0} for name in ("imap","telegram","openrouter","todoist","google_calendar")},"telegram_poll_seconds":30},logging={"directory":str(tmp_path/"logs"),"console":{"enabled":False},"file":{"filename":"application.jsonl","max_bytes":10000,"backup_count":1,"retention_days":30},"llm":{"filename":"llm/requests.jsonl","max_bytes":10000,"backup_count":1,"retention_days":30}})


def app(tmp_path, imap, telegram, orch, folders=("INBOX",), store=None,
        global_newest_first=False):
    from threading import Event
    event=Event(); orch._stop=event if orch._stop else None
    return Application(settings(tmp_path,folders,global_newest_first),store or Store(),Log(),imap,object(),object(),telegram,object(),object(),orch,event)


def test_global_mailbox_order_and_max_mail_budget(tmp_path):
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)

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
    results = service._poll_imap(max_mails=2)

    assert len(results) == 2
    assert imap.fetches == [("Archive", 2, 7), ("Archive", 3, 7)]
    assert service.orchestrator.seen == [2, 3]
    assert service.store.values[_checkpoint_name(imap.account_id, "Archive")][
        "completed_uid_ranges"
    ] == [(2, 3)]


def test_exhausted_uid_halts_queue_and_restart_retries_same_item(tmp_path):
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)

    class Reader:
        account_id = "0" * 24
        last_uidvalidity = 7
        def __init__(self, fail=True): self.fetches = []; self.fail = fail
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

    results = service._poll_imap(max_mails=2)

    run = MailRunState.model_validate(store.values[f"mail-run-{reader.account_id}"])
    assert [entry.status.value for entry in run.entries] == ["processing", "queued"]
    assert [entry.failure_code for entry in run.entries] == [None, None]
    assert "private server diagnostic" not in str(store.values[f"mail-run-{reader.account_id}"])
    assert reader.fetches == [2]
    assert service.orchestrator.seen == []
    assert results == []
    assert service._poll_imap(max_mails=2) == []
    assert reader.fetches == [2]

    restarted_reader = Reader(fail=False)
    restarted = app(tmp_path, restarted_reader, Telegram([]), Orch(), store=store,
                    global_newest_first=True)
    assert len(restarted._poll_imap(max_mails=2)) == 2
    assert restarted_reader.fetches == [2, 3]
    assert restarted.orchestrator.seen == [2, 3]
    with pytest.raises(ValueError, match="Fehlermerkmal"):
        MailRunEntry(account_id="a", folder="INBOX", uidvalidity=1, uid=1,
                     status="completed", analysis_terminal="completed",
                     failure_code="processing_failed")


def test_terminal_processing_failure_is_persisted_and_counted(tmp_path):
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)

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
            return ProcessingResult(ProcessingOutcome.FAILED, {
                "error": {"code": "permanent_adapter_error"},
            })

    service = app(tmp_path, Reader(), Telegram([]), Failed(),
                  global_newest_first=True)

    results = service._poll_imap(max_mails=2)

    run = service.store.load_model("mail-run-" + "0" * 24, MailRunState)
    assert len(results) == 1
    assert [entry.status.value for entry in run.entries] == ["failed", "queued"]
    assert run.entries[0].analysis_terminal == "failed"
    assert run.entries[0].failure_code == "processing_failed"
    assert run.counters.failed == 1
    assert _RunSummary.from_run(run) == _RunSummary(
        discovered=2, queued=1, processed=1, failed=1, run_complete=False,
    )
    assert _checkpoint_name(service.imap.account_id, "INBOX") in service.store.values
    assert service.store.values[_checkpoint_name(
        service.imap.account_id, "INBOX"
    )]["completed_uid_ranges"] == []


def test_persistent_run_records_duplicate_and_irrelevant_analysis(tmp_path):
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)

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
            state = ({"duplicate": {"previous_mail_id": "a"}}
                     if mail.uid == 1 else
                     {"relevance": {"decision": "irrelevant"}})
            return ProcessingResult(ProcessingOutcome.COMPLETED, state)

    service = app(tmp_path, Reader(), Telegram([]), Classified(),
                  global_newest_first=True)
    service._poll_imap(max_mails=2)
    run = service.store.load_model("mail-run-" + "0" * 24, MailRunState)
    assert [entry.analysis_terminal for entry in run.entries] == [
        "duplicate", "irrelevant"
    ]


def test_repeated_global_max_mail_runs_continue_with_next_newest_batch(tmp_path):
    """A persisted newest-first batch must not hide the older backlog."""
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)

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
    assert len(first._poll_imap(max_mails=100)) == 100
    assert reader.fetches == list(range(205, 105, -1))

    restarted = app(tmp_path, reader, Telegram([]), Orch(), store=store,
                    global_newest_first=True)
    assert len(restarted._poll_imap(max_mails=100)) == 100
    assert reader.fetches[100:] == list(range(105, 5, -1))
    assert store.values[key]["completed_uid_ranges"] == [(6, 205)]


@pytest.mark.parametrize(("available", "maximum", "expected"), ((86, 100, 86), (150, 100, 100)))
def test_run_materializes_exact_bounded_uid_queue_before_fetch(tmp_path, available, maximum, expected):
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)

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

    assert len(service._poll_imap(max_mails=maximum)) == expected
    run = MailRunState.model_validate(store.values[f"mail-run-{reader.account_id}"])
    assert run.max_mails == maximum
    assert run.counters.completed == expected
    assert len({entry.key for entry in run.entries}) == expected


def test_interrupted_batch_resumes_fixed_queue_without_rediscovery_or_reanalysis(tmp_path):
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)

    class Crash(BaseException):
        pass

    class Reader:
        account_id = "0" * 24
        last_uidvalidity = 7
        def __init__(self): self.discoveries = 0; self.fetches = []
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

    store = Store(); reader = Reader()
    first = app(tmp_path, reader, Telegram([]), CrashOnTwo(), store=store,
                global_newest_first=True)
    with pytest.raises(Crash):
        first._poll_imap(max_mails=3)
    run_name = f"mail-run-{reader.account_id}"
    interrupted = MailRunState.model_validate(store.values[run_name])
    assert [entry.status for entry in interrupted.entries] == ["completed", "processing", "queued"]

    restarted = app(tmp_path, reader, Telegram([]), Orch(), store=store,
                    global_newest_first=True)
    assert len(restarted._poll_imap(max_mails=3)) == 2
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
        MailRunState(created_at=datetime.now(timezone.utc), **{**base, "entries": [queued, queued]})
    with pytest.raises(ValueError, match="Zähler"):
        MailRunState(created_at=datetime.now(timezone.utc),
                     **{**base, "counters": MailRunCounters()})
    assert MailRunState(created_at=datetime.now(timezone.utc), **base).run_complete is False
    terminal = MailRunEntry(
        account_id="a", folder="INBOX", uidvalidity=1, uid=1,
        status="completed", analysis_terminal="completed",
    )
    assert MailRunState(
        created_at=datetime.now(timezone.utc),
        **{**base, "entries": [terminal], "counters": MailRunCounters(completed=1)},
    ).run_complete is True


def test_reconnectable_timeout_resumes_same_materialized_queue(tmp_path):
    """Fall D: reconnecting must neither rediscover nor replace the fixed queue."""
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)

    class Reader:
        account_id = "0" * 24
        last_uidvalidity = 7
        def __init__(self, timeout=False): self.timeout=timeout; self.discoveries=0; self.fetches=[]
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
        first._poll_imap(max_mails=100)

    run_name = f"mail-run-{disconnected.account_id}"
    interrupted = MailRunState.model_validate(store.values[run_name])
    assert [entry.status for entry in interrupted.entries] == ["completed", "completed", "processing"]
    assert interrupted.run_complete is False

    reconnected = Reader()
    second = app(tmp_path, reconnected, Telegram([]), Orch(), store=store,
                 global_newest_first=True)
    assert len(second._poll_imap(max_mails=100)) == 1
    assert reconnected.discoveries == 0
    assert second.orchestrator.seen == [3]
    assert MailRunState.model_validate(store.values[run_name]).run_complete is True


def test_unhandled_analysis_failure_halts_the_materialized_queue(tmp_path):
    """One analysis failure must not be repeated for the remaining queue."""
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)

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
    results = service._poll_imap(max_mails=100)
    run = MailRunState.model_validate(store.values[f"mail-run-{service.imap.account_id}"])

    assert results == []
    assert service.orchestrator.seen == [1]
    assert [entry.status for entry in run.entries] == ["processing", "queued"]
    assert run.run_complete is False


def test_acceptance_full_inbox_batch_survives_dialog_timeout_and_optional_folders(tmp_path):
    """Fälle A, C, D und F gemeinsam mit der geforderten 86-Mail-Abnahme."""
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    analyzed: list[int] = []

    class Reader:
        account_id = "0" * 24
        last_uidvalidity = 7
        def __init__(self, disconnect=False): self.disconnect=disconnect; self.fetches=[]
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
        first._poll_imap(max_mails=100)

    # A new adapter represents the newly established IMAP connection.  It must
    # consume the already persisted queue instead of running discovery again.
    second_reader = Reader()
    second = app(tmp_path, second_reader, Telegram([]), Analyzer(), folders=folders,
                 store=store, global_newest_first=True)
    resumed_results = second._poll_imap(max_mails=100)
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


def test_global_mailbox_checkpoint_failures_restarts_and_dialog(tmp_path):
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    key = _checkpoint_name("0" * 24, "INBOX")

    class GlobalImap:
        account_id = "0" * 24
        last_uidvalidity = 7
        def __init__(self, discoveries):
            self.discoveries = iter(discoveries); self.fetch_error = False
        def discover_since(self, *args):
            value = next(self.discoveries)
            if isinstance(value, Exception): raise value
            return value
        def fetch_uid(self, folder, uid, validity):
            if self.fetch_error: raise RuntimeError("fetch")
            return FetchedMail(folder, validity, uid, b"x", self.account_id, stamp)
        def determine_start_uid(self, _folder, _start):
            return 4

    candidate = MailCandidate("INBOX", 7, 5, "0" * 24, stamp)
    legacy_store = Store({key: {"uidvalidity": 7, "uid": 3, "start_uid": 0}})
    empty = app(tmp_path, GlobalImap([[]]), Telegram([]), Orch(), store=legacy_store,
                global_newest_first=True)
    empty._poll_imap()
    assert legacy_store.values[key]["completed_uid_ranges"] == []

    fresh_store = Store()
    fresh = app(tmp_path, GlobalImap([[]]), Telegram([]), Orch(), store=fresh_store,
                global_newest_first=True)
    fresh._poll_imap()
    assert fresh_store.values[key]["uidvalidity"] == 7

    failed_imap = GlobalImap([RuntimeError("discovery")])
    failed = app(tmp_path, failed_imap, Telegram([]), Orch(),
                 global_newest_first=True)
    assert failed._poll_imap() == []
    assert failed.logger.events[-1][0][2] == "poll_failed"

    fetch_imap = GlobalImap([[candidate]])
    fetch_imap.fetch_error = True
    fetch_failed = app(tmp_path, fetch_imap, Telegram([]), Orch(),
                       global_newest_first=True)
    assert fetch_failed._poll_imap() == []
    assert fetch_failed.logger.events[-1][0][2] == "mail_failed"

    class FailedOrch(Orch):
        def process(self, mail):
            self.seen.append(mail.uid)
            return ProcessingResult(ProcessingOutcome.FAILED, {"error": "failed"})

    outcome = app(tmp_path, GlobalImap([[candidate]]), Telegram([]), FailedOrch(),
                  global_newest_first=True)
    assert outcome._poll_imap()[0].outcome is ProcessingOutcome.FAILED
    assert outcome.logger.events[-1][1]["error"] == "failed"

    class Dialog:
        def __init__(self): self.open = True
        def awaiting_decision(self): return self.open
        def poll_once(self, timeout=None): self.open = False

    dialog = app(tmp_path, GlobalImap([[candidate]]), Telegram([]), Orch(),
                 global_newest_first=True)
    dialog.dialog = Dialog()
    assert len(dialog._poll_imap()) == 1
    assert dialog.dialog.open is True

    stopped = app(tmp_path, GlobalImap([]), Telegram([]), Orch(),
                  global_newest_first=True)
    stopped.stop_event.set()
    assert stopped._poll_imap() == []
    assert stopped._poll_imap_global(_MailBudget(1)) == []

    interrupted = app(tmp_path, GlobalImap([[candidate]]), Telegram([]), Orch(),
                      global_newest_first=True)
    original_discover = interrupted.imap.discover_since
    def discover_and_stop(*args):
        result = original_discover(*args)
        interrupted.stop_event.set()
        return result
    interrupted.imap.discover_since = discover_and_stop
    assert interrupted._poll_imap() == []

    two_candidates = [candidate, MailCandidate("INBOX", 7, 6, "0" * 24, stamp)]
    stopped_during_processing = app(
        tmp_path, GlobalImap([two_candidates]), Telegram([]), Orch(stop=True),
        global_newest_first=True,
    )
    assert len(stopped_during_processing._poll_imap()) == 1


def test_global_mailbox_uidvalidity_and_historical_boundary(tmp_path):
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    boundary = stamp - timedelta(days=1)
    key = _checkpoint_name("0" * 24, "INBOX")

    class ChangingImap:
        account_id = "0" * 24
        last_uidvalidity = 7
        def __init__(self, drift=False): self.calls = 0; self.drift = drift
        def determine_start_uid(self, _folder, _start):
            self.last_uidvalidity = 9 if self.drift else (8 if self.calls else 7)
            return 4
        def discover_since(self, folder, start, expected, ranges):
            self.calls += 1
            if self.calls == 1 and expected == 7:
                raise UIDValidityChanged(folder, 7, 8)
            return [MailCandidate(folder, 8, 5, self.account_id, stamp)]
        def fetch_uid(self, folder, uid, validity):
            return FetchedMail(folder, validity, uid, b"x", self.account_id, stamp)

    configured = settings(tmp_path, global_newest_first=True)
    configured.imap.historical_start = boundary
    imap = ChangingImap()
    service = Application(configured, Store(), Log(), imap, object(), object(),
                          Telegram([]), object(), object(), Orch(), __import__('threading').Event())
    assert len(service._poll_imap()) == 1
    assert service.store.values[key]["uidvalidity"] == 8
    assert any(event[0][2] == "uidvalidity_changed" for event in service.logger.events)

    drifting = ChangingImap(drift=True)
    drift_store = Store({key: {"uidvalidity": 7, "uid": 4, "start_uid": 4}})
    drifted = Application(configured, drift_store, Log(), drifting, object(), object(),
                          Telegram([]), object(), object(), Orch(), __import__('threading').Event())
    assert drifted._poll_imap() == []
    assert "während der Grenzermittlung" in drifted.logger.events[-1][1]["error"]

    no_history = settings(tmp_path, global_newest_first=True)
    changed = ChangingImap()
    changed_store = Store({key: {"uidvalidity": 7, "uid": 4, "start_uid": 4}})
    reset = Application(no_history, changed_store, Log(), changed, object(), object(),
                        Telegram([]), object(), object(), Orch(), __import__('threading').Event())
    assert len(reset._poll_imap()) == 1


def test_polling_errors_resume_and_stop(tmp_path):
    mail1=FetchedMail("INBOX",7,4,b"x"); mail2=FetchedMail("INBOX",7,5,b"x")
    store=Store({_checkpoint_name("0"*24, "INBOX"):{"uidvalidity":7,"uid":3},"telegram-offset":{"offset":8}})
    service=app(tmp_path,Imap([(7,[mail1,mail2])]),Telegram([{"update_id":8},{"update_id":10}]),Orch(fail=True),store=store)
    service._poll_imap(); service._poll_telegram()
    assert service.imap.calls==[("INBOX",3,7,None,())] and service.orchestrator.seen==[4,5]
    assert store.values[_checkpoint_name("0"*24, "INBOX")]["uid"]==3 and store.values["telegram-offset"]["offset"]==11
    assert any(e[0][2]=="mail_failed" for e in service.logger.events)

    class FirstFails(Orch):
        def process(self, mail):
            self.seen.append(mail.uid)
            if mail.uid == 4: raise RuntimeError("mail")
            return ProcessingResult(ProcessingOutcome.COMPLETED,{})
    mixed_store=Store({_checkpoint_name("0"*24, "INBOX"):{"uidvalidity":7,"uid":3}})
    mixed=app(tmp_path,Imap([(7,[mail1,mail2])]),Telegram([]),FirstFails(),store=mixed_store)
    mixed._poll_imap()
    assert mixed.orchestrator.seen==[4,5]
    assert mixed_store.values[_checkpoint_name("0"*24, "INBOX")]["uid"]==5
    assert mixed_store.values[_checkpoint_name("0"*24, "INBOX")]["completed_uid_ranges"]==[(5,5)]

    class FirstReturnsFailure(Orch):
        def process(self, mail):
            self.seen.append(mail.uid)
            outcome=ProcessingOutcome.FAILED if mail.uid==4 else ProcessingOutcome.COMPLETED
            return ProcessingResult(outcome,{"error":{"type":"RuntimeError","message":"mail"}} if mail.uid==4 else {})
    durable_store=Store({_checkpoint_name("0"*24, "INBOX"):{"uidvalidity":7,"uid":3}})
    durable=app(tmp_path,Imap([(7,[mail1,mail2])]),Telegram([]),FirstReturnsFailure(),store=durable_store)
    results=durable._poll_imap()
    assert [result.outcome for result in results]==[ProcessingOutcome.FAILED]
    assert durable.orchestrator.seen==[4]
    assert durable_store.values[_checkpoint_name("0"*24, "INBOX")]["uid"]==3
    assert durable_store.values[_checkpoint_name("0"*24, "INBOX")].get("completed_uid_ranges",[])==[]
    assert any(e[0][2]=="mail_failed" and e[1]["uid"]==4 for e in durable.logger.events)

    failing=app(tmp_path,Imap([RuntimeError("imap"),(9,[]),(10,[])]),Telegram(RuntimeError("tg")),Orch(),folders=("bad","new","none"))
    failing._poll_imap(); failing._poll_telegram()
    assert len(failing.logger.events)==2
    assert failing.store.values[_checkpoint_name("0"*24, "new")]["uidvalidity"]==9
    assert failing.store.values[_checkpoint_name("0"*24, "none")]["uidvalidity"]==10

    stopped=app(tmp_path,Imap([(1,[mail1,mail2])]),Telegram([]),Orch(stop=True),folders=("INBOX","Other"))
    stopped._poll_imap(); assert stopped.orchestrator.seen==[4]
    stopped.stop(); assert stopped.stop_event.is_set() and stopped.orchestrator.stop_called

    limited=app(tmp_path,Imap([(7,[mail1])]),Telegram([]),Orch(),store=store)
    limited._poll_imap(max_mails=1)
    assert limited.imap.calls == [("INBOX",3,7,1,())]


def test_empty_checkpoint_and_run_paths(tmp_path):
    key=_checkpoint_name("0"*24, "INBOX")
    store=Store({key:{"uidvalidity":4,"uid":12}})
    same=app(tmp_path,Imap([(4,[])]),Telegram([]),Orch(),store=store); same._poll_imap()
    assert store.values[key]["uid"]==12
    none=app(tmp_path,Imap([(None,[])]),Telegram([]),Orch()); none._poll_imap()
    assert none.store.saved[0][1]["start_uid"] == 0
    none.stop_event.set(); none.run()
    running=app(tmp_path,Imap([(1,[])]),Telegram([]),Orch())
    running._poll_imap=lambda _limit=None: (running.stop_event.set(), [])[1]; running.run()
    complete=app(tmp_path,Imap([(1,[])]),Telegram([]),Orch())
    complete._poll_imap=lambda _limit=None: []
    complete._poll_telegram=lambda: complete.stop_event.set()
    complete.run()

    import mailhelp.application as application_module
    original = application_module.RetentionService
    class BrokenRetention:
        def __init__(self, *args): pass
        def run(self): raise RuntimeError("private detail")
    application_module.RetentionService = BrokenRetention
    failed_cleanup=app(tmp_path,Imap([(1,[])]),Telegram([]),Orch())
    failed_cleanup._poll_imap=lambda _limit=None: (failed_cleanup.stop_event.set(), [])[1]
    failed_cleanup.run()
    application_module.RetentionService = original
    assert failed_cleanup.logger.events[0][0][2]=="cleanup_failed"
    assert failed_cleanup.logger.events[0][1]["failure_count"]==1
    assert datetime.fromisoformat(failed_cleanup.logger.events[0][1]["processed_at"]).tzinfo is not None

    class Dialog:
        def __init__(self, error=None): self.calls=0; self.error=error
        def poll_once(self, timeout=None):
            self.calls += 1
            if self.error: raise self.error
    dialog_app=app(tmp_path,Imap([(1,[])]),Telegram([]),Orch()); dialog_app.dialog=Dialog(); dialog_app._poll_telegram(); assert dialog_app.dialog.calls==1
    failed_dialog=app(tmp_path,Imap([(1,[])]),Telegram([]),Orch()); failed_dialog.dialog=Dialog(RuntimeError("dialog")); failed_dialog._poll_telegram()
    assert failed_dialog.logger.events[0][0][2]=="poll_failed"


def test_run_waits_for_open_proposal_before_polling_imap(tmp_path):
    class ControlledStop:
        def __init__(self): self.stopped=False; self.waits=[]
        def is_set(self): return self.stopped
        def set(self): self.stopped=True
        def wait(self, seconds): self.waits.append(seconds); self.stopped=True; return True
    class Dialog:
        def __init__(self): self.polls=0
        def poll_once(self, timeout=None):
            self.polls += 1
            self.open = False
        open = True
        def awaiting_decision(self): return self.open

    service=app(tmp_path,Imap([(1,[])]),Telegram([]),Orch())
    stop=ControlledStop(); service.stop_event=stop; service.dialog=Dialog()
    service.run()

    assert service.dialog.polls == 1
    assert service.imap.calls == [("INBOX",0,None,None,())]
    assert stop.waits == [service.settings.poll_interval_seconds]


def test_mail_batch_does_not_poll_telegram_without_an_open_question(tmp_path):
    mails = [FetchedMail("INBOX", 7, uid, b"synthetic") for uid in (1, 2)]

    class Dialog:
        def __init__(self): self.timeouts = []
        def poll_once(self, timeout=None): self.timeouts.append(timeout)

    service = app(tmp_path, Imap([(7, mails)]), Telegram([]), Orch())
    service.dialog = Dialog()
    service.dialog.awaiting_decision = lambda: False

    results = service._poll_imap()

    assert len(results) == 2
    assert service.orchestrator.seen == [1, 2]
    assert service.dialog.timeouts == []


def test_open_proposal_blocks_next_mail_even_in_bounded_run(tmp_path):
    mails = [FetchedMail("INBOX", 7, uid, b"x") for uid in (1, 2, 3)]

    class Dialog:
        open = False
        polls = 0
        def poll_once(self, timeout=None):
            self.polls += 1
            self.open = False
        def awaiting_decision(self): return self.open

    dialog = Dialog()
    class OpensDialog(Orch):
        def process(self, mail):
            result = super().process(mail)
            if mail.uid == 2:
                dialog.open = True
            return result

    service = app(tmp_path, Imap([(7, mails)]), Telegram([]), OpensDialog())
    service.dialog = dialog

    service.run(max_mails=3)

    assert service.orchestrator.seen == [1, 2, 3]
    assert dialog.open is False
    assert dialog.polls == 2


def test_versioned_answer_is_processed_before_later_mail(tmp_path):
    reference = ("a" * 24, "proposal-2", 3)

    class Dialog:
        def __init__(self): self.updates=[]; self.handled=[]; self.executions=[]; self.polls=0; self.open=False
        def poll_once(self, timeout=None):
            self.polls += 1
            if not self.open:
                return
            for update in self.updates:
                identity = (update["mail_id"], update["proposal_id"], update["version"])
                if identity not in self.executions:
                    self.handled.append(update)
                    self.executions.append(identity)
            self.updates.clear()
            self.open = False
        def awaiting_decision(self): return self.open
        def awaiting_relevance_decision(self): return self.open

    class ProposesOnTwo(Orch):
        def process(self, mail):
            self.seen.append(mail.uid)
            if mail.uid == 2 and not dialog.handled:
                dialog.open = True
            outcome = (ProcessingOutcome.WAITING if dialog.open
                       else ProcessingOutcome.COMPLETED)
            return ProcessingResult(outcome, {})

    dialog = Dialog()
    arrived_ten_minutes_later = {
        "received_at": datetime.now(timezone.utc) + timedelta(minutes=10),
        "mail_id": reference[0], "proposal_id": reference[1], "version": reference[2],
    }
    # Telegram may redeliver an update; the immutable proposal revision still
    # authorizes exactly one simulated external write.
    dialog.updates.extend([arrived_ten_minutes_later, arrived_ten_minutes_later.copy()])
    mails = [FetchedMail("INBOX", 7, uid, b"synthetic") for uid in (1, 2, 3)]
    first = app(tmp_path, Imap([(7, mails)]), Telegram([]), ProposesOnTwo())
    first.dialog = dialog
    first.run(max_mails=3)

    assert [(item["mail_id"], item["proposal_id"], item["version"])
            for item in dialog.handled] == [reference]
    assert dialog.executions == [reference]
    assert first.orchestrator.seen == [1, 2, 2, 3]
    assert dialog.polls == 2


def test_completed_mail_with_multiple_open_proposals_waits_until_closed(tmp_path):
    class Dialog:
        def __init__(self): self.polls = 0; self.open = True
        def poll_once(self, timeout=None): self.polls += 1; self.open = False
        def awaiting_decision(self): return self.open

    service = app(tmp_path, Imap([]), Telegram([]), Orch())
    service.dialog = Dialog()
    service._wait_for_user = True

    result = service._process_mail(FetchedMail("INBOX", 7, 1, b"synthetic"))

    assert result.outcome is ProcessingOutcome.COMPLETED
    assert service.dialog.polls == 1


def test_new_proposal_returns_when_shutdown_interrupts_its_wait(tmp_path):
    class OpensDialog(Orch):
        def process(self, mail):
            dialog.open = True
            return ProcessingResult(ProcessingOutcome.COMPLETED, {})

    class Dialog:
        open = False
        def awaiting_decision(self): return self.open
        def poll_once(self, timeout=None): raise RuntimeError("network")

    class StopOnWait:
        stopped = False
        def is_set(self): return self.stopped
        def wait(self, _seconds): self.stopped = True; return True

    dialog = Dialog()
    service = app(tmp_path, Imap([]), Telegram([]), OpensDialog())
    service.dialog = dialog
    service.stop_event = StopOnWait()
    service._wait_for_user = True

    result = service._process_mail(FetchedMail("INBOX", 7, 1, b"synthetic"))

    assert result.outcome is ProcessingOutcome.COMPLETED


def test_run_waits_when_regular_telegram_poll_opens_dialog(tmp_path):
    class Dialog:
        def __init__(self): self.open = False; self.polls = 0
        def awaiting_decision(self): return self.open
        def poll_once(self, timeout=None):
            self.polls += 1
            self.open = self.polls == 1

    service = app(tmp_path, Imap([(1, [])]), Telegram([]), Orch())
    service.dialog = Dialog()

    service.run(max_mails=0)

    assert service.dialog.polls == 2
    assert not service.dialog.open


def test_waiting_relevance_handles_closed_dialog_and_poll_failure(tmp_path):
    class WaitingOrchestrator(Orch):
        def process(self, mail):
            return ProcessingResult(ProcessingOutcome.WAITING, {})

    class Dialog:
        def __init__(self, open): self.open = open
        def awaiting_decision(self): return self.open
        def awaiting_relevance_decision(self): return self.open
        def poll_once(self, timeout=None): raise RuntimeError("network")

    service = app(tmp_path, Imap([]), Telegram([]), WaitingOrchestrator())
    service.dialog = Dialog(False)
    service._wait_for_user = True
    assert service._process_mail(FetchedMail("INBOX", 7, 1, b"synthetic")).outcome \
        is ProcessingOutcome.WAITING
    assert service._wait_for_telegram_decision() is False

    class StopOnWait:
        def __init__(self): self.stopped = False
        def is_set(self): return self.stopped
        def wait(self, _seconds): self.stopped = True; return True

    service.dialog.open = True
    service.stop_event = StopOnWait()
    assert service._process_mail(FetchedMail("INBOX", 7, 1, b"synthetic")).outcome \
        is ProcessingOutcome.WAITING
    assert service.stop_event.is_set()


def test_run_keeps_imap_interval_without_open_dialog(tmp_path):
    class ControlledStop:
        def __init__(self): self.stopped=False; self.waits=[]
        def is_set(self): return self.stopped
        def set(self): self.stopped=True
        def wait(self, seconds): self.waits.append(seconds); self.stopped=True; return True

    service=app(tmp_path,Imap([(1,[])]),Telegram([]),Orch())
    stop=ControlledStop(); service.stop_event=stop
    service.run()

    assert service.imap.calls == [("INBOX",0,None,None,())]
    assert stop.waits == [service.settings.poll_interval_seconds]


def test_telegram_poll_failure_backs_off_and_shutdown_interrupts_it(tmp_path):
    class ControlledStop:
        def __init__(self): self.stopped=False; self.waits=[]
        def is_set(self): return self.stopped
        def set(self): self.stopped=True
        def wait(self, seconds): self.waits.append(seconds); self.stopped=True; return True
    class FailingDialog:
        def __init__(self): self.polls=0
        def poll_once(self, timeout=None): self.polls += 1; raise RuntimeError("network")
        def awaiting_decision(self): return True

    service=app(tmp_path,Imap([]),Telegram([]),Orch())
    stop=ControlledStop(); service.stop_event=stop; service.dialog=FailingDialog()
    service.run()

    assert service.dialog.polls == 1
    assert stop.waits == [5]
    assert stop.is_set()


def test_shutdown_requested_during_long_poll_stops_before_retry(tmp_path):
    class Dialog:
        def __init__(self, stop): self.stop=stop; self.polls=0
        def poll_once(self, timeout=None): self.polls += 1; self.stop.set()
        def awaiting_decision(self): return True

    service=app(tmp_path,Imap([]),Telegram([]),Orch())
    service.dialog=Dialog(service.stop_event)
    service.run()

    assert service.dialog.polls == 1


def test_newest_first_backlog_arrivals_restart_failure_and_folders(tmp_path):
    """Ranges preserve holes while new mail is prioritized across short batches."""
    class BacklogImap:
        account_id="0"*24
        last_uidvalidity=None
        def __init__(self):
            self.available={"INBOX":[4,5,6],"Archive":[2]}; self.calls=[]
        def fetch_since(self,folder,start,expected,maximum,ranges):
            self.calls.append((folder,start,expected,maximum,ranges))
            self.last_uidvalidity=7
            remaining=[uid for uid in reversed(self.available[folder])
                       if uid>start and not any(a<=uid<=b for a,b in ranges)]
            count=min(2,maximum) if maximum is not None else 2
            return [FetchedMail(folder,7,uid,b"x") for uid in remaining[:count]]
        def fetch_uid(self,*_args): raise AssertionError("no pending state")
    class FailFiveOnce(Orch):
        def __init__(self): super().__init__(); self.failed=False
        def process(self,mail):
            self.seen.append(mail.uid)
            if mail.uid==5 and not self.failed:
                self.failed=True; raise RuntimeError("synthetic")
            return ProcessingResult(ProcessingOutcome.COMPLETED,{})

    reader=BacklogImap(); store=Store(); folders=("INBOX","Archive")
    first=app(tmp_path,reader,Telegram([]),FailFiveOnce(),folders=folders,store=store)
    first._poll_imap(max_mails=2)
    key=_checkpoint_name(reader.account_id,"INBOX")
    assert first.orchestrator.seen==[6,5]
    assert store.values[key]["completed_uid_ranges"]==[(6,6)]

    # UID 7 arrives while UID 5 and 4 are still in the durable backlog.  A new
    # Application instance proves that the JSON checkpoint alone is sufficient.
    reader.available["INBOX"].append(7)
    restarted=app(tmp_path,reader,Telegram([]),Orch(),folders=folders,store=store)
    restarted._poll_imap(max_mails=2)
    assert restarted.orchestrator.seen==[7,5]
    assert store.values[key]["completed_uid_ranges"]==[(5,7)]
    restarted._poll_imap(max_mails=2)
    assert restarted.orchestrator.seen==[7,5,4,2]
    assert store.values[key]["completed_uid_ranges"]==[(4,7)]
    assert store.values[_checkpoint_name(reader.account_id,"Archive")]["completed_uid_ranges"]==[(2,2)]


def test_uid_range_normalization_paths():
    assert _add_uid([(1,1),(4,4)],3)==[(1,1),(3,4)]
    assert _add_uid([(1,2),(4,5)],3)==[(1,5)]
    assert _add_uid([(3,4)],1)==[(1,1),(3,4)]


def _persisted_run(entries):
    return MailRunState(
        run_id="00000000-0000-0000-0000-000000000001", max_mails=100,
        created_at=datetime.now(timezone.utc), entries=entries,
        counters=Application._run_counters(entries),
    )


def test_run_sends_persistent_summary_on_normal_and_exceptional_exit(tmp_path):
    entries = [
        MailRunEntry(account_id="a", folder="INBOX", uidvalidity=1, uid=1,
                     status="completed", analysis_terminal="completed"),
        MailRunEntry(account_id="a", folder="INBOX", uidvalidity=1, uid=2,
                     status="waiting_for_user", analysis_terminal="completed",
                     user_action_open=True),
        MailRunEntry(account_id="a", folder="INBOX", uidvalidity=1, uid=3,
                     status="failed", analysis_terminal="failed",
                     failure_code="processing_failed"),
        MailRunEntry(account_id="a", folder="INBOX", uidvalidity=1, uid=4,
                     status="completed", analysis_terminal="irrelevant"),
        MailRunEntry(account_id="a", folder="INBOX", uidvalidity=1, uid=5,
                     status="skipped", analysis_terminal="duplicate"),
    ]
    run = _persisted_run(entries)
    store = Store({"mail-run-" + "0" * 24: run.model_dump(mode="json")})
    service=app(tmp_path,Imap([]),Telegram([]),Orch(),store=store)
    service._poll_imap=lambda _limit=None: []
    service.run(max_mails=3)
    assert service.telegram.sent == [(2, "Mailhelp-Lauf vollständig abgearbeitet.\nEntdeckt: 5\nIn Warteschlange: 0\nAnalysiert: 5\nRelevant: 2\nIrrelevant: 1\nWarten auf Benutzer: 1\nFehlgeschlagen: 1\nÜbersprungen: 1")]
    assert service.logger.events[-1][0][2] == "run_summary_sent"
    assert service.logger.events[-1][1] == {
        "discovered":5, "queued":0, "processed":5, "relevant":2,
        "irrelevant":1, "waiting_for_user":1, "failed":1, "skipped":1,
        "run_complete":True,
    }

    broken=app(tmp_path,Imap([]),Telegram([]),Orch())
    broken._poll_imap=lambda _limit=None: (_ for _ in ()).throw(RuntimeError("poll"))
    with pytest.raises(RuntimeError, match="poll"):
        broken.run()
    assert broken.telegram.sent[0][1].startswith(
        "Mailhelp-Lauf abgebrochen oder unvollständig.\nEntdeckt: 0"
    )

    send_failure=app(tmp_path,Imap([]),Telegram([]),Orch())
    send_failure.stop_event.set()
    send_failure.telegram.send=lambda *_args: (_ for _ in ()).throw(RuntimeError("telegram"))
    send_failure.run()
    assert send_failure.logger.events[-1][0][2] == "run_summary_failed"


@pytest.mark.parametrize("batch_size", (86, 100))
def test_run_summary_uses_all_terminal_entries_in_large_persistent_batch(batch_size):
    entries = [MailRunEntry(account_id="a", folder="INBOX", uidvalidity=1, uid=uid,
                            status="completed", analysis_terminal="completed")
               for uid in range(1, batch_size + 1)]
    summary = _RunSummary.from_run(_persisted_run(entries))
    assert (summary.discovered, summary.processed, summary.relevant) == (
        batch_size, batch_size, batch_size
    )
    assert summary.run_complete is True
    assert "vollständig abgearbeitet" in summary.message(bounded=True)
    assert "Hinweis:" not in summary.message(bounded=True)


def test_run_summary_marks_a_genuinely_unfinished_persistent_batch():
    entries = [
        MailRunEntry(account_id="a", folder="INBOX", uidvalidity=1, uid=1,
                     status="completed", analysis_terminal="completed"),
        MailRunEntry(account_id="a", folder="INBOX", uidvalidity=1, uid=2,
                     status="queued"),
        MailRunEntry(account_id="a", folder="INBOX", uidvalidity=1, uid=3,
                     status="processing"),
    ]
    summary = _RunSummary.from_run(_persisted_run(entries))
    assert (summary.discovered, summary.queued, summary.processed) == (3, 1, 1)
    assert summary.run_complete is False
    assert summary.message().startswith("Mailhelp-Lauf abgebrochen oder unvollständig.")
    assert _RunSummary.from_run(None).run_complete is False


def test_bounded_run_limits_resumed_and_new_mail_then_exits(tmp_path):
    pending=MailState(id="a"*24,config_fingerprint="0"*64,imap={"account_id":"0"*24,"folder":"INBOX","uidvalidity":7,"uid":2})
    key=_checkpoint_name("0"*24,"INBOX")
    store=Store({"mail-a":pending.model_dump(mode="json"),key:{"uidvalidity":7,"uid":2,"start_uid":2}})
    mail3=FetchedMail("INBOX",7,3,b"x")
    mail4=FetchedMail("INBOX",7,4,b"x")
    service=app(tmp_path,Imap([(7,[mail3,mail4])]),Telegram([]),Orch(),store=store)

    service.run(max_mails=2)

    assert service.orchestrator.seen == [2,3]
    assert service.imap.calls == [("INBOX",2,7,1,())]
    assert service.telegram.offsets == [0]
    assert store.values[key]["uid"] == 3
    assert not service.stop_event.is_set()


def test_mail_budget_and_limit_consumed_by_resume_before_folder_poll(tmp_path):
    budget=_MailBudget(1)
    assert budget.take() is None
    assert budget.remaining == 0
    explicit_blocked_budget=_MailBudget(1,2)
    explicit_blocked_budget.take_blocked()
    assert explicit_blocked_budget.blocked_remaining == 1

    pending=MailState(id="a"*24,config_fingerprint="0"*64,imap={"account_id":"0"*24,"folder":"INBOX","uidvalidity":7,"uid":2})
    service=app(tmp_path,Imap([]),Telegram([]),Orch(),store=Store({"mail-a":pending.model_dump(mode="json")}))
    assert len(service._poll_imap(max_mails=1)) == 1
    assert service.imap.calls == []


def test_fingerprint_blocked_backlog_has_separate_limit_and_does_not_starve_new_mail(tmp_path):
    active="a"*64
    blocked={
        f"mail-blocked-{number}": MailState(
            id=f"{number:024x}", config_fingerprint="b"*64,
            imap={"account_id":"0"*24,"folder":"INBOX","uidvalidity":7,"uid":number},
        ).model_dump(mode="json")
        for number in range(1, 5)
    }
    key=_checkpoint_name("0"*24,"INBOX")
    store=Store({**blocked,key:{"uidvalidity":7,"uid":4,"start_uid":1}})
    new=[FetchedMail("INBOX",7,5,b"x"),FetchedMail("INBOX",7,6,b"x")]
    service=app(tmp_path,Imap([(7,new)]),Telegram([]),Orch(config_fingerprint=active),store=store)

    results=service._poll_imap(max_mails=2)

    assert [result.outcome for result in results] == [
        ProcessingOutcome.WAITING, ProcessingOutcome.WAITING,
        ProcessingOutcome.COMPLETED, ProcessingOutcome.COMPLETED,
    ]
    assert service.imap.uid_calls == []
    assert service.orchestrator.seen == [5,6]
    assert store.values[key]["uid"] == 6
    assert len([event for event in service.logger.events
                if event[0][2] == "configuration_changed"]) == 2

    restarted=app(tmp_path,Imap([(7,[])]),Telegram([]),Orch(config_fingerprint=active),store=store)
    restarted_results=restarted._poll_imap(max_mails=2)
    assert len(restarted_results) == 2
    assert restarted.imap.uid_calls == []
    assert restarted.orchestrator.seen == []


def test_resume_mixes_matching_and_blocked_fingerprints_without_resuming_blocked(tmp_path):
    active="a"*64
    states={}
    for suffix, uid, fingerprint in (("a",1,active),("b",2,"b"*64),("c",3,active)):
        states[f"mail-{suffix}"]=MailState(
            id=suffix*24, config_fingerprint=fingerprint,
            imap={"account_id":"0"*24,"folder":"INBOX","uidvalidity":7,"uid":uid},
        ).model_dump(mode="json")
    service=app(tmp_path,Imap([]),Telegram([]),Orch(config_fingerprint=active),store=Store(states))

    results=service._resume_pending(_MailBudget(2))

    assert [result.outcome for result in results] == [
        ProcessingOutcome.COMPLETED, ProcessingOutcome.WAITING,
        ProcessingOutcome.COMPLETED,
    ]
    assert service.imap.uid_calls == [("INBOX",1,7),("INBOX",3,7)]
    assert service.orchestrator.seen == [1,3]


def test_resume_due_pending_states_and_isolate_failures(tmp_path):
    class LegacyStore:
        def load(self,name,default=None): return default
        def save(self,name,value): pass
    legacy=app(tmp_path,Imap([]),Telegram([]),Orch(),store=LegacyStore())
    assert legacy._resume_pending()==[]
    due=MailState(id="a"*24,config_fingerprint="0"*64,imap={"account_id":"0"*24,"folder":"INBOX","uidvalidity":7,"uid":4})
    future=MailState(id="b"*24,config_fingerprint="0"*64,imap={"account_id":"0"*24,"folder":"INBOX","uidvalidity":7,"uid":5},deferred_until=datetime.now(timezone.utc)+timedelta(hours=1))
    completed=MailState(id="c"*24,config_fingerprint="0"*64,imap={"account_id":"0"*24,"folder":"INBOX","uidvalidity":7,"uid":6})
    completed.steps.completion="completed"
    store=Store({"mail-a":due.model_dump(mode="json"),"mail-b":future.model_dump(mode="json"),"mail-c":completed.model_dump(mode="json"),"mail-missing":None})
    imap=Imap([]); orch=Orch(); service=app(tmp_path,imap,Telegram([]),orch,store=store)
    results=service._resume_pending()
    assert imap.uid_calls==[("INBOX",4,7)] and orch.seen==[4]
    assert results[0].outcome is ProcessingOutcome.COMPLETED

    failed_orch=Orch()
    failed_orch.process=lambda mail: ProcessingResult(ProcessingOutcome.FAILED,{"error":{"type":"RuntimeError","message":"resume"}})
    failed_service=app(tmp_path,Imap([]),Telegram([]),failed_orch,store=Store({"mail-a":due.model_dump(mode="json")}))
    assert failed_service._resume_pending()[0].outcome is ProcessingOutcome.FAILED
    assert failed_service.logger.events[0][0][2]=="resume_failed"

    class BrokenImap(Imap):
        def fetch_uid(self,*args): raise RuntimeError("gone")
    broken=app(tmp_path,BrokenImap([]),Telegram([]),Orch(),store=Store({"mail-a":due.model_dump(mode="json")}))
    broken._resume_pending()
    assert broken.logger.events[0][0][2]=="resume_failed"
    broken.stop_event.set(); broken._resume_pending()


@pytest.mark.parametrize(("mode","starttls"), [("ssl",False),("starttls",True),("plain",False)])
def test_composition_cleanup_and_build_failure(tmp_path, monkeypatch, mode, starttls):
    closed=[]
    class Resource:
        def __init__(self,*args,**kwargs): pass
        def close(self): closed.append(type(self).__name__)
        def check_access(self,*args): pass
    class FakeImap(Resource):
        kwargs={}
        def __init__(self,*args,**kwargs): type(self).kwargs=kwargs
    class FakeOpen(Resource): pass
    class FakeTelegram(Resource):
        def send(self,*args): pass
    class FakeWriter(Resource):
        calls=[]
        def __init__(self,*args,**kwargs):
            type(self).calls.append((args,kwargs))
    class FakeOAuth(Resource):
        calls=[]
        def __init__(self,*args,**kwargs): type(self).calls.append((args,kwargs))
    monkeypatch.setattr("mailhelp.application.ImapReader",FakeImap)
    monkeypatch.setattr("mailhelp.application.OpenRouterClient",FakeOpen)
    monkeypatch.setattr("mailhelp.application.TelegramClient",FakeTelegram)
    monkeypatch.setattr("mailhelp.application.HttpWriter",FakeWriter)
    monkeypatch.setattr("mailhelp.application.GoogleOAuthTokenProvider",FakeOAuth)
    cfg=settings(tmp_path); cfg.imap.connection_mode=mode
    cfg.logging.file.enabled = False
    cfg.logging.file.level = "CRITICAL"
    cfg.logging.console.enabled = False
    cfg.logging.console.level = "ERROR"
    cfg.logging.modules = {"access_check": "CRITICAL"}
    sec=Secrets(imap_username="u",imap_password="p",openrouter_api_key="o",telegram_bot_token="t",todoist_token="d",todoist_client_id="ti",todoist_client_secret="ts",google_oauth_client_id="i",google_oauth_client_secret="s",google_oauth_refresh_token="r")
    topic=[Topic(id="x",name="x",enabled=True,description="x")]
    diagnostics = mode == "ssl"
    supplied_logger = build_logger(cfg, sec, tmp_path) if mode == "starttls" else None
    overridden_logger = build_logger(cfg, sec, tmp_path, log_directory=tmp_path / "override-logs")
    assert overridden_logger.app == tmp_path / "override-logs/application.jsonl"
    with build_application(
        cfg, sec, topic, prompt_config(), "f" * 64,
        base_directory=tmp_path, access_diagnostics=diagnostics,
        logger=supplied_logger,
    ) as made:
        assert made.todoist and (tmp_path/"data/test/.lock").exists()
        assert made.sender_store.directory == tmp_path
        assert made.orchestrator.sender_store is made.sender_store
        assert made.dialog.relevance_handler is made.orchestrator
        assert made.dialog.revision_service is made.analyzer
        assert made.orchestrator.config_fingerprint == "f"*64
        assert FakeImap.kwargs["starttls"] is starttls
        assert FakeImap.kwargs["batch_size"] == 25
        assert FakeImap.kwargs["factory"].__name__ == ("IMAP4_SSL" if mode=="ssl" else "IMAP4")
        assert FakeOAuth.calls[-1][0][:3] == ("i", "s", "r")
        calendar_args, calendar_kwargs = FakeWriter.calls[-1]
        assert calendar_args[0] == "google_calendar"
        assert isinstance(calendar_args[1], FakeOAuth) and calendar_args[2] == "c"
        assert calendar_kwargs["calendar_timezone"] == "UTC"
        assert made.logger.file_enabled is diagnostics
        assert made.logger.console_enabled is diagnostics
        assert made.logger.level == ("DEBUG" if diagnostics else "CRITICAL")
        assert made.logger.console_level == ("DEBUG" if diagnostics else "ERROR")
        assert made.logger.module_levels == ({} if diagnostics else {"access_check": "CRITICAL"})
        if supplied_logger is not None:
            assert made.logger is supplied_logger
    assert len(closed)==6 and (tmp_path/"data/test/.lock").exists()

    closed.clear()
    class BrokenImap(Resource):
        def __init__(self,*args,**kwargs): raise RuntimeError("authentication failed")
    monkeypatch.setattr("mailhelp.application.ImapReader",BrokenImap)
    with build_application(
        cfg, sec, topic, prompt_config(), "f" * 64,
        base_directory=tmp_path, access_diagnostics=True,
    ) as made:
        assert made.check_access() == {
            "IMAP": "authentication failed", "OpenRouter": None,
            "Telegram": None, "Todoist": None, "Google Kalender": None,
        }
    assert len(closed) == 5
    with pytest.raises(RuntimeError, match="authentication failed"):
        with build_application(
            cfg, sec, topic, prompt_config(), "f" * 64,
            base_directory=tmp_path,
        ):
            pass

    cfg.data_directory=Path("relative"); cfg.logging.directory=Path("relative-logs")
    monkeypatch.setattr("mailhelp.application.ImapReader",FakeImap)
    class BrokenTelegram(Resource):
        def __init__(self,*args,**kwargs): raise RuntimeError("build")
    monkeypatch.setattr("mailhelp.application.TelegramClient",BrokenTelegram)
    with pytest.raises(RuntimeError,match="build"):
        with build_application(cfg,sec,topic,prompt_config(),"f"*64,base_directory=tmp_path): pass
    assert (tmp_path/"relative/test/.lock").exists()


def test_state_directory_separates_every_durable_state_and_lock(tmp_path):
    test_settings=settings(tmp_path)
    production_settings=settings(tmp_path)
    production_settings.test_mode=False
    assert _state_directory(test_settings,tmp_path)==tmp_path/"data/test"
    assert _state_directory(production_settings,tmp_path)==tmp_path/"data/production"

    state_names=(
        _checkpoint_name("0"*24,"INBOX"), "mail-same", "telegram-offset",
        "telegram-dialog", "proposal-same", "proposal-same-v1", "llm-budget",
    )
    from mailhelp.storage import JsonStore
    with JsonStore(_state_directory(test_settings,tmp_path)) as test_store:
        with JsonStore(_state_directory(production_settings,tmp_path)) as production_store:
            for name in state_names:
                test_store.save(name,{"mode":"test"})
                production_store.save(name,{"mode":"production"})
            assert (test_store.directory/".lock").exists()
            assert (production_store.directory/".lock").exists()
            assert test_store.names()==production_store.names()
            assert all(test_store.load(name)=={"mode":"test"} for name in state_names)
            assert all(production_store.load(name)=={"mode":"production"} for name in state_names)


def test_historical_start_is_persisted_account_scoped_and_uidvalidity_logged(tmp_path):
    boundary=datetime(2025,1,2,3,4,tzinfo=timezone.utc)
    cfg=settings(tmp_path); cfg.imap.historical_start=boundary
    fake=Imap([(8,[])]); fake.account_id="1"*24
    fake.determine_calls=[]
    def initial_boundary(folder, start):
        fake.determine_calls.append((folder,start)); fake.last_uidvalidity=8; return 41
    fake.determine_start_uid=initial_boundary
    store=Store(); service=Application(cfg,store,Log(),fake,object(),object(),Telegram([]),object(),object(),Orch(),__import__('threading').Event())
    service._poll_imap()
    key=_checkpoint_name("1"*24,"INBOX")
    assert fake.determine_calls==[("INBOX",boundary)]
    assert fake.calls==[("INBOX",41,8,None,())] and store.values[key]["start_uid"]==41

    before_boundary=FetchedMail("INBOX",9,1,b"must-not-be-delivered")
    restarted=Imap([(9,[before_boundary]),(9,[])]); restarted.account_id="1"*24
    restarted.determine_start_uid=lambda *_: setattr(restarted,"last_uidvalidity",9) or 42
    again=Application(cfg,store,Log(),restarted,object(),object(),Telegram([]),object(),object(),Orch(),__import__('threading').Event())
    again._poll_imap()
    assert restarted.calls==[("INBOX",41,8,None,()),("INBOX",42,9,None,())]
    assert again.orchestrator.seen==[]
    assert store.values[key]["start_uid"]==42
    assert any(event[0][2]=="uidvalidity_changed" for event in again.logger.events)

    changed=Imap([(3,[])]); changed.account_id="2"*24
    changed.determine_start_uid=lambda *_: setattr(changed,"last_uidvalidity",3) or 7
    other=Application(cfg,store,Log(),changed,object(),object(),Telegram([]),object(),object(),Orch(),__import__('threading').Event())
    other._poll_imap()
    assert _checkpoint_name("2"*24,"INBOX") in store.values

    no_history_store=Store({_checkpoint_name("0"*24,"INBOX"):{"uidvalidity":1,"uid":9,"start_uid":0}})
    no_history=app(tmp_path,Imap([(2,[])]),Telegram([]),Orch(),store=no_history_store)
    no_history._poll_imap()
    assert no_history_store.values[_checkpoint_name("0"*24,"INBOX")]["uid"]==0

    broken=Imap([(10,[]) ]); broken.account_id="1"*24
    broken.determine_start_uid=lambda *_: (_ for _ in ()).throw(RuntimeError("boundary"))
    failed=Application(cfg,store,Log(),broken,object(),object(),Telegram([]),object(),object(),Orch(),__import__('threading').Event())
    failed._poll_imap()
    assert failed.logger.events[-1][0][2]=="poll_failed"

    drifting=Imap([(10,[])]); drifting.account_id="1"*24
    drifting.determine_start_uid=lambda *_: setattr(drifting,"last_uidvalidity",11) or 5
    drifted=Application(cfg,store,Log(),drifting,object(),object(),Telegram([]),object(),object(),Orch(),__import__('threading').Event())
    drifted._poll_imap()
    assert len(drifting.calls)==1 and "während der Grenzermittlung" in drifted.logger.events[-1][1]["error"]

    foreign=MailState(id="f"*24,config_fingerprint="0"*64,imap={"account_id":"9"*24,"folder":"INBOX","uidvalidity":1,"uid":1})
    other.store.values["mail-foreign"]=foreign.model_dump(mode="json")
    assert other._resume_pending()==[] and changed.uid_calls==[]
