"""Run summaries, startup help and resuming persisted mail."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from mailhelp.domain.mail import MailState
from mailhelp.domain.run import MailRunCounters, MailRunEntry, MailRunState
from mailhelp.mailbox.imap import FetchedMail
from mailhelp.mailbox.mailbox_run import MailboxRunService, _add_uid, _checkpoint_name, _MailBudget, _RunSummary
from mailhelp.processing.orchestrator import ProcessingOutcome, ProcessingResult
from mailhelp.telegram.commands import HELP, STARTUP
from tests.fakes.factories import build_mail_state
from tests.fakes.shared_application import Imap, Orch, Store, Telegram, _persisted_run, app

# Since 2.3 the writers are built in mailhelp.external.providers.


def test_newest_first_backlog_arrivals_restart_failure_and_folders(tmp_path):
    """Ranges preserve holes while new mail is prioritized across short batches."""
    class BacklogImap:
        account_id="0"*24
        last_uidvalidity=None
        def __init__(self):
            self.available={"INBOX":[4,5,6],"Archive":[2]}
            self.calls=[]
        def fetch_since(self,folder,start,expected,maximum,ranges):
            self.calls.append((folder,start,expected,maximum,ranges))
            self.last_uidvalidity=7
            remaining=[uid for uid in reversed(self.available[folder])
                       if uid>start and not any(a<=uid<=b for a,b in ranges)]
            count=min(2,maximum) if maximum is not None else 2
            return [FetchedMail(folder,7,uid,b"x") for uid in remaining[:count]]
        def fetch_uid(self,*_args): raise AssertionError("no pending state")
    class FailFiveOnce(Orch):
        def __init__(self):
            super().__init__()
            self.failed=False
        def process(self,mail):
            self.seen.append(mail.uid)
            if mail.uid==5 and not self.failed:
                self.failed=True
                raise RuntimeError("synthetic")
            return ProcessingResult(ProcessingOutcome.COMPLETED,{})

    reader=BacklogImap()
    store=Store()
    folders=("INBOX","Archive")
    first=app(tmp_path,reader,Telegram([]),FailFiveOnce(),folders=folders,store=store)
    first.mailbox.poll(max_mails=2)
    key=_checkpoint_name(reader.account_id,"INBOX")
    assert first.orchestrator.seen==[6,5]
    assert store.values[key]["completed_uid_ranges"]==[(6,6)]

    # UID 7 arrives while UID 5 and 4 are still in the durable backlog.  A new
    # Application instance proves that the JSON checkpoint alone is sufficient.
    reader.available["INBOX"].append(7)
    restarted=app(tmp_path,reader,Telegram([]),Orch(),folders=folders,store=store)
    restarted.mailbox.poll(max_mails=2)
    assert restarted.orchestrator.seen==[7,5]
    assert store.values[key]["completed_uid_ranges"]==[(5,7)]
    restarted.mailbox.poll(max_mails=2)
    assert restarted.orchestrator.seen==[7,5,4,2]
    assert store.values[key]["completed_uid_ranges"]==[(4,7)]
    assert store.values[_checkpoint_name(reader.account_id,"Archive")]["completed_uid_ranges"]==[(2,2)]


def test_uid_range_normalization_paths():
    assert _add_uid([(1,1),(4,4)],3)==[(1,1),(3,4)]
    assert _add_uid([(1,2),(4,5)],3)==[(1,5)]
    assert _add_uid([(3,4)],1)==[(1,1),(3,4)]




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
    # One compact line; zero counters (here: still queued) are left out.
    assert service.telegram.sent == [(2, STARTUP), (2, "✅ Lauf abgeschlossen: 5 von 5 Mails geprüft · 2 relevant · 1 irrelevant · 1 warten auf dich · 1 fehlgeschlagen · 1 übersprungen")]
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
    assert broken.telegram.sent[-1][1] == "⏸ Lauf unterbrochen: 0 von 0 Mails geprüft"

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
    assert summary.message(bounded=True).startswith("✅ Lauf abgeschlossen")
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
    assert summary.message() == "⏸ Lauf unterbrochen: 1 von 3 Mails geprüft · 1 relevant · 1 noch offen"
    assert _RunSummary.from_run(None).run_complete is False


@pytest.mark.parametrize("max_mails", [None, 1])
def test_startup_help_once_before_work_and_again_after_restart(tmp_path, max_mails):
    store = Store()
    for _restart in range(2):
        service = app(tmp_path, Imap([]), Telegram([]), Orch(), store=store)
        cycles = []

        def poll_imap(_limit=None, service=service, cycles=cycles):
            assert service.telegram.sent == [(2, STARTUP)]
            cycles.append(1)
            if len(cycles) == 2:
                service.stop_event.set()

        service._poll_imap = poll_imap
        service.stop_event.wait = lambda _delay: False
        service.run(max_mails=max_mails)
        assert len(cycles) == (2 if max_mails is None else 1)
        greetings = [text for _, text in service.telegram.sent if "Mailhelp gestartet." in text]
        assert greetings == [STARTUP]
        # The short greeting points to /hilfe, which lists every command.
        assert "/hilfe" in greetings[0]
        assert all(command in HELP for command in ("/hilfe", "/status", "/offen", "/abbrechen"))
        assert all(chat == service.settings.telegram.chat_id for chat, _ in service.telegram.sent)
        assert any(args[2] == "startup_help_sent" for args, _ in service.logger.events)


def test_startup_help_failure_does_not_block_processing_or_log_provider_content(tmp_path):
    service = app(tmp_path, Imap([(1, [])]), Telegram([]), Orch())
    calls = []
    send = service.telegram.send

    def fail_greeting(chat, text):
        calls.append(text)
        if text == STARTUP:
            raise RuntimeError("synthetic-sensitive-provider-content")
        send(chat, text)

    service.telegram.send = fail_greeting
    assert service.run(max_mails=1) is None
    assert service.imap.calls
    assert len(calls) == 2  # one greeting attempt and the final summary
    errors = [(args, fields) for args, fields in service.logger.events if args[2] == "startup_help_failed"]
    assert errors == [(("ERROR", "telegram", "startup_help_failed"), {"error_class": "RuntimeError"})]
    assert "synthetic-sensitive-provider-content" not in str(service.logger.events)


def test_startup_help_precedes_resumed_decision_without_resolving_it(tmp_path):
    service = app(tmp_path, Imap([]), Telegram([]), Orch())

    def poll_once(timeout=None):
        assert service.telegram.sent == [(2, STARTUP)]
        service.stop_event.set()

    service.dialog = SimpleNamespace(awaiting_decision=lambda: True, awaiting_relevance_decision=lambda: True, poll_once=poll_once)
    service.run()
    assert service.dialog.awaiting_decision()
    assert not service.imap.calls and not service.orchestrator.seen
    assert service.logger.events[-1][0][2] == "run_summary_deferred"
    assert len(service.telegram.sent) == 1


def test_bounded_run_limits_resumed_and_new_mail_then_exits(tmp_path):
    pending=build_mail_state("a"*24,uid=2,sender=None,config_fingerprint="0"*64,imap={"account_id":"0"*24,"uidvalidity":7})
    key=_checkpoint_name("0"*24,"INBOX")
    store=Store({"mail-a":pending.model_dump(mode="json"),key:{"uidvalidity":7,"uid":2,"start_uid":2}})
    mail3=FetchedMail("INBOX",7,3,b"x")
    mail4=FetchedMail("INBOX",7,4,b"x")
    service=app(tmp_path,Imap([(7,[mail3,mail4])]),Telegram([]),Orch(),store=store)

    service.run(max_mails=2)

    assert service.orchestrator.seen == [2,3]
    assert service.imap.calls == [("INBOX",2,7,1,())]
    assert service.telegram.offsets == []
    assert store.values[key]["uid"] == 3
    assert not service.stop_event.is_set()


def test_mail_budget_and_limit_consumed_by_resume_before_folder_poll(tmp_path):
    budget=_MailBudget(1)
    assert budget.take() is None
    assert budget.remaining == 0
    explicit_blocked_budget=_MailBudget(1,2)
    explicit_blocked_budget.take_blocked()
    assert explicit_blocked_budget.blocked_remaining == 1

    pending=build_mail_state("a"*24,uid=2,sender=None,config_fingerprint="0"*64,imap={"account_id":"0"*24,"uidvalidity":7})
    service=app(tmp_path,Imap([]),Telegram([]),Orch(),store=Store({"mail-a":pending.model_dump(mode="json")}))
    assert len(service.mailbox.poll(max_mails=1)) == 1
    assert service.imap.calls == []


def test_max_mail_resume_persists_completion_and_continues_with_unprocessed_mail(tmp_path):
    """A resumed MailState must not leave its fixed max-mails queue entry open."""
    account = "0" * 24
    pending = MailState(
        id="a" * 24, config_fingerprint="0" * 64,
        imap={"account_id": account, "folder": "INBOX", "uidvalidity": 7, "uid": 2},
    )
    entries = [
        MailRunEntry(account_id=account, folder="INBOX", uidvalidity=7, uid=2,
                     status="processing"),
        MailRunEntry(account_id=account, folder="INBOX", uidvalidity=7, uid=1,
                     status="queued"),
    ]
    run = MailRunState(
        run_id="00000000-0000-0000-0000-000000000001", max_mails=2,
        created_at=datetime.now(UTC), entries=entries,
        counters=MailRunCounters(processing=1, queued=1),
    )
    run_name = f"mail-run-{account}"
    store = Store({
        "mail-a": pending.model_dump(mode="json"),
        run_name: run.model_dump(mode="json"),
        _checkpoint_name(account, "INBOX"): {
            "uidvalidity": 7, "uid": 0, "start_uid": 0,
        },
    })
    class DurableImap(Imap):
        def discover_since(self, *_args):
            raise AssertionError("the persisted run must be resumed without discovery")

    reader = DurableImap([])

    first = app(tmp_path, reader, Telegram([]), Orch(), store=store,
                global_newest_first=True)
    assert len(first.mailbox.poll(max_mails=1)) == 1
    persisted = MailRunState.model_validate(store.values[run_name])
    assert [entry.status for entry in persisted.entries] == ["completed", "queued"]
    assert store.values[_checkpoint_name(account, "INBOX")]["completed_uid_ranges"] == [(2, 2)]
    # The production orchestrator persists this transition while completing
    # the resumed mail; the deliberately small test double does not.
    store.values["mail-a"]["steps"]["completion"] = "completed"

    restarted = app(tmp_path, reader, Telegram([]), Orch(), store=store,
                    global_newest_first=True)
    assert len(restarted.mailbox.poll(max_mails=1)) == 1
    assert restarted.orchestrator.seen == [1]
    assert reader.uid_calls == [("INBOX", 2, 7), ("INBOX", 1, 7)]


def test_resumed_run_completion_handles_terminal_variants_and_safe_checkpoints(tmp_path):
    account = "0" * 24
    state = MailState(
        id="a" * 24, config_fingerprint="0" * 64,
        imap={"account_id": account, "folder": "INBOX", "uidvalidity": 7, "uid": 2},
    )

    def service_with(entry, checkpoint=None):
        run = MailRunState(
            run_id="00000000-0000-0000-0000-000000000001", max_mails=1,
            created_at=datetime.now(UTC), entries=[entry],
            counters=MailboxRunService.run_counters([entry]),
        )
        values = {f"mail-run-{account}": run.model_dump(mode="json")}
        if checkpoint is not None:
            values[_checkpoint_name(account, "INBOX")] = checkpoint
        return app(tmp_path, Imap([]), Telegram([]), Orch(), store=Store(values))

    processing = MailRunEntry(
        account_id=account, folder="INBOX", uidvalidity=7, uid=2,
        status="processing",
    )
    duplicate = service_with(processing, {
        "uidvalidity": 8, "uid": 0, "start_uid": 0,
    })
    duplicate.mailbox.complete_resumed_entry(state, ProcessingResult(
        ProcessingOutcome.COMPLETED, {"duplicate": {"outcome": "duplicate", "previous_mail_id": "b"}},
    ))
    assert duplicate.store.load_model(
        f"mail-run-{account}", MailRunState
    ).entries[0].analysis_terminal == "duplicate"
    assert duplicate.store.values[_checkpoint_name(account, "INBOX")]["uidvalidity"] == 8

    waiting = service_with(processing.model_copy(), {
        "uidvalidity": 7, "uid": 1, "start_uid": 0,
    })
    waiting.mailbox.complete_resumed_entry(state, ProcessingResult(
        ProcessingOutcome.WAITING, {"relevance": {"decision": "irrelevant"}},
    ))
    waiting_entry = waiting.store.load_model(
        f"mail-run-{account}", MailRunState
    ).entries[0]
    assert (waiting_entry.status, waiting_entry.analysis_terminal) == (
        "waiting_for_user", "irrelevant"
    )
    assert waiting.store.values[
        _checkpoint_name(account, "INBOX")
    ]["completed_uid_ranges"] == [(1, 2)]

    terminal = MailRunEntry(
        account_id=account, folder="INBOX", uidvalidity=7, uid=2,
        status="completed", analysis_terminal="completed",
    )
    already_done = service_with(terminal)
    already_done.mailbox.complete_resumed_entry(
        state, ProcessingResult(ProcessingOutcome.COMPLETED, {})
    )

    mismatches = [
        MailRunEntry(account_id="other", folder="INBOX", uidvalidity=7, uid=2),
        MailRunEntry(account_id=account, folder="Archive", uidvalidity=7, uid=2),
        MailRunEntry(account_id=account, folder="INBOX", uidvalidity=8, uid=2),
        MailRunEntry(account_id=account, folder="INBOX", uidvalidity=7, uid=3),
    ]
    mismatch_run = MailRunState(
        run_id="00000000-0000-0000-0000-000000000002", max_mails=4,
        created_at=datetime.now(UTC), entries=mismatches,
        counters=MailRunCounters(discovered=4),
    )
    mismatch_service = app(
        tmp_path, Imap([]), Telegram([]), Orch(),
        store=Store({f"mail-run-{account}": mismatch_run.model_dump(mode="json")}),
    )
    mismatch_service.mailbox.complete_resumed_entry(
        state, ProcessingResult(ProcessingOutcome.COMPLETED, {})
    )


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

    results=service.mailbox.poll(max_mails=2)

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
    restarted_results=restarted.mailbox.poll(max_mails=2)
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

    results=service.mailbox.resume_pending(_MailBudget(2))

    assert [result.outcome for result in results] == [
        ProcessingOutcome.COMPLETED, ProcessingOutcome.WAITING,
        ProcessingOutcome.COMPLETED,
    ]
    assert service.imap.uid_calls == [("INBOX",1,7),("INBOX",3,7)]
    assert service.orchestrator.seen == [1,3]

    stopped = app(
        tmp_path, Imap([]), Telegram([]), Orch(config_fingerprint=active),
        store=Store(states),
    )
    stopped.dialog = type("BlockedDialog", (), {
        "awaiting_decision": lambda self: False,
        "awaiting_relevance_decision": lambda self: False,
        "processing_blocked": lambda self: True,
    })()
    assert len(stopped.mailbox.resume_pending(_MailBudget(2))) == 3
    assert stopped.orchestrator.seen == [1,3]


def test_resume_due_pending_states_and_isolate_failures(tmp_path):
    due=build_mail_state("a"*24,uid=4,sender=None,config_fingerprint="0"*64,imap={"account_id":"0"*24,"uidvalidity":7})
    future=build_mail_state("b"*24,uid=5,sender=None,config_fingerprint="0"*64,imap={"account_id":"0"*24,"uidvalidity":7},deferred_until=datetime.now(UTC)+timedelta(hours=1))
    completed=build_mail_state("c"*24,uid=6,sender=None,config_fingerprint="0"*64,imap={"account_id":"0"*24,"uidvalidity":7})
    completed.steps.completion="completed"
    store=Store({"mail-a":due.model_dump(mode="json"),"mail-b":future.model_dump(mode="json"),"mail-c":completed.model_dump(mode="json"),"mail-missing":None})
    imap=Imap([])
    orch=Orch()
    service=app(tmp_path,imap,Telegram([]),orch,store=store)
    results=service.mailbox.resume_pending()
    assert imap.uid_calls==[("INBOX",4,7)] and orch.seen==[4]
    assert results[0].outcome is ProcessingOutcome.COMPLETED

    failed_orch=Orch()
    failed_orch.process=lambda mail: ProcessingResult(ProcessingOutcome.FAILED,{"error":{"type":"RuntimeError","message":"resume"}})
    failed_service=app(tmp_path,Imap([]),Telegram([]),failed_orch,store=Store({"mail-a":due.model_dump(mode="json")}))
    assert failed_service.mailbox.resume_pending()[0].outcome is ProcessingOutcome.FAILED
    assert failed_service.logger.events[0][0][2]=="resume_failed"

    class BrokenImap(Imap):
        def fetch_uid(self,*args): raise RuntimeError("gone")
    broken=app(tmp_path,BrokenImap([]),Telegram([]),Orch(),store=Store({"mail-a":due.model_dump(mode="json")}))
    broken.mailbox.resume_pending()
    assert broken.logger.events[0][0][2]=="resume_failed"
    broken.stop_event.set()
    broken.mailbox.resume_pending()
