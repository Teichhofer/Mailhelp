"""Shared HTTP requests, caching and service error classification."""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

from ..adapter import PermanentError, RetryPolicy
from ..logging import EventLogger
from ..models import CalendarDuplicateDecision, Proposal
from .contracts import AccessTokenProvider, AuthenticationError, CalendarAccessError


class HttpTransport:
    client: httpx.Client
    logger: EventLogger
    service: str
    role: str
    label: str
    target: str
    policy: RetryPolicy
    calendar_timezone: str | None
    calendar_matcher: Callable[[Proposal, dict[str, Any]], tuple[str, CalendarDuplicateDecision]] | None
    _token_provider: AccessTokenProvider | None
    _static_token: str | None
    _read_cache: dict[tuple[Any, ...], tuple[float, Any]]
    _cache_ttl: float
    _create_prepared: Callable[[Proposal, str, str, dict[str, Any]], dict[str, Any]]

    def _get_cached(self, key: tuple[Any, ...]) -> Any | None:
        if key in self._read_cache:
            ts, val = self._read_cache[key]
            if time.time() - ts < self._cache_ttl:
                return val
        return None


    def _set_cached(self, key: tuple[Any, ...], val: Any) -> None:
        self._read_cache[key] = (time.time(), val)


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
        message: str | None
        if self.service == "google_calendar" and response.status_code in {401, 403, 404}:
            status = response.status_code
            reason = _google_error_reason(response) if status == 403 else None
            if status == 401:
                if self._token_provider is not None:
                    self._token_provider.invalidate()
                message = "Google Calendar: ausgestellter Access-Token wurde vom Calendar-Endpunkt abgelehnt"
                error: type[PermanentError] = AuthenticationError
            elif status == 404:
                message = ("Google Calendar: Zielkalender existiert nicht oder ist für das authentifizierte "
                           "Konto nicht sichtbar")
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

