"""Read-only calendar choices for saved Google credentials, including pagination."""
from __future__ import annotations

import os
from pathlib import Path

import httpx

from ..config.loader import _dotenv
from ..external.oauth import GoogleOAuthTokenProvider
from ..proposals.target_profiles import secret_name
from .oauth_web import OAuthConfig


def google_calendars(directory: Path, profile: int, cfg: OAuthConfig,
                     transport: httpx.BaseTransport | None = None, *, tasks: bool = False) -> list[tuple[str, str]]:
    """Read every available calendar or task list with the profile's saved credentials."""
    endpoint = ("https://tasks.googleapis.com/tasks/v1/users/@me/lists" if tasks
                else "https://www.googleapis.com/calendar/v3/users/me/calendarList")
    label = "Aufgabenliste" if tasks else "Kalenderliste"
    title_field = "title" if tasks else "summary"
    env = {**_dotenv(directory / ".env"), **os.environ}
    name = "GOOGLE_OAUTH_REFRESH_TOKEN" if profile == 1 else secret_name("GOOGLE_OAUTH_REFRESH_TOKEN", profile)
    token = GoogleOAuthTokenProvider(cfg.client_id, cfg.client_secret, env.get(name, ""),
                                    timeout=15, transport=transport)
    try:
        bearer = token.access_token()
        with httpx.Client(transport=transport, timeout=15, trust_env=False) as client:
            choices, seen, page = [], set(), ""
            for _ in range(20):
                response = client.get(endpoint,
                    params={"maxResults": "250", "pageToken": page}, headers={"Authorization": "Bearer " + bearer})
                response.raise_for_status()
                body = response.json()
                for item in body.get("items", []):
                    if not isinstance(item["id"], str) or not item["id"] or not isinstance(item[title_field], str):
                        raise ValueError(f"Ungültige {label}.")
                    if tasks or item.get("accessRole") in {"writer", "owner"}:
                        choices.append((item["id"], item[title_field]))
                page = body.get("nextPageToken", "")
                if not page:
                    return choices
                if not isinstance(page, str) or page in seen:
                    break
                seen.add(page)
            raise ValueError(f"{label} unvollständig.")
    finally:
        token.close()
