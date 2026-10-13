"""Restartable configuration drafts; saving is separate from approval."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .config import Settings, read_yaml
from .configuration import AdminCommand, AdminKind, ConfigurationConflict, apply_settings, file_hash
from .diagnostics import DiagnosticsState
from .notification_config import effective_profile


def profile_patch(settings):
    result = {}
    for section, value in effective_profile(settings).model_dump().items():
        if isinstance(value, dict):
            result.update((f"notifications.{section}.{name}", item) for name, item in value.items())
        else:
            result[f"notifications.{section}"] = value
    return result


class SetupState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    version: int = Field(default=0, ge=0)
    step: int = Field(default=1, ge=1, le=6)
    base_hash: str = Field(default="", pattern=r"^(?:[a-f0-9]{64})?$")
    patch: dict = Field(default_factory=dict, max_length=60)
    operations: dict[str, str] = Field(default_factory=dict)


class SetupService:
    def __init__(self, configuration):
        self.configuration, self.store = configuration, configuration.store

    def state(self) -> SetupState:
        return self.store.load_model("setup-state", SetupState, SetupState())

    def draft_settings(self):
        state = self.state()
        path = self.configuration.directory / "config.yaml"
        if state.base_hash and state.base_hash != file_hash(path):
            raise ConfigurationConflict("Konfiguration inzwischen geändert")
        return Settings.model_validate(apply_settings(read_yaml(path), state.patch, True, setup=True))

    def fingerprint(self):
        state = self.state()
        return hashlib.sha256(json.dumps([file_hash(self.configuration.directory / "config.yaml"), state.patch],
                                        sort_keys=True).encode()).hexdigest()

    def _save(self, state):
        self.store.save("setup-state", state.model_dump(mode="json"))

    def _authorized(self, actor, version, key, signature):
        if not self.configuration.authorize(actor):
            raise PermissionError("Sitzung abgelaufen")
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", key):
            raise ValueError("Idempotenzschlüssel fehlt")
        state = self.state()
        operation = f"{actor}:{key}"
        digest = hashlib.sha256(json.dumps([version, signature], sort_keys=True).encode()).hexdigest()
        if operation in state.operations:
            if state.operations[operation] != digest:
                raise ValueError("Idempotenzkonflikt")
            return state, True
        if state.version != version:
            raise ConfigurationConflict("Entwurf inzwischen geändert")
        state.operations[operation] = digest
        state.operations = dict(list(state.operations.items())[-500:])
        return state, False

    def save(self, actor, version, key, step, patch, *, refresh=False):
        with self.store.locked():
            state, repeated = self._authorized(actor, version, key, [step, patch, refresh])
            if repeated:
                return state
            if step not in range(1, 7):
                raise ValueError("Ungültiger Schritt")
            current = file_hash(self.configuration.directory / "config.yaml")
            if state.base_hash and state.base_hash != current and not refresh:
                raise ConfigurationConflict("Konfiguration geändert; Differenz erneut prüfen")
            merged = {**state.patch, **patch}
            raw = read_yaml(self.configuration.directory / "config.yaml")
            if raw.get("notifications") is None and any(name.startswith("notifications.") for name in merged):
                merged = {**profile_patch(Settings.model_validate(raw)), **merged}
            command = AdminCommand(kind=AdminKind.SETUP, actor=actor, expected_hash=current,
                                   idempotency_key=key, patch=merged, acknowledged=True)
            self.configuration.candidate(command)
            state.patch, state.base_hash, state.step = merged, current, step
            state.version += 1
            self._save(state)
            return state

    def command(self, actor, version, key, expected_hash):
        """Approval exists only in this new, session-bound immutable command."""
        if not self.configuration.authorize(actor):
            raise PermissionError("Sitzung abgelaufen")
        with self.store.locked():
            state = self.state()
            if state.version != version or state.base_hash != expected_hash:
                raise ConfigurationConflict("Entwurf inzwischen geändert")
            command = AdminCommand(kind=AdminKind.SETUP, actor=actor, expected_hash=expected_hash,
                                   idempotency_key=key, patch=state.patch, acknowledged=True)
            self.configuration.candidate(command)
            checks = {"imap": "imap.", "calendar": "targets.google_calendar", "todoist": "targets.todoist_project"}
            diagnostics = self.store.load_model("diagnostics-state", DiagnosticsState, DiagnosticsState())
            for name, prefix in checks.items():
                if any(field.startswith(prefix) for field in state.patch):
                    result = diagnostics.results.get(name)
                    if (result is None or result.status not in {"ready", "limited"}
                            or result.config_revision != self.fingerprint()):
                        raise ValueError("Verbindungsänderungen benötigen eine aktuelle erfolgreiche Diagnose")
            return command
