"""Restart-safe action ledger and duplicate lookup."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from typing import Protocol


from ..models import ActionLedger, ActionLedgerEntry, Proposal
from ..storage import JsonStore


class ActionLedgerPort(Protocol):
    def book_created(self, proposal: Proposal) -> None: ...
    def prior_actions(self, proposal: Proposal) -> list[ActionLedgerEntry]: ...


class ActionLedgerService:
    """Record externally created actions and detect semantic duplicates."""

    def __init__(self, store: JsonStore):
        self.store = store

    @staticmethod
    def action_key(proposal: Proposal) -> str:
        def encoded(value: date | datetime | None) -> str | None:
            return value.isoformat() if value is not None else None

        identity = {
            "kind": proposal.kind.value,
            "title": proposal.title.strip().casefold(),
            "description": proposal.description.strip().casefold(),
            "target": proposal.target,
            "due": encoded(proposal.due),
            "start": encoded(proposal.start),
            "end": encoded(proposal.end),
            "all_day": proposal.all_day,
            "location": (proposal.location or "").strip().casefold(),
            "video_link": str(proposal.video_link)
            if proposal.video_link is not None
            else None,
        }
        return hashlib.sha256(
            json.dumps(
                identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()

    def book_created(self, proposal: Proposal) -> None:
        ledger = self.store.load_model("action-ledger", ActionLedger, ActionLedger())
        assert isinstance(ledger, ActionLedger)
        reference = (proposal.source_mail_id, proposal.id, proposal.version)
        if any(
            (item.mail_id, item.proposal_id, item.proposal_version) == reference
            for item in ledger.entries
        ):
            return
        ledger.entries.append(
            ActionLedgerEntry(
                action_key=self.action_key(proposal),
                mail_id=proposal.source_mail_id,
                proposal_id=proposal.id,
                proposal_version=proposal.version,
                kind=proposal.kind,
                title=proposal.title,
                target=proposal.target,
                external_id=proposal.external_id,
                external_link=proposal.external_link,
            )
        )
        self.store.save("action-ledger", ledger.model_dump(mode="json"))

    def prior_actions(self, proposal: Proposal) -> list[ActionLedgerEntry]:
        ledger = self.store.load_model("action-ledger", ActionLedger, ActionLedger())
        assert isinstance(ledger, ActionLedger)
        current = (proposal.source_mail_id, proposal.id, proposal.version)
        key = self.action_key(proposal)
        return [
            item
            for item in ledger.entries
            if item.action_key == key
            and (item.mail_id, item.proposal_id, item.proposal_version) != current
        ]
