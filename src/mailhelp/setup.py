"""Restartable configuration drafts; saving is separate from approval."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .config import Settings, read_yaml
from .configuration import AdminCommand, AdminKind, ConfigurationConflict, apply_settings, file_hash
from .diagnostics import DiagnosticsState
from .notification_config import effective_profile


def profile_patch(settings):
    result: dict[str, Any] = {}
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
    kind: Literal["settings", "topics", "senders"] = "settings"
    category: Literal["relevant", "irrelevant"] = "relevant"
    configuration_hash: str = ""


class SetupService:
    def __init__(self, configuration):
        self.configuration, self.store = configuration, configuration.store

    def state(self) -> SetupState:
        return self.store.load_model("setup-state", SetupState, SetupState())

    def draft_settings(self):
        state = self.state()
        path = self.configuration.directory / "config.yaml"
        if state.kind != "settings":
            return Settings.model_validate(read_yaml(path))
        if state.base_hash and state.base_hash != file_hash(path):
            raise ConfigurationConflict("Konfiguration inzwischen geändert")
        return Settings.model_validate(apply_settings(read_yaml(path), state.patch, True, setup=True))

    def fingerprint(self):
        state = self.state()
        return hashlib.sha256(json.dumps([file_hash(self.configuration.directory / "config.yaml"), state.patch],
                                        sort_keys=True).encode()).hexdigest()

    def save_local(self, actor, version, key, kind, patch, category="relevant"):
        with self.store.locked():
            state, repeated = self._authorized(actor, version, key, [kind, patch, category])
            if repeated:
                return state
            if kind not in {"topics", "senders"}:
                raise ValueError("Ungültiger lokaler Entwurf")
            if state.patch and (state.kind != kind or state.category != category or
                                kind == "topics" and state.patch.get("id") != patch.get("id")):
                raise ConfigurationConflict("Anderen Entwurf zuerst übernehmen oder verwerfen")
            command = AdminCommand(kind=AdminKind(kind), actor=actor, idempotency_key=key,
                expected_hash="0" * 64, patch=patch, category=category, acknowledged=True)
            current = file_hash(self.configuration.path(command))
            if state.base_hash and state.base_hash != current:
                raise ConfigurationConflict("Lokaler Bestand inzwischen geändert")
            command = command.model_copy(update={"expected_hash": current})
            if kind == "topics":
                self.configuration.candidate(command)
            else:
                from .configuration import SenderChange
                SenderChange.model_validate(patch)
            state.kind, state.patch, state.category = kind, patch, category
            state.base_hash, state.step = current, 6
            state.configuration_hash = file_hash(self.configuration.directory / "config.yaml")
            state.version += 1
            self._save(state)
            return state

    def discard(self, actor, version, key):
        with self.store.locked():
            state, repeated = self._authorized(actor, version, key, "discard")
            if not repeated:
                state.kind, state.patch, state.base_hash, state.configuration_hash = "settings", {}, "", ""
                state.version += 1
                self._save(state)
            return state

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

    def save(self, actor, version, key, step, patch, *, refresh=False, request_signature=None):
        with self.store.locked():
            signature = patch if request_signature is None else request_signature
            state, repeated = self._authorized(actor, version, key, [step, signature, refresh])
            if repeated:
                return state
            if state.kind != "settings":
                raise ConfigurationConflict("Lokalen Entwurf zuerst übernehmen oder verwerfen")
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
            if state.kind != "settings":
                if state.configuration_hash != file_hash(self.configuration.directory / "config.yaml"):
                    raise ConfigurationConflict("Postfachkonfiguration inzwischen geändert")
                command = AdminCommand(kind=AdminKind(state.kind), actor=actor, expected_hash=expected_hash,
                    idempotency_key=key, patch=state.patch, category=state.category, acknowledged=True,
                    context_hash=state.configuration_hash)
                if file_hash(self.configuration.path(command)) != expected_hash:
                    raise ConfigurationConflict("Lokaler Bestand inzwischen geändert")
                return command
            command = AdminCommand(kind=AdminKind.SETUP, actor=actor, expected_hash=expected_hash,
                                   idempotency_key=key, patch=state.patch, acknowledged=True)
            self.configuration.candidate(command)
            checks = {"imap": ("imap.",),
                      "calendar": ("targets.google_calendar", "targets.calendar_provider",
                                   "targets.caldav_calendar_url", "targets.outlook_calendar",
                                   "targets.microsoft_tenant"),
                      "todoist": ("targets.todoist_project", "targets.task_provider", "targets.caldav_task_url",
                                  "targets.microsoft_todo_list"),
                      "iserv": ("iserv.",)}
            diagnostics = self.store.load_model("diagnostics-state", DiagnosticsState, DiagnosticsState())
            for name, prefixes in checks.items():
                if any(field.startswith(prefixes) for field in state.patch):
                    result = diagnostics.results.get(name)
                    # Without enabled IServ accounts the check reports "disabled", e.g. after removing the last.
                    accepted = {"ready", "limited", "disabled"} if name == "iserv" else {"ready", "limited"}
                    if (result is None or result.status not in accepted
                            or result.config_revision != self.fingerprint()):
                        raise ValueError("Verbindungsänderungen benötigen eine aktuelle erfolgreiche Diagnose")
            if "target_profiles" in state.patch or "imap.mailboxes" in state.patch or any(
                    name.endswith(".target_profile") for name in state.patch):
                from .mailbox_settings import active_profiles
                for number in active_profiles(self.draft_settings()):
                    components = ("calendar", "todoist") if number == 1 else (f"calendar:{number}", f"tasks:{number}")
                    for name in components:
                        result = diagnostics.results.get(name)
                        if result is None or result.status != "ready" or result.config_revision != self.fingerprint():
                            raise ValueError("Zielprofil benötigt eine aktuelle erfolgreiche Diagnose")
            return command
