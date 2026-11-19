"""8.0: the central Inboxstride service and Google, simulated together for instance tests.

The instance's mTLS client talks to the real ``inboxstride_auth`` request handling through an
``httpx.MockTransport``; the client certificate is represented by its fingerprint, as the TLS
layer would report it. Google's token endpoint and calendar list are simulated as well.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx

from inboxstride_auth.google import Client, GoogleTokens
from inboxstride_auth.http_api import internal, public
from inboxstride_auth.models import Instance
from inboxstride_auth.secret_store import SecretStore, create_key
from inboxstride_auth.service import AuthService
from inboxstride_auth.state_file import StateFile
from mailhelp.config.target_settings import HostedAuthSettings
from mailhelp.external.hosted_oauth import HostedAuthClient
from tests.fakes.google_oauth import FakeGoogle

CALENDARS = [{"id": "familie@group.calendar.google.com", "summary": "Familie", "accessRole": "owner"},
             {"id": "feiertage", "summary": "Feiertage", "accessRole": "reader"}]
FINGERPRINTS = {"anna": "1" * 64, "bert": "2" * 64}


def settings(instance: str = "anna") -> HostedAuthSettings:
    return HostedAuthSettings(enabled=True, service_url="https://auth-intern.inboxstride.example:8443",
                              instance_id=instance, certificate="/tls/instance.pem", key="/tls/instance.key",
                              ca="/tls/ca.pem")


class Central:
    """One central service with two registered instances and a simulated Google."""

    def __init__(self, directory: Path) -> None:
        key = directory / "auth.key"
        create_key(key)
        self.google = FakeGoogle()
        self.events: list[tuple[str, dict]] = []
        self.calendars = list(CALENDARS)
        self.down = False
        self.tokens = GoogleTokens(Client("synthetic-client", "synthetic-client-secret"),
                                   transport=httpx.MockTransport(self.google))
        self.service = AuthService(StateFile(directory / "central"), SecretStore(directory / "central", key),
                                   self.tokens)
        for name in ("anna", "bert"):
            self.service.register(Instance(id=name, host=f"{name}.inboxstride.example",
                                           certificate=FINGERPRINTS[name]))

    def _log(self, event: str, context: dict) -> None:
        self.events.append((event, context))

    def transport(self, instance: str = "anna") -> httpx.MockTransport:
        """What one instance reaches: the internal API with its certificate, and Google's calendar list."""
        def handle(request: httpx.Request) -> httpx.Response:
            if request.url.host == "www.googleapis.com":
                if not request.headers.get("Authorization", "").startswith("Bearer access-"):
                    return httpx.Response(401, json={"error": {"code": 401}})
                return httpx.Response(200, json={"items": self.calendars})
            if self.down:
                raise httpx.ConnectError("synthetic outage", request=request)
            answer = internal(self.service, request.method, request.url.path, request.content,
                              FINGERPRINTS[instance], self._log)
            return httpx.Response(answer.status, content=answer.body, headers=answer.headers)
        return httpx.MockTransport(handle)

    def client(self, instance: str = "anna") -> HostedAuthClient:
        return HostedAuthClient(settings(instance), self.transport(instance))

    def google_return(self, url: str, code: str = "good", error: str | None = None) -> str:
        """Google's redirect to the central callback after the user's consent; returns where it sends the browser."""
        from urllib.parse import parse_qs, urlsplit
        state = parse_qs(urlsplit(url).query)["state"][0]
        target = f"/auth/google/callback?state={state}" + (f"&error={error}" if error else f"&code={code}")
        answer = public(self.service, "GET", target, self._log)
        return answer.headers["Location"] if answer.status == 303 else json.dumps({"status": answer.status})

    def close(self) -> None:
        self.tokens.close()
