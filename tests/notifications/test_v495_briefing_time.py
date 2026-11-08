"""Real scheduler and MIME writer travel through local slots; IMAP stays synthetic."""
from contextlib import nullcontext
from datetime import UTC, datetime
from email import policy
from email.parser import BytesParser

import pytest
import time_machine

from mailhelp.notifications.briefing_drafts import BriefingDraftService
from mailhelp.notifications.briefing_scheduler import STATE, BriefingScheduler, BriefingState
from mailhelp.notifications.drafts import DraftTarget
from mailhelp.review.views import ReviewViews
from mailhelp.storage import JsonStore
from tests.fakes.shared_application import settings


class DraftMailbox:
    def __init__(self):
        self.messages = {}

    def select(self, folder, readonly):
        assert readonly
        return "OK", []

    def uid(self, *args):
        return "OK", [b"1" if args[-1] in self.messages else b""]

    def append(self, folder, flags, stamp, raw):
        message = BytesParser(policy=policy.default).parsebytes(raw)
        assert message["Message-ID"] not in self.messages, "second APPEND for the same slot"
        self.messages[message["Message-ID"]] = message
        return "OK", []


@pytest.fixture
def calendar(tmp_path):
    cfg, mailbox = settings(tmp_path), DraftMailbox()
    cfg.timezone, cfg.web.enabled, cfg.test_mode = "Europe/Berlin", True, False
    cfg.briefings.enabled, cfg.briefings.skip_empty = True, False
    def tick():
        # Close/reopen the state store on every tick, as after a process restart.
        with JsonStore(tmp_path / "data") as store:
            service = BriefingDraftService(store, lambda: cfg, ReviewViews(store, cfg.timezone),
                lambda number: ("account-1", DraftTarget(lambda: nullcontext(mailbox), "me@example.test", "Drafts")),
                lambda: "https://mailhelp.example.test")
            BriefingScheduler(store, lambda: cfg, service.deliver).tick()
            return store.load_model(STATE, BriefingState, BriefingState())
    return cfg, mailbox, tick


@pytest.mark.parametrize("day", ["2026-11-06", "2026-11-07", "2026-11-08"])
def test_three_slots_on_workdays_and_weekend_append_once_with_real_clock(calendar, day):
    cfg, mailbox, tick = calendar
    with time_machine.travel(day + "T05:59:59Z", tick=False) as clock:
        assert not tick().runs
        for hour in (6, 12, 17):
            clock.move_to(f"{day}T{hour:02}:00:00Z")
            tick()
            tick()
        state = tick()
    assert [run.label for run in sorted(state.runs.values(), key=lambda run: run.scheduled_at)] == [
        "07:00", "13:00", "18:00"]
    assert len(mailbox.messages) == 3 and all(run.status == "saved" for run in state.runs.values())
    assert state.last_briefing_at == datetime.fromisoformat(day + "T17:00:00+00:00")


@pytest.mark.parametrize("day,first,second,stamp", [
    ("2026-03-29", "00:59:59", "01:30:00", "01:30:00"),
    ("2026-10-25", "00:29:59", "00:30:00", "00:30:00"),
])
def test_missing_spring_slot_and_repeated_autumn_slot_each_append_exactly_once(calendar, day, first, second, stamp):
    cfg, mailbox, tick = calendar
    cfg.briefings.times = ["02:30"]
    with time_machine.travel(f"{day}T{first}Z", tick=False) as clock:
        assert not tick().runs
        clock.move_to(f"{day}T{second}Z")
        tick()
        clock.move_to(f"{day}T02:30:00Z")
        state = tick()
        tick()
    assert len(mailbox.messages) == len(state.runs) == 1
    assert next(iter(state.runs.values())).scheduled_at == datetime.fromisoformat(f"{day}T{stamp}+00:00")


def test_delayed_start_catches_up_today_and_never_fabricates_missed_days(calendar):
    cfg, mailbox, tick = calendar
    with time_machine.travel("2026-11-07T19:00:00Z", tick=False) as clock:
        state = tick()
        assert [run.window_start.hour for run in sorted(state.runs.values(), key=lambda run: run.scheduled_at)] == [23, 6, 12]
        clock.move_to("2026-11-09T06:00:00Z")
        state = tick()
        assert len(state.runs) == len(mailbox.messages) == 4
        clock.move_to("2026-11-08T19:00:00Z")
        tick()
        assert len(mailbox.messages) == 4


def test_changed_timezone_or_target_does_not_repeat_a_completed_local_slot(calendar):
    cfg, mailbox, tick = calendar
    cfg.briefings.times = ["07:00"]
    with time_machine.travel("2026-11-08T12:00:00Z", tick=False):
        tick()
        cfg.timezone = "UTC"
        tick()
        cfg.briefings.enabled = False
        tick()
        cfg.briefings.enabled = True
        tick()
    assert len(mailbox.messages) == 1
