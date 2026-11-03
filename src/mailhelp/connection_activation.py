"""Check a connection, then save its credentials and configuration in one authorized step.

Shared by IServ accounts (3.4.7) and IMAP mailboxes (3.5).  The configuration journal writes
config.yaml; the new adapters are only installed by the mail loop, never by the web thread.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from abc import ABC, abstractmethod
from typing import Any

from .config import ImapCredentials, Settings, read_yaml
from .configuration import AdminCommand, AdminKind, ConfigurationConflict, ConfigurationService, file_hash
from .env_file import EnvFileConflict, set_values, validate
from .env_file import file_hash as env_hash
from .review.results import ResultStatus


class ActivationProblem(ValueError):
    """A rejected entry whose message is safe to show; it never contains credentials."""


class ConnectionActivation(ABC):
    prefix = ""
    patch_key = ""
    area = ""

    def __init__(self, runtime: Any):
        self.runtime = runtime
        original = runtime.app.configuration
        # Persist using the ordinary journal, but install adapters and settings only in the mail loop.
        self.configuration = ConfigurationService(original.directory, original.store, original.active,
                                                   original.authorize, lambda settings: None)
        self.store = runtime.app.store

    @abstractmethod
    def merged(self, saved: Settings, item) -> Settings:
        """The saved configuration with *item* added or replaced."""

    @abstractmethod
    def entries(self, cfg: Settings) -> list[dict]:
        """The complete list written under :attr:`patch_key`."""

    @abstractmethod
    def credentials(self, keys) -> dict[int, ImapCredentials]:
        """The credential map of this kind inside *keys*, changed in place."""

    @abstractmethod
    def probe(self, cfg: Settings, item, keys) -> None:
        """Connect read-only; raise when the connection cannot be used."""

    @abstractmethod
    def request(self, cfg: Settings, keys) -> None:
        """Ask the mail loop to install the new adapters at its next safe point."""

    def _current(self, actor, version, revision, env_revision):
        if not self.configuration.authorize(actor):
            raise PermissionError("Sitzung abgelaufen")
        state = self.runtime.setup.state()
        if (state.version != version or file_hash(self.configuration.directory / "config.yaml") != revision
                or state.base_hash and state.base_hash != revision):
            raise ConfigurationConflict("Konfiguration oder Entwurf geändert; Seite neu laden.")
        if env_hash(self.configuration.directory / ".env") != env_revision:
            raise EnvFileConflict("Zugangsdaten geändert; Seite neu laden.")
        if state.kind != "settings":
            raise ConfigurationConflict("Anderen Entwurf zuerst übernehmen oder verwerfen.")
        return state

    def activate(self, actor: str, version: int, key: str, revision: str, env_revision: str, item: Any,
                 username: str, password: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", key):
            raise ValueError("Idempotenzschlüssel fehlt")
        signature = hashlib.sha256(json.dumps([actor, version, revision, env_revision,
            item.model_dump(mode="json")], sort_keys=True).encode()).hexdigest()
        name = f"{self.prefix}-{key}"
        with self.store.locked():
            if self._repeated(name, signature, actor):
                return
            self._current(actor, version, revision, env_revision)
        cfg = self.merged(Settings.model_validate(read_yaml(self.configuration.directory / "config.yaml")), item)
        keys = self.runtime.credentials(cfg)
        if keys is None:
            raise ValueError("Zugangsdaten nicht verfügbar")
        known = self.credentials(keys)
        previous = known.get(item.id)
        user = username or (previous.username if previous else "")
        secret = password or (previous.password.get_secret_value() if previous else "")
        values = dict(zip(item.secret_names, (user, secret), strict=True))
        for field, value in values.items():
            validate(field, value)
        # Process variables keep precedence; do not silently test a value the service cannot use.
        if any(field in os.environ and os.environ[field] != value for field, value in values.items()):
            raise ValueError("Prozessumgebung überschreibt die Zugangsdaten")
        known[item.id] = ImapCredentials(username=user, password=secret)
        self.runtime.app.logger.secrets = (*getattr(self.runtime.app.logger, "secrets", ()), user, secret)
        self.probe(cfg, item, keys)
        with self.store.locked():
            if self._repeated(name, signature, actor):
                return
            state = self._current(actor, version, revision, env_revision)
            command = AdminCommand(kind=AdminKind.SETUP, actor=actor, idempotency_key=key, expected_hash=revision,
                                   patch={self.patch_key: self.entries(cfg)}, acknowledged=True)
            content = self.configuration.render(command, self.configuration.candidate(command))
            self.store.save(name, {"signature": signature,
                                  "candidate_hash": hashlib.sha256(content.encode()).hexdigest(), "status": "prepared"})
            # Recheck authorization immediately before the credential/configuration writes.
            self._current(actor, version, revision, env_revision)
            set_values(self.configuration.directory / ".env", values, env_revision)
            result = self.configuration.execute(command)
            if result.status != ResultStatus.DONE:
                raise ConfigurationConflict("Nicht aktiviert; Seite neu laden und erneut prüfen.")
            self._rebase(state, cfg, item)
            self.request(cfg, keys)
            self.store.save(name, {"signature": signature, "status": "done"})
            self.runtime.app.logger.event("INFO", self.area, "activation_requested", account=item.id)

    def _repeated(self, name, signature, actor):
        operation = self.store.load(name, {})
        if not operation:
            return False
        if not self.configuration.authorize(actor):
            raise PermissionError("Sitzung abgelaufen")
        if operation["signature"] != signature:
            raise ConfigurationConflict("Idempotenzschlüssel bereits verwendet.")
        if operation["status"] != "done":
            raise ConfigurationConflict("Aktivierung unterbrochen; Seite neu laden und gespeicherten Stand prüfen.")
        return True

    def _rebase(self, state, cfg, item):
        """Keep unrelated draft changes; only the activated entry leaves the draft."""
        if state.patch:
            pending = dict(state.patch)
            if self.patch_key in pending:
                pending[self.patch_key] = [entry for entry in pending[self.patch_key] if entry["id"] != item.id]
                pending[self.patch_key].append(item.model_dump(mode="json"))
                if pending[self.patch_key] == self.entries(cfg):
                    del pending[self.patch_key]
            state.patch = pending
            state.base_hash = file_hash(self.configuration.directory / "config.yaml") if pending else ""
            state.version += 1
            self.runtime.setup._save(state)


__all__ = ["ActivationProblem", "ConnectionActivation"]
