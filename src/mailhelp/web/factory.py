"""Assemble the web interface from the application's components."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..config import Settings
from ..storage import JsonStore
from .app import WebApp
from .auth import WebAuth
from .server import EventLogger, WebServer
from .site import MailhelpSite


@dataclass(frozen=True)
class WebComponents:
    server: WebServer
    auth: WebAuth

    def authorize(self, actor: str) -> bool:
        """Review commands from the web run only while their session exists."""
        return self.auth.active(actor.removeprefix("web:"))


def create_web(settings: Settings, secret: str | None, store: JsonStore,
               notify: Callable[[str], None], logger: EventLogger) -> WebComponents:
    if not secret:
        raise ValueError("MAILHELP_WEB_SECRET fehlt für die Weboberfläche")
    auth = WebAuth(store, secret, settings.web.session_days, notify)
    app = WebApp(settings.web.allowed_hosts)
    MailhelpSite(app, auth, settings.web, settings.timezone, logger)
    server = WebServer(settings.web.host, settings.web.port, app, logger)
    return WebComponents(server, auth)


__all__ = ["WebComponents", "create_web"]
