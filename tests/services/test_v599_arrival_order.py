"""Regression 5.9.9: web commands run in the order they arrived, also with a coarse system clock."""
from datetime import UTC, datetime, timedelta

import pytest

from mailhelp.review import CommandKind
from mailhelp.review import inbox as inbox_module
from mailhelp.review.inbox import MAX_QUEUED, ArrivalClock, CommandInbox
from mailhelp.storage import JsonStore
from tests.fakes.shared_review import command

FROZEN = datetime(2026, 11, 13, 7, tzinfo=UTC)
PAIRS = MAX_QUEUED // 2


class Frozen(datetime):
    """A wall clock that does not advance, like Windows' 15.6 ms steps for quick submissions."""

    @classmethod
    def now(cls, tz=None):
        return FROZEN


@pytest.fixture
def coarse(monkeypatch):
    monkeypatch.setattr(inbox_module, "datetime", Frozen)
    monkeypatch.setattr(inbox_module.time, "perf_counter_ns", lambda: 0)
    # A fresh process clock: the shared one must not keep the frozen time for later tests.
    monkeypatch.setattr(inbox_module, "_now", ArrivalClock())


def test_regression_a_reject_followed_by_a_confirm_keeps_its_order(tmp_path, coarse):
    """Regression 5.9.9: with Python 3.12 on Windows datetime.now() advances only every ~15.6 ms.
    Two web commands in the same step had the same received_at and were ordered by their random id,
    so a confirmation could run before the earlier rejection and create the entry."""
    with JsonStore(tmp_path) as store:
        inbox = CommandInbox(store)
        for index in range(PAIRS):
            inbox.submit(command(CommandKind.REJECT, key=f"key-reject-{index:04}", proposal_id=f"p{index}"))
            inbox.submit(command(CommandKind.CONFIRM, key=f"key-confirm-{index:04}", proposal_id=f"p{index}"))
        kinds = [(entry.command.proposal_id, entry.command.kind) for entry in inbox.queued()]
        assert kinds == [(f"p{index}", kind) for index in range(PAIRS) for kind in (CommandKind.REJECT,
                                                                                CommandKind.CONFIRM)]


def test_the_arrival_clock_strictly_increases_and_follows_the_wall_clock(monkeypatch):
    now, perf = [FROZEN], [0]

    class Moving(datetime):
        @classmethod
        def now(cls, tz=None):
            return now[0]
    monkeypatch.setattr(inbox_module, "datetime", Moving)
    monkeypatch.setattr(inbox_module.time, "perf_counter_ns", lambda: perf[0])
    clock = ArrivalClock()
    first, second = clock(), clock()
    assert second == first + timedelta(microseconds=1)
    # Between wall clock steps the high-resolution counter orders the calls.
    perf[0] += 3_000_000
    assert clock() == FROZEN + timedelta(milliseconds=3)
    # A larger deviation (clock adjusted, long uptime) re-bases on the wall clock ...
    now[0] = FROZEN + timedelta(hours=1)
    perf[0] += 1_000_000
    assert clock() == FROZEN + timedelta(hours=1)
    # ... but never backwards: the order of earlier arrivals is kept.
    now[0] = FROZEN
    perf[0] += 1_000
    later = clock()
    assert later == FROZEN + timedelta(hours=1, microseconds=1)
