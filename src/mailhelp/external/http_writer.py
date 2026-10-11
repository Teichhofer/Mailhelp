"""Compatible construction and dispatch for the two HTTP integration adapters."""
from __future__ import annotations
from typing import Any, Callable
import time, traceback
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import httpx
from pydantic import ValidationError
from ..models import CalendarDuplicateDecision, Proposal
from ..adapter import RetryPolicy, uncertain_write
from ..logging import EventLogger, NullLogger
from .contracts import AccessTokenProvider, CalendarEventResponse, PreparedWrite, TodoistTaskResponse, proposal_is_writable, _path
from .calendar import CalendarOperations
from .todoist import TodoistOperations
from .transport import HttpTransport

class HttpWriter(CalendarOperations, TodoistOperations, HttpTransport):
    def __init__(self, service: str, token: str | AccessTokenProvider, target: str, timeout: float = 30, transport: httpx.BaseTransport | None = None, policy: RetryPolicy | None = None, logger: EventLogger | None = None, calendar_timezone: str | None = None,
                 calendar_matcher: Callable[[Proposal, dict[str, Any]], tuple[str, CalendarDuplicateDecision]] | None = None):
        if service not in {"todoist", "google_calendar"}: raise ValueError("Unbekannter Dienst")
        if service == "google_calendar":
            if calendar_timezone is None: raise ValueError("Google Kalender benötigt die konfigurierte IANA-Zeitzone")
            try: ZoneInfo(calendar_timezone)
            except (ZoneInfoNotFoundError, ValueError) as exc: raise ValueError("Unbekannte IANA-Zeitzone für Google Kalender") from exc
        base = "https://api.todoist.com/api/v1" if service == "todoist" else "https://www.googleapis.com/calendar/v3"
        self.service, self.target, self.calendar_timezone = service, target, calendar_timezone
        self.calendar_matcher = calendar_matcher
        self._token_provider = token if service == "google_calendar" and not isinstance(token, str) else None
        self._static_token = token if isinstance(token, str) else None
        self.client = httpx.Client(base_url=base, timeout=timeout, transport=transport)
        self.policy = policy or RetryPolicy(0, 0, 0, lambda _delay: False)
        self.logger = logger or NullLogger()
        self._read_cache: dict[tuple[Any, ...], tuple[float, Any]] = {}
        self._cache_ttl: float = 60.0


    def check_access(self) -> None:
        """Verify access to the configured target using only a GET request."""
        url = (f"/projects/{self.target}" if self.service == "todoist"
               else f"/calendars/{self.target}")
        self.policy.run(lambda: self._get(url, {}))


    def reconcile(self, key: str) -> dict[str, Any] | None:
        self.logger.event("INFO", self.service, "reconcile_started", call_id=key)
        if self.service == "todoist":
            return self._reconcile_todoist(key)
        return self._reconcile_calendar(key)

    def create(self, proposal: Proposal, key: str) -> dict[str, Any]:
        return self.prepare(proposal, key).operation()


    def prepare(self, proposal: Proposal, key: str) -> PreparedWrite:
        """Perform read-only checks and return the actual write operation."""
        if not proposal_is_writable(proposal):
            raise ValueError("Dieser Vorschlag darf nicht extern angelegt werden")
        if proposal.target != self.target:
            raise ValueError("Konfiguriertes Ziel weicht vom bestätigten Vorschlagsziel ab")
        self.logger.event("INFO", self.service, "create_started", call_id=key, mail_id=proposal.source_mail_id, proposal_id=proposal.id)
        if self.service == "todoist":
            return self._prepare_todoist(proposal, key)
        return self._prepare_calendar(proposal, key)

    def _create_prepared(self, proposal: Proposal, key: str, url: str,
                         body: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            response = uncertain_write(lambda: self._post(url, body, key))
        except Exception as exc:
            self.logger.event("ERROR", self.service, "create_failed", call_id=key, mail_id=proposal.source_mail_id,
                              proposal_id=proposal.id, error=exc, stacktrace=traceback.format_exc(), duration_ms=round((time.perf_counter()-started)*1000, 3))
            raise
        model = TodoistTaskResponse if self.service == "todoist" else CalendarEventResponse
        try: result = model.model_validate(response.json())
        except (ValueError, ValidationError) as exc: raise ValueError(f"{self.service}: ungültige Antwort am Schlüsselpfad {_path(exc)}") from exc
        self.logger.event("INFO", self.service, "create_completed", call_id=key, mail_id=proposal.source_mail_id,
                          proposal_id=proposal.id, duration_ms=round((time.perf_counter()-started)*1000, 3), status=response.status_code)
        self._read_cache.clear()
        return result.model_dump()

