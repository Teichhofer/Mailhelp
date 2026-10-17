"""The IServ connection can be checked and activated from one form, without external writes."""
from __future__ import annotations

import pytest
import yaml
from shared_decision_test import secrets

from mailhelp.config import Secrets
from mailhelp.iserv import IServSignInError

ROUTE = "/einstellungen/iserv"
ACTIVATE = ROUTE + "/aktivieren"
VALUES = {"id": "1", "label": "Schule", "server": "schule.example", "mailbox": "1",
          "historical_start": "01.09.2026", "username": "synthetic-parent", "password": "synthetic-password"}


class Reader:
    calls = []
    error = None

    def __init__(self, account, credentials, *args, **kwargs):
        self.account = account
        Reader.calls.append((account.id, credentials.username, credentials.password.get_secret_value()))

    def check_access(self):
        if Reader.error:
            raise Reader.error

    def close(self):
        Reader.calls.append("closed")


@pytest.fixture
def activation(profiled, monkeypatch):
    Reader.calls, Reader.error = [], None
    monkeypatch.setattr("mailhelp.iserv.IServReader", Reader)
    for name in ("ISERV_1_USERNAME", "ISERV_1_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    profiled.runtime.secrets = Secrets.model_validate(secrets().model_dump())
    profiled.reloads = []
    from types import SimpleNamespace
    profiled.app.iserv_runtime = SimpleNamespace(request=lambda cfg, keys: profiled.reloads.append((cfg, keys)))
    return profiled


def form(ctx):
    return {**ctx.web.form(ROUTE, action=ACTIVATE), **VALUES}


def test_regression_one_form_checks_saves_and_starts_the_account(activation):
    ctx = activation
    submitted = form(ctx)
    response = ctx.web.browser.request("POST", ACTIVATE, submitted)
    assert response.status == 303
    cfg = yaml.safe_load((ctx.tmp_path / "config.yaml").read_text())
    assert cfg["iserv"]["accounts"][0]["server"] == "https://schule.example"
    assert cfg["iserv"]["accounts"][0]["historical_start"] == "2026-09-01T00:00:00Z"
    assert Reader.calls == [(1, VALUES["username"], VALUES["password"]), "closed"]
    assert len(ctx.reloads) == 1
    assert ctx.reloads[0][1].iserv[1].username == VALUES["username"]
    for path in ctx.web.store.directory.glob("*.json"):
        assert VALUES["password"] not in path.read_text()
    assert ctx.web.writer.created == 0
    assert ctx.web.browser.request("POST", ACTIVATE, submitted).status == 303
    assert len(ctx.reloads) == 1 and len(Reader.calls) == 2
    page = ctx.web.browser.request("GET", ROUTE + "?aktiviert=1").body.decode()
    assert "ohne Neustart" in page and VALUES["password"] not in page


def test_failed_connection_keeps_config_and_secrets_unchanged(activation):
    ctx = activation
    before = (ctx.tmp_path / "config.yaml").read_bytes()
    Reader.error = IServSignInError("must-never-show-synthetic-password")
    response = ctx.web.browser.request("POST", ACTIVATE, form(ctx))
    assert response.status == 422
    assert "Anmeldung" in response.body.decode()
    assert "must-never-show" not in response.body.decode()
    assert (ctx.tmp_path / "config.yaml").read_bytes() == before
    assert not (ctx.tmp_path / ".env").exists() and not ctx.reloads
    assert Reader.calls[-1] == "closed"


@pytest.mark.parametrize(("changes", "status"), [
    ({"csrf": "bad"}, 403), ({"version": "99"}, 409), ({"revision": "0" * 64}, 409),
    ({"env_revision": "0" * 64}, 409), ({"key": "bad"}, 422), ({"id": "x"}, 422),
    ({"server": "http://school.example"}, 422), ({"mailbox": "9"}, 422),
    ({"username": "", "password": ""}, 422), ({"historical_start": "31.09.2026"}, 422),
])
def test_invalid_or_stale_forms_do_not_start_a_connection(activation, changes, status):
    ctx = activation
    before = (ctx.tmp_path / "config.yaml").read_bytes()
    assert ctx.web.browser.request("POST", ACTIVATE, {**form(ctx), **changes}).status == status
    assert not Reader.calls and not ctx.reloads
    assert (ctx.tmp_path / "config.yaml").read_bytes() == before


@pytest.mark.parametrize("when", ["before", "after_probe", "before_write", "repeat"])
def test_session_is_checked_again_before_execution(activation, monkeypatch, when):
    ctx = activation
    submitted = form(ctx)
    if when == "repeat":
        assert ctx.web.browser.request("POST", ACTIVATE, submitted).status == 303
    if when == "after_probe":
        monkeypatch.setattr(Reader, "check_access", lambda self: monkeypatch.setattr(
            ctx.web.auth, "active", lambda session: False))
    elif when == "before_write":
        original = ctx.web.store.save
        def save(name, value):
            original(name, value)
            if name.startswith("iserv-activation-"):
                monkeypatch.setattr(ctx.web.auth, "active", lambda session: False)
        monkeypatch.setattr(ctx.web.store, "save", save)
    else:
        monkeypatch.setattr(ctx.web.auth, "active", lambda session: False)
    assert ctx.web.browser.request("POST", ACTIVATE, submitted).status == 403
    assert len(ctx.reloads) == (1 if when == "repeat" else 0)


def test_saved_credentials_are_reused_and_unrelated_drafts_are_preserved(activation):
    ctx = activation
    from mailhelp.setup import SetupState
    pending = {"id": 2, "server": "https://other.example", "label": "Andere Schule", "mailbox": 1,
               "enabled": True, "historical_start": None}
    state = SetupState(version=3, patch={"timezone": "Europe/Berlin", "iserv.accounts": [pending]})
    ctx.web.store.save("setup-state", state.model_dump(mode="json"))
    (ctx.tmp_path / ".env").write_text("# keep\nOTHER=value\nISERV_1_USERNAME=saved-user\nISERV_1_PASSWORD=saved-pw\n")
    submitted = {**form(ctx), "username": "", "password": ""}
    assert ctx.web.browser.request("POST", ACTIVATE, submitted).status == 303
    assert Reader.calls[0] == (1, "saved-user", "saved-pw")
    cfg = yaml.safe_load((ctx.tmp_path / "config.yaml").read_text())
    assert [item["id"] for item in cfg["iserv"]["accounts"]] == [1]
    state = ctx.runtime.setup.state()
    assert state.patch["timezone"] == "Europe/Berlin"
    assert [item["id"] for item in state.patch["iserv.accounts"]] == [2, 1]
    assert ctx.runtime.setup.draft_settings().timezone == "Europe/Berlin"
    assert "# keep\nOTHER=value" in (ctx.tmp_path / ".env").read_text()
    # A new service after restart reads the persisted config and credentials.
    from mailhelp.setup_runtime import SetupRuntime
    restarted = SetupRuntime(ctx.app, ctx.web.site, ctx.runtime.secrets)
    assert restarted.credentials(restarted.setup.draft_settings()).iserv[1].username == "saved-user"


def test_activating_the_existing_iserv_draft_clears_only_that_change(activation):
    ctx = activation
    from mailhelp.config import IServAccountSettings
    from mailhelp.setup import SetupState
    account = IServAccountSettings(id=1, server="schule.example", label="Schule")
    state = SetupState(patch={"iserv.accounts": [account.model_dump(mode="json")]})
    ctx.web.store.save("setup-state", state.model_dump(mode="json"))
    assert ctx.web.browser.request("POST", ACTIVATE, {**form(ctx), "historical_start": ""}).status == 303
    assert ctx.runtime.setup.state().patch == {}
    assert ctx.web.browser.request("GET", ROUTE).status == 200


def test_reactivating_a_saved_account_uses_existing_credentials_without_duplicates(activation):
    ctx = activation
    assert ctx.web.browser.request("POST", ACTIVATE, form(ctx)).status == 303
    submitted = {**form(ctx), "username": "", "password": "", "label": "Neue Bezeichnung"}
    assert ctx.web.browser.request("POST", ACTIVATE, submitted).status == 303
    saved = yaml.safe_load((ctx.tmp_path / "config.yaml").read_text())["iserv"]["accounts"]
    assert len(saved) == 1 and saved[0]["label"] == "Neue Bezeichnung"
    assert len(ctx.reloads) == 2


@pytest.mark.parametrize("change", ["file", "env", "draft"])
def test_changes_during_connection_check_prevent_activation(activation, monkeypatch, change):
    ctx = activation
    submitted = form(ctx)
    def check(reader):
        if change == "file":
            with (ctx.tmp_path / "config.yaml").open("a") as stream:
                stream.write("\n# concurrent edit\n")
        elif change == "env":
            (ctx.tmp_path / ".env").write_text("OTHER=concurrent\n")
        else:
            state = ctx.runtime.setup.state()
            state.version += 1
            ctx.runtime.setup._save(state)
    monkeypatch.setattr(Reader, "check_access", check)
    assert ctx.web.browser.request("POST", ACTIVATE, submitted).status == 409
    assert not ctx.reloads


def test_current_draft_hash_and_matching_process_credentials_are_accepted(activation, monkeypatch):
    from mailhelp.configuration import file_hash
    ctx = activation
    monkeypatch.setenv("ISERV_1_USERNAME", VALUES["username"])
    monkeypatch.setenv("ISERV_1_PASSWORD", VALUES["password"])
    state = ctx.runtime.setup.state()
    state.base_hash = file_hash(ctx.tmp_path / "config.yaml")
    ctx.runtime.setup._save(state)
    assert ctx.web.browser.request("POST", ACTIVATE, form(ctx)).status == 303


def test_changed_draft_base_is_rejected_without_rendering_the_stale_page(activation):
    ctx = activation
    submitted = form(ctx)
    state = ctx.runtime.setup.state()
    state.base_hash = "0" * 64
    ctx.runtime.setup._save(state)
    assert ctx.web.browser.request("POST", ACTIVATE, submitted).status == 409


def test_the_page_distinguishes_draft_saved_and_running_accounts(activation):
    from mailhelp.config import IServSettings
    from mailhelp.setup import SetupState
    ctx = activation
    account = {"id": 1, "server": "https://schule.example", "label": "Schule", "mailbox": 1}
    ctx.web.store.save("setup-state", SetupState(patch={"iserv.accounts": [account]}).model_dump(mode="json"))
    assert "Entwurf – noch nicht aktiviert" in ctx.web.browser.request("GET", ROUTE).body.decode()
    assert ctx.web.browser.request("POST", ACTIVATE, form(ctx)).status == 303
    assert "gespeichert – Aktivierung ausstehend" in ctx.web.browser.request("GET", ROUTE).body.decode()
    ctx.app.configuration.active.iserv = IServSettings.model_validate(
        yaml.safe_load((ctx.tmp_path / "config.yaml").read_text())["iserv"])
    html = ctx.web.browser.request("GET", ROUTE).body.decode()
    assert "Aktivierung ausstehend" not in html and "Postfach 1 · aktiv" in html


@pytest.mark.parametrize("failure", ["missing_keys", "environment", "probe", "write", "config", "other_draft"])
def test_activation_failures_are_safe_and_recoverable(activation, monkeypatch, failure):
    ctx = activation
    submitted = form(ctx)
    if failure == "missing_keys":
        ctx.runtime.secrets = None
    elif failure == "environment":
        monkeypatch.setenv("ISERV_1_PASSWORD", "process-password")
    elif failure == "probe":
        Reader.error = RuntimeError("never-display-secret")
    elif failure == "write":
        monkeypatch.setattr("mailhelp.iserv_activation.set_values", lambda *args: (_ for _ in ()).throw(OSError()))
    elif failure == "config":
        from mailhelp.review.results import ResultStatus, ReviewResult
        monkeypatch.setattr("mailhelp.iserv_activation.ConfigurationService.execute",
                            lambda *args: ReviewResult(status=ResultStatus.STALE, message="changed"))
    else:
        from mailhelp.setup import SetupState
        ctx.web.store.save("setup-state", SetupState(kind="topics").model_dump(mode="json"))
    response = ctx.web.browser.request("POST", ACTIVATE, submitted)
    assert response.status == (409 if failure in {"config", "other_draft"} else 422)
    assert "never-display-secret" not in response.body.decode()
    assert not ctx.reloads and ctx.web.writer.created == 0
    if failure in {"write", "config"}:
        # A partially written operation is not executed twice with the same key.
        assert ctx.web.browser.request("POST", ACTIVATE, submitted).status == 409


def test_same_key_cannot_activate_another_account(activation):
    ctx = activation
    submitted = form(ctx)
    assert ctx.web.browser.request("POST", ACTIVATE, submitted).status == 303
    assert ctx.web.browser.request("POST", ACTIVATE, {**submitted, "label": "Changed"}).status == 409
    assert len(ctx.reloads) == 1


def test_no_activation_without_runtime(activation):
    ctx = activation
    submitted = form(ctx)
    ctx.web.site.setup_page.runtime = None
    assert ctx.web.browser.request("POST", ACTIVATE, submitted).status == 503


def test_double_click_during_the_probe_activates_only_once(activation, monkeypatch):
    ctx = activation
    submitted = form(ctx)
    entered = False
    def check(reader):
        nonlocal entered
        if not entered:
            entered = True
            assert ctx.web.browser.request("POST", ACTIVATE, submitted).status == 303
    monkeypatch.setattr(Reader, "check_access", check)
    assert ctx.web.browser.request("POST", ACTIVATE, submitted).status == 303
    assert len(ctx.reloads) == 1


def test_a_non_iserv_draft_is_preserved(activation):
    from mailhelp.setup import SetupState
    ctx = activation
    ctx.web.store.save("setup-state", SetupState(patch={"timezone": "Europe/Berlin"}).model_dump(mode="json"))
    assert ctx.web.browser.request("POST", ACTIVATE, form(ctx)).status == 303
    assert ctx.runtime.setup.draft_settings().timezone == "Europe/Berlin"
