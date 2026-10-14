"""Bounded independent probes with sanitized errors and session-bound execution."""
import imaplib
import json
import ssl
from datetime import UTC, datetime
from threading import Event

import httpx
import pytest

from mailhelp.adapter import PermanentError
from mailhelp.diagnostics import DiagnosticResult, DiagnosticsService, error_code
from mailhelp.storage import JsonStore


@pytest.mark.parametrize("exc,code", [
    (ssl.SSLError("secret"), "tls"), (TimeoutError(), "timeout"), (httpx.ReadTimeout("secret"), "timeout"),
    (imaplib.IMAP4.error("secret"), "auth"), (PermissionError(), "permission"),
    (ConnectionError(), "network"), (httpx.ConnectError("secret"), "network"),
    (ValueError("secret"), "configuration"), (PermanentError("secret"), "permission"),
    (RuntimeError("secret"), "service"),
])
def test_error_classification_never_uses_provider_text(exc, code):
    assert error_code(exc) == code


@pytest.mark.parametrize("status,code", [(401, "auth"), (403, "permission"), (500, "service")])
def test_http_error_codes(status, code):
    request = httpx.Request("GET", "https://synthetic.test")
    assert error_code(httpx.HTTPStatusError("secret", request=request, response=httpx.Response(status))) == code


def test_checks_fail_independently_and_do_not_leak_raw_content(tmp_path, monkeypatch):
    calls = []
    def failed(actor):
        raise ValueError("token=SECRET; mail subject; C:/private; https://push.test/full-endpoint")
    svc = DiagnosticsService(JsonStore(tmp_path), lambda actor: actor == "active",
                             {"imap": failed, "calendar": lambda actor: calls.append(actor) or ("ready", "")})
    svc.run("active", "imap", 0, "probe-0001")
    svc.run("active", "calendar", 1, "probe-0002")
    assert calls == ["active"]
    svc.run("active", "calendar", 1, "probe-0002")
    assert calls == ["active"]
    state = svc.state()
    assert state.results["imap"].code == "configuration" and state.results["calendar"].status == "ready"
    for value in (json.dumps(svc.report()), (tmp_path / "diagnostics-state.json").read_text()):
        assert not any(secret in value for secret in ("SECRET", "mail subject", "private", "full-endpoint"))
    monkeypatch.setattr("mailhelp.diagnostics.platform.system", lambda: "Linux")
    assert svc.report()["platform"] == "Linux"
    monkeypatch.setattr("mailhelp.diagnostics.platform.system", lambda: "Windows")
    assert svc.report()["platform"] == "Windows"
    with pytest.raises(PermissionError):
        svc.run("revoked", "imap", 2, "probe-0003")
    for name, version, key in (("unknown", 2, "probe-0003"), ("imap", 2, "bad"),
                               ("imap", 1, "probe-0004"), ("imap", 1, "probe-0002")):
        with pytest.raises(ValueError):
            svc.run("active", name, version, key)


def test_timeout_does_not_block_other_components_or_accept_late_success(tmp_path):
    release, entered = Event(), Event()
    def slow(actor):
        entered.set()
        release.wait(2)
        return "ready", ""
    svc = DiagnosticsService(JsonStore(tmp_path), lambda actor: True,
                             {"imap": slow, "todoist": lambda actor: ("ready", "")}, timeout=.03)
    svc.run("active", "imap", 0, "probe-0001")
    assert entered.is_set() and svc.state().results["imap"].code == "timeout"
    svc.run("active", "todoist", 1, "probe-0002")
    assert svc.state().results["todoist"].status == "ready"
    with pytest.raises(ValueError):
        svc.run("active", "imap", 2, "probe-0003")
    release.set()
    assert svc.state().results["imap"].code == "timeout"


def test_revocation_before_worker_execution_and_restart_discard_authorization(tmp_path):
    store = JsonStore(tmp_path)
    store.save("diagnostics-state", {"schema_version": 1, "version": 0,
               "results": {"imap": DiagnosticResult(status="running").model_dump(mode="json"),
                           "todoist": DiagnosticResult(status="ready").model_dump(mode="json")}, "operations": {}})
    authorizations = iter([True, False])
    svc = DiagnosticsService(store, lambda actor: next(authorizations),
                             {"imap": lambda actor: pytest.fail("revoked session must not run network probe")})
    assert svc.state().results["imap"].code == "interrupted"
    svc.run("active", "imap", 0, "probe-0001")
    assert svc.state().results["imap"].code == "unauthorized"


def test_diagnostic_replay_history_is_bounded(tmp_path):
    svc = DiagnosticsService(JsonStore(tmp_path), lambda actor: True, {"imap": lambda actor: ("ready", "")})
    state = svc.state()
    state.operations = {f"a:key-{index:08d}": "imap:0" for index in range(500)}
    svc.store.save("diagnostics-state", state.model_dump(mode="json"))
    svc.run("active", "imap", 0, "probe-new1")
    assert len(svc.state().operations) == 500 and "a:key-00000000" not in svc.state().operations


def test_a_config_change_during_a_probe_cannot_confirm_the_new_draft(tmp_path):
    revision = {"current": "a" * 64}
    def probe(actor):
        revision["current"] = "b" * 64
        return "ready", ""
    svc = DiagnosticsService(JsonStore(tmp_path), lambda actor: True, {"imap": probe},
                             revision=lambda: revision["current"])
    svc.run("active", "imap", 0, "probe-0001")
    result = svc.state().results["imap"]
    assert result.config_revision == "a" * 64 and result.status == "failed" and result.code == "configuration"
