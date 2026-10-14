"""Versioned local merge intents and bounded semantic comparison results."""
from typing import Literal

from pydantic import Field, model_validator

from ._base import StrictModel
from .proposal import Proposal
from .proposal_sources import ProposalMatchDecision, ProposalReference


class ProposalMergeJournal(StrictModel):
    schema_version: Literal[1] = 1
    source: ProposalReference
    target: ProposalReference
    source_version: int = Field(ge=1)
    target_version: int = Field(ge=1)
    policy: str = Field(default="", max_length=64)
    status: Literal["prepared", "completed"] = "prepared"
    alias: Proposal | None = None
    revision: Proposal | None = None

    @model_validator(mode="after")
    def validate_payload(self) -> "ProposalMergeJournal":
        if self.source == self.target:
            raise ValueError("Abgleich braucht zwei unterschiedliche Vorschläge")
        if self.status == "completed":
            if self.alias is not None or self.revision is not None:
                raise ValueError("Abgeschlossener Abgleich enthält keine Inhalte")
        else:
            if self.alias is None or self.revision is None:
                raise ValueError("Vorbereiteter Abgleich benötigt beide Revisionen")
            if ((self.alias.source_mail_id, self.alias.id, self.alias.version) !=
                    (self.source.mail_id, self.source.proposal_id, self.source_version + 1) or
                    (self.revision.source_mail_id, self.revision.id) !=
                    (self.target.mail_id, self.target.proposal_id) or
                    self.revision.version not in {self.target_version, self.target_version + 1}):
                raise ValueError("Abgleichrevision passt nicht zur gebundenen Version")
        return self


class ProposalMatchCache(StrictModel):
    schema_version: Literal[1] = 1
    call_id: str = Field(max_length=200)
    decision: ProposalMatchDecision
