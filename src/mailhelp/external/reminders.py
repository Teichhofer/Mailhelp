"""8.4: Provider-neutral calendar reminder calculation, payloads, facts and previews."""

from __future__ import annotations

import re
from typing import Any

from mailhelp.i18n import tr

_ISO_DURATION = re.compile(r"^-?PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$")


def effective_reminder(enabled: bool, minutes: int, *, all_day: bool) -> int | None:
    """Return the effective reminder offset in minutes, or ``None`` when no alarm applies."""
    if all_day or not enabled:
        return None
    return minutes


def google_reminders_payload(enabled: bool, minutes: int, *, all_day: bool) -> dict[str, Any] | None:
    """Return the Google-format ``reminders`` dict for timed events, or ``None`` for all-day."""
    if all_day:
        return None
    if not enabled:
        return {"useDefault": False, "overrides": []}
    return {"useDefault": False, "overrides": [{"method": "popup", "minutes": minutes}]}


def reminder_fact_from_google(reminders: dict[str, Any] | None) -> str | None:
    """Normalize a Google ``reminders`` object into a comparable verification fact."""
    if not isinstance(reminders, dict):
        return None
    if reminders.get("useDefault") is True:
        return "default"
    if reminders.get("useDefault") is not False:
        return None
    overrides = reminders.get("overrides")
    if not overrides:
        return "none"
    if isinstance(overrides, list):
        for item in overrides:
            if isinstance(item, dict) and item.get("method") == "popup" and isinstance(item.get("minutes"), int):
                return str(item["minutes"])
    return "other"


def reminder_fact_from_microsoft(is_reminder_on: bool | None, minutes: int | None) -> str | None:
    """Normalize Microsoft Graph ``isReminderOn`` / ``reminderMinutesBeforeStart`` into a fact."""
    if is_reminder_on is None:
        return None
    if not is_reminder_on:
        return "none"
    if minutes is None:
        return "other"
    return str(minutes)


def trigger_for_minutes(minutes: int) -> str:
    """Return the RFC 5545 VALARM TRIGGER value for ``minutes`` before start."""
    return "PT0S" if minutes == 0 else f"-PT{minutes}M"


def minutes_from_trigger(trigger: str) -> int | None:
    """Parse an RFC 5545 relative TRIGGER duration into whole minutes."""
    match = _ISO_DURATION.fullmatch(trigger.strip().upper())
    if match is None:
        return None
    hours = int(match.group(1) or 0)
    mins = int(match.group(2) or 0)
    secs = int(match.group(3) or 0)
    if secs != 0:
        return None
    return hours * 60 + mins


def reminder_preview_text(
    enabled: bool,
    minutes: int,
    *,
    all_day: bool,
    operation: str = "create",
    duplicate_skipped: bool = False,
) -> str | None:
    """Return the localized preview line for Web and Telegram, or ``None`` if not applicable."""
    if all_day or operation == "cancel" or duplicate_skipped:
        return None
    if not enabled:
        return tr("Erinnerung: keine")
    if minutes == 0:
        return tr("Erinnerung: zum Beginn")
    if minutes == 1:
        return tr("Erinnerung: 1 Minute vor Beginn")
    return tr("Erinnerung: {minutes} Minuten vor Beginn", minutes=minutes)
