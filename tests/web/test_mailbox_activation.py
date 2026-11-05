"""One authenticated, read-only check before persisting and scheduling an IMAP mailbox."""
from types import SimpleNamespace as NS

import pytest
import yaml

from mailhelp.config import MAX_MAILBOXES, ImapSettings, Secrets, Settings
from mailhelp.mailbox.imap import FolderNotReadable
from mailhelp.runtime.setup import SetupState
from tests.fakes.shared_decision_test import secrets

ROUTE = "/einstellungen/postfaecher"
ACTIVATE = ROUTE + "/aktivieren"
VALUES = {"id": "3", "label": "Verein", "host": "imap.example.test", "port": "993",
          "connection_mode": "ssl", "folders": "INBOX, Archiv", "drafts_folder": "Drafts",
          "historical_start": "01.09.2026", "username": "synthetic-user", "password": "synthetic-password"}


class Reader:
    calls = []
    folders = []
    error = None

    def __init__(self, *args, **kwargs):
        Reader.calls.append((args, kwargs))

    def close(self):
        Reader.calls.append("closed")

    def list_folders(self):
        return [NS(name=name) for name in Reader.folders]

    def check_access(self, folders):
        Reader.calls.append(folders)
        if Reader.error:
            raise Reader.error


@pytest.fixture
def activation(profiled, monkeypatch):
    Reader.calls, Reader.error, Reader.folders = [], None, ["INBOX", "Archiv", "Drafts"]
    monkeypatch.setattr("mailhelp.runtime.experience.ImapReader", Reader)
    for number in range(1, 12):
        for suffix in ("USERNAME", "PASSWORD"):
            monkeypatch.delenv(f"IMAP_{number}_{suffix}", raising=False)
    profiled.runtime.secrets = Secrets.model_validate(secrets().model_dump())
    profiled.reloads = []
    profiled.app.mailbox_runtime = NS(request=lambda cfg, keys: profiled.reloads.append((cfg, keys)))
    return profiled


def form(ctx):
    return {**ctx.web.form(ROUTE, action=ACTIVATE), **VALUES}


def test_check_save_retry_and_restart(activation):
    ctx = activation
    submitted = form(ctx)
    assert ctx.web.browser.request("POST", ACTIVATE, submitted).status == 303
    cfg = Settings.model_validate(yaml.safe_load((ctx.tmp_path / "config.yaml").read_text()))
    box = cfg.imap.mailbox(3)
    assert box.label == "Verein" and box.folders == ["INBOX", "Archiv"]
    assert box.historical_start.isoformat() == "2026-09-01T00:00:00+00:00"
    assert Reader.calls[0][0][:4] == (VALUES["host"], 993, VALUES["username"], VALUES["password"])
    assert Reader.calls[1:] == [["INBOX", "Archiv", "Drafts"], "closed"]
    assert len(ctx.reloads) == 1 and ctx.app.settings.imap.mailbox(3) is None
    assert ctx.web.browser.request("POST", ACTIVATE, submitted).status == 303
    assert len(ctx.reloads) == 1 and len(Reader.calls) == 3
    from mailhelp.runtime.setup_runtime import SetupRuntime
    restarted = SetupRuntime(ctx.app, ctx.web.site, ctx.runtime.secrets)
    assert restarted.credentials(cfg).imap[3].username == VALUES["username"]
    for path in ctx.web.store.directory.glob("*.json"):
        assert VALUES["password"] not in path.read_text()
    assert ctx.web.writer.created == 0
    page = ctx.web.browser.request("GET", ROUTE + "?aktiviert=1").body.decode()
    assert "ohne Neustart" in page and "gespeichert – Aktivierung ausstehend" in page


@pytest.mark.parametrize(("changes", "status"), [
    ({"csrf": "bad"}, 403), ({"version": "99"}, 409), ({"revision": "0" * 64}, 409),
    ({"env_revision": "0" * 64}, 409), ({"key": "bad"}, 422), ({"id": "x"}, 422),
    ({"port": "0"}, 422), ({"folders": ""}, 422), ({"drafts_folder": "\n"}, 422),
    ({"username": "", "password": ""}, 422), ({"historical_start": "31.09.2026"}, 422),
    ({"id": "1"}, 422), ({"connection_mode": "bad"}, 422),
])
def test_invalid_or_stale_forms_never_connect(activation, changes, status):
    ctx = activation
    before = (ctx.tmp_path / "config.yaml").read_bytes()
    assert ctx.web.browser.request("POST", ACTIVATE, {**form(ctx), **changes}).status == status
    assert not Reader.calls and not ctx.reloads
    assert (ctx.tmp_path / "config.yaml").read_bytes() == before
    assert not (ctx.tmp_path / ".env").exists()


@pytest.mark.parametrize(("folders", "error", "message"), [
    ([], None, "Vorhandene Ordner: keine"),
    ([f"Ordner-{n}" for n in range(31)], None, "Ordner-29 …"),
    (["INBOX", "Archiv"], None, "Ordner nicht gefunden: Drafts"),
    (["INBOX", "Archiv", "Drafts"], FolderNotReadable("Archiv"), "Ordner nicht lesbar: Archiv"),
    (["INBOX", "Archiv", "Drafts"], OSError("private-secret"), "Server nicht erreichbar"),
    (["INBOX", "Archiv", "Drafts"], RuntimeError("private-secret"), "Anmeldung abgelehnt"),
])
def test_probe_failures_preserve_inputs_without_secrets(activation, folders, error, message):
    ctx = activation
    Reader.folders, Reader.error = folders, error
    before = (ctx.tmp_path / "config.yaml").read_bytes()
    response = ctx.web.browser.request("POST", ACTIVATE, form(ctx))
    assert response.status == 422 and message in response.body.decode()
    assert 'value="imap.example.test"' in response.body.decode()
    assert 'type="password" name="password" value=""' in response.body.decode()
    assert "private-secret" not in response.body.decode() and VALUES["password"] not in response.body.decode()
    assert (ctx.tmp_path / "config.yaml").read_bytes() == before
    assert not (ctx.tmp_path / ".env").exists() and not ctx.reloads
    assert Reader.calls[-1] == "closed"


@pytest.mark.parametrize("enabled", [True, False])
def test_duplicate_account_is_rejected_before_connection(activation, enabled):
    ctx = activation
    if not enabled:
        cfg = ctx.cfg.model_copy(deep=True)
        cfg.imap.mailbox(1).enabled = False
        (ctx.tmp_path / "config.yaml").write_text(yaml.safe_dump(cfg.model_dump(mode="json")))
    ctx.runtime.secrets.imap[1] = ctx.runtime.secrets.imap[1].model_copy(update={"username": VALUES["username"]})
    response = ctx.web.browser.request("POST", ACTIVATE, {**form(ctx), "host": ctx.cfg.imap.mailbox(1).host})
    assert response.status == 422 and "bereits als Postfach 1" in response.body.decode()
    assert not Reader.calls and not ctx.reloads


def test_disabled_account_credentials_are_checked_even_if_not_loaded_at_start(activation):
    ctx = activation
    cfg = ctx.cfg.model_copy(deep=True)
    cfg.imap.mailbox(1).enabled = False
    (ctx.tmp_path / "config.yaml").write_text(yaml.safe_dump(cfg.model_dump(mode="json")))
    del ctx.runtime.secrets.imap[1]
    (ctx.tmp_path / ".env").write_text("IMAP_1_USERNAME=synthetic-user\nIMAP_1_PASSWORD=stored-password\n")
    response = ctx.web.browser.request("POST", ACTIVATE, {**form(ctx), "host": ctx.cfg.imap.mailbox(1).host})
    assert response.status == 422 and "bereits als Postfach 1" in response.body.decode()
    assert not Reader.calls and not ctx.reloads


@pytest.mark.parametrize("when", ["before", "after_probe", "before_write", "repeat"])
def test_authorization_is_rechecked_at_execution(activation, monkeypatch, when):
    ctx = activation
    submitted = form(ctx)
    if when == "repeat":
        assert ctx.web.browser.request("POST", ACTIVATE, submitted).status == 303
    if when == "after_probe":
        monkeypatch.setattr(Reader, "check_access", lambda *args: monkeypatch.setattr(ctx.web.auth, "active", lambda _: False))
    elif when == "before_write":
        save = ctx.web.store.save
        def expire(name, value):
            save(name, value)
            if name.startswith("mailbox-activation-"):
                monkeypatch.setattr(ctx.web.auth, "active", lambda _: False)
        monkeypatch.setattr(ctx.web.store, "save", expire)
    else:
        monkeypatch.setattr(ctx.web.auth, "active", lambda _: False)
    assert ctx.web.browser.request("POST", ACTIVATE, submitted).status == 403
    assert len(ctx.reloads) == (1 if when == "repeat" else 0)


@pytest.mark.parametrize("change", ["file", "env", "draft"])
def test_concurrent_changes_prevent_writes(activation, monkeypatch, change):
    ctx = activation
    submitted = form(ctx)
    def mutate(*args):
        if change == "file":
            with (ctx.tmp_path / "config.yaml").open("a") as stream:
                stream.write("\n# concurrent\n")
        elif change == "env":
            (ctx.tmp_path / ".env").write_text("OTHER=concurrent\n")
        else:
            state = ctx.runtime.setup.state()
            state.version += 1
            ctx.runtime.setup._save(state)
    monkeypatch.setattr(Reader, "check_access", mutate)
    assert ctx.web.browser.request("POST", ACTIVATE, submitted).status == 409
    assert not ctx.reloads


@pytest.mark.parametrize("failure", ["keys", "environment", "write", "config", "other_draft", "missing_field"])
def test_failed_activation_is_safe_and_recoverable(activation, monkeypatch, failure):
    ctx = activation
    submitted = form(ctx)
    if failure == "keys":
        ctx.runtime.secrets = None
    elif failure == "environment":
        monkeypatch.setenv("IMAP_3_PASSWORD", "other-process-secret")
    elif failure == "write":
        def fail(*args):
            raise OSError("private-secret")
        monkeypatch.setattr("mailhelp.mailbox.connection_activation.set_values", fail)
    elif failure == "config":
        from mailhelp.review.results import ResultStatus, ReviewResult
        monkeypatch.setattr("mailhelp.mailbox.connection_activation.ConfigurationService.execute",
                            lambda *args: ReviewResult(status=ResultStatus.STALE, message="changed"))
    elif failure == "other_draft":
        ctx.web.store.save("setup-state", SetupState(kind="topics").model_dump(mode="json"))
    else:
        del submitted["port"]
    response = ctx.web.browser.request("POST", ACTIVATE, submitted)
    assert response.status == (409 if failure in {"config", "other_draft"} else 422)
    assert "private-secret" not in response.body.decode() and not ctx.reloads
    if failure in {"config", "write"}:
        assert ctx.web.browser.request("POST", ACTIVATE, submitted).status == 409


def test_existing_credentials_draft_rebase_and_blank_label(activation, monkeypatch):
    ctx = activation
    (ctx.tmp_path / ".env").write_text("# keep\nIMAP_3_USERNAME=saved-user\nIMAP_3_PASSWORD=saved-pw\n")
    monkeypatch.setenv("IMAP_3_PASSWORD", "saved-pw")
    state = SetupState(patch={"timezone": "Europe/Berlin", "imap.mailboxes": [
        *(box.model_dump(mode="json") for box in ctx.cfg.imap.configured_mailboxes()),
        {"id": 3, "host": VALUES["host"], "port": 993, "folders": ["INBOX"]}]})
    ctx.runtime.setup._save(state)
    page = ctx.web.browser.request("GET", ROUTE).body.decode()
    assert "Entwurf – noch nicht aktiviert" in page
    assert ctx.web.browser.request("POST", ACTIVATE, {**form(ctx), "username": "", "password": "",
                                                     "label": "", "historical_start": ""}).status == 303
    assert Reader.calls[0][0][2:4] == ("saved-user", "saved-pw")
    assert ctx.runtime.setup.state().patch == {"timezone": "Europe/Berlin"}
    assert ctx.runtime.setup.draft_settings().imap.mailbox(3).label == "Postfach 3"
    assert "# keep" in (ctx.tmp_path / ".env").read_text()


def test_limit_and_missing_runtime(activation):
    ctx = activation
    boxes = [ctx.cfg.imap.mailbox(1).model_copy(update={"id": n}) for n in range(1, MAX_MAILBOXES + 1)]
    cfg = ctx.cfg.model_copy(update={"imap": ImapSettings(mailboxes=boxes)})
    (ctx.tmp_path / "config.yaml").write_text(yaml.safe_dump(cfg.model_dump(mode="json")))
    assert "bereits 10 Postfächer" in ctx.web.browser.request("GET", ROUTE).body.decode()
    submitted = {**VALUES, "id": "11", "version": "1", "key": "limit-0001", "csrf": ctx.web.browser.csrf(ROUTE),
                 "revision": "", "env_revision": ""}
    from mailhelp.configuration import file_hash
    from mailhelp.runtime.env_file import file_hash as env_hash
    submitted.update(revision=file_hash(ctx.tmp_path / "config.yaml"), env_revision=env_hash(ctx.tmp_path / ".env"),
                     version=str(ctx.runtime.setup.state().version))
    assert ctx.web.browser.request("POST", ACTIVATE, submitted).status == 422
    ctx.web.site.setup_page.runtime = None
    assert ctx.web.browser.request("POST", ACTIVATE, submitted).status == 503


def test_legacy_configuration_is_migrated_without_losing_the_old_mailbox(configured, monkeypatch):
    from mailhelp.config import Secrets
    ctx = configured
    Reader.calls, Reader.error, Reader.folders = [], None, ["INBOX", "Archiv", "Drafts"]
    monkeypatch.setattr("mailhelp.runtime.experience.ImapReader", Reader)
    ctx.runtime.secrets = Secrets.model_validate(secrets().model_dump())
    ctx.app.mailbox_runtime = NS(request=lambda *args: None)
    assert ctx.web.browser.request("POST", ACTIVATE, {**form(ctx), "id": "2"}).status == 303
    cfg = Settings.model_validate(yaml.safe_load((ctx.tmp_path / "config.yaml").read_text()))
    assert not cfg.imap.legacy_format and cfg.imap.mailbox(1) == ctx.cfg.imap.mailbox(1)
    assert cfg.imap.mailbox(2).host == VALUES["host"]


def test_card_states_and_stored_credentials_hint(activation):
    ctx = activation
    boxes = [box.model_dump(mode="json") for box in ctx.cfg.imap.configured_mailboxes()]
    boxes[0]["label"] = "Geändert"
    boxes[1]["enabled"] = False
    ctx.runtime.setup._save(SetupState(patch={"imap.mailboxes": boxes}))
    (ctx.tmp_path / ".env").write_text("IMAP_3_USERNAME=saved\nIMAP_3_PASSWORD=pw\n")
    page = ctx.web.browser.request("GET", ROUTE).body.decode()
    assert "Änderungen im Entwurf" in page and "deaktiviert" in page
    assert "leer: hinterlegtes verwenden" in page
    assert "Stattdessen nur als Entwurf hinzufügen" in page


def test_repeat_key_with_changed_data_is_conflict(activation):
    ctx = activation
    submitted = form(ctx)
    assert ctx.web.browser.request("POST", ACTIVATE, submitted).status == 303
    assert ctx.web.browser.request("POST", ACTIVATE, {**submitted, "label": "Anders"}).status == 409


@pytest.mark.parametrize(("mode", "port"), [("ssl", "993"), ("starttls", "143"), ("plain", "143")])
def test_connection_modes_and_primary_folder(activation, mode, port):
    ctx = activation
    response = ctx.web.browser.request("POST", ACTIVATE, {**form(ctx), "connection_mode": mode, "port": port,
                                                         "folders": "Archiv, INBOX, Drafts"})
    assert response.status == 303
    cfg = ctx.reloads[0][0]
    assert cfg.imap.mailbox(3).primary_folder == "Archiv"
    assert Reader.calls[0][1]["starttls"] == (mode == "starttls")
    assert Reader.calls[1] == ["Archiv", "INBOX", "Drafts"]


def test_double_click_during_probe_schedules_only_one_activation(activation, monkeypatch):
    ctx = activation
    submitted = form(ctx)
    entered = False
    def check(*args):
        nonlocal entered
        if not entered:
            entered = True
            assert ctx.web.browser.request("POST", ACTIVATE, submitted).status == 303
    monkeypatch.setattr(Reader, "check_access", check)
    assert ctx.web.browser.request("POST", ACTIVATE, submitted).status == 303
    assert len(ctx.reloads) == 1
