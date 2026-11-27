"""Shared central-service fixture and HTML form inspection."""
import re
from html import unescape
from urllib.parse import urlsplit

import pytest

from tests.fakes.hosted_google import Central


@pytest.fixture
def central(tmp_path):
    hub = Central(tmp_path)
    yield hub
    hub.close()


def fields(html, action):
    block = re.search(rf'<form method="post" action="{re.escape(action)}"[^>]*>(.*?)</form>', html, re.S)[1]
    return {name: unescape(value) for name, value in re.findall(r'name="([^"]+)" value="([^"]*)"', block)}


class Profiles:
    """Setup drafts of target profiles 1 and 2 as a test double of the setup flows."""

    def __init__(self):
        self.connections = {1: "", 2: ""}
        self.version = 1
        self.saved: list[tuple] = []

    def draft(self, profile):
        if profile not in self.connections:
            raise LookupError(profile)
        return self.connections[profile], self.version

    def save(self, actor, profile, values, version, key):
        if version != self.version:
            raise ValueError("Entwurf geändert")
        self.saved.append((actor, profile, values, version))
        self.connections[profile] = values.get("google_connection", self.connections[profile])
        self.version += 1

    def target(self, profile):
        self.draft(profile)
        return f"profile:{profile}"


def connect(web, profile=1, code="good"):
    """Start, Google's consent and the return to the instance; returns the completion page."""
    page = web.browser.request("GET", f"/google/verbinden?profile={profile}").body.decode()
    started = web.browser.request("POST", "/google/verbinden", fields(page, "/google/verbinden"))
    assert started.status == 303 and started.headers["Cache-Control"] == "no-store"
    back = web.central.google_return(started.headers["Location"], code)
    assert back.startswith("https://anna.inboxstride.example/einrichtung/google/abschluss?")
    parts = urlsplit(back)
    return web.browser.request("GET", f"{parts.path}?{parts.query}")
