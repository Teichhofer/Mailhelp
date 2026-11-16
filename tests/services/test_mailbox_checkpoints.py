"""Mailbox checkpoints, UIDVALIDITY, historical boundary and polling errors."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from mailhelp.app.application import Application
from mailhelp.domain.run import MailRunState
from mailhelp.mailbox.imap import FetchedMail, MailCandidate, UIDValidityChanged
from mailhelp.mailbox.mailbox_run import _checkpoint_name, _MailBudget
from mailhelp.processing.orchestrator import ProcessingOutcome, ProcessingResult
from tests.fakes.log_fakes import RecordingLogger as Log
from tests.fakes.shared_application import Imap, Orch, Store, Telegram, app, settings

# Since 2.3 the writers are built in mailhelp.external.providers.


def test_global_mailbox_checkpoint_failures_restarts_and_dialog(tmp_path):
    stamp = datetime(2026, 1, 1, tzinfo=UTC)
    key = _checkpoint_name("0" * 24, "INBOX")

    class GlobalImap:
        account_id = "0" * 24
        last_uidvalidity = 7
        def __init__(self, discoveries):
            self.discoveries = iter(discoveries)
            self.fetch_error = False
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
    empty.mailbox.poll()
    assert legacy_store.values[key]["completed_uid_ranges"] == []

    fresh_store = Store()
    fresh = app(tmp_path, GlobalImap([[]]), Telegram([]), Orch(), store=fresh_store,
                global_newest_first=True)
    fresh.mailbox.poll()
    assert fresh_store.values[key]["uidvalidity"] == 7

    failed_imap = GlobalImap([RuntimeError("discovery")])
    failed = app(tmp_path, failed_imap, Telegram([]), Orch(),
                 global_newest_first=True)
    assert failed.mailbox.poll() == []
    assert failed.logger.events[-1][0][2] == "poll_failed"

    fetch_imap = GlobalImap([[candidate]])
    fetch_imap.fetch_error = True
    fetch_failed = app(tmp_path, fetch_imap, Telegram([]), Orch(),
                       global_newest_first=True)
    assert fetch_failed.mailbox.poll() == []
    assert fetch_failed.logger.events[-1][0][2] == "mail_failed"

    class FailedOrch(Orch):
        def process(self, mail):
            self.seen.append(mail.uid)
            return ProcessingResult(ProcessingOutcome.FAILED, {"error": "failed"})

    outcome = app(tmp_path, GlobalImap([[candidate]]), Telegram([]), FailedOrch(),
                  global_newest_first=True)
    assert outcome.mailbox.poll()[0].outcome is ProcessingOutcome.FAILED
    assert outcome.logger.events[-1][1]["error"] == "failed"

    class Dialog:
        def __init__(self): self.open = True
        def awaiting_decision(self): return self.open
        def awaiting_relevance_decision(self): return self.open
        def poll_once(self, timeout=None): self.open = False

    dialog = app(tmp_path, GlobalImap([[candidate]]), Telegram([]), Orch(),
                 global_newest_first=True)
    dialog.dialog = Dialog()
    assert len(dialog.mailbox.poll()) == 1
    assert dialog.dialog.open is True

    stopped = app(tmp_path, GlobalImap([]), Telegram([]), Orch(),
                  global_newest_first=True)
    stopped.stop_event.set()
    assert stopped.mailbox.poll() == []
    assert stopped.mailbox.poll_global(_MailBudget(1)) == []

    interrupted = app(tmp_path, GlobalImap([[candidate]]), Telegram([]), Orch(),
                      global_newest_first=True)
    original_discover = interrupted.imap.discover_since
    def discover_and_stop(*args):
        result = original_discover(*args)
        interrupted.stop_event.set()
        return result
    interrupted.imap.discover_since = discover_and_stop
    assert interrupted.mailbox.poll() == []

    two_candidates = [candidate, MailCandidate("INBOX", 7, 6, "0" * 24, stamp)]
    stopped_during_processing = app(
        tmp_path, GlobalImap([two_candidates]), Telegram([]), Orch(stop=True),
        global_newest_first=True,
    )
    assert len(stopped_during_processing.mailbox.poll()) == 1

    technically_blocked = app(
        tmp_path, GlobalImap([two_candidates]), Telegram([]), Orch(),
        global_newest_first=True,
    )
    technically_blocked.dialog = type("BlockedDialog", (), {
        "awaiting_decision": lambda self: False,
        "awaiting_relevance_decision": lambda self: False,
        "processing_blocked": lambda self: True,
    })()
    assert len(technically_blocked.mailbox.poll()) == 2
    blocked_run = MailRunState.model_validate(
        technically_blocked.store.values[f"mail-run-{technically_blocked.imap.account_id}"]
    )
    assert blocked_run.counters.queued == 0
    assert blocked_run.run_complete is True


def test_global_mailbox_uidvalidity_and_historical_boundary(tmp_path):
    stamp = datetime(2026, 1, 1, tzinfo=UTC)
    boundary = stamp - timedelta(days=1)
    key = _checkpoint_name("0" * 24, "INBOX")

    class ChangingImap:
        account_id = "0" * 24
        last_uidvalidity = 7
        def __init__(self, drift=False):
            self.calls = 0
            self.drift = drift
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
    assert len(service.mailbox.poll()) == 1
    assert service.store.values[key]["uidvalidity"] == 8
    assert any(event[0][2] == "uidvalidity_changed" for event in service.logger.events)

    drifting = ChangingImap(drift=True)
    drift_store = Store({key: {"uidvalidity": 7, "uid": 4, "start_uid": 4}})
    drifted = Application(configured, drift_store, Log(), drifting, object(), object(),
                          Telegram([]), object(), object(), Orch(), __import__('threading').Event())
    assert drifted.mailbox.poll() == []
    assert "während der Grenzermittlung" in drifted.logger.events[-1][1]["error"]

    no_history = settings(tmp_path, global_newest_first=True)
    changed = ChangingImap()
    changed_store = Store({key: {"uidvalidity": 7, "uid": 4, "start_uid": 4}})
    reset = Application(no_history, changed_store, Log(), changed, object(), object(),
                        Telegram([]), object(), object(), Orch(), __import__('threading').Event())
    assert len(reset.mailbox.poll()) == 1


def test_global_mailbox_can_ignore_persisted_historical_boundary(tmp_path):
    stamp = datetime(2026, 1, 1, tzinfo=UTC)
    key = _checkpoint_name("0" * 24, "INBOX")

    class Reader:
        account_id = "0" * 24
        last_uidvalidity = 7
        def __init__(self): self.discoveries = []
        def determine_start_uid(self, *_args):
            pytest.fail("historical boundary must be ignored")
        def discover_since(self, folder, start, expected, ranges):
            self.discoveries.append((folder, start, expected, ranges))
            return [MailCandidate(folder, 7, 20, self.account_id, stamp)]
        def fetch_uid(self, folder, uid, validity):
            return FetchedMail(folder, validity, uid, b"older", self.account_id, stamp)

    configured = settings(tmp_path, global_newest_first=True)
    configured.imap.historical_start = stamp
    store = Store({key: {
        "uidvalidity": 7, "uid": 45, "start_uid": 41,
        "completed_uid_ranges": [(42, 45)],
    }})
    reader = Reader()
    service = Application(configured, store, Log(), reader, object(), object(),
                          Telegram([]), object(), object(), Orch(),
                          __import__('threading').Event())

    service.run(max_mails=1, ignore_historical_start=True)
    assert service.orchestrator.seen == [20]
    assert reader.discoveries == [("INBOX", 0, 7, ((42, 45),))]
    assert store.values[key]["start_uid"] == 0


def test_polling_errors_resume_and_stop(tmp_path):
    mail1=FetchedMail("INBOX",7,4,b"x")
    mail2=FetchedMail("INBOX",7,5,b"x")
    store=Store({_checkpoint_name("0"*24, "INBOX"):{"uidvalidity":7,"uid":3},"telegram-offset":{"offset":8}})
    service=app(tmp_path,Imap([(7,[mail1,mail2])]),Telegram([{"update_id":8},{"update_id":10}]),Orch(fail=True),store=store)
    service.mailbox.poll()
    service._poll_telegram()
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
    mixed.mailbox.poll()
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
    results=durable.mailbox.poll()
    assert [result.outcome for result in results]==[ProcessingOutcome.FAILED, ProcessingOutcome.COMPLETED]
    assert durable.orchestrator.seen==[4,5]
    assert durable_store.values[_checkpoint_name("0"*24, "INBOX")]["uid"]==5
    assert durable_store.values[_checkpoint_name("0"*24, "INBOX")]["completed_uid_ranges"]==[(5,5)]
    assert any(e[0][2]=="mail_failed" and e[1]["uid"]==4 for e in durable.logger.events)

    failing=app(tmp_path,Imap([RuntimeError("imap"),(9,[]),(10,[])]),Telegram(RuntimeError("tg")),Orch(),folders=("bad","new","none"))
    failing.mailbox.poll()
    failing._poll_telegram()
    assert len(failing.logger.events)==2
    assert failing.store.values[_checkpoint_name("0"*24, "new")]["uidvalidity"]==9
    assert failing.store.values[_checkpoint_name("0"*24, "none")]["uidvalidity"]==10

    stopped=app(tmp_path,Imap([(1,[mail1,mail2])]),Telegram([]),Orch(stop=True),folders=("INBOX","Other"))
    stopped.mailbox.poll()
    assert stopped.orchestrator.seen==[4]
    stopped.stop()
    assert stopped.stop_event.is_set() and stopped.orchestrator.stop_called

    limited=app(tmp_path,Imap([(7,[mail1])]),Telegram([]),Orch(),store=store)
    limited.mailbox.poll(max_mails=1)
    assert limited.imap.calls == [("INBOX",3,7,1,())]


def test_empty_checkpoint_and_run_paths(tmp_path):
    key=_checkpoint_name("0"*24, "INBOX")
    store=Store({key:{"uidvalidity":4,"uid":12}})
    same=app(tmp_path,Imap([(4,[])]),Telegram([]),Orch(),store=store)
    same.mailbox.poll()
    assert store.values[key]["uid"]==12
    none=app(tmp_path,Imap([(None,[])]),Telegram([]),Orch())
    none.mailbox.poll()
    assert none.store.saved[0][1]["start_uid"] == 0
    none.stop_event.set()
    none.run()
    running=app(tmp_path,Imap([(1,[])]),Telegram([]),Orch())
    running._poll_imap=lambda _limit=None: (running.stop_event.set(), [])[1]
    running.run()
    complete=app(tmp_path,Imap([(1,[])]),Telegram([]),Orch())
    complete._poll_imap=lambda _limit=None: []
    complete._poll_telegram=lambda: complete.stop_event.set()
    complete.run()

    import mailhelp.app.application as application_module
    original = application_module.RetentionService
    class BrokenRetention:
        def __init__(self, *args): pass
        def run(self): raise RuntimeError("private detail")
    application_module.RetentionService = BrokenRetention
    failed_cleanup=app(tmp_path,Imap([(1,[])]),Telegram([]),Orch())
    failed_cleanup._poll_imap=lambda _limit=None: (failed_cleanup.stop_event.set(), [])[1]
    failed_cleanup.run()
    application_module.RetentionService = original
    assert failed_cleanup.logger.events[0][0][2]=="startup_help_sent"
    assert failed_cleanup.logger.events[1][0][2]=="cleanup_failed"
    assert failed_cleanup.logger.events[1][1]["failure_count"]==1
    assert datetime.fromisoformat(failed_cleanup.logger.events[1][1]["processed_at"]).tzinfo is not None

    class Dialog:
        def __init__(self, error=None):
            self.calls=0
            self.error=error
        def poll_once(self, timeout=None):
            self.calls += 1
            if self.error: raise self.error
    dialog_app=app(tmp_path,Imap([(1,[])]),Telegram([]),Orch())
    dialog_app.dialog=Dialog()
    dialog_app._poll_telegram()
    assert dialog_app.dialog.calls==1
    failed_dialog=app(tmp_path,Imap([(1,[])]),Telegram([]),Orch())
    failed_dialog.dialog=Dialog(RuntimeError("dialog"))
    failed_dialog._poll_telegram()
    assert failed_dialog.logger.events[0][0][2]=="poll_failed"
