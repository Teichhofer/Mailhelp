"""Links that open the original mail in the user's mail program (Planung 4.7).

The Message-ID comes from an untrusted header. It is reduced to one ``id-left@id-right``
value and percent-encoded completely before it becomes part of a link, so no header
content can add a scheme, a query or markup. Without a usable Message-ID there is no link.
"""
from __future__ import annotations

import re
from typing import Literal
from urllib.parse import quote

MailClient = Literal["auto", "apple_mail", "gmail_web", "outlook_web", "none"]
LinkKind = Literal["apple_mail", "gmail_web", "outlook_web", "none"]
# IMAP servers of Gmail and Google Workspace; "auto" opens their mails in Gmail on the web.
GMAIL_HOSTS = frozenset({"imap.gmail.com", "imap.googlemail.com"})
MAX_MESSAGE_ID = 900
# RFC 5322 msg-id: "<" id-left "@" id-right ">"; printable ASCII without spaces or brackets.
_MESSAGE_ID = re.compile(r"<([!-;=?-~]{1,900})>")
_BARE = re.compile(r"[!-;=?-~]{1,900}")


def clean_message_id(raw: str | None) -> str | None:
    """The first Message-ID of a header value without angle brackets, or ``None``.

    Accepts ``<id@host>`` (also with surrounding spaces or comments) and a bare
    ``id@host``; anything without exactly one ``@`` or with spaces is no Message-ID.
    """
    if not raw:
        return None
    text = raw.strip()
    match = _MESSAGE_ID.search(text)
    value = match.group(1) if match else (text if _BARE.fullmatch(text) else None)
    if value is None or value.count("@") != 1 or value.startswith("@") or value.endswith("@"):
        return None
    return value


def message_uri(message_id: str) -> str:
    """``message://%3Cid@host%3E``: opens the mail in Apple Mail (macOS, iOS)."""
    return f"message://%3C{quote(message_id, safe='@')}%3E"


def gmail_url(message_id: str) -> str:
    """Gmail on the web, searching exactly this Message-ID (``rfc822msgid:``)."""
    return f"https://mail.google.com/mail/u/0/#search/rfc822msgid%3A{quote(message_id, safe='')}"


def outlook_url(message_id: str) -> str:
    """Outlook on the web, searching the Message-ID.

    Outlook offers no documented link to a message by its Message-ID; this opens the
    search, which is why ``auto`` never chooses it.
    """
    return f"https://outlook.office.com/mail/search?q={quote(message_id, safe='')}"


def resolve_client(configured: MailClient, imap_host: str | None) -> LinkKind:
    """``auto``: Gmail on the web for Gmail's IMAP servers, otherwise Apple Mail."""
    if configured != "auto":
        return configured
    host = (imap_host or "").strip().casefold().rstrip(".")
    return "gmail_web" if host in GMAIL_HOSTS else "apple_mail"


def mail_link(raw_message_id: str | None, kind: LinkKind) -> str | None:
    """The link to the original mail, or ``None`` without a usable Message-ID or with ``none``."""
    message_id = clean_message_id(raw_message_id)
    if message_id is None or kind == "none":
        return None
    builders = {"apple_mail": message_uri, "gmail_web": gmail_url, "outlook_web": outlook_url}
    return builders[kind](message_id)


__all__ = ["GMAIL_HOSTS", "MAX_MESSAGE_ID", "LinkKind", "MailClient", "clean_message_id", "gmail_url",
           "mail_link", "message_uri", "outlook_url", "resolve_client"]
