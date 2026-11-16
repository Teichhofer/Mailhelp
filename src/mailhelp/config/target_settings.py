"""Write targets, target profiles and event defaults. (7.0: split from models.py)"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import (
    Field,
    model_validator,
)

from .base import ConfigModel


class EventDefaultsSettings(ConfigModel):
    video_duration_minutes: int = Field(default=60, ge=1, le=1440)
    in_person_duration_minutes: int = Field(default=180, ge=1, le=1440)

class MailboxEventDefaults(ConfigModel):
    video_duration_minutes: int | None = Field(default=None, ge=1, le=1440)
    in_person_duration_minutes: int | None = Field(default=None, ge=1, le=1440)

class ProposalReconciliationSettings(ConfigModel):
    max_semantic_candidates: int = Field(default=8, ge=1, le=50)

CALENDAR_PROVIDERS = ("google", "caldav", "outlook")

TASK_PROVIDERS = ("todoist", "microsoft_todo", "caldav", "apple_reminders", "google_tasks")

# iCloud serves collections on caldav.icloud.com and on numbered partition hosts (p52-caldav…).
ICLOUD_CALDAV = re.compile(r"https://(p\d{1,3}-)?caldav\.icloud\.com/")

def _dav_url(value: str) -> bool:
    """CalDAV collections need TLS; plain HTTP only on the local machine."""
    match = re.fullmatch(r"(https?)://([^/@:?#\s]+)(:\d{1,5})?(/[^\s?#]*)?", value)
    if match is None:
        return False
    return match.group(1) == "https" or match.group(2) in {"localhost", "127.0.0.1"}

class TargetSettings(ConfigModel):
    """One calendar and one task target; each provider needs its own target field."""

    calendar_provider: Literal["google", "caldav", "outlook"] = "google"
    task_provider: Literal["todoist", "microsoft_todo", "caldav", "apple_reminders", "google_tasks"] = "todoist"
    todoist_project: str = Field(default="", max_length=500)
    google_calendar: str = Field(default="", max_length=500)
    caldav_calendar_url: str = Field(default="", max_length=2000)
    caldav_task_url: str = Field(default="", max_length=2000)
    outlook_calendar: str = Field(default="default", min_length=1, max_length=500, pattern=r"^[A-Za-z0-9=_+/-]+$")
    microsoft_todo_list: str = Field(default="default", min_length=1, max_length=500, pattern=r"^[A-Za-z0-9=_+/-]+$")
    # 7.2: a Google Tasks list id or ``@default`` for the account's first list.
    google_tasks_list: str = Field(default="@default", min_length=1, max_length=500, pattern=r"^[A-Za-z0-9@_-]+$")
    microsoft_tenant: str = Field(default="common", pattern=r"^[A-Za-z0-9.-]{1,100}$")
    removal_window_minutes: int = Field(default=10, ge=1, le=1440)

    @model_validator(mode="after")
    def provider_targets(self) -> TargetSettings:
        if self.calendar_provider == "google" and not self.google_calendar:
            raise ValueError("google_calendar wird für calendar_provider google benötigt")
        if self.task_provider == "todoist" and not self.todoist_project:
            raise ValueError("todoist_project wird für task_provider todoist benötigt")
        if self.calendar_provider == "caldav" and not _dav_url(self.caldav_calendar_url):
            raise ValueError("caldav_calendar_url muss eine https-Adresse sein")
        if self.task_provider in {"caldav", "apple_reminders"} and not _dav_url(self.caldav_task_url):
            raise ValueError("caldav_task_url muss eine https-Adresse sein")
        if self.task_provider == "apple_reminders" and not ICLOUD_CALDAV.match(self.caldav_task_url):
            raise ValueError("Apple Erinnerungen benötigen eine Listenadresse unter https://caldav.icloud.com")
        return self

    @property
    def calendar_target(self) -> str:
        """The calendar each event proposal is confirmed against."""
        return {"google": self.google_calendar, "caldav": self.caldav_calendar_url,
                "outlook": self.outlook_calendar}[self.calendar_provider]

    @property
    def task_target(self) -> str:
        """The project or list each task proposal is confirmed against."""
        return {"todoist": self.todoist_project, "microsoft_todo": self.microsoft_todo_list,
                "google_tasks": self.google_tasks_list}.get(self.task_provider, self.caldav_task_url)

    @property
    def uses_microsoft(self) -> bool:
        return self.calendar_provider == "outlook" or self.task_provider == "microsoft_todo"

    @property
    def uses_google(self) -> bool:
        """7.2: one Google sign-in serves the calendar and Google Tasks of a profile."""
        return self.calendar_provider == "google" or self.task_provider == "google_tasks"

    @property
    def uses_caldav(self) -> bool:
        return self.calendar_provider == "caldav" or self.task_provider in {"caldav", "apple_reminders"}

class TargetProfileSettings(TargetSettings):
    id: int = Field(ge=2, le=99)
    label: str = Field(min_length=1, max_length=40, pattern=r"^[^\x00-\x1f\x7f]+$")

class OriginalAttachmentSettings(ConfigModel):
    """Original documents kept for download in the web interface (2.3)."""

    store_originals: bool = True
    max_original_bytes: int = Field(default=26_214_400, ge=1024, le=104_857_600)
    max_total_bytes: int = Field(default=52_428_800, ge=1024, le=524_288_000)
