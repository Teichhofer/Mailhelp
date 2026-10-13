"""Stable slot keys of the two write roles.

The keys predate the choice of providers: ``google_calendar`` holds whichever
calendar is configured (Google, CalDAV, Outlook) and ``todoist`` whichever task
list (Todoist, Microsoft To Do, CalDAV, Apple Erinnerungen). They are persisted
in ``write_attempts`` and therefore keep their historical spelling.
"""
from __future__ import annotations

from .contracts import TargetWriter

CALENDAR_SLOT = "google_calendar"
TASK_SLOT = "todoist"


def slot(writer: TargetWriter) -> str:
    """The slot a writer fills, derived from its role."""
    return CALENDAR_SLOT if writer.role == "calendar" else TASK_SLOT
