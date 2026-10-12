"""Shared synthetic fixtures and doubles; no test-module dependencies."""
from __future__ import annotations

import re
from html import unescape

import pytest
from shared_telegram_dialog import Logger, Telegram, Writer
from shared_web_auth import LOCAL, SECRET, Browser, code_from
from web_scenario import Revisions, mail_id, populate

from mailhelp.config import WebSettings
from mailhelp.review.inbox import CommandInbox
from mailhelp.review.views import ReviewViews
from mailhelp.storage import JsonStore
from mailhelp.telegram import TelegramDialogController
from mailhelp.web import WebApp
from mailhelp.web.auth import WebAuth
from mailhelp.web.site import MailhelpSite

MAIL1 = mail_id(1)

class Web:
    """Web app, Mailhelp main thread (driven by run()) and a signed-in browser."""

    def __init__(self, store: JsonStore):
        self.store, self.telegram, self.writer = store, Telegram(), Writer()
        self.commands = CommandInbox(store)
        self.dialog = TelegramDialogController(
            store, self.telegram, 1, 2, Logger(), {"todoist": self.writer, "google_calendar": self.writer},
            False, "Europe/Berlin", Revisions(), commands=self.commands)
        messages = []
        self.auth = WebAuth(store, SECRET, 30, messages.append)
        self.dialog.review.web_authorizer = lambda actor: self.auth.active(actor.removeprefix("web:"))
        self.logger = Logger()
        self.app = WebApp([LOCAL])
        self.site = MailhelpSite(self.app, self.auth, WebSettings(), "Europe/Berlin", self.logger,
                     ReviewViews(store, "Europe/Berlin"), self.commands)
        self.browser = Browser(self.app)
        csrf = self.browser.csrf()
        self.browser.request("POST", "/anmelden/code", {"csrf": csrf})
        self.browser.request("POST", "/anmelden", {"csrf": csrf, "code": code_from(messages)})

    def run(self):
        """One cycle of the main thread."""
        self.dialog.poll_once()

    def form(self, path: str, *, action: str = "/aktion", index: int = 0, **match: str) -> dict:
        """Fields of the index-th form for the given action whose hidden fields match."""
        html = self.browser.request("GET", path).body.decode()
        forms = []
        for block in re.findall(r'<form method="post" action="([^"]+)"[^>]*>(.*?)</form>', html, re.S):
            if block[0] != action:
                continue
            fields = {name: unescape(value) for name, value in
                      re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)">', block[1])}
            if all(fields.get(name) == value for name, value in match.items()):
                forms.append(fields)
        return forms[index]

    def submit(self, fields: dict, **headers):
        return self.browser.request("POST", "/aktion", fields, **headers)

@pytest.fixture
def web(tmp_path, monkeypatch):
    # Without a running main thread, waiting for a quick result only slows tests down.
    monkeypatch.setattr("mailhelp.web.site.SETTLE_SECONDS", 0)
    with JsonStore(tmp_path) as store:
        populate(store)
        yield Web(store)
