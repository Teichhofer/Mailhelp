"""Quick filters of the open decisions, the mail archive and the history."""
from __future__ import annotations

from collections.abc import Iterable

from ..i18n import msg

FILTERS = {"": msg("Alle"), "events": msg("Termine"), "tasks": msg("Aufgaben"), "clarification": msg("Klärung nötig"),
           "attachments": msg("Mit Anhängen"), "duplicates": msg("Duplikate")}


def matches(selected: str, kinds: Iterable[str], statuses: Iterable[str], attachments: object,
            duplicate: bool = False) -> bool:
    """Whether an item with these proposal kinds and statuses passes the quick filter."""
    kinds, statuses = list(kinds), list(statuses)
    return {"": True, "events": "event" in kinds, "tasks": "task" in kinds,
            "clarification": "needs_clarification" in statuses or "unclear" in statuses,
            "attachments": bool(attachments),
            "duplicates": duplicate or "already_exists" in statuses}[selected]
