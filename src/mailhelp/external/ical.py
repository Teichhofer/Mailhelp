"""RFC 5545 file serialization and Telegram document delivery."""
from __future__ import annotations

import hashlib
import re
from datetime import UTC, date, datetime
from typing import Any

from ..logging import EventLogger, NullLogger
from ..models import Proposal, ProposalKind
from .contracts import proposal_is_writable


class CalendarFileWriter:
    """Create a standards-based iCalendar attachment and deliver it via Telegram."""

    def __init__(self, telegram: Any, chat_id: int, logger: EventLogger | None = None):
        self.telegram, self.chat_id = telegram, chat_id
        self.logger = logger or NullLogger()

    def check_access(self) -> None:
        """Calendar delivery uses the Telegram access checked separately."""

    def reconcile(self, key: str) -> dict[str, Any] | None:
        # Telegram offers no API for reliably reconciling a possibly delivered
        # document. Returning None makes execute_confirmed retain UNCERTAIN and
        # therefore prevents an automatic duplicate after a crash or timeout.
        return None

    def create(self, proposal: Proposal, key: str) -> dict[str, Any]:
        if proposal.kind != ProposalKind.EVENT or not proposal_is_writable(proposal):
            raise ValueError("Kalenderdateien können nur für anlegbare Termine erzeugt werden")
        content = calendar_file(proposal, key)
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
        filename = f"termin-{digest}.ics"
        self.logger.event("INFO", "calendar_file", "create_started", call_id=key,
                          mail_id=proposal.source_mail_id, proposal_id=proposal.id)
        self.telegram.send_document(
            self.chat_id, filename, content,
            f"Termin „{proposal.title}“ – antippen, um ihn in den Kalender zu übernehmen.",
        )
        self.logger.event("INFO", "calendar_file", "create_completed", call_id=key,
                          mail_id=proposal.source_mail_id, proposal_id=proposal.id,
                          filename=filename)
        return {"id": f"calendar-file:{digest}"}


def calendar_file(proposal: Proposal, key: str) -> bytes:
    """Serialize a validated event as an RFC 5545 compatible UTF-8 file."""
    item = Proposal.model_validate(proposal.model_dump())
    if item.kind != ProposalKind.EVENT or item.start is None or item.end is None:
        raise ValueError("Kalenderdatei benötigt einen vollständigen Termin")
    uid = hashlib.sha256(key.encode("utf-8")).hexdigest() + "@mailhelp.local"
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Mailhelp//Calendar File//DE",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH", "BEGIN:VEVENT", f"UID:{uid}"]
    if item.all_day:
        assert isinstance(item.start, date) and not isinstance(item.start, datetime)
        assert isinstance(item.end, date) and not isinstance(item.end, datetime)
        lines.extend((f"DTSTART;VALUE=DATE:{item.start:%Y%m%d}",
                      f"DTEND;VALUE=DATE:{item.end:%Y%m%d}"))
    else:
        assert isinstance(item.start, datetime) and isinstance(item.end, datetime)
        lines.extend((f"DTSTART:{_ical_datetime(item.start)}", f"DTEND:{_ical_datetime(item.end)}"))
    lines.append(f"SUMMARY:{_ical_text(item.title)}")
    description = item.description
    if item.video_link is not None:
        description = f"{description}\n\nVideolink: {item.video_link}" if description else f"Videolink: {item.video_link}"
    if description:
        lines.append(f"DESCRIPTION:{_ical_text(description)}")
    if item.location:
        lines.append(f"LOCATION:{_ical_text(item.location)}")
    lines.extend(("END:VEVENT", "END:VCALENDAR"))
    return ("\r\n".join(_fold_ical_line(line) for line in lines) + "\r\n").encode("utf-8")


def _ical_datetime(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _ical_text(value: str) -> str:
    normalized = value.replace("\\", "\\\\")
    normalized = re.sub(r"\r\n?|\n", lambda _match: "\\n", normalized)
    return normalized.replace(",", "\\,").replace(";", "\\;")


def _fold_ical_line(value: str, limit: int = 75) -> str:
    """Fold without splitting a UTF-8 code point (continuations start with SP)."""
    chunks: list[str] = []
    current = ""
    current_bytes = 0
    for character in value:
        size = len(character.encode("utf-8"))
        available = limit if not chunks else limit - 1
        if current and current_bytes + size > available:
            chunks.append(current)
            current, current_bytes = character, size
        else:
            current += character
            current_bytes += size
    chunks.append(current)
    return "\r\n ".join(chunks)

