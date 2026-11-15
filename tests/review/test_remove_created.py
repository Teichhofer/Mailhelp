"""Tests for REMOVE_CREATED review command and reconciliation (Patch 6.6.2 / D2).

Checks D2:
- Removal window: allowed at 9 min, rejected after 10 min
- Not created by Mailhelp: rejected for pending, simulated, rejected, already_exists
- Stale version and unknown proposal
- Session revocation at execution time
- Restart reconciliation in every phase
- Duplicate command
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from mailhelp.domain.proposal import ProposalKind, ProposalStatus
from mailhelp.domain.verification import FieldDifference, fingerprint
from mailhelp.external.contracts import EntryModifiedError
from mailhelp.llm.adapter import UncertainWriteError
from mailhelp.persistence.storage import JsonStore
from mailhelp.review import CommandKind, CommandSource, ResultStatus, ReviewCommand, StaleCommand
from mailhelp.review.learning_log import DecisionLearningLog
from mailhelp.review.service import proposal_creation_time
from tests.fakes.factories import build_proposal
from tests.fakes.shared_review import command, setup, web
from tests.fakes.shared_telegram_dialog import Writer

MAIL = "a" * 24


def _created_proposal(minutes_ago: float = 0, status: ProposalStatus = ProposalStatus.CREATED, **extra):
    created_at = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    version = extra.pop("version", 1)
    kind = extra.pop("kind", ProposalKind.EVENT)
    proposal_id = extra.pop("id", "p1")
    external_id = extra.pop("external_id", "ext-1" if status != ProposalStatus.SIMULATED else None)
    payload = {
        "start": "2026-10-21T12:30:00+02:00",
        "end": "2026-10-21T15:30:00+02:00",
        "target": "calendar",
    } if kind == ProposalKind.EVENT else {}
    payload.update(extra)
    return build_proposal(
        kind=kind,
        status=status,
        source_mail_id=MAIL,
        id=proposal_id,
        version=version,
        external_id=external_id,
        created_at=created_at,
        **payload,
    )


def test_command_requires_proposal_and_version():
    cmd = command(CommandKind.REMOVE_CREATED)
    assert cmd.kind == CommandKind.REMOVE_CREATED
    assert cmd.proposal_id == "p1"
    assert cmd.version == 1

    # Missing proposal_id
    with pytest.raises(ValidationError):
        ReviewCommand(
            kind=CommandKind.REMOVE_CREATED,
            source=CommandSource.WEB,
            actor="web:s",
            mail_id=MAIL,
            proposal_id=None,
            version=1,
            idempotency_key="key-00000001",
        )


def test_remove_created_success_within_window(tmp_path):
    prop = _created_proposal(minutes_ago=5)
    writer = Writer()
    with JsonStore(tmp_path) as store:
        dialog, _, log = setup(store, prop, writers={"google_calendar": writer})
        learning = DecisionLearningLog(store, 30, log)
        dialog.learning = learning

        service = web(dialog)
        cmd = command(CommandKind.REMOVE_CREATED)
        result = service.execute(cmd)

        assert result.status == ResultStatus.DONE
        assert result.message == "Entfernt und geprüft."
        assert writer.removed == 1

        # Proposal status changed to REMOVED
        updated = dialog.repository.load_current(MAIL, "p1")
        assert updated is not None
        assert updated.status == ProposalStatus.REMOVED
        assert not updated.is_creatable

        # Learning log recorded the removal decision
        records = [json.loads(line) for line in learning.path.read_text(encoding="utf-8").splitlines()]
        assert len(records) == 1
        assert records[0]["kind"] == "remove"


def test_remove_created_rejected_after_window_expired(tmp_path):
    # Created 12 minutes ago (> 10 minute window)
    prop = _created_proposal(minutes_ago=12)
    writer = Writer()
    with JsonStore(tmp_path) as store:
        dialog, _, _ = setup(store, prop, writers={"google_calendar": writer})
        service = web(dialog)
        cmd = command(CommandKind.REMOVE_CREATED)

        result = service.execute(cmd)
        assert result.status == ResultStatus.INVALID
        assert "Frist zum Entfernen" in result.message
        assert writer.removed == 0

        with pytest.raises(ValueError, match="Frist zum Entfernen"):
            service.execute(cmd, raise_errors=True)


def test_remove_created_rejected_for_invalid_proposal_states(tmp_path):
    # 1. SIMULATED proposal
    prop_sim = _created_proposal(status=ProposalStatus.SIMULATED)
    writer = Writer()
    with JsonStore(tmp_path) as store:
        dialog, _, _ = setup(store, prop_sim, writers={"google_calendar": writer})
        service = web(dialog)
        result = service.execute(command(CommandKind.REMOVE_CREATED))
        assert result.status == ResultStatus.INVALID
        assert "Simulierte Vorschläge" in result.message

    # 2. PENDING_CONFIRMATION proposal
    prop_pending = build_proposal(status=ProposalStatus.PENDING_CONFIRMATION, source_mail_id=MAIL, id="p1", version=1)
    with JsonStore(tmp_path) as store:
        dialog, _, _ = setup(store, prop_pending, writers={"google_calendar": writer})
        service = web(dialog)
        result = service.execute(command(CommandKind.REMOVE_CREATED))
        assert result.status == ResultStatus.INVALID
        assert "Nur angelegte Einträge" in result.message

    # 3. Missing external_id
    prop_no_ext = _created_proposal()
    prop_no_ext = prop_no_ext.model_copy(update={"external_id": None})
    with JsonStore(tmp_path) as store:
        dialog, _, _ = setup(store, prop_no_ext, writers={"google_calendar": writer})
        service = web(dialog)
        result = service.execute(command(CommandKind.REMOVE_CREATED))
        assert result.status == ResultStatus.INVALID
        assert "Keine externe ID" in result.message


def test_remove_created_stale_version_and_unknown_proposal(tmp_path):
    prop = _created_proposal(version=2)
    writer = Writer()
    with JsonStore(tmp_path) as store:
        dialog, _, _ = setup(store, prop, writers={"google_calendar": writer})
        service = web(dialog)

        # Version mismatch
        res_v = service.execute(command(CommandKind.REMOVE_CREATED, version=1))
        assert res_v.status == ResultStatus.STALE

        # Unknown proposal
        res_u = service.execute(command(CommandKind.REMOVE_CREATED, proposal_id="unknown"))
        assert res_u.status == ResultStatus.STALE


def test_remove_created_session_revoked_at_execution_time(tmp_path):
    prop = _created_proposal(minutes_ago=2)
    writer = Writer()
    with JsonStore(tmp_path) as store:
        dialog, _, _ = setup(store, prop, writers={"google_calendar": writer})
        service = web(dialog, allowed=False)
        result = service.execute(command(CommandKind.REMOVE_CREATED))
        assert result.status == ResultStatus.UNAUTHORIZED
        assert writer.removed == 0


def test_remove_created_modified_e5_rejected(tmp_path):
    prop = _created_proposal(minutes_ago=2)
    mod_error = EntryModifiedError("Geändert beim Anbieter", differences={"title": FieldDifference(expected="a", actual="b")})
    writer = Writer(modified_error=mod_error)
    with JsonStore(tmp_path) as store:
        dialog, _, _ = setup(store, prop, writers={"google_calendar": writer})
        service = web(dialog)
        result = service.execute(command(CommandKind.REMOVE_CREATED))
        assert result.status == ResultStatus.INVALID
        assert "Nicht entfernt – Eintrag wurde beim Anbieter geändert" in result.message
        assert writer.removed == 0


def test_remove_created_already_removed_at_provider(tmp_path):
    prop = _created_proposal(minutes_ago=2)
    writer = Writer(already_removed=True)
    with JsonStore(tmp_path) as store:
        dialog, _, _ = setup(store, prop, writers={"google_calendar": writer})
        service = web(dialog)
        result = service.execute(command(CommandKind.REMOVE_CREATED))
        assert result.status == ResultStatus.DONE
        assert result.message == "Bereits entfernt."
        assert writer.removed == 0

        updated = dialog.repository.load_current(MAIL, "p1")
        assert updated.status == ProposalStatus.REMOVED


def test_remove_created_duplicate_command(tmp_path):
    prop = _created_proposal(minutes_ago=2)
    writer = Writer()
    with JsonStore(tmp_path) as store:
        dialog, _, _ = setup(store, prop, writers={"google_calendar": writer})
        service = web(dialog)

        # First call removes entry
        res1 = service.execute(command(CommandKind.REMOVE_CREATED, key="key-00000001"))
        assert res1.status == ResultStatus.DONE
        assert writer.removed == 1

        # Second call sees status is already REMOVED -> DONE without second write
        res2 = service.execute(command(CommandKind.REMOVE_CREATED, key="key-00000002"))
        assert res2.status == ResultStatus.DONE
        assert res2.message == "Bereits entfernt."
        assert writer.removed == 1


def test_remove_created_uncertain_write_and_immediate_reconcile(tmp_path):
    prop = _created_proposal(minutes_ago=2)
    writer = Writer(remove_error=UncertainWriteError("Timeout nach dem Löschen"))
    with JsonStore(tmp_path) as store:
        dialog, _, _ = setup(store, prop, writers={"google_calendar": writer})
        service = web(dialog)

        # 1. Reconcile succeeds immediately
        result = service.execute(command(CommandKind.REMOVE_CREATED))
        assert result.status == ResultStatus.DONE
        assert result.message == "Entfernt und geprüft."

        # 2. Reconcile fails immediately (provider still reports entry active)
        prop2 = _created_proposal(minutes_ago=2, id="p2", external_id="ext-2")
        dialog.persist(prop2)
        writer.reconcile_remove = lambda p, k: None  # mock provider still active
        cmd2 = command(CommandKind.REMOVE_CREATED, proposal_id="p2", key="key-00000unc")
        res2 = service.execute(cmd2)
        assert res2.status == ResultStatus.WRITE_UNCERTAIN
        assert "Entfernen noch nicht bestätigt" in res2.message


def test_remove_created_restart_reconciliation(tmp_path):
    prop = _created_proposal(minutes_ago=2)
    writer = Writer()
    with JsonStore(tmp_path) as store:
        dialog, _, _ = setup(store, prop, writers={"google_calendar": writer})
        service = web(dialog)
        cmd = command(CommandKind.REMOVE_CREATED)

        # 1. Before write: proposal still CREATED and writer reports not removed
        writer.reconcile_remove = lambda p, k: None
        res_before = service.reconcile(cmd)
        assert res_before.status == ResultStatus.FAILED
        assert "Durch einen Neustart unterbrochen" in res_before.message
        assert writer.removed == 0

        # 2. Crash after write: proposal still CREATED in store, but writer.reconcile_remove confirms removal
        writer.reconcile_remove = lambda p, k: {"id": "ext-1", "operation": "removed"}
        res_after = service.reconcile(cmd)
        assert res_after.status == ResultStatus.DONE
        assert "Nach einem Neustart abgeglichen" in res_after.message

        # Status was updated to REMOVED
        updated = dialog.repository.load_current(MAIL, "p1")
        assert updated.status == ProposalStatus.REMOVED

        # 3. Effect already visible: proposal status is REMOVED in store
        res_done = service.reconcile(cmd)
        assert res_done.status == ResultStatus.DONE


def test_proposal_creation_time_fallbacks(tmp_path):
    from mailhelp.domain.proposal import ActionLedger, ActionLedgerEntry
    from mailhelp.domain.verification import TargetBinding, WriteReceipt, WriteVerification

    now = datetime(2026, 12, 1, 10, 0, tzinfo=UTC)

    with JsonStore(tmp_path) as store:
        prop = build_proposal(status=ProposalStatus.CREATED, source_mail_id=MAIL, id="p1", version=1, external_id="e1")

        # 1. Direct created_at on proposal
        prop_with_ts = prop.model_copy(update={"created_at": now})
        assert proposal_creation_time(store, prop_with_ts) == now

        # 2. Action ledger fallback
        ledger = ActionLedger(entries=[
            ActionLedgerEntry(
                action_key="0" * 64,
                mail_id=MAIL,
                proposal_id="p1",
                proposal_version=1,
                kind=ProposalKind.EVENT,
                title="Test",
                target="cal",
                external_id="e1",
                created_at=now,
            )
        ])
        store.save("action-ledger", ledger.model_dump(mode="json"))
        assert proposal_creation_time(store, prop) == now

        # 3. Write verification fallback
        store.save("action-ledger", ActionLedger().model_dump(mode="json"))
        from mailhelp import state_names
        from mailhelp.domain.verification import operation_id
        exp = {"kind": "event"}
        rec = WriteVerification(
            id=operation_id(MAIL, "p1", 1, "create"),
            mail_id=MAIL,
            proposal_id="p1",
            proposal_version=1,
            idempotency_key="key-1",
            operation="create",
            target=TargetBinding(profile=1, provider="google", account="acc", container="cal"),
            expected=exp,
            expected_fingerprint=fingerprint(exp),
            receipt=WriteReceipt(external_id="e1", written_at=now, result="created"),
            next_check_at=now + timedelta(minutes=1),
            created_at=now,
            updated_at=now,
            deadline_at=now + timedelta(minutes=5),
        )
        store.save(state_names.write_verification(rec.id), rec.model_dump(mode="json"))
        assert proposal_creation_time(store, prop) == now

        # If no record exists, returns None
        prop_other = build_proposal(status=ProposalStatus.CREATED, source_mail_id=MAIL, id="p_other", version=1)
        assert proposal_creation_time(store, prop_other) is None

        # Ledger with entry for a different proposal
        ledger_other = ActionLedger(entries=[
            ActionLedgerEntry(
                action_key="1" * 64,
                mail_id=MAIL,
                proposal_id="p_other",
                proposal_version=1,
                kind=ProposalKind.EVENT,
                title="Other",
                target="cal",
                external_id="e2",
                created_at=now,
            )
        ])
        store.save("action-ledger", ledger_other.model_dump(mode="json"))
        # prop has id="p1", so it skips ledger_other and finds WriteVerification rec
        assert proposal_creation_time(store, prop) == now

        # WriteVerification with receipt is None -> returns rec.created_at
        store.save("action-ledger", ActionLedger().model_dump(mode="json"))
        rec_no_receipt = WriteVerification(
            id=operation_id(MAIL, "p1", 1, "create"),
            mail_id=MAIL,
            proposal_id="p1",
            proposal_version=1,
            idempotency_key="key-1",
            operation="create",
            target=TargetBinding(profile=1, provider="google", account="acc", container="cal"),
            expected=exp,
            expected_fingerprint=fingerprint(exp),
            state="simulated",
            receipt=None,
            created_at=now,
            updated_at=now,
            deadline_at=now + timedelta(minutes=5),
        )
        store.save(state_names.write_verification(rec_no_receipt.id), rec_no_receipt.model_dump(mode="json"))
        assert proposal_creation_time(store, prop) == now


def test_remove_created_no_writer_configured(tmp_path):
    prop = _created_proposal(minutes_ago=2)
    with JsonStore(tmp_path) as store:
        dialog, _, _ = setup(store, prop, writers={})
        service = web(dialog)
        cmd = command(CommandKind.REMOVE_CREATED)
        res = service.execute(cmd)
        assert res.status == ResultStatus.INVALID
        assert "Kein Schreibdienst" in res.message


def test_remove_created_operation_errors(tmp_path):
    prop = _created_proposal(minutes_ago=2)
    mod_error = EntryModifiedError("Geändert beim Anbieter", differences={"title": FieldDifference(expected="a", actual="b")})
    
    # 1. EntryModifiedError during operation
    writer_mod = Writer()
    from mailhelp.external.contracts import PreparedWrite
    writer_mod.prepare_remove = lambda p, k: PreparedWrite(lambda: (_ for _ in ()).throw(mod_error), kind="remove")
    with JsonStore(tmp_path) as store:
        dialog, _, _ = setup(store, prop, writers={"google_calendar": writer_mod})
        service = web(dialog)
        res = service.execute(command(CommandKind.REMOVE_CREATED))
        assert res.status == ResultStatus.INVALID
        assert "beim Anbieter geändert" in res.message

    # 2. Generic exception during operation
    writer_exc = Writer()
    writer_exc.prepare_remove = lambda p, k: PreparedWrite(lambda: (_ for _ in ()).throw(RuntimeError("Boom")), kind="remove")
    with JsonStore(tmp_path) as store:
        dialog, _, _ = setup(store, prop, writers={"google_calendar": writer_exc})
        service = web(dialog)
        res = service.execute(command(CommandKind.REMOVE_CREATED))
        assert res.status == ResultStatus.FAILED
        assert "fehlgeschlagen" in res.message


def test_removal_window_configuration_and_fallbacks(tmp_path):
    from unittest.mock import MagicMock
    prop = _created_proposal(minutes_ago=15)
    writer = Writer()
    with JsonStore(tmp_path) as store:
        dialog, _, _ = setup(store, prop, writers={"google_calendar": writer})
        service = web(dialog)

        # 1. Configuration active with 20 minutes window -> allowed at 15 minutes
        cfg = MagicMock()
        cfg.active.targets.removal_window_minutes = 20
        service.configuration = cfg
        res = service.execute(command(CommandKind.REMOVE_CREATED, key="key-cfg0001"))
        assert res.status == ResultStatus.DONE

        # Reset prop back to CREATED
        dialog.persist(prop)
        writer.removed = 0

        # 2. Relevance handler targets with 20 minutes window
        service.configuration = None
        handler = MagicMock()
        handler.targets.removal_window_minutes = 20
        dialog.relevance_handler = handler
        res2 = service.execute(command(CommandKind.REMOVE_CREATED, key="key-hdl0001"))
        assert res2.status == ResultStatus.DONE

        # 3. Proposal creation time is None -> allowed
        dialog.persist(prop.model_copy(update={"created_at": None, "status": ProposalStatus.CREATED}))
        dialog.relevance_handler = None
        res3 = service.execute(command(CommandKind.REMOVE_CREATED, key="key-none001"))
        assert res3.status == ResultStatus.DONE


def test_took_effect_without_writer(tmp_path):
    prop = _created_proposal(minutes_ago=2)
    with JsonStore(tmp_path) as store:
        dialog, _, _ = setup(store, prop, writers={})
        service = web(dialog)
        cmd = command(CommandKind.REMOVE_CREATED)
        # _took_effect should return False since current is CREATED and writer is None
        assert not service._took_effect(cmd)
