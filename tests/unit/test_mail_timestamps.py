"""MailState timestamps under a wall clock that steps back (regression from the 4.0.0 acceptance)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from clock_fakes import step_back_wall_clock

from mailhelp.models import MailState, next_updated_at

IDENTITY = {"id": "a" * 24, "config_fingerprint": "f" * 64,
            "imap": {"account_id": "0" * 24, "folder": "INBOX", "uidvalidity": 1, "uid": 1}}


def test_a_new_state_reads_the_clock_once_even_if_it_steps_back_in_between(monkeypatch):
    """Regression: two separate clock readings produced updated_at before created_at."""
    step_back_wall_clock(monkeypatch, 1, timedelta(hours=1))
    state = MailState(**IDENTITY)
    assert state.created_at == state.updated_at


def test_a_given_creation_time_is_also_the_first_update_time():
    created = datetime(2026, 11, 4, 12, tzinfo=UTC)
    assert MailState(**IDENTITY, created_at=created).updated_at == created


def test_given_timestamps_are_kept_and_still_validated():
    created, updated = datetime(2026, 11, 4, 12, tzinfo=UTC), datetime(2026, 11, 4, 13, tzinfo=UTC)
    state = MailState(**IDENTITY, created_at=created, updated_at=updated)
    assert (state.created_at, state.updated_at) == (created, updated)
    with pytest.raises(ValueError, match="updated_at darf nicht vor created_at"):
        MailState(**IDENTITY, created_at=updated, updated_at=created)


def test_only_mappings_are_completed():
    assert MailState.one_creation_instant("unverändert") == "unverändert"


def test_next_updated_at_is_now_but_never_earlier_than_before(monkeypatch):
    state = MailState(**IDENTITY)
    assert next_updated_at(state) >= state.updated_at
    step_back_wall_clock(monkeypatch, 0, timedelta(hours=1))
    assert next_updated_at(state) == state.updated_at
