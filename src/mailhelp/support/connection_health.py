"""7.9.2: durable sign-in status of every used connection (Planung 7.9, section 4.5).

The status is derived from the content-free event stream the services already write, so a
page never reads logs and never calls a provider. Only explicit sign-in outcomes count:

* a refused token renewal (``token_refresh_denied``) of Google, Microsoft or Notion,
* a refused request (``authentication_failed``, HTTP 401) or missing permission
  (``target_access_failed``, HTTP 403) of a calendar or task service,
* a refused IMAP or IServ sign-in, also from the read-only access check.

Timeouts, network errors and rate limits are other kinds of failure and leave the status
alone. A later successful contact of the same connection clears exactly its warning; saving
new credentials does not. The file holds codes, numbers and times, never provider texts,
tokens or passwords.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

STATE = "connection-health"
OAUTH = {"google_oauth": "Google-Anmeldung", "microsoft_oauth": "Microsoft-Anmeldung",
         "notion_oauth": "Notion-Anmeldung"}
WRITERS = {"todoist": "Todoist", "google_calendar": "Google Kalender", "google_tasks": "Google Tasks",
           "caldav_calendar": "CalDAV-Kalender", "caldav_tasks": "CalDAV-Aufgaben",
           "apple_reminders": "Apple Erinnerungen", "outlook_calendar": "Outlook-Kalender",
           "microsoft_todo": "Microsoft To Do", "notion": "Notion"}
_SUCCESS = {"token_credentials_accepted", "access_confirmed", "create_completed", "duplicate_updated",
            "messages_discovered", "letters_listed", "request_completed", "message_fetched"}
_IMAP_REFUSED = "IMAP-Anmeldung vom Server abgelehnt"
_ISERV_REFUSED = ("IServSignInError", "IServ-Anmeldung fehlgeschlagen", "Unbekanntes IServ-Anmeldeformular")

Code = Literal["refresh_denied", "login_rejected", "permission_denied"]


class ConnectionProblem(BaseModel):
    """The current sign-in problem of one connection; removed once a contact succeeds again."""

    model_config = ConfigDict(extra="forbid")
    key: str = Field(pattern=r"^[a-z_]{2,40}(:[A-Za-z0-9_-]{1,64})?$")
    service: str = Field(pattern=r"^[a-z_]{2,40}$")
    number: int | None = Field(default=None, ge=1, le=99)
    code: Code
    first_seen: datetime
    last_seen: datetime
    last_success: datetime | None = None
    # Strictly increasing per file: a result observed earlier never overrides a later one.
    sequence: int = Field(ge=1)


class ConnectionHealth(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    sequence: int = Field(default=0, ge=0)
    problems: dict[str, ConnectionProblem] = Field(default_factory=dict)
    # Last successful contact of every connection, also without a problem (for late results).
    successes: dict[str, datetime] = Field(default_factory=dict)


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 99 else None


def classify(event: str, context: dict[str, Any]) -> tuple[str, str, int | None, Code | None] | None:
    """(key, service, number, code) of a sign-in outcome; code None is a success; None is unrelated."""
    service = str(context.get("service", ""))
    error = str(context.get("error", ""))
    if service in OAUTH:
        if event == "token_refresh_denied":
            return service, service, None, "refresh_denied"
        return (service, service, None, None) if event == "token_credentials_accepted" else None
    if service in WRITERS:
        number = _int(context.get("profile"))
        failed: dict[str, Code] = {"authentication_failed": "login_rejected",
                                   "target_access_failed": "permission_denied"}
        if event in failed:
            return service, service, number, failed[event]
        if event == "access_check_failed" and error.startswith("AuthenticationError"):
            return service, service, number, "login_rejected"
        return (service, service, number, None) if event in _SUCCESS else None
    if service == "imap":
        account = str(context.get("account_id") or "")
        if not account:
            return None
        key = f"imap:{account}"
        if event in {"poll_failed", "optional_folder_failed"} and error.startswith(_IMAP_REFUSED):
            return key, "imap", _int(context.get("mailbox")), "login_rejected"
        return (key, "imap", _int(context.get("mailbox")), None) if event in _SUCCESS else None
    if service == "iserv":
        number = _int(context.get("account"))
        if number is None:
            return None
        key = f"iserv:{number}"
        if event in {"poll_failed", "access_check_failed"} and any(part in error for part in _ISERV_REFUSED):
            return key, "iserv", number, "login_rejected"
        return (key, "iserv", number, None) if event in _SUCCESS else None
    return None


class ConnectionHealthRecorder:
    """Applies sign-in outcomes in order and keeps them in the readable state file."""

    def __init__(self, store: Any, clock: Callable[[], datetime] = lambda: datetime.now(UTC),
                 warn: Callable[[str], None] = lambda _event: None) -> None:
        self.store, self.clock, self.warn = store, clock, warn
        # Only this process writes the file; frequent success events must not read it each time.
        self._cache: ConnectionHealth | None = None

    def load(self) -> ConnectionHealth:
        """The stored status; a missing file (upgrade) or a damaged one starts empty."""
        if self._cache is None:
            try:
                self._cache = ConnectionHealth.model_validate(self.store.load(STATE, {}))
            except (ValueError, ValidationError, OSError):
                self.warn("connection_health_damaged")
                self._cache = ConnectionHealth()
        return self._cache

    def _save(self, health: ConnectionHealth) -> None:
        self.store.save(STATE, health.model_dump(mode="json"))
        self._cache = health

    def observe(self, event: str, context: dict[str, Any]) -> None:
        outcome = classify(event, context)
        if outcome is None:
            return
        key, service, number, code = outcome
        now = self.clock()
        with self.store.locked():
            health = self.load()
            changed = self._apply(health, key, service, number, code, now)
            if changed is not None:
                self._save(changed)

    @staticmethod
    def _apply(health: ConnectionHealth, key: str, service: str, number: int | None, code: Code | None,
               now: datetime) -> ConnectionHealth | None:
        current = health.problems.get(key)
        sequence = health.sequence + 1
        if code is None:
            if current is None:
                # Only the time of the success is kept; a quiet repetition writes nothing.
                previous = health.successes.get(key)
                if previous is not None and previous >= now:
                    return None
                return health.model_copy(update={"successes": {**health.successes, key: now}})
            if current.last_seen > now:
                return None  # a success observed before the newer failure never clears it
            problems = {name: item for name, item in health.problems.items() if name != key}
            return health.model_copy(update={"sequence": sequence, "problems": problems,
                                             "successes": {**health.successes, key: now}})
        success = health.successes.get(key)
        if success is not None and success > now:
            return None  # a failure observed before the newer success never brings the warning back
        if current is not None and current.code == code and current.last_seen >= now:
            return None
        problem = ConnectionProblem(
            key=key, service=service, number=number if number is not None else current.number if current else None,
            code=code, first_seen=current.first_seen if current is not None else now, last_seen=now,
            last_success=success, sequence=sequence)
        return health.model_copy(update={"sequence": sequence, "problems": {**health.problems, key: problem}})

    def retain(self, services: Iterable[str], accounts: Iterable[str] = ()) -> None:
        """Drop problems of connections that are no longer configured (deactivated or removed)."""
        wanted, keys = set(services), set(accounts)
        with self.store.locked():
            health = self.load()
            kept = {key: item for key, item in health.problems.items()
                    if item.service in wanted or key in keys}
            if kept != health.problems:
                self._save(health.model_copy(update={"problems": kept}))


_SIGN_IN = {"google_calendar": "google_oauth", "google_tasks": "google_oauth", "outlook_calendar": "microsoft_oauth",
            "microsoft_todo": "microsoft_oauth", "notion": "notion_oauth"}


def used_connections(writers: Iterable[str], imap_accounts: Iterable[str],
                     iserv_accounts: Iterable[int]) -> tuple[set[str], set[str]]:
    """(services, keys) of the configured connections, including the sign-in their writers use."""
    services = set(writers)
    services |= {_SIGN_IN[name] for name in services if name in _SIGN_IN}
    keys = {f"imap:{account}" for account in imap_accounts} | {f"iserv:{number}" for number in iserv_accounts}
    return services, keys


def current(store: Any) -> tuple[ConnectionProblem, ...]:
    """The problems to show, oldest first; a damaged file shows nothing rather than failing the page."""
    try:
        health = ConnectionHealth.model_validate(store.load(STATE, {}))
    except (ValueError, ValidationError, OSError):
        return ()
    return tuple(sorted(health.problems.values(), key=lambda item: (item.first_seen, item.key)))


def digest(problems: Iterable[ConnectionProblem]) -> str:
    """Changes when a warning appears, changes its kind or disappears (not on every repetition)."""
    parts = sorted((item.key, item.code) for item in problems)
    return hashlib.sha256(json.dumps(parts).encode("utf-8")).hexdigest()[:16]


__all__ = ["OAUTH", "STATE", "WRITERS", "ConnectionHealth", "ConnectionHealthRecorder", "ConnectionProblem",
           "classify", "current", "digest", "used_connections"]
