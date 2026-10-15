"""Postfach policies reach drafts, report inputs, filters and full-text retention."""
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace as NS

import pytest
from activity_fakes import Model, activity_prompts, definition, raw_mail
from shared_profiles import ACCOUNT_TWO, settings
from shared_retention import state
from shared_telegram_dialog import proposal

from mailhelp.activity.llm import ActivityAnalyzer
from mailhelp.activity.models import FolderProgress, ReportStatus
from mailhelp.activity.scan import read_mail
from mailhelp.activity.service import ActivityService
from mailhelp.activity.store import ActivityReportStore
from mailhelp.analysis import Analyzer
from mailhelp.application import Application
from mailhelp.drafts import DraftService
from mailhelp.imap import FetchedMail
from mailhelp.logging import NullLogger
from mailhelp.models import IrrelevantSenders
from mailhelp.storage import JsonStore


def test_report_snapshots_scoped_allow_filter_and_uses_work_signature(tmp_path):
    cfg = settings(tmp_path)
    rules = IrrelevantSenders(domains=["example.test"], mailboxes={"2": {"addresses": ["digest@work.test"], "allow": ["chief@example.test"]}})
    with JsonStore(tmp_path) as store:
        service = ActivityService(ActivityReportStore(store))
        service.mailbox_senders = lambda _: rules
        item = service.create(definition(mailbox=2), [], [])
        item.status = ReportStatus.READY
        service.store.save(item)
        item = service.act(item.id, item.version, "start-0001", "start")
        assert item.allowed_addresses == ["chief@example.test"] and item.blocked_addresses == ["digest@work.test"]
        progress = FolderProgress(folder="INBOX", uidvalidity=1)
        mail, _ = read_mail(item, progress, FetchedMail("INBOX", 1, 1, raw_mail("Work", "Body", sender="chief@example.test")), cfg.limits, "UTC", 1000)
        assert mail.skipped is None
        model = Model(activity_relevance={"relevant": True, "confidence": "high", "reason": "synthetic"})
        analyzer = ActivityAnalyzer(Analyzer(model, activity_prompts()), mailbox_personal_info=lambda number: f"Signature {number}")
        analyzer.relevance(item, mail, date(2026, 1, 10))
        assert model.requests[0][1]["personal_info"] == "Signature 2"
        service.mailbox_senders = lambda _: IrrelevantSenders()
        other = service.create(definition(mailbox=1), [], [])
        other.status = ReportStatus.READY
        service.store.save(other)
        assert service.act(other.id, other.version, "start-0002", "start").allowed_addresses == []


def test_disabled_mailbox_drafts_cannot_be_generated_even_by_old_form(tmp_path):
    with JsonStore(tmp_path) as store:
        mail = state("a" * 24)
        store.save("mail-" + mail.id, mail.model_dump(mode="json"))
        svc = DraftService(store, lambda _: True, lambda: None, "me@example.test", "Drafts", True,
            mailbox_policy=lambda _: (False, "Work"))
        assert not svc.available(mail.id)
        with pytest.raises(ValueError, match="ausgeschaltet"):
            svc.generate("actor", mail.id, 0, "draft-0001", "accept")


def test_maintenance_selects_captured_origin_and_only_shortens_full_mail_retention(tmp_path):
    cfg = settings(tmp_path)
    cfg.imap.mailboxes[1].retention = cfg.imap.mailboxes[1].model_validate(
        {**cfg.imap.mailboxes[1].model_dump(), "retention": {"full_mail_days": 1}}).retention
    with JsonStore(tmp_path) as store:
        for identifier, number in (("a" * 24, 1), ("b" * 24, 2), ("c" * 24, 99)):
            mail = state(identifier, age=0)
            mail.updated_at = datetime.now(UTC) - timedelta(days=2)
            mail.created_at = mail.updated_at - timedelta(days=1)
            mail.proposal_policy = {"mailbox_id": number}
            store.save("mail-" + identifier, mail.model_dump(mode="json"))
        app = NS(settings=cfg, store=store, logger=NullLogger(),
            orchestrator=NS(mailbox_settings=cfg, mailbox_number=lambda _: 1))
        Application._maintain(app)
        assert store.load("mail-" + "b" * 24)["mail"] is None
        assert store.load("mail-" + "a" * 24)["mail"] is not None
        assert store.load("mail-" + "c" * 24)["mail"] is not None
        app.orchestrator.mailbox_settings = None
        Application._maintain(app)
