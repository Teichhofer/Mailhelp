"""8.0: the instance side of the central Inboxstride OAuth service (Planung 8.0, sections 3 and 6).

The instance talks to the service over mTLS with its own client certificate. It holds only an
opaque connection reference; the refresh token and the shared Google client secret stay in the
central service. Access tokens are kept in memory for their short lifetime and never stored.
"""
from __future__ import annotations

import ssl
import time
from collections.abc import Callable
from typing import Any

import httpx

from ..config.target_settings import HostedAuthSettings
from ..logging import EventLogger, NullLogger
from .contracts import ExternalUnavailable, OAuthTokenError

MARGIN_SECONDS = 30
# Connections disconnected in this process; the central service refuses them anyway after a restart.
_disconnected: set[str] = set()


def forget_locally(connection: str) -> None:
    """Every provider of this process stops using *connection*, even with a token still cached."""
    _disconnected.add(connection)


class HostedRefused(RuntimeError):
    """The service refused the request; ``code`` is its content-free reason."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class HostedUnavailable(ExternalUnavailable):
    """The central service is not reachable; Google actions stay open, nothing else is affected."""


def mtls_transport(settings: HostedAuthSettings) -> httpx.HTTPTransport:
    context = ssl.create_default_context(cafile=settings.ca)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return httpx.HTTPTransport(verify=context, cert=(settings.certificate, settings.key))


class HostedAuthClient:
    def __init__(self, settings: HostedAuthSettings, transport: httpx.BaseTransport | None = None,
                 timeout: float = 15) -> None:
        self._http = httpx.Client(base_url=settings.service_url, timeout=timeout, trust_env=False,
                                  transport=transport or mtls_transport(settings))

    def post(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self._http.post(path, json=data)
        except httpx.HTTPError:
            raise HostedUnavailable("Inboxstride-Anmeldedienst nicht erreichbar") from None
        try:
            body = response.json()
        except ValueError:
            raise HostedUnavailable("Antwort des Anmeldedienstes nicht lesbar") from None
        if response.status_code == 200 and isinstance(body, dict):
            return body
        error = body.get("error") if isinstance(body, dict) else None
        if response.status_code in {403, 409} and isinstance(error, str):
            raise HostedRefused(error)
        raise HostedUnavailable("Anmeldedienst antwortete unerwartet")

    def close(self) -> None:
        self._http.close()


def cached_client(read: Callable[[], HostedAuthSettings],
                  transport: httpx.BaseTransport | None = None) -> Callable[[], HostedAuthClient | None]:
    """One client per effective settings; None while the hosted sign-in is not configured."""
    cache: dict[str, Any] = {}

    def client() -> HostedAuthClient | None:
        settings = read()
        if not settings.enabled:
            return None
        key = settings.model_dump_json()
        if cache.get("key") != key:
            if "client" in cache:
                cache["client"].close()
            cache.update(key=key, client=HostedAuthClient(settings, transport))
        result: HostedAuthClient = cache["client"]
        return result
    return client


class HostedTokenProvider:
    """``AccessTokenProvider`` for a hosted Google connection; reports sign-in outcomes like Google's."""

    def __init__(self, client: HostedAuthClient, connection: str, logger: EventLogger | None = None,
                 clock: Callable[[], float] = time.monotonic, purpose: str = "calendar") -> None:
        self.client, self.connection, self.clock = client, connection, clock
        self.purpose = purpose
        self._logger = logger or NullLogger()
        self._token: str | None = None
        self._until = 0.0

    def access_token(self) -> str:
        if self.connection in _disconnected:
            # Planung 8.0, section 6: a disconnect also ends the local use of a token still cached.
            self.invalidate()
            raise OAuthTokenError("Google-Verbindung über Inboxstride getrennt; Google erneut verbinden.")
        if self._token is not None and self.clock() < self._until:
            return self._token
        self._logger.event("INFO", "google_oauth", "token_refresh_started", mode="hosted")
        try:
            data = {"connection": self.connection}
            if self.purpose != "calendar":
                data["purpose"] = self.purpose
            answer = self.client.post("/intern/token", data)
        except HostedRefused as exc:
            # The same event as a refused direct renewal: the warning of 7.9.2 names Google sign-in.
            self._logger.event("ERROR", "google_oauth", "token_refresh_denied", mode="hosted", reason=exc.code)
            raise OAuthTokenError("Google-Zugang über Inboxstride nicht nutzbar; Google erneut verbinden.") from None
        token, valid = answer.get("access_token"), answer.get("expires_in")
        if not isinstance(token, str) or not token or not isinstance(valid, int) or valid <= 0:
            raise HostedUnavailable("Antwort des Anmeldedienstes unvollständig")
        self._token, self._until = token, self.clock() + max(0, valid - MARGIN_SECONDS)
        self._logger.event("INFO", "google_oauth", "token_credentials_accepted", mode="hosted")
        return token

    def invalidate(self) -> None:
        self._token, self._until = None, 0.0

    def close(self) -> None:
        self.client.close()


__all__ = ["MARGIN_SECONDS", "HostedAuthClient", "HostedRefused", "HostedTokenProvider", "HostedUnavailable",
           "cached_client", "forget_locally", "mtls_transport"]
