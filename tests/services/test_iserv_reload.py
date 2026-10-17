"""IServ adapters are replaced between mail cycles and closed on replacement/shutdown."""
from contextlib import ExitStack
from threading import Event
from types import SimpleNamespace as NS

import pytest
from shared_application import Imap, Orch, Telegram, app
from shared_decision_test import secrets

from mailhelp.config import IServSettings, Secrets
from mailhelp.iserv_runtime import IServRuntime


class Reader:
    instances = []
    fail = False

    def __init__(self, account, keys, *args, **kwargs):
        if Reader.fail and account.id == 2:
            raise RuntimeError("secret-must-not-appear")
        self.account, self.closed, self.account_id = account, False, str(account.id) * 24
        Reader.instances.append(self)

    def close(self):
        self.closed = True

    def letters(self):
        return []


@pytest.fixture
def reloadable(profiled, monkeypatch):
    Reader.instances, Reader.fail = [], False
    monkeypatch.setattr("mailhelp.iserv.IServReader", Reader)
    ctx = profiled
    ctx.app.mailbox = NS(settings=ctx.cfg, resume_readers={"old": object()})
    ctx.app.orchestrator.mailbox_numbers["old"] = 1
    ctx.app.sources = []
    ctx.app._process_mail = lambda mail: None
    ctx.app.stop_event = Event()
    ctx.app.logger.metrics = NS(mailbox_numbers={})
    ctx.events = []
    ctx.app.logger.event = lambda *args, **kwargs: ctx.events.append((args, kwargs))
    ctx.controller = IServRuntime(ctx.app, ExitStack())
    raw = ctx.cfg.model_dump()
    raw["iserv"] = {"accounts": [{"id": 1, "server": "https://school.example", "mailbox": 2}]}
    from mailhelp.config import Settings
    ctx.new_settings = Settings.model_validate(raw)
    raw_keys = secrets().model_dump()
    raw_keys["iserv"] = {1: {"username": "synthetic", "password": "pw"},
                         2: {"username": "other", "password": "pw"}}
    ctx.keys = Secrets.model_validate(raw_keys)
    yield ctx
    ctx.controller.close()


def test_activating_readers_preserves_imap_settings_and_enables_polling(reloadable):
    ctx = reloadable
    ctx.controller.apply_pending()
    assert not Reader.instances
    ctx.controller.request(ctx.new_settings, ctx.keys)
    assert ctx.app.settings.iserv.accounts == []
    ctx.controller.apply_pending()
    first = Reader.instances[0]
    assert ctx.app.settings.iserv == ctx.new_settings.iserv
    assert ctx.app.configuration.active.iserv == ctx.new_settings.iserv
    assert ctx.app.settings.imap == ctx.cfg.imap
    assert ctx.app.orchestrator.mailbox_numbers["1" * 24] == 2
    assert "old" not in ctx.app.orchestrator.mailbox_numbers
    assert ctx.app.mailbox.resume_readers == {"1" * 24: first}
    assert ctx.app.orchestrator.always_relevant == frozenset({"1" * 24})
    assert ctx.app.iserv.poll() == []
    assert ctx.events[-1][0][2] == "letters_listed"
    ctx.controller.request(ctx.new_settings, ctx.keys)
    ctx.controller.apply_pending()
    assert first.closed and not Reader.instances[-1].closed
    # Removing all readers does not leave stale resumption adapters or relevance rules.
    ctx.controller.request(ctx.new_settings.model_copy(update={"iserv": IServSettings()}), ctx.keys)
    ctx.controller.apply_pending()
    assert ctx.app.mailbox.resume_readers == {} and not ctx.app.orchestrator.always_relevant
    assert Reader.instances[-1].closed


def test_failed_build_is_closed_and_retried_without_stopping_mail(reloadable):
    ctx = reloadable
    settings = ctx.new_settings.model_copy(deep=True)
    settings.iserv.accounts.append(settings.iserv.accounts[0].model_copy(update={"id": 2}))
    ctx.controller.request(settings, ctx.keys)
    Reader.fail = True
    ctx.controller.apply_pending()
    assert Reader.instances[0].closed
    assert ctx.app.settings.iserv.accounts == []
    assert ctx.events[-1] == (("ERROR", "iserv", "activation_failed"), {})
    assert ctx.controller.pending is not None
    Reader.fail = False
    ctx.controller.apply_pending()
    assert len(ctx.app.iserv.sources) == 2 and ctx.controller.pending is None


def test_a_newer_request_survives_a_failed_build(reloadable, monkeypatch):
    ctx = reloadable
    ctx.controller.request(ctx.new_settings, ctx.keys)
    def replace(pending):
        ctx.controller.request(ctx.cfg, ctx.keys)
        raise RuntimeError("failed")
    monkeypatch.setattr(ctx.controller, "_apply", replace)
    ctx.controller.apply_pending()
    assert ctx.controller.pending[0] == ctx.cfg


def test_old_cleanup_failure_does_not_close_the_installed_reader(reloadable):
    ctx = reloadable
    def fail_close():
        raise OSError("old transport failed")
    ctx.controller.resources.callback(fail_close)
    ctx.controller.request(ctx.new_settings, ctx.keys)
    ctx.controller.apply_pending()
    assert not Reader.instances[0].closed and ctx.app.iserv.poll() == []
    ctx.controller.apply_pending()
    assert Reader.instances[0].closed and not Reader.instances[-1].closed


def test_the_mail_cycle_installs_pending_readers_before_polling(tmp_path):
    service = app(tmp_path, Imap([]), Telegram([]), Orch())
    calls = []
    service.iserv_runtime = NS(apply_pending=lambda: calls.append("reload"))
    service.iserv = NS(poll=lambda limit: calls.append("poll"))
    service._poll_telegram = lambda timeout=None: True
    service._idle = lambda delay: None
    assert service._cycle(None, False)
    assert calls == ["reload", "poll"]
