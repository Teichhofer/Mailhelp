"""Local provider discovery: no credentials or addresses leave the process."""
from __future__ import annotations

from datetime import date
from importlib.resources import files
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


class ProviderPreset(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    label: str = Field(min_length=1, max_length=100)
    domains: list[str]
    host: str = Field(pattern=r"^[a-z0-9][a-z0-9.-]+\.[a-z]{2,}$")
    port: Literal[993]
    connection_mode: Literal["ssl"]
    username_pattern: Literal["email", "local_part"]
    checked_on: date
    authentication: Literal["password", "oauth2"]
    help_url: str = Field(pattern=r"^https://[^\s]+$")
    de: str
    en: str


def providers() -> dict[str, ProviderPreset]:
    raw = yaml.safe_load(files("mailhelp.defaults").joinpath("imap-providers.yaml").read_text(encoding="utf-8"))
    return {key: ProviderPreset.model_validate(value) for key, value in raw.items()}


def detect_provider(address: str) -> str:
    domain = address.strip().lower().split("@")
    if len(domain) != 2 or not domain[0]:
        return "manual"
    return next((key for key, preset in providers().items() if domain[1] in preset.domains), "manual")


def apply_provider(form: dict[str, str], *, initial: bool = False) -> dict[str, str]:
    """Explicitly apply defaults to the displayed form; neither save nor connect."""
    result = dict(form)
    chosen = form.get("provider", "auto")
    address = form.get("provider_email", "").strip()
    if chosen == "auto":
        chosen = detect_provider(address)
    result["provider"] = chosen
    if chosen == "manual":
        return result
    preset = providers()[chosen]
    prefix = "imap." if initial else ""
    result.update({prefix + "host": preset.host, prefix + "port": str(preset.port),
                   prefix + "connection_mode": preset.connection_mode})
    result["IMAP_USERNAME" if initial else "username"] = (
        address.split("@", 1)[0] if preset.username_pattern == "local_part" else address)
    return result
