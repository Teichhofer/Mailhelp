"""Targeted recovery is a versioned local state change, never an external action."""
import runpy
import sys

import pytest

from devtools.recover_revision import main, recover
from mailhelp.domain.processing import ProposalClarificationState
from mailhelp.persistence.proposals import clarification_name, proposal_name
from mailhelp.persistence.storage import CorruptState, JsonStore
from tests.fakes.shared_telegram_dialog import proposal


def seed(store, **changes):
    item = proposal(kind="event", status="needs_clarification",
                    known_temporal_facts={"start_time": "11:30:00"},
                    open_questions=["Wann beginnt der Termin?", "Wann endet der Termin?"])
    store.save(proposal_name(item.source_mail_id, item.id), item.model_dump(mode="json"))
    answer = ProposalClarificationState(mail_id=item.source_mail_id, proposal_id=item.id, version=1,
        question=item.open_questions[0], authorized_answer="7.1.2027 11:30", normalized_answer="2027-01-07 11:30",
        question_status="answered", answer_status="valid", interpretation_status="completed",
        proposal_revision_status="paused", revision_attempts=3)
    answer = answer.model_copy(update=changes)
    name = clarification_name(item.source_mail_id, item.id, 1)
    store.save(name, answer.model_dump(mode="json"))
    return item, name


def test_preflight_apply_restart_and_repeat(tmp_path):
    with JsonStore(tmp_path) as store:
        item, name = seed(store)
        original = store.load(name)
        assert recover(store, item.source_mail_id, item.id, 1, "Europe/Berlin")
        assert store.load(name) == original
        assert recover(store, item.source_mail_id, item.id, 1, "Europe/Berlin", apply=True)
        updated = store.load(name)
        assert updated["revision_attempts"] == 0 and updated["proposal_revision_status"] == "retry_required"
        assert updated["authorized_answer"] == original["authorized_answer"]
    with JsonStore(tmp_path) as store:
        assert not recover(store, item.source_mail_id, item.id, 1, "Europe/Berlin", apply=True)
        assert store.load(name) == updated


@pytest.mark.parametrize("changes", [
    {"normalized_answer": "not a time"}, {"normalized_answer": None},
    {"normalized_answer": "2027-01-07 12:30"}, {"proposal_revision_status": "completed"},
    {"question": "Other question"},
])
def test_refused_recovery_preserves_state(tmp_path, changes):
    with JsonStore(tmp_path) as store:
        item, name = seed(store, **changes)
        before = store.load(name)
        with pytest.raises((ValueError, CorruptState)):
            recover(store, item.source_mail_id, item.id, 1, "Europe/Berlin", apply=True)
        assert store.load(name) == before


def test_missing_and_changed_version_are_refused(tmp_path):
    with JsonStore(tmp_path) as store:
        with pytest.raises(ValueError):
            recover(store, "a" * 24, "p1", 1, "UTC")
        item, _ = seed(store)
        with pytest.raises(ValueError):
            recover(store, item.source_mail_id, item.id, 2, "UTC")


def test_cli_defaults_to_dry_run_and_explicit_apply(tmp_path, monkeypatch, capsys):
    with JsonStore(tmp_path) as store:
        item, _ = seed(store)
    args = ["--data", str(tmp_path), "--mail", item.source_mail_id, "--proposal", item.id, "--version", "1"]
    assert main(args) == 0 and "preflight_ok" in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["recover_revision", *args, "--apply"])
    with pytest.raises(SystemExit) as stopped:
        runpy.run_module("devtools.recover_revision", run_name="__main__")
    assert stopped.value.code == 0 and "requeued" in capsys.readouterr().out
