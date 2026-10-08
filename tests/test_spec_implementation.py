"""Regression tests for the specification audit, using synthetic services only."""
from types import SimpleNamespace
from pathlib import Path
import yaml
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from mailhelp.analysis import Analyzer
from mailhelp.application import Application
from mailhelp.imap import FetchedMail
from mailhelp.logging import NullLogger
from mailhelp.storage import JsonStore
from mailhelp.models import ProposalStatus
from test_application import app, Imap, Orch, Telegram
from test_core import prompt_config
from test_telegram_dialog import controller, callback
from test_review_write_safety import reminder
from test_quality_corpus import load_corpus, prompt_config as quality_prompts
from mailhelp.config import Topic
from mailhelp.orchestrator import Orchestrator, ProcessingOutcome


@pytest.mark.parametrize("kind", ["tasks", "events"])
def test_valid_empty_extraction_is_not_a_schema_failure(kind):
    calls = []
    class Provider:
        def complete(self, *args, **kwargs):
            calls.append(args)
            return "synthetic-call", {"schema_version": 1, kind: []}
    analyzer = Analyzer(Provider(), prompt_config(), validation_retries=0)
    call, result = getattr(analyzer, "extract_" + kind)({}, expected_count=1)
    assert getattr(result, kind) == []
    assert call == "synthetic-call" and len(calls) == 1


def test_open_proposal_does_not_wait_or_stop_bounded_batch(tmp_path):
    class Dialog:
        polls = 0
        def awaiting_decision(self): return True
        def awaiting_relevance_decision(self): return False
        def show_open_decisions(self): pass
        def poll_once(self, timeout=None):
            self.polls += 1
            service.stop_event.set()  # deterministic failure instead of hanging
    service = app(tmp_path, Imap([(7, [FetchedMail("INBOX", 7, uid, b"x")
                                     for uid in (1, 2)])]), Telegram([]), Orch())
    service.dialog = Dialog()
    service.run(max_mails=2)
    assert service.orchestrator.seen == [1, 2]
    assert service.dialog.polls == 0
    assert service.dialog.awaiting_decision()


def test_access_check_reports_unreadable_secondary_folder_and_checks_remaining():
    seen = []
    def check(folders):
        seen.extend(folders)
        if folders == ["Archive"]:
            raise RuntimeError("synthetic failure")
    noop = SimpleNamespace(check_access=lambda: None)
    service = SimpleNamespace(
        settings=SimpleNamespace(imap=SimpleNamespace(folders=["INBOX", "Archive", "Sent"]),
                                 timezone="UTC", telegram=SimpleNamespace(chat_id=1)),
        logger=NullLogger(), imap=SimpleNamespace(check_access=check),
        openrouter=noop, todoist=noop, calendar=noop,
        telegram=SimpleNamespace(check_access=lambda: None, send=lambda *args: None))
    results = Application.check_access(service)
    assert results["IMAP"] is not None and "Archive" in results["IMAP"]
    assert seen == ["INBOX", "Archive", "Sent"]
    assert results["Google Kalender"] is None


@pytest.mark.parametrize("has_headers", [False, True])
def test_duplicate_prompt_does_not_disclose_internal_identifiers(tmp_path, has_headers):
    first = reminder("a" * 24, "Original")
    second = reminder("b" * 24, "Erinnerung")
    with JsonStore(tmp_path) as store:
        dialog, telegram, _ = controller(store)
        if has_headers:
            from mailhelp.models import MailState
            state = MailState(id=first.source_mail_id, config_fingerprint="0" * 64,
                imap={"account_id": "0" * 24, "folder": "INBOX", "uidvalidity": 7, "uid": 1},
                display_headers={"sender": "source@example.test", "subject": "Original source"})
            store.save("mail-" + state.id, state.model_dump(mode="json"))
        dialog.persist(first.model_copy(update={"status": ProposalStatus.CREATED, "external_id": "old"}))
        dialog.send_proposal(second)
        telegram.updates = [callback(1, telegram.sent[-1][2]["inline_keyboard"][0][0]["callback_data"])]
        dialog.poll_once()
        message = next(text for _, text, markup in telegram.sent if markup and
                       markup["inline_keyboard"][0][0]["text"] == "Erneut anlegen")
        assert first.source_mail_id not in message and first.id not in message
        assert "Frühere Quelle" in message
        assert ("Original source" in message) is has_headers


def test_compose_mounts_filter_and_learning_uses_replaceable_directory():
    root = Path(__file__).parents[1]
    production = yaml.safe_load((root / "compose.yaml").read_text(encoding="utf-8"))
    mounts = production["services"]["mailhelp"]["volumes"]
    assert any("/config/irrelevant-senders.json" in str(mount) for mount in mounts)
    learning = yaml.safe_load((root / "compose.learn.yaml").read_text(encoding="utf-8"))
    mounts = learning["services"]["mailhelp"]["volumes"]
    assert any(mount.endswith(":/config") for mount in mounts)
    assert not any("/config/config.yaml" in mount for mount in mounts)


@pytest.mark.parametrize("empty", [False, True])
def test_real_analyzer_count_conflict_retains_other_extraction_and_restart(tmp_path, empty):
    corpus = load_corpus()
    case = next(item for item in corpus["cases"] if item["id"] == "04_task_and_event")
    calls = []
    class Provider:
        def complete(self, model, parameters, system, payload, **metadata):
            stage = metadata["stage"]
            calls.append(stage)
            value = deepcopy(case["expected"][{"action_router": "action_route"}.get(stage, stage)])
            if stage == "action_router": value["task_count"] = 2
            if empty and stage == "task_extraction": value["tasks"] = []
            return "call-" + stage, value
    from test_services import Notify
    notifier = Notify()
    mail = FetchedMail("INBOX", 7, 1, case["raw_email"].encode(), "0" * 24,
                       datetime(2026, 9, 18, 8, 1, tzinfo=timezone.utc))
    with JsonStore(tmp_path) as store:
        analyzer = Analyzer(Provider(), quality_prompts(), validation_retries=0)
        service = Orchestrator(analyzer, store, notifier, 1,
            [Topic.model_validate(item) for item in corpus["topics"]], 100_000,
            user_timezone="Europe/Berlin")
        result = service.process(mail)
        assert result.outcome is ProcessingOutcome.COMPLETED
        assert result.state["steps"]["event_extraction"] == "completed"
        assert len(result.state["event_extraction"]["events"]) == 1
        assert len(result.state["task_extraction"]["tasks"]) == (0 if empty else 1)
        assert "mail_question_resolution" not in calls
        if not empty:
            task = result.state["proposals"][0]
            assert task["status"] == "needs_clarification"
            assert task["open_questions"] == ["Wie viele Aufgaben enthält diese Mail tatsächlich?"]
        count = len(calls), len(notifier.messages)
    with JsonStore(tmp_path) as store:
        service.store = store
        again = service.process(mail)
        assert again.outcome is ProcessingOutcome.COMPLETED
        assert (len(calls), len(notifier.messages)) == count
        assert len(again.state["extraction_count_conflicts"]) == 1


def test_real_bounded_batch_sends_all_proposals_and_counts_open_actions(tmp_path):
    from mailhelp.imap import MailCandidate
    from mailhelp.models import MailRunState
    from test_e2e_simulated import FakeTelegram
    from mailhelp.telegram import TelegramDialogController
    corpus = load_corpus()
    case = next(item for item in corpus["cases"] if item["id"] == "04_task_and_event")
    class Provider:
        def complete(self, model, parameters, system, payload, **metadata):
            stage = metadata["stage"]
            return stage, deepcopy(case["expected"][{"action_router": "action_route"}.get(stage, stage)])
    stamp = datetime(2026, 9, 18, 8, 1, tzinfo=timezone.utc)
    class Reader:
        account_id = "0" * 24
        last_uidvalidity = 7
        def discover_since(self, *args):
            return [MailCandidate("INBOX", 7, uid, self.account_id, stamp) for uid in (2, 1)]
        def fetch_uid(self, folder, uid, validity):
            raw = case["raw_email"].replace("04_task_and_event@example.test", f"synthetic-{uid}@example.test")
            return FetchedMail(folder, validity, uid, raw.encode(), self.account_id, stamp)
    with JsonStore(tmp_path / "state") as store:
        telegram = FakeTelegram()
        dialog = TelegramDialogController(store, telegram, 1, 2, NullLogger(), {}, False)
        analyzer = Analyzer(Provider(), quality_prompts(), validation_retries=0)
        orch = Orchestrator(analyzer, store, dialog, 2,
            [Topic.model_validate(item) for item in corpus["topics"]], 100_000,
            user_timezone="Europe/Berlin")
        service = app(tmp_path, Reader(), telegram, Orch(), store=store, global_newest_first=True)
        service.orchestrator = orch
        service.dialog = dialog
        service.run(max_mails=2)
        assert not telegram.polls
        assert sum(markup is not None for _, _, markup in telegram.sent) == 4
        run = store.load_model("mail-run-" + Reader.account_id, MailRunState)
        assert run.counters.waiting_for_user == 2
        assert run.run_complete
        assert [entry.analysis_terminal for entry in run.entries] == ["completed", "completed"]
    # A fresh controller can act on every displayed version without reanalysis.
    from mailhelp.models import Proposal
    from mailhelp.telegram import Decision, DecisionAction
    with JsonStore(tmp_path / "state") as store:
        dialog, telegram, _ = controller(store)
        proposals = [store.load_model(name, Proposal) for name in store.names("proposal-") if "-v" not in name]
        for index, proposal in enumerate(proposals):
            decision = Decision(mail_id=proposal.source_mail_id, proposal_id=proposal.id,
                                version=proposal.version, action=DecisionAction.REJECT)
            telegram.updates = [callback(index * 2 + 1, decision.encode(store), user=999)]
            dialog.poll_once()
            assert dialog.repository.load_current(proposal.source_mail_id, proposal.id).status == ProposalStatus.PENDING_CONFIRMATION
            telegram.updates = [callback(index * 2 + 2, decision.encode(store))]
            dialog.poll_once()
        run = store.load_model("mail-run-" + Reader.account_id, MailRunState)
        assert run.counters.waiting_for_user == 0 and run.counters.completed == 2
        # Replaying persistence after a crash keeps counters unchanged.
        current = dialog.repository.load_current(proposals[-1].source_mail_id, proposals[-1].id)
        dialog.persist(current)
        assert store.load_model("mail-run-" + Reader.account_id, MailRunState) == run


@pytest.mark.parametrize("decision", ["relevant", "irrelevant"])
def test_regression_held_relevance_keeps_queue_incomplete_and_resumes(tmp_path, decision):
    from mailhelp.imap import MailCandidate
    from mailhelp.models import MailState, MailRunState, ImapCheckpoint
    from mailhelp.application import _checkpoint_name
    from test_telegram_outbox import item, stored, A, shown
    corpus = load_corpus()
    case = next(case for case in corpus["cases"] if case["id"] == "02_task_only")
    calls = []
    class Provider:
        def complete(self, model, parameters, system, payload, **metadata):
            stage = metadata["stage"]
            subject = payload["mail"]["headers"]["subject"]
            calls.append((subject, stage))
            if subject == "Mail B" and stage == "relevance":
                return "call", {"decision": "unclear", "topic_ids": [], "reason": "Synthetic ambiguity"}
            return "call", deepcopy(case["expected"][{"action_router": "action_route"}.get(stage, stage)])
    stamp = datetime(2026, 9, 18, 8, 1, tzinfo=timezone.utc)
    class Reader:
        account_id = "0" * 24
        last_uidvalidity = 7
        def discover_since(self, *args):
            return [MailCandidate("INBOX", 7, uid, self.account_id, stamp) for uid in (2, 3)]
        def fetch_uid(self, folder, uid, validity):
            lines = case["raw_email"].splitlines()
            lines = [f"Subject: Mail {'B' if uid == 2 else 'C'}" if line.startswith("Subject:")
                     else f"Message-ID: <synthetic-{uid}@example.test>" if line.startswith("Message-ID:")
                     else line for line in lines]
            return FetchedMail(folder, validity, uid, "\n".join(lines).encode(), self.account_id, stamp)
    def setup(store):
        dialog, telegram, _ = controller(store)
        orch = Orchestrator(Analyzer(Provider(), quality_prompts(), validation_retries=0),
                            store, dialog, 2, [Topic.model_validate(t) for t in corpus["topics"]],
                            100_000, user_timezone="Europe/Berlin")
        dialog.relevance_handler = orch
        service = app(tmp_path, Reader(), telegram, Orch(), store=store, global_newest_first=True)
        service.orchestrator, service.dialog = orch, dialog
        # Fail deterministically rather than hang if a hidden question blocks.
        original_poll = dialog.poll_once
        def unexpected_poll(timeout=None):
            service.stop_event.set()
            original_poll(timeout)
        dialog.poll_once = unexpected_poll
        return service, dialog, telegram
    with JsonStore(tmp_path / "state") as store:
        service, dialog, telegram = setup(store)
        first = item(A, "Question A", ["Wann?"])
        stored(store, first)
        state = store.load_model("mail-" + A, MailState)
        state.steps.completion = "completed"
        store.save("mail-" + A, state.model_dump(mode="json"))
        dialog.send_proposal(first)
        service.run(max_mails=2)
        states = [store.load_model(name, MailState) for name in store.names("mail-")
                  if not name.startswith("mail-run-")]
        b = next(state for state in states if state.imap.uid == 2)
        c = next(state for state in states if state.imap.uid == 3)
        assert b.awaiting_relevance and b.steps.completion == "pending"
        assert c.steps.completion == "completed"
        assert not shown(telegram, "Mail B")
        run = store.load_model("mail-run-" + Reader.account_id, MailRunState)
        assert run.entries[0].analysis_terminal is None and not run.run_complete
        checkpoint = store.load_model(_checkpoint_name(Reader.account_id, "INBOX"), ImapCheckpoint)
        assert checkpoint.completed_uid_ranges == [(3, 3)]
    with JsonStore(tmp_path / "state") as store:
        service, dialog, telegram = setup(store)
        assert not dialog.awaiting_relevance_decision()
        telegram.updates = [callback(1, f"proposal:{A}:p1:1:reject")]
        dialog.poll_once()
        service.stop_event.clear()
        assert shown(telegram, "Mail B") and dialog.awaiting_relevance_decision()
        telegram.updates = [callback(2, f"relevance:{b.id}:1:{decision}")]
        dialog.poll_once()
        service.stop_event.clear()
        service._poll_imap(max_mails=2)
        run = store.load_model("mail-run-" + Reader.account_id, MailRunState)
        assert run.run_complete
        assert run.entries[0].analysis_terminal == ("completed" if decision == "relevant" else "irrelevant")
        checkpoint = store.load_model(_checkpoint_name(Reader.account_id, "INBOX"), ImapCheckpoint)
        assert checkpoint.completed_uid_ranges == [(2, 3)]
        assert calls.count(("Mail B", "relevance")) == 1
        assert calls.count(("Mail C", "relevance")) == 1


def test_regression_legacy_reader_does_not_checkpoint_unanswered_relevance(tmp_path):
    from mailhelp.orchestrator import ProcessingResult
    from mailhelp.application import _checkpoint_name
    class Waiting(Orch):
        def process(self, mail):
            self.seen.append(mail.uid)
            return ProcessingResult(ProcessingOutcome.WAITING, {"awaiting_relevance": True}) if mail.uid == 1 else ProcessingResult(ProcessingOutcome.COMPLETED, {})
    reader = Imap([(7, [FetchedMail("INBOX", 7, uid, b"synthetic") for uid in (1, 2)])])
    service = app(tmp_path, reader, Telegram([]), Waiting())
    service._poll_imap(max_mails=2)
    assert service.orchestrator.seen == [1, 2]
    assert service.store.values[_checkpoint_name(reader.account_id, "INBOX")]["completed_uid_ranges"] == [(2, 2)]


def test_regression_held_relevance_does_not_consume_next_run_budget(tmp_path):
    from uuid import uuid4
    from mailhelp.models import MailState, MailRunState, MailRunEntry, MailRunCounters, RelevanceDialog
    from mailhelp.imap import MailCandidate
    from mailhelp.application import _checkpoint_name
    stamp = datetime(2026, 9, 18, tzinfo=timezone.utc)
    class Reader:
        account_id = "0" * 24
        last_uidvalidity = 7
        def __init__(self): self.fetched = []
        def discover_since(self, *args):
            return [MailCandidate("INBOX", 7, uid, self.account_id, stamp) for uid in (2, 3)]
        def fetch_uid(self, folder, uid, validity):
            self.fetched.append(uid)
            return FetchedMail(folder, validity, uid, b"synthetic", self.account_id, stamp)
    with JsonStore(tmp_path / "state") as store:
        state = MailState(id="b" * 24, config_fingerprint="0" * 64,
            imap={"account_id": Reader.account_id, "folder": "INBOX", "uidvalidity": 7, "uid": 2},
            awaiting_relevance=True, relevance_dialog=RelevanceDialog(mail_id="b" * 24))
        store.save("mail-" + state.id, state.model_dump(mode="json"))
        run_state = MailRunState(run_id=uuid4(), created_at=stamp,
            entries=[MailRunEntry(account_id=Reader.account_id, folder="INBOX", uidvalidity=7,
                                 uid=2, status="processing")], counters=MailRunCounters(processing=1))
        store.save("mail-run-" + Reader.account_id, run_state.model_dump(mode="json"))
        reader = Reader()
        service = app(tmp_path, reader, Telegram([]), Orch(), store=store, global_newest_first=True)
        service._poll_imap(max_mails=1)
        assert reader.fetched == [3]
        assert store.load_model("mail-" + state.id, MailState).awaiting_relevance
        assert store.load(_checkpoint_name(Reader.account_id, "INBOX"))["completed_uid_ranges"] == [[3, 3]]
