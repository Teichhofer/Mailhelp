"""Idempotente Adapter für Todoist, Kalenderdateien und Google Calendar (Legacy)."""
from __future__ import annotations
from datetime import date, datetime, timezone
import hashlib
import re
from typing import Any, Callable, Protocol
import time, traceback
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from .models import (CalendarDuplicateDecision, Proposal, ProposalCertainty, ProposalClassification, ProposalKind,
                     ProposalResponsibility, ProposalStatus)
from .adapter import PermanentError, RetryPolicy, UncertainWriteError, uncertain_write
from .logging import EventLogger, NullLogger


class AuthenticationError(PermanentError):
    """Anmeldedaten wurden dauerhaft abgelehnt; ein Schreibzugriff ist nicht unklar."""


class OAuthTokenError(AuthenticationError):
    """Client oder Refresh-Token wurden am OAuth-Endpunkt abgelehnt."""


class CalendarAccessError(PermanentError):
    """Ein bezogener Access-Token konnte den Zielkalender nicht erreichen."""


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
            # Do not chain the parser/HTTP exception: validation details may
            # contain an untrusted token response and must not reach the
            # access-check stacktrace.
            raise OAuthTokenError(
                "Google OAuth-Anmeldung abgelehnt: Client-Zugangsdaten oder "
                "Refresh-Zugang sind ungültig. Zugangsdaten erneuern und "
                "'mailhelp --check-access' ausführen."
            ) from None
        self._token, self._expires_at = value.access_token, self._clock() + value.expires_in
        self._logger.event("INFO", "google_oauth", "token_credentials_accepted",
                           expires_in=value.expires_in)
        return self._token

    def invalidate(self) -> None:
        self._token, self._expires_at = None, 0.0

    def close(self) -> None:
        self._client.close()


class TodoistTaskResponse(IntegrationModel):
    id: str | int
    description: str = ""
    url: str | None = None


class TodoistTaskListResponse(IntegrationModel):
    results: list[TodoistTaskResponse]
    next_cursor: str | None


class CalendarEventResponse(IntegrationModel):
    id: str = Field(min_length=1)
    htmlLink: str | None = None


class CalendarListResponse(IntegrationModel):
    items: list[CalendarEventResponse]


class CalendarOverlapEvent(IntegrationModel):
    id: str = Field(min_length=1)
    summary: str = Field(default="", max_length=500)
    description: str = Field(default="", max_length=4000)
    location: str | None = Field(default=None, max_length=1000)
    htmlLink: str | None = None
    start: dict[str, str]
    end: dict[str, str]


class ExternalWriter(Protocol):
    def reconcile(self, key: str) -> dict[str, Any] | None: ...
    def create(self, proposal: Proposal, key: str) -> dict[str, Any]: ...


class CalendarFileWriter:
    """Create a standards-based iCalendar attachment and deliver it via Telegram."""

    def __init__(self, telegram: Any, chat_id: int, logger: EventLogger | None = None):
        self.telegram, self.chat_id = telegram, chat_id
        self.logger = logger or NullLogger()

    def check_access(self) -> None:
        """Calendar delivery uses the Telegram access checked separately."""

    def reconcile(self, key: str) -> dict[str, Any] | None:
        # Telegram offers no API for reliably reconciling a possibly delivered
        # document. Returning None makes execute_confirmed retain UNCERTAIN and
        # therefore prevents an automatic duplicate after a crash or timeout.
        return None

    def create(self, proposal: Proposal, key: str) -> dict[str, Any]:
        if proposal.kind != ProposalKind.EVENT or not proposal_is_writable(proposal):
            raise ValueError("Kalenderdateien können nur für anlegbare Termine erzeugt werden")
        content = calendar_file(proposal, key)
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
        filename = f"termin-{digest}.ics"
        self.logger.event("INFO", "calendar_file", "create_started", call_id=key,
                          mail_id=proposal.source_mail_id, proposal_id=proposal.id)
        self.telegram.send_document(
            self.chat_id, filename, content,
            f"Termin „{proposal.title}“ – antippen, um ihn in den Kalender zu übernehmen.",
        )
        self.logger.event("INFO", "calendar_file", "create_completed", call_id=key,
                          mail_id=proposal.source_mail_id, proposal_id=proposal.id,
                          filename=filename)
        return {"id": f"calendar-file:{digest}"}


def calendar_file(proposal: Proposal, key: str) -> bytes:
    """Serialize a validated event as an RFC 5545 compatible UTF-8 file."""
    item = Proposal.model_validate(proposal.model_dump())
    if item.kind != ProposalKind.EVENT or item.start is None or item.end is None:
        raise ValueError("Kalenderdatei benötigt einen vollständigen Termin")
    uid = hashlib.sha256(key.encode("utf-8")).hexdigest() + "@mailhelp.local"
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Mailhelp//Calendar File//DE",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH", "BEGIN:VEVENT", f"UID:{uid}"]
    if item.all_day:
        assert isinstance(item.start, date) and not isinstance(item.start, datetime)
        assert isinstance(item.end, date) and not isinstance(item.end, datetime)
        lines.extend((f"DTSTART;VALUE=DATE:{item.start:%Y%m%d}",
                      f"DTEND;VALUE=DATE:{item.end:%Y%m%d}"))
    else:
        assert isinstance(item.start, datetime) and isinstance(item.end, datetime)
        lines.extend((f"DTSTART:{_ical_datetime(item.start)}", f"DTEND:{_ical_datetime(item.end)}"))
    lines.append(f"SUMMARY:{_ical_text(item.title)}")
    description = item.description
    if item.video_link is not None:
        description = f"{description}\n\nVideolink: {item.video_link}" if description else f"Videolink: {item.video_link}"
    if description:
        lines.append(f"DESCRIPTION:{_ical_text(description)}")
    if item.location:
        lines.append(f"LOCATION:{_ical_text(item.location)}")
    lines.extend(("END:VEVENT", "END:VCALENDAR"))
    return ("\r\n".join(_fold_ical_line(line) for line in lines) + "\r\n").encode("utf-8")


def _ical_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _ical_text(value: str) -> str:
    normalized = value.replace("\\", "\\\\")
    normalized = re.sub(r"\r\n?|\n", lambda _match: "\\n", normalized)
    return normalized.replace(",", "\\,").replace(";", "\\;")


def _fold_ical_line(value: str, limit: int = 75) -> str:
    """Fold without splitting a UTF-8 code point (continuations start with SP)."""
    chunks: list[str] = []
    current = ""
    current_bytes = 0
    for character in value:
        size = len(character.encode("utf-8"))
        available = limit if not chunks else limit - 1
        if current and current_bytes + size > available:
            chunks.append(current)
            current, current_bytes = character, size
        else:
            current += character
            current_bytes += size
    chunks.append(current)
    return "\r\n ".join(chunks)


class AccessTokenProvider(Protocol):
    def access_token(self) -> str: ...
    def invalidate(self) -> None: ...


def proposal_is_writable(proposal: Proposal) -> bool:
    """Return whether the proposal may be confirmed and externally created."""
    creatable_classification = (
        proposal.classification == ProposalClassification.NEW or
        (proposal.classification == ProposalClassification.CHANGE and
         proposal.explicit_create_fallback_confirmed)
    )
    return (creatable_classification and
            proposal.responsibility == ProposalResponsibility.USER and
            proposal.certainty == ProposalCertainty.CERTAIN)


def execute_confirmed(proposal: Proposal, writer: ExternalWriter, persist: Callable[[Proposal], None], test_mode: bool = False) -> tuple[Proposal, dict[str, Any]]:
    if not proposal_is_writable(proposal):
        raise ValueError("Nur neue, sichere und eigene Vorschläge oder ausdrücklich bestätigte Ersatz-Neuanlagen dürfen extern angelegt werden")
    if proposal.status == ProposalStatus.SIMULATED:
        return proposal, {"simulation": True}
    if proposal.status not in {ProposalStatus.CONFIRMED, ProposalStatus.WRITING, ProposalStatus.UNCERTAIN} or proposal.open_questions: raise ValueError("Schreiben erfordert vollständige, bestätigte Vorschlagsversion")
    # Test mode suppresses writes to Todoist, but calendar attachments are the
    # actual user-facing result and are deliberately generated and delivered.
    if test_mode and proposal.kind == ProposalKind.TASK:
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

    def check_access(self) -> None:
        """Verify access to the configured target using only a GET request."""
        url = (f"/projects/{self.target}" if self.service == "todoist"
               else f"/calendars/{self.target}")
        self.policy.run(lambda: self._get(url, {}))

    def reconcile(self, key: str) -> dict[str, Any] | None:
        self.logger.event("INFO", self.service, "reconcile_started", call_id=key)
        if self.service == "todoist":
            cursor = None
            while True:
                params = {"project_id": self.target}
                if cursor is not None:
                    params["cursor"] = cursor
                response = self.policy.run(lambda: self._get("/tasks", params))
                try: page = TodoistTaskListResponse.model_validate(response.json())
                except (ValueError, ValidationError) as exc: raise ValueError(f"Todoist tasks: ungültige Antwort am Schlüsselpfad {_path(exc)}") from exc
                found = next((item for item in page.results if key in item.description), None)
                if found is not None:
                    return found.model_dump()
                cursor = page.next_cursor
                if cursor is None:
                    return None
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
            duplicate = self._matching_calendar_event(proposal)
            if duplicate is not None:
                existing, decision = duplicate
                if decision.missing_fields:
                    body = self._calendar_merge_body(proposal, key, existing, decision)
                    return self._update_calendar_event(existing.id, body, key, proposal)
                return {"id": existing.id, "htmlLink": existing.htmlLink,
                        "operation": "duplicate_skipped"}
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

    def _matching_calendar_event(self, proposal: Proposal) -> tuple[CalendarOverlapEvent, CalendarDuplicateDecision] | None:
        if self.service != "google_calendar" or self.calendar_matcher is None:
            return None
        assert proposal.start is not None and proposal.end is not None
        if proposal.all_day:
            time_min = datetime.combine(proposal.start, datetime.min.time(), timezone.utc).isoformat()
            time_max = datetime.combine(proposal.end, datetime.min.time(), timezone.utc).isoformat()
        else:
            assert isinstance(proposal.start, datetime) and isinstance(proposal.end, datetime)
            time_min, time_max = proposal.start.isoformat(), proposal.end.isoformat()
        response = self.policy.run(lambda: self._get(
            f"/calendars/{self.target}/events",
            {"timeMin": time_min, "timeMax": time_max, "singleEvents": "true",
             "maxResults": "50"},
        ))
        try:
            raw_items = response.json().get("items", [])
            if not isinstance(raw_items, list):
                raise ValueError("items")
            items = [CalendarOverlapEvent.model_validate(item) for item in raw_items]
        except (AttributeError, ValueError, ValidationError) as exc:
            raise ValueError(f"Google Calendar events: ungültige Antwort am Schlüsselpfad {_path(exc)}") from exc
        for item in items:
            safe = item.model_dump(mode="json", exclude={"htmlLink"})
            _call_id, decision = self.calendar_matcher(proposal, safe)
            if decision.same_event:
                return item, decision
        return None

    def _calendar_merge_body(self, proposal: Proposal, key: str,
                             existing: CalendarOverlapEvent,
                             decision: CalendarDuplicateDecision) -> dict[str, Any]:
        body: dict[str, Any] = {"extendedProperties": {"private": {"mailhelp_key": key}}}
        if "description" in decision.missing_fields and proposal.description:
            body["description"] = (f"{existing.description}\n\n{proposal.description}"
                                   if existing.description else proposal.description)
        if "location" in decision.missing_fields and proposal.location and not existing.location:
            body["location"] = proposal.location
        if "video_link" in decision.missing_fields and proposal.video_link is not None:
            link = str(proposal.video_link)
            addition = f"[Mailhelp-Videolink]\n{link}"
            body["description"] = (f"{body.get('description', existing.description)}\n\n{addition}"
                                   if body.get("description", existing.description) else addition)
        return body

    def _update_calendar_event(self, existing_id: str, body: dict[str, Any], key: str,
                               proposal: Proposal) -> dict[str, Any]:
        url = f"/calendars/{self.target}/events/{existing_id}"
        response = uncertain_write(lambda: self._patch(url, body, key))
        try:
            result = CalendarEventResponse.model_validate(response.json()).model_dump()
        except (ValueError, ValidationError) as exc:
            raise ValueError(f"google_calendar: ungültige Antwort am Schlüsselpfad {_path(exc)}") from exc
        self.logger.event("INFO", self.service, "duplicate_updated", call_id=key,
                          mail_id=proposal.source_mail_id, proposal_id=proposal.id,
                          existing_event_id=existing_id)
        return {**result, "operation": "duplicate_updated"}

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
        # dateTime already identifies the instant through its mandatory UTC
        # offset.  Supplying the configured calendar zone as well could make a
        # different zone appear authoritative and reinterpret the wall time.
        return {
            "start": {"dateTime": proposal.start.isoformat()},
            "end": {"dateTime": proposal.end.isoformat()},
        }

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

    def _patch(self, url: str, body: dict[str, Any], key: str) -> httpx.Response:
        self.logger.event("DEBUG", self.service, "http_request", method="PATCH", url=url, call_id=key)
        response = self.client.patch(url, json=body, headers={**self._auth_headers(), "X-Request-Id": key})
        self._raise_for_status(response)
        return response

    def _auth_headers(self) -> dict[str, str]:
        token = self._token_provider.access_token() if self._token_provider is not None else self._static_token
        return {"Authorization": f"Bearer {token}"}

    def _raise_for_status(self, response: httpx.Response) -> None:
        if self.service == "google_calendar" and response.status_code in {401, 403, 404}:
            status = response.status_code
            reason = _google_error_reason(response) if status == 403 else None
            if status == 401:
                if self._token_provider is not None:
                    self._token_provider.invalidate()
                message = "Google Calendar: ausgestellter Access-Token wurde vom Calendar-Endpunkt abgelehnt"
                error: type[PermanentError] = AuthenticationError
            elif status == 404:
                message = "Google Calendar: Zielkalender existiert nicht oder ist für das authentifizierte Konto nicht sichtbar"
                error = CalendarAccessError
            elif reason in {"insufficientPermissions", "forbidden"}:
                message = "Google Calendar: OAuth-Token bezogen, aber Berechtigung für den Zielkalender fehlt"
                error = CalendarAccessError
            elif reason in {"accessNotConfigured", "serviceDisabled", "apiDisabled"}:
                message = "Google Calendar: OAuth-Token bezogen, aber die Calendar API ist deaktiviert"
                error = CalendarAccessError
            else:
                message = "Google Calendar: OAuth-Token bezogen, aber der Calendar-Aufruf wurde verweigert"
                error = CalendarAccessError
            self.logger.event("ERROR", self.service, "target_access_failed", status=status,
                              reason=reason)
            raise error(message)
        if self.service == "todoist":
            message = {
                401: "Todoist: Authentifizierungsfehler (Token wurde abgelehnt)",
                403: "Todoist: Berechtigungsfehler für das Zielprojekt",
                404: "Todoist: Zielprojekt nicht erreichbar",
            }.get(response.status_code)
            if message is not None:
                # Deliberately log only the classification and status.  The
                # response and request headers are untrusted and may contain
                # credentials or provider-supplied confidential content.
                event = "authentication_failed" if response.status_code == 401 else "target_access_failed"
                self.logger.event("ERROR", self.service, event, status=response.status_code)
                error = AuthenticationError if response.status_code == 401 else PermanentError
                raise error(message)
        response.raise_for_status()


def _google_error_reason(response: httpx.Response) -> str | None:
    """Return only an allow-listed Google error reason from an untrusted body."""
    allowed = {"insufficientPermissions", "forbidden", "accessNotConfigured",
               "serviceDisabled", "apiDisabled"}
    try:
        body = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    error = body.get("error")
    if not isinstance(error, dict):
        return None
    errors = error.get("errors")
    if not isinstance(errors, list):
        return None
    for item in errors:
        if isinstance(item, dict) and item.get("reason") in allowed:
            return item["reason"]
    return None


def _path(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return ", ".join(".".join(str(value) for value in item["loc"]) or "<root>" for item in exc.errors(include_input=False))
    return "<json>"
