"""Provider choice: configuration, secrets, writer factory and Microsoft sign-in (Planung 2.3, 3.4/4.6/7)."""
import sys

import httpx
import pytest
from pydantic import ValidationError
from shared_application import settings
from shared_core import shipped_configuration

from mailhelp import cli
from mailhelp.config import Secrets, TargetSettings, load_all, provider_secret_names
from mailhelp.external.caldav import AppleReminders, CalDavCalendar, CalDavTasks
from mailhelp.external.contracts import OAuthTokenError
from mailhelp.external.http_writer import HttpWriter
from mailhelp.external.microsoft import MicrosoftTodo, MicrosoftTokenProvider, OutlookCalendar
from mailhelp.external.providers import Writers, build_writers, provider_services
from mailhelp.external.roles import CALENDAR_SLOT, TASK_SLOT, slot

DAV = "https://dav.example.test/calendars/anna/"
SECRETS = Secrets(imap={1: {"username": "u", "password": "p"}}, openrouter_api_key="o", todoist_token="t",
                  google_oauth_client_id="gi", google_oauth_client_secret="gs", google_oauth_refresh_token="gr",
                  caldav_username="anna", caldav_password="app", microsoft_client_id="mi")


def configured(tmp_path, **targets):
    cfg = settings(tmp_path)
    data = {**cfg.targets.model_dump(), **targets}
    cfg.targets = TargetSettings.model_validate(data)
    return cfg


def test_google_and_todoist_remain_the_default(tmp_path):
    cfg = configured(tmp_path)
    assert (cfg.targets.calendar_provider, cfg.targets.task_provider) == ("google", "todoist")
    assert (cfg.targets.calendar_target, cfg.targets.task_target) == ("c", "p")
    built = build_writers(cfg, SECRETS, tmp_path)
    assert isinstance(built.calendar, HttpWriter) and built.calendar.service == "google_calendar"
    assert isinstance(built.tasks, HttpWriter) and built.tasks.service == "todoist"
    assert built.slots == {TASK_SLOT: built.tasks, CALENDAR_SLOT: built.calendar}
    assert [slot(built.calendar), slot(built.tasks)] == [CALENDAR_SLOT, TASK_SLOT]
    assert (built.calendar.label, built.tasks.label) == ("Google Kalender", "Todoist")
    assert provider_services(cfg.targets) == ["Todoist", "Google Kalender", "Google-Anmeldung"]
    built.close()


def test_caldav_writers_share_the_app_password_and_respect_the_timeout_cap(tmp_path):
    cfg = configured(tmp_path, calendar_provider="caldav", task_provider="caldav", caldav_calendar_url=DAV + "p/",
                     caldav_task_url=DAV + "t/")
    policies = []
    built = build_writers(cfg, SECRETS, tmp_path, timeout_cap=5,
                          policy=lambda name: policies.append(name) or None)
    assert isinstance(built.calendar, CalDavCalendar) and isinstance(built.tasks, CalDavTasks)
    assert built.calendar.target == DAV + "p/" and built.tasks.target == DAV + "t/"
    assert built.calendar.client.timeout.read == 5 and built.calendar.client.auth is not None
    assert policies == ["caldav", "caldav"] and built.resources == []
    assert built.calendar.fetch_active_tasks() == []
    assert provider_services(cfg.targets) == ["CalDAV-Aufgaben", "CalDAV-Kalender"]
    built.close()


def test_microsoft_writers_share_one_token_provider(tmp_path):
    cfg = configured(tmp_path, calendar_provider="outlook", task_provider="microsoft_todo",
                     microsoft_tenant="organizations")
    built = build_writers(cfg, SECRETS, tmp_path)
    assert isinstance(built.calendar, OutlookCalendar) and isinstance(built.tasks, MicrosoftTodo)
    assert built.calendar.token is built.tasks.token and isinstance(built.resources[0], MicrosoftTokenProvider)
    assert str(built.resources[0]._client.base_url).startswith(
        "https://login.microsoftonline.com/organizations/oauth2/v2.0")
    assert (built.calendar.target, built.tasks.target) == ("default", "default")
    assert provider_services(cfg.targets) == ["Microsoft To Do", "Outlook-Kalender", "Microsoft-Anmeldung"]
    built.close()


def test_apple_reminders_with_google_calendar(tmp_path):
    url = "https://p52-caldav.icloud.com/123/calendars/erinnerungen/"
    cfg = configured(tmp_path, task_provider="apple_reminders", caldav_task_url=url)
    built = build_writers(cfg, SECRETS, tmp_path)
    assert isinstance(built.tasks, AppleReminders) and built.tasks.target == url == cfg.targets.task_target
    assert provider_services(cfg.targets) == ["Apple Erinnerungen", "Google Kalender", "Google-Anmeldung"]
    built.close()


def test_writers_close_every_resource():
    closed = []

    class Closing:
        def __init__(self, name):
            self.name = name

        def close(self):
            closed.append(self.name)

    Writers(Closing("calendar"), Closing("tasks"), [Closing("token")]).close()
    assert closed == ["tasks", "calendar", "token"]


@pytest.mark.parametrize(("changes", "message"), [
    ({"google_calendar": ""}, "google_calendar wird"),
    ({"todoist_project": ""}, "todoist_project wird"),
    ({"calendar_provider": "caldav"}, "caldav_calendar_url"),
    ({"calendar_provider": "caldav", "caldav_calendar_url": "http://dav.example.test/x/"}, "caldav_calendar_url"),
    ({"calendar_provider": "caldav", "caldav_calendar_url": "ftp://x/"}, "caldav_calendar_url"),
    ({"task_provider": "caldav", "caldav_task_url": "https://dav example/"}, "caldav_task_url"),
    ({"task_provider": "apple_reminders", "caldav_task_url": DAV}, "caldav.icloud.com"),
    ({"outlook_calendar": "a b"}, "outlook_calendar"),
    ({"microsoft_tenant": "../x"}, "microsoft_tenant"),
    ({"calendar_provider": "exchange"}, "calendar_provider")])
def test_invalid_targets_are_rejected(changes, message):
    with pytest.raises(ValidationError, match=message):
        TargetSettings.model_validate({"todoist_project": "p", "google_calendar": "c", **changes})


def test_local_plain_http_is_allowed_for_a_local_server():
    targets = TargetSettings.model_validate({"todoist_project": "p", "calendar_provider": "caldav",
                                             "caldav_calendar_url": "http://localhost:5232/anna/k/"})
    assert targets.calendar_target == "http://localhost:5232/anna/k/" and not targets.uses_microsoft
    assert TargetSettings.model_validate({"google_calendar": "c", "task_provider": "caldav",
                                          "caldav_task_url": "http://127.0.0.1/a/"}).uses_caldav


def test_secrets_are_required_only_for_configured_providers(tmp_path):
    env = shipped_configuration(tmp_path)
    assert load_all(tmp_path, env)[1].todoist_token.get_secret_value() == "secret"
    config = tmp_path / "config.yaml"
    text = config.read_text(encoding="utf-8")
    for old, new in (("calendar_provider: google", "calendar_provider: outlook"),
                     ("task_provider: todoist", "task_provider: caldav"),
                     ('caldav_task_url: ""', f"caldav_task_url: {DAV}")):
        assert old in text
        text = text.replace(old, new, 1)
    config.write_text(text, encoding="utf-8")
    without = {key: value for key, value in env.items() if not key.startswith(("GOOGLE", "TODOIST"))}
    with pytest.raises(ValueError, match="CALDAV_USERNAME, CALDAV_PASSWORD, MICROSOFT_CLIENT_ID"):
        load_all(tmp_path, without)
    complete = {**without, "CALDAV_USERNAME": "anna", "CALDAV_PASSWORD": "app", "MICROSOFT_CLIENT_ID": "mi",
                "MICROSOFT_REFRESH_TOKEN": "seed"}
    loaded = load_all(tmp_path, complete)[1]
    assert loaded.microsoft_refresh_token.get_secret_value() == "seed"
    assert loaded.microsoft_client_secret.get_secret_value() == "" and loaded.todoist_token.get_secret_value() == ""
    assert provider_secret_names(TargetSettings(todoist_project="p", google_calendar="c")) == [
        "TODOIST_TOKEN", "TODOIST_CLIENT_ID", "TODOIST_CLIENT_SECRET", "GOOGLE_OAUTH_CLIENT_ID",
        "GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_OAUTH_REFRESH_TOKEN"]


def test_target_writer_default_create_runs_the_prepared_write(tmp_path):
    from shared_write_improvements import event
    cfg = configured(tmp_path, calendar_provider="caldav", caldav_calendar_url=DAV)
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(201)

    built = build_writers(cfg, SECRETS, tmp_path, transport=httpx.MockTransport(handler))
    result = built.calendar.create(event(status="confirmed", target=DAV), "mailhelp:" + "a" * 24 + ":p1:v1")
    assert result["id"].startswith(DAV + "mailhelp-") and requests[-1].method == "PUT"
    built.close()


def run_cli(monkeypatch, tmp_path, secrets):
    loaded = (settings(tmp_path), secrets, [], [], None, "f")
    monkeypatch.setattr(cli, "load_all", lambda directory: loaded)
    monkeypatch.setattr(cli, "build_application", lambda *args, **kwargs: pytest.fail("no application"))
    monkeypatch.setattr(sys, "argv", ["mailhelp", "--microsoft-login", "--config-directory", str(tmp_path)])
    return cli.main()


def test_cli_microsoft_login(monkeypatch, tmp_path, capsys):
    assert run_cli(monkeypatch, tmp_path, Secrets(imap={1: {"username": "u", "password": "p"}},
                                                  openrouter_api_key="o")) == 1
    assert "MICROSOFT_CLIENT_ID fehlt" in capsys.readouterr().err
    logins = []

    def device_login(self, show):
        logins.append(self._tokens.path)
        show("Öffne https://microsoft.com/devicelogin und gib den Code X ein.")

    monkeypatch.setattr(MicrosoftTokenProvider, "device_login", device_login)
    assert run_cli(monkeypatch, tmp_path, SECRETS) == 0
    assert logins == [tmp_path / "microsoft-token.json"] and "Code X" in capsys.readouterr().out

    def refused(self, show):
        raise OAuthTokenError("Microsoft-Anmeldung nicht abgeschlossen")

    monkeypatch.setattr(MicrosoftTokenProvider, "device_login", refused)
    assert run_cli(monkeypatch, tmp_path, SECRETS) == 1
    assert "FEHLER: Microsoft-Anmeldung nicht abgeschlossen" in capsys.readouterr().err
