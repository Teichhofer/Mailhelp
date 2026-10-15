"""Versioned .env edits: secrets never enter command queues, receipts or HTML."""
from __future__ import annotations

import hmac
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .config import Settings, _dotenv, imap_secret_names, provider_secret_names, read_yaml
from .configuration import ConfigurationConflict, file_hash
from .mailbox_settings import profile_label, target_profiles
from .storage import JsonStore, atomic_replace
from .target_profiles import secret_name

RECEIPTS = "credential-edits"
MAX_RECEIPTS = 100
LABELS = {
    "IMAP_USERNAME": "IMAP-Benutzername", "IMAP_PASSWORD": "IMAP-Passwort",
    "OPENROUTER_API_KEY": "OpenRouter API-Schlüssel", "TELEGRAM_BOT_TOKEN": "Telegram Bot-Token",
    "TODOIST_TOKEN": "Todoist API-Token", "TODOIST_CLIENT_ID": "Todoist Client-ID",
    "TODOIST_CLIENT_SECRET": "Todoist Client-Schlüssel",
    "GOOGLE_OAUTH_CLIENT_ID": "Google OAuth Client-ID", "GOOGLE_OAUTH_CLIENT_SECRET": "Google OAuth Client-Schlüssel",
    "GOOGLE_OAUTH_REFRESH_TOKEN": "Google OAuth Refresh-Token",
    "CALDAV_USERNAME": "CalDAV-Benutzername", "CALDAV_PASSWORD": "CalDAV-Passwort",
    "MICROSOFT_CLIENT_ID": "Microsoft Client-ID", "MICROSOFT_CLIENT_SECRET": "Microsoft Client-Schlüssel",
    "MICROSOFT_REFRESH_TOKEN": "Microsoft Refresh-Token",
}


@dataclass(frozen=True)
class CredentialField:
    name: str
    label: str
    group: str
    present: bool
    inherited: bool
    overridden: bool


@dataclass(frozen=True)
class CredentialSnapshot:
    fields: tuple[CredentialField, ...]
    revision: str
    config_revision: str


class CredentialReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    request: str
    before: str
    after: str
    status: Literal["prepared", "done"] = "prepared"


class CredentialEdits(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    entries: list[CredentialReceipt] = Field(default_factory=list)


class CredentialUnauthorized(PermissionError):
    """The web session expired or was revoked before the local file edit."""


class CredentialService:
    def __init__(self, directory: Path, store: JsonStore, authorize: Callable[[str], bool],
                 sign: Callable[[str], str]):
        self.directory, self.store, self.authorize, self.sign = directory, store, authorize, sign

    def _content(self) -> str:
        path = self.directory / ".env"
        return path.read_bytes().decode("utf-8") if path.exists() else ""

    def _revision(self, content: str) -> str:
        # A keyed digest prevents offline guessing of short passwords from a receipt.
        return self.sign("file:" + content)

    def snapshot(self) -> CredentialSnapshot:
        cfg = Settings.model_validate(read_yaml(self.directory / "config.yaml"))
        env = {**_dotenv(self.directory / ".env"), **os.environ}
        fields = []

        def add(name: str, label: str, group: str, fallback: str = "") -> None:
            inherited = not env.get(name) and bool(env.get(fallback))
            fields.append(CredentialField(name, label, group, bool(env.get(name)) or inherited,
                                          bool(inherited), name in os.environ))

        for mailbox in cfg.imap.configured_mailboxes():
            mailbox_names = imap_secret_names(mailbox, env, cfg.imap.legacy_format)
            for name, base in zip(mailbox_names, ("IMAP_USERNAME", "IMAP_PASSWORD"), strict=True):
                add(name, LABELS[base], f"Postfach {mailbox.id} · {mailbox.label}")
        add("OPENROUTER_API_KEY", LABELS["OPENROUTER_API_KEY"], "KI-Anbieter")
        add("TELEGRAM_BOT_TOKEN", LABELS["TELEGRAM_BOT_TOKEN"], "Telegram")
        for number, target in target_profiles(cfg).items():
            provider_names = provider_secret_names(target)
            if target.uses_microsoft:
                provider_names += ["MICROSOFT_CLIENT_SECRET", "MICROSOFT_REFRESH_TOKEN"]
            for base in provider_names:
                name = base if number == 1 else secret_name(base, number)
                fallback = base if number != 1 and base.endswith(("_CLIENT_ID", "_CLIENT_SECRET")) else ""
                add(name, LABELS[base], f"Zielprofil {number} · {profile_label(cfg, number)}", fallback)
        return CredentialSnapshot(tuple(fields), self._revision(self._content()),
                                  file_hash(self.directory / "config.yaml"))

    def _authorized(self, session: str) -> None:
        if not self.authorize(session):
            raise CredentialUnauthorized("Sitzung nicht mehr gültig")

    @staticmethod
    def _updated(content: str, name: str, value: str) -> str:
        lines = [line for line in content.splitlines(keepends=True)
                 if line.split("=", 1)[0].strip() != name]
        prefix = "".join(lines)
        if prefix and not prefix.endswith(("\n", "\r")):
            prefix += "\n"
        # The app's .env reader strips only the outer quotes; it never expands
        # backslashes, dollar signs or internal quotes.
        return prefix + name + '="' + value + '"\n'

    def save(self, session: str, key: str, name: str, value: str, expected: str, config_revision: str) -> None:
        with self.store.locked():
            self._authorized(session)
            if (not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", key) or not 1 <= len(value) <= 4000
                    or not value.strip() or any(ord(char) < 32 or char in "\x7f\x85\u2028\u2029" for char in value)):
                raise ValueError("Ungültiger Schlüssel oder Zugangswert")
            value.encode("utf-8")
            snapshot = self.snapshot()
            if config_revision != snapshot.config_revision:
                raise ConfigurationConflict("Konfiguration inzwischen geändert")
            if name not in {item.name for item in snapshot.fields}:
                raise ValueError("Nicht angebotener Zugang")
            signature = self.sign("request:" + json.dumps([session, key, name, value, expected, config_revision]))
            state = self.store.load_model(RECEIPTS, CredentialEdits, CredentialEdits())
            receipt = next((entry for entry in state.entries if entry.key == key), None)
            if receipt is not None:
                if not hmac.compare_digest(receipt.request, signature):
                    raise ConfigurationConflict("Schlüssel gehört zu einer anderen Änderung")
                if receipt.status == "done":
                    return
            else:
                if not hmac.compare_digest(snapshot.revision, expected):
                    raise ConfigurationConflict("Zugangsdaten inzwischen geändert")
                changed = self._updated(self._content(), name, value)
                receipt = CredentialReceipt(key=key, request=signature, before=expected, after=self._revision(changed))
                state.entries = [*state.entries, receipt][-MAX_RECEIPTS:]
                self.store.save(RECEIPTS, state.model_dump())
            self._authorized(session)
            if file_hash(self.directory / "config.yaml") != config_revision:
                raise ConfigurationConflict("Konfiguration inzwischen geändert")
            content = self._content()
            revision = self._revision(content)
            if hmac.compare_digest(revision, receipt.before):
                atomic_replace(self.directory / ".env", self._updated(content, name, value))
            elif not hmac.compare_digest(revision, receipt.after):
                raise ConfigurationConflict("Zugangsdaten inzwischen geändert")
            (self.directory / ".env").chmod(0o600)
            receipt.status = "done"
            self.store.save(RECEIPTS, state.model_dump())
