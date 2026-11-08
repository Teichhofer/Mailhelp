"""Automatic draft notifications use the existing privacy, delivery and replay policy."""
from types import SimpleNamespace as NS

import pytest

from mailhelp import state_names
from mailhelp.notifications.notification_config import Categories, NotificationSettings
from mailhelp.notifications.notification_runtime import NotificationRuntime
from tests.fakes.shared_web_actions import MAIL1


@pytest.fixture
def draft_runtime(configured):
    app, web = configured.app, configured.web
    app.settings.notifications = NotificationSettings(categories=Categories(action_results=["telegram"]))
    app.settings.daily_briefing.enabled = False
    svc = NotificationRuntime(app, web.site)
    return NS(app=app, web=web, svc=svc)


def save_draft(ctx, **changes):
    value = {"version": 1, "status": "saved", "text": "Danke. [Termin vorschlagen]", "auto": True}
    value.update(changes)
    ctx.app.store.save(state_names.draft(MAIL1), value)


def test_standalone_draft_notifies_once_and_restarts_without_resending(draft_runtime):
    ctx = draft_runtime
    ctx.app.settings.notifications.telegram_content = "summary"
    save_draft(ctx)
    before = len(ctx.web.telegram.sent)
    ctx.svc.tick()
    assert len(ctx.web.telegram.sent) == before + 1
    text = ctx.web.telegram.sent[-1][1]
    assert "Als Entwurf im Postfach abgelegt" in text and "Danke. [Termin vorschlagen]" in text
    ctx.svc.tick()
    NotificationRuntime(ctx.app, ctx.web.site).tick()
    assert len(ctx.web.telegram.sent) == before + 1
    queued = (ctx.app.store.directory / "notification-queue.json").read_text()
    assert "Danke." not in queued  # the queue stores references, not mail content


@pytest.mark.parametrize("changes", [
    {"auto": False}, {"text": ""}, {"status": "discarded"},
])
def test_manual_or_removed_drafts_are_not_announced(draft_runtime, changes):
    save_draft(draft_runtime, **changes)
    draft_runtime.svc.tick()
    assert not draft_runtime.svc.queue.state().entries


def test_neutral_mode_hides_content_and_dispatch_rechecks_the_draft(draft_runtime):
    ctx = draft_runtime
    save_draft(ctx)
    ctx.svc.tick()
    assert "Danke." not in ctx.web.telegram.sent[-1][1]
    item = next(iter(ctx.svc.queue.state().entries.values()))
    assert ctx.svc.relevant(item)
    assert not ctx.svc.relevant(item.model_copy(update={"version": 2}))
    save_draft(ctx, text="")
    assert not ctx.svc.relevant(item)


@pytest.mark.parametrize("status,label", [("editing", "noch nicht im Postfach"),
                                          ("uncertain", "Schreibresultat unklar"),
                                          ("simulated", "Testmodus")])
def test_failed_and_uncertain_drafts_remain_visible_in_the_summary(draft_runtime, status, label):
    ctx = draft_runtime
    save_draft(ctx, status=status)
    ctx.app.settings.notifications.telegram_content = "summary"
    ctx.svc.tick()
    assert label in ctx.web.telegram.sent[-1][1]
