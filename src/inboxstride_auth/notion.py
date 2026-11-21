"""8.2: Notion OAuth tokens for the central Inboxstride service."""
from __future__ import annotations

from urllib.parse import urlencode, urlsplit

import httpx

from .google import Client, GoogleTokens, TokenAnswer

CALLBACK = "https://auth.inboxstride.de/auth/notion/callback"


class NotionTokens(GoogleTokens):
    token_url = "https://api.notion.com/v1/oauth/token"

    def __init__(self, client: Client, *, timeout: float = 15,
                 transport: httpx.BaseTransport | None = None) -> None:
        redirect = urlsplit(client.redirect)
        local_http = redirect.scheme == "http" and redirect.hostname in {"localhost", "127.0.0.1"}
        if (not redirect.hostname or redirect.username or redirect.password or redirect.query or redirect.fragment
                or redirect.path != "/auth/notion/callback" or (redirect.scheme != "https" and not local_http)):
            raise ValueError("Invalid Notion callback")
        super().__init__(client, timeout=timeout, transport=transport)

    def authorize(self, state: str, challenge: str, scopes: tuple[str, ...]) -> str:
        return "https://api.notion.com/v1/oauth/authorize?" + urlencode({
            "client_id": self.client.client_id, "redirect_uri": self.client.redirect,
            "response_type": "code", "owner": "user", "state": state,
            "code_challenge": challenge, "code_challenge_method": "S256"})

    def _post(self, data: dict[str, str]) -> TokenAnswer:
        return super()._post({**data, "scope": "notion"})
