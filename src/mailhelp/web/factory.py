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
from .network import lan_ip
from .server import EventLogger, WebServer
from .site import MailhelpSite


@dataclass(frozen=True)
class WebComponents:
    server: WebServer
    auth: WebAuth

    # Determined for every /web: the PC's IP address can change (DHCP).
    base_url: Callable[[], str]

    def invite(self) -> str:
        """Telegram message of /web: link to the login page with a fresh one-time code."""
        base = self.base_url()
        code = self.auth.issue_code()
        text = (f"🌐 Mailhelp-Weboberfläche öffnen:\n{base}/anmelden?code={code}\n\n"
                f"Code: {code[:4]} {code[4:]} – 10 Minuten gültig, für ein Gerät. Nicht weitergeben.")
        if base.startswith("http://127.0.0.1"):
            text += ("\n\nDieser Link funktioniert nur am PC. Fürs Telefon im selben WLAN "
                     "web.lan_access: true und web.host: 0.0.0.0 setzen (oder Tailscale Serve einrichten).")
        elif base.startswith("http://"):
            text += "\n\nNur im selben Netzwerk wie der PC erreichbar."
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
    app = WebApp(settings.web.allowed_hosts,
                 settings.web.port if settings.web.lan_access else None)
    views = ReviewViews(store, settings.timezone, settings.test_mode)
    MailhelpSite(app, auth, settings.web, settings.timezone, logger, views, commands)
    server = WebServer(settings.web.host, settings.web.port, app, logger)
    return WebComponents(server, auth, lambda: base_url(settings))


def base_url(settings: Settings, find_lan_ip: Callable[[], str | None] | None = None) -> str:
    """Address for links: the PC's IP in the home network with lan_access, else the
    Tailnet name over HTTPS if configured, else the local address."""
    address = (find_lan_ip or lan_ip)() if settings.web.lan_access else None
    if address is not None:
        return f"http://{address}:{settings.web.port}"
    local = {f"127.0.0.1:{settings.web.port}", f"localhost:{settings.web.port}"}
    remote = next((host for host in settings.web.allowed_hosts if host not in local), None)
    return f"https://{remote}" if remote else f"http://127.0.0.1:{settings.web.port}"


__all__ = ["WebComponents", "base_url", "create_web"]
