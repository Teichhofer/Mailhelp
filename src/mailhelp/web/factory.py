"""Assemble the web interface from the application's components."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..config import Settings
from ..review.inbox import CommandInbox
from ..review.views import ReviewViews
from ..storage import JsonStore
from .app import WebApp
from .auth import WebAuth
from .server import EventLogger, WebServer
from .site import MailhelpSite


@dataclass(frozen=True)
class WebComponents:
    server: WebServer
    auth: WebAuth

    base_url: str = ""

    def invite(self) -> str:
        """Telegram message of /web: link to the login page with a fresh one-time code."""
        code = self.auth.issue_code()
        text = (f"🌐 Mailhelp-Weboberfläche öffnen:\n{self.base_url}/anmelden?code={code}\n\n"
                f"Code: {code[:4]} {code[4:]} – 10 Minuten gültig, für ein Gerät. Nicht weitergeben.")
        if self.base_url.startswith("http://"):
            text += ("\n\nDieser Link funktioniert nur am PC. Fürs Telefon Tailscale Serve einrichten "
                     "und den Tailnet-Namen in web.allowed_hosts eintragen.")
        return text

    def authorize(self, actor: str) -> bool:
        """Review commands from the web run only while their session exists."""
        return self.auth.active(actor.removeprefix("web:"))


def create_web(settings: Settings, secret: str | None, store: JsonStore,
               notify: Callable[[str], None], logger: EventLogger,
               commands: CommandInbox) -> WebComponents:
    if not secret:
        raise ValueError("MAILHELP_WEB_SECRET fehlt für die Weboberfläche")
    auth = WebAuth(store, secret, settings.web.session_days, notify)
    app = WebApp(settings.web.allowed_hosts)
    views = ReviewViews(store, settings.timezone, settings.test_mode)
    MailhelpSite(app, auth, settings.web, settings.timezone, logger, views, commands)
    server = WebServer(settings.web.host, settings.web.port, app, logger)
    return WebComponents(server, auth, base_url(settings))


def base_url(settings: Settings) -> str:
    """Address for links: the Tailnet name over HTTPS if configured, else the local one."""
    local = {f"127.0.0.1:{settings.web.port}", f"localhost:{settings.web.port}"}
    remote = next((host for host in settings.web.allowed_hosts if host not in local), None)
    return f"https://{remote}" if remote else f"http://127.0.0.1:{settings.web.port}"


__all__ = ["WebComponents", "base_url", "create_web"]
