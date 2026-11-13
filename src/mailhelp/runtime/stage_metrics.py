"""6.1.6: content-free journal of the wall time of every processing step, next to the AI call journal.

One line per step and mail; at the end of a mail one more line ``stage="total"`` with the run time
(sum of the steps) and the time the mail waited in between (for example for the user's relevance
decision). No subjects, senders, texts or error messages are written.
"""
from __future__ import annotations

import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, FiniteFloat

TOTAL = "total"


class StageRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-f0-9]{32}$")
    mail_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{24}$")
    run_id: str = Field(max_length=100)
    mode: str = Field(max_length=30)
    stage: str = Field(max_length=100)
    started_at: AwareDatetime
    duration_ms: FiniteFloat = Field(ge=0)
    llm_ms: FiniteFloat = Field(default=0, ge=0)
    outcome: Literal["completed", "failed", "deferred"]
    analysis_round: int = Field(default=1, ge=1)
    resumed: bool = False
    parts: dict[str, FiniteFloat] = Field(default_factory=dict)
    # Only for stage "total": time between the first step and the end that no step used.
    waiting_ms: FiniteFloat = Field(default=0, ge=0)


class StageJournal:
    def __init__(self, path: Path, retention_days: Callable[[], int]):
        self.path, self.retention_days = path, retention_days
        self._lock = RLock()
        self._cache: list[dict[str, Any]] | None = None
        self._signature: tuple[int, int] | None = None
        self.damaged = 0
        self.failures = 0

    def write(self, record: StageRecord) -> None:
        """Append one line; a failure is counted and never interrupts the processing."""
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as stream:
                    stream.write(record.model_dump_json() + "\n")
                self._cache = None
        except OSError:
            self.failures += 1

    def records(self) -> list[dict[str, Any]]:
        """Valid lines within the retention period, each id once; damaged lines are counted."""
        with self._lock:
            signature = (self.path.stat().st_mtime_ns, self.path.stat().st_size) if self.path.exists() else None
            if self._cache is None or signature != self._signature:
                self._signature, self._cache, self.damaged, seen = signature, [], 0, set()
                if self.path.exists():
                    for line in self.path.read_text(encoding="utf-8").splitlines():
                        try:
                            item = StageRecord.model_validate_json(line).model_dump(mode="json")
                        except ValueError:
                            self.damaged += 1
                            continue
                        if item["id"] not in seen:
                            seen.add(item["id"])
                            self._cache.append(item)
            cutoff = datetime.now(UTC) - timedelta(days=self.retention_days())
            return [item for item in self._cache if datetime.fromisoformat(item["started_at"]) >= cutoff]

    def finish(self, context: dict[str, Any], run_id: str, mode: str, llm_ms: float) -> None:
        """Write the step of a ``stage_finished`` event and, at the end of a mail, its run time."""
        started = datetime.fromtimestamp(float(context["started_wall"]), UTC)
        record = StageRecord(id=secrets.token_hex(16), mail_id=context.get("mail_id"), run_id=run_id, mode=mode,
                             stage=str(context["stage"]), started_at=started,
                             duration_ms=max(0.0, float(context["duration_ms"])), llm_ms=llm_ms,
                             outcome=context["outcome"], analysis_round=int(context.get("analysis_round", 1)),
                             resumed=bool(context.get("resumed")), parts=dict(context.get("parts") or {}))
        self.write(record)
        if context.get("final") and record.mail_id is not None:
            self.write(self.total(record))

    def total(self, last: StageRecord) -> StageRecord:
        """Run time of a mail: the sum of its steps in this analysis round; waiting is the rest."""
        steps = [item for item in self.records() if item["mail_id"] == last.mail_id
                 and item["analysis_round"] == last.analysis_round and item["stage"] != TOTAL]
        first = min(datetime.fromisoformat(item["started_at"]) for item in steps)
        end = last.started_at + timedelta(milliseconds=last.duration_ms)
        busy = sum(item["duration_ms"] for item in steps)
        elapsed = (end - first).total_seconds() * 1000
        return StageRecord(id=secrets.token_hex(16), mail_id=last.mail_id, run_id=last.run_id, mode=last.mode,
                           stage=TOTAL, started_at=first, duration_ms=busy,
                           llm_ms=sum(item["llm_ms"] for item in steps), outcome="completed",
                           analysis_round=last.analysis_round, waiting_ms=max(0.0, elapsed - busy))


def journal_path(metrics_path: Path) -> Path:
    """The step journal belongs to exactly one AI call journal (comparison runs keep their own)."""
    return metrics_path.with_name(f"{metrics_path.stem}-stages.jsonl")


__all__ = ["TOTAL", "StageJournal", "StageRecord", "journal_path"]
