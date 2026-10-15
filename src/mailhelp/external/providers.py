"""Construction of the configured calendar and task writers (Planung 2.3, 3.4)."""
from __future__ import annotations

from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from ..adapter import RetryPolicy
from ..config import Secrets, Settings, TargetSettings
from ..logging import EventLogger
from .caldav import AppleReminders, CalDavCalendar, CalDavTasks
from .contracts import TargetWriter
from .http_writer import HttpWriter
from .microsoft import MicrosoftTodo, MicrosoftTokenProvider, OutlookCalendar, TokenFile
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
               "apple_reminders": "Apple Erinnerungen"}


def provider_services(targets: TargetSettings) -> list[str]:
    """Display names for the connection status: both targets and the sign-ins they need."""
    names = [TASK_LABELS[targets.task_provider], CALENDAR_LABELS[targets.calendar_provider]]
    names += ["Google-Anmeldung"] if targets.calendar_provider == "google" else []
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

    tasks: TargetWriter
    if targets.task_provider == "todoist":
        tasks = HttpWriter("todoist", secrets.todoist_token.get_secret_value(), targets.todoist_project,
                           timeout("todoist"), transport, policy=retry("todoist"), logger=logger)
    elif targets.task_provider == "microsoft_todo":
        assert microsoft is not None
        tasks = MicrosoftTodo(microsoft, targets.microsoft_todo_list, timeout("microsoft"), transport,
                              retry("microsoft"), logger)
    else:
        kind = AppleReminders if targets.task_provider == "apple_reminders" else CalDavTasks
        tasks = kind(targets.caldav_task_url, *caldav, timeout("caldav"), transport, retry("caldav"), logger)

    stack.callback(tasks.close)
    calendar: TargetWriter
    if targets.calendar_provider == "google":
        oauth = GoogleOAuthTokenProvider(
            secrets.google_oauth_client_id.get_secret_value(), secrets.google_oauth_client_secret.get_secret_value(),
            secrets.google_oauth_refresh_token.get_secret_value(), timeout("google_calendar"), transport,
            logger=logger)
        resources.append(oauth)
        stack.callback(oauth.close)
        calendar = HttpWriter("google_calendar", oauth, targets.google_calendar, timeout("google_calendar"), transport,
                              policy=retry("google_calendar"), logger=logger, calendar_timezone=settings.timezone,
                              calendar_matcher=calendar_matcher)
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
