"""Synthetic disk, concurrency and restart checks for immutable web intents."""
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from mailhelp.review import CommandKind, ResultStatus, ReviewResult
from mailhelp.review.inbox import COMMAND_INBOX, CommandConflict, CommandInbox, CommandInboxFull, CommandStatus
from mailhelp.review.incoming import IncomingRecord, atomic_json, key_hash, record_payload, replace_file, requires_ack
from mailhelp.storage import JsonStore
from tests.fakes.shared_review import command


def test_same_key_concurrent_producers_commit_one_intent(tmp_path):
    inbox = CommandInbox(JsonStore(tmp_path))
    cmd = command(CommandKind.REJECT)
    with ThreadPoolExecutor(max_workers=5) as pool:
        accepted = list(pool.map(lambda _: inbox.submit(cmd), range(10)))
    assert len({entry.id for entry, _ in accepted}) == 1
    assert sum(new for _, new in accepted) == 1
    assert len(list((tmp_path / 'commands/capacity').glob('*.json'))) == 1
    assert len(inbox.queued()) == 1
    inbox.drain()
    assert not list((tmp_path / 'commands/incoming').glob('*.json'))
    assert len(inbox.store.load(COMMAND_INBOX)['entries']) == 1


def test_different_payload_same_key_never_overwrites_accepted_intent(tmp_path):
    inbox = CommandInbox(JsonStore(tmp_path))
    first, _ = inbox.submit(command(CommandKind.REJECT))
    with pytest.raises(CommandConflict):
        inbox.submit(command(CommandKind.CONFIRM))
    assert inbox.get(first.id).command.kind == CommandKind.REJECT
    inbox.drain()
    with pytest.raises(CommandConflict):
        inbox.submit(command(CommandKind.CONFIRM))


def test_field_deletion_and_omitted_patch_are_distinct_intents(tmp_path):
    from mailhelp.review.editing import ProposalEditPatch
    inbox = CommandInbox(JsonStore(tmp_path))
    base = command(CommandKind.REJECT)
    omitted = base.model_copy(update={'kind': CommandKind.EDIT, 'patch': ProposalEditPatch()})
    deleted = omitted.model_copy(update={'patch': ProposalEditPatch(due=None)})
    inbox.submit(omitted)
    with pytest.raises(CommandConflict):
        inbox.submit(deleted)
    inbox.drain()
    restarted = CommandInbox(inbox.store)
    assert restarted.submit(omitted)[1] is False
    with pytest.raises(CommandConflict):
        restarted.submit(deleted)


def test_capacity_covers_imported_and_unimported_commands(tmp_path, monkeypatch):
    monkeypatch.setattr('mailhelp.review.inbox.MAX_QUEUED', 2)
    inbox = CommandInbox(JsonStore(tmp_path))
    first, _ = inbox.submit(command(CommandKind.REJECT, key='key-first'))
    inbox.drain()
    inbox.submit(command(CommandKind.REJECT, key='key-second'))
    with pytest.raises(CommandInboxFull):
        inbox.submit(command(CommandKind.REJECT, key='key-third'))
    inbox.start(first.id)
    inbox.submit(command(CommandKind.REJECT, key='key-third'))
    assert len(inbox.queued()) == 2


def test_disk_full_before_commit_releases_slot_and_retains_no_intent(tmp_path, monkeypatch):
    import mailhelp.review.incoming as incoming
    inbox = CommandInbox(JsonStore(tmp_path))
    real = incoming.atomic_json
    def full(path, *args, **kwargs):
        if path.parent.name == 'receipts':
            raise OSError(28, 'synthetic full disk')
        return real(path, *args, **kwargs)
    monkeypatch.setattr(incoming, 'atomic_json', full)
    with pytest.raises(OSError):
        inbox.submit(command(CommandKind.REJECT))
    assert inbox.queued() == []
    assert list((tmp_path / 'commands/capacity').glob('*.json')) == []


def test_receipt_recovers_crash_before_incoming_publication(tmp_path, monkeypatch):
    import mailhelp.review.incoming as incoming
    inbox = CommandInbox(JsonStore(tmp_path))
    real = incoming.atomic_json
    def interrupted(path, *args, **kwargs):
        if path.parent.name == 'incoming':
            raise OSError('synthetic interrupted incoming publication')
        return real(path, *args, **kwargs)
    monkeypatch.setattr(incoming, 'atomic_json', interrupted)
    accepted, _ = inbox.submit(command(CommandKind.REJECT))
    restarted = CommandInbox(inbox.store)
    restarted.drain()
    assert restarted.get(accepted.id).command == accepted.command
    assert restarted.submit(accepted.command)[1] is False


def test_crash_after_queue_commit_before_input_deletion_is_idempotent(tmp_path, monkeypatch):
    inbox = CommandInbox(JsonStore(tmp_path))
    accepted, _ = inbox.submit(command(CommandKind.REJECT))
    def killed(*_):
        raise RuntimeError('synthetic kill after commit')
    monkeypatch.setattr(inbox.incoming, 'remove_incoming', killed)
    with pytest.raises(RuntimeError):
        inbox.drain()
    restarted = CommandInbox(inbox.store)
    restarted.drain()
    assert [entry.id for entry in restarted.queued()] == [accepted.id]
    assert len(inbox.store.load(COMMAND_INBOX)['entries']) == 1


@pytest.mark.parametrize('stage', ['incoming', 'receipts'])
def test_damaged_input_is_isolated_and_reported_with_repair_from_second_copy(tmp_path, stage):
    inbox = CommandInbox(JsonStore(tmp_path))
    entry, _ = inbox.submit(command(CommandKind.REJECT))
    name = key_hash(entry.command.idempotency_key) if stage == 'incoming' else entry.id
    damaged = tmp_path / 'commands' / stage / f'{name}.json'
    damaged.write_text('secret broken payload', encoding='utf-8')
    assert len(inbox._entries()) == 1 if stage == 'incoming' else inbox._entries() == []
    inbox.drain()
    assert inbox.get(entry.id) is not None
    assert len(list((tmp_path / 'commands/quarantine').glob('*.invalid'))) == 1
    assert inbox.incoming.problems and 'secret' not in str(inbox.incoming.problems)


def test_replace_retries_permission_errors_with_a_fixed_bound(tmp_path, monkeypatch):
    import mailhelp.review.incoming as incoming
    first, target = tmp_path / 'first', tmp_path / 'target'
    first.write_text('complete', encoding='utf-8')
    real = incoming.os.replace
    calls, waits = [], []
    def blocked(source, destination):
        calls.append(1)
        if len(calls) < 4:
            raise PermissionError('synthetic indexer')
        real(source, destination)
    monkeypatch.setattr(incoming.os, 'replace', blocked)
    monkeypatch.setattr(incoming.time, 'sleep', waits.append)
    replace_file(first, target)
    assert target.read_text() == 'complete' and waits == [.005, .01, .02]
    def always_blocked(*_):
        raise PermissionError('synthetic permanently open target')
    monkeypatch.setattr(incoming.os, 'replace', always_blocked)
    with pytest.raises(PermissionError):
        replace_file(first, target)


def test_serialization_failure_cleans_atomic_temporary_files(tmp_path):
    with pytest.raises(TypeError):
        atomic_json(tmp_path / 'x.json', {'invalid': object()})
    assert list(tmp_path.iterdir()) == []


def test_acknowledgement_persists_across_restart_and_errors_outlive_success(tmp_path):
    now = [datetime(2026, 11, 7, tzinfo=UTC)]
    inbox = CommandInbox(JsonStore(tmp_path), clock=lambda: now[0])
    failed, _ = inbox.submit(command(CommandKind.REJECT, key='key-failed'))
    inbox.finish(failed.id, ReviewResult(status=ResultStatus.STALE, message='veraltet'))
    now[0] += timedelta(days=2)
    fresh, _ = inbox.submit(command(CommandKind.REJECT, key='key-fresh'))
    inbox.finish(fresh.id, ReviewResult(status=ResultStatus.DONE, message='ok'))
    assert requires_ack(inbox.get(failed.id))
    inbox.incoming.acknowledge(inbox.get(failed.id), 'web:session')
    restarted = CommandInbox(inbox.store, clock=lambda: now[0])
    assert restarted.get(failed.id).acknowledged
    restarted.finish(fresh.id, ReviewResult(status=ResultStatus.DONE, message='ok'))
    assert restarted.get(failed.id) is None
