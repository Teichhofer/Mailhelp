"""Delegated Exchange IMAP tokens, independent of Graph calendar permissions."""
import re
from urllib.parse import urlencode, urlsplit

import httpx

from .google import Client, GoogleTokens, TokenAnswer
from .models import MAIL_SCOPES

CALLBACK = "https://auth.inboxstride.de/auth/microsoft/callback"


class MicrosoftTokens(GoogleTokens):
    def __init__(self, client: Client, tenant: str = "common", *, timeout: float = 15,
                 transport: httpx.BaseTransport | None = None,
                 scopes: tuple[str, ...] = MAIL_SCOPES["microsoft"]) -> None:
        if not re.fullmatch(r"common|organizations|consumers|[a-fA-F0-9-]{36}", tenant):
            raise ValueError("Invalid Microsoft tenant")
        redirect = urlsplit(client.redirect)
        local_http = redirect.scheme == "http" and redirect.hostname in {"localhost", "127.0.0.1"}
        if (not redirect.hostname or redirect.username or redirect.password or redirect.query or redirect.fragment
                or redirect.path != "/auth/microsoft/callback" or (redirect.scheme != "https" and not local_http)):
            raise ValueError("Invalid Microsoft callback")
        super().__init__(client, timeout=timeout, transport=transport)
        self.base = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0"
        self.token_url = self.base + "/token"
        self.scopes = scopes

    def authorize(self, state: str, challenge: str, scopes: tuple[str, ...]) -> str:
        return self.base + "/authorize?" + urlencode({
            "client_id": self.client.client_id, "redirect_uri": self.client.redirect,
            "response_type": "code", "scope": " ".join((*scopes, "offline_access")),
            "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
            "prompt": "select_account"})

    def _post(self, data: dict[str, str]) -> TokenAnswer:
        return super()._post({**data, "scope": " ".join((*self.scopes, "offline_access"))})
