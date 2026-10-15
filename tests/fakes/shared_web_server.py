"""Shared synthetic fixtures and doubles; no test-module dependencies."""
from __future__ import annotations

import http.client
from pathlib import Path
from threading import Event

import pytest
from shared_application import Log, Orch
from shared_application import settings as app_settings

from mailhelp.application import Application
from mailhelp.web import Request, WebApp, WebServer

HOST = "127.0.0.1:8765"

def get(app, path, host=HOST, method="GET", **headers):
    return app(Request(method, path, {"host": host, **headers}))

class Logger:
    def __init__(self):
        self.events = []

    def event(self, level, module, event, **fields):
        self.events.append((level, module, event, fields))

@pytest.fixture
def running():
    servers = []

    def start(handler=None, **kwargs):
        logger = Logger()
        server = WebServer("127.0.0.1", 0, handler or WebApp([HOST]), logger, **kwargs)
        server.start()
        servers.append(server)
        return server, logger

    yield start
    for server in servers:
        server.stop()

def call(server, method, path, body=None, headers=None):
    connection = http.client.HTTPConnection(*server.address, timeout=5)
    try:
        connection.request(method, path, body=body, headers={"Host": HOST, **(headers or {})})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()

def write_config(directory: Path) -> dict[str, str]:
    for name in ("config.yaml", "prompts.yaml", "topics.yaml", "irrelevant_topics.yaml"):
        source = Path("config.example.yaml" if name == "config.yaml" else name)
        (directory / name).write_text(source.read_text(encoding="utf8"), encoding="utf8")
    return {name: "secret" for name in [
        "IMAP_USERNAME", "IMAP_PASSWORD", "OPENROUTER_API_KEY", "TELEGRAM_BOT_TOKEN", "TODOIST_TOKEN",
        "TODOIST_CLIENT_ID", "TODOIST_CLIENT_SECRET", "GOOGLE_OAUTH_CLIENT_ID",
        "GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_OAUTH_REFRESH_TOKEN"]}

class Telegram:
    def __init__(self, error=None):
        self.sent, self.error = [], error

    def send(self, chat_id, text):
        if self.error:
            raise self.error
        self.sent.append(text)

class FakeWeb:
    def __init__(self, error=None):
        self.error, self.calls = error, []

    def start(self):
        self.calls.append("start")
        if self.error:
            raise self.error

    def stop(self):
        self.calls.append("stop")

def lifecycle_app(tmp_path, web, telegram):
    application = Application(app_settings(tmp_path), object(), Log(), object(), object(), object(),
                              telegram, object(), object(), Orch(), Event())
    application.web = web
    return application
