"""Read-only access diagnostics never enter the mail-processing path."""
from contextlib import contextmanager
from types import SimpleNamespace
import sys

import httpx
import pytest

from mailhelp.application import Application
from mailhelp.imap import ImapReader
from mailhelp.integrations import CalendarAccessError, HttpWriter, OAuthTokenAccessError, GoogleOAuthTokenProvider
from mailhelp.logging import JsonlLogger
from mailhelp.openrouter import OpenRouterClient
from mailhelp.telegram import TelegramClient, TelegramBotResponse
from mailhelp.cli import main


def response_transport(payload, status=200, seen=None):
    def handle(request):
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json=payload)
    return httpx.MockTransport(handle)


def test_adapter_access_checks_are_read_only_and_validate_responses():
    connection = SimpleNamespace(select=lambda folder, readonly: ("OK", [folder, readonly]))
    reader = object.__new__(ImapReader)
    reader.connection = connection
    reader.check_access(["INBOX", "Archive"])
    connection.select = lambda _folder, readonly: ("NO", [readonly])
    with pytest.raises(RuntimeError, match="nicht lesbar"):
        reader.check_access(["Missing"])

    seen = []
    openrouter = OpenRouterClient("secret", 1, 0, 1,
                                  transport=response_transport({"data": {}}, seen=seen))
    openrouter.check_access()
    assert seen[0].method == "GET" and seen[0].url.path.endswith("/auth/key")
    assert seen[0].headers["authorization"] == "Bearer secret"
    openrouter.close()
    for payload in ([], {"data": []}):
        client = OpenRouterClient("key", 1, 0, 1, transport=response_transport(payload))
        with pytest.raises(ValueError, match="Schlüsselpfad data"):
            client.check_access()
        client.close()

    telegram_seen = []
    telegram = TelegramClient("token", 1, transport=response_transport(
        {"ok": True, "result": {"id": 1, "is_bot": True}}, seen=telegram_seen))
    telegram.check_access()
    assert telegram_seen[0].method == "GET" and telegram_seen[0].url.path.endswith("/getMe")
    telegram.close()
    invalid = TelegramClient("token", 1, transport=response_transport({"wrong": True}))
    with pytest.raises(ValueError, match="Telegram getMe"):
        invalid.check_access()
    invalid.close()
    for value in (
        {"ok": False, "result": {"id": 1, "is_bot": True}},
        {"ok": True, "result": {"id": 1, "is_bot": False}},
    ):
        with pytest.raises(ValueError, match="keinen gültigen Bot"):
            TelegramBotResponse.model_validate(value)


def test_target_access_checks_only_issue_get_requests():
    for service, target, expected in (
        ("todoist", "project", "/api/v1/projects/project"),
        ("google_calendar", "calendar", "/calendar/v3/calendars/calendar"),
    ):
        seen = []
        writer = HttpWriter(service, "token", target, 1,
                            transport=response_transport({}, seen=seen),
                            calendar_timezone="UTC" if service == "google_calendar" else None)
        writer.check_access()
        writer.check_authentication()
        assert seen[0].method == "GET" and seen[0].url.path == expected
        writer.close()


def test_google_oauth_and_calendar_success_are_separate_checks():
    seen = []

    def handle(request):
        seen.append(request)
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "issued", "expires_in": 3600,
                                             "token_type": "Bearer"}, request=request)
        return httpx.Response(200, json={}, request=request)

    provider = GoogleOAuthTokenProvider("client", "secret", "refresh", transport=httpx.MockTransport(handle))
    calendar = HttpWriter("google_calendar", provider, "target", transport=httpx.MockTransport(handle),
                          calendar_timezone="UTC")
    application = SimpleNamespace(
        settings=SimpleNamespace(imap=SimpleNamespace(folders=[])), imap=Check(),
        openrouter=Check(), telegram=Check(), todoist=Check(), calendar=calendar,
    )
    results = Application.check_access(application)
    assert results["Google OAuth"] is None and results["Google Calendar"] is None
    assert provider.credentials_accepted is True
    assert [request.url.host for request in seen] == ["oauth2.googleapis.com", "www.googleapis.com"]
    calendar.close()
    provider.close()


def test_google_oauth_failure_is_distinct_and_calendar_is_still_reported():
    provider = GoogleOAuthTokenProvider("client", "secret", "refresh", transport=response_transport({}, 400))
    calendar = HttpWriter("google_calendar", provider, "target", transport=response_transport({}, 200),
                          calendar_timezone="UTC")
    application = SimpleNamespace(
        settings=SimpleNamespace(imap=SimpleNamespace(folders=[])), imap=Check(),
        openrouter=Check(), telegram=Check(), todoist=Check(), calendar=calendar,
    )
    results = Application.check_access(application)
    assert results["Google OAuth"] == "Google OAuth: Token-Abruf wurde verweigert"
    assert results["Google Calendar"] == "Google Calendar: nicht geprüft, weil Google OAuth fehlgeschlagen ist"
    assert isinstance(_capture_oauth_error(provider), OAuthTokenAccessError)
    calendar.close()
    provider.close()


def _capture_oauth_error(provider):
    try:
        provider.access_token()
    except OAuthTokenAccessError as exc:
        return exc
    raise AssertionError("OAuth failure expected")


@pytest.mark.parametrize("status, body, expected", [
    (401, {"error": {"message": "untrusted"}}, "ausgestellter Access-Token"),
    (403, {"error": {"errors": [{"reason": "insufficientPermissions"}]}}, "Berechtigung"),
    (403, {"error": {"errors": [{"reason": "forbidden"}]}}, "Berechtigung"),
    (403, {"error": {"errors": [{"reason": "accessNotConfigured"}]}}, "API ist deaktiviert"),
    (403, {"error": {"errors": [{"reason": "serviceDisabled"}]}}, "API ist deaktiviert"),
    (403, {"error": {"errors": [{"reason": "secret-unknown"}]}}, "andere Ursache"),
    (403, [], "andere Ursache"),
    (403, {"error": []}, "andere Ursache"),
    (403, {"error": {}}, "andere Ursache"),
    (403, {"error": {"errors": ["bad"]}}, "andere Ursache"),
    (404, {"private": "secret-body"}, "nicht sichtbar"),
])
def test_google_calendar_safe_access_diagnostics(status, body, expected):
    writer = HttpWriter("google_calendar", "token", "target", calendar_timezone="UTC",
                        transport=response_transport(body, status))
    with pytest.raises(CalendarAccessError, match=expected) as caught:
        writer.check_access()
    assert "untrusted" not in str(caught.value) and "secret" not in str(caught.value)
    writer.close()


def test_google_calendar_invalid_json_is_not_exposed(tmp_path):
    secret = "response-secret"
    token = "access-token-secret"
    logger = JsonlLogger(tmp_path, secrets=(secret, token))
    transport = httpx.MockTransport(lambda request: httpx.Response(403, text=secret, request=request))
    writer = HttpWriter("google_calendar", token, "target", calendar_timezone="UTC",
                        transport=transport, logger=logger)
    with pytest.raises(CalendarAccessError, match="andere Ursache") as caught:
        writer.check_access()
    assert secret not in str(caught.value)
    logs = (tmp_path / "application.jsonl").read_text(encoding="utf-8")
    assert secret not in logs and token not in logs and "Authorization" not in logs
    writer.close()


@pytest.mark.parametrize("status, message", [
    (401, "Todoist: Authentifizierungsfehler (Token wurde abgelehnt)"),
    (403, "Todoist: Berechtigungsfehler für das Zielprojekt"),
    (404, "Todoist: Zielprojekt nicht erreichbar"),
])
def test_todoist_access_errors_reach_cli_without_secrets(
        tmp_path, monkeypatch, capsys, status, message):
    token = "todoist-token-must-stay-secret"
    response_secret = f"complete-response-secret-{status}"
    seen = []
    logger = JsonlLogger(tmp_path, secrets=(token, response_secret))
    writer = HttpWriter(
        "todoist", token, "real-project-id", 1,
        transport=response_transport(
            {"error": response_secret, "authorization": f"Bearer {token}"},
            status=status,
            seen=seen,
        ),
        logger=logger,
    )
    application = SimpleNamespace(
        settings=SimpleNamespace(imap=SimpleNamespace(folders=["INBOX"])),
        imap=Check(), openrouter=Check(), telegram=Check(), todoist=writer,
        calendar=Check(),
    )

    results = Application.check_access(application)

    assert results["Todoist"] == message
    assert seen[0].headers["authorization"] == f"Bearer {token}"

    class App:
        def check_access(self):
            return results

    @contextmanager
    def builder(*_args, **_kwargs):
        yield App()

    monkeypatch.setattr("mailhelp.cli.load_all", lambda _directory: (None, None, [], None, "fingerprint"))
    monkeypatch.setattr("mailhelp.cli.build_logger", lambda *_args: type("Logger", (), {"event": lambda *_args, **_kwargs: None})())
    monkeypatch.setattr("mailhelp.cli.build_application", builder)
    monkeypatch.setattr(sys, "argv", ["mailhelp", "--check-access"])
    assert main() == 1
    output = capsys.readouterr().out
    logs = (tmp_path / "application.jsonl").read_text(encoding="utf-8")
    assert f"FEHLER: Todoist – {message}" in output
    assert all(secret not in output and secret not in logs for secret in (token, response_secret))
    assert "Authorization" not in output and "Authorization" not in logs
    writer.close()


class Check:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def check_access(self, *args):
        self.calls.append(args)
        if self.error is not None:
            raise self.error

    def check_authentication(self):
        self.check_access()


def test_application_access_check_runs_every_check_after_errors():
    imap = Check(RuntimeError())
    openrouter = Check(ValueError("bad key"))
    telegram, todoist, calendar = Check(), Check(), Check()
    application = SimpleNamespace(
        settings=SimpleNamespace(imap=SimpleNamespace(folders=["INBOX"])),
        imap=imap, openrouter=openrouter, telegram=telegram,
        todoist=todoist, calendar=calendar,
    )

    results = Application.check_access(application)

    assert results == {
        "IMAP": "RuntimeError", "OpenRouter": "bad key", "Telegram": None,
        "Todoist": None, "Google OAuth": None, "Google Calendar": None,
    }
    assert imap.calls == [(["INBOX"],)]
    assert all(item.calls == [()] for item in (openrouter, telegram, todoist))
    assert calendar.calls == [(), ()]


@pytest.mark.parametrize("results, expected, status", [
    ({"IMAP": None, "Telegram": None}, "OK: IMAP\nOK: Telegram\n", 0),
    ({"IMAP": "denied", "Telegram": None}, "FEHLER: IMAP – denied\nOK: Telegram\n", 1),
])
def test_cli_access_check_prints_summary_and_never_runs(monkeypatch, capsys, results, expected, status):
    class App:
        def check_access(self): return results
        def run(self, **_kwargs): raise AssertionError("mail processing must not start")

    @contextmanager
    def builder(*_args, **kwargs):
        assert kwargs["access_diagnostics"] is True
        assert "logger" in kwargs
        yield App()

    monkeypatch.setattr("mailhelp.cli.load_all", lambda _directory: (None, None, [], None, "fingerprint"))
    monkeypatch.setattr("mailhelp.cli.build_logger", lambda *_args: type("Logger", (), {"event": lambda *_args, **_kwargs: None})())
    monkeypatch.setattr("mailhelp.cli.build_application", builder)
    monkeypatch.setattr(sys, "argv", ["mailhelp", "--check-access"])
    assert main() == status
    assert capsys.readouterr().out == expected
