"""Activated mailboxes join the running service only at a mail-cycle boundary."""
from contextlib import ExitStack
from threading import Event
from types import SimpleNamespace as NS

import pytest
from shared_application import Imap, Orch, Telegram, app
from shared_decision_test import secrets

from mailhelp.config import ImapSettings, Secrets
from mailhelp.mailbox.imap import account_id
from mailhelp.mailbox.mailbox_run import MailboxSource
from mailhelp.mailbox.mailbox_runtime import MailboxRuntime
from mailhelp.runtime.experience import ExperienceRuntime


class Reader:
    instances = []
    fail = None

    def __init__(self, host, port, username, password, *args, **kwargs):
        if host == Reader.fail:
            raise OSError("private-connection-details")
        self.account_id, self.closed = account_id(host, port, username), False
        self.options = kwargs
        Reader.instances.append(self)

    def close(self):
        self.closed = True


@pytest.fixture
def reloadable(profiled, monkeypatch):
    ctx = profiled
    Reader.instances, Reader.fail = [], None
    monkeypatch.setattr("mailhelp.mailbox.imap.ImapReader", Reader)
    keys = secrets().model_dump()
    keys["imap"] = {n: {"username": f"user-{n}", "password": f"pw-{n}"} for n in range(1, 5)}
    ctx.keys = Secrets.model_validate(keys)
    ctx.app.sources = [MailboxSource(box, Reader(box.host, box.port, f"user-{box.id}", "pw"))
                       for box in ctx.cfg.imap.enabled_mailboxes()]
    ctx.original_sources = list(ctx.app.sources)
    ctx.app.mailbox = NS(settings=ctx.cfg, sources=ctx.app.sources)
    ctx.app.stop_event = Event()
    ctx.app.logger.metrics = NS(mailbox_numbers={"existing": 1})
    ctx.events = []
    ctx.app.logger.event = lambda *args, **kwargs: ctx.events.append((args, kwargs))
    ctx.app.iserv = None
    ctx.app.experience = None
    ctx.shared_keys = ctx.keys.model_copy(deep=True)
    del ctx.shared_keys.imap[3]
    ctx.controller = MailboxRuntime(ctx.app, ExitStack(), ctx.shared_keys)
    boxes = [*ctx.cfg.imap.configured_mailboxes(), ctx.cfg.imap.mailbox(1).model_copy(
        update={"id": 3, "host": "new.example.test", "label": "Verein", "drafts_folder": "Entwürfe"})]
    ctx.new_settings = ctx.cfg.model_copy(update={"imap": ImapSettings(mailboxes=boxes)})
    yield ctx
    ctx.controller.close()


@pytest.mark.parametrize("experience", [False, True])
def test_install_preserves_running_sources_and_connects_all_consumers(reloadable, experience):
    ctx = reloadable
    updates = []
    if experience:
        ctx.app.experience = NS(add_mailboxes=lambda cfg, keys: updates.append((cfg, keys)))
        ctx.app.iserv = NS(sources=[NS(reader=NS(account_id="iserv"), account=NS(label="Schule"))])
    ctx.controller.apply_pending()
    assert len(Reader.instances) == 2
    ctx.controller.request(ctx.new_settings, ctx.keys)
    assert len(ctx.app.sources) == 2
    ctx.controller.apply_pending()
    assert ctx.app.sources[:2] == ctx.original_sources and len(ctx.app.sources) == 3
    source = ctx.app.sources[2]
    assert not any(source.reader.closed for source in ctx.app.sources)
    assert ctx.app.mailbox.sources is ctx.app.sources
    assert ctx.app.settings is ctx.app.mailbox.settings
    assert ctx.app.configuration.active.imap.mailbox(3).label == "Verein"
    assert ctx.shared_keys.imap[3].username == "user-3"
    assert ctx.app.orchestrator.mailbox_numbers[source.account_id] == 3
    assert ctx.app.logger.metrics.mailbox_numbers[source.account_id] == 3
    assert ctx.app.logger.metrics.mailbox_numbers["existing"] == 1
    assert ctx.events[-1] == (("INFO", "imap", "mailboxes_activated"), {"count": 1})
    assert bool(updates) == experience
    # A repeated pending snapshot cannot install a second reader for the same mailbox.
    ctx.controller.request(ctx.new_settings, ctx.keys)
    ctx.controller.apply_pending()
    assert len(Reader.instances) == 3
    ctx.controller.close()
    assert source.reader.closed and not ctx.original_sources[0].reader.closed


def test_failed_connection_closes_new_readers_and_retries_without_partial_install(reloadable):
    ctx = reloadable
    fourth = ctx.new_settings.imap.mailbox(3).model_copy(update={"id": 4, "host": "fail.example.test"})
    settings = ctx.new_settings.model_copy(deep=True)
    settings.imap.mailboxes.append(fourth)
    Reader.fail = fourth.host
    ctx.controller.request(settings, ctx.keys)
    ctx.controller.apply_pending()
    assert len(ctx.app.sources) == 2 and ctx.app.settings is ctx.cfg
    assert Reader.instances[2].closed and 3 not in ctx.shared_keys.imap
    assert ctx.controller.pending is not None
    assert ctx.events[-1] == (("ERROR", "imap", "activation_failed"), {})
    Reader.fail = None
    ctx.controller.apply_pending()
    assert len(ctx.app.sources) == 4 and ctx.controller.pending is None


@pytest.mark.parametrize("drafts", [False, True])
@pytest.mark.parametrize("multiple", [False, True])
def test_experience_updates_draft_targets_and_mailbox_filters(reloadable, drafts, multiple):
    ctx = reloadable
    feature = ExperienceRuntime.__new__(ExperienceRuntime)
    feature.app, feature.site = ctx.app, ctx.web.site
    feature.mailbox_numbers = {}
    feature.draft_targets = {} if drafts else None
    ctx.app.settings = ctx.new_settings
    if not multiple:
        ctx.app.sources[:] = ctx.app.sources[:1]
    feature.add_mailboxes(ctx.new_settings, ctx.keys)
    new_account = account_id("new.example.test", 993, "user-3")
    if drafts:
        assert feature.mailbox_numbers[new_account] == 3
        target = feature.draft_targets[new_account]
        assert target.sender == "user-3" and target.folder == "Entwürfe"
        assert feature.draft_policy(new_account)[0] == ctx.cfg.smart_reply
    assert bool(ctx.web.site.views.mailboxes) == multiple
    if multiple:
        assert ctx.web.site.views.mailboxes == ctx.web.site.archive.queries.mailboxes


def test_mail_cycle_installs_mailboxes_then_iserv_before_polling(tmp_path):
    service = app(tmp_path, Imap([]), Telegram([]), Orch())
    calls = []
    service.mailbox_runtime = NS(apply_pending=lambda: calls.append("imap"))
    service.iserv_runtime = NS(apply_pending=lambda: calls.append("iserv"))
    service.iserv = NS(poll=lambda limit: calls.append("poll"))
    service._poll_telegram = lambda timeout=None: True
    service._idle = lambda delay: None
    assert service._cycle(None, False)
    assert calls == ["imap", "iserv", "poll"]
