"""Shared first-run harness; every network probe is synthetic."""
import os
from pathlib import Path
from threading import Event

import pytest

from mailhelp.config import WebSettings
from mailhelp.logging import NullLogger
from mailhelp.runtime.bootstrap import create_initial
from mailhelp.storage import JsonStore


class SyntheticChecks:
    def __init__(self):
        self.calls = []

    def imap(self, settings, env):
        self.calls.append("imap")
        return {"folders": ["INBOX", "Entwürfe"], "inbox": "INBOX", "drafts": "Entwürfe"}

    def llm(self, settings, env, prompts):
        self.calls.append("llm")
        return {"models": ["synthetic:latest"], "balance": 10}

    def targets(self, settings, env):
        self.calls.append("targets")
        return {"ready": True}


class InitialHarness:
    def __init__(self, directory: Path):
        self.directory = directory
        self.store = JsonStore(directory / "data/production")
        self.store.__enter__()
        self.stopped = Event()
        self.server, self.auth, self.setup, self.oauth = create_initial(
            directory, self.store, WebSettings(enabled=True), self.stopped, NullLogger())
        self.app = self.server.handler
        self.checks = self.setup.checks = SyntheticChecks()
        self.code = self.auth.issue_code()
        self.token = self.auth.redeem("synthetic-browser", self.code, "Synthetic")
        self.session = self.auth.authenticate(self.token)
        self.actor = "web:" + self.session.id
        self.sequence = 0

    def close(self):
        self.store.__exit__(None, None, None)

    def form(self, step, **values):
        self.sequence += 1
        return {"step": str(step), "version": str(self.setup.state().version), "key": f"{self.sequence:032x}",
                "csrf": self.auth.csrf_token(self.session.id), **values}

    def advance(self, local=False):
        self.setup.save(self.actor, self.form(1, timezone="Europe/Berlin", password="synthetic-password"))
        self.setup.save(self.actor, self.form(2, **{"imap.host": "imap.example.test", "imap.drafts_folder": "Entwürfe",
            "IMAP_USERNAME": "user@example.test", "IMAP_PASSWORD": "synthetic-imap-password"}))
        self.setup.save(self.actor, self.form(3, **{"llm.provider": "ollama" if local else "openrouter",
            "model": "synthetic:latest", "OPENROUTER_API_KEY": "synthetic-router-key"}))
        self.setup.save(self.actor, self.form(4, **{"GOOGLE_OAUTH_CLIENT_ID": "synthetic-client",
            "GOOGLE_OAUTH_CLIENT_SECRET": "synthetic-client-secret", "GOOGLE_OAUTH_REFRESH_TOKEN": "synthetic-refresh",
            "TODOIST_TOKEN": "synthetic-todoist-token"}))


@pytest.fixture
def initial(tmp_path, monkeypatch):
    for name in list(os.environ):
        if name.startswith(("GOOGLE_", "MICROSOFT_", "IMAP_", "OPENROUTER_", "TODOIST_", "MAILHELP_WEB_")):
            monkeypatch.delenv(name)
    harness = InitialHarness(tmp_path)
    yield harness
    harness.close()
