"""Attach OAuth and calendar-selection drafts to an already configured application."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..config import Settings, read_yaml
from ..config.loader import _dotenv
from ..external.hosted_oauth import cached_client
from ..mailbox.mailbox_settings import target_profiles
from ..runtime.oauth_web import BrowserOAuth, OAuthConfig, oauth_config
from ..runtime.onboarding import OnboardingService
from ..web.hosted_google_site import HostedGoogleSite, HostedProfiles
from ..web.hosted_targets_site import HostedTargetContext, HostedTargetsSite
from ..web.notion_site import NotionSite
from ..web.oauth_site import OAuthSite
from ..web.onboarding_site import OnboardingSite
from .mailbox_accounts import attach_running_mailbox


def attach_accounts(app: Any, site: Any, directory: Path) -> None:
    def saved() -> Settings:
        return Settings.model_validate(read_yaml(directory / "config.yaml"))

    def config(profile: int, provider: str) -> OAuthConfig:
        return oauth_config(saved(), {**_dotenv(directory / ".env"), **os.environ}, profile, provider)

    def authorize(actor: str) -> bool:
        return actor.startswith("web:") and site.auth.active(actor.removeprefix("web:"))

    service = BrowserOAuth(directory, app.store, authorize, config,
                           lambda value: site.auth._mac("oauth", value))

    def calendar_context(profile: int, field: str = "google_calendar") -> tuple[str, int]:
        setup = site.setup_page.runtime.setup
        return getattr(target_profiles(setup.draft_settings())[profile], field), setup.state().version

    def save_targets(actor: str, profile: int, values: dict[str, Any], version: int, key: str) -> None:
        setup = site.setup_page.runtime.setup
        cfg = setup.draft_settings()
        patch: dict[str, Any]
        if profile == 1:
            patch = {"targets." + field: value for field, value in values.items()}
        else:
            target_profiles(cfg)[profile]  # Reject unconfigured profile numbers before creating a draft.
            entries = [p.model_dump(mode="json") for p in cfg.target_profiles]
            patch = {"target_profiles": [{**p, **values} if p["id"] == profile else p for p in entries]}
        setup.save(actor, version, key, 3, patch)

    def save_calendar(actor: str, profile: int, calendar: str, version: int, key: str,
                      field: str = "google_calendar") -> None:
        save_targets(actor, profile, {field: calendar}, version, key)

    def targets_context(profile: int) -> tuple[Any, int]:
        setup = site.setup_page.runtime.setup
        return target_profiles(setup.draft_settings())[profile], setup.state().version

    def hosted_draft(profile: int) -> tuple[str, int]:
        return calendar_context(profile, "google_connection")

    def hosted_target(profile: int) -> str:
        target_profiles(site.setup_page.runtime.setup.draft_settings())[profile]  # unknown numbers raise
        return f"profile:{profile}"

    client = cached_client(lambda: saved().hosted_auth)

    def hosted_notion_token(profile: int) -> str:
        hub = client()
        conn, _ver = calendar_context(profile, "notion_connection")
        if hub is None or not conn:
            return ""
        return str(hub.post("/intern/token", {"connection": conn, "purpose": "notion"}).get("access_token", ""))

    OAuthSite(site, service, calendar_context, save_calendar, "/einrichtung")
    NotionSite(site, directory, targets_context, save_targets, hosted_token=hosted_notion_token)
    # 8.0 / 8.2: central Inboxstride OAuth for Google, Microsoft and Notion targets, plus guided onboarding.
    HostedGoogleSite(site, app.store, client,
                     HostedProfiles(hosted_draft, save_targets, hosted_target), "/einrichtung")
    HostedTargetsSite(site, app.store, client,
                      HostedTargetContext(calendar_context, save_targets, hosted_target), "/einrichtung")
    OnboardingSite(site, OnboardingService(directory, app.store, authorize,
                                           lambda value: site.auth._mac("onboarding", value)), "/einrichtung")
    attach_running_mailbox(app, site, saved)
    app.services.oauth = service
