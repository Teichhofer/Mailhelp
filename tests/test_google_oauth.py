import json

import httpx
import pytest

from mailhelp.integrations import (AuthenticationError, GoogleOAuthTokenProvider, HttpWriter,
                                   TodoistOAuthTokenProvider, execute_confirmed)
from mailhelp.logging import JsonlLogger
from test_core import proposal


class Log:
    def __init__(self):
        self.events = []

    def event(self, *args, **kwargs):
        self.events.append((args, kwargs))


def test_first_token_cached_regular_refresh_expiry_and_restart():
    now = [100.0]
    requests = []

    def issue(request):
        requests.append(request)
        return httpx.Response(200, json={"access_token": f"short-{len(requests)}", "expires_in": 120, "token_type": "Bearer"}, request=request)

    arguments = dict(client_id="client", client_secret="secret", refresh_token="refresh", transport=httpx.MockTransport(issue), clock=lambda: now[0])
    provider = GoogleOAuthTokenProvider(**arguments)
    assert provider.access_token() == provider.access_token() == "short-1"
    assert len(requests) == 1 and b"grant_type=refresh_token" in requests[0].content
    now[0] = 161
    assert provider.access_token() == "short-2"  # within the safety margin
    now[0] = 1000
    assert provider.access_token() == "short-3"  # fully expired
    provider.invalidate()
    assert provider.access_token() == "short-4"
    provider.close()

    restarted = GoogleOAuthTokenProvider(**arguments)
    assert restarted.access_token() == "short-5"  # no token survives a restart
    restarted.close()


def test_todoist_uses_client_credentials_and_rotates_refresh_token():
    now = [100.0]
    requests = []

    def issue(request):
        requests.append(request)
        number = len(requests)
        return httpx.Response(200, json={"access_token": f"access-{number}", "expires_in": 120,
                                         "token_type": "Bearer", "refresh_token": f"refresh-{number}"},
                              request=request)

    provider = TodoistOAuthTokenProvider("client-id", "client-secret", "initial-refresh",
                                         transport=httpx.MockTransport(issue), clock=lambda: now[0])
    assert provider.access_token() == provider.access_token() == "access-1"
    first = requests[0].content
    assert all(value in first for value in (b"client_id=client-id", b"client_secret=client-secret",
                                             b"refresh_token=initial-refresh"))
    now[0] = 161
    assert provider.access_token() == "access-2"
    assert b"refresh_token=refresh-1" in requests[1].content
    provider.invalidate()
    assert provider.access_token() == "access-3"
    provider.close()


@pytest.mark.parametrize("response", [
    (401, {"error": "invalid_client"}),
    (200, {"access_token": "x", "expires_in": 10, "token_type": "MAC", "refresh_token": "r"}),
    (200, {"access_token": "", "expires_in": 0, "token_type": "Bearer", "refresh_token": ""}),
])
def test_todoist_oauth_rejects_invalid_token_responses(response):
    status, body = response
    provider = TodoistOAuthTokenProvider("client", "secret", "refresh", transport=httpx.MockTransport(
        lambda request: httpx.Response(status, json=body, request=request)))
    with pytest.raises(AuthenticationError, match="Todoist-OAuth"):
        provider.access_token()
    provider.close()


@pytest.mark.parametrize("response", [
    (400, {"error": "invalid_grant", "refresh_token": "must-not-log"}),
    (200, {"access_token": "x", "expires_in": 10, "token_type": "MAC"}),
    (200, {"access_token": "", "expires_in": 0, "token_type": "Bearer"}),
])
def test_authorization_is_permanently_denied_and_logs_are_redacted(tmp_path, response):
    status, body = response
    values = ("client-id-value", "client-secret-value", "refresh-value", "must-not-log")
    logger = JsonlLogger(tmp_path, secrets=values)
    transport = httpx.MockTransport(lambda request: httpx.Response(status, json=body, request=request))
    provider = GoogleOAuthTokenProvider(*values[:3], transport=transport, logger=logger)
    with pytest.raises(AuthenticationError, match="verweigert"):
        provider.access_token()
    provider.close()
    content = (tmp_path / "application.jsonl").read_text(encoding="utf-8")
    assert all(value not in content for value in (*values, "access_token"))
    records = [json.loads(line) for line in content.splitlines()]
    assert records[-1]["event"] == "token_refresh_denied"


def test_calendar_401_is_authentication_failure_without_second_write():
    calls = []

    class Provider:
        invalidated = 0

        def access_token(self):
            return "ephemeral"

        def invalidate(self):
            self.invalidated += 1

    provider = Provider()

    def reject(request):
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"items": []}, request=request)
        return httpx.Response(401, json={"error": {"message": "token=ephemeral"}}, request=request)

    writer = HttpWriter("google_calendar", provider, "primary", transport=httpx.MockTransport(reject), calendar_timezone="UTC", logger=Log())
    saved = []
    result, external = execute_confirmed(proposal(kind="event", status="confirmed", start="2026-01-01T10:00:00+00:00", end="2026-01-01T11:00:00+00:00"), writer, saved.append)
    assert result.status.value == "failed" and external == {}
    assert [request.method for request in calls] == ["GET", "POST"]  # never a blind second POST
    assert provider.invalidated == 1
    writer.close()

    legacy = HttpWriter("google_calendar", "static", "primary", transport=httpx.MockTransport(
        lambda request: httpx.Response(401, request=request)), calendar_timezone="UTC")
    with pytest.raises(AuthenticationError):
        legacy.reconcile("key")
    legacy.close()
