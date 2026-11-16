"""6.1.1: every setup failure gets a catalogue code with cause and remedy – never provider text."""
import imaplib
import re
import socket
import ssl
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from mailhelp.config import Settings
from mailhelp.external.contracts import (
    AuthenticationError,
    CalendarAccessError,
    ExternalRefused,
    ExternalUnavailable,
    OAuthTokenError,
    TargetAccessError,
)
from mailhelp.mailbox.imap import FolderNotReadable, ImapLoginRejected, StartTlsFailed
from mailhelp.runtime import setup_checks as module
from mailhelp.runtime.setup_checks import SetupChecks
from mailhelp.runtime.setup_messages import CATALOGUE, CheckResult, SetupProblem, classify, finding
from tests.fakes.initial_harness import initial  # noqa: F401  (fixture)

SECRET = "geheim-passwort-123"


def test_every_code_used_in_the_code_has_a_cause_and_every_error_a_remedy():
    used = set()
    for path in Path("src/mailhelp").rglob("*.py"):
        used |= set(re.findall(r'SetupProblem\(\s*"([a-z0-9_.]+)"', path.read_text(encoding="utf-8")))
    text = Path("src/mailhelp/runtime/setup_checks.py").read_text(encoding="utf-8")
    used |= set(re.findall(r'(?:SetupProblem\(|else )"([a-z]+\.[a-z_]+)"', text))
    assert used and used <= set(CATALOGUE)
    for code, message in CATALOGUE.items():
        assert message.cause.endswith(".")
        if not code.endswith(".ok") and code not in {"password.kept"}:
            assert message.steps, code
    assert finding("imap.auth_failed").field == "IMAP_PASSWORD"
    assert finding("imap.auth_failed", field="x").field == "x"
    result = CheckResult(step=2, ok=True, findings=[finding("imap.drafts_missing", severity="warning")])
    assert result.warnings and not CheckResult(step=2, ok=True).warnings


@pytest.mark.parametrize(("error", "code"), [
    (SetupProblem("imap.auth_failed"), "imap.auth_failed"),
    (httpx.ReadTimeout("x"), "timeout"), (TimeoutError(), "timeout"), (ssl.SSLError(), "tls"),
    (httpx.HTTPStatusError("x", request=httpx.Request("GET", "https://a.test"),
                           response=httpx.Response(401)), "target.auth_failed"),
    (httpx.HTTPStatusError("x", request=httpx.Request("GET", "https://a.test"),
                           response=httpx.Response(500)), "service"),
    (httpx.ConnectError("x"), "network"), (socket.gaierror(), "network"), (OSError(), "network"),
    (RuntimeError(SECRET), "unknown"),
])
def test_exceptions_are_classified_by_type_only(error, code):
    assert classify(error) == code


def config(initial, **mailbox):
    initial.advance()
    raw = initial.setup.state().config
    raw["imap"].update(mailbox)
    if "primary_folder" in mailbox:
        raw["imap"]["folders"] = [mailbox["primary_folder"]]
    return Settings.model_validate(raw), initial.setup.environment()


def failing(error):
    def reader(*args, **kwargs):
        raise error
    return reader


@pytest.mark.parametrize(("error", "mailbox", "code"), [
    (ImapLoginRejected(SECRET), {}, "imap.auth_failed"),
    (StartTlsFailed(SECRET), {}, "imap.tls_mismatch"),
    (ssl.SSLCertVerificationError(SECRET), {}, "imap.certificate"),
    (ssl.SSLError(SECRET), {}, "imap.tls_mismatch"),
    (socket.gaierror(SECRET), {}, "imap.host_unknown"),
    (TimeoutError(SECRET), {"port": 993, "connection_mode": "starttls"}, "imap.tls_mismatch"),
    (imaplib.IMAP4.abort(SECRET), {"port": 143, "connection_mode": "ssl"}, "imap.tls_mismatch"),
    (TimeoutError(SECRET), {"port": 993, "connection_mode": "ssl"}, "imap.unreachable"),
    (ConnectionRefusedError(SECRET), {}, "imap.unreachable"),
])
def test_regression_imap_failures_name_their_cause_without_server_text(initial, error, mailbox, code):
    """Regression 6.1: every setup failure ended in the same message "Eingaben und Verbindungsdaten
    prüfen", so a wrong port could not be told apart from a wrong password."""
    cfg, env = config(initial, **mailbox)
    with pytest.raises(SetupProblem) as raised:
        SetupChecks(initial.directory, reader=failing(error)).imap(cfg, env)
    assert raised.value.code == code
    assert SECRET not in str(raised.value) and SECRET not in raised.value.detail


class Reader:
    folders = [SimpleNamespace(name="INBOX", role="inbox"), SimpleNamespace(name="Entwürfe", role="drafts")]
    closed = 0

    def __init__(self, *args, **kwargs):
        pass

    def list_folders(self):
        return self.folders

    def check_access(self, folders):
        pass

    def close(self):
        Reader.closed += 1


def test_missing_inbox_lists_the_folders_and_a_missing_drafts_folder_is_only_noted(initial, monkeypatch):
    cfg, env = config(initial, primary_folder="Posteingang", drafts_folder="Drafts")
    with pytest.raises(SetupProblem) as raised:
        SetupChecks(initial.directory, reader=Reader).imap(cfg, env)
    assert raised.value.code == "imap.folder_missing" and raised.value.detail == "INBOX, Entwürfe"
    cfg, env = config(initial, primary_folder="inbox", drafts_folder="Drafts")
    result = SetupChecks(initial.directory, reader=Reader).imap(cfg, env)
    assert result["drafts_missing"] and result["drafts"] == "Entwürfe" and "993" in result["server"]
    monkeypatch.setattr(Reader, "check_access", lambda self, folders: (_ for _ in ()).throw(
        FolderNotReadable("INBOX")))
    with pytest.raises(SetupProblem, match="imap.folder_missing"):
        SetupChecks(initial.directory, reader=Reader).imap(cfg, env)
    with pytest.raises(SetupProblem, match="imap.missing") as raised:
        SetupChecks(initial.directory, reader=Reader).imap(cfg, {})
    assert "IMAP_PASSWORD" in raised.value.detail


def router(initial, handler):
    initial.advance()
    cfg = Settings.model_validate(initial.setup.state().config)
    prompts = initial.setup.prompts(initial.setup.state())
    return SetupChecks(initial.directory, httpx.MockTransport(handler)), cfg, prompts


@pytest.mark.parametrize(("status", "code"), [(401, "llm.key_invalid"), (403, "llm.key_invalid"),
                                              (402, "llm.no_credit"), (429, "llm.service"), (503, "llm.service")])
def test_openrouter_status_codes_have_their_own_message(initial, status, code):
    checks, cfg, prompts = router(initial, lambda request: httpx.Response(status, text=SECRET))
    with pytest.raises(SetupProblem) as raised:
        checks.llm(cfg, initial.setup.environment(), prompts)
    assert raised.value.code == code and SECRET not in str(raised.value)


def test_openrouter_names_missing_models_and_an_empty_key_limit(initial):
    def handler(request):
        if request.url.path.endswith("/key"):
            return httpx.Response(200, json={"data": {"limit_remaining": 0}})
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": name} for name in names]})
        return httpx.Response(200, json={"data": {"total_credits": 1, "total_usage": 1}})
    names = set()
    checks, cfg, prompts = router(initial, handler)
    with pytest.raises(SetupProblem) as raised:
        checks.llm(cfg, initial.setup.environment(), prompts)
    assert raised.value.code == "llm.model_missing" and "/" in raised.value.detail
    names = {route.model for name in prompts.prompts for route in prompts.resolved_routes(name)[0]}
    with pytest.raises(SetupProblem, match="llm.no_credit"):
        checks.llm(cfg, initial.setup.environment(), prompts)


@pytest.mark.parametrize(("handler", "code"), [
    (lambda request: (_ for _ in ()).throw(httpx.ConnectError("refused")), "llm.ollama_unreachable"),
    (lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("slow")), "timeout"),
    (lambda request: httpx.Response(500), "llm.ollama_unreachable"),
    (lambda request: httpx.Response(200, text="kein json"), "llm.ollama_unreachable"),
    (lambda request: httpx.Response(200, json={"models": []}), "llm.ollama_empty"),
])
def test_ollama_failures(initial, handler, code):
    initial.advance(True)
    cfg = Settings.model_validate(initial.setup.state().config)
    with pytest.raises(SetupProblem) as raised:
        SetupChecks(initial.directory, httpx.MockTransport(handler)).llm(cfg, {}, initial.setup.prompts(
            initial.setup.state()))
    assert raised.value.code == code


def test_openrouter_transport_errors_are_general_codes(initial):
    checks, cfg, prompts = router(initial, lambda request: (_ for _ in ()).throw(httpx.ConnectError(SECRET)))
    with pytest.raises(SetupProblem, match="^network$"):
        checks.llm(cfg, initial.setup.environment(), prompts)


@pytest.mark.parametrize(("error", "code"), [
    (OAuthTokenError(SECRET), "google.token_expired"), (AuthenticationError(SECRET), "target.auth_failed"),
    (CalendarAccessError(SECRET), "target.not_found"), (ExternalUnavailable(SECRET), "network"),
    (TargetAccessError(SECRET, reason="forbidden"), "target.permission"),
    (CalendarAccessError(SECRET, reason="api_disabled"), "target.api_disabled"),
    (ExternalRefused(SECRET), "target.permission"), (httpx.ConnectTimeout(SECRET), "timeout"),
])
def test_target_failures_name_the_target_and_their_cause(initial, monkeypatch, error, code):
    initial.advance()
    cfg = Settings.model_validate(initial.setup.state().config)
    closed = []

    def broken():
        raise error
    writers = SimpleNamespace(calendar=SimpleNamespace(check_access=broken),
                              tasks=SimpleNamespace(check_access=lambda: None), close=lambda: closed.append(1))
    monkeypatch.setattr(module, "build_writers", lambda *args, **kwargs: writers)
    with pytest.raises(SetupProblem) as raised:
        SetupChecks(initial.directory).targets(cfg, initial.setup.environment())
    assert raised.value.code == code and raised.value.detail == "Kalender: google" and closed == [1]
    assert SECRET not in str(raised.value)
    cfg.targets.task_provider = "microsoft_todo"
    monkeypatch.setattr(module, "setup_secrets", lambda *args: None)
    writers.calendar.check_access, writers.tasks.check_access = (lambda: None), (
        lambda: (_ for _ in ()).throw(OAuthTokenError(SECRET)))
    with pytest.raises(SetupProblem, match="target.auth_failed"):
        SetupChecks(initial.directory).targets(cfg, initial.setup.environment())
