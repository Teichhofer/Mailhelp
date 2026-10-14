"""Synthetic delivery contracts: local time, durable identity and uncertain writes."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS

import pytest
from pydantic import ValidationError

from mailhelp.adapter import PermanentError, RetryableError
from mailhelp.notification_config import (
    Batching,
    Categories,
    DeliverySettings,
    NotificationSettings,
    QuietHours,
    effective_profile,
)
from mailhelp.notifications import NotificationService, QueueFull, quiet_now
from mailhelp.storage import JsonStore


@pytest.fixture
def queue(tmp_path):
    clock = NS(now=datetime(2026, 10, 13, 10, tzinfo=UTC))
    cfg = NS(notifications=NotificationSettings(categories=Categories(decisions=["telegram", "web_push"])),
             timezone="Europe/Berlin", telegram=NS(enabled=True), push=NS(enabled=True))
    sent, active, relevant = [], [("telegram", ""), ("web_push", "a" * 16)], set()
    service = NotificationService(JsonStore(tmp_path), lambda: cfg, lambda category: active,
                                  lambda item: item.reference in relevant,
                                  lambda items, profile: sent.append((items, profile)), lambda: clock.now)
    return NS(service=service, cfg=cfg, clock=clock, sent=sent, active=active, relevant=relevant)


def test_profiles_validate_strict_bounds_and_preserve_legacy_choices(queue):
    for model, data in ((QuietHours, {"enabled": True, "start": "07:30", "end": "07:30"}),
                        (QuietHours, {"start": "24:00"}), (Batching, {"window_seconds": 0}),
                        (DeliverySettings, {"initial_backoff_seconds": 1000}),
                        (Categories, {"decisions": ["telegram", "telegram"]}),
                        (Categories, {"decisions": ["email"]}),
                        (NotificationSettings, {"telegram_content": "secret"}),
                        (NotificationSettings, {"unknown": True})):
        with pytest.raises(ValidationError):
            model.model_validate(data)
    assert effective_profile(queue.cfg) is queue.cfg.notifications
    queue.cfg.notifications = None
    legacy = effective_profile(queue.cfg)
    assert legacy.telegram_content == "summary" and legacy.categories.decisions == ["telegram", "web_push"]
    assert not legacy.batching.enabled and not legacy.quiet_hours.enabled
    queue.cfg.telegram.enabled = queue.cfg.push.enabled = False
    assert effective_profile(queue.cfg).categories.decisions == []


@pytest.mark.parametrize("stamp,expected", [
    ("2026-10-13T19:59:00+00:00", False), ("2026-10-13T20:00:00+00:00", True),
    ("2026-10-14T05:29:00+00:00", True), ("2026-10-14T05:30:00+00:00", False),
    ("2026-10-25T00:30:00+00:00", True), ("2026-10-25T01:30:00+00:00", True),
    ("2026-03-29T01:30:00+00:00", True),
])
def test_quiet_hours_use_local_time_across_midnight_and_dst(stamp, expected):
    profile = NotificationSettings(quiet_hours=QuietHours(enabled=True))
    assert quiet_now(profile, "Europe/Berlin", datetime.fromisoformat(stamp), "decisions") == expected
    profile.quiet_hours.allow_system_errors = True
    assert not quiet_now(profile, "Europe/Berlin", datetime.fromisoformat(stamp), "system_errors")


def test_daytime_quiet_hours_and_zone_changes(queue):
    profile = queue.cfg.notifications
    profile.quiet_hours = QuietHours(enabled=True, start="11:00", end="13:00")
    assert quiet_now(profile, "Europe/Berlin", queue.clock.now, "decisions")
    assert not quiet_now(profile, "UTC", queue.clock.now, "decisions")
    profile.quiet_hours.enabled = False
    assert not quiet_now(profile, "Europe/Berlin", queue.clock.now, "decisions")


def test_duplicate_identity_batch_timer_and_restart(queue):
    svc = queue.service
    queue.cfg.notifications.batching.enabled = True
    queue.relevant.update({"mail:a", "mail:b"})
    svc.enqueue("decisions", "mail:a", 1)
    first_due = next(iter(svc.state().entries.values())).due_at
    queue.clock.now += timedelta(seconds=200)
    svc.enqueue("decisions", "mail:a", 1)
    svc.enqueue("decisions", "mail:b", 2)
    assert len(svc.state().entries) == 4
    assert {item.due_at for item in svc.state().entries.values()} == {first_due}
    svc.tick()
    assert queue.sent == []
    restarted = NotificationService(svc.store, svc.settings, svc.destinations, svc.relevant, svc.sender, svc.clock)
    queue.clock.now += timedelta(seconds=100)
    restarted.tick()
    assert len(queue.sent) == 2 and all(len(items) == 2 for items, _ in queue.sent)
    restarted.tick()
    assert len(queue.sent) == 2 and {item.status for item in svc.state().entries.values()} == {"sent"}
    assert "mail:a" in (svc.store.directory / "notification-queue.json").read_text()


def test_quiet_restart_sends_only_current_relevant_summary(queue):
    svc = queue.service
    queue.cfg.notifications.quiet_hours.enabled = queue.cfg.notifications.batching.enabled = True
    queue.clock.now = datetime(2026, 10, 13, 21, tzinfo=UTC)
    queue.relevant.update({"a", "b"})
    svc.enqueue("decisions", "a", 1)
    svc.enqueue("decisions", "b", 1)
    svc.tick()
    assert {item.status for item in svc.state().entries.values()} == {"deferred"}
    queue.relevant.remove("a")
    queue.clock.now = datetime(2026, 10, 14, 5, 30, tzinfo=UTC)
    svc.tick()
    assert len(queue.sent) == 2 and all(len(items) == 1 for items, _ in queue.sent)
    assert {item.status for item in svc.state().entries.values()} == {"sent", "cancelled"}


@pytest.mark.parametrize("exception,expected,error", [
    (RetryableError("private token"), "failed", "retryable"),
    (PermanentError("private token"), "failed", "refused"),
    (OSError("private token"), "uncertain", "unknown"),
])
def test_delivery_failures_are_safe_bounded_and_do_not_block_other_channels(queue, exception, expected, error):
    svc = queue.service
    queue.relevant.add("a")
    attempts = []
    def send(items, profile):
        attempts.append(items[0].channel)
        if items[0].channel == "telegram":
            raise exception
    svc.sender = send
    svc.enqueue("decisions", "a")
    svc.tick()
    assert attempts == ["telegram", "web_push"]
    item = next(item for item in svc.state().entries.values() if item.channel == "telegram")
    assert (item.status, item.error) == (expected, error)
    assert "private token" not in (svc.store.directory / "notification-queue.json").read_text()
    for _ in range(5):
        queue.clock.now += timedelta(minutes=30)
        svc.tick()
    assert attempts.count("telegram") == (3 if error == "retryable" else 1)
    assert attempts.count("web_push") == 1


def test_backoff_waits_and_interrupted_send_is_never_repeated(queue):
    svc = queue.service
    queue.relevant.add("a")
    svc.sender = lambda items, profile: (_ for _ in ()).throw(RetryableError())
    svc.enqueue("decisions", "a")
    svc.tick()
    svc.tick()
    assert {item.attempts for item in svc.state().entries.values()} == {1}
    state = svc.state()
    for item in state.entries.values():
        item.status = "sending"
    svc.store.save("notification-queue", state.model_dump(mode="json"))
    svc.tick()
    assert {(item.status, item.error) for item in svc.state().entries.values()} == {("uncertain", "interrupted")}


def test_sender_runs_without_global_lock_and_nested_scheduler_is_ignored(queue):
    from threading import Event, Thread
    svc = queue.service
    queue.relevant.add("a")
    def send(items, profile):
        done = Event()
        def concurrent_reader():
            with svc.store.locked():
                done.set()
        worker = Thread(target=concurrent_reader)
        worker.start()
        assert done.wait(2)
        worker.join()
        svc.tick()
        queue.sent.append(items)
    svc.sender = send
    svc.enqueue("decisions", "a")
    svc.tick()
    assert len(queue.sent) == 2


def test_configuration_and_relevance_are_rechecked_immediately_before_each_group(queue):
    svc = queue.service
    queue.relevant.add("a")
    def send(items, profile):
        queue.sent.append(items)
        queue.active.clear()
    svc.sender = send
    svc.enqueue("decisions", "a")
    svc.tick()
    assert len(queue.sent) == 1
    assert {item.status for item in svc.state().entries.values()} == {"sent", "cancelled"}


def test_new_quiet_settings_before_second_dispatch_are_observed(queue):
    svc = queue.service
    queue.relevant.add("a")
    def send(items, profile):
        queue.sent.append(items)
        queue.cfg.notifications.quiet_hours = QuietHours(enabled=True, start="11:00", end="13:00")
    svc.sender = send
    svc.enqueue("decisions", "a")
    svc.tick()
    assert len(queue.sent) == 1
    assert {item.status for item in svc.state().entries.values()} == {"sent", "deferred"}


def test_capacity_keeps_source_recoverable_and_history_preserves_open_delivery_identity(queue):
    svc = queue.service
    queue.cfg.notifications.delivery.max_pending = 2
    queue.relevant.update({"a", "b"})
    svc.enqueue("decisions", "a")
    with pytest.raises(QueueFull):
        svc.enqueue("decisions", "b")
    assert len(svc.state().entries) == 2
    svc.tick()
    svc.enqueue("decisions", "b")
    svc.tick()
    queue.clock.now += timedelta(days=31)
    svc.tick()
    assert len(svc.state().entries) == 4
    queue.relevant.clear()
    svc.tick()
    assert svc.state().entries == {}


def test_invalid_references_and_removed_devices_never_send(queue):
    with pytest.raises(ValidationError):
        queue.service.enqueue("decisions", "mail subject <script>")
    queue.service.enqueue("decisions", "a")
    queue.active.clear()
    queue.service.tick()
    assert not queue.sent


def test_capacity_smaller_than_the_channel_count_still_makes_progress(queue):
    queue.cfg.notifications.delivery.max_pending = 1
    queue.relevant.add("a")
    with pytest.raises(QueueFull):
        queue.service.enqueue("decisions", "a")
    queue.service.tick()
    assert len(queue.sent) == 1
    queue.service.enqueue("decisions", "a")
    queue.service.tick()
    assert len(queue.sent) == 2 and {item.status for item in queue.service.state().entries.values()} == {"sent"}


def test_regression_exhausted_failures_do_not_fill_the_pending_queue_forever(queue):
    queue.active[:] = [("telegram", "")]
    queue.cfg.notifications.delivery.max_attempts = queue.cfg.notifications.delivery.max_pending = 1
    queue.relevant.update({"a", "b"})
    queue.service.sender = lambda *args: (_ for _ in ()).throw(RetryableError())
    queue.service.enqueue("decisions", "a")
    queue.service.tick()
    queue.service.enqueue("decisions", "b")
    queue.service.tick()
    assert len(queue.service.state().entries) == 2
    assert {item.status for item in queue.service.state().entries.values()} == {"failed"}
    queue.relevant.clear()
    queue.clock.now += timedelta(days=31)
    queue.service.tick()
    assert queue.service.state().entries == {}


def test_regression_increasing_retry_limits_cannot_retry_a_permanently_refused_delivery(queue):
    attempts = []
    queue.active[:] = [("telegram", "")]
    queue.cfg.notifications.delivery.max_attempts = 1
    queue.relevant.add("a")
    def refused(*args):
        attempts.append(True)
        raise PermanentError("synthetic refusal")
    queue.service.sender = refused
    queue.service.enqueue("decisions", "a")
    queue.service.tick()
    queue.cfg.notifications.delivery.max_attempts = 5
    queue.clock.now += timedelta(hours=1)
    queue.service.tick()
    assert attempts == [True]


def test_retry_budget_changes_are_rechecked_before_the_next_channel_attempt(queue):
    queue.relevant.add("a")
    attempts = []
    def failed(items, profile):
        attempts.append(items[0].channel)
        raise RetryableError()
    queue.service.sender = failed
    queue.service.enqueue("decisions", "a")
    queue.service.tick()
    queue.clock.now += timedelta(minutes=1)
    def changed(items, profile):
        attempts.append(items[0].channel)
        queue.cfg.notifications = profile.model_copy(deep=True)
        queue.cfg.notifications.delivery.max_attempts = 1
    queue.service.sender = changed
    queue.service.tick()
    assert attempts == ["telegram", "web_push", "telegram"]
    push = next(item for item in queue.service.state().entries.values() if item.channel == "web_push")
    assert push.status == "failed" and push.attempts == 1
