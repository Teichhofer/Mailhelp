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

TASK_PROVIDERS = ("todoist", "microsoft_todo", "caldav", "apple_reminders", "google_tasks", "notion")

# iCloud serves collections on caldav.icloud.com and on numbered partition hosts (p52-caldav…).
ICLOUD_CALDAV = re.compile(r"https://(p\d{1,3}-)?caldav\.icloud\.com/")

def _dav_url(value: str) -> bool:
    """CalDAV collections need TLS; plain HTTP only on the local machine."""
    match = re.fullmatch(r"(https?)://([^/@:?#\s]+)(:\d{1,5})?(/[^\s?#]*)?", value)
    if match is None:
        return False
    return match.group(1) == "https" or match.group(2) in {"localhost", "127.0.0.1"}

class NotionProperties(ConfigModel):
    """7.2: the property ids of a Notion data source; ids survive a renamed column."""

    title: str = Field(default="", max_length=100, pattern=r"^\S*$")
    description: str = Field(default="", max_length=100, pattern=r"^\S*$")
    due: str = Field(default="", max_length=100, pattern=r"^\S*$")
    source: str = Field(default="", max_length=100, pattern=r"^\S*$")
    operation_key: str = Field(default="", max_length=100, pattern=r"^\S*$")
    # Optional: without it Mailhelp cannot tell done pages from open ones.
    status: str = Field(default="", max_length=100, pattern=r"^\S*$")


NOTION_REQUIRED = ("title", "description", "due", "source", "operation_key")
NOTION_ID = r"^([0-9a-fA-F]{32}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})?$"


class TargetSettings(ConfigModel):
    """One calendar and one task target; each provider needs its own target field."""

    calendar_provider: Literal["google", "caldav", "outlook"] = "google"
    task_provider: Literal["todoist", "microsoft_todo", "caldav", "apple_reminders", "google_tasks",
                           "notion"] = "todoist"
    todoist_project: str = Field(default="", max_length=500)
    google_calendar: str = Field(default="", max_length=500)
    # 8.0: reference of a Google access held by the central Inboxstride service (hosted mode);
    # empty for the direct mode with the profile's own GOOGLE_OAUTH_* secrets.
    google_connection: str = Field(default="", pattern=r"^([a-f0-9]{32})?$")
    caldav_calendar_url: str = Field(default="", max_length=2000)
    caldav_task_url: str = Field(default="", max_length=2000)
    outlook_calendar: str = Field(default="default", min_length=1, max_length=500, pattern=r"^[A-Za-z0-9=_+/-]+$")
    microsoft_todo_list: str = Field(default="default", min_length=1, max_length=500, pattern=r"^[A-Za-z0-9=_+/-]+$")
    # 7.2: a Google Tasks list id or ``@default`` for the account's first list.
    google_tasks_list: str = Field(default="@default", min_length=1, max_length=500, pattern=r"^[A-Za-z0-9@_-]+$")
    # 7.2: a Notion data source (not the database) with the ids of its mapped properties.
    notion_data_source_id: str = Field(default="", max_length=36, pattern=NOTION_ID)
    notion_properties: NotionProperties = Field(default_factory=NotionProperties)
    # Status option ids: the one new pages get and those that count as done.
    notion_open_status: str = Field(default="", max_length=100, pattern=r"^\S*$")
    notion_done_statuses: list[str] = Field(default_factory=list, max_length=50)
    microsoft_tenant: str = Field(default="common", pattern=r"^[A-Za-z0-9.-]{1,100}$")
    removal_window_minutes: int = Field(default=10, ge=1, le=1440)

    @model_validator(mode="after")
    def provider_targets(self) -> TargetSettings:
        if self.calendar_provider == "google" and not self.google_calendar:
            raise ValueError("google_calendar wird für calendar_provider google benötigt")
        if self.google_connection and (self.calendar_provider != "google" or self.task_provider == "google_tasks"):
            # 8.0: the hosted access grants calendar scopes only; Google Tasks stays in the direct mode.
            raise ValueError("google_connection gilt nur für den Google Kalender, nicht für Google Tasks")
        if self.task_provider == "todoist" and not self.todoist_project:
            raise ValueError("todoist_project wird für task_provider todoist benötigt")
        if self.calendar_provider == "caldav" and not _dav_url(self.caldav_calendar_url):
            raise ValueError("caldav_calendar_url muss eine https-Adresse sein")
        if self.task_provider in {"caldav", "apple_reminders"} and not _dav_url(self.caldav_task_url):
            raise ValueError("caldav_task_url muss eine https-Adresse sein")
        if self.task_provider == "notion":
            missing = [name for name in NOTION_REQUIRED if not getattr(self.notion_properties, name)]
            if not self.notion_data_source_id or missing:
                raise ValueError("Notion benötigt notion_data_source_id und die Eigenschaften "
                                 + ", ".join(missing or NOTION_REQUIRED))
            if self.notion_properties.status and not self.notion_open_status:
                raise ValueError("Mit einem Notion-Statusfeld wird notion_open_status benötigt")
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
                "google_tasks": self.google_tasks_list, "notion": self.notion_data_source_id}.get(
            self.task_provider, self.caldav_task_url)

    @property
    def calendar_binding(self) -> str:
        """The provider an event proposal is bound to; 8.0: a hosted Google access names its connection.

        A changed connection (another Google account with the same calendar id ``primary``) therefore
        never lets an earlier confirmation write into the new account.
        """
        if self.google_connection and self.calendar_provider == "google":
            return "google-" + self.google_connection[:16]
        return self.calendar_provider

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

class HostedAuthSettings(ConfigModel):
    """8.0: the central Inboxstride OAuth service; set by the operator of a hosted instance.

    Only paths are configured; certificate key and CA stay in files the operator provides.
    """

    enabled: bool = False
    service_url: str = Field(default="", max_length=500, pattern=r"^(https://[A-Za-z0-9.-]+(:\d{1,5})?)?$")
    instance_id: str = Field(default="", pattern=r"^([a-z0-9][a-z0-9-]{2,62})?$")
    certificate: str = Field(default="", max_length=500)
    key: str = Field(default="", max_length=500)
    ca: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def complete(self) -> HostedAuthSettings:
        if self.enabled and not all((self.service_url, self.instance_id, self.certificate, self.key, self.ca)):
            raise ValueError("hosted_auth benötigt service_url, instance_id, certificate, key und ca")
        return self


class TargetProfileSettings(TargetSettings):
    id: int = Field(ge=2, le=99)
    label: str = Field(min_length=1, max_length=40, pattern=r"^[^\x00-\x1f\x7f]+$")

class OriginalAttachmentSettings(ConfigModel):
    """Original documents kept for download in the web interface (2.3)."""

    store_originals: bool = True
    max_original_bytes: int = Field(default=26_214_400, ge=1024, le=104_857_600)
    max_total_bytes: int = Field(default=52_428_800, ge=1024, le=524_288_000)
