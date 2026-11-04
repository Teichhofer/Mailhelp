"""Start the protected setup server without creating any production adapters."""
from __future__ import annotations

import os
import secrets
from collections.abc import Callable
from pathlib import Path
from threading import Event
from typing import Any

from ..config import Settings, WebSettings
from ..config.loader import _dotenv
from ..logging import JsonlLogger
from ..storage import JsonStore, atomic_replace
from ..web.app import WebApp
from ..web.auth import WebAuth
from ..web.initial_site import InitialSite
from ..web.oauth_site import OAuthSite
from ..web.server import WebServer
from .initial_setup import InitialSetup
from .oauth_web import BrowserOAuth, oauth_config
from .setup_checks import SetupChecks


def ensure_web_secret(directory: Path) -> str:
    path = directory / ".env"
    env = {**_dotenv(path), **os.environ}
    secret = env.get("MAILHELP_WEB_SECRET", "") or secrets.token_urlsafe(48)
    if len(secret) < 32 or any(ord(c) < 32 for c in secret):
        raise ValueError("MAILHELP_WEB_SECRET muss mindestens 32 Zeichen ohne Steuerzeichen besitzen.")
    if not env.get("MAILHELP_WEB_SECRET"):
        content = path.read_text(encoding="utf-8") if path.exists() else ""
        atomic_replace(path, content.rstrip("\n") + "\nMAILHELP_WEB_SECRET=" + secret + "\n")
    return secret


def create_initial(directory: Path, store: JsonStore, settings: WebSettings, stopped: Event,
                   logger: Any) -> tuple[WebServer, WebAuth, InitialSetup, BrowserOAuth]:
    secret = ensure_web_secret(directory)
    auth = WebAuth(store, secret, settings.session_days, lambda text: None)
    auth.channel = "console"
    authorize = lambda actor: actor.startswith("web:") and auth.active(actor.removeprefix("web:"))
    sign = lambda value: auth._mac("initial-setup", value)
    setup = InitialSetup(directory, store, authorize, sign, SetupChecks(directory), settings.model_dump())
    if not (store.directory / "initial-setup.json").exists():
        setup._save(setup.state())
    app = WebApp(settings.allowed_hosts, settings.port if settings.lan_access else None)
    site = InitialSite(app, auth, settings, logger, setup, stopped.set)
    oauth = BrowserOAuth(directory, store, authorize,
        lambda profile, provider: oauth_config(Settings.model_validate(setup.state().config), setup.environment(),
                                                profile, provider), sign, stopped=stopped,
        changed=setup.credentials_changed)

    def calendar_context(profile: int) -> tuple[str, int]:
        if profile != 1:
            raise ValueError("Ersteinrichtung verwendet Zielprofil 1.")
        state = setup.state()
        return str(state.config["targets"]["google_calendar"]), state.version

    def save_calendar(actor: str, profile: int, calendar: str, version: int, key: str) -> None:
        calendar_context(profile)
        setup.save(actor, {"step": "4", "version": str(version), "key": key, "targets.google_calendar": calendar})

    OAuthSite(site, oauth, calendar_context, save_calendar)
    return WebServer(settings.host, settings.port, app, logger), auth, setup, oauth


def run_initial_setup(directory: Path, shutdown: Any, *, emit: Callable[[str], None] = print) -> int:
    directory.mkdir(parents=True, exist_ok=True)
    port = int(os.environ.get("MAILHELP_SETUP_PORT", "8765"))
    host = os.environ.get("MAILHELP_SETUP_HOST", "0.0.0.0")
    settings = WebSettings(enabled=True, host=host, port=port, lan_access=host == "0.0.0.0",
        allowed_hosts=[f"localhost:{port}", f"127.0.0.1:{port}",
                       *filter(None, os.environ.get("MAILHELP_SETUP_ALLOWED_HOSTS", "").split(","))])
    stopped = Event()
    shutdown.stop = stopped.set
    with JsonStore(directory / "data" / "production") as store:
        logger = JsonlLogger(directory / "logs", console_enabled=False)
        server, auth, setup, oauth = create_initial(directory, store, settings, stopped, logger)
        server.start()
        worker = oauth.start_worker()
        try:
            emit(f"Mailhelp-Ersteinrichtung: http://localhost:{port}/anmelden")
            emit(f"Authentifizierungscode: {auth.issue_code()} – 10 Minuten gültig, einmal verwendbar.")
            stopped.wait()
        finally:
            stopped.set()
            oauth.wake.set()
            worker.join(timeout=20)
            server.stop()
        return 75 if setup.state().status == "done" else 0
