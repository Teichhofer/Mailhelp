"""Recognize mail the user sent to their own mailbox (Planung 4.5, step 16.1).

The sender header is untrusted and can be forged. ``self_mail`` therefore only
changes how the mail is read. It never authorizes an external write; every
proposal still needs an explicit, version-bound confirmation.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from email.utils import getaddresses

# Deliberately simple: addresses written in configuration or personal_info.
ADDRESS = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
NOTE_LIMIT = 2000


def addresses_in(texts: Iterable[str | None]) -> frozenset[str]:
    """Every address found in *texts*, case-insensitively."""
    return frozenset(match.casefold() for text in texts if text for match in ADDRESS.findall(text))


def sender_addresses(header: str) -> frozenset[str]:
    """Addresses of a From header; display names never count."""
    return frozenset(address.casefold() for _, address in getaddresses([header]) if ADDRESS.fullmatch(address))


def is_self_mail(sender: str, own: frozenset[str]) -> bool:
    """A single sender address that is one of the user's own addresses."""
    found = sender_addresses(sender)
    return len(found) == 1 and found <= own


def user_note(text: str | None) -> str | None:
    """The user's own words, bounded; an empty note is no note."""
    note = (text or "").strip()
    return note[:NOTE_LIMIT] or None


__all__ = ["NOTE_LIMIT", "addresses_in", "is_self_mail", "sender_addresses", "user_note"]
