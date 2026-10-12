"""Google access-token renewal, isolated from Calendar resource requests."""
from __future__ import annotations

import time
from collections.abc import Callable

import httpx
from pydantic import Field, ValidationError

from ..logging import EventLogger, NullLogger
from .contracts import IntegrationModel, OAuthTokenError


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

