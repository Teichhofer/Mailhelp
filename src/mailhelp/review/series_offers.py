"""Server-owned, actor-bound snapshots of the explicitly displayed series list."""
from __future__ import annotations

from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from ..models import Proposal
from ..proposals.proposal_reconciliation import ProposalReconciliationService
from ..storage import JsonStore
from .commands import CommandKind, CommandSource, ReviewCommand
from .series import OPEN, members


class SeriesOffer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    actor: str
    items: list[Proposal] = Field(min_length=1, max_length=100)
    answer: str | None = None
    endpoint: Literal["start", "end"] = "start"


def current_series(store: JsonStore, proposal: Proposal) -> list[Proposal]:
    return sorted((item for item in ProposalReconciliationService(store).current()
                   if item.source_mail_id == proposal.source_mail_id and item.kind == "event"
                   and item.series_key == proposal.series_key and item.status in OPEN),
                  key=lambda item: (str(item.start or item.known_temporal_facts), item.id))


def create_offer(store: JsonStore, offer: SeriesOffer) -> str:
    token = uuid4().hex
    store.save(f"series-offer-{token}", offer.model_dump(mode="json"))
    return token


def offer_command(offer: SeriesOffer, token: str, kind: CommandKind,
                  source: CommandSource, answer: str | None = None) -> ReviewCommand:
    first = offer.items[0]
    return ReviewCommand(kind=kind, source=source, actor=offer.actor,
        mail_id=first.source_mail_id, proposal_id=first.id, version=first.version,
        idempotency_key=f"series-{token}-{kind.value}", members=members(offer.items), text=answer,
        endpoint=offer.endpoint if kind == CommandKind.SERIES_ANSWER else "start")
