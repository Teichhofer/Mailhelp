"""Local analysis snapshots and recoverable, content-minimal decision history."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from ..models import MailState, Proposal, ProposalStatus, Relevance, Summary
from ..storage import JsonStore


class AnalysisSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    mail_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{24}$")
    relevance: Relevance | None = None
    summary: Summary | None = None
    topics: dict[str, str] = Field(default_factory=dict)
    source: str = Field(default="unknown", max_length=200)
    human_decision: Literal["relevant", "irrelevant"] | None = None
    recorded_at: AwareDatetime | None = None
    removed: bool = False


class HistoryEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-f0-9]{32}$")
    proposal_id: str = Field(default="", pattern=r"^(?:[A-Za-z0-9_-]{1,64})?$")
    version: int = Field(ge=1)
    kind: str = Field(max_length=50)
    status: ProposalStatus | Literal["relevant", "irrelevant"]
    source: Literal["system", "web", "telegram"]
    at: AwareDatetime


class HistorySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    events: list[HistoryEvent] = Field(default_factory=list)
    removed: bool = False


def record_analysis(store: JsonStore, state: MailState, topics: dict[str, str], source: str) -> None:
    """A separate schema preserves display data independently of raw debug data."""
    if state.relevance is None and state.summary is None:
        return
    name = f"analysis-{state.id}"
    previous_model = AnalysisSnapshot.model_validate(store.load(name) or {})
    old = previous_model.model_dump(mode="json", exclude_unset=True)
    record = {
        "schema_version": 1, "mail_id": state.id,
        "relevance": old.get("relevance") or (state.relevance.model_dump(mode="json") if state.relevance else None),
        "summary": state.summary.model_dump(mode="json") if state.summary else old.get("summary"),
        "topics": old.get("topics", topics), "source": old.get("source", source),
        "human_decision": state.relevance_dialog.decision if state.relevance_dialog else None,
    }
    previous = {key: value for key, value in old.items() if key != "recorded_at"}
    if record != previous:
        record["recorded_at"] = state.updated_at.isoformat()
        store.save(name, record)


def record_event(store: JsonStore, proposal: Proposal, kind: str, source: str = "system",
                 operation: str = "", at: datetime | None = None) -> None:
    """Stable operation identity deduplicates recovery, without copying mail text."""
    identity = [proposal.id, proposal.version, kind, proposal.status.value, source, operation]
    identifier = hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:32]
    append_event(store, proposal.source_mail_id, HistoryEvent(
        id=identifier, proposal_id=proposal.id, version=proposal.version, kind=kind,
        status=proposal.status, source=source, at=at or datetime.now(timezone.utc)))


def record_relevance(store: JsonStore, state: MailState, source: str, operation: str) -> None:
    dialog = state.relevance_dialog
    if dialog is None or dialog.decision is None:
        return
    identifier = hashlib.sha256(json.dumps([state.id, dialog.version, dialog.decision, source, operation]).encode()).hexdigest()[:32]
    append_event(store, state.id, HistoryEvent(id=identifier, version=dialog.version,
                 kind="relevance", status=dialog.decision, source=source, at=state.updated_at))


def append_event(store: JsonStore, mail_id: str, event: HistoryEvent) -> None:
    name = f"history-{mail_id}"
    history = HistorySnapshot.model_validate(store.load(name) or {})
    if any(item.id == event.id for item in history.events):
        return
    history.events.append(event)
    store.save(name, history.model_dump(mode="json"))
