"""Bounded, secret-redacted evidence from the actual DecisionLearningLog format."""
from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

MAX_BYTES, MAX_RECORDS, MAX_EVIDENCE = 1_000_000, 200, 100


def signal(record: dict[str, Any]) -> str | None:
    kind = record.get("kind")
    relevance = (record.get("analysis") or {}).get("relevance") or {}
    proposal = record.get("proposal") or {}
    if kind == "already_done":
        return "positive_already_done"
    if kind == "reject":
        return "rejected_proposal"
    if kind in {"edit", "answer"} and proposal.get("changes"):
        return "manual_correction"
    if kind == "relevance" and record.get("decision") in {"relevant", "irrelevant"}:
        return "relevance_disagreement" if record["decision"] != relevance.get("decision") else None
    if kind == "confirm" and not relevance.get("topic_ids"):
        return "unclassified_confirmation"
    return None


class DecisionRuleMiner:
    def __init__(self, path: Path, redact: Callable[[str], str] = lambda text: text):
        self.path, self.redact = path, redact

    def mine(self) -> tuple[list[dict[str, Any]], int]:
        if not self.path.exists():
            return [], 0
        with self.path.open("rb") as stream:
            offset = max(0, self.path.stat().st_size - MAX_BYTES)
            stream.seek(offset)
            if offset:
                stream.readline()
            lines = stream.read(MAX_BYTES).splitlines()[-MAX_RECORDS:]
        evidence, seen, skipped = [], set(), 0
        for line in reversed(lines):
            try:
                record = json.loads(line)
                item = self._evidence(record)
            except (ValueError, TypeError, AttributeError):
                item = None
            if item is None or item["id"] in seen:
                skipped += 1
                continue
            seen.add(item["id"])
            evidence.append(item)
            if len(evidence) == MAX_EVIDENCE:
                break
        return evidence, skipped

    def _evidence(self, record: Any) -> dict[str, Any] | None:
        if not isinstance(record, dict) or record.get("schema_version") != 1:
            return None
        identity = record.get("id")
        reason = signal(record)
        if not isinstance(identity, str) or not 1 <= len(identity) <= 64 or reason is None:
            return None
        mail = record.get("mail") or {}
        relevance = (record.get("analysis") or {}).get("relevance") or {}
        proposal = record.get("proposal") or {}
        fields = ("title", "description", "due_date", "start", "end")
        return {"id": identity, "signal": reason,
                "subject": self.redact(str((mail.get("headers") or {}).get("subject", "")))[:200],
                "text": self.redact(str((mail.get("content") or {}).get("text", "")))[:1000],
                "topic_ids": [str(key)[:64] for key in relevance.get("topic_ids", [])][:20],
                "decision": str(record.get("decision") or record.get("kind")),
                "answer": self.redact(str(record.get("answer") or ""))[:500],
                "changes": {key: self.redact(str(value))[:500]
                            for key, value in (proposal.get("changes") or {}).items() if key in fields}}

    @staticmethod
    def counts(evidence: list[dict[str, Any]]) -> dict[str, int]:
        return dict(Counter(item["signal"] for item in evidence))
