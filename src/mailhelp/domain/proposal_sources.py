"""Bounded, content-free provenance and references for a canonical proposal."""
from datetime import datetime
from typing import Literal

from pydantic import Field

from ._base import StrictModel


class ProposalReference(StrictModel):
    mail_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    proposal_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")


class ProposalSource(ProposalReference):
    sent_at: datetime | None = None
    subject: str = Field(default="", max_length=500)
    anchors: list[str] = Field(default_factory=list, max_length=100)


class ProposalMatchDecision(StrictModel):
    candidate: int | None = Field(default=None, ge=0)
    relation: Literal["same_occurrence", "related_action", "different", "unclear"]
    reason: str = Field(min_length=1, max_length=1000)


class ProposalRelation(StrictModel):
    schema_version: Literal[1] = 1
    source: ProposalReference
    target: ProposalReference
    kind: Literal["related", "rsvp_for"]
