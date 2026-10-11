"""Content-free per-attempt metrics, bounded queries and decimal cost estimates."""
from __future__ import annotations

import json
import os
import math
import secrets
import statistics
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from threading import RLock

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, FiniteFloat, model_validator


class MetricsSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    retention_days: int = Field(default=90, ge=1, le=3650)
    ollama_power_watts: float = Field(default=300, ge=0, le=100000, allow_inf_nan=False)
    electricity_eur_per_kwh: float = Field(default=0.30, ge=0, le=100, allow_inf_nan=False)
    usd_per_eur: float | None = Field(default=1.1, gt=0, allow_inf_nan=False)
    exchange_rate_date: date | None = None

    @model_validator(mode="after")
    def exchange_rate_pair(self):
        if self.exchange_rate_date is not None and self.usd_per_eur is None:
            raise ValueError("Ein Bezugsdatum erfordert einen konfigurierten Wechselkurs")
        return self


class AttemptRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-f0-9]{32}$")
    call_id: str = Field(max_length=500)
    attempt: int = Field(ge=1)
    mail_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{24}$")
    run_id: str = Field(default="unknown", max_length=100)
    logical_call_id: str = Field(default="unknown", max_length=500)
    server: str = Field(default="unknown", max_length=500)
    backend: str = Field(default="unknown", max_length=200)
    test_mail_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    mode: str = Field(max_length=30)
    model: str = Field(max_length=500)
    stage: str = Field(max_length=100)
    provider: str = Field(max_length=200)
    started_at: AwareDatetime
    start: FiniteFloat
    end: FiniteFloat
    duration_ms: FiniteFloat = Field(ge=0)
    status: str = Field(pattern=r"^(success|failed)$")
    tokens: dict[str, int | None]
    cost_usd: Decimal | None = Field(ge=0, allow_inf_nan=False)
    power_watts: FiniteFloat = Field(ge=0)
    electricity_price: FiniteFloat = Field(ge=0)


def electricity(intervals: list[tuple[float, float]], watts, price) -> Decimal:
    """Merge occupied server intervals to avoid charging concurrency twice."""
    seconds = 0.0
    end = float("-inf")
    for start, finish in sorted(intervals):
        seconds += max(0, finish - max(start, end))
        end = max(end, finish)
    return Decimal(str(seconds)) * Decimal(str(watts)) * Decimal(str(price)) / Decimal(3600000)


def server_electricity(records: list[dict]) -> Decimal:
    """A sweep merges overlaps; the most recent active assumption wins."""
    events = []
    for index, row in enumerate(records):
        if row["end"] > row["start"]:
            events.extend([(row["start"], True, index), (row["end"], False, index)])
    active = {}
    previous = 0
    total = Decimal(0)
    for point, begin, index in sorted(events):
        if active:
            recent = max(active.values(), key=lambda item: item["start"])
            total += electricity([(previous, point)], recent["power_watts"], recent["electricity_price"])
        if begin:
            active[index] = records[index]
        else:
            active.pop(index)
        previous = point
    return total


# Successful contacts are taken from events that are logged anyway; showing the
# status never triggers a request.  Keys are (module, event).
CONTACT_EVENTS = {
    ("imap", "request_completed"): "IMAP-Postfach",
    ("imap", "message_fetched"): "IMAP-Postfach",
    ("decisions", "jev_relevance_completed"): "Jev (Relevanz)",
    ("telegram", "message_sent"): "Telegram",
    ("telegram", "message_received"): "Telegram",
    ("todoist", "create_completed"): "Todoist",
    ("todoist", "duplicate_updated"): "Todoist",
    ("google_calendar", "create_completed"): "Google Kalender",
    ("google_calendar", "duplicate_updated"): "Google Kalender",
    ("google_oauth", "token_credentials_accepted"): "Google-Anmeldung",
}
LLM_CONTACT = {"standard": "KI-Modelle (OpenRouter)", "local": "Ollama", "decision_test": "KI-Vergleichslauf"}


PRODUCTION_FILE = "llm.jsonl"
DECISION_TEST_FILE = "decision-tests.jsonl"


def metrics_directory(log_directory: Path) -> Path:
    """Metrics are content-free JSONL logs and live next to the other logs."""
    return log_directory / "metrics"


def adopt_legacy(legacy: Path, target: Path) -> bool:
    """Move a metrics file and its aggregates from the former state location once.

    Up to 1.2 beta the files lived in the state directory.  Nothing is merged or
    overwritten: an existing target always wins, so a repeated start is harmless.
    """
    if not legacy.exists() or target.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    for old, new in ((legacy, target),
                     (legacy.with_name("daily.json"), sibling(target, "daily")),
                     (legacy.with_name("compaction.json"), sibling(target, "compaction"))):
        if old.exists():
            os.replace(old, new)
    return True


def sibling(path: Path, kind: str) -> Path:
    """Aggregate and journal belong to exactly one metrics file."""
    return path.with_name(f"{path.stem}-{kind}.json")


class MetricsRecorder:
    def __init__(self, path: Path, settings: MetricsSettings, mode: str = "standard"):
        self.path, self.settings, self.mode = path, settings, mode
        self._lock = RLock()
        self._pending: dict[str, dict] = {}
        self._cache: list[dict] | None = None
        self._cache_signature = None
        self.activity = {"stage": "idle", "mail_id": None, "started": time.monotonic()}
        self.contacts = {}
        self.failures = 0
        self.run_id = secrets.token_hex(16)
        self.test_mail_hash = None
        self.comparison = None
        self.changed = lambda: None

    def runtime(self) -> dict:
        with self._lock:
            return {**self.activity, "elapsed": time.monotonic() - self.activity["started"], "contacts": dict(self.contacts)}

    def expected_services(self) -> list[str]:
        """The services this process talks to, in display order."""
        models = ([LLM_CONTACT["local"]] if self.mode == "local"
                  else [LLM_CONTACT["standard"], "Jev (Relevanz)"])
        return ["IMAP-Postfach", *models, "Telegram", "Todoist", "Google Kalender", "Google-Anmeldung"]

    def observe(self, event: str, context: dict) -> None:
        with self._lock:
            self._observe(event, context)

    def _observe(self, event: str, context: dict) -> None:
        if event == "state_persisted":
            stage = ("failed" if context.get("failed") else "waiting_for_user" if context.get("awaiting_relevance") else
                     next((key for key, value in context["state"].items() if value == "pending"), "idle"))
            if stage != self.activity["stage"]:
                self.activity = {"stage": stage, "mail_id": context.get("mail_id"), "started": time.monotonic()}
                self.changed()
        elif event == "idle_started":
            self.activity = {"stage": "idle", "mail_id": None, "started": time.monotonic(),
                             "next_poll": (datetime.now(timezone.utc) + timedelta(seconds=context["delay_seconds"])).isoformat()}
            self.changed()
        contact = CONTACT_EVENTS.get((context.get("service"), event))
        if event == "response_received":
            contact = LLM_CONTACT[self.mode]
        if contact is not None:
            self.contacts[contact] = datetime.now(timezone.utc).isoformat()
        if event == "processing_started":
            self.activity = {"stage": "preparation", "mail_id": context.get("mail_id"), "started": time.monotonic()}
        elif event in {"processing_completed", "processing_failed", "llm_rate_limited"}:
            self.activity = {"stage": "idle", "mail_id": None, "started": time.monotonic()}
        elif event == "request_started":
            self.activity = {**self.activity, "stage": context.get("stage", "unknown"), "started": time.monotonic()}
        if event in {"processing_started", "processing_completed", "processing_failed", "llm_rate_limited", "request_started"}:
            self.changed()
        if not self.settings.enabled:
            return
        call = context.get("call_id")
        if not isinstance(call, str):
            return
        with self._lock:
            raw = context.get("response")
            if isinstance(raw, dict):
                context = {**context, "token_usage": context.get("token_usage") or raw.get("usage"),
                           "reported_cost": context.get("reported_cost") or raw.get("cost"),
                           "provider": context.get("provider") or raw.get("provider")}
            if event == "request_started":
                if call in self._pending:
                    self._finish(call, "failed", {})
                self._pending[call] = {
                    "id": secrets.token_hex(16), "call_id": call,
                    "attempt": context.get("attempt", 1), "mode": self.mode,
                    "mail_id": context.get("mail_id") or self.activity["mail_id"],
                    "run_id": self.run_id, "logical_call_id": context.get("correlation_id") or call,
                    "test_mail_hash": self.test_mail_hash,
                    "server": context.get("server", "unknown"), "backend": context.get("backend", "unknown"),
                    "model": str(context.get("model", "unknown")),
                    "stage": str(context.get("stage", context.get("step", "unknown"))),
                    "provider": "ollama" if self.mode == "local" or context.get("backend", "").startswith(("Ollama", "Laya")) else "unknown",
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    "start": time.time(), "monotonic": time.monotonic(),
                }
            elif event == "token_usage_recorded" and call in self._pending:
                self._pending[call]["token_usage"] = context.get("token_usage")
            elif event in {"response_received", "request_failed", "invalid_json", "provider_response_invalid", "retry_failed"}:
                self._finish(call, "success" if event == "response_received" else "failed", context)

    def _finish(self, call: str, status: str, context: dict) -> None:
        item = self._pending.pop(call, None)
        if item is None:
            return
        item["duration_ms"] = max(0, (time.monotonic() - item.pop("monotonic")) * 1000)
        item["end"] = item["start"] + item["duration_ms"] / 1000
        item["status"] = status
        provider = context.get("provider")
        if isinstance(provider, str) and len(provider) <= 200:
            item["provider"] = provider
        pending_usage = item.pop("token_usage", None)
        usage = context.get("token_usage") or pending_usage or {}
        usage = usage if isinstance(usage, dict) else {}
        item["tokens"] = {key: usage.get(key) if type(usage.get(key)) is int and 0 <= usage[key] <= 10**12 else None for key in ("prompt_tokens", "completion_tokens")}
        cost = context.get("reported_cost")
        if cost is None:
            cost = usage.get("cost")
        try:
            number = Decimal(str(cost))
            item["cost_usd"] = str(number) if number.is_finite() and number >= 0 else None
        except InvalidOperation:
            item["cost_usd"] = None
        item["power_watts"] = self.settings.ollama_power_watts
        item["electricity_price"] = self.settings.electricity_eur_per_kwh
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(item, ensure_ascii=False) + "\n")
            stream.flush()
        self._cache = None
        self.changed()

    def records(self) -> tuple[list[dict], int]:
        with self._lock:
            damaged = 0
            signature = (self.path.stat().st_mtime_ns, self.path.stat().st_size) if self.path.exists() else None
            if self._cache is None or signature != self._cache_signature:
                self._cache_signature = signature
                self._cache = []
                seen = set()
                if self.path.exists():
                    with self.path.open(encoding="utf-8") as stream:
                        for line in stream:
                            try:
                                item = AttemptRecord.model_validate_json(line).model_dump(mode="json")
                                if item["id"] not in seen:
                                    seen.add(item["id"])
                                    self._cache.append(item)
                            except (ValueError, KeyError, TypeError):
                                damaged += 1
                self._damaged = damaged
            cutoff = datetime.now(timezone.utc) - timedelta(days=self.settings.retention_days)
            records = [item for item in self._cache if datetime.fromisoformat(item["started_at"]) >= cutoff]
            return records, self._damaged

    def report(self, *, days: int = 30, model: str = "", stage: str = "", mode: str = "",
               since: str = "", until: str = "", provider: str = "") -> dict:
        if since:
            date.fromisoformat(since)
        if until:
            date.fromisoformat(until)
        if since and until and since > until:
            raise ValueError("Ungültiger Zeitraum")
        if not 1 <= days <= 3650:
            raise ValueError("Ungültiger Zeitraum")
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        records, damaged = self.records()
        records = [item for item in records if datetime.fromisoformat(item["started_at"]) >= cutoff
                   and (not model or item["model"] == model) and (not stage or item["stage"] == stage)
                   and (not mode or (item["mode"] in {"standard", "local"} if mode == "production" else item["mode"] == mode)) and (not provider or item["provider"] == provider)
                   and (not since or item["started_at"][:10] >= since)
                   and (not until or item["started_at"][:10] <= until)]
        durations = sorted(item["duration_ms"] / 1000 for item in records)
        costs = [Decimal(item["cost_usd"]) for item in records if item["cost_usd"] is not None]
        local = [item for item in records if item["provider"] == "ollama"]
        energy = sum((server_electricity([row for row in local if row["server"] == server])
                      for server in {row["server"] for row in local}), Decimal(0))
        groups = {}
        for row in records:
            groups.setdefault((row["mode"], row["model"], row["stage"], row["provider"]), []).append(row)
        summaries = []
        for key, rows in sorted(groups.items()):
            times = sorted(row["duration_ms"] / 1000 for row in rows)
            summaries.append({"mode": key[0], "model": key[1], "stage": key[2], "provider": key[3],
                              "count": len(rows), "failed": sum(row["status"] != "success" for row in rows),
                              "seconds": sum(times), "mean": statistics.mean(times), "median": statistics.median(times),
                              "p95": times[math.ceil(len(times)*.95)-1],
                              "usd": str(sum((Decimal(row["cost_usd"]) for row in rows if row["cost_usd"] is not None), Decimal(0)))})
        return {"count": len(records), "failed": sum(r["status"] != "success" for r in records),
                "unknown_cost": sum(r["cost_usd"] is None and r["provider"] != "ollama" for r in records), "usd": str(sum(costs, Decimal(0))),
                "cloud_eur": str(sum(costs, Decimal(0))/Decimal(str(self.settings.usd_per_eur))) if self.settings.usd_per_eur else None,
                "exchange_rate_date": str(self.settings.exchange_rate_date) if self.settings.exchange_rate_date else None,
                "electricity_eur": str(energy), "seconds": sum(durations),
                "mean": statistics.mean(durations) if durations else None,
                "median": statistics.median(durations) if durations else None,
                "p95": durations[max(0, math.ceil(len(durations) * .95) - 1)] if durations else None,
                "damaged": damaged, "capture_failures": self.failures, "groups": summaries, "records": records}

    def maintain(self) -> None:
        """Main-thread pruning with a replayable compaction journal.

        Daily aggregates contain no mail/call IDs. The journal is written first;
        recovery replaces both outputs instead of incrementing a sum twice.
        """
        from .learning import _atomic_replace
        with self._lock:
            pending = sibling(self.path, "compaction")
            daily = sibling(self.path, "daily")
            if pending.exists():
                operation = json.loads(pending.read_text(encoding="utf-8"))
                _atomic_replace(daily, json.dumps(operation["daily"], ensure_ascii=False, indent=2))
                _atomic_replace(self.path, operation["retained"])
                pending.unlink()
                self._cache = None
            records, _ = self.records()
            # records() intentionally filters expired data; read its validated cache
            # here to aggregate those records before physically removing them.
            expired = [item for item in self._cache if item not in records]
            if not expired:
                return
            aggregate = json.loads(daily.read_text(encoding="utf-8")) if daily.exists() else {}
            for item in expired:
                key = json.dumps([item["started_at"][:10], item["mode"], item["model"], item["stage"], item["provider"]])
                row = aggregate.setdefault(key, {"count": 0, "failed": 0, "seconds": 0, "usd": "0", "unknown_cost": 0})
                row["count"] += 1
                row["failed"] += item["status"] != "success"
                row["seconds"] += item["duration_ms"] / 1000
                row["unknown_cost"] += item["cost_usd"] is None
                row["usd"] = str(Decimal(row["usd"]) + Decimal(item["cost_usd"] or "0"))
            operation = {"daily": aggregate, "retained": "".join(json.dumps(item) + "\n" for item in records)}
            _atomic_replace(pending, json.dumps(operation, ensure_ascii=False, indent=2))
            _atomic_replace(daily, json.dumps(aggregate, ensure_ascii=False, indent=2))
            _atomic_replace(self.path, operation["retained"])
            pending.unlink()
            self._cache = None
