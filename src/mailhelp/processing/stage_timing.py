"""6.1.6: wall time of every processing step, measured where the pipeline switches ``run.stage``.

The clock only emits the content-free event ``stage_finished``; ``MetricsRecorder`` writes the line,
adds the time spent in AI calls and, at the end of a mail, the run time. Measuring never writes
files itself and never stops the processing.
"""
from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, nullcontext
from typing import Any, Literal

Outcome = Literal["completed", "failed", "deferred"]


class StageClock:
    def __init__(self, emit: Callable[[dict[str, Any]], None], mail_id: str, analysis_round: int, resumed: bool,
                 monotonic: Callable[[], float] = time.monotonic, wall: Callable[[], float] = time.time):
        self.emit, self.mail_id, self.analysis_round, self.resumed = emit, mail_id, analysis_round, resumed
        self.monotonic, self.wall = monotonic, wall
        self.current: str | None = None
        self.started = self.started_wall = 0.0
        self.parts: dict[str, float] = {}

    def enter(self, stage: str) -> None:
        """A new step begins; the previous one is complete."""
        if stage == self.current:
            return
        self.finish("completed")
        self.current, self.started, self.started_wall, self.parts = stage, self.monotonic(), self.wall(), {}

    @contextmanager
    def part(self, name: str) -> Iterator[None]:
        """A measured part of the current step, e.g. the parsing within the preparation."""
        started = self.monotonic()
        try:
            yield
        finally:
            self.parts[name] = self.parts.get(name, 0.0) + (self.monotonic() - started) * 1000

    def finish(self, outcome: Outcome, *, final: bool = False) -> None:
        """End the current step; *final* marks the end of the whole mail (run time follows)."""
        if self.current is None:
            return
        ended = self.monotonic()
        self.emit({"mail_id": self.mail_id, "stage": self.current, "outcome": outcome,
                   "started_wall": self.started_wall, "duration_ms": (ended - self.started) * 1000,
                   "parts": {key: round(value, 3) for key, value in self.parts.items()},
                   "analysis_round": self.analysis_round, "resumed": self.resumed, "final": final})
        self.current, self.parts = None, {}


def part(timer: StageClock | None, name: str) -> Any:
    """A measured part, or nothing when the run is not timed (tests, metrics switched off)."""
    return timer.part(name) if timer is not None else nullcontext()


__all__ = ["Outcome", "StageClock", "part"]
