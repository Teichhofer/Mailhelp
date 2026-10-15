"""Per-mail analysis captures trusted policy and isolates fingerprints and suggestions."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS

import pytest
from shared_core import prompt_config
from shared_profiles import ACCOUNT_ONE, ACCOUNT_TWO, TOPICS, settings
from shared_services import AnalyzerStub, Notify

from mailhelp.config import Settings, Topic
from mailhelp.imap import FetchedMail
from mailhelp.mailbox_settings import effective_settings
from mailhelp.models import IrrelevantSenders, MailState
from mailhelp.notifications import NotificationService
from mailhelp.orchestrator import Orchestrator
from mailhelp.storage import JsonStore

NOW = datetime(2026, 10, 14, 23, tzinfo=UTC)
RAW = b"From: chief@example.test\r\nSubject: Synthetic\r\nDate: Wed, 14 Oct 2026 10:00:00 +0000\r\n\r\nBody"


def test_two_mailboxes_capture_targets_filters_and_future_changes(tmp_path):
    cfg = settings(tmp_path)
    with JsonStore(tmp_path / "data") as store:
        analyzer = AnalyzerStub("relevant")
        notify = Notify()
        run = Orchestrator(analyzer, store, notify, 1, TOPICS, cfg.limits, targets=cfg.targets)
        run.configure_mailboxes(cfg, prompt_config(), {ACCOUNT_ONE: 1, ACCOUNT_TWO: 2})
        one = run.process(FetchedMail("INBOX", 1, 1, RAW, account_id=ACCOUNT_ONE))
        two = run.process(FetchedMail("INBOX", 1, 1, RAW + b" work", account_id=ACCOUNT_TWO))
        assert MailState.model_validate(one.state).proposals[0].target_profile == 1 and MailState.model_validate(two.state).proposals[0].target_profile == 2
        assert MailState.model_validate(two.state).proposals[0].target == "default" and MailState.model_validate(two.state).proposal_policy["mailbox_id"] == 2
        assert MailState.model_validate(one.state).proposals[0].status != "merged"
        original = MailState.model_validate(two.state).proposals[0]
        cfg.imap.mailboxes[1].target_profile = 1
        assert run.build_proposals(MailState.model_validate(two.state))[0].target_profile == 2
        next_mail = run.process(FetchedMail("INBOX", 1, 2, RAW + b" next", account_id=ACCOUNT_TWO))
        assert MailState.model_validate(next_mail.state).normalized_proposals[0].target_profile == 1
        store.save("irrelevant-senders", IrrelevantSenders(mailboxes={"2": {"addresses": ["chief@example.test"]}}).model_dump())
        filtered = run.process(FetchedMail("INBOX", 1, 3, RAW + b" blocked", account_id=ACCOUNT_TWO))
        assert MailState.model_validate(filtered.state).relevance.decision == "irrelevant" and not MailState.model_validate(filtered.state).proposals
        assert original.target_profile == 2


def test_topic_scope_change_holds_back_only_the_affected_mailbox(tmp_path):
    cfg = settings(tmp_path)
    with JsonStore(tmp_path) as store:
        run = Orchestrator(AnalyzerStub("relevant"), store, Notify(), 1, TOPICS, 1000)
        run.configure_mailboxes(cfg, prompt_config(), {ACCOUNT_ONE: 1, ACCOUNT_TWO: 2})
        before = run.fingerprint_for(ACCOUNT_ONE)
        run.topics = [TOPICS[0].model_copy(update={"mailboxes": [1]})]
        assert run.accepts_configuration(before, ACCOUNT_ONE)
        assert not run.accepts_configuration(before, ACCOUNT_TWO)
        no_topics = run.process(FetchedMail("INBOX", 1, 1, RAW, account_id=ACCOUNT_TWO))
        assert MailState.model_validate(no_topics.state).relevance.decision == "irrelevant"
        assert run.topics_for(run.fingerprint_for(ACCOUNT_TWO), ACCOUNT_TWO) == []
        assert run.mailbox_number("removed") == 1


def notification_service(store, cfg, delivered, now):
    return NotificationService(store, lambda: cfg, lambda category, number: [("telegram", "")],
        lambda _: True, lambda items, profile: delivered.append([item.reference for item in items]),
        clock=lambda: now[0], settings_for_mailbox=lambda number: effective_settings(cfg, number))


def test_quiet_hours_bundles_and_restart_keep_mailbox_policies_separate(tmp_path):
    raw = settings(tmp_path).model_dump(mode="json")
    raw["notifications"] = {"batching": {"enabled": True, "window_seconds": 1}}
    raw["imap"]["mailboxes"][1]["notifications"] = {"quiet_hours": {"enabled": True}}
    cfg = Settings.model_validate(raw)
    delivered, now = [], [NOW]
    with JsonStore(tmp_path) as store:
        svc = notification_service(store, cfg, delivered, now)
        svc.enqueue("decisions", "private", mailbox_id=1)
        svc.enqueue("decisions", "work", mailbox_id=2)
        svc.enqueue("decisions", "work-next", mailbox_id=2)
        now[0] += timedelta(seconds=2)
        svc.tick()
        assert delivered == [["private"]]
        assert [item.status for item in svc.state().entries.values()].count("deferred") == 2
    with JsonStore(tmp_path) as store:
        restarted = notification_service(store, cfg, delivered, now)
        restarted.enqueue("decisions", "work", mailbox_id=2)
        assert len(restarted.state().entries) == 3
        restarted.tick()
        assert delivered == [["private"]]
        now[0] += timedelta(hours=10)
        restarted.tick()
        assert delivered[-1] == ["work", "work-next"]


@pytest.mark.parametrize("status", ["sent", "uncertain", "sending", "pending"])
def test_upgrade_never_replays_a_delivered_global_briefing_as_mailbox_sections(tmp_path, status):
    cfg, delivered, now = settings(tmp_path), [], [NOW]
    with JsonStore(tmp_path) as store:
        svc = notification_service(store, cfg, delivered, now)
        svc.enqueue("daily_briefing", "2026-10-14")
        state = svc.state()
        old = next(iter(state.entries.values()))
        old.status = status
        store.save("notification-queue", state.model_dump(mode="json"))
        svc.enqueue("daily_briefing", "2026-10-14:2", mailbox_id=2)
        current = [item for item in svc.state().entries.values() if item.mailbox_id == 2][0]
        assert current.status == ("uncertain" if status == "sending" else status)
