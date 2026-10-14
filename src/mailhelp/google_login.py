"""Desktop Google OAuth: loopback, PKCE and private, profile-bound token storage."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

from .external.contracts import OAuthTokenError
from .storage import atomic_replace
from .target_profiles import secret_name

SCOPES = "https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/calendar.calendars.readonly"


def receive_code(url_builder, *, opener=webbrowser.open, server_factory=HTTPServer, clock=time.monotonic):
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    result = {}

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query)
            accepted = (
                parsed.path == "/oauth/callback"
                and query.get("state") == [state]
                and len(query.get("code", [])) == 1
                and bool(query["code"][0])
            )
            self.send_response(200 if accepted else 400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(b"Mailhelp: Anmeldung empfangen." if accepted else b"Ungueltige Anmeldung.")
            if accepted:
                result["code"] = query["code"][0]

    with server_factory(("127.0.0.1", 0), Callback) as server:
        server.timeout = 1
        redirect = f"http://127.0.0.1:{server.server_port}/oauth/callback"
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        if not opener(url_builder(redirect, state, challenge)):
            raise OAuthTokenError("Browser konnte nicht geöffnet werden.")
        deadline = clock() + 300
        while "code" not in result:
            if clock() >= deadline:
                raise OAuthTokenError("Google-Anmeldung abgelaufen.")
            server.handle_request()
    return result["code"], redirect, verifier


def login(credentials, directory, profile=1, *, receiver=receive_code, transport=None):
    client_id = credentials.google_oauth_client_id.get_secret_value()
    client_secret = credentials.google_oauth_client_secret.get_secret_value()
    if not client_id or not client_secret:
        raise OAuthTokenError("Google OAuth Client-ID oder Client-Secret fehlt.")

    def authorize(redirect, state, challenge):
        return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(
            {
                "client_id": client_id,
                "redirect_uri": redirect,
                "response_type": "code",
                "scope": SCOPES,
                "access_type": "offline",
                "prompt": "consent",
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )

    code, redirect, verifier = receiver(authorize)
    try:
        with httpx.Client(transport=transport, timeout=30) as client:
            response = client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                    "redirect_uri": redirect,
                    "grant_type": "authorization_code",
                    "code_verifier": verifier,
                },
            )
            response.raise_for_status()
            token = response.json()["refresh_token"]
            if not isinstance(token, str) or not token or len(token) > 16384:
                raise ValueError("Ungültiges Token")
    except (httpx.HTTPError, ValueError, KeyError):
        raise OAuthTokenError("Google-Anmeldung fehlgeschlagen; kein Refresh-Token gespeichert.") from None
    name = "GOOGLE_OAUTH_REFRESH_TOKEN" if profile == 1 else secret_name("GOOGLE_OAUTH_REFRESH_TOKEN", profile)
    path = directory / ".env"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    lines = [line for line in lines if line.split("=", 1)[0].strip() != name]
    atomic_replace(path, "\n".join([*lines, name + "=" + json.dumps(token)]) + "\n")
    path.chmod(0o600)
