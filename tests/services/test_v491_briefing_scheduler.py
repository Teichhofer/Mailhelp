"""Durable slots, local dates and restart behavior without external services."""
from datetime import UTC, datetime, timedelta

import pytest

from mailhelp.notifications.briefing_scheduler import STATE, BriefingScheduler, BriefingState, target_mailbox
from mailhelp.storage import JsonStore
from tests.fakes.shared_application import settings


@pytest.fixture
def clocked(tmp_path):
    cfg = settings(tmp_path)
    cfg.timezone, cfg.briefings.enabled = "Europe/Berlin", True
    now, calls, reports = [datetime(2026, 11, 8, 6, tzinfo=UTC)], [], []
    def deliver(run, persist):
        calls.append(run.model_copy(deep=True))
        return "saved"
    with JsonStore(tmp_path / "data") as store:
        scheduler = BriefingScheduler(store, lambda: cfg, deliver, lambda: now[0],
                                       lambda identity, status: reports.append((identity, status)))
        yield cfg, now, calls, reports, store, scheduler


def test_each_local_slot_is_written_once_even_after_restart(clocked):
    cfg, now, calls, reports, store, scheduler = clocked
    for hour in (6, 12, 17):
        now[0] = now[0].replace(hour=hour)
        scheduler.tick()
        scheduler.tick()
        BriefingScheduler(store, lambda: cfg, scheduler.deliver, lambda: now[0]).tick()
    assert [run.label for run in calls] == ["07:00", "13:00", "18:00"]
    state = store.load_model(STATE, BriefingState)
    assert state.last_briefing_at == now[0] and len(state.runs) == 3
    assert len(reports) == 3 and all(status == "saved" for _, status in reports)


def test_delayed_ticks_use_the_previous_successful_slot_as_the_next_window(clocked):
    _, now, calls, _, _, scheduler = clocked
    now[0] = now[0].replace(hour=17)
    scheduler.tick()
    assert [run.window_start.hour for run in calls] == [23, 6, 12]


def test_disabled_future_and_busy_ticks_do_not_deliver(clocked):
    cfg, now, calls, _, store, scheduler = clocked
    cfg.briefings.enabled = False
    scheduler.tick()
    assert store.load(STATE) is None
    cfg.briefings.enabled = True
    now[0] = now[0].replace(hour=5)
    scheduler.tick()
    assert not calls
    scheduler._lock.acquire()
    try:
        scheduler.tick()
    finally:
        scheduler._lock.release()
    now[0] = datetime(2026, 11, 8, 7)
    with pytest.raises(ValueError, match="Zeitzone"):
        scheduler.tick()


@pytest.mark.parametrize("outcome", ["failed", "uncertain", "invalid", "exception", "uncertain_exception"])
def test_failures_have_durable_backoff_and_never_log_exception_content(clocked, outcome):
    _, now, calls, _, store, scheduler = clocked
    def deliver(run, persist):
        calls.append(run.id)
        if outcome.endswith("exception"):
            run.draft["status"] = "uncertain" if outcome == "uncertain_exception" else "editing"
            persist()
            raise OSError("private-content-and-credentials")
        return outcome
    scheduler.deliver = deliver
    scheduler.tick()
    state = store.load_model(STATE, BriefingState)
    run = next(iter(state.runs.values()))
    assert run.status in {"failed", "uncertain"} and run.retry_at == now[0] + timedelta(seconds=60)
    scheduler.tick()
    assert len(calls) == 1
    now[0] += timedelta(seconds=60)
    scheduler.deliver = lambda run, persist: "simulated"
    scheduler.tick()
    assert store.load_model(STATE, BriefingState).last_briefing_at is not None
    assert "private-content" not in (store.directory / (STATE + ".json")).read_text()


def test_crash_preserves_snapshot_and_recovers_the_same_identity(clocked):
    cfg, now, calls, _, store, scheduler = clocked
    class Crash(BaseException):
        pass
    def crash(run, persist):
        calls.append(run.id)
        run.snapshot, run.draft = {"text": "Synthetic summary"}, {"status": "uncertain"}
        persist()
        raise Crash()
    scheduler.deliver = crash
    with pytest.raises(Crash):
        scheduler.tick()
    def recover(run, persist):
        assert run.id == calls[0] and run.snapshot == {"text": "Synthetic summary"}
        return "saved"
    BriefingScheduler(store, lambda: cfg, recover, lambda: now[0]).tick()
    assert next(iter(store.load_model(STATE, BriefingState).runs.values())).snapshot is None


def test_skipped_empty_advances_checkpoint_and_clock_rollback_creates_no_old_slots(clocked):
    _, now, calls, _, store, scheduler = clocked
    scheduler.deliver = lambda run, persist: "skipped_empty"
    scheduler.tick()
    stamp = store.load_model(STATE, BriefingState).last_briefing_at
    now[0] -= timedelta(days=1)
    scheduler.tick()
    assert store.load_model(STATE, BriefingState).last_briefing_at == stamp and calls == []


def test_removed_times_and_future_saved_runs_are_not_replayed(clocked):
    cfg, now, calls, _, store, scheduler = clocked
    scheduler.deliver = lambda run, persist: "failed"
    scheduler.tick()
    state = store.load_model(STATE, BriefingState)
    run = next(iter(state.runs.values()))
    run.scheduled_at += timedelta(hours=1)
    run.retry_at = None
    store.save(STATE, state.model_dump(mode="json"))
    scheduler.tick()
    cfg.briefings.times = ["13:00"]
    now[0] += timedelta(hours=2)
    scheduler.tick()
    assert calls == []


def test_target_selection_rejects_a_removed_mailbox(profiled):
    cfg = profiled.cfg
    assert target_mailbox(cfg) == 1
    cfg.briefings.mailbox = 2
    assert target_mailbox(cfg) == 2
    cfg.briefings.mailbox = 99
    with pytest.raises(ValueError, match="aktiv"):
        target_mailbox(cfg)


def test_recovered_older_run_never_moves_the_successful_checkpoint_backwards(clocked):
    cfg, now, calls, _, store, scheduler = clocked
    scheduler.deliver = lambda run, persist: "failed" if run.label == "07:00" else "saved"
    now[0] = now[0].replace(hour=12)
    scheduler.tick()
    state = store.load_model(STATE, BriefingState)
    latest = state.last_briefing_at
    assert latest == now[0]
    now[0] += timedelta(minutes=1)
    scheduler.deliver = lambda run, persist: "saved"
    scheduler.tick()
    state = store.load_model(STATE, BriefingState)
    assert state.last_briefing_at == latest and all(run.status == "saved" for run in state.runs.values())
