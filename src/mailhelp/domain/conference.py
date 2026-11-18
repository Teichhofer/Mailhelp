"""7.9: deterministic comparison of conference access links (Planung 7.9, section 3).

A link counts as conference access only for a known conference provider, so a registration
page, the organiser's website or a general link never becomes a "video link" supplement.
Normalisation is limited to what is technically safe: scheme and host are compared
case-insensitively and trailing punctuation from running text is dropped. Path, meeting
ID, passcode and query parameters stay exactly as written. Links are never fetched.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

# Hosts (and their subdomains) of conference services; anything else is not conference access.
CONFERENCE_HOSTS = (
    "zoom.us", "zoom.com", "zoomgov.com", "teams.microsoft.com", "teams.live.com", "meet.google.com",
    "webex.com", "gotomeeting.com", "meet.goto.com", "whereby.com", "meet.jit.si", "bluejeans.com",
    "chime.aws", "meetings.ringcentral.com", "skype.com", "join.skype.com", "meet.lync.com",
    "edudip.com", "clickmeeting.com", "alfaview.com", "senfcall.de", "visavid.de",
)
_LINK = re.compile(r"https?://[^\s<>\"'\]\[)(]+", re.IGNORECASE)
_TRAILING = ".,;:!?»«“”„"


def normalized(url: str) -> str:
    """*url* with lower-case scheme and host and without trailing sentence punctuation."""
    text = url.strip().rstrip(_TRAILING)
    parts = urlsplit(text)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, parts.fragment))


def is_conference(url: str) -> bool:
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    return parts.scheme.lower() == "https" and any(
        host == known or host.endswith("." + known) for known in CONFERENCE_HOSTS)


def links_in(texts: Iterable[str | None]) -> list[str]:
    """Every http(s) link in the texts, normalised, in order and without repetition."""
    found = (normalized(match) for text in texts if text for match in _LINK.findall(text))
    return list(dict.fromkeys(found))


@dataclass(frozen=True)
class LinkAssessment:
    """How a proposed conference link relates to the links an entry already has."""

    state: Literal["missing", "same", "conflict", "not_conference"]
    previous: str | None = None


def assess(proposed: str, texts: Iterable[str | None], native: Iterable[str] = ()) -> LinkAssessment:
    """Compare *proposed* with the description/location *texts* and native conference fields."""
    if not is_conference(proposed):
        return LinkAssessment("not_conference")
    wanted = normalized(proposed)
    existing = [link for link in [*links_in(texts), *(normalized(item) for item in native)] if is_conference(link)]
    if wanted in existing:
        return LinkAssessment("same")
    if existing:
        return LinkAssessment("conflict", previous=existing[0])
    return LinkAssessment("missing")


def with_link(description: str, link: str, previous: str | None = None) -> str:
    """The description with *link* exactly once; a confirmed replacement swaps *previous*.

    The user's own text stays as it is. Only the confirmed old link is replaced; without one the
    link is appended in the marked Mailhelp section, unless it is already present.
    """
    if previous is not None:
        replaced = _replace_link(description, previous, link)
        if replaced != description:
            return replaced
    if normalized(link) in links_in([description]):
        return description
    addition = f"[Mailhelp-Videolink]\n{link}"
    return f"{description}\n\n{addition}" if description else addition


def _replace_link(description: str, previous: str, link: str) -> str:
    wanted = normalized(previous)

    def swap(match: re.Match[str]) -> str:
        raw = match.group(0)
        stripped = raw.rstrip(_TRAILING)
        return link + raw[len(stripped):] if normalized(stripped) == wanted else raw

    return _LINK.sub(swap, description)


__all__ = ["CONFERENCE_HOSTS", "LinkAssessment", "assess", "is_conference", "links_in", "normalized", "with_link"]
