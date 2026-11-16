"""7.2.5: a public Notion connection signed in through OAuth, bound to one workspace.

Notion rotates the refresh token on every renewal; the newest pair is written at once to
``notion-token.json`` (``notion-token-<n>.json`` for further profiles) next to ``.env``, readable only
by the owner. Before renewing, the provider reads the file again: when another process rotated the
pair meanwhile, it takes that pair instead of sending an already used refresh token. The workspace
and bot of the first sign-in are kept; a renewal for another workspace is refused.
"""
from __future__ import annotations

import base64
import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..llm.adapter import RETRYABLE_STATUS
from ..logging import EventLogger, NullLogger
from ..persistence.storage import atomic_replace
from .contracts import AccessTokenProvider, ExternalUnavailable, OAuthTokenError

TOKEN_URL = "https://api.notion.com/v1/oauth/token"
AUTHORIZE_URL = "https://api.notion.com/v1/oauth/authorize"


class NotionGrant(BaseModel):
    model_config = ConfigDict(extra="ignore")
    access_token: str = Field(min_length=1, max_length=4096)
    refresh_token: str = Field(min_length=1, max_length=4096)
    workspace_id: str = Field(min_length=1, max_length=100)
    bot_id: str = Field(min_length=1, max_length=100)
    workspace_name: str | None = Field(default=None, max_length=200)


def token_path(directory: Path, profile: int) -> Path:
    return directory / ("notion-token.json" if profile == 1 else f"notion-token-{profile}.json")


class NotionTokenFile:
    """The newest grant as readable JSON next to ``.env``; never in the state directory."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> NotionGrant | None:
        try:
            return NotionGrant.model_validate_json(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, ValidationError):
            return None

    def save(self, grant: NotionGrant) -> None:
        atomic_replace(self.path, json.dumps({"schema_version": 1, **grant.model_dump(),
                                              "updated_at": datetime.now(UTC).isoformat()}, indent=2) + "\n")
        os.chmod(self.path, 0o600)


def exchange(client: httpx.Client, client_id: str, client_secret: str, body: dict[str, str]) -> NotionGrant:
    """One token request with the client's Basic credentials; the answer becomes a grant."""
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    response = client.post(TOKEN_URL, json=body, headers={"Authorization": f"Basic {basic}"})
    if response.status_code in RETRYABLE_STATUS:
        raise ExternalUnavailable("Notion-Anmeldedienst vorübergehend nicht erreichbar")
    try:
        response.raise_for_status()
        return NotionGrant.model_validate(response.json())
    except (httpx.HTTPStatusError, ValueError, ValidationError):
        # Never chain: the answer may contain tokens.
        raise OAuthTokenError("Notion-Anmeldung abgelehnt oder abgelaufen; Notion erneut verbinden.") from None


class NotionTokenProvider(AccessTokenProvider):
    """Access tokens of the saved grant; renewed on demand, rotated pairs saved at once."""

    _lock = threading.Lock()

    def __init__(self, client_id: str, client_secret: str, tokens: NotionTokenFile, timeout: float = 30,
                 transport: httpx.BaseTransport | None = None, logger: EventLogger | None = None) -> None:
        self._client_id, self._client_secret, self._tokens = client_id, client_secret, tokens
        self._client = httpx.Client(timeout=timeout, transport=transport, trust_env=False, follow_redirects=False)
        self._logger = logger or NullLogger()
        self._grant: NotionGrant | None = None
        self._stale = False

    def _current(self) -> NotionGrant:
        grant = self._tokens.load()
        if grant is None:
            raise OAuthTokenError("Notion: keine Anmeldung vorhanden; unter Zielprofile „Notion verbinden“.")
        return grant

    def access_token(self) -> str:
        with self._lock:
            if self._grant is not None and not self._stale:
                return self._grant.access_token
            saved = self._current()
            if self._grant is None or saved.refresh_token != self._grant.refresh_token or not self._stale:
                # First use, or another process rotated the pair meanwhile: take the saved pair.
                self._grant, self._stale = saved, False
                return saved.access_token
            self._logger.event("INFO", "notion_oauth", "token_refresh_started")
            renewed = exchange(self._client, self._client_id, self._client_secret,
                               {"grant_type": "refresh_token", "refresh_token": saved.refresh_token})
            if (renewed.workspace_id, renewed.bot_id) != (saved.workspace_id, saved.bot_id):
                self._logger.event("ERROR", "notion_oauth", "workspace_changed")
                raise OAuthTokenError("Notion: Erneuerung für einen anderen Arbeitsbereich abgelehnt.")
            self._tokens.save(renewed)
            self._grant, self._stale = renewed, False
            self._logger.event("INFO", "notion_oauth", "token_credentials_accepted")
            return renewed.access_token

    def invalidate(self) -> None:
        """After a refused request: the next call renews, unless the file has a newer pair."""
        with self._lock:
            self._stale = True

    def close(self) -> None:
        self._client.close()
