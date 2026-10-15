"""Draft conflicts, file races and denied execution preserve the previous configuration."""
import hashlib
import json

import pytest
import yaml
from shared_profiles import TOPICS

from mailhelp.configuration import AdminCommand, AdminKind, ConfigurationConflict, SenderChange, file_hash
from mailhelp.review.results import ResultStatus
from mailhelp.setup import SetupState
from mailhelp.yaml_edit import replace_block


def actor(profiled):
    return "web:" + profiled.web.auth.sessions()[0].id


def test_local_drafts_reject_mixing_invalid_kind_and_changed_files(profiled):
    setup = profiled.runtime.setup
    patch = TOPICS[0].model_dump(mode="json")
    with pytest.raises(ValueError):
        setup.save_local(actor(profiled), 0, "invalid-kind", "other", patch)
    state = setup.save_local(actor(profiled), 0, "topic-0001", "topics", patch)
    with pytest.raises(ConfigurationConflict):
        setup.save(actor(profiled), state.version, "mix-000001", 6, {"personal_info": "mixed"})
    with pytest.raises(ConfigurationConflict):
        setup.save_local(actor(profiled), state.version, "mix-000002", "topics", {**patch, "id": "other"})
    setup.discard(actor(profiled), state.version, "discard-001")
    assert setup.discard(actor(profiled), state.version, "discard-001").patch == {}
    state = setup.save_local(actor(profiled), setup.state().version, "topic-0002", "topics", patch)
    path = profiled.tmp_path / "topics.yaml"
    path.write_text(path.read_text() + "\n# externally changed\n")
    with pytest.raises(ConfigurationConflict):
        setup.save_local(actor(profiled), state.version, "topic-0003", "topics", patch)
    with pytest.raises(ConfigurationConflict):
        setup.command(actor(profiled), state.version, "apply-0001", state.base_hash)
    config = profiled.tmp_path / "config.yaml"
    config.write_text(config.read_text() + "\n# changed\n")
    with pytest.raises(ConfigurationConflict):
        setup.command(actor(profiled), state.version, "apply-0002", state.base_hash)


def test_profile_changes_require_fresh_per_profile_diagnoses(profiled):
    setup, cfg = profiled.runtime.setup, profiled.app.settings
    state = setup.save(actor(profiled), 0, "profile-001", 6,
        {"target_profiles": [profile.model_dump() for profile in cfg.target_profiles]})
    with pytest.raises(ValueError, match="Zielprofil"):
        setup.command(actor(profiled), state.version, "apply-0001", state.base_hash)
    from mailhelp.diagnostics import DiagnosticResult, DiagnosticsState
    revision = setup.fingerprint()
    results = {name: DiagnosticResult(status="ready", config_revision=revision)
               for name in ("calendar", "todoist", "calendar:2", "tasks:2")}
    profiled.app.store.save("diagnostics-state", DiagnosticsState(results=results).model_dump(mode="json"))
    assert setup.command(actor(profiled), state.version, "apply-0002", state.base_hash).patch == state.patch


def test_sender_exception_validation_and_missing_mailbox_block_local_write(profiled):
    for values in ({"action": "allow", "addresses": ["a@example.test"]},
                   {"action": "allow", "mailbox_id": 2, "domains": ["example.test"]}):
        with pytest.raises(ValueError):
            SenderChange.model_validate(values)
    cfg = profiled.app.configuration
    path = profiled.tmp_path / "irrelevant-senders.json"
    command = AdminCommand(kind=AdminKind.SENDERS, actor=actor(profiled), idempotency_key="sender-0001",
        expected_hash=file_hash(path), patch={"action": "add", "mailbox_id": 99, "addresses": ["a@example.test"]})
    assert cfg.execute(command).status == ResultStatus.INVALID
    command = command.model_copy(update={"patch": {"action": "allow", "mailbox_id": 2, "addresses": ["a@example.test"]}})
    assert cfg.execute(command).status == ResultStatus.DONE
    assert cfg.execute(command).status == ResultStatus.STALE
    current = command.model_copy(update={"expected_hash": file_hash(path)})
    assert cfg.execute(current).status == ResultStatus.DONE
    current = current.model_copy(update={"patch": {"action": "unallow", "mailbox_id": 2, "addresses": ["a@example.test"]}})
    assert cfg.execute(current).status == ResultStatus.DONE
    assert not cfg.blocked_senders().mailboxes["2"].allow
    rejected = current.model_copy(update={"context_hash": "0" * 64})
    assert cfg.execute(rejected).status == ResultStatus.STALE
    checks = iter([True, False])
    cfg.authorize = lambda _: next(checks)
    denied = current.model_copy(update={"expected_hash": file_hash(path), "patch": {"action": "add", "addresses": ["b@example.test"]}})
    before = path.read_bytes()
    assert cfg.execute(denied).status == ResultStatus.UNAUTHORIZED and path.read_bytes() == before


def test_operative_override_is_live_but_connection_and_profile_assignment_wait_for_restart(profiled):
    cfg = profiled.app.configuration
    boxes = [box.model_dump(mode="json") for box in cfg.active.imap.configured_mailboxes()]
    boxes[1].update(personal_info="New work signature", host="changed.example.test", target_profile=1)
    command = AdminCommand(kind=AdminKind.SETUP, actor=actor(profiled), idempotency_key="live-000001",
        expected_hash=file_hash(profiled.tmp_path / "config.yaml"), patch={"imap.mailboxes": boxes}, acknowledged=True)
    assert cfg.execute(command).status == ResultStatus.DONE
    assert cfg.active.imap.mailbox(2).personal_info == "New work signature"
    assert cfg.active.imap.mailbox(2).target_profile == 2 and cfg.active.imap.mailbox(2).host == "work.example.test"
    assert yaml.safe_load((profiled.tmp_path / "config.yaml").read_text())["imap"]["mailboxes"][1]["target_profile"] == 1


@pytest.mark.parametrize("source", ["# keep\nimap:\n  mailboxes: []\nother: yes\n", "imap:\n  mailboxes:\n  - id: 1\n",
    "other: yes\n", "imap:\n  mailboxes:\n  - id: 1\n  # nested comment\n\nother: yes\n"])
def test_collection_yaml_edit_preserves_surrounding_content(source):
    result = replace_block(source, "imap.mailboxes", [{"id": 2}])
    assert yaml.safe_load(result)["imap"]["mailboxes"] == [{"id": 2}]
    if "other: yes" in source:
        assert "other: yes" in result
