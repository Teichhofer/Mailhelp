"""Authenticated no-JavaScript forms, explicit probes and local CLI entry."""
import json
import time
from contextlib import contextmanager
from types import SimpleNamespace as NS

import httpx
import pytest
import yaml
from shared_application import settings
from shared_core import prompt_config
from shared_web_auth import SECRET

from mailhelp.configuration import ConfigurationService
from mailhelp.local_pairing import issue, signature
from mailhelp.notification_runtime import NotificationRuntime
from mailhelp.setup_runtime import SetupRuntime
from mailhelp.web.auth import PairingLimited
from mailhelp.web.setup_site import input_field


def test_all_new_routes_require_authentication_and_csrf(web):
    for path in ("/einrichtung", "/diagnose", "/diagnose/bericht", "/benachrichtigungen",
                 "/einstellungen/benachrichtigungen"):
        assert web.browser.request("GET", path).status == 503
    for path in ("/einrichtung/speichern", "/einrichtung/uebernehmen", "/diagnose/pruefen"):
        assert web.browser.request("POST", path, {"csrf": "wrong"}).status == 403
        csrf = web.auth.csrf_token(web.auth.sessions()[0].id)
        assert web.browser.request("POST", path, {"csrf": csrf}).status == 503
    web.auth.revoke_all()
    for path in ("/einrichtung", "/diagnose", "/diagnose/bericht", "/benachrichtigungen",
                 "/einstellungen/benachrichtigungen"):
        assert web.browser.request("GET", path).status == 303


def test_wizard_draft_review_queue_and_session_recheck(configured):
    web, runtime = configured.web, configured.runtime
    for path in ("/einrichtung", "/diagnose", "/einstellungen/benachrichtigungen"):
        response = web.browser.request("GET", path)
        assert response.status == 200 and "secret" not in response.body.decode().lower()
    form = web.form("/einrichtung", action="/einrichtung/speichern", name="imap.drafts_folder")
    assert web.browser.request("POST", "/einrichtung/speichern", {**form, "value": "Entwürfe"}).status == 303
    assert runtime.setup.configuration.active.imap.drafts_folder == "Drafts"
    runtime.diagnostics.checks["imap"] = lambda actor: ("limited", "draft_readonly")
    check = web.form("/diagnose", action="/diagnose/pruefen", name="imap")
    assert web.browser.request("POST", "/diagnose/pruefen", check).status == 303
    review = web.browser.request("GET", "/einrichtung").body.decode()
    assert "Entwürfe" in review and "Neustart erforderlich" in review
    form = web.form("/einrichtung", action="/einrichtung/uebernehmen")
    assert web.browser.request("POST", "/einrichtung/uebernehmen", form).status == 422
    response = web.browser.request("POST", "/einrichtung/uebernehmen", {**form, "confirm": "yes"})
    assert response.status == 303
    assert web.browser.request("POST", "/einrichtung/uebernehmen", {**form, "confirm": "yes"}).status == 303
    assert len(web.commands.queued()) == 1
    web.auth.revoke_all()
    web.run()
    assert yaml.safe_load((configured.tmp_path / "config.yaml").read_text(encoding="utf-8"))["imap"]["drafts_folder"] == "Drafts"
    assert web.writer.created == 0 and web.writer.reconciled == 0


def test_form_errors_and_conflicts_do_not_activate_settings(configured):
    web = configured.web
    original = web.form("/einrichtung", action="/einrichtung/speichern", name="timezone")
    for change in ({"version": "x"}, {"value": "invalid"}, {"name": "IMAP_PASSWORD", "value": "secret"},
                   {"step": "7"}):
        assert web.browser.request("POST", "/einrichtung/speichern", {**original, "value": "UTC", **change}).status == 422
    assert web.browser.request("POST", "/einrichtung/speichern", {**original, "value": "UTC"}).status == 303
    assert web.browser.request("POST", "/einrichtung/speichern", {**original, "key": "other-001", "value": "UTC"}).status == 409
    apply = web.form("/einrichtung", action="/einrichtung/uebernehmen")
    assert web.browser.request("POST", "/einrichtung/uebernehmen", {**apply, "version": "0", "confirm": "yes"}).status == 409
    assert web.browser.request("POST", "/einrichtung/uebernehmen", {**apply, "version": "x", "confirm": "yes"}).status == 422
    assert web.browser.request("POST", "/einrichtung/uebernehmen", {**apply, "confirm": "yes"}).status == 303
    web.run()
    assert configured.app.configuration.active.timezone == configured.cfg.timezone


def test_profile_displays_only_available_technical_channels_and_content_consent(configured):
    web, cfg = configured.web, configured.cfg
    page = web.browser.request("GET", "/einstellungen/benachrichtigungen").body.decode()
    assert "Betreffzeilen" in page and "Web-Push ist immer neutral" in page
    assert "[&quot;telegram&quot;]" in page and "[&quot;web_push&quot;]" not in page
    configured.runtime.setup.configuration.active = cfg
    cfg.push.enabled = True
    path = configured.tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg.model_dump(mode="json")), encoding="utf-8")
    page = web.browser.request("GET", "/einstellungen/benachrichtigungen").body.decode()
    assert "[&quot;telegram&quot;, &quot;web_push&quot;]" in page
    cfg.telegram.enabled = False
    path.write_text(yaml.safe_dump(cfg.model_dump(mode="json")), encoding="utf-8")
    page = web.browser.request("GET", "/einstellungen/benachrichtigungen").body.decode()
    assert "[&quot;web_push&quot;]" in page and "[&quot;telegram&quot;]" not in page


def test_diagnose_actions_are_explicit_versioned_and_report_is_sanitized(configured):
    web = configured.web
    form = web.form("/diagnose", action="/diagnose/pruefen", name="telegram_test")
    before = list(web.telegram.sent)
    web.browser.request("GET", "/diagnose")
    assert web.telegram.sent == before
    assert web.browser.request("POST", "/diagnose/pruefen", form).status == 303
    assert len(web.telegram.sent) == len(before) + 1
    assert web.browser.request("POST", "/diagnose/pruefen", form).status == 303
    assert len(web.telegram.sent) == len(before) + 1
    assert web.browser.request("POST", "/diagnose/pruefen", {**form, "name": "unknown"}).status == 409
    assert web.browser.request("POST", "/diagnose/pruefen", {**form, "version": "x"}).status == 409
    response = web.browser.request("GET", "/diagnose/bericht")
    assert response.status == 200 and "attachment" in response.headers["Content-Disposition"]
    report = json.loads(response.body)
    assert report["components"]["telegram_test"]["status"] == "ready"
    assert SECRET.encode() not in response.body and "state" not in report


def test_runtime_readonly_probes_and_synthetic_tests(configured, monkeypatch):
    runtime, cfg = configured.runtime, configured.cfg
    session = configured.web.auth.sessions()[0].id
    calls = []
    @contextmanager
    def reader(settings, secrets):
        yield NS(list_folders=lambda: [NS(name=name) for name in ["INBOX", "Drafts"]],
                 check_access=lambda folders: calls.append(folders))
    monkeypatch.setattr("mailhelp.setup_runtime._reader", reader)
    assert runtime.imap(session) == ("limited", "draft_readonly")
    assert calls == [["INBOX", "Drafts"]]
    cfg.imap.drafts_folder = "missing"
    (configured.tmp_path / "config.yaml").write_text(yaml.safe_dump(cfg.model_dump(mode="json")), encoding="utf-8")
    assert runtime.imap(session) == ("failed", "configuration")
    assert runtime.calendar(session) == runtime.todoist(session) == runtime.llm(session) == ("ready", "")
    assert runtime.filesystem(session) == ("ready", "")
    assert not list(configured.app.store.directory.glob("diagnostic-*"))
    assert runtime.telegram(session) == ("ready", "")
    cfg.telegram.enabled = False
    assert runtime.telegram(session) == runtime.telegram_test(session) == ("disabled", "")
    assert runtime.push(session) == runtime.push_test(session) == ("disabled", "")
    cfg.push.enabled = True
    assert runtime.push(session) == ("limited", "browser")
    assert runtime.push_test(session) == ("disabled", "")
    configured.web.site.experience.push = NS(destinations=lambda: [], deliver=lambda *args: calls.append(args))
    assert runtime.push_test(session) == ("limited", "browser")
    configured.web.site.experience.push.destinations = lambda: ["a" * 16 + ":" + "b" * 64, session + ":" + "c" * 64]
    assert runtime.push(session) == runtime.push_test(session) == ("ready", "")
    assert calls[-1] == (session + ":" + "c" * 64, "test")
    assert runtime.llm_test(session) == ("disabled", "configuration")
    from mailhelp.config import PromptStep
    configured.app.analyzer.prompts.prompts["diagnostic_test"] = PromptStep(system_prompt="synthetic")
    configured.app.openrouter.complete = lambda *args, **kw: calls.append((args, kw))
    assert runtime.llm_test(session) == ("ready", "")
    assert calls[-1][0][3] == {"synthetic": True} and calls[-1][1] == {"stage": "diagnostic_test"}
    monkeypatch.setattr("mailhelp.setup_runtime.Path.read_text", lambda *args, **kw: "corrupt")
    assert runtime.filesystem(session) == ("failed", "service")


def test_local_pairing_requires_host_secret_expiry_and_one_time_use(web, monkeypatch):
    message = f"{int(time.time())}:" + "a" * 32
    assert web.browser.request("POST", "/api/local-pair", {"message": message, "signature": "bad"}).status == 403
    response = web.browser.request("POST", "/api/local-pair", {"message": message, "signature": signature(SECRET, message)})
    assert response.status == 200 and len(json.loads(response.body)["code"]) == 4
    assert web.browser.request("POST", "/api/local-pair", {"message": message, "signature": signature(SECRET, message)}).status == 403
    for message in ("bad", "0:" + "b" * 32, f"{int(time.time())}:short"):
        with pytest.raises(PermissionError):
            issue(web.auth, message, signature(SECRET, message))
    monkeypatch.setattr(web.auth, "issue_code", lambda: (_ for _ in ()).throw(PairingLimited()))
    message = f"{int(time.time())}:" + "c" * 32
    assert web.browser.request("POST", "/api/local-pair", {"message": message, "signature": signature(SECRET, message)}).status == 429
    assert web.browser.request("POST", "/api/local-pair", {}, **{"content-type": "text/plain"}).status == 415


def test_cli_pairing_uses_local_address_prints_code_and_skips_other_services(configured, monkeypatch, capsys):
    from mailhelp import cli
    from mailhelp.local_pairing import request_local_code
    calls = []
    class Client:
        def __init__(self, **kw):
            assert kw == {"trust_env": False, "timeout": 10}
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def post(self, url, data):
            calls.append((url, data))
            return httpx.Response(200, json={"code": "1234"}, request=httpx.Request("POST", url))
    monkeypatch.setattr("mailhelp.local_pairing.httpx.Client", Client)
    monkeypatch.setenv("MAILHELP_WEB_SECRET", SECRET)
    request_local_code(configured.tmp_path)
    assert "Einmalcode: 1234" in capsys.readouterr().out
    assert calls[0][0].startswith("http://127.0.0.1:")
    assert calls[0][1]["signature"] == signature(SECRET, calls[0][1]["message"])
    monkeypatch.setattr("sys.argv", ["mailhelp", "--pair", "--config-directory", str(configured.tmp_path)])
    assert cli.main() == 0
    for code in (1234, "invalid"):
        monkeypatch.setattr(Client, "post", lambda self, url, data, code=code: httpx.Response(
            200, json={"code": code}, request=httpx.Request("POST", url)))
        with pytest.raises(ValueError, match="Einmalcode"):
            request_local_code(configured.tmp_path)
    monkeypatch.delenv("MAILHELP_WEB_SECRET")
    with pytest.raises(ValueError):
        request_local_code(configured.tmp_path)


def test_markup_escapes_untrusted_values_and_console_entry_issues_no_code(web):
    assert "&lt;script&gt;" in input_field("unsafe", "<script>")
    assert 'selected' in input_field("telegram.enabled", True)
    web.auth.channel = "console"
    from shared_web_auth import Browser
    browser = Browser(web.app)
    csrf = browser.csrf()
    before = web.store.load("web-pairing")
    response = browser.request("POST", "/anmelden/code", {"csrf": csrf})
    assert response.status == 200 and "mailhelp --pair" in response.body.decode()
    assert web.store.load("web-pairing") == before


def test_refresh_and_diagnostic_staleness_are_visible(configured):
    web = configured.web
    check = web.form("/diagnose", action="/diagnose/pruefen", name="llm")
    assert web.browser.request("POST", "/diagnose/pruefen", check).status == 303
    refresh = web.form("/einrichtung", action="/einrichtung/speichern", refresh="yes")
    assert web.browser.request("POST", "/einrichtung/speichern", refresh).status == 303
    form = web.form("/einrichtung", action="/einrichtung/speichern", name="timezone")
    assert web.browser.request("POST", "/einrichtung/speichern", {**form, "value": "Europe/Berlin"}).status == 303
    assert "Lokale Konfiguration" in web.browser.request("GET", "/diagnose").body.decode()
    assert "wird geprüft" not in web.browser.request("GET", "/diagnose").body.decode()


def test_target_probes_use_draft_targets_own_clients_and_close_on_failure(configured, monkeypatch):
    from pydantic import SecretStr
    calls = []
    class Token:
        def __init__(self, *args):
            calls.append(("token", args))
        def close(self):
            calls.append("token closed")
    class Adapter:
        fail = False
        def __init__(self, service, token, target, timeout, **kw):
            calls.append((service, target, timeout, kw))
        def close(self):
            calls.append("adapter closed")
        def check_access(self):
            if self.fail:
                raise PermissionError("synthetic refused")
    monkeypatch.setattr("mailhelp.setup_runtime.HttpWriter", Adapter)
    monkeypatch.setattr("mailhelp.setup_runtime.GoogleOAuthTokenProvider", Token)
    secrets = NS(**{name: SecretStr("synthetic") for name in (
        "imap_password", "openrouter_api_key", "telegram_bot_token", "todoist_token",
        "google_oauth_refresh_token", "google_oauth_client_id", "google_oauth_client_secret")})
    runtime = SetupRuntime(configured.app, configured.web.site, secrets)
    actor = "web:" + configured.web.auth.sessions()[0].id
    runtime.setup.save(actor, 0, "target-001", 3, {"targets.google_calendar": "new-calendar",
                                                  "targets.todoist_project": "new-project"})
    assert runtime.calendar("device") == runtime.todoist("device") == ("ready", "")
    assert ("google_calendar", "new-calendar", 10, {"calendar_timezone": "UTC"}) in calls
    assert ("todoist", "new-project", 10, {"calendar_timezone": "UTC"}) in calls
    assert calls.count("token closed") == 1 and calls.count("adapter closed") == 2
    assert set(runtime.secret_status().values()) == {"vorhanden"}
    Adapter.fail = True
    with pytest.raises(PermissionError):
        runtime.calendar("device")
    assert calls[-2:] == ["adapter closed", "token closed"]


@pytest.mark.parametrize("kind", ["local", "csrf"])
def test_regression_non_ascii_authentication_tokens_are_rejected_without_server_error(web, kind):
    message = f"{int(time.time())}:" + "a" * 32
    if kind == "local":
        assert web.browser.request("POST", "/api/local-pair", {
            "message": message, "signature": "ungültig"}).status == 403
    else:
        assert web.browser.request("POST", "/einrichtung/speichern", {"csrf": "ungültig"}).status == 403
        assert web.auth.csrf_valid(web.auth.sessions()[0].id, "ungültig") is False
