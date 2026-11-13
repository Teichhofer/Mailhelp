"""6.1.6: content-free journal of the wall time of every processing step, next to the AI call journal.

One line per step and mail; at the end of a mail one more line ``stage="total"`` with the run time
(sum of the steps) and the time the mail waited in between (for example for the user's relevance
decision). No subjects, senders, texts or error messages are written.
"""
from __future__ import annotations

import json
import math
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

    def sibling(self, kind: str) -> Path:
        return self.path.with_name(f"{self.path.stem}-{kind}.json")

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


def quantile(values: list[float], share: float) -> float:
    """Nearest-rank quantile of a non-empty list (0,5 is the lower median for an even count)."""
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(share * len(ordered)) - 1))]


def median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Count, sum, median, 95 %, maximum, failures and AI share of a group of step lines."""
    durations = [row["duration_ms"] for row in rows]
    by_mail: dict[str, float] = {}
    for row in rows:
        if row.get("mail_id"):
            by_mail[row["mail_id"]] = by_mail.get(row["mail_id"], 0.0) + row["duration_ms"]
    return {"count": len(rows), "sum_ms": sum(durations), "median_ms": median(durations) if durations else None,
            "p95_ms": quantile(durations, .95) if durations else None, "max_ms": max(durations, default=None),
            "failed": sum(row["outcome"] == "failed" for row in rows),
            "llm_ms": sum(row["llm_ms"] for row in rows),
            "per_mail_median_ms": median(list(by_mail.values())) if by_mail else None}


def report(journal: StageJournal, *, days: int = 30, mode: str = "", stage: str = "", since: str = "",
           until: str = "") -> dict[str, Any]:
    """6.1.7: step times of the selected period; run times separately; nothing about mail content."""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    modes = {"standard", "local"} if mode == "production" else {mode}
    rows = [row for row in journal.records() if datetime.fromisoformat(row["started_at"]) >= cutoff
            and (not mode or row["mode"] in modes) and (not since or row["started_at"][:10] >= since)
            and (not until or row["started_at"][:10] <= until)]
    totals = [row for row in rows if row["stage"] == TOTAL]
    steps = [row for row in rows if row["stage"] != TOTAL and (not stage or row["stage"] == stage)]
    stages: dict[str, list[dict[str, Any]]] = {}
    for row in steps:
        stages.setdefault(row["stage"], []).append(row)
    parts: dict[str, float] = {}
    for row in steps:
        for name, value in row.get("parts", {}).items():
            parts[name] = parts.get(name, 0.0) + value
    waiting = [row["waiting_ms"] for row in totals]
    return {"stages": {name: summary(group) for name, group in stages.items()}, "total": summary(totals),
            "waiting_median_ms": median(waiting) if waiting else None, "parts": parts, "records": steps,
            "totals": totals, "damaged": journal.damaged, "failures": journal.failures}


def compact(journal: StageJournal) -> None:
    """Fold lines beyond the retention period into daily figures, replayably (as the AI journal does).

    The journal of the operation is written first; after a crash it is applied again instead of
    adding the same lines twice.
    """
    from ..storage import atomic_replace
    pending, daily = journal.sibling("compaction"), journal.sibling("daily")
    with journal._lock:
        if pending.exists():
            operation = json.loads(pending.read_text(encoding="utf-8"))
            atomic_replace(daily, json.dumps(operation["daily"], ensure_ascii=False, indent=2))
            atomic_replace(journal.path, operation["retained"])
            pending.unlink()
            journal._cache = None
        kept = journal.records()
        assert journal._cache is not None  # records() filled the validated cache
        expired = [item for item in journal._cache if item not in kept]
        if not expired:
            return
        aggregate = json.loads(daily.read_text(encoding="utf-8")) if daily.exists() else {}
        groups: dict[str, list[dict[str, Any]]] = {}
        for item in expired:
            groups.setdefault(json.dumps([item["started_at"][:10], item["mode"], item["stage"]]), []).append(item)
        for key, rows in groups.items():
            figures = summary(rows)
            previous = aggregate.get(key)
            if previous is not None:
                # A later fold of the same day adds counts and sums; medians stay those of the first fold.
                figures = {**previous, "count": previous["count"] + figures["count"],
                           "sum_ms": previous["sum_ms"] + figures["sum_ms"],
                           "failed": previous["failed"] + figures["failed"],
                           "llm_ms": previous["llm_ms"] + figures["llm_ms"],
                           "max_ms": max(previous["max_ms"], figures["max_ms"])}
            aggregate[key] = figures
        operation = {"daily": aggregate, "retained": "".join(json.dumps(item) + "\n" for item in kept)}
        atomic_replace(pending, json.dumps(operation, ensure_ascii=False, indent=2))
        atomic_replace(daily, json.dumps(aggregate, ensure_ascii=False, indent=2))
        atomic_replace(journal.path, operation["retained"])
        pending.unlink()
        journal._cache = None


def journal_path(metrics_path: Path) -> Path:
    """The step journal belongs to exactly one AI call journal (comparison runs keep their own)."""
    return metrics_path.with_name(f"{metrics_path.stem}-stages.jsonl")


__all__ = ["TOTAL", "StageJournal", "StageRecord", "compact", "journal_path", "median", "quantile", "report", "summary"]
