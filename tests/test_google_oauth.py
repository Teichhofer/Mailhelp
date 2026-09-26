import json

import httpx
import pytest

from mailhelp.integrations import (AuthenticationError, CalendarAccessError,
                                   GoogleOAuthTokenProvider, HttpWriter,
                                   OAuthTokenError, execute_confirmed)
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
    with pytest.raises(OAuthTokenError, match="OAuth-Anmeldung abgelehnt"):
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


def test_successful_oauth_token_then_calendar_access_records_acceptance():
    token_log, calendar_log, seen = Log(), Log(), []
    provider = GoogleOAuthTokenProvider(
        "client", "secret", "refresh", logger=token_log,
        transport=httpx.MockTransport(lambda request: httpx.Response(
            200, json={"access_token": "issued", "expires_in": 3600,
                       "token_type": "Bearer"}, request=request)),
    )

    def calendar(request):
        seen.append(request)
        return httpx.Response(200, json={}, request=request)

    writer = HttpWriter("google_calendar", provider, "primary", logger=calendar_log,
                        transport=httpx.MockTransport(calendar), calendar_timezone="UTC")
    writer.check_access()
    assert seen[0].headers["authorization"] == "Bearer issued"
    assert token_log.events[-1][0][2] == "token_credentials_accepted"
    writer.close()
    provider.close()


@pytest.mark.parametrize("status, body, expected", [
    (401, {"error": {"message": "issued secret"}}, "Access-Token wurde"),
    (403, {"error": {"errors": [{"reason": "insufficientPermissions"}]}}, "Berechtigung"),
    (403, {"error": {"errors": [{"reason": "forbidden"}]}}, "Berechtigung"),
    (403, {"error": {"errors": [{"reason": "accessNotConfigured"}]}}, "API ist deaktiviert"),
    (403, {"error": {"errors": [{"reason": "serviceDisabled"}]}}, "API ist deaktiviert"),
    (403, {"error": {"errors": [{"reason": "apiDisabled"}]}}, "API ist deaktiviert"),
    (403, {"error": {"errors": [{"reason": "unknown-secret"}]}}, "Aufruf wurde verweigert"),
    (403, ["invalid"], "Aufruf wurde verweigert"),
    (403, {"error": "invalid"}, "Aufruf wurde verweigert"),
    (403, {"error": {"errors": "invalid"}}, "Aufruf wurde verweigert"),
    (403, {"error": {"errors": ["invalid"]}}, "Aufruf wurde verweigert"),
    (404, {"error": "calendar-secret"}, "existiert nicht"),
])
def test_calendar_access_diagnostics_use_only_safe_categories(status, body, expected):
    log = Log()
    writer = HttpWriter(
        "google_calendar", "issued-secret", "target",
        transport=httpx.MockTransport(lambda request: httpx.Response(
            status, json=body, request=request)), calendar_timezone="UTC", logger=log,
    )
    error = AuthenticationError if status == 401 else CalendarAccessError
    with pytest.raises(error, match=expected) as caught:
        writer.check_access()
    message = str(caught.value)
    assert "issued-secret" not in message and "unknown-secret" not in message
    assert log.events[-1][1]["reason"] != "unknown-secret"
    writer.close()


def test_invalid_google_error_json_is_never_exposed():
    secret = "body-secret"
    writer = HttpWriter(
        "google_calendar", "token", "target",
        transport=httpx.MockTransport(lambda request: httpx.Response(
            403, content=b"not-json-body-secret", request=request)),
        calendar_timezone="UTC",
    )
    with pytest.raises(CalendarAccessError) as caught:
        writer.check_access()
    assert secret not in str(caught.value)
    writer.close()
