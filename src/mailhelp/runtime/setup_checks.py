"""Bounded, read-only setup probes; provider response bodies never reach error pages."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from ..config import PromptConfig, Secrets, Settings
from ..config.loader import imap_secret_values, provider_secret_names
from ..config.models import ImapCredentials
from ..external.providers import build_writers
from ..llm.ollama import LocalLlm, parse_address
from ..mailbox.imap import ImapReader, reader_arguments
from ..proposals.target_profiles import PROVIDER_FIELDS


def setup_secrets(settings: Settings, env: dict[str, str]) -> Secrets:
    imap, missing = imap_secret_values(settings.imap, env)
    required = provider_secret_names(settings.targets)
    if settings.llm.provider == "openrouter":
        required.append("OPENROUTER_API_KEY")
    missing += [name for name in required if not env.get(name)]
    if missing:
        raise ValueError("Zugangsdaten fehlen: " + ", ".join(missing))
    values = {name: env[name.upper()] for name in PROVIDER_FIELDS if env.get(name.upper())}
    return Secrets(imap=imap, openrouter_api_key=env.get("OPENROUTER_API_KEY", ""), **values)


class SetupChecks:
    def __init__(self, directory: Path, transport: httpx.BaseTransport | None = None):
        self.directory, self.transport = directory, transport

    def imap(self, settings: Settings, env: dict[str, str]) -> dict[str, Any]:
        credentials, missing = imap_secret_values(settings.imap, env)
        if missing:
            raise ValueError("IMAP-Benutzername und Passwort fehlen.")
        mailbox = settings.imap.enabled_mailboxes()[0]
        address, options = reader_arguments(mailbox, ImapCredentials.model_validate(credentials[mailbox.id]))
        reader = ImapReader(*address, timeout=15, **options)
        try:
            folders = reader.list_folders()
            reader.check_access([mailbox.primary_folder])
            return {"folders": [folder.name for folder in folders],
                    "inbox": next((f.name for f in folders if f.role == "inbox"), "INBOX"),
                    "drafts": next((f.name for f in folders if f.role == "drafts"), "")}
        finally:
            reader.close()

    def llm(self, settings: Settings, env: dict[str, str], prompts: PromptConfig) -> dict[str, Any]:
        with httpx.Client(transport=self.transport, timeout=15, trust_env=False) as client:
            if settings.llm.provider == "ollama":
                host, port = parse_address(settings.llm.ollama_address)
                response = client.get(LocalLlm(host, port, model="").base_url + "/api/tags")
                response.raise_for_status()
                names = [item["name"] for item in response.json()["models"]]
                if not names or any(not isinstance(name, str) or not name for name in names):
                    raise ValueError("Keine installierten Ollama-Modelle gefunden.")
                return {"models": names}
            token = env.get("OPENROUTER_API_KEY", "")
            if not token:
                raise ValueError("OpenRouter-API-Schlüssel fehlt.")
            headers = {"Authorization": "Bearer " + token}
            key = client.get("https://openrouter.ai/api/v1/key", headers=headers)
            key.raise_for_status()
            data = key.json()["data"]
            models = client.get("https://openrouter.ai/api/v1/models", headers=headers)
            models.raise_for_status()
            available = {model["id"] for model in models.json()["data"]}
            required = {route.model for name in prompts.prompts for route in prompts.resolved_routes(name)[0]}
            if not required <= available:
                raise ValueError("Mindestens ein konfiguriertes Modell ist nicht verfügbar.")
            credits = client.get("https://openrouter.ai/api/v1/credits", headers=headers)
            balance: float | None = None
            if credits.status_code == 200:
                account = credits.json()["data"]
                balance = float(account["total_credits"]) - float(account["total_usage"])
            elif credits.status_code not in {401, 403}:
                credits.raise_for_status()
            remaining = data.get("limit_remaining")
            if remaining is not None and not isinstance(remaining, (int, float)):
                raise ValueError("Ungültige Guthabenauskunft.")
            return {"models": sorted(required), "balance": balance, "key_remaining": remaining}

    def targets(self, settings: Settings, env: dict[str, str]) -> dict[str, Any]:
        writers = build_writers(settings, setup_secrets(settings, env), self.directory,
                                transport=self.transport, timeout_cap=15)
        try:
            writers.calendar.check_access()
            writers.tasks.check_access()
        finally:
            writers.close()
        return {"ready": True}
