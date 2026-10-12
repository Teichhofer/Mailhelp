"""Shared synthetic fixtures and doubles; no test-module dependencies."""
from __future__ import annotations

import re
from datetime import UTC, datetime
from urllib.parse import urlencode

import pytest

from mailhelp.config import WebSettings
from mailhelp.review.inbox import CommandInbox
from mailhelp.review.views import ReviewViews
from mailhelp.storage import JsonStore
from mailhelp.web import Request, WebApp
from mailhelp.web.auth import (
    WebAuth,
)
from mailhelp.web.site import FORM_TYPE, MailhelpSite

LOCAL = "127.0.0.1:8765"

TAILNET = "mailhelp-pc.tail.ts.net"

SECRET = "s" * 40

IPHONE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
          "(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1")

class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 11, 12, tzinfo=UTC)

    def __call__(self):
        return self.now

class Logger:
    def __init__(self):
        self.events = []

    def event(self, level, module, event, **fields):
        self.events.append((level, event, fields))

def code_from(messages):
    return re.search(r"Code (\d{4})", messages[-1]).group(1)

@pytest.fixture
def auth(tmp_path):
    messages, clock = [], Clock()
    with JsonStore(tmp_path) as store:
        service = WebAuth(store, SECRET, 30, messages.append, clock)
        service.messages, service.clock_ = messages, clock
        yield service

def pair(auth, device="PC", browser="browser"):
    auth.request_code(browser, device)
    return auth.redeem(browser, code_from(auth.messages), device)

class Browser:
    """A minimal cookie-keeping client for the in-process web app."""

    def __init__(self, app, host=LOCAL, agent=IPHONE):
        self.app, self.host, self.agent, self.cookies = app, host, agent, {}

    def request(self, method, path, form=None, content_type=FORM_TYPE, **headers):
        cookie = "; ".join(f"{name}={value}" for name, value in self.cookies.items())
        base = {"host": self.host, "user-agent": self.agent, "cookie": cookie}
        body = urlencode(form or {}).encode() if form is not None else b""
        if form is not None:
            base["content-type"] = content_type
        path, _, query = path.partition("?")
        response = self.app(Request(method, path, {**base, **headers}, query=query, body=body))
        for line in response.cookies:
            name, value = line.split(";")[0].split("=", 1)
            if "Max-Age=0" in line:
                self.cookies.pop(name, None)
            else:
                self.cookies[name] = value
        return response

    def csrf(self, path="/anmelden"):
        page = self.request("GET", path).body.decode()
        return re.search(r'name="csrf" value="([^"]+)"', page).group(1)

@pytest.fixture
def site(tmp_path):
    messages, logger = [], Logger()
    with JsonStore(tmp_path) as store:
        auth = WebAuth(store, SECRET, 30, messages.append)
        app = WebApp([LOCAL, TAILNET])
        MailhelpSite(app, auth, WebSettings(allowed_hosts=[LOCAL, TAILNET]), "Europe/Berlin", logger,
                     ReviewViews(store, "Europe/Berlin"), CommandInbox(store))
        app.messages, app.logger, app.auth = messages, logger, auth
        yield app

def signed_in(site, host=LOCAL, device=""):
    browser = Browser(site, host)
    csrf = browser.csrf()
    assert browser.request("POST", "/anmelden/code", {"csrf": csrf}).headers["Location"] == "/anmelden"
    response = browser.request("POST", "/anmelden", {"csrf": csrf, "code": code_from(site.messages),
                                                     "geraet": device})
    assert response.status == 303 and response.headers["Location"] == "/"
    return browser, response

class Telegram:
    def __init__(self):
        self.sent = []

    def send(self, chat_id, text, reply_markup=None):
        self.sent.append(text)
