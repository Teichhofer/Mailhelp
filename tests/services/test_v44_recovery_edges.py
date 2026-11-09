"""4.4: integrity, races and restarts of the lock-free web admission (synthetic disk)."""
import json
import shutil
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

import mailhelp.review.incoming as incoming
from mailhelp.configuration import AdminCommand, AdminKind
from mailhelp.review import CommandKind, ResultStatus, ReviewResult
from mailhelp.review.commands import CommandSource
from mailhelp.review.inbox import (
    COMMAND_INBOX,
    CommandConflict,
    CommandEntry,
    CommandInbox,
    CommandInboxFull,
    CommandStatus,
)
from mailhelp.review.incoming import IncomingRecord, key_hash, record_payload
from mailhelp.storage import JsonStore
from tests.fakes.shared_review import command, setup

NOW = datetime(2026, 11, 7, 12, tzinfo=UTC)


def telegram(kind=CommandKind.REJECT, key="key-telegram1"):
    return command(kind, source=CommandSource.TELEGRAM, actor="telegram:1", key=key)


def record_for(cmd):
    digest = key_hash(cmd.idempotency_key)
    return IncomingRecord(key_hash=digest, ticket="0" * 32, slot=0,
                          entry=CommandEntry(id=digest[:32], command=cmd, received_at=NOW))


def receipts(tmp_path):
    return sorted((tmp_path / "commands/receipts").glob("*.json"))


def test_incoming_record_binds_its_key_identifier_timezone_and_web_source():
    cmd = command(CommandKind.REJECT)
    assert record_for(cmd).entry.id == key_hash(cmd.idempotency_key)[:32]
    with pytest.raises(ValidationError, match="Idempotenzschlüssel"):
        IncomingRecord(key_hash="f" * 64, ticket="0" * 32, slot=0, entry=record_for(cmd).entry)
    with pytest.raises(ValidationError, match="Annahmezeit"):
        IncomingRecord.model_validate({**record_payload(record_for(cmd)),
                                       "entry": {**record_payload(record_for(cmd))["entry"],
                                                 "received_at": "2026-11-07T12:00:00"}})
    other = telegram()
    with pytest.raises(ValidationError, match="Web-Quelle"):
        IncomingRecord(key_hash=key_hash(other.idempotency_key), ticket="0" * 32, slot=0,
                       entry=CommandEntry(id=key_hash(other.idempotency_key)[:32], command=other,
                                          received_at=NOW))


@pytest.mark.parametrize("section", ["receipts", "incoming"])
def test_a_valid_record_under_a_foreign_file_name_is_isolated_not_trusted(tmp_path, section):
    inbox = CommandInbox(JsonStore(tmp_path))
    entry, _ = inbox.submit(command(CommandKind.REJECT))
    name = key_hash(entry.command.idempotency_key) if section == "incoming" else entry.id
    source = tmp_path / "commands" / section / f"{name}.json"
    foreign = source.with_name(("b" * 64 if section == "incoming" else "b" * 32) + ".json")
    shutil.copy(source, foreign)
    with pytest.raises(ValueError, match="Falscher Name"):
        inbox.incoming.read(foreign)
    inbox.drain()
    assert not foreign.exists() and inbox.incoming.problems
    assert [item.id for item in inbox.queued()] == [entry.id]


def test_direct_repeated_admission_returns_the_committed_intent(tmp_path):
    inbox = CommandInbox(JsonStore(tmp_path))
    first, new = inbox.incoming.accept(command(CommandKind.REJECT))
    again, repeated = inbox.incoming.accept(command(CommandKind.REJECT))
    assert new and not repeated and again.id == first.id
    assert len(list((tmp_path / "commands/capacity").glob("*.json"))) == 1


def test_a_receipt_vanishing_between_listing_and_reading_is_skipped(tmp_path, monkeypatch):
    inbox = CommandInbox(JsonStore(tmp_path))
    entry, _ = inbox.submit(command(CommandKind.REJECT))
    read = inbox.incoming.read
    def vanishing(path):
        path.unlink(missing_ok=True)  # The operator forgot the entry meanwhile.
        return read(path)
    monkeypatch.setattr(inbox.incoming, "read", vanishing)
    assert inbox.incoming.records(quarantine=False) == []
    assert inbox.incoming.problems == []
    assert inbox.get(entry.id) is None


def test_contradicting_incoming_copy_is_isolated_and_the_receipt_wins(tmp_path):
    inbox = CommandInbox(JsonStore(tmp_path))
    entry, _ = inbox.submit(command(CommandKind.REJECT))
    forged = record_for(command(CommandKind.CONFIRM))
    path = tmp_path / "commands/incoming" / f"{forged.key_hash}.json"
    path.write_text(json.dumps(record_payload(forged)), encoding="utf-8")
    inbox.drain()
    assert not path.exists() and inbox.incoming.problems
    assert inbox.get(entry.id).command.kind == CommandKind.REJECT
    assert len(list((tmp_path / "commands/quarantine").glob("incoming-*.invalid"))) == 1


def test_repair_tolerates_a_concurrent_producer_committing_the_same_receipt(tmp_path, monkeypatch):
    inbox = CommandInbox(JsonStore(tmp_path))
    entry, _ = inbox.submit(command(CommandKind.REJECT))
    receipt = receipts(tmp_path)[0]
    content = receipt.read_bytes()
    receipt.unlink()  # Interrupted before the receipt was published.
    real = incoming.atomic_json
    def raced(path, value, *, exclusive=False):
        if exclusive and path.parent.name == "receipts":
            path.write_bytes(content)  # Another producer wins the compare-and-set.
            raise FileExistsError(str(path))
        return real(path, value, exclusive=exclusive)
    monkeypatch.setattr(incoming, "atomic_json", raced)
    inbox.incoming.repair()
    assert receipt.read_bytes() == content and inbox.incoming.problems == []
    assert inbox.get(entry.id).command == entry.command


def test_legacy_queue_entries_keep_their_ticket_until_execution_starts(tmp_path, monkeypatch):
    monkeypatch.setattr("mailhelp.review.inbox.MAX_QUEUED", 1)
    store = JsonStore(tmp_path)
    legacy, _ = CommandInbox(store).submit(telegram())  # Queued without a web receipt.
    restarted = CommandInbox(store)
    assert legacy.id in restarted.incoming.legacy
    restarted.incoming.publish(restarted.get(legacy.id))
    assert legacy.id in restarted.incoming.legacy
    with pytest.raises(CommandInboxFull):
        restarted.submit(command(CommandKind.REJECT))
    restarted.start(legacy.id)
    assert legacy.id not in restarted.incoming.legacy
    assert restarted.submit(command(CommandKind.REJECT))[1] is True


def test_a_receipt_contradicting_the_imported_queue_entry_is_refused(tmp_path):
    inbox = CommandInbox(JsonStore(tmp_path))
    entry, _ = inbox.submit(command(CommandKind.REJECT))
    altered = entry.model_copy(update={"command": command(CommandKind.CONFIRM)})
    with pytest.raises(CommandConflict, match="widersprechen"):
        inbox.incoming.publish(altered)
    assert inbox.get(entry.id).command.kind == CommandKind.REJECT


def test_retention_forgets_telegram_entries_without_web_receipts(tmp_path):
    now = [NOW]
    inbox = CommandInbox(JsonStore(tmp_path), clock=lambda: now[0])
    old = inbox.record_completed(telegram(), ReviewResult(status=ResultStatus.DONE, message="ok"))
    now[0] += timedelta(days=2)
    fresh, _ = inbox.submit(command(CommandKind.REJECT))
    inbox.finish(fresh.id, ReviewResult(status=ResultStatus.DONE, message="ok"))
    assert inbox.get(old.id) is None and inbox.get(fresh.id) is not None


def test_startup_removes_interrupted_temporary_admission_files(tmp_path):
    for section, name in (("incoming", ".admission-1.tmp"), ("capacity", ".ticket-2.tmp"),
                          ("receipts", ".admission-3.tmp")):
        path = tmp_path / "commands" / section / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("partial", encoding="utf-8")
    CommandInbox(JsonStore(tmp_path))
    assert not list((tmp_path / "commands").rglob("*.tmp"))


def test_startup_refuses_more_stored_intents_than_capacity(tmp_path, monkeypatch):
    monkeypatch.setattr("mailhelp.review.inbox.MAX_QUEUED", 2)
    store = JsonStore(tmp_path)
    inbox = CommandInbox(store)
    inbox.submit(command(CommandKind.REJECT, key="key-first01"))
    inbox.submit(command(CommandKind.REJECT, key="key-second1"))
    monkeypatch.setattr("mailhelp.review.inbox.MAX_QUEUED", 1)
    with pytest.raises(CommandInboxFull, match="Kapazität"):
        CommandInbox(store)


def test_operator_repairs_a_receipt_left_behind_by_a_crash_after_the_queue_commit(tmp_path, monkeypatch):
    store = JsonStore(tmp_path)
    inbox = CommandInbox(store)
    entry, _ = inbox.submit(command(CommandKind.REJECT))
    inbox.drain()
    def killed(_):
        raise RuntimeError("synthetic kill after queue commit")
    monkeypatch.setattr(inbox.incoming, "publish", killed)
    with pytest.raises(RuntimeError):
        inbox.finish(entry.id, ReviewResult(status=ResultStatus.DONE, message="ok"))
    assert json.loads(receipts(tmp_path)[0].read_text())["entry"]["status"] == "queued"
    restarted = CommandInbox(store)
    restarted.drain()
    assert json.loads(receipts(tmp_path)[0].read_text())["entry"]["status"] == "done"
    assert restarted.get(entry.id).status == CommandStatus.DONE and restarted.queued() == []


def test_telegram_queue_keeps_conflict_capacity_and_wake_semantics(tmp_path, monkeypatch):
    monkeypatch.setattr("mailhelp.review.inbox.MAX_QUEUED", 1)
    woken = []
    inbox = CommandInbox(JsonStore(tmp_path), wake=lambda: woken.append(1))
    inbox.submit(telegram())
    assert woken == [1]
    assert inbox.submit(telegram())[1] is False and woken == [1]
    with pytest.raises(CommandConflict):
        inbox._submit(telegram(CommandKind.CONFIRM), None)
    with pytest.raises(CommandInboxFull):
        inbox.submit(telegram(key="key-telegram2"))
    assert woken == [1]


def test_neither_web_admission_nor_receipt_import_touches_the_wake_event(tmp_path):
    woken = []
    inbox = CommandInbox(JsonStore(tmp_path), wake=lambda: woken.append(1))
    inbox.submit(command(CommandKind.REJECT))
    inbox.drain()
    assert woken == [] and len(inbox.queued()) == 1


def test_drain_imports_receipts_even_when_the_queue_reached_its_limit(tmp_path, monkeypatch):
    store = JsonStore(tmp_path)
    inbox = CommandInbox(store)
    entry, _ = inbox.submit(command(CommandKind.REJECT))
    monkeypatch.setattr("mailhelp.review.inbox.MAX_QUEUED", 0)  # Ticket already owned.
    inbox.drain()
    assert [item.id for item in inbox.queued()] == [entry.id]
    assert len(store.load(COMMAND_INBOX)["entries"]) == 1


def test_finishing_an_unknown_entry_changes_nothing(tmp_path):
    inbox = CommandInbox(JsonStore(tmp_path))
    inbox.finish("c" * 32, ReviewResult(status=ResultStatus.DONE, message="ok"))
    assert inbox.get("c" * 32) is None and receipts(tmp_path) == []


def test_interrupted_admin_command_with_receipt_is_reconciled_not_repeated(tmp_path):
    with JsonStore(tmp_path) as store:
        dialog, _, _ = setup(store)
        inbox = CommandInbox(store)
        admin = AdminCommand(kind=AdminKind.SENDERS, actor="web:" + "a" * 16,
                             idempotency_key="admin-0001", patch={})
        entry, _ = inbox.submit(admin)
        inbox.start(entry.id)
        restarted = CommandInbox(store)
        executed = []
        assert restarted.recover(lambda cmd: executed.append(cmd), dialog.review.resume_admitted) == 1
        result = restarted.get(entry.id).result
        assert executed == [] and result.status == ResultStatus.FAILED
        assert "Konfigurationsdienst" in result.message


def test_a_concurrent_producer_of_the_same_command_wins_and_the_second_returns_its_entry(tmp_path, monkeypatch):
    """Both producers passed the duplicate check; the receipt is the compare-and-set that decides."""
    inbox = CommandInbox(JsonStore(tmp_path))
    real = incoming.atomic_json
    def raced(path, value, *, exclusive=False):
        if exclusive and path.parent.name == "receipts":
            real(path, value, exclusive=True)  # The other producer publishes the same intent first.
            raise FileExistsError(str(path))
        return real(path, value, exclusive=exclusive)
    monkeypatch.setattr(incoming, "atomic_json", raced)
    entry, created = inbox.incoming.accept(command(CommandKind.REJECT))
    assert created is False and entry.command == command(CommandKind.REJECT)
    assert len(receipts(tmp_path)) == 1
