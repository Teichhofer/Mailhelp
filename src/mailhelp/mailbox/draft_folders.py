"""Which folder of a mailbox receives reply drafts (Planung 4.8, 19.1).

The configured ``drafts_folder`` wins. If the server does not have it, the folder the
server marks as ``\\Drafts`` (SPECIAL-USE, RFC 6154) is used when exactly one exists,
otherwise a common name. Without any of them no draft is written.
"""
from __future__ import annotations

import imaplib
from typing import Any, cast

from .imap import ListedMailbox, _list_mailbox_name

COMMON_NAMES = ("Drafts", "Entwürfe", "Entwurf", "INBOX.Drafts", "INBOX/Drafts", "[Gmail]/Entwürfe",
                "[Gmail]/Drafts")


def listed_folders(connection: imaplib.IMAP4) -> list[ListedMailbox]:
    """Every selectable folder the server lists, with its SPECIAL-USE role."""
    status, data = cast(Any, connection).list()
    if status != "OK":
        raise ValueError("IMAP-Ordnerliste konnte nicht geladen werden")
    return [folder for item in data or [] if (folder := _list_mailbox_name(item)) is not None]


def choose_drafts_folder(configured: str, listed: list[ListedMailbox]) -> str | None:
    """The configured folder if it exists, else the unique ``\\Drafts`` folder, else a common name."""
    names = {folder.name for folder in listed}
    if configured in names:
        return configured
    marked = [folder.name for folder in listed if folder.role == "drafts"]
    if len(marked) == 1:
        return marked[0]
    return next((name for name in COMMON_NAMES if name in names), None)


__all__ = ["COMMON_NAMES", "choose_drafts_folder", "listed_folders"]
