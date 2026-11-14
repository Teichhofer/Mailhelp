"""Tests for rejection reasons in ReviewCommand, ReviewService and learning log."""
from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from mailhelp.models import ProposalStatus
from mailhelp.review import CommandKind, CommandSource, ResultStatus, ReviewCommand, StaleCommand
from mailhelp.review.learning_log import DecisionLearningLog
from mailhelp.review.reject_reasons import REJECT_REASONS, USER_REJECT_REASONS
from mailhelp.review.views import ReviewViews
from mailhelp.storage import JsonStore
from tests.fakes.factories import build_proposal
from tests.fakes.shared_review import command, setup, web

MAIL = "a" * 24


def test_command_requires_reason_only_for_reject_reason():
    # Valid REJECT_REASON command
    cmd = command(CommandKind.REJECT_REASON, reason="not_for_me")
    assert cmd.reason == "not_for_me"

    # Missing reason
    with pytest.raises(ValidationError):
        command(CommandKind.REJECT_REASON)

    # Missing proposal_id
    with pytest.raises(ValidationError):
        ReviewCommand(kind=CommandKind.REJECT_REASON, source=CommandSource.WEB, actor="web:s",
                      mail_id=MAIL, proposal_id=None, version=1, idempotency_key="key-00000001",
                      reason="not_for_me")

    # Reason supplied to a command that forbids it
    with pytest.raises(ValidationError):
        command(CommandKind.REJECT, reason="not_for_me")


def test_set_and_replace_reject_reason_updates_proposal_and_learning_log(tmp_path):
    prop = build_proposal(status=ProposalStatus.REJECTED, source_mail_id=MAIL, id="p1", version=1)
    with JsonStore(tmp_path) as store:
        dialog, _, log = setup(store, prop)
        learning = DecisionLearningLog(store, 30, log)
        dialog.learning = learning

        # Record initial rejection in decisions.jsonl so _set_reject_reason finds it
        learning.proposal_decision(MAIL, "p1", 1, "reject", "web", "key-reject")

        service = web(dialog)
        result = service.execute(command(CommandKind.REJECT_REASON, reason="not_for_me"))
        assert result.status == ResultStatus.DONE
        assert result.message == f"Grund gespeichert: {REJECT_REASONS['not_for_me']}."

        # Verify proposal was updated
        updated = dialog.repository.load_current(MAIL, "p1")
        assert updated is not None
        assert updated.reject_reason == "not_for_me"

        # Verify learning log updated
        records = [json.loads(line) for line in learning.path.read_text(encoding="utf-8").splitlines()]
        assert records[0]["reject_reason"] == "not_for_me"

        # Verify view reflects reject_reason
        views = ReviewViews(store, "Europe/Berlin")
        view = views.proposal(MAIL, "p1")
        assert view is not None
        assert view.reject_reason == "not_for_me"

        # Replace reason
        result2 = service.execute(command(CommandKind.REJECT_REASON, reason="advertising", key="key-00000002"))
        assert result2.status == ResultStatus.DONE
        assert result2.message == f"Grund gespeichert: {REJECT_REASONS['advertising']}."

        updated2 = dialog.repository.load_current(MAIL, "p1")
        assert updated2 is not None
        assert updated2.reject_reason == "advertising"

        records2 = [json.loads(line) for line in learning.path.read_text(encoding="utf-8").splitlines()]
        assert records2[0]["reject_reason"] == "advertising"


def test_reject_reason_fails_for_non_rejected_proposal(tmp_path):
    prop = build_proposal(status=ProposalStatus.PENDING_CONFIRMATION, source_mail_id=MAIL, id="p1", version=1)
    with JsonStore(tmp_path) as store:
        dialog, _, _ = setup(store, prop)
        service = web(dialog)
        result = service.execute(command(CommandKind.REJECT_REASON, reason="not_for_me"))
        assert result.status == ResultStatus.INVALID
        with pytest.raises(ValueError, match="Grund kann nur für verworfene Vorschläge"):
            service.execute(command(CommandKind.REJECT_REASON, reason="not_for_me"), raise_errors=True)


def test_reject_reason_fails_for_unknown_reason():
    with pytest.raises(ValidationError, match="Unbekannter Ablehnungsgrund"):
        command(CommandKind.REJECT_REASON, reason="totally_bogus_reason")


def test_reject_reason_fails_for_stale_version_or_unknown_proposal(tmp_path):
    prop = build_proposal(status=ProposalStatus.REJECTED, source_mail_id=MAIL, id="p1", version=2)
    with JsonStore(tmp_path) as store:
        dialog, _, _ = setup(store, prop)
        service = web(dialog)
        result = service.execute(command(CommandKind.REJECT_REASON, version=1, reason="not_for_me"))
        assert result.status == ResultStatus.STALE

        missing = service.execute(command(CommandKind.REJECT_REASON, proposal_id="unknown", reason="not_for_me"))
        assert missing.status == ResultStatus.STALE


def test_reject_reason_restart_reconciliation(tmp_path):
    prop = build_proposal(status=ProposalStatus.REJECTED, source_mail_id=MAIL, id="p1", version=1, reject_reason="not_for_me")
    with JsonStore(tmp_path) as store:
        dialog, _, _ = setup(store, prop)
        service = web(dialog)

        # Effect already visible: reconcile succeeds
        cmd = command(CommandKind.REJECT_REASON, reason="not_for_me")
        result = service.reconcile(cmd)
        assert result.status == ResultStatus.DONE
        assert "Nach einem Neustart abgeglichen" in result.message

        # Effect not yet visible (different reason): reconcile reports failure
        cmd_diff = command(CommandKind.REJECT_REASON, reason="advertising")
        result_diff = service.reconcile(cmd_diff)
        assert result_diff.status == ResultStatus.FAILED


def test_reject_reason_unauthorized_web_actor(tmp_path):
    prop = build_proposal(status=ProposalStatus.REJECTED, source_mail_id=MAIL, id="p1", version=1)
    with JsonStore(tmp_path) as store:
        dialog, _, _ = setup(store, prop)
        service = web(dialog, allowed=False)
        result = service.execute(command(CommandKind.REJECT_REASON, reason="not_for_me"))
        assert result.status == ResultStatus.UNAUTHORIZED


def test_learning_log_reject_reason_edge_cases(tmp_path):
    from mailhelp.review.learning_log import DecisionLearningLog
    from tests.fakes.shared_telegram_dialog import Logger
    with JsonStore(tmp_path) as store:
        learning = DecisionLearningLog(store, "unlimited", Logger())

        # 1. decisions.jsonl does not exist
        learning.reject_reason(MAIL, "p1", 1, "not_for_me")
        assert not learning.path.is_file()

        # 2. decisions.jsonl exists with records that do not match kind == "reject" or IDs
        records = [
            {"mail_id": "other_mail", "proposal_id": "p1", "kind": "reject"},
            {"mail_id": MAIL, "proposal_id": "other_prop", "kind": "reject"},
            {"mail_id": MAIL, "proposal_id": "p1", "kind": "confirm"},
        ]
        learning.path.parent.mkdir(parents=True, exist_ok=True)
        learning.path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
        learning.reject_reason(MAIL, "p1", 1, "advertising")
        # File unchanged
        read_back = [json.loads(l) for l in learning.path.read_text(encoding="utf-8").splitlines()]
        assert all("reject_reason" not in r for r in read_back)


def test_reject_reason_service_direct_unregistered_reason(tmp_path):
    from mailhelp.review.commands import CommandSource as ReviewSource
    prop = build_proposal(status=ProposalStatus.REJECTED, source_mail_id=MAIL, id="p1", version=1)
    with JsonStore(tmp_path) as store:
        dialog, _, _ = setup(store, prop)
        service = web(dialog)
        cmd = ReviewCommand.model_construct(
            kind=CommandKind.REJECT_REASON,
            mail_id=MAIL,
            proposal_id="p1",
            version=1,
            source=ReviewSource.WEB,
            actor="web:session",
            idempotency_key="0" * 32,
            reason="unregistered",
        )
        with pytest.raises(ValueError, match="Unbekannter Ablehnungsgrund: unregistered"):
            service.execute(cmd, raise_errors=True)

