"""5.2 V1: the verification contract and the safe handling of VERIFYING by every status consumer."""
from datetime import UTC, datetime, timedelta

import pytest

from mailhelp.domain.proposal import ProposalStatus
from mailhelp.domain.verification import (
    FINAL,
    TRANSITIONS,
    WRITTEN,
    VerificationState,
    WriteVerification,
    allowed,
    fingerprint,
    operation_id,
)
from mailhelp.external.confirmed import execute_confirmed
from mailhelp.proposals.proposal_reconciliation import PROTECTED
from mailhelp.review.views import STATUS_LABELS
from mailhelp.web.review_pages import _STATE_BADGE
from tests.scenarios.web_scenario import mail_id, proposal

NOW = datetime(2026, 11, 10, 9, tzinfo=UTC)
EXPECTED = {"title": "Unterlagen senden", "due": "2026-11-11", "project": "Inbox"}


def record(**fields):
    data = dict(id=operation_id(mail_id(3), "a", 2, "create"), mail_id=mail_id(3), proposal_id="a",
                proposal_version=2, idempotency_key="mailhelp:x:a:v2", operation="create",
                target={"profile": 1, "provider": "todoist", "account": "konto-1", "container": "Inbox"},
                receipt={"external_id": "123", "written_at": NOW, "result": "created"},
                expected=EXPECTED, expected_fingerprint=fingerprint(EXPECTED), next_check_at=NOW,
                deadline_at=NOW + timedelta(minutes=5), created_at=NOW, updated_at=NOW)
    data.update(fields)
    return WriteVerification.model_validate(data)


def test_a_pending_verification_names_its_write_target_receipt_and_expected_facts():
    item = record()
    assert item.state == VerificationState.PENDING and item.receipt.external_id == "123"
    assert fingerprint({"due": "2026-11-11", "project": "Inbox", "title": "Unterlagen senden"}) == \
        item.expected_fingerprint
    assert operation_id(mail_id(3), "a", 3, "create") != item.id


@pytest.mark.parametrize(("change", "message"), [
    ({"id": "0" * 32}, "genau einer Vorschlagsversion"),
    ({"expected_fingerprint": "0" * 64}, "Fingerabdruck"),
    ({"receipt": None}, "Schreibbeleg"),
    ({"next_check_at": None}, "nächsten Prüfzeitpunkt"),
    ({"state": "verified", "next_check_at": None}, "Prüfzeitpunkt und keine Abweichung"),
    ({"state": "mismatch", "next_check_at": None}, "abweichenden Felder"),
    ({"differences": {"due": {"expected": "a", "actual": "b"}}}, "abweichenden Felder"),
    ({"deadline_at": datetime(2026, 11, 10, 9)}, "Zeitzone"),
])
def test_an_inconsistent_record_is_rejected(change, message):
    with pytest.raises(ValueError, match=message):
        record(**change)


def test_final_states_and_legacy_records():
    verified = record(state="verified", next_check_at=None, checked_at=NOW)
    mismatch = record(state="mismatch", next_check_at=None, checked_at=NOW,
                      differences={"due": {"expected": "2026-11-11", "actual": "2026-11-12"}})
    legacy = record(state="legacy_unverified", next_check_at=None, receipt=None)
    assert (verified.state, mismatch.differences["due"].actual, legacy.receipt) == (
        VerificationState.VERIFIED, "2026-11-12", None)
    assert VerificationState.PENDING not in FINAL and len(FINAL) == len(VerificationState) - 1


def test_transitions_never_lead_from_a_written_entry_back_to_a_write():
    assert allowed(ProposalStatus.WRITING, ProposalStatus.VERIFYING)
    assert allowed(ProposalStatus.UNCERTAIN, ProposalStatus.VERIFYING)
    assert allowed(ProposalStatus.VERIFYING, ProposalStatus.CREATED)
    for old in (ProposalStatus.VERIFYING, ProposalStatus.CREATED, ProposalStatus.UNCERTAIN):
        for start in (ProposalStatus.CONFIRMED, ProposalStatus.WRITING):
            assert not allowed(old, start)
    assert not allowed(ProposalStatus.WRITING, ProposalStatus.CREATED)  # only through a verification
    assert allowed(ProposalStatus.PENDING_CONFIRMATION, ProposalStatus.CONFIRMED)  # not governed here
    assert set(TRANSITIONS) | {ProposalStatus.VERIFYING} >= WRITTEN


def test_every_status_consumer_knows_verifying():
    assert STATUS_LABELS[ProposalStatus.VERIFYING] == "Gespeichert – Eintrag wird geprüft"
    assert set(STATUS_LABELS) == set(ProposalStatus) and set(_STATE_BADGE) == set(ProposalStatus)
    assert ProposalStatus.VERIFYING in PROTECTED


def test_a_verifying_proposal_is_never_written_again():
    class Writer:
        def reconcile(self, key):
            raise AssertionError("kein Abgleich und kein Schreiben bei VERIFYING")
    item = proposal(3, "a", status="verifying", external_id="123")
    persisted = []
    assert execute_confirmed(item, Writer(), persisted.append) == (item, {"verifying": True})
    assert persisted == []
    with pytest.raises(ValueError, match="externe ID"):
        proposal(3, "b", status="verifying")
