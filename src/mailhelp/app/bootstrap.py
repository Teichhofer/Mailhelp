"""Start the protected setup server without creating any production adapters."""
from __future__ import annotations

import hashlib
import os
import secrets
from collections.abc import Callable
from pathlib import Path
from threading import Event
from typing import Any

from ..config import Settings, WebSettings
from ..config.loader import _dotenv
from ..config.target_settings import HostedAuthSettings
from ..external.hosted_oauth import cached_client
from ..i18n import tr
from ..logging import JsonlLogger
from ..persistence.storage import JsonStore, atomic_replace
from ..runtime.initial_setup import InitialSetup
from ..runtime.oauth_web import BrowserOAuth, oauth_config
from ..runtime.onboarding import OnboardingService
from ..runtime.setup_checks import SetupChecks
from ..web.app import WebApp
from ..web.auth import WebAuth
from ..web.hosted_google_site import HostedGoogleSite, HostedProfiles
from ..web.hosted_targets_site import HostedTargetContext, HostedTargetsSite
from ..web.initial_site import InitialSite
from ..web.oauth_site import OAuthSite
from ..web.onboarding_site import OnboardingSite
from ..web.server import WebServer
from .mailbox_accounts import attach_initial_mailbox


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

    def calendar_context(profile: int, field: str = "google_calendar") -> tuple[str, int]:
        if profile != 1:
            raise ValueError("Ersteinrichtung verwendet Zielprofil 1.")
        state = setup.state()
        return str(state.config["targets"].get(field, "@default")), state.version

    def save_calendar(actor: str, profile: int, calendar: str, version: int, key: str,
                      field: str = "google_calendar") -> None:
        calendar_context(profile, field)
        setup.save(actor, {"step": "4", "version": str(version), "key": key, "targets." + field: calendar})

    def hosted_draft(profile: int) -> tuple[str, int]:
        if profile != 1:
            raise LookupError("Ersteinrichtung verwendet Zielprofil 1.")
        state = setup.state()
        return str(state.config["targets"].get("google_connection", "")), state.version

    def hosted_save(actor: str, profile: int, values: dict[str, str], version: int, key: str) -> None:
        hosted_draft(profile)
        setup.save(actor, {"step": "4", "version": str(version), "key": key,
                           **{"targets." + field: value for field, value in values.items()}})

    def hosted_target(profile: int) -> str:
        # 8.0: before config.yaml exists, the sign-in is bound to this installation's setup draft.
        hosted_draft(profile)
        return "draft:" + hashlib.sha256(str(directory.resolve()).encode("utf-8")).hexdigest()[:32]

    def hosted_settings() -> HostedAuthSettings:
        return Settings.model_validate(setup.state().config).hosted_auth

    client = cached_client(hosted_settings)
    OAuthSite(site, oauth, calendar_context, save_calendar)
    HostedGoogleSite(site, store, client,
                     HostedProfiles(hosted_draft, hosted_save, hosted_target), "/einrichtung/start", navigation=False)
    HostedTargetsSite(site, store, client,
                      HostedTargetContext(calendar_context, hosted_save, hosted_target), "/einrichtung/start",
                      navigation=False)
    OnboardingSite(site, OnboardingService(directory, store, authorize, sign), "/einrichtung/start", navigation=False)
    attach_initial_mailbox(site, setup, store)
    return WebServer(settings.host, settings.port, app, logger), auth, setup, oauth


def console(text: str) -> None:
    """First-run codes must reach piped terminals and container logs immediately."""
    print(text, flush=True)


def run_initial_setup(directory: Path, shutdown: Any, *, emit: Callable[[str], None] = console) -> int:
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
            emit(tr("Mailhelp-Ersteinrichtung: http://localhost:{port}/anmelden", port=port))
            emit(tr("Authentifizierungscode: {code} – 10 Minuten gültig, einmal verwendbar.", code=auth.issue_code()))
            stopped.wait()
        finally:
            stopped.set()
            oauth.wake.set()
            worker.join(timeout=20)
            server.stop()
        return 75 if setup.state().status == "done" else 0
