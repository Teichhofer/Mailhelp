"""Links that open the original mail in the user's mail program (Planung 4.7).

The Message-ID comes from an untrusted header. It is reduced to one ``id-left@id-right``
value and percent-encoded completely before it becomes part of a link, so no header
content can add a scheme, a query or markup. Without a usable Message-ID there is no link.
"""
from __future__ import annotations

import re
from urllib.parse import quote

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


__all__ = ["MAX_MESSAGE_ID", "clean_message_id", "message_uri"]
