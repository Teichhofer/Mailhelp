"""Autorisierte Telegram-Dialoge und versionsgebundene Entscheidungen."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable
import httpx
from .models import Proposal, ProposalStatus


@dataclass(frozen=True)
class Decision:
    proposal_id: str
    version: int
    action: str


def apply_decision(proposal: Proposal, decision: Decision, user_id: int, chat_id: int, allowed_user: int, allowed_chat: int) -> Proposal:
    if (user_id, chat_id) != (allowed_user, allowed_chat): raise PermissionError("Nicht autorisierte Telegram-Anfrage")
    if decision.proposal_id != proposal.id or decision.version != proposal.version: raise ValueError("Veraltete oder unpassende Bestätigung")
    if proposal.status != ProposalStatus.PENDING_CONFIRMATION: return proposal
    if decision.action == "confirm":
        if proposal.open_questions: raise ValueError("Offene Fragen verhindern die Bestätigung")
        return proposal.model_copy(update={"status": ProposalStatus.CONFIRMED})
    if decision.action == "reject": return proposal.model_copy(update={"status": ProposalStatus.REJECTED})
    if decision.action == "edit": return proposal.model_copy(update={"status": ProposalStatus.NEEDS_CLARIFICATION})
    raise ValueError("Unbekannte Telegram-Aktion")


def split_message(text: str, limit: int = 4000) -> list[str]:
    if limit < 1: raise ValueError("limit muss positiv sein")
    return [text[index:index + limit] for index in range(0, len(text), limit)] or [""]


class TelegramClient:
    def __init__(self, token: str, timeout: float, transport: httpx.BaseTransport | None = None): self.client = httpx.Client(base_url=f"https://api.telegram.org/bot{token}", timeout=timeout, transport=transport)
    def poll(self, offset: int, timeout: int = 30) -> list[dict[str, Any]]:
        response = self.client.get("/getUpdates", params={"offset": offset, "timeout": timeout}); response.raise_for_status(); return response.json()["result"]
    def send(self, chat_id: int, text: str) -> None:
        for part in split_message(text):
            response = self.client.post("/sendMessage", json={"chat_id": chat_id, "text": part}); response.raise_for_status()
    def close(self) -> None: self.client.close()

