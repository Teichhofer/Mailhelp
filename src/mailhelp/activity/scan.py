"""Read-only mailbox access for activity reports: listing and preparing mail.

Only ``SELECT (readonly)``, ``UID SEARCH`` and ``BODY.PEEK`` are used, so no
flag of the user's mailbox changes.  Listing reads metadata only; contents are
read one mail at a time while the report runs.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from email import policy
from email.parser import BytesHeaderParser
from typing import Any
from zoneinfo import ZoneInfo

from ..domain.prepared import PreparedMail
from ..domain.relevance import IrrelevantSenders
from ..imap import FetchedMail
from ..mime import MimeLimitExceeded, prepare
from ..sender_filter import is_irrelevant_sender, sender_addresses
from .models import EXCLUDED_ROLES, ActivityReport, FolderProgress, ReportMail

SHORTENED = "\n… gekürzt"


def default_folders(listed: list[Any], configured: list[str]) -> list[str]:
    """The configured folders without trash, junk and drafts."""
    roles = {item.name: item.role for item in listed}
    return [folder for folder in configured if roles.get(folder) not in EXCLUDED_ROLES]


def sent_folders(listed: list[Any]) -> list[str]:
    return [item.name for item in listed if item.role == "sent"]


def period(report: ActivityReport, zone: str) -> tuple[datetime, datetime]:
    """Start (inclusive) and end (exclusive) of the period in the configured zone."""
    local = ZoneInfo(zone)
    definition = report.definition
    return (datetime.combine(definition.since, time(), local),
            datetime.combine(definition.until + timedelta(days=1), time(), local))


def list_folder(reader: Any, folder: str, sent: bool, start: datetime, end: datetime) -> FolderProgress:
    """UIDs of the folder received within the period, from metadata only."""
    candidates = reader.discover_since(folder, 0, None, (), None, historical_start=start)
    uids = sorted(item.uid for item in candidates if item.received_at < end)
    return FolderProgress(folder=folder, sent=sent, uidvalidity=reader.last_uidvalidity, uids=uids)


def _header(headers: Any, name: str) -> str:
    """A bounded, single-line header value; undecodable headers read as empty."""
    try:
        value = str(headers.get(name, ""))
    except (ValueError, LookupError):
        return ""
    return " ".join(value.split())[:500]


def _recipients(headers: Any) -> str:
    return ", ".join(str(headers.get(name, "")) for name in ("To", "Cc") if headers.get(name))


def _all_blocked(header: str, blocked: IrrelevantSenders) -> bool:
    """A sent mail is skipped only if every recipient is an ignored sender."""
    addresses = sender_addresses(header)
    return bool(addresses) and all(is_irrelevant_sender(address, blocked) for address in addresses)


def _automated(headers: Any) -> bool:
    auto = str(headers.get("Auto-Submitted", "no")).strip().casefold()
    return auto not in {"", "no"} or headers.get("List-Unsubscribe") is not None


def full_text(prepared: PreparedMail, limit: int) -> str:
    """Mail text and every recognized attachment text, cut at *limit* characters."""
    parts = [prepared.text or ""]
    for attachment in prepared.extracted_attachments:
        if attachment.usable_text:
            parts.append(f"--- Anhang: {attachment.filename} ---\n{attachment.usable_text}")
    text = "\n\n".join(part for part in parts if part)
    if len(text) <= limit:
        return text
    return text[:limit - len(SHORTENED)] + SHORTENED


def normalized_message_id(value: str) -> str:
    compact = re.sub(r"\s+", "", value).casefold()
    return compact if re.fullmatch(r"<[^<>@\s]+@[^<>@\s]+>", compact) else ""


def read_mail(report: ActivityReport, progress: FolderProgress, fetched: FetchedMail, limits: Any,
              zone: str, text_limit: int) -> tuple[ReportMail, PreparedMail | None]:
    """Prepare one fetched mail; skipped mails carry their reason and no content."""
    key = f"{progress.folder}:{progress.uidvalidity}:{fetched.uid}"
    headers = BytesHeaderParser(policy=policy.default).parsebytes(fetched.raw)
    # Shown for skipped mails too, so the user sees which mail was left out.
    base: dict[str, Any] = dict(key=key, folder=progress.folder, uid=fetched.uid, received_at=fetched.received_at,
                sender=_header(headers, "To" if progress.sent else "From"), subject=_header(headers, "Subject"))
    try:
        prepared = PreparedMail.model_validate(prepare(fetched.raw, limits, fetched.received_at, zone))
    except MimeLimitExceeded:
        return ReportMail(**base, skipped="size"), None
    except (ValueError, LookupError):
        return ReportMail(**base, skipped="unreadable"), None
    sender = prepared.headers.sender
    shown = f"An: {_recipients(headers)}" if progress.sent else sender
    base.update(sender=shown[:500], subject=prepared.headers.subject[:500])
    mail = ReportMail(**base, message_id=normalized_message_id(prepared.headers.message_id))
    blocked = IrrelevantSenders(addresses=report.blocked_addresses, domains=report.blocked_domains)
    if (_all_blocked(_recipients(headers), blocked) if progress.sent
            else is_irrelevant_sender(sender, blocked)):
        mail.skipped = "sender"
        return mail, None
    if report.definition.skip_automated and _automated(headers):
        mail.skipped = "automated"
        return mail, None
    mail.text = full_text(prepared, text_limit)
    mail.attachments = [item.filename for item in prepared.extracted_attachments][:50]
    return mail, prepared


def received_day(mail: ReportMail, zone: str) -> date:
    return mail.received_at.astimezone(ZoneInfo(zone)).date()


__all__ = ["SHORTENED", "default_folders", "full_text", "list_folder", "normalized_message_id", "period",
           "read_mail", "received_day", "sent_folders"]
