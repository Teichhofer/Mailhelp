"""Planung 4.1, Schritt 9.9: model factories produce valid defaults and apply only changes."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from mailhelp.domain.proposal import ProposalStatus
from tests.fakes.factories import (
    MAIL_ID,
    build_mail_state,
    build_proposal,
    complete_settings,
    merged,
    minimal_settings,
)


def test_a_default_proposal_is_a_certain_new_user_task_waiting_for_confirmation():
    item = build_proposal()
    assert (item.kind, item.status, item.source_mail_id) == ("task", ProposalStatus.PENDING_CONFIRMATION, MAIL_ID)


@pytest.mark.parametrize("changes", [{"responsibility": "other"}, {"certainty": "uncertain"},
                                     {"classification": "change"}, {"open_questions": ["Wann?"]}])
def test_doubtful_proposals_need_clarification_unless_a_status_is_given(changes):
    assert build_proposal(**changes).status == ProposalStatus.NEEDS_CLARIFICATION
    assert build_proposal(status="confirmed", **changes).status == ProposalStatus.CONFIRMED


def test_invalid_changes_are_rejected_by_the_real_model():
    with pytest.raises(ValidationError):
        build_proposal(kind="meeting")


def test_mail_state_keeps_creation_before_update_and_merges_imap_identity():
    updated = datetime(2026, 11, 5, 8, tzinfo=UTC)
    state = build_mail_state(uid=7, updated=updated, imap={"folder": "Archiv"}, proposals=[build_proposal()])
    assert state.created_at == updated - timedelta(days=1) and state.updated_at == updated
    assert (state.imap.folder, state.imap.uid, state.imap.account_id) == ("Archiv", 7, "0" * 24)
    assert state.display_headers.subject == "Elternabend" and len(state.proposals) == 1
    assert build_mail_state(sender=None).display_headers is None


def test_settings_changes_merge_nested_values(tmp_path):
    cfg = minimal_settings(tmp_path, imap={"folders": ["INBOX", "Archiv"]}, poll_interval_seconds=30)
    assert cfg.imap.folders == ["INBOX", "Archiv"] and cfg.imap.host == "h"
    assert cfg.poll_interval_seconds == 30 and cfg.test_mode
    assert str(cfg.data_directory).startswith(str(tmp_path))


def test_complete_settings_are_the_shipped_example_below_the_temporary_directory(tmp_path):
    cfg = complete_settings(tmp_path, test_mode=True)
    assert cfg.imap.host == "imap.example.test" and cfg.test_mode
    assert str(cfg.data_directory).startswith(str(tmp_path))
    assert str(cfg.logging.directory).startswith(str(tmp_path))


def test_merging_never_changes_the_base():
    base = {"a": {"b": 1, "c": [1]}, "d": 1}
    assert merged(base, {"a": {"b": 2}, "d": {"e": 1}}) == {"a": {"b": 2, "c": [1]}, "d": {"e": 1}}
    assert base == {"a": {"b": 1, "c": [1]}, "d": 1}
