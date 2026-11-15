"""A synthetic analysed mail reaches the real durable queue and a simulated provider."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from mailhelp.config import Settings, read_yaml
from mailhelp.domain.extraction import ExtractedEvent
from mailhelp.domain.mail import ActionRoute, EventExtraction
from mailhelp.domain.proposal import ProposalStatus
from mailhelp.mailbox.imap import FetchedMail
from mailhelp.notifications.notification_runtime import NotificationRuntime
from mailhelp.notifications.webpush import PushService
from mailhelp.processing.orchestrator import Orchestrator
from mailhelp.review.commands import CommandKind, CommandSource, ReviewCommand
from mailhelp.review.revision_origin import revision_origin
from tests.fakes.factories import build_proposal
from tests.fakes.push68 import subscription
from tests.fakes.shared_services import AnalyzerStub
from tests.scenarios.web_scenario import mail_id, save_mail


def install(configured, empty=False):
    app, web = configured.app, configured.web
    if empty:
        for prefix in ("proposal-", "mail-", "history-", "analysis-"):
            for name in web.store.names(prefix):
                web.store.delete(name)
    template = Settings.model_validate(read_yaml(Path("src/mailhelp/defaults/initial-config.yaml")))
    app.settings.notifications = template.notifications
    app.settings.push.enabled = True
    app.settings.daily_briefing.enabled = False
    sent = []
    push = PushService(web.store, web.auth, "mailto:ops@example.test", lambda **kw: sent.append(kw))
    web.site.experience.push = push
    runtime = NotificationRuntime(app, web.site)
    return app, web, runtime, push, sent


def test_regression_newly_activated_device_does_not_receive_existing_decisions(configured):
    app, web, runtime, push, sent = install(configured)
    push.change(web.auth.sessions()[0].id, "subscribe-001", subscription())
    runtime.tick()
    assert sent == []
    item = build_proposal(source_mail_id=mail_id(90), id="new-task")
    save_mail(web.store, 90, "Synthetic <s@example.test>", "Synthetic new mail", [item])
    web.dialog.persist(item)
    runtime.tick()
    assert len(sent) == 1 and json.loads(sent[0]["data"]) == {"tag": "decisions"}
    NotificationRuntime(app, web.site).tick()
    assert len(sent) == 1


@pytest.mark.parametrize("source", [CommandSource.WEB, CommandSource.TELEGRAM])
def test_regression_own_version_is_silent_and_system_followup_is_not(configured, source):
    app, web, runtime, push, sent = install(configured, empty=True)
    push.change(web.auth.sessions()[0].id, "subscribe-001", subscription())
    item = build_proposal(
        source_mail_id=mail_id(91),
        id="question",
        open_questions=["Synthetic question?"],
        status=ProposalStatus.NEEDS_CLARIFICATION,
    )
    save_mail(web.store, 91, "Synthetic <s@example.test>", "Synthetic", [item])
    web.dialog.persist(item)
    runtime.tick()
    assert len(sent) == 1
    sid = web.auth.sessions()[0].id
    answer_result = web.dialog.review.execute(
        ReviewCommand(
            kind=CommandKind.ANSWER,
            source=source,
            actor="web:" + sid if source == CommandSource.WEB else "telegram:1:2",
            mail_id=item.source_mail_id,
            proposal_id=item.id,
            version=1,
            idempotency_key="answer-synthetic-01",
            text="Synthetic answer",
        ),
        raise_errors=True,
    )
    revised = web.dialog.repository.load_current(item.source_mail_id, item.id)
    assert revised.version == 2, answer_result
    runtime.tick()
    assert len(sent) == 1
    with revision_origin("system"):
        web.dialog.persist(item.model_copy(update={"version": 3}))
    runtime.tick()
    assert len(sent) == 2
    NotificationRuntime(app, web.site).tick()
    assert len(sent) == 2


@pytest.mark.parametrize("kind", ["task", "event", "change", "cancellation", "relevance"])
def test_template_mail_analysis_open_decision_queue_and_provider(configured, kind):
    app, web, runtime, push, sent = install(configured)
    push.change(web.auth.sessions()[0].id, "subscribe-001", subscription())

    class Analyzer(AnalyzerStub):
        def action_route(self, mail):
            if kind == "task":
                return super().action_route(mail)
            return "route", ActionRoute(action_state="event", task_count=0, event_count=1, reason="Synthetic")

        def extract_events(self, mail, *, expected_count):
            return "events", EventExtraction(
                events=[
                    ExtractedEvent(
                        title="Synthetic event",
                        evidence="Synthetic",
                        date_text="20.12.2026",
                        time_text=None,
                        time_requirement="required_unknown",
                        responsibility="user",
                        certainty="certain",
                        classification="new" if kind == "event" else kind,
                    )
                ]
            )

    notifier = SimpleNamespace(
        send=web.telegram.send, send_proposal=web.dialog.send_proposal, send_relevance=web.dialog.relevance.open
    )
    # Opening relevance is handled by the real orchestrator's MailQuestions port.
    analyzer = Analyzer("unclear" if kind == "relevance" else "relevant")
    processor = Orchestrator(analyzer, web.store, notifier, 2, [], 100_000)
    result = processor.process(FetchedMail("INBOX", 1, 100, b"From: s@example.test\nSubject: Synthetic\n\nSynthetic"))
    overview = web.site.views.overview()
    assert overview.relevance if kind == "relevance" else overview.open
    runtime.tick()
    assert len(sent) == 1 and json.loads(sent[0]["data"]) == {"tag": "decisions"}
    runtime.tick()
    assert len(sent) == 1
    assert result.state["id"] and web.writer.created == 0


def test_two_devices_mailbox_override_batching_quiet_hours_and_restart(configured):
    from datetime import UTC, datetime, timedelta

    from mailhelp.config.models import ImapSettings, MailboxSettings

    app, web, runtime, push, sent = install(configured)
    app.settings.imap = ImapSettings(
        mailboxes=[
            MailboxSettings(
                id=number,
                host="synthetic.test",
                port=993,
                folders=["INBOX"],
                notifications={"categories": {"decisions": []}} if number == 2 else None,
            )
            for number in (1, 2)
        ]
    )
    first = web.auth.sessions()[0].id
    push.change(first, "subscribe-001", subscription())
    token = web.auth.redeem("synthetic-second-browser", web.auth.issue_code(), "Synthetic device")
    second = web.auth.authenticate(token)
    push.change(second.id, "subscribe-002", subscription())
    profile = app.settings.notifications
    profile.quiet_hours.enabled = True
    profile.batching.enabled = True
    clock = [datetime(2026, 11, 14, 23, tzinfo=UTC)]
    runtime.queue.clock = lambda: clock[0]
    for number in (92, 93, 94):
        item = build_proposal(source_mail_id=mail_id(number), id="new-task")
        save_mail(
            web.store,
            number,
            "Synthetic <s@example.test>",
            "Synthetic",
            [item],
            proposal_policy={"mailbox_id": 2 if number == 94 else 1},
        )
        web.dialog.persist(item)
    runtime.tick()
    assert sent == []
    pending = [entry for entry in runtime.queue.state().entries.values() if entry.channel == "web_push"]
    assert len(pending) == 4 and {entry.mailbox_id for entry in pending} == {1}
    clock[0] += timedelta(hours=12)
    runtime.tick()
    assert len(sent) == 2  # One batch per device, containing two decisions.
    restarted = NotificationRuntime(app, web.site)
    restarted.queue.clock = lambda: clock[0]
    restarted.tick()
    assert len(sent) == 2
