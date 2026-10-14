"""Callback encoding, parsing, validation, and proposal transitions."""

from __future__ import annotations

import secrets
from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from ..domain.proposal_sources import ProposalReference
from ..models import Proposal, ProposalStatus
from ..storage import JsonStore
from .models import InternalTelegramModel


class DecisionAction(StrEnum):
    CONFIRM = "confirm"
    CONFIRM_DUPLICATE = "confirm_duplicate"
    EDIT = "edit"
    REJECT = "reject"
    MERGE_SOURCE = "merge_source"
    SEPARATE_SOURCE = "separate_source"
    RETARGET = "retarget"


class RelevanceDecision(InternalTelegramModel):
    mail_id: str = Field(pattern=r"^[a-f0-9]{24}$")
    version: int = Field(ge=1)
    decision: str = Field(pattern=r"^(relevant|irrelevant)$")

    def encode(self) -> str:
        return f"relevance:{self.mail_id}:{self.version}:{self.decision}"

    @classmethod
    def parse(cls, value: str) -> RelevanceDecision:
        parts = value.split(":")
        if (
            len(parts) != 4
            or parts[0] != "relevance"
            or not parts[2].isascii()
            or not parts[2].isdigit()
        ):
            raise ValueError("Ungültige Relevanzentscheidung")
        return cls(mail_id=parts[1], version=int(parts[2]), decision=parts[3])


class Decision(InternalTelegramModel):
    mail_id: str = Field(pattern=r"^[a-f0-9]{24}$")
    proposal_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,32}$")
    version: int = Field(ge=1)
    action: DecisionAction
    additional_ref: ProposalReference | None = None
    additional_version: int | None = Field(default=None, ge=1)
    target_profile: int | None = Field(default=None, ge=1, le=99)
    profile_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_additional(self):
        if (self.action == DecisionAction.RETARGET) != (
            self.target_profile is not None and self.profile_hash is not None
        ):
            raise ValueError("Zielwechsel benötigt Profil und geprüfte Zielkonfiguration")
        if self.action != DecisionAction.RETARGET and (
            self.target_profile is not None or self.profile_hash is not None
        ):
            raise ValueError("Nur Zielwechsel enthält ein Profil")
        needs = self.action in {DecisionAction.MERGE_SOURCE, DecisionAction.SEPARATE_SOURCE}
        if needs != (self.additional_ref is not None and self.additional_version is not None):
            raise ValueError("Quellenentscheidung benötigt beide Vorschlagsversionen")
        if not needs and (self.additional_ref is not None or self.additional_version is not None):
            raise ValueError("Nur Quellenentscheidungen enthalten eine zusätzliche Quelle")
        return self

    def encode(self, store: JsonStore | None = None) -> str:
        """Encode a decision, preferably as an opaque, durable callback token.

        The store-less form is retained solely for short, already-issued legacy
        callbacks and deliberately refuses values Telegram could not transport.
        """
        if store is None:
            if self.additional_ref is not None:
                raise ValueError("Quellenentscheidung benötigt einen dauerhaften Callback-Token")
            value = f"proposal:{self.mail_id}:{self.proposal_id}:{self.version}:{self.action.value}"
            validate_callback_data(value)
            return value
        while True:
            token = secrets.token_hex(16)
            name = f"telegram-callback-{token}"
            if store.load(name) is None:
                store.save(name, self.model_dump(mode="json"))
                return f"decision:{token}"

    @classmethod
    def parse(cls, value: str, store: JsonStore | None = None) -> Decision:
        validate_callback_data(value)
        if value.startswith("decision:"):
            token = value.removeprefix("decision:")
            if len(token) != 32 or any(
                character not in "0123456789abcdef" for character in token
            ):
                raise ValueError("Ungültiger Callback-Token")
            record = (
                store.load(f"telegram-callback-{token}") if store is not None else None
            )
            if record is None:
                raise ValueError("Unbekannter Callback-Token")
            if not isinstance(record, dict) or not isinstance(
                record.get("action"), str
            ):
                raise ValueError("Ungültiger Callback-Datensatz")
            return cls.model_validate(
                {**record, "action": DecisionAction(record["action"])}
            )
        parts = value.split(":")
        if (
            len(parts) != 5
            or parts[0] != "proposal"
            or not parts[3].isascii()
            or not parts[3].isdigit()
        ):
            raise ValueError("Ungültige Aktion")
        return cls(
            mail_id=parts[1],
            proposal_id=parts[2],
            version=int(parts[3]),
            action=DecisionAction(parts[4]),
        )


def validate_callback_data(value: str) -> None:
    """Enforce Telegram's documented callback_data UTF-8 byte boundary locally."""
    size = len(value.encode("utf-8"))
    if not 1 <= size <= 64:
        raise ValueError(
            f"Telegram callback_data muss 1 bis 64 UTF-8-Bytes lang sein (ist {size})"
        )


def validate_callback_markup(reply_markup: dict[str, Any] | None) -> None:
    if reply_markup is None:
        return
    for row in reply_markup.get("inline_keyboard", []):
        for button in row:
            if "callback_data" in button:
                value = button["callback_data"]
                if not isinstance(value, str):
                    raise ValueError(
                        "Telegram callback_data muss eine Zeichenkette sein"
                    )
                validate_callback_data(value)


def apply_decision(
    proposal: Proposal,
    decision: Decision,
    user_id: int,
    chat_id: int,
    allowed_user: int,
    allowed_chat: int,
) -> Proposal:
    if (user_id, chat_id) != (allowed_user, allowed_chat):
        raise PermissionError("Nicht autorisierte Telegram-Anfrage")
    if (decision.mail_id, decision.proposal_id, decision.version) != (
        proposal.source_mail_id,
        proposal.id,
        proposal.version,
    ):
        raise ValueError("Veraltete oder unpassende Bestätigung")
    if proposal.status != ProposalStatus.PENDING_CONFIRMATION:
        return proposal
    if decision.action == DecisionAction.CONFIRM:
        return proposal.model_copy(update={"status": ProposalStatus.CONFIRMED})
    if decision.action == DecisionAction.REJECT:
        return proposal.model_copy(update={"status": ProposalStatus.REJECTED})
    return proposal.model_copy(update={"status": ProposalStatus.NEEDS_CLARIFICATION})
