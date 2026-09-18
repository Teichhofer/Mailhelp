"""Idempotente Adapter für Todoist und Google Kalender."""
from __future__ import annotations
from datetime import datetime
from typing import Any, Callable, Protocol
import time, traceback
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from .models import (Proposal, ProposalCertainty, ProposalClassification, ProposalKind,
                     ProposalResponsibility, ProposalStatus)
from .adapter import PermanentError, RetryPolicy, UncertainWriteError, uncertain_write
from .logging import EventLogger, NullLogger


class AuthenticationError(PermanentError):
    """Anmeldedaten wurden dauerhaft abgelehnt; ein Schreibzugriff ist nicht unklar."""


class IntegrationModel(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)


class OAuthTokenResponse(IntegrationModel):
    access_token: str = Field(min_length=1)
    expires_in: int = Field(gt=0)
    token_type: str


class GoogleOAuthTokenProvider:
    """Hält kurzlebige Google-Tokens ausschließlich im Arbeitsspeicher."""

    def __init__(self, client_id: str, client_secret: str, refresh_token: str, timeout: float = 30,
                 transport: httpx.BaseTransport | None = None, clock: Callable[[], float] = time.time,
                 refresh_margin_seconds: float = 60, logger: EventLogger | None = None):
        self._client_id, self._client_secret, self._refresh_token = client_id, client_secret, refresh_token
        self._clock, self._margin = clock, refresh_margin_seconds
        self._token: str | None = None
        self._expires_at = 0.0
        self._client = httpx.Client(base_url="https://oauth2.googleapis.com", timeout=timeout, transport=transport)
        self._logger = logger or NullLogger()

    def access_token(self) -> str:
        if self._token is not None and self._clock() < self._expires_at - self._margin:
            return self._token
        self._logger.event("INFO", "google_oauth", "token_refresh_started")
        try:
            response = self._client.post("/token", data={
                "client_id": self._client_id, "client_secret": self._client_secret,
                "refresh_token": self._refresh_token, "grant_type": "refresh_token",
            })
            response.raise_for_status()
            value = OAuthTokenResponse.model_validate(response.json())
            if value.token_type.lower() != "bearer":
                raise ValueError("unerwarteter Token-Typ")
        except (httpx.HTTPStatusError, ValueError, ValidationError) as exc:
            self._logger.event("ERROR", "google_oauth", "token_refresh_denied",
                               status=exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None)
            raise AuthenticationError("Google-OAuth-Autorisierung verweigert") from exc
        self._token, self._expires_at = value.access_token, self._clock() + value.expires_in
        self._logger.event("INFO", "google_oauth", "token_refresh_completed", expires_in=value.expires_in)
        return self._token

    def invalidate(self) -> None:
        self._token, self._expires_at = None, 0.0

    def close(self) -> None:
        self._client.close()


class TodoistTaskResponse(IntegrationModel):
    id: str | int
    description: str = ""
    url: str | None = None


class CalendarEventResponse(IntegrationModel):
    id: str = Field(min_length=1)
    htmlLink: str | None = None


class CalendarListResponse(IntegrationModel):
    items: list[CalendarEventResponse]


class ExternalWriter(Protocol):
    def reconcile(self, key: str) -> dict[str, Any] | None: ...
    def create(self, proposal: Proposal, key: str) -> dict[str, Any]: ...


class AccessTokenProvider(Protocol):
    def access_token(self) -> str: ...
    def invalidate(self) -> None: ...


def proposal_is_writable(proposal: Proposal) -> bool:
    """Return whether the proposal may be confirmed and externally created."""
    return (proposal.classification == ProposalClassification.NEW and
            proposal.responsibility == ProposalResponsibility.USER and
            proposal.certainty == ProposalCertainty.CERTAIN)


def execute_confirmed(proposal: Proposal, writer: ExternalWriter, persist: Callable[[Proposal], None], test_mode: bool = False) -> tuple[Proposal, dict[str, Any]]:
    if not proposal_is_writable(proposal):
        raise ValueError("Nur neue, sichere und eigene Vorschläge dürfen extern angelegt werden")
    if proposal.status == ProposalStatus.SIMULATED:
        return proposal, {"simulation": True}
    if proposal.status not in {ProposalStatus.CONFIRMED, ProposalStatus.WRITING, ProposalStatus.UNCERTAIN} or proposal.open_questions: raise ValueError("Schreiben erfordert vollständige, bestätigte Vorschlagsversion")
    if test_mode:
        simulated = proposal.model_copy(update={
            "status": ProposalStatus.SIMULATED,
            "external_id": None,
            "external_link": None,
        })
        persist(simulated)
        return simulated, {"simulation": True}
    key = f"mailhelp:{proposal.source_mail_id}:{proposal.id}:v{proposal.version}"
    found = writer.reconcile(key)
    if found is not None:
        created = _with_external_result(proposal, found)
        persist(created)
        return created, found
    # A request which may already have reached the external service must never
    # be repeated automatically.  Later reconciliations may still prove that
    # it succeeded.
    if proposal.status in {ProposalStatus.WRITING, ProposalStatus.UNCERTAIN}:
        uncertain = proposal.model_copy(update={"status": ProposalStatus.UNCERTAIN})
        persist(uncertain)
        return uncertain, {}
    # Only this transition is allowed to initiate a new external write.  A
    # future operator retry therefore needs its own explicit state transition
    # back to CONFIRMED rather than falling through from UNCERTAIN.
    writing = proposal.model_copy(update={"status": ProposalStatus.WRITING})
    persist(writing)
    try: result = writer.create(writing, key)
    except (UncertainWriteError, httpx.TimeoutException, httpx.TransportError):
        uncertain = writing.model_copy(update={"status": ProposalStatus.UNCERTAIN})
        persist(uncertain)
        return uncertain, {}
    except (PermanentError, httpx.HTTPStatusError):
        failed = writing.model_copy(update={"status": ProposalStatus.FAILED})
        persist(failed)
        return failed, {}
    created = _with_external_result(writing, result)
    persist(created)
    return created, result


def _with_external_result(proposal: Proposal, result: dict[str, Any]) -> Proposal:
    external_id = result.get("id")
    if external_id is None or isinstance(external_id, bool) or not str(external_id):
        raise ValueError("Externe Integration: benötigter Schlüsselpfad id fehlt")
    link = result.get("url") or result.get("html_url") or result.get("htmlLink")
    return proposal.model_copy(update={
        "status": ProposalStatus.CREATED,
        "external_id": str(external_id) if external_id is not None else None,
        "external_link": str(link) if link is not None else None,
    })


class HttpWriter:
    def __init__(self, service: str, token: str | AccessTokenProvider, target: str, timeout: float = 30, transport: httpx.BaseTransport | None = None, policy: RetryPolicy | None = None, logger: EventLogger | None = None, calendar_timezone: str | None = None):
        if service not in {"todoist", "google_calendar"}: raise ValueError("Unbekannter Dienst")
        if service == "google_calendar":
            if calendar_timezone is None: raise ValueError("Google Kalender benötigt die konfigurierte IANA-Zeitzone")
            try: ZoneInfo(calendar_timezone)
            except (ZoneInfoNotFoundError, ValueError) as exc: raise ValueError("Unbekannte IANA-Zeitzone für Google Kalender") from exc
        base = "https://api.todoist.com/rest/v2" if service == "todoist" else "https://www.googleapis.com/calendar/v3"
        self.service, self.target, self.calendar_timezone = service, target, calendar_timezone
        self._token_provider = token if service == "google_calendar" and not isinstance(token, str) else None
        self._static_token = token if isinstance(token, str) else None
        self.client = httpx.Client(base_url=base, timeout=timeout, transport=transport)
        self.policy = policy or RetryPolicy(0, 0, 0, lambda _delay: False)
        self.logger = logger or NullLogger()

    def check_access(self) -> None:
        """Verify access to the configured target using only a GET request."""
        url = (f"/projects/{self.target}" if self.service == "todoist"
               else f"/calendars/{self.target}")
        self.policy.run(lambda: self._get(url, {}))

    def reconcile(self, key: str) -> dict[str, Any] | None:
        self.logger.event("INFO", self.service, "reconcile_started", call_id=key)
        if self.service == "todoist":
            response = self.policy.run(lambda: self._get("/tasks", {"project_id": self.target}))
            items = self._validate_list(response, TodoistTaskResponse, "Todoist tasks")
            found = next((item for item in items if key in item.description), None)
            return found.model_dump() if found else None
        response = self.policy.run(lambda: self._get(f"/calendars/{self.target}/events", {"privateExtendedProperty": f"mailhelp_key={key}"}))
        try: items = CalendarListResponse.model_validate(response.json()).items
        except (ValueError, ValidationError) as exc: raise ValueError(f"Google Calendar events: ungültige Antwort am Schlüsselpfad {_path(exc)}") from exc
        return items[0].model_dump() if items else None

    def create(self, proposal: Proposal, key: str) -> dict[str, Any]:
        if not proposal_is_writable(proposal):
            raise ValueError("Dieser Vorschlag darf nicht extern angelegt werden")
        self.logger.event("INFO", self.service, "create_started", call_id=key, mail_id=proposal.source_mail_id, proposal_id=proposal.id)
        if self.service == "todoist":
            if proposal.kind != ProposalKind.TASK: raise ValueError("Todoist akzeptiert nur Aufgaben")
            url, body = "/tasks", {"content": proposal.title, "description": f"{proposal.description}\n\n[{key}]".strip(), "project_id": self.target}
            if isinstance(proposal.due, datetime):
                body["due_datetime"] = proposal.due.isoformat()
            elif proposal.due is not None:
                body["due_date"] = proposal.due.isoformat()
        else:
            if proposal.kind != ProposalKind.EVENT: raise ValueError("Kalender akzeptiert nur Termine")
            url, body = f"/calendars/{self.target}/events", self._calendar_event_body(proposal, key)
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
        return result.model_dump()

    def _calendar_event_body(self, proposal: Proposal, key: str) -> dict[str, Any]:
        # Revalidate at the external trust boundary; model_copy() can otherwise
        # construct an inconsistent proposal without running model validators.
        validated = Proposal.model_validate(proposal.model_dump())
        interval = self._all_day_interval(validated) if validated.all_day else self._timed_interval(validated)
        description = validated.description
        if validated.video_link is not None:
            video_section = f"[Mailhelp-Videolink]\n{validated.video_link}"
            description = f"{description}\n\n{video_section}" if description else video_section
        body = {"summary": validated.title, "description": description, **interval,
                "extendedProperties": {"private": {"mailhelp_key": key}}}
        if validated.location is not None:
            body["location"] = validated.location
        return body

    @staticmethod
    def _all_day_interval(proposal: Proposal) -> dict[str, Any]:
        # Google interprets end.date as exclusive: a one-day event therefore
        # has end equal to the calendar day after start.
        return {"start": {"date": proposal.start.isoformat()}, "end": {"date": proposal.end.isoformat()}}

    def _timed_interval(self, proposal: Proposal) -> dict[str, Any]:
        return {
            "start": {"dateTime": proposal.start.isoformat(), "timeZone": self.calendar_timezone},
            "end": {"dateTime": proposal.end.isoformat(), "timeZone": self.calendar_timezone},
        }

    @staticmethod
    def _validate_list(response: httpx.Response, model: type[IntegrationModel], operation: str) -> list[IntegrationModel]:
        try:
            value = response.json()
            if not isinstance(value, list): raise ValueError("Antwort ist keine Liste")
            return [model.model_validate(item) for item in value]
        except (ValueError, ValidationError) as exc: raise ValueError(f"{operation}: ungültige Antwort am Schlüsselpfad {_path(exc)}") from exc

    def close(self) -> None: self.client.close()

    def _get(self, url: str, params: dict[str, Any]) -> httpx.Response:
        self.logger.event("DEBUG", self.service, "http_request", method="GET", url=url)
        response = self.client.get(url, params=params, headers=self._auth_headers())
        self._raise_for_status(response)
        return response

    def _post(self, url: str, body: dict[str, Any], key: str) -> httpx.Response:
        self.logger.event("DEBUG", self.service, "http_request", method="POST", url=url, call_id=key)
        response = self.client.post(url, json=body, headers={**self._auth_headers(), "X-Request-Id": key})
        self._raise_for_status(response)
        return response

    def _auth_headers(self) -> dict[str, str]:
        token = self._token_provider.access_token() if self._token_provider is not None else self._static_token
        return {"Authorization": f"Bearer {token}"}

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code == 401 and self.service == "google_calendar":
            if self._token_provider is not None:
                self._token_provider.invalidate()
            self.logger.event("ERROR", self.service, "authentication_failed", status=401)
            raise AuthenticationError("Google-Calendar-Autorisierung verweigert")
        response.raise_for_status()


def _path(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return ", ".join(".".join(str(value) for value in item["loc"]) or "<root>" for item in exc.errors(include_input=False))
    return "<json>"
