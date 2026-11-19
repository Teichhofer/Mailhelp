"""Construction of the configured calendar and task writers (Planung 2.3, 3.4)."""
from __future__ import annotations

from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from ..config import Secrets, Settings, TargetSettings
from ..llm.adapter import RetryPolicy
from ..logging import EventLogger
from .caldav import AppleReminders, CalDavCalendar, CalDavTasks
from .contracts import TargetWriter
from .google_tasks import GoogleTasks
from .hosted_oauth import HostedAuthClient, HostedTokenProvider
from .http_writer import HttpWriter
from .microsoft import MicrosoftTodo, MicrosoftTokenProvider, OutlookCalendar, TokenFile
from .notion import NotionTasks
from .notion_oauth import NotionTokenFile, NotionTokenProvider, token_path
from .oauth import GoogleOAuthTokenProvider
from .roles import CALENDAR_SLOT, TASK_SLOT

TOKEN_FILE = "microsoft-token.json"


@dataclass
class Writers:
    """Both writers plus the token providers they share; ``close`` releases everything."""

    calendar: TargetWriter
    tasks: TargetWriter
    resources: list[Any] = field(default_factory=list)

    @property
    def slots(self) -> dict[str, TargetWriter]:
        return {TASK_SLOT: self.tasks, CALENDAR_SLOT: self.calendar}

    def close(self) -> None:
        for item in (self.tasks, self.calendar, *self.resources):
            item.close()


CALENDAR_LABELS = {"google": "Google Kalender", "caldav": "CalDAV-Kalender", "outlook": "Outlook-Kalender"}
TASK_LABELS = {"todoist": "Todoist", "microsoft_todo": "Microsoft To Do", "caldav": "CalDAV-Aufgaben",
               "apple_reminders": "Apple Erinnerungen", "google_tasks": "Google Tasks", "notion": "Notion"}


def provider_services(targets: TargetSettings) -> list[str]:
    """Display names for the connection status: both targets and the sign-ins they need."""
    names = [TASK_LABELS[targets.task_provider], CALENDAR_LABELS[targets.calendar_provider]]
    names += ["Google-Anmeldung"] if targets.uses_google else []
    names += ["Microsoft-Anmeldung"] if targets.uses_microsoft else []
    return names


def microsoft_tokens(settings: Settings, secrets: Secrets, base_directory: Path, timeout: float,
                     transport: httpx.BaseTransport | None = None,
                     logger: EventLogger | None = None, profile_id: int = 1) -> MicrosoftTokenProvider:
    return MicrosoftTokenProvider(
        secrets.microsoft_client_id.get_secret_value(), secrets.microsoft_client_secret.get_secret_value(),
        secrets.microsoft_refresh_token.get_secret_value(), settings.targets.microsoft_tenant,
        TokenFile(base_directory / (TOKEN_FILE if profile_id == 1 else f"microsoft-token-{profile_id}.json")),
        timeout, transport, logger=logger)


def google_tokens(settings: Settings, secrets: Secrets, timeout: float, transport: httpx.BaseTransport | None,
                  logger: EventLogger | None) -> GoogleOAuthTokenProvider | HostedTokenProvider | None:
    """The Google sign-in of a profile: hosted through Inboxstride (8.0), direct (7.2) or none."""
    targets = settings.targets
    if targets.google_connection:
        # The access is held by the central Inboxstride service; the instance has no Google secret.
        return HostedTokenProvider(HostedAuthClient(settings.hosted_auth, transport, timeout),
                                   targets.google_connection, logger)
    if targets.uses_google:
        # One sign-in for the calendar and Google Tasks of this profile (7.2).
        return GoogleOAuthTokenProvider(
            secrets.google_oauth_client_id.get_secret_value(), secrets.google_oauth_client_secret.get_secret_value(),
            secrets.google_oauth_refresh_token.get_secret_value(), timeout, transport, logger=logger)
    return None


def build_writers(settings: Settings, secrets: Secrets, base_directory: Path, *,
                  policy: Callable[[str], RetryPolicy] | None = None, logger: EventLogger | None = None,
                  calendar_matcher: Callable[..., Any] | None = None, timeout_cap: float | None = None,
                  transport: httpx.BaseTransport | None = None, profile_id: int = 1) -> Writers:
    """Create each adapter once; close partial constructions on any failure."""
    with ExitStack() as stack:
        writers = _build_writers(settings, secrets, base_directory, policy=policy, logger=logger,
            calendar_matcher=calendar_matcher, timeout_cap=timeout_cap, transport=transport,
            profile_id=profile_id, stack=stack)
        stack.pop_all()
        return writers


def _build_writers(settings: Settings, secrets: Secrets, base_directory: Path, *,
                  policy: Callable[[str], RetryPolicy] | None = None, logger: EventLogger | None = None,
                  calendar_matcher: Callable[..., Any] | None = None, timeout_cap: float | None = None,
                  transport: httpx.BaseTransport | None = None, profile_id: int = 1, stack: ExitStack) -> Writers:
    """The writers of ``targets.calendar_provider`` and ``targets.task_provider``."""
    targets, resources = settings.targets, list[Any]()

    def timeout(name: str) -> float:
        value = getattr(settings.timeouts, name).timeout_seconds
        return value if timeout_cap is None else min(timeout_cap, value)

    def retry(name: str) -> RetryPolicy | None:
        return policy(name) if policy is not None else None

    caldav = (secrets.caldav_username.get_secret_value(), secrets.caldav_password.get_secret_value())
    microsoft: MicrosoftTokenProvider | None = None
    if targets.uses_microsoft:
        microsoft = microsoft_tokens(
            settings, secrets, base_directory, timeout("microsoft"), transport, logger, profile_id
        )
        resources.append(microsoft)
        stack.callback(microsoft.close)

    google = google_tokens(settings, secrets, timeout("google_calendar" if targets.calendar_provider == "google"
                                                      else "google_tasks"), transport, logger)
    if google is not None:
        resources.append(google)
        stack.callback(google.close)

    tasks: TargetWriter
    if targets.task_provider == "todoist":
        tasks = HttpWriter("todoist", secrets.todoist_token.get_secret_value(), targets.todoist_project,
                           timeout("todoist"), transport, policy=retry("todoist"), logger=logger)
    elif targets.task_provider == "microsoft_todo":
        assert microsoft is not None
        tasks = MicrosoftTodo(microsoft, targets.microsoft_todo_list, timeout("microsoft"), transport,
                              retry("microsoft"), logger)
    elif targets.task_provider == "google_tasks":
        assert google is not None
        tasks = GoogleTasks(google, targets.google_tasks_list, timeout("google_tasks"), transport,
                            retry("google_tasks"), logger, settings.timezone)
    elif targets.task_provider == "notion":
        token: str | NotionTokenProvider = secrets.notion_token.get_secret_value()
        if not token:
            # 7.2.5: a public connection signed in through OAuth; its grant file belongs to the profile.
            token = NotionTokenProvider(secrets.notion_client_id.get_secret_value(),
                                        secrets.notion_client_secret.get_secret_value(),
                                        NotionTokenFile(token_path(base_directory, profile_id)), timeout("notion"),
                                        transport, logger)
            resources.append(token)
            stack.callback(token.close)
        tasks = NotionTasks(token, targets.notion_data_source_id,
                            targets.notion_properties, targets.notion_open_status,
                            tuple(targets.notion_done_statuses), timeout("notion"), transport, retry("notion"), logger)
    else:
        kind = AppleReminders if targets.task_provider == "apple_reminders" else CalDavTasks
        tasks = kind(targets.caldav_task_url, *caldav, timeout("caldav"), transport, retry("caldav"), logger)

    stack.callback(tasks.close)
    calendar: TargetWriter
    if targets.calendar_provider == "google":
        assert google is not None
        calendar = HttpWriter("google_calendar", google, targets.google_calendar, timeout("google_calendar"), transport,
                              policy=retry("google_calendar"), logger=logger, calendar_timezone=settings.timezone,
                              calendar_matcher=calendar_matcher)
        # 8.0: proposals confirmed for another (or no) hosted connection never write through this one.
        calendar.binding = targets.calendar_binding if targets.google_connection else ""
    elif targets.calendar_provider == "outlook":
        assert microsoft is not None
        calendar = OutlookCalendar(microsoft, targets.outlook_calendar, timeout("microsoft"), transport,
                                   retry("microsoft"), logger, settings.timezone, calendar_matcher)
    else:
        calendar = CalDavCalendar(targets.caldav_calendar_url, *caldav, timeout("caldav"), transport,
                                  retry("caldav"), logger, settings.timezone, calendar_matcher)
    stack.callback(calendar.close)
    calendar.target_profile = tasks.target_profile = profile_id
    return Writers(calendar, tasks, resources)
