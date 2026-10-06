"""Restart-safe action ledger and duplicate lookup."""

from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
import re
from typing import Protocol


from ..models import ActionLedger, ActionLedgerEntry, Proposal, ProposalKind
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

        description = proposal.description
        if proposal.kind == ProposalKind.TASK:
            # Only the exact trailing block appended by ProposalBuilder is
            # provenance. Keep the actual task description in the identity.
            description = re.sub(
                r"(?:\n\n|^)Absender: [^\n]*\nBetreff: [^\n]*\nMail-Datum: [^\n]*\Z",
                "", description,
            )
        identity = {
            "kind": proposal.kind.value,
            "title": proposal.title.strip().casefold(),
            "description": description.strip().casefold(),
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
                action_key_version=2,
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
        upgraded = False
        for item in ledger.entries:
            if item.action_key_version == 2:
                continue
            name = f"proposal-{item.mail_id}-{item.proposal_id}"
            previous = self.store.load_model(f"{name}-v{item.proposal_version}", Proposal)
            if previous is None:
                previous = self.store.load_model(name, Proposal)
            if previous is not None and (
                previous.source_mail_id, previous.id, previous.version
            ) == (item.mail_id, item.proposal_id, item.proposal_version):
                item.action_key = self.action_key(previous)
                item.action_key_version = 2
                upgraded = True
        if upgraded:
            self.store.save("action-ledger", ledger.model_dump(mode="json"))
        current = (proposal.source_mail_id, proposal.id, proposal.version)
        key = self.action_key(proposal)
        return [
            item
            for item in ledger.entries
            if item.action_key == key
            and (item.mail_id, item.proposal_id, item.proposal_version) != current
        ]
