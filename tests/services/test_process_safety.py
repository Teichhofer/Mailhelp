"""A1–A7: hard process termination, independent provider and two fresh restarts."""
from pathlib import Path

import pytest
from safety_harness import PersistentWriter, ProcessHarness, seed
from shared_web_auth import SECRET
from web_scenario import mail_id, proposal, save_mail

from mailhelp.models import Proposal
from mailhelp.review.commands import ReviewCommand
from mailhelp.review.inbox import CommandInbox
from mailhelp.storage import JsonStore
from mailhelp.web.auth import WebAuth

MAIL = mail_id(1)


def snapshot(directory):
    with JsonStore(directory) as store:
        return {name: store.load(name) for name in store.names()
                if name.startswith(("proposal-", "action-ledger", "reconciliation-merge-", "command-inbox"))}


def creates(provider):
    return [call for call in PersistentWriter(provider).state()["calls"] if call[0] == "create"]


@pytest.mark.parametrize("point", ["A1", "A2", "A3", "A4"])
@pytest.mark.parametrize("mode", ["found", "none", "error", "invalid"])
def test_write_crash_and_two_restarts(tmp_path, point, mode):
    directory, provider = tmp_path / "app", tmp_path / "provider.json"
    entry_id = seed(directory)
    harness = ProcessHarness(directory, provider)
    harness.run(point)
    # No shared in-memory adapter or ledger: only the independent provider survives.
    assert len(creates(provider)) == (0 if point == "A1" else 1)
    before = None
    for restart in range(2):
        result = harness.run(mode=mode)
        after = snapshot(directory)
        item = after[f"proposal-{MAIL}-action"]
        assert len(creates(provider)) <= 1
        if point == "A4" or mode == "found" or (point == "A1" and mode == "none"):
            assert item["status"] == "created", result
            assert len(after["action-ledger"]["entries"]) == 1
            entry = next(e for e in after["command-inbox"]["entries"] if e["id"] == entry_id)
            assert entry["status"] == "done"
        else:
            assert item["status"] in {"confirmed", "writing", "uncertain"}
            assert not after.get("action-ledger", {}).get("entries")
        if restart:
            assert after == before
        before = after


@pytest.mark.parametrize("point", ["A5", "A6", "A7"])
def test_merge_crash_and_two_restarts_preserve_sources_and_manual_values(tmp_path, point):
    directory, provider = tmp_path / "app", tmp_path / "provider.json"
    seed(directory, merge=True)
    harness = ProcessHarness(directory, provider)
    harness.run(point)
    before = None
    for restart in range(2):
        assert harness.run()[0] == "done"
        after = snapshot(directory)
        target = Proposal.model_validate(after[f"proposal-{MAIL}-target"])
        alias = Proposal.model_validate(after[f"proposal-{mail_id(2)}-source"])
        assert target.version == alias.version == 2
        assert target.title == "Synthetische Aufgabe" and "title" in target.protected_fields
        assert len(target.sources) == 2
        assert alias.status.value == "merged" and alias.canonical_ref.mail_id == MAIL
        assert all(value["status"] == "completed" for name, value in after.items()
                   if name.startswith("reconciliation-merge-"))
        assert creates(provider) == []
        if restart:
            assert after == before
        before = after


@pytest.mark.parametrize("revocation", ["revoked", "expired"])
def test_fresh_process_does_not_replace_web_authorization(tmp_path, revocation):
    directory, provider = tmp_path / "app", tmp_path / "provider.json"
    seed(directory, web=True)
    harness = ProcessHarness(directory, provider)
    harness.run("A1")
    with JsonStore(directory) as store:
        if revocation == "revoked":
            WebAuth(store, SECRET, 30, lambda text: None).revoke_all()
        else:
            state = store.load("web-sessions")
            for session in state["sessions"]:
                session["expires_at"] = "2000-01-01T00:00:00Z"
            store.save("web-sessions", state)
    for _ in range(2):
        assert harness.run()[0] == "done"
        assert creates(provider) == []


@pytest.mark.parametrize("point", ["A5", "A6", "A7"])
@pytest.mark.parametrize("damage", ["missing", "corrupt", "changed"])
def test_merge_recovery_never_overwrites_changed_or_damaged_target(tmp_path, point, damage):
    directory, provider = tmp_path / "app", tmp_path / "provider.json"
    seed(directory, merge=True)
    harness = ProcessHarness(directory, provider)
    harness.run(point)
    path = directory / f"proposal-{MAIL}-target.json"
    if damage == "missing":
        path.unlink()
    elif damage == "corrupt":
        path.write_text("{damaged", encoding="utf-8")
    else:
        import json
        item = json.loads(path.read_text(encoding="utf-8"))
        item.update(version=3, title="Spätere manuelle Änderung")
        path.write_text(json.dumps(item, ensure_ascii=False), encoding="utf-8")
    for _ in range(2):
        assert harness.run()[0] == "error"
        if damage == "changed":
            assert "Spätere manuelle" in path.read_text(encoding="utf-8")
        assert creates(provider) == []


def test_merge_recovery_never_recreates_a_missing_preexisting_source(tmp_path):
    directory, provider = tmp_path / "app", tmp_path / "provider.json"
    seed(directory, merge=True)
    harness = ProcessHarness(directory, provider)
    harness.run("A5")
    path = directory / f"proposal-{mail_id(2)}-source.json"
    path.unlink()
    for _ in range(2):
        assert harness.run()[0] == "error"
        assert not path.exists()


@pytest.mark.parametrize("record", ["proposal", "mail", "action-ledger", "command-inbox"])
@pytest.mark.parametrize("damage", ["missing", "corrupt", "invalid"])
def test_a2_missing_or_damaged_authorities_never_repeat_provider_write(tmp_path, record, damage):
    directory, provider = tmp_path / "app", tmp_path / "provider.json"
    seed(directory)
    harness = ProcessHarness(directory, provider)
    harness.run("A2")
    name = {"proposal": f"proposal-{MAIL}-action", "mail": f"mail-{MAIL}"}.get(record, record)
    path = directory / f"{name}.json"
    if damage == "missing":
        path.unlink(missing_ok=True)
    else:
        path.write_text("{damaged" if damage == "corrupt" else '{"schema_version": 999}', encoding="utf-8")
    for _ in range(2):
        harness.run()
        assert len(creates(provider)) == 1


@pytest.mark.parametrize("damage", ["corrupt", "missing"])
def test_quarantined_merge_journal_blocks_later_restarts(tmp_path, damage):
    directory, provider = tmp_path / "app", tmp_path / "provider.json"
    seed(directory, merge=True)
    harness = ProcessHarness(directory, provider)
    harness.run("A6")
    path, = directory.glob("reconciliation-merge-*.json")
    if damage == "corrupt":
        path.write_text("{damaged", encoding="utf-8")
    else:
        path.unlink()
    for _ in range(2):
        assert harness.run()[0] == "error"
        assert creates(provider) == []
