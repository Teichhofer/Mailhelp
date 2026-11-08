"""Who wrote a mail, and how routing and extraction receive it (Planung 4.5).

Shared by the mail pipeline and ``mailhelp-evaluate`` so that the corpus measures
exactly the input the application sends to the model.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..domain.mail import ForwardedHeaders
from ..domain.relevance import Relevance
from .forwarding import split_forward
from .identity import is_self_mail, user_note

SELF_NOTE_REASON = "Eigene Notiz: immer relevant"


@dataclass(frozen=True)
class Perspective:
    self_mail: bool = False
    user_note: str | None = None
    is_forwarding: bool = False
    forwarded_headers: ForwardedHeaders | None = None

    def own_relevance(self) -> Relevance | None:
        """4.5.6: what the user sends themselves is relevant without a topic decision.

        The configured topics describe mail from others; a note or forwarding of the
        user's own must not be filed away by them. This only spares the relevance
        call; every proposal still needs an explicit confirmation.
        """
        if not self.self_mail:
            return None
        return Relevance(decision="relevant", topic_ids=[], reason=SELF_NOTE_REASON)

    def model_input(self, mail: dict[str, Any]) -> dict[str, Any]:
        """The mail plus ``perspective``; mails of others that are no forwarding stay unchanged."""
        if not (self.self_mail or self.is_forwarding):
            return mail
        headers = self.forwarded_headers
        return {**mail, "perspective": {
            "self_mail": self.self_mail, "user_note": self.user_note, "is_forwarding": self.is_forwarding,
            "forwarded_headers": headers.model_dump() if headers is not None else None}}


def read_perspective(mail: dict[str, Any], own: frozenset[str]) -> Perspective:
    """Derive the perspective of a prepared mail from its sender and text."""
    headers = mail.get("headers") or {}
    text = mail.get("text")
    self_mail = is_self_mail(headers.get("from", ""), own)
    forward = split_forward(headers.get("subject", ""), text)
    # Above a forwarded message only the note is the user's own text.
    note = user_note(forward.note if forward is not None else text) if self_mail else None
    return Perspective(self_mail=self_mail, user_note=note, is_forwarding=forward is not None,
                       forwarded_headers=forward.headers if forward is not None else None)


__all__ = ["SELF_NOTE_REASON", "Perspective", "read_perspective"]
