"""Stable slot keys of the two write roles.

The keys predate the choice of providers: ``google_calendar`` holds whichever
calendar is configured (Google, CalDAV, Outlook) and ``todoist`` whichever task
list (Todoist, Microsoft To Do, CalDAV, Apple Erinnerungen). They are persisted
in ``write_attempts`` and therefore keep their historical spelling.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from .contracts import TargetWriter

if TYPE_CHECKING:
    from ..models import Proposal

CALENDAR_SLOT = "google_calendar"
TASK_SLOT = "todoist"


def profile_slot(role: str, profile: int) -> str:
    return role if profile == 1 else f"{role}:{profile}"


def writer_for[W](writers: Mapping[str, W], proposal: Proposal) -> W | None:
    role = TASK_SLOT if proposal.kind == "task" else CALENDAR_SLOT
    return writers.get(profile_slot(role, proposal.target_profile))


def provider_key(writer: TargetWriter) -> str:
    return {"google_calendar": "google", "outlook_calendar": "outlook",
            "caldav_calendar": "caldav", "caldav_tasks": "caldav"}.get(writer.service, writer.service)


def slot(writer: TargetWriter) -> str:
    """The slot a writer fills, derived from its role."""
    return CALENDAR_SLOT if writer.role == "calendar" else TASK_SLOT
