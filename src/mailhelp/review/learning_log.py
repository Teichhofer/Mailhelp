"""Durable record of every manual decision as training material for later learning.

One JSON line per decision joins what is otherwise spread across state files
with their own retention: the mail, the language-model results, the proposal
as first suggested and as decided, and the decision itself.  Full prompts and
model responses are copied only with ``learning.decision_llm_content``.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any

from .. import state_names
from ..models import MailState, Proposal
from ..storage import JsonStore, atomic_replace

LEARNING_FILE = Path("learning") / "decisions.jsonl"
# Bookkeeping fields that change on every transition and say nothing about content.
_UNCOMPARED = frozenset({"version", "status", "simulation_notified", "external_id", "external_link"})


def learning_path(directory: Path) -> Path:
    return directory / LEARNING_FILE


def _changes(original: dict[str, Any] | None, decided: dict[str, Any] | None) -> dict[str, list[Any]]:
    if original is None or decided is None:
        return {}
    return {key: [original.get(key), decided.get(key)] for key in sorted(set(original) | set(decided))
            if key not in _UNCOMPARED and original.get(key) != decided.get(key)}


def _dump(value: Any) -> Any:
    return value.model_dump(mode="json") if value is not None else None


def _read(path: Path) -> list[dict[str, Any]]:
    """Every intact record; a line damaged by a crash mid-write is skipped."""
    if not path.is_file():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def prune(directory: Path, period: int | str, now: datetime) -> int:
    """Remove records older than *period* days; ``disabled`` removes all, ``unlimited`` none."""
    path = learning_path(directory)
    if period == "unlimited" or not path.is_file():
        return 0
    records = _read(path)
    cutoff = None if period == "disabled" else now - timedelta(days=int(period))
    kept = [record for record in records if cutoff is not None and _recent(record, cutoff)]
    if len(kept) != len(records):
        atomic_replace(path, "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in kept))
    return len(records) - len(kept)


def _recent(record: dict[str, Any], cutoff: datetime) -> bool:
    try:
        recorded = datetime.fromisoformat(str(record.get("recorded_at")))
    except ValueError:
        return False
    return recorded.tzinfo is not None and recorded > cutoff


class DecisionLearningLog:
    """Append one record per manual decision; a repeated decision is recorded once."""

    def __init__(self, store: JsonStore, period: int | str, logger: Any, *,
                 llm_logs: Iterable[Path] = (), clock: Callable[[], datetime] | None = None):
        self.store, self.period, self.logger = store, period, logger
        # Rotated LLM logs to search for full content; empty unless explicitly enabled.
        self.llm_logs = tuple(llm_logs)
        self.clock = clock or (lambda: datetime.now(UTC))
        self.path = learning_path(store.directory)
        self._lock = Lock()
        self._known: set[str] | None = None

    def proposal_decision(self, mail_id: str, proposal_id: str, version: int, kind: str, source: str,
                          operation: str, answer: str | None = None) -> None:
        self._guarded(lambda: self._proposal(mail_id, proposal_id, version, kind, source, operation, answer))

    def relevance_decision(self, mail_id: str, source: str, operation: str) -> None:
        self._guarded(lambda: self._relevance(mail_id, source, operation))

    def _guarded(self, record: Callable[[], None]) -> None:
        """Learning data must never stop or undo the decision it describes."""
        if self.period == "disabled":
            return
        try:
            record()
        except Exception as exc:
            self.logger.event("WARNING", "learning", "decision_record_failed", error_class=type(exc).__name__)

    def _relevance(self, mail_id: str, source: str, operation: str) -> None:
        state = self.store.load_model(state_names.mail(mail_id), MailState)
        dialog = state.relevance_dialog if isinstance(state, MailState) else None
        if state is None or dialog is None or dialog.decision is None:
            return
        self._append(state, {"kind": "relevance", "source": source, "operation": operation,
                             "proposal_id": None, "version": dialog.version, "decision": dialog.decision,
                             "answer": None, "proposal": None})

    def _proposal(self, mail_id: str, proposal_id: str, version: int, kind: str, source: str,
                  operation: str, answer: str | None) -> None:
        state = self.store.load_model(state_names.mail(mail_id), MailState)
        if not isinstance(state, MailState):
            return
        result = self._load(state_names.proposal(mail_id, proposal_id))
        if result is None:
            return
        decided = self._load(state_names.proposal(mail_id, proposal_id, version))
        if decided is None and result.get("version") == version:
            decided = result
        original = self._original(state, proposal_id)
        self._append(state, {"kind": kind, "source": source, "operation": operation,
                             "proposal_id": proposal_id, "version": version, "decision": None,
                             "answer": answer, "proposal": {
                                 "original": original, "decided": decided, "result": result,
                                 "changes": _changes(original, decided)}})

    def _load(self, name: str) -> dict[str, Any] | None:
        value = self.store.load(name)
        return Proposal.model_validate(value).model_dump(mode="json") if isinstance(value, dict) else None

    def _original(self, state: MailState, proposal_id: str) -> dict[str, Any] | None:
        """The proposal as the language model first suggested it."""
        prefix = state_names.proposal(state.id, proposal_id) + "-v"
        versions = sorted(int(name[len(prefix):]) for name in self.store.names(prefix)
                          if name[len(prefix):].isdigit())
        if versions:
            return self._load(f"{prefix}{versions[0]}")
        first = next((item for item in state.normalized_proposals if item.id == proposal_id), None)
        return first.model_dump(mode="json") if first is not None else None

    def _append(self, state: MailState, decision: dict[str, Any]) -> None:
        identity = [state.id, decision["proposal_id"], decision["version"], decision["kind"],
                    decision["decision"], decision["answer"]]
        identifier = hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:32]
        with self._lock:
            if self._known is None:
                self._known = {str(record.get("id")) for record in _read(self.path)}
            if identifier in self._known:
                return
            record = {"schema_version": 1, "id": identifier, "recorded_at": self.clock().isoformat(),
                      "mail_id": state.id, **decision,
                      "mail": {"headers": _dump(state.display_headers), "content": state.mail},
                      "analysis": {"relevance": _dump(state.relevance), "summary": _dump(state.summary),
                                   "action_route": _dump(state.action_route),
                                   "task_extraction": _dump(state.task_extraction),
                                   "event_extraction": _dump(state.event_extraction),
                                   "config_fingerprint": state.config_fingerprint,
                                   "llm_call_ids": state.llm_call_ids},
                      "llm_content": self._llm_content(state.llm_call_ids)}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._known.add(identifier)
        self.logger.event("INFO", "learning", "decision_recorded", kind=decision["kind"], source=decision["source"])

    def _llm_content(self, call_ids: list[str]) -> list[dict[str, Any]] | None:
        """Prompts and responses of this mail's calls, as far as the LLM log still holds them."""
        if not self.llm_logs:
            return None
        wanted, found = set(call_ids), []
        for path in self.llm_logs:
            for entry in _read(path):
                if entry.get("call_id") in wanted and ("request" in entry or "response" in entry):
                    found.append({key: entry.get(key) for key in
                                  ("call_id", "stage", "model", "event", "request", "response")})
        return found
