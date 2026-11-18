"""A simulated Google token endpoint for the central OAuth service (8.0); synthetic values only."""
from __future__ import annotations

import json
from urllib.parse import parse_qs

import httpx

from inboxstride_auth.models import SCOPES

FULL_SCOPE = " ".join(SCOPES)


class FakeGoogle:
    """Answers by code or refresh token; every request is kept (without being logged anywhere)."""

    def __init__(self) -> None:
        self.requests: list[dict[str, str]] = []
        self.rotate = False
        self.issued = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        form = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
        self.requests.append(form)
        if form.get("client_secret") != "synthetic-client-secret":
            return httpx.Response(401, json={"error": "invalid_client"})
        value = form.get("code") or form.get("refresh_token") or ""
        if value.startswith("lost"):
            raise httpx.ReadTimeout("synthetic", request=request)
        special = {
            "refused": httpx.Response(400, json={"error": "invalid_grant"}),
            "busy": httpx.Response(429, headers={"Retry-After": "30"}, json={}),
            "down": httpx.Response(503, text="down"),
            "html": httpx.Response(200, text="<html>"),
            "odd": httpx.Response(400, json={"error": "invalid_request"}),
            "huge": httpx.Response(200, content=b" " * 70000),
            "partial": httpx.Response(200, json={"access_token": "x"}),
            "mac": httpx.Response(200, json={"access_token": "x", "expires_in": 3600, "token_type": "mac"}),
            "list": httpx.Response(400, json=["error"]),
        }
        for prefix, response in special.items():
            if value.startswith(prefix):
                return response
        self.issued += 1
        answer = {"access_token": f"access-{self.issued}", "expires_in": 3600, "token_type": "Bearer",
                  "scope": "https://www.googleapis.com/auth/calendar.events" if value.startswith("narrow")
                  else FULL_SCOPE}
        if form["grant_type"] == "authorization_code" and not value.startswith("norefresh"):
            answer["refresh_token"] = f"refresh-for-{value}"
        if form["grant_type"] == "refresh_token" and self.rotate:
            answer["refresh_token"] = f"rotated-{self.issued}"
        return httpx.Response(200, content=json.dumps(answer).encode())
