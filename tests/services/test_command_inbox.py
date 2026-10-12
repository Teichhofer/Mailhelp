"""Durable web command queue: idempotency, ordering, restart reconciliation, cleanup."""
from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

import pytest
from shared_review import MAIL, OTHER, command, setup
from shared_telegram_dialog import (
    Logger,
    RelevanceHandler,
    RevisionService,
    Telegram,
    Writer,
    proposal,
    relevance_state,
)

from mailhelp.domain.processing import ProposalClarificationState
from mailhelp.models import TelegramDialogState
from mailhelp.review import CommandKind, ResultStatus, ReviewResult
from mailhelp.review.inbox import (
    COMMAND_INBOX,
    MAX_QUEUED,
    CommandConflict,
    CommandInbox,
    CommandInboxFull,
    CommandStatus,
)
from mailhelp.storage import JsonStore
from mailhelp.telegram import TelegramDialogController


def with_commands(store, dialog, clock=None):
    """Attach a command inbox to a controller built by the review test helpers."""
    inbox = CommandInbox(store, clock=clock) if clock else CommandInbox(store)
    dialog.commands = inbox
    dialog.review.web_authorizer = lambda actor: actor == "web:session"
    return inbox


def restarted(store, writers=None, inbox=None):
    """A fresh controller on the same store, as after a process restart."""
    dialog = TelegramDialogController(store, Telegram(), 1, 2, Logger(), writers, False, "UTC",
                                      RevisionService(), commands=inbox or CommandInbox(store))
    dialog.review.web_authorizer = lambda actor: actor == "web:session"
    return dialog


def test_a_repeated_submission_has_no_second_effect(tmp_path):
    writer = Writer()
    with JsonStore(tmp_path) as store:
        dialog, _, log = setup(store, proposal(), writers={"todoist": writer})
        inbox = with_commands(store, dialog)
        first, new = inbox.submit(command(CommandKind.CONFIRM))
        # A browser timeout followed by a retry sends the same key again.
        again, repeated = inbox.submit(command(CommandKind.CONFIRM))
        assert (new, repeated) == (True, False) and again.id == first.id
        dialog.poll_once()
        retry, _ = inbox.submit(command(CommandKind.CONFIRM))
        dialog.poll_once()
        assert writer.created == 1
        assert retry.status == CommandStatus.DONE
        assert retry.result == ReviewResult(status=ResultStatus.WRITTEN, message="Angelegt.")
        assert ("INFO", "review", "command_finished") in [args for args, _ in log.events]


def test_a_reused_key_for_another_command_is_refused(tmp_path):
    with JsonStore(tmp_path) as store:
        inbox = CommandInbox(store)
        inbox.submit(command(CommandKind.CONFIRM))
        with pytest.raises(CommandConflict):
            inbox.submit(command(CommandKind.REJECT))


def test_the_queue_is_bounded_and_wakes_the_main_thread(tmp_path):
    woken = []
    with JsonStore(tmp_path) as store:
        inbox = CommandInbox(store, wake=lambda: woken.append(1))
        for index in range(MAX_QUEUED):
            inbox.submit(command(CommandKind.REJECT, key=f"key-{index:08d}"))
        with pytest.raises(CommandInboxFull):
            inbox.submit(command(CommandKind.REJECT, key="key-overflow"))
        assert len(woken) == MAX_QUEUED and len(inbox.queued()) == MAX_QUEUED
        assert inbox.get("0" * 32) is None


def test_commands_run_in_arrival_order_with_typed_outcomes(tmp_path):
    with JsonStore(tmp_path) as store:
        dialog, _, log = setup(store, proposal(), proposal(id="p2", open_questions=["Ort?"]))
        inbox = with_commands(store, dialog)
        rejected, _ = inbox.submit(command(CommandKind.CONFIRM, proposal_id="p2", key="key-first"))
        done, _ = inbox.submit(command(CommandKind.REJECT, key="key-second"))
        stale, _ = inbox.submit(command(CommandKind.REJECT, key="key-third"))
        dialog.poll_once()
        statuses = [inbox.get(entry.id).status for entry in (rejected, done, stale)]
        assert statuses == [CommandStatus.REJECTED, CommandStatus.DONE, CommandStatus.REJECTED]
        assert inbox.get(rejected.id).result.status == ResultStatus.NEEDS_ANSWER
        assert inbox.queued() == []


def test_an_unexpected_failure_is_recorded_without_details(tmp_path, monkeypatch):
    with JsonStore(tmp_path) as store:
        dialog, _, log = setup(store, proposal())
        inbox = with_commands(store, dialog)
        entry, _ = inbox.submit(command(CommandKind.REJECT))

        def broken(*_args, **_kwargs):
            raise RuntimeError("secret provider detail")

        monkeypatch.setattr(dialog.review, "execute", broken)
        dialog.poll_once()
        stored = inbox.get(entry.id)
        assert stored.status == CommandStatus.FAILED
        assert "secret" not in stored.result.message
        failure = next(fields for args, fields in log.events if args[2] == "command_failed")
        assert failure["error_class"] == "RuntimeError" and "secret" not in str(failure)


def test_queued_commands_survive_a_restart(tmp_path):
    with JsonStore(tmp_path) as store:
        setup(store, proposal())
        entry, _ = CommandInbox(store).submit(command(CommandKind.REJECT))
        restarted(store).poll_once()
        assert CommandInbox(store).get(entry.id).status == CommandStatus.DONE
        assert store.load(f"proposal-{MAIL}-p1")["status"] == "rejected"


def interrupt(store, *commands):
    """Leave commands in the running state, as after a crash during execution."""
    inbox = CommandInbox(store)
    entries = [inbox.submit(item)[0] for item in commands]
    for entry in entries:
        inbox.start(entry.id)
    return inbox, entries


def test_a_running_confirmation_is_reconciled_not_repeated(tmp_path):
    writer = Writer()
    with JsonStore(tmp_path) as store:
        setup(store, proposal(), proposal(id="p2"))
        # p1 was already confirmed before the crash; p2 had no visible effect.
        store.save(f"proposal-{MAIL}-p1", proposal(status="confirmed").model_dump(mode="json"))
        inbox, (applied, lost) = interrupt(
            store, command(CommandKind.CONFIRM, key="key-applied"),
            command(CommandKind.CONFIRM, proposal_id="p2", key="key-lost"))
        restarted(store, {"todoist": writer}, inbox).poll_once()
        assert inbox.get(applied.id).status == CommandStatus.DONE
        assert inbox.get(lost.id).status == CommandStatus.FAILED
        assert "erneut auslösen" in inbox.get(lost.id).result.message
        # Only the write executor completes the confirmed version; p2 stays open.
        assert writer.versions == [1]
        assert store.load(f"proposal-{MAIL}-p2")["status"] == "pending_confirmation"


def test_reconciliation_of_clarification_answer_cancel_and_relevance(tmp_path):
    with JsonStore(tmp_path) as store:
        setup(store, proposal(id="edit"), proposal(id="answer", open_questions=["Ort?"]),
              proposal(id="cancel"), proposal(id="unanswered", open_questions=["Ort?"]))
        store.save(f"mail-{OTHER}", relevance_state(OTHER).model_dump(mode="json"))
        store.save("telegram-dialog", TelegramDialogState(
            mail_id=MAIL, proposal_id="edit", version=1).model_dump(mode="json"))
        store.save(f"clarification-{MAIL}-answer-v1", ProposalClarificationState(
            mail_id=MAIL, proposal_id="answer", version=1, question="Ort?",
            authorized_answer="Raum 3").model_dump(mode="json"))
        commands = {
            "edit": command(CommandKind.START_CLARIFICATION, proposal_id="edit", key="key-edit"),
            "cancel_edit": command(CommandKind.CANCEL_CLARIFICATION, proposal_id="edit", key="key-c-edit"),
            "cancel": command(CommandKind.CANCEL_CLARIFICATION, proposal_id="cancel", key="key-cancel"),
            "clarify": command(CommandKind.START_CLARIFICATION, proposal_id="cancel", key="key-clarify"),
            "answer": command(CommandKind.ANSWER, proposal_id="answer", text="Raum 3", key="key-answer"),
            "unanswered": command(CommandKind.ANSWER, proposal_id="unanswered", text="x", key="key-unans"),
            "missing": command(CommandKind.REJECT, proposal_id="missing", key="key-missing"),
            "relevance": command(CommandKind.RELEVANCE, mail_id=OTHER, decision="relevant", key="key-relev"),
        }
        inbox, entries = interrupt(store, *commands.values())
        dialog = restarted(store, inbox=inbox)
        dialog.relevance_handler = RelevanceHandler(store)
        assert inbox.recover(dialog.review.reconcile) == len(commands)
        outcome = {name: inbox.get(entry.id).status for name, entry in zip(commands, entries, strict=False)}
    assert outcome == {
        "edit": CommandStatus.DONE, "cancel_edit": CommandStatus.FAILED,
        "cancel": CommandStatus.DONE, "clarify": CommandStatus.FAILED,
        "answer": CommandStatus.DONE, "unanswered": CommandStatus.FAILED,
        "missing": CommandStatus.FAILED, "relevance": CommandStatus.FAILED,
    }


def test_a_decided_relevance_question_counts_as_done_after_a_restart(tmp_path):
    with JsonStore(tmp_path) as store:
        store.save(f"mail-{OTHER}", relevance_state(OTHER).model_dump(mode="json"))
        RelevanceHandler(store).resolve_relevance(OTHER, 1, "relevant", 5)
        inbox, (entry,) = interrupt(store, command(CommandKind.RELEVANCE, mail_id=OTHER,
                                                   decision="relevant"))
        restarted(store, inbox=inbox).poll_once()
        assert inbox.get(entry.id).status == CommandStatus.DONE


def test_recovery_runs_once_per_process(tmp_path):
    with JsonStore(tmp_path) as store:
        setup(store, proposal())
        dialog = restarted(store)
        dialog.poll_once()
        # Marked running by this process right now; a second poll must not touch it.
        entry, _ = dialog.commands.submit(command(CommandKind.REJECT))
        dialog.commands.start(entry.id)
        dialog._process_commands()
        dialog.poll_once()
        assert dialog.commands.get(entry.id).status == CommandStatus.RUNNING


def test_finished_entries_are_removed_after_a_day(tmp_path):
    now = [datetime(2026, 10, 11, 12, tzinfo=UTC)]
    with JsonStore(tmp_path) as store:
        inbox = CommandInbox(store, clock=lambda: now[0])
        old, _ = inbox.submit(command(CommandKind.REJECT, key="key-older"))
        waiting, _ = inbox.submit(command(CommandKind.REJECT, key="key-waiting"))
        inbox.finish(old.id, ReviewResult(status=ResultStatus.DONE, message="ok"))
        now[0] += timedelta(days=1, seconds=1)
        fresh, _ = inbox.submit(command(CommandKind.REJECT, key="key-fresh"))
        inbox.finish(fresh.id, ReviewResult(status=ResultStatus.DONE, message="ok"))
        assert inbox.get(old.id) is None
        assert inbox.get(waiting.id).status == CommandStatus.QUEUED
        assert inbox.get(fresh.id).status == CommandStatus.DONE
        assert store.load(COMMAND_INBOX)["schema_version"] == 1


def test_parallel_submissions_and_processing_lose_nothing(tmp_path):
    with JsonStore(tmp_path) as store:
        items = [proposal(id=f"p{index}") for index in range(20)]
        dialog, _, _ = setup(store, *items)
        inbox = with_commands(store, dialog)
        errors = []

        def submit(index):
            try:
                inbox.submit(command(CommandKind.REJECT, proposal_id=f"p{index}", key=f"key-{index:08d}"))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=submit, args=(index,)) for index in range(20)]
        for thread in threads:
            thread.start()
        while any(thread.is_alive() for thread in threads):
            dialog._process_commands()
        for thread in threads:
            thread.join()
        dialog._process_commands()
        assert errors == []
        assert all(store.load(f"proposal-{MAIL}-p{index}")["status"] == "rejected" for index in range(20))
