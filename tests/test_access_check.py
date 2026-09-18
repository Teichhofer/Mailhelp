"""Read-only access diagnostics never enter the mail-processing path."""
from contextlib import contextmanager
from types import SimpleNamespace
import sys

import httpx
import pytest

from mailhelp.application import Application
from mailhelp.imap import ImapReader
from mailhelp.integrations import GoogleOAuthTokenProvider, HttpWriter
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
        assert seen[0].method == "GET" and seen[0].url.path == expected
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
    def __init__(self, error=None, send_error=None):
        self.error = error
        self.send_error = send_error
        self.calls = []
        self.sent = []

    def check_access(self, *args):
        self.calls.append(args)
        if self.error is not None:
            raise self.error

    def send(self, chat_id, text):
        self.sent.append((chat_id, text))
        if self.send_error is not None:
            raise self.send_error


def test_application_access_check_runs_every_check_after_errors():
    imap = Check(RuntimeError())
    openrouter = Check(ValueError("bad key"))
    telegram, todoist, calendar = Check(), Check(), Check()
    application = SimpleNamespace(
        settings=SimpleNamespace(
            imap=SimpleNamespace(folders=["INBOX"]),
            telegram=SimpleNamespace(chat_id=12345), timezone="Europe/Berlin",
        ),
        imap=imap, openrouter=openrouter, telegram=telegram,
        todoist=todoist, calendar=calendar,
    )
    results = Application.check_access(application)

    assert results == {
        "IMAP": "RuntimeError", "OpenRouter": "bad key", "Telegram": None,
        "Todoist": None, "Google Calendar": None,
    }
    assert imap.calls == [(["INBOX"],)]
    assert all(item.calls == [()] for item in (openrouter, telegram, todoist, calendar))
    assert len(telegram.sent) == 1
    chat_id, message = telegram.sent[0]
    assert chat_id == 12345
    assert message.startswith("Test – Datum: ")
    assert ", Uhrzeit: " in message and message.endswith(" (Europe/Berlin)")


def test_application_reports_telegram_test_message_failure_and_skips_send_if_bot_is_invalid():
    for telegram, expected_sent, expected_error in (
        (Check(RuntimeError("bot invalid")), [], "bot invalid"),
        (Check(send_error=RuntimeError("chat denied")), [(7,)], "chat denied"),
    ):
        application = SimpleNamespace(
            settings=SimpleNamespace(
                imap=SimpleNamespace(folders=["INBOX"]),
                telegram=SimpleNamespace(chat_id=7), timezone="UTC",
            ),
            imap=Check(), openrouter=Check(), telegram=telegram,
            todoist=Check(), calendar=Check(),
        )
        results = Application.check_access(application)

        assert results["Telegram"] == expected_error
        assert [(chat_id,) for chat_id, _message in telegram.sent] == expected_sent


def test_application_distinguishes_oauth_failure_without_logging_response_secrets(tmp_path):
    response_secret = "untrusted-issued-token"
    logger = JsonlLogger(tmp_path, secrets=("client-secret", "refresh-secret"))
    provider = GoogleOAuthTokenProvider(
        "client", "client-secret", "refresh-secret", logger=logger,
        transport=response_transport({
            "access_token": response_secret, "expires_in": 100, "token_type": "MAC",
        }),
    )
    calendar = HttpWriter(
        "google_calendar", provider, "target", logger=logger,
        transport=response_transport({}), calendar_timezone="UTC",
    )
    application = SimpleNamespace(
        settings=SimpleNamespace(imap=SimpleNamespace(folders=["INBOX"])),
        logger=logger, imap=Check(), openrouter=Check(), telegram=Check(),
        todoist=Check(), calendar=calendar,
    )

    results = Application.check_access(application)

    assert results["Google Calendar"].startswith("Google OAuth: Token-Abruf abgelehnt")
    logs = (tmp_path / "application.jsonl").read_text(encoding="utf-8")
    assert response_secret not in logs
    assert "client-secret" not in logs and "refresh-secret" not in logs
    calendar.close()
    provider.close()


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
        assert kwargs == {"access_diagnostics": True, "logger": logger}
        yield App()

    logger = type("Logger", (), {"event": lambda *_args, **_kwargs: None})()
    monkeypatch.setattr("mailhelp.cli.load_all", lambda _directory: (None, None, [], None, "fingerprint"))
    monkeypatch.setattr("mailhelp.cli.build_logger", lambda *_args: logger)
    monkeypatch.setattr("mailhelp.cli.build_application", builder)
    monkeypatch.setattr(sys, "argv", ["mailhelp", "--check-access"])
    assert main() == status
    assert capsys.readouterr().out == expected
