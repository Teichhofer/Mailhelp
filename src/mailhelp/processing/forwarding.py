"""Recognize forwarded mail and separate the note from the original (Planung 4.5, 16.2).

Mail text is untrusted. The parser only splits text deterministically. It never
follows instructions, and its results never authorize an external write.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..domain.mail import ForwardedHeaders

SUBJECT = re.compile(r"^\s*(?:\[[^\]]{0,40}\]\s*)?(?:fwd?|wg|weitergeleitet)\s*:", re.IGNORECASE)
MARKER = re.compile(
    r"^[ \t>]*(?:"
    r"-{2,}[ \t]*(?:weitergeleitete nachricht|ursprüngliche nachricht|original message|forwarded message)[ \t]*-{2,}"
    r"|anfang der weitergeleiteten nachricht:|begin forwarded message:"
    r")[ \t]*$",
    re.IGNORECASE | re.MULTILINE)
FIELDS = {
    "von": "sender", "from": "sender",
    "datum": "date", "date": "date", "gesendet": "date", "sent": "date",
    "betreff": "subject", "subject": "subject",
    "an": "recipients", "to": "recipients",
}
# Outlook writes "**Von:**" when a forward passes through Markdown or HTML-to-text.
HEADER = re.compile(r"^[ \t>]*\*{0,2}([A-Za-zÄÖÜäöü-]+)\*{0,2}[ \t]*:\*{0,2}[ \t]*(.*)$")
OTHER_HEADERS = {"cc", "kopie", "bcc", "reply-to"}
LIMIT = 500


@dataclass(frozen=True)
class Forward:
    note: str
    headers: ForwardedHeaders | None
    original: str


def _clean(value: str) -> str:
    return " ".join("".join(char for char in value if char.isprintable()).split())[:LIMIT]


def _headers(lines: list[str]) -> tuple[ForwardedHeaders | None, int]:
    """Header lines right after the marker; returns them and the index of the body."""
    values: dict[str, str] = {}
    index = _content(lines, 0)
    while index < len(lines):
        match = HEADER.match(lines[index])
        if match is None:
            break
        key = match.group(1).casefold()
        if key in FIELDS:
            values.setdefault(FIELDS[key], _clean(match.group(2)))
        elif key not in OTHER_HEADERS:
            break
        index += 1
    return (ForwardedHeaders(**values) if values else None), _content(lines, index)


def _content(lines: list[str], index: int) -> int:
    """Skip blank lines, also quoted ones (">")."""
    while index < len(lines) and not lines[index].strip(" \t>"):
        index += 1
    return index


def split_forward(subject: str, text: str | None) -> Forward | None:
    """The outermost forwarded message, or ``None`` if the mail is no forwarding."""
    body = text or ""
    marker = MARKER.search(body)
    if marker is None:
        return Forward(note=body.strip(), headers=None, original="") if SUBJECT.match(subject) else None
    rest = body[marker.end():].lstrip("\r\n").splitlines()
    headers, start = _headers(rest)
    return Forward(note=body[:marker.start()].strip(), headers=headers, original="\n".join(rest[start:]).strip())


__all__ = ["Forward", "split_forward"]
