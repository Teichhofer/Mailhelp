"""Additive authorization/journal fields preserve pre-3.6.17 state and require new consent on revision."""
import json
from pathlib import Path

from shared_telegram_dialog import Writer, controller

from mailhelp.domain.proposal import UNVERIFIED_LEGACY_ACTOR, Proposal, invalidate_creation_permissions
from mailhelp.domain.reconciliation import ProposalMergeJournal
from mailhelp.storage import JsonStore

FIXTURE = Path(__file__).parents[1] / "fixtures/safety_v36/legacy-proposal.json"


def test_legacy_confirmed_record_loads_and_reconciles_without_repeating_creation(tmp_path):
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    proposal = Proposal.model_validate(raw)
    assert proposal.confirmed_web_actor == UNVERIFIED_LEGACY_ACTOR and proposal.reconciliation_journal is None
    with JsonStore(tmp_path) as store:
        name = f"proposal-{proposal.source_mail_id}-{proposal.id}"
        store.save(name, raw)
        writer = Writer(found={"id": "previously-created"})
        for _ in range(2):
            dialog, _, _ = controller(store, writers={"todoist": writer})
            dialog.poll_once()
            current = store.load_model(name, Proposal)
            assert current.status == "created" and current.external_id == "previously-created"
            assert writer.created == 0


def test_revision_discards_web_authorization_but_retains_journal_provenance():
    proposal = Proposal.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    proposal = proposal.model_copy(update={"version": 2, "status": "pending_confirmation",
        "confirmed_web_actor": "web:" + "a" * 16, "reconciliation_journal": "reconciliation-merge-" + "b" * 64})
    revised = invalidate_creation_permissions(proposal)
    assert revised.confirmed_web_actor is None and revised.reconciliation_journal == proposal.reconciliation_journal


def test_legacy_completed_merge_journal_needs_no_migration():
    journal = ProposalMergeJournal.model_validate({"schema_version": 1, "status": "completed",
        "source": {"mail_id": "0" * 24, "proposal_id": "source"},
        "target": {"mail_id": "1" * 24, "proposal_id": "target"}, "source_version": 1, "target_version": 1})
    assert not journal.source_was_present
