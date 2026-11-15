from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from mailhelp.notifications.push_events import PushDecisionEvents
from mailhelp.notifications.webpush import PushService
from mailhelp.persistence.proposals import ProposalRepository
from mailhelp.persistence.storage import JsonStore
from mailhelp.review.revision_origin import ORIGIN, revision_origin
from tests.fakes.factories import build_proposal
from tests.fakes.push68 import subscription


def test_activation_existing_cards_own_revision_system_revision_and_restart(tmp_path):
    now = [datetime.now(UTC)]
    with JsonStore(tmp_path) as store:
        push = PushService(
            store,
            SimpleNamespace(active=lambda _: True),
            "mailto:ops@example.test",
            lambda **_: None,
            clock=lambda: now[0],
        )
        ref = "a" * 24 + ":p1"
        events = PushDecisionEvents(store, lambda: now[0], {(ref, 1): None})
        push.change("a" * 16, "subscribe-01", subscription())
        device = push.destinations()[0]
        assert not events.eligible(ref, 1, push, device)
        now[0] += timedelta(seconds=1)
        proposal = build_proposal(source_mail_id="a" * 24, id="p1", version=2)
        repo = ProposalRepository(store)
        with revision_origin("web"):
            repo.save_revision(proposal)
        assert not events.eligible(ref, 2, push, device)
        assert events.records[ref]["source"] == "web" and ORIGIN.get() == "system"
        now[0] += timedelta(seconds=1)
        repo.save_revision(proposal.model_copy(update={"version": 3}))
        assert events.eligible(ref, 3, push, device)
        assert not events.eligible(ref, 2, push, device)
        saved = events.records.copy()
        restarted = PushDecisionEvents(store, lambda: now[0], {})
        assert restarted.records == saved and restarted.eligible(ref, 3, push, device)
        now[0] += timedelta(seconds=1)
        push.change("b" * 16, "subscribe-01", subscription())
        second = next(d for d in push.destinations() if d.startswith("b" * 16))
        assert not restarted.eligible(ref, 3, push, second)
        with pytest.raises(RuntimeError):
            with revision_origin("telegram"):
                raise RuntimeError("synthetic")
        assert ORIGIN.get() == "system"


def test_regression_proposal_in_the_same_clock_tick_as_activation_is_delivered(tmp_path):
    # The Windows clock often returns the same value for consecutive calls. A proposal that appeared in the
    # same tick as the activation counted as "before" it and was never announced on that device.
    now = datetime(2026, 11, 15, 9, 0, tzinfo=UTC)
    with JsonStore(tmp_path) as store:
        push = PushService(store, SimpleNamespace(active=lambda _: True), "mailto:ops@example.test",
                           lambda **_: None, clock=lambda: now)
        events = PushDecisionEvents(store, lambda: now, {})
        push.change("a" * 16, "subscribe-01", subscription())
        device = push.destinations()[0]
        assert events.eligible("a" * 24 + ":p1", 1, push, device)
        # Earlier than the activation stays silent: activating a device never replays the backlog.
        older = PushDecisionEvents(store, lambda: now - timedelta(microseconds=1), {})
        assert not older.eligible("b" * 24 + ":p1", 1, push, device)


def test_missing_and_damaged_history_defaults_to_system(tmp_path):
    with JsonStore(tmp_path) as store:
        now = datetime.now(UTC)
        events = PushDecisionEvents(store, lambda: now, {})
        ref = "a" * 24 + ":p1"
        assert events.observe(ref, 1)["source"] == "system"
        store.save("history-" + "a" * 24, {"invalid": True})
        assert events.observe(ref, 2)["source"] == "system"
        assert events.observe("b" * 24 + ":relevance", 1)["source"] == "system"
