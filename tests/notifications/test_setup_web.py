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
    original = (configured.tmp_path / "config.yaml").read_text(encoding="utf-8")
    for path in ("/einrichtung", "/diagnose", "/einstellungen/benachrichtigungen"):
        response = web.browser.request("GET", path)
        assert response.status == 200 and "secret" not in response.body.decode().lower()
    form = web.form("/einrichtung", action="/einrichtung/speichern", name="imap.drafts_folder")
    assert web.browser.request("POST", "/einrichtung/speichern", {**form, "value": "Entwürfe"}).status == 303
    assert runtime.setup.configuration.active.imap.configured_mailboxes()[0].drafts_folder == "Drafts"
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
    # The session was revoked before execution: config.yaml stays exactly as it was.
    assert (configured.tmp_path / "config.yaml").read_text(encoding="utf-8") == original
    assert web.writer.created == 0 and web.writer.reconciled == 0


MAILBOX_CONFIG = """imap:
  mailboxes:
  - id: 1   # privat
    label: Privat
    host: h
    port: 993
    folders: [INBOX]
"""


def test_wizard_edits_the_mailboxes_of_the_3_1_format(configured):
    """Planung 3.1: the setup step shows every mailbox and writes into its list entry."""
    web, runtime = configured.web, configured.runtime
    path = configured.tmp_path / "config.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw.pop("imap")
    path.write_text(MAILBOX_CONFIG + yaml.safe_dump(raw), encoding="utf-8")
    page = web.browser.request("GET", "/einrichtung").body.decode()
    assert "Entwurfsordner – Postfach 1 (Privat)" in page and 'value="Drafts"' in page
    assert '<option value="starttls">' in page
    form = web.form("/einrichtung", action="/einrichtung/speichern", name="imap.mailboxes.0.drafts_folder")
    assert web.browser.request("POST", "/einrichtung/speichern", {**form, "value": "Entwürfe"}).status == 303
    assert runtime.setup.draft_settings().imap.mailboxes[0].drafts_folder == "Entwürfe"
    # A list position that does not exist is not offered, even with a valid field name.
    state = runtime.setup.state()
    actor = "web:" + web.auth.sessions()[0].id
    with pytest.raises(ValueError, match="Nicht angebotene"):
        runtime.setup.save(actor, state.version, "missing-mailbox", 2, {"imap.mailboxes.4.host": "x"})
    runtime.diagnostics.checks["imap"] = lambda actor: ("limited", "draft_readonly")
    check = web.form("/diagnose", action="/diagnose/pruefen", name="imap")
    assert web.browser.request("POST", "/diagnose/pruefen", check).status == 303
    form = web.form("/einrichtung", action="/einrichtung/uebernehmen")
    assert web.browser.request("POST", "/einrichtung/uebernehmen", {**form, "confirm": "yes"}).status == 303
    web.run()
    content = path.read_text(encoding="utf-8")
    assert "# privat" in content
    assert yaml.safe_load(content)["imap"]["mailboxes"][0]["drafts_folder"] == "Entwürfe"


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
    def reader(settings, secrets, mailbox):
        yield NS(list_folders=lambda: [NS(name=name) for name in ["INBOX", "Drafts"]],
                 check_access=lambda folders: calls.append(folders))
    monkeypatch.setattr("mailhelp.setup_runtime._reader", reader)
    # Credentials are read at start; a mailbox without them cannot be checked yet.
    assert runtime.imap(session) == ("failed", "auth") and calls == []
    runtime.secrets = NS(imap={1: object()})
    assert runtime.imap(session) == ("limited", "draft_readonly")
    assert calls == [["INBOX", "Drafts"]]
    assert configured.app.store.load("setup-folders")["mailboxes"] == {"1": ["INBOX", "Drafts"]}
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


def test_setup_offers_the_providers_with_defaults_for_a_2_2_configuration(configured):
    path = configured.tmp_path / "config.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    for name in ("calendar_provider", "task_provider", "caldav_calendar_url", "caldav_task_url",
                 "outlook_calendar", "microsoft_todo_list", "microsoft_tenant"):
        raw["targets"].pop(name)
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    page = configured.web.browser.request("GET", "/einrichtung").body.decode()
    assert '<option value="google" selected>google</option>' in page
    assert '<option value="apple_reminders">apple_reminders</option>' in page
    assert 'name="value" value="default"' in page and "Microsoft-Mandant" in page


def test_target_probes_use_draft_targets_own_clients_and_close_on_failure(configured, monkeypatch):
    from pydantic import SecretStr

    from mailhelp.external.providers import Writers
    calls = []

    class Adapter:
        fail = False

        def __init__(self, name):
            self.name = name

        def close(self):
            calls.append(f"{self.name} closed")

        def check_access(self):
            calls.append(f"{self.name} checked")
            if self.fail:
                raise PermissionError("synthetic refused")

    class Token:
        def close(self):
            calls.append("token closed")

    def build(cfg, secrets, directory, *, timeout_cap):
        calls.append((cfg.targets.calendar_target, cfg.targets.task_target, directory, timeout_cap))
        return Writers(Adapter("calendar"), Adapter("tasks"), [Token()])

    monkeypatch.setattr("mailhelp.setup_runtime.build_writers", build)
    secrets = NS(imap={1: object()}, **{name: SecretStr("synthetic") for name in (
        "openrouter_api_key", "telegram_bot_token", "todoist_token", "todoist_client_id",
        "todoist_client_secret", "google_oauth_refresh_token", "google_oauth_client_id",
        "google_oauth_client_secret", "caldav_username", "caldav_password", "microsoft_client_id")})
    runtime = SetupRuntime(configured.app, configured.web.site, secrets)
    actor = "web:" + configured.web.auth.sessions()[0].id
    runtime.setup.save(actor, 0, "target-001", 3, {"targets.google_calendar": "new-calendar",
                                                  "targets.todoist_project": "new-project"})
    assert runtime.calendar("device") == runtime.todoist("device") == ("ready", "")
    directory = configured.app.configuration.directory
    assert calls[0] == ("new-calendar", "new-project", directory, 10)
    assert calls[1:5] == ["calendar checked", "tasks closed", "calendar closed", "token closed"]
    assert "tasks checked" in calls and calls.count("token closed") == 2
    assert set(runtime.secret_status().values()) == {"vorhanden"}
    Adapter.fail = True
    with pytest.raises(PermissionError):
        runtime.calendar("device")
    assert calls[-3:] == ["tasks closed", "calendar closed", "token closed"]
    # Only the secrets of the configured providers are listed.
    runtime.setup.save(actor, 1, "target-002", 3, {"targets.caldav_task_url": "https://dav.example.org/tasks/",
                                                  "targets.task_provider": "caldav"})
    assert "caldav_password" in runtime.secret_status() and "todoist_token" not in runtime.secret_status()
    runtime.setup.save(actor, 2, "target-003", 3, {"targets.calendar_provider": "outlook"})
    assert "microsoft_client_id" in runtime.secret_status()
    assert "google_oauth_refresh_token" not in runtime.secret_status()


@pytest.mark.parametrize("kind", ["local", "csrf"])
def test_regression_non_ascii_authentication_tokens_are_rejected_without_server_error(web, kind):
    message = f"{int(time.time())}:" + "a" * 32
    if kind == "local":
        assert web.browser.request("POST", "/api/local-pair", {
            "message": message, "signature": "ungültig"}).status == 403
    else:
        assert web.browser.request("POST", "/einrichtung/speichern", {"csrf": "ungültig"}).status == 403
        assert web.auth.csrf_valid(web.auth.sessions()[0].id, "ungültig") is False


TWO_MAILBOXES = MAILBOX_CONFIG + """  - id: 2
    label: Arbeit
    host: b
    port: 993
    folders: [INBOX, Projekte]
"""


def test_diagnosis_checks_every_mailbox_and_offers_its_own_folders(configured, monkeypatch):
    web, runtime = configured.web, configured.runtime
    path = configured.tmp_path / "config.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw.pop("imap")
    path.write_text(TWO_MAILBOXES + yaml.safe_dump(raw), encoding="utf-8")
    folders = {"h": ["INBOX", "Drafts"], "b": ["INBOX", "Drafts", "Projekte", "Archiv"]}
    checked = []

    @contextmanager
    def reader(settings, secrets, mailbox):
        yield NS(list_folders=lambda: [NS(name=name) for name in folders[mailbox.host]],
                 check_access=lambda required: checked.append((mailbox.id, required)))
    monkeypatch.setattr("mailhelp.setup_runtime._reader", reader)
    from pydantic import SecretStr
    runtime.secrets = NS(imap={1: object(), 2: object()}, openrouter_api_key=SecretStr("o"),
                         telegram_bot_token=SecretStr(""), todoist_token=SecretStr("t"),
                         google_oauth_refresh_token=SecretStr("g"))
    assert runtime.imap("device") == ("limited", "draft_readonly")
    assert checked == [(1, ["INBOX", "Drafts"]), (2, ["INBOX", "Projekte", "Drafts"])]
    page = web.browser.request("GET", "/einrichtung").body.decode()
    assert "Postfach 1: INBOX, Drafts; Postfach 2: INBOX, Drafts, Projekte, Archiv" in page
    assert '<option value="Archiv">' in page and "Anzeigename – Postfach 2 (Arbeit)" in page
    # A failing second mailbox fails the check, the folders of the first stay offered.
    folders["b"] = ["INBOX"]
    assert runtime.imap("device") == ("failed", "configuration")
    assert configured.app.store.load("setup-folders")["mailboxes"] == {"1": ["INBOX", "Drafts"], "2": ["INBOX"]}
