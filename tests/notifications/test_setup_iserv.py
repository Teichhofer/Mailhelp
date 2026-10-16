"""IServ credentials in the setup overview and the IServ diagnosis (3.3.8); synthetic data only."""
from __future__ import annotations

import pytest
import yaml
from pydantic import SecretStr

from mailhelp.config import Secrets
from mailhelp.iserv import IServError, IServSignInError

NAMES = "ISERV_1_USERNAME/ISERV_1_PASSWORD"


def with_accounts(configured, *accounts):
    path = configured.tmp_path / "config.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["iserv"] = {"accounts": list(accounts)}
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")


def secrets(**iserv):
    return Secrets(imap={1: {"username": "u", "password": "p"}}, openrouter_api_key=SecretStr("o"),
                   iserv=iserv)


@pytest.fixture
def no_env(monkeypatch):
    for name in ("ISERV_1_USERNAME", "ISERV_1_PASSWORD"):
        monkeypatch.delenv(name, raising=False)


def test_setup_lists_the_credentials_of_every_enabled_iserv_account(configured, no_env):
    """Regression: the credentials overview did not mention IServ at all."""
    runtime = configured.runtime
    assert NAMES not in runtime.secret_status()
    with_accounts(configured, {"id": 1, "server": "https://schule.example"},
                  {"id": 2, "server": "https://andere.example", "enabled": False})
    assert runtime.secret_status()[NAMES] == "fehlt"
    assert "ISERV_2_USERNAME/ISERV_2_PASSWORD" not in runtime.secret_status()
    runtime.secrets = secrets()
    assert runtime.secret_status()[NAMES] == "fehlt"
    (configured.tmp_path / ".env").write_text("ISERV_1_USERNAME=eltern\nISERV_1_PASSWORD=geheim\n", encoding="utf-8")
    assert runtime.secret_status()[NAMES] == "vorhanden"
    page = configured.web.browser.request("GET", "/einrichtung").body.decode()
    assert f"{NAMES}: vorhanden" in page and "geheim" not in page


class Reader:
    error: Exception | None = None
    seen: list = []

    def __init__(self, account, credentials, timezone, max_bytes, *, max_attachment_bytes):
        Reader.seen.append((account.id, credentials.username, timezone, max_bytes))

    def check_access(self):
        if Reader.error is not None:
            raise Reader.error

    def close(self):
        Reader.seen.append("closed")


def test_iserv_diagnosis_signs_in_without_reading_letters(configured, monkeypatch, no_env):
    runtime = configured.runtime
    monkeypatch.setattr("mailhelp.iserv.IServReader", Reader)
    Reader.seen, Reader.error = [], None
    assert runtime.iserv("device") == ("disabled", "")
    with_accounts(configured, {"id": 1, "server": "https://schule.example"})
    assert runtime.iserv("device") == ("failed", "auth")
    runtime.secrets = secrets()
    assert runtime.iserv("device") == ("failed", "auth") and Reader.seen == []
    runtime.secrets = secrets(**{"1": {"username": "eltern", "password": "geheim"}})
    assert runtime.iserv("device") == ("ready", "")
    assert Reader.seen == [(1, "eltern", configured.cfg.timezone, configured.cfg.limits.max_mail_bytes), "closed"]
    Reader.error = IServSignInError("abgelehnt")
    assert runtime.iserv("device") == ("failed", "auth") and Reader.seen[-1] == "closed"
    Reader.error = IServError("HTTP-Status 500")
    with pytest.raises(IServError):
        runtime.iserv("device")
    assert Reader.seen[-1] == "closed"
    assert "iserv" in runtime.diagnostics.checks
