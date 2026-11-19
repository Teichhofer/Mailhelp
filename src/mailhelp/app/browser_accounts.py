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
from ..web.hosted_google_site import HostedGoogleSite, HostedProfiles
from ..web.notion_site import NotionSite
from ..web.oauth_site import OAuthSite


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

    OAuthSite(site, service, calendar_context, save_calendar, "/einrichtung")
    NotionSite(site, directory, targets_context, save_targets)
    # 8.0: "Mit Google verbinden" through the central Inboxstride service of a hosted instance.
    HostedGoogleSite(site, app.store, cached_client(lambda: saved().hosted_auth),
                     HostedProfiles(hosted_draft, save_targets, hosted_target), "/einrichtung")
    app.services.oauth = service
