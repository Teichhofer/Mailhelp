"""OAuth CLI dispatch is profile-bound and cannot start mail processing."""
import sys

import pytest
import yaml
from shared_core import prompt_config
from shared_decision_test import secrets
from shared_profiles import TOPICS, settings

from mailhelp import cli
from mailhelp.config import load_all
from mailhelp.external.contracts import OAuthTokenError


@pytest.mark.parametrize("args", [["--profile", "0"], ["--profile", "100"], ["--profile", "2"],
    ["--google-auth", "--microsoft-login"], ["--google-auth", "--profile", "99"]])
def test_invalid_profile_modes_stop_before_services(tmp_path, monkeypatch, args):
    monkeypatch.setattr(sys, "argv", ["mailhelp", *args])
    monkeypatch.setattr(cli, "load_all", lambda *a, **kw: (settings(tmp_path), secrets(), TOPICS, [], prompt_config(), "f" * 64))
    with pytest.raises(SystemExit):
        cli.main()


@pytest.mark.parametrize("failed", [False, True])
def test_google_login_dispatch_never_prints_tokens_or_builds_application(tmp_path, monkeypatch, capsys, failed):
    monkeypatch.setattr(sys, "argv", ["mailhelp", "--google-auth", "--profile", "2"])
    calls = []
    creds = secrets().model_copy(update={"profiles": {2: {"google_oauth_refresh_token": secrets().google_oauth_refresh_token}}})
    def load(*args, **kwargs):
        assert kwargs == {"oauth_profile": 2}
        return settings(tmp_path), creds, TOPICS, [], prompt_config(), "f" * 64
    monkeypatch.setattr(cli, "load_all", load)
    def login(credentials, directory, number):
        calls.append(number)
        assert credentials.todoist_token.get_secret_value() == ""
        if failed:
            raise OAuthTokenError("Synthetisch fehlgeschlagen")
    monkeypatch.setattr("mailhelp.google_login.login", login)
    assert cli.main() == int(failed) and calls == [2]
    assert "synthetic" not in capsys.readouterr().out


def test_microsoft_cli_uses_selected_profile_vault(tmp_path, monkeypatch):
    from types import SimpleNamespace as NS
    cfg = settings(tmp_path)
    creds = secrets().model_copy(update={"profiles": {2: {"microsoft_client_id": secrets().microsoft_client_id}}})
    calls = []
    def tokens(cfg, secret, directory, timeout, **kw):
        assert kw == {"profile_id": 2} and cfg.targets.calendar_provider == "outlook"
        return NS(device_login=lambda _: calls.append("login"), close=lambda: calls.append("close"))
    monkeypatch.setattr("mailhelp.external.providers.microsoft_tokens", tokens)
    assert cli._microsoft_login(cfg, creds, tmp_path, 2) == 0 and calls == ["login", "close"]
    monkeypatch.setattr(cli, "load_all", lambda *args: (cfg, creds, TOPICS, [], prompt_config(), "f" * 64))
    monkeypatch.setattr(sys, "argv", ["mailhelp", "--microsoft-login", "--profile", "2"])
    assert cli.main() == 0


def test_google_initial_login_requires_all_other_secrets_but_not_its_own_refresh(tmp_path):
    cfg = settings(tmp_path, profiles=False)
    for name, data in (("config.yaml", cfg.model_dump(mode="json")), ("prompts.yaml", prompt_config().model_dump()),
        ("topics.yaml", {"topics": [topic.model_dump(mode="json") for topic in TOPICS]}), ("irrelevant_topics.yaml", {"topics": []})):
        (tmp_path / name).write_text(yaml.safe_dump(data), encoding="utf-8")
    env = {name.upper(): value.get_secret_value() for name, value in secrets() if hasattr(value, "get_secret_value")}
    env.update(IMAP_1_USERNAME="one", IMAP_1_PASSWORD="one-pass", IMAP_2_USERNAME="two", IMAP_2_PASSWORD="two-pass")
    env.pop("GOOGLE_OAUTH_REFRESH_TOKEN")
    with pytest.raises(ValueError, match="GOOGLE_OAUTH_REFRESH_TOKEN"):
        load_all(tmp_path, env)
    assert load_all(tmp_path, env, oauth_profile=1)[1].google_oauth_refresh_token.get_secret_value() == ""
    cfg.target_profiles = settings(tmp_path).target_profiles
    cfg.imap.mailboxes[1].target_profile = 2
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(cfg.model_dump(mode="json")))
    env["GOOGLE_OAUTH_REFRESH_TOKEN"] = "one-refresh"
    assert load_all(tmp_path, env, oauth_profile=2)[1].profiles[2]["microsoft_client_id"]
