"""Mailbox OAuth uses real setup persistence and preserves unrelated mailbox policies."""
from types import SimpleNamespace as NS

import pytest

from mailhelp.app import mailbox_accounts as module
from mailhelp.config import MailboxSettings, Settings
from tests.fakes.initial_harness import initial  # noqa: F401
from tests.fakes.shared_application import settings


def capture(monkeypatch):
    result = {}
    def site(site, store, client, context, back):
        result.update(client=client, context=context, back=back)
    monkeypatch.setattr(module, "MailboxOAuthSite", site)
    return result


def test_initial_wiring_reads_and_saves_the_actual_draft(initial, monkeypatch):
    h = initial
    captured = capture(monkeypatch)
    module.attach_initial_mailbox(NS(), h.setup, h.store)
    context = captured["context"]
    assert captured["client"]() is None and captured["back"] == "/einrichtung/start"
    with pytest.raises(ValueError):
        context.read(1)
    h.setup.save(h.actor, h.form(1, password="synthetic-password"))
    from tests.fakes.hosted_google import settings as hosted_settings
    state = h.setup.state()
    state.config["hosted_auth"] = hosted_settings().model_dump()
    h.setup._save(state)
    with pytest.raises(ValueError):
        context.read(2)
    mailbox, version, revision = context.read(1)
    candidate = MailboxSettings.model_validate({**mailbox.model_dump(), "host": "imap.gmail.com",
                                               "auth_method": "gmail", "oauth_connection": "a" * 32})
    with pytest.raises(ValueError):
        context.save(h.actor, candidate, "test@example.test", version, "b" * 32, "stale")
    context.save(h.actor, candidate, "test@example.test", version, "b" * 32, revision)
    assert h.setup.state().config["imap"]["oauth_connection"] == "a" * 32
    assert h.setup.environment()["IMAP_USERNAME"] == "test@example.test"
    assert "IMAP_PASSWORD" not in h.setup.environment()
    from mailhelp.web.initial_pages import initial_page
    html = initial_page(h.setup.state(), "csrf", 2)
    assert 'name="IMAP_PASSWORD"' not in html and 'name="IMAP_USERNAME"' in html
    monkeypatch.setattr(module, "probe", lambda cfg, box, user: [(box.host, user)])
    assert context.probe(candidate, "user") == [("imap.gmail.com", "user")]


@pytest.mark.parametrize("role", ["inbox", None])
def test_probe_reads_without_creating_folders_or_messages(tmp_path, monkeypatch, role):
    calls = []
    class Reader:
        def __init__(self, *args, **options):
            calls.append("connected")
        def list_folders(self):
            return [NS(name="INBOX", role=role)]
        def check_access(self, folders):
            calls.append(folders)
        def close(self):
            calls.append("closed")
    monkeypatch.setattr(module, "reader_arguments", lambda *_args: (("imap.example.test", 993, "u", ""), {}))
    monkeypatch.setattr(module, "ImapReader", Reader)
    cfg = settings(tmp_path)
    assert module.probe(cfg, cfg.imap.mailbox(1), "u") == [("INBOX", role)]
    assert calls == ["connected", ["INBOX"], "closed"]


def test_running_context_new_and_existing_mailboxes(tmp_path, monkeypatch):
    cfg = settings(tmp_path)
    captured = capture(monkeypatch)
    state = NS(version=2, kind="settings", patch={})
    setup = NS(draft_settings=lambda: cfg, state=lambda: state)
    runtime = NS(setup=setup)
    app = NS(configuration=NS(directory=tmp_path), store=NS())
    site = NS(setup_page=NS(runtime=runtime))
    module.attach_running_mailbox(app, site, lambda: cfg)
    context = captured["context"]
    assert captured["client"]() is None
    assert context.read(1)[0].id == 1
    box, version, revision = context.read(2)
    assert box.id == 2 and version == 2 and ":" in revision
    with pytest.raises(ValueError):
        context.read(0)
    calls = []
    monkeypatch.setattr(module, "ReconnectActivation", lambda runtime: NS(activate=lambda *args: calls.append(args)))
    context.save("web:actor", box, "username", 2, "key", revision)
    assert calls[0][-3:] == (box, "username", "")
    monkeypatch.setattr(module, "probe", lambda *args: [])
    assert context.probe(box, "username") == []
    raw = cfg.model_dump()
    raw["imap"] = {"mailboxes": [MailboxSettings(id=n, host=f"imap{n}.example.test", port=993,
        folders=["INBOX"]).model_dump() for n in range(1, 11)]}
    cfg = Settings.model_validate(raw)
    with pytest.raises(ValueError):
        context.read(11)
    state.patch = {"imap.mailboxes": []}
    with pytest.raises(ValueError):
        context.read(1)
    state.patch, state.kind = {}, "topics"
    with pytest.raises(ValueError):
        context.read(1)


def test_reconnect_replaces_one_entry_without_losing_policy(tmp_path):
    cfg = settings(tmp_path)
    instance = object.__new__(module.ReconnectActivation)
    original = cfg.imap.mailbox(1)
    replacement = original.model_copy(update={"label": "Changed"})
    assert instance.merged(cfg, replacement).imap.mailbox(1).label == "Changed"
    new = MailboxSettings(id=2, host="imap2.example.test", port=993, folders=["INBOX"])
    result = instance.merged(cfg, new)
    assert len(result.imap.configured_mailboxes()) == 2 and result.imap.mailbox(1) == original


def test_mailbox_oauth_needs_the_service_before_any_connection(tmp_path):
    from pydantic import ValidationError
    cfg = settings(tmp_path).model_dump()
    cfg["imap"] = {"host": "imap.gmail.com", "port": 993, "folders": ["INBOX"], "auth_method": "gmail",
                   "oauth_connection": "a" * 32}
    with pytest.raises(ValidationError, match="hosted_auth.enabled"):
        Settings.model_validate(cfg)


def test_running_oauth_persists_only_username_and_renders_bound_controls(profiled, monkeypatch):
    import yaml

    from mailhelp.config import Secrets
    from tests.fakes.hosted_google import settings as hosted_settings
    from tests.fakes.shared_decision_test import secrets

    ctx = profiled
    cfg = ctx.cfg.model_copy(update={"hosted_auth": hosted_settings()})
    ctx.app.settings = ctx.app.configuration.active = cfg
    (ctx.tmp_path / "config.yaml").write_text(yaml.safe_dump(cfg.model_dump(mode="json")), encoding="utf-8")
    ctx.runtime.secrets = Secrets.model_validate(secrets().model_dump())
    activated, checked = [], []
    ctx.app.mailbox_runtime = NS(request=lambda cfg, keys: activated.append(cfg))
    monkeypatch.setattr(module.ReconnectActivation, "probe",
        lambda self, cfg, box, keys: checked.append((box.id, keys.imap[box.id].username)))
    captured = capture(monkeypatch)
    module.attach_running_mailbox(ctx.app, ctx.web.site, lambda: cfg)
    context = captured["context"]
    box, version, revision = context.read(1)
    candidate = box.model_copy(update={"host": "imap.gmail.com", "auth_method": "gmail",
                                       "oauth_connection": "c" * 32})
    session = ctx.web.auth.authenticate(ctx.web.browser.cookies["mh_session"])
    context.save("web:" + session.id, candidate, "synthetic@example.test", version, "oauth-save-0001", revision)
    assert checked == [(1, "synthetic@example.test")] and len(activated) == 1
    saved = Settings.model_validate(yaml.safe_load((ctx.tmp_path / "config.yaml").read_text(encoding="utf-8")))
    assert saved.imap.mailbox(1).oauth_connection == "c" * 32
    credentials = (ctx.tmp_path / ".env").read_text(encoding="utf-8")
    assert 'IMAP_1_USERNAME=' in credentials and 'IMAP_1_PASSWORD=' not in credentials
    html = ctx.web.browser.request("GET", "/einstellungen/postfaecher/1").body.decode()
    assert "/postfach/oauth/trennen" in html and "mailbox=1" in html
    assert "/einstellungen/postfaecher/1/anbieter" not in html
