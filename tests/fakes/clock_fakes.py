"""A wall clock that steps back, as after an NTP or VM time-sync correction."""
from __future__ import annotations

from datetime import datetime, timedelta

# Every module that stamps a mail state with the wall clock.
STAMPING_MODULES = ("mailhelp.domain.mail", "mailhelp.persistence.proposals", "mailhelp.processing.orchestrator")


def stepping_clock(after: int, back: timedelta = timedelta(seconds=3)) -> type[datetime]:
    """A ``datetime`` whose ``now`` steps back by *back* after *after* calls."""
    calls = {"n": 0}

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            calls["n"] += 1
            value = datetime.now(tz)
            return value - back if calls["n"] > after else value

    return Clock


def step_back_wall_clock(monkeypatch, after: int, back: timedelta = timedelta(seconds=3)) -> None:
    """Let the wall clock of all stamping modules step back together."""
    clock = stepping_clock(after, back)
    for module in STAMPING_MODULES:
        # raising=False: after the fix a module may no longer import datetime at all.
        monkeypatch.setattr(f"{module}.datetime", clock, raising=False)
