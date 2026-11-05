"""Actual local files, authentication and learning core with synthetic external services."""

from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace as NS

import pytest

from mailhelp.config import load_all
from mailhelp.configuration import ConfigurationService
from mailhelp.logging import NullLogger
from mailhelp.mailbox.imap import FetchedMail, ListedMailbox, MailCandidate
from mailhelp.processing.analysis import Analyzer
from mailhelp.review.inbox import CommandInbox
from mailhelp.review.views import ReviewViews
from mailhelp.runtime.learning_worker import LearningWorker
from mailhelp.storage import JsonStore
from mailhelp.web import WebApp
from mailhelp.web.learning_site import LearningSite
from mailhelp.web.login_site import SESSION_COOKIE
from mailhelp.web.site import MailhelpSite
from tests.fakes.initial_harness import InitialHarness
from tests.fakes.shared_core import prompt_config
from tests.fakes.shared_web_auth import Browser


class LearningClient:
    def __init__(self):
        self.policy = NS(retries=0)
        self.calls = []
        self.before = lambda: None
        self.fail = False

    def complete(self, model, parameters, system, payload, **kwargs):
        self.before()
        self.calls.append(kwargs["stage"])
        if self.fail:
            raise ConnectionError("synthetic-secret-must-not-escape")
        if kwargs["stage"] == "relevance":
            result = {"decision": "irrelevant", "topic_ids": [], "reason": "synthetic"}
        else:
            result = {"categories": [{"name": "<Newsletter>", "description": "Synthetic category"}]}
        return "synthetic-call", result


class LearningReader:
    account_id = "synthetic-account"

    def __init__(self):
        self.before = lambda: None
        self.reads = []

    def list_folders(self):
        return [
            ListedMailbox("INBOX", frozenset()),
            ListedMailbox("Archive", frozenset()),
            ListedMailbox("Junk", frozenset({"\\Junk"}), "junk"),
        ]

    def discover_since(self, folder, max_count, historical_start):
        self.before()
        return [
            MailCandidate(folder, 1, number, self.account_id, datetime(2026, 11, 1, tzinfo=UTC))
            for number in range(1, min(2, max_count) + 1)
        ]

    def fetch_uid(self, folder, uid, uidvalidity):
        self.reads.append(uid)
        self.before()
        return FetchedMail(
            folder,
            uidvalidity,
            uid,
            b"From: Synthetic <news@example.test>\nSubject: <untrusted>\n\nSynthetic content",
            self.account_id,
            datetime(2026, 11, 1, tzinfo=UTC),
        )


class LearningHarness:
    def __init__(self, initial):
        self.initial = initial
        initial.advance()
        initial.setup.finish(initial.actor, initial.setup.state().version, "f" * 32)
        self.directory, self.store, self.auth = initial.directory, initial.store, initial.auth
        settings, secrets, topics, _, _, _ = load_all(self.directory, initial.setup.environment())
        self.client, self.reader = LearningClient(), LearningReader()
        self.configuration = ConfigurationService(
            self.directory, self.store, settings, self.auth.active, lambda _: None
        )
        self.app = NS(
            settings=settings,
            configuration=self.configuration,
            store=self.store,
            sender_store=JsonStore(self.directory),
            analyzer=Analyzer(self.client, prompt_config()),
            openrouter=self.client,
            orchestrator=NS(topics=topics),
        )
        self.web = WebApp(settings.web.allowed_hosts)
        self.site = MailhelpSite(
            self.web,
            self.auth,
            settings.web,
            settings.timezone,
            NullLogger(),
            ReviewViews(self.store, settings.timezone),
            CommandInbox(self.store),
            configuration=self.configuration,
        )

        @contextmanager
        def reader(*_):
            yield self.reader

        self.worker = LearningWorker(self.app, self.site, secrets, reader)
        self.jobs = self.worker.jobs
        LearningSite(self.site, self.worker)
        self.browser = Browser(self.web, host="localhost:8765")
        self.browser.cookies[SESSION_COOKIE] = initial.token
        self.actor = initial.actor
        self.sequence = 0
        self.selection = dict(mailbox=1, folders=["INBOX"], count=2, budget_usd=1000, usd_per_million_tokens=0.001)

    def change(self, action, payload=None, **kw):
        self.sequence += 1
        return self.jobs.change(
            kw.get("actor", self.actor),
            kw.get("version", self.jobs.state().version),
            kw.get("key", f"{self.sequence:032x}"),
            action,
            payload or {},
        )

    def review(self):
        self.change("start", self.selection)
        while self.worker.tick():
            pass
        return self.jobs.state()


@pytest.fixture
def learning(tmp_path, monkeypatch):
    import os

    for name in list(os.environ):
        if name.startswith(("GOOGLE_", "MICROSOFT_", "IMAP_", "OPENROUTER_", "TODOIST_", "MAILHELP_WEB_")):
            monkeypatch.delenv(name)
    initial = InitialHarness(tmp_path)
    try:
        yield LearningHarness(initial)
    finally:
        initial.close()
