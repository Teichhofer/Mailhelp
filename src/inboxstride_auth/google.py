"""Google's token endpoint for the central service (Planung 8.0, sections 4.1 and 6).

Answers are untrusted: size-limited, schema-checked and never logged or chained into errors,
because they may contain tokens. Errors are classified so that only a refused grant leads to
``reconnect_required``; network trouble and rate limits stay temporary.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

AUTHORIZE = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
CALLBACK = "https://auth.inboxstride.de/auth/google/callback"
MAX_ANSWER = 65536


class GoogleError(RuntimeError):
    """Base class; the message names the kind only."""


class GrantRefused(GoogleError):
    """``invalid_grant``: the code or refresh token is no longer valid; the user must sign in again."""


class ClientRefused(GoogleError):
    """``invalid_client`` or ``unauthorized_client``: the operator's client configuration is wrong."""


class TemporaryFailure(GoogleError):
    """Network trouble, 5xx or a rate limit; may be retried later."""

    def __init__(self, message: str, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class UnclearResult(GoogleError):
    """A code exchange without a readable answer; a code is never exchanged twice."""


class TokenAnswer(BaseModel):
    model_config = ConfigDict(extra="ignore")
    access_token: str = Field(min_length=1, max_length=4096)
    expires_in: int = Field(gt=0, le=86400)
    token_type: str
    refresh_token: str | None = Field(default=None, min_length=1, max_length=4096)
    scope: str = Field(default="", max_length=4096)


@dataclass(frozen=True)
class Client:
    client_id: str
    client_secret: str
    redirect: str = CALLBACK


def authorization_url(client: Client, state: str, challenge: str, scopes: tuple[str, ...]) -> str:
    """Offline access with consent and a deliberate account choice, bound to state and PKCE."""
    query = {"client_id": client.client_id, "redirect_uri": client.redirect, "response_type": "code",
             "scope": " ".join(scopes), "access_type": "offline", "prompt": "consent select_account",
             "include_granted_scopes": "false", "state": state, "code_challenge": challenge,
             "code_challenge_method": "S256"}
    return f"{AUTHORIZE}?{urlencode(query)}"


class GoogleTokens:
    token_url = TOKEN
    def __init__(self, client: Client, timeout: float = 15, transport: httpx.BaseTransport | None = None) -> None:
        self.client = client
        self._http = httpx.Client(timeout=timeout, transport=transport)

    def authorize(self, state: str, challenge: str, scopes: tuple[str, ...]) -> str:
        return authorization_url(self.client, state, challenge, scopes)

    def exchange(self, code: str, verifier: str) -> TokenAnswer:
        try:
            return self._post({"grant_type": "authorization_code", "code": code, "code_verifier": verifier,
                               "redirect_uri": self.client.redirect})
        except TemporaryFailure:
            # The code may already be redeemed by Google: never try it again.
            raise UnclearResult("Code-Tausch ohne lesbare Antwort") from None

    def refresh(self, refresh_token: str) -> TokenAnswer:
        return self._post({"grant_type": "refresh_token", "refresh_token": refresh_token})

    def _post(self, data: dict[str, str]) -> TokenAnswer:
        try:
            response = self._http.post(self.token_url, data={**data, "client_id": self.client.client_id,
                                                    "client_secret": self.client.client_secret})
        except httpx.HTTPError:
            raise TemporaryFailure("Google nicht erreichbar") from None
        if response.status_code == 429 or response.status_code >= 500:
            retry = response.headers.get("Retry-After", "")
            raise TemporaryFailure("Google vorübergehend nicht verfügbar",
                                   int(retry) if retry.isdigit() else None)
        if len(response.content) > MAX_ANSWER:
            raise TemporaryFailure("Antwort zu groß")
        try:
            body = response.json()
        except ValueError:
            raise TemporaryFailure("Antwort nicht lesbar") from None
        if response.status_code != 200:
            error = body.get("error") if isinstance(body, dict) else None
            if error == "invalid_grant":
                raise GrantRefused("Zugang abgelehnt")
            if error in {"invalid_client", "unauthorized_client"}:
                raise ClientRefused("Client abgelehnt")
            raise TemporaryFailure("Unerwartete Antwort")
        try:
            answer = TokenAnswer.model_validate(body)
        except ValidationError:
            raise TemporaryFailure("Antwort unvollständig") from None
        if answer.token_type.lower() != "bearer":
            raise TemporaryFailure("Unerwarteter Tokentyp")
        return answer

    def close(self) -> None:
        self._http.close()


__all__ = ["AUTHORIZE", "CALLBACK", "TOKEN", "Client", "ClientRefused", "GoogleError", "GoogleTokens",
           "GrantRefused", "TemporaryFailure", "TokenAnswer", "UnclearResult", "authorization_url"]
