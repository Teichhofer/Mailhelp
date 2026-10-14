"""Bounded archive queries over a revision-invalidated in-memory metadata index."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..models import MailState, ProposalStatus
from ..storage import CorruptState, JsonStore, mail_state_names
from .archive import AnalysisSnapshot, HistorySnapshot
from .filters import matches
from .search import SEPARATOR, bounded, excerpt, fold, terms


class ArchiveQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    q: str = Field(default="", max_length=200)
    # "all" also searches the mail text and the recognised attachment text (2.3).
    scope: Literal["all", "meta"] = "all"
    filter: Literal["", "events", "tasks", "clarification", "attachments", "duplicates"] = ""
    relevance: Literal["", "relevant", "irrelevant", "unclear", "unknown"] = ""
    topic: str = Field(default="", max_length=100)
    state: Literal["", "failed", "waiting", "completed", "no_action"] = ""
    kind: Literal["", "state", "edit", "edit_fields", "confirm", "confirm_duplicate", "reject", "clarify", "answer",
                  "cancel", "relevance", "legacy"] = ""
    proposal_kind: Literal["", "task", "event"] = ""
    status: ProposalStatus | Literal["relevant", "irrelevant"] | None = None
    since: date | None = None
    until: date | None = None
    sort: Literal["received", "updated"] = "received"
    # Mailbox number (3.1); only offered with several mailboxes.
    postfach: int | None = Field(default=None, ge=1, le=99)
    page: int = Field(default=1, ge=1, le=1000000)
    size: int = Field(default=25, ge=1, le=100)

    @model_validator(mode="after")
    def interval(self):
        if self.since and self.until and self.since > self.until:
            raise ValueError("Datumsbereich ist umgekehrt")
        return self


class ArchiveQueries:
    def __init__(self, store: JsonStore, zone: str = "UTC"):
        self.store = store
        self.zone = ZoneInfo(zone)
        self._revision = -1
        self._items: list[dict] = []
        self.damaged = 0
        self._history_revision = -1
        self._history: list[dict[str, Any]] = []
        # Account id -> (number, label) of every enabled mailbox; empty with a single mailbox (3.1).
        self.mailboxes: dict[str, tuple[int, str]] = {}

    def items(self) -> list[dict]:
        with self.store.locked():
            if self._revision != self.store.archive_revision:
                self._rebuild()
            return list(self._items)

    def _rebuild(self) -> None:
        items = []
        self.damaged = 0
        for name in mail_state_names(self.store):
            try:
                state = self.store.peek_model(name, MailState)
                snapshot = self.store.peek_model(f"analysis-{name[5:]}", AnalysisSnapshot)
                analysis = snapshot.model_dump(mode="json") if snapshot is not None else {}
            except CorruptState:
                self.damaged += 1
                continue
            if state is None:
                continue
            headers = state.display_headers
            relevance = {} if analysis.get("removed") else analysis.get("relevance") or (
                state.relevance.model_dump(mode="json") if state.relevance else {})
            summary = {} if analysis.get("removed") else analysis.get("summary") or (
                state.summary.model_dump(mode="json") if state.summary else {})
            mail = state.prepared
            received = mail.received if mail is not None else None
            try:
                stamp = datetime.fromisoformat(received) if received is not None else None
                received = stamp.isoformat() if stamp and stamp.tzinfo else None
            except ValueError:
                received = None
            sender = headers.sender if headers else "—"
            subject = headers.subject if headers else "Mail ohne Betreff"
            summary_text = " ".join(summary.get("sentences", []))
            meta = [("Absender", sender), ("Betreff", subject), ("Zusammenfassung", summary_text)]
            content = bounded([("Mailtext", mail.text or ""), *(
                (f"Anhang „{item.filename}“", f"{item.filename}\n{item.text}")
                for item in mail.extracted_attachments)] if mail is not None else [])
            items.append({"id": state.id, "account": state.imap.account_id, "sender": sender, "subject": subject,
                          "received": received, "updated": state.updated_at.isoformat(),
                          "relevance": (state.relevance_dialog.decision if state.relevance_dialog else None)
                                       or relevance.get("decision", "unknown"),
                          "topics": relevance.get("topic_ids", []),
                          "summary": summary_text,
                          "failed": state.error is not None,
                          "waiting": state.awaiting_relevance,
                          "completed": state.steps.completion == "completed",
                          "statuses": [p.status.value for p in state.proposals],
                          "kinds": {p.id: p.kind.value for p in state.proposals},
                          "attachments": mail is not None and bool(mail.extracted_attachments),
                          "duplicate": state.duplicate is not None,
                          "text_available": mail is not None and mail.text is not None,
                          # Folded copies for matching; fields for the excerpt of a hit.
                          "fields": meta + content,
                          "meta_folded": SEPARATOR.join(fold(text) for _, text in meta),
                          "content_folded": SEPARATOR.join(fold(text) for _, text in content)})
        self._items, self._revision = items, self.store.archive_revision

    def search(self, query: ArchiveQuery) -> tuple[list[dict], int]:
        """Matching mails, newest first; each page item carries where the first term matched."""
        items = []
        wanted = terms(query.q)
        for item in self.items():
            if not matches(query.filter, item["kinds"].values(), item["statuses"] + [item["relevance"]],
                           item["attachments"], item["duplicate"]):
                continue
            day = datetime.fromisoformat(item[query.sort] or item["updated"]).astimezone(self.zone).date()
            haystack = item["meta_folded"] + (SEPARATOR + item["content_folded"] if query.scope == "all" else "")
            if not all(term in haystack for term in wanted):
                continue
            if query.relevance and query.relevance != item["relevance"]:
                continue
            if query.topic and query.topic not in item["topics"]:
                continue
            if query.state == "no_action" and item["statuses"]:
                continue
            if query.state in {"failed", "waiting", "completed"} and not item[query.state]:
                continue
            if query.status and str(query.status) not in item["statuses"]:
                continue
            if query.since and day < query.since or query.until and day > query.until:
                continue
            if query.postfach is not None and self.mailboxes.get(item["account"], (None,))[0] != query.postfach:
                continue
            items.append(item)
        def order(item: dict[str, Any]) -> tuple[float, str]:
            return datetime.fromisoformat(item[query.sort] or item["updated"]).timestamp(), item["id"]
        items.sort(key=order, reverse=True)
        start = (query.page - 1) * query.size
        page = items[start:start + query.size]
        fields = (lambda item: item["fields"][:3]) if query.scope == "meta" else (lambda item: item["fields"])
        return [{**item, "hit": excerpt(fields(item), wanted)} for item in page], len(items)

    def history(self) -> list[dict]:
        with self.store.locked():
            if self._history_revision == self.store.archive_revision:
                return list(self._history)
            rows = []
            for item in self.items():
                try:
                    snapshot = self.store.peek_model(f'history-{item["id"]}', HistorySnapshot)
                    record = snapshot.model_dump(mode="json") if snapshot is not None else {}
                except CorruptState:
                    continue
                events = record.get("events", [])
                if record.get("removed"):
                    continue
                if not events:
                    rows.append({"at": item["updated"], "mail_id": item["id"], "title": item["subject"],
                                 "proposal_id": "", "version": "", "kind": "legacy", "proposal_kind": "",
                                 "status": "Altbestand / Ablauf nicht vollständig erfasst", "source": "unbekannt"})
                for event in events:
                    rows.append({**event, "mail_id": item["id"], "title": item["subject"],
                                 "proposal_kind": item["kinds"].get(event["proposal_id"], "")})
            self._history, self._history_revision = rows, self.store.archive_revision
            return list(rows)
