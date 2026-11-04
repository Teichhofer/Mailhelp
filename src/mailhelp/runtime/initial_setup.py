"""Versioned first-run drafts; config.yaml is the final atomic activation marker."""
from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from datetime import datetime
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel, ConfigDict, Field

from ..config import PromptConfig, Settings
from ..config.loader import _dotenv
from ..storage import JsonStore, atomic_replace
from .env_file import file_hash, set_values
from .setup_checks import SetupChecks
from .web_password import WebPassword

FIELDS = {
    1: ("timezone",),
    2: ("imap.host", "imap.port", "imap.connection_mode", "imap.primary_folder", "imap.drafts_folder"),
    3: ("llm.provider", "llm.ollama_address"),
    4: ("targets.calendar_provider", "targets.task_provider", "targets.google_calendar", "targets.todoist_project",
        "targets.caldav_calendar_url", "targets.caldav_task_url", "targets.outlook_calendar",
        "targets.microsoft_todo_list", "targets.microsoft_tenant", "web.google_redirect_uri"),
}
SECRET_FIELDS = {
    1: (), 2: ("IMAP_USERNAME", "IMAP_PASSWORD"), 3: ("OPENROUTER_API_KEY",),
    4: ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_OAUTH_REFRESH_TOKEN", "TODOIST_TOKEN",
        "CALDAV_USERNAME", "CALDAV_PASSWORD", "MICROSOFT_CLIENT_ID", "MICROSOFT_CLIENT_SECRET",
        "MICROSOFT_REFRESH_TOKEN"),
}


def default_file(name: str) -> str:
    return files("mailhelp").joinpath("defaults", name).read_text(encoding="utf-8")


class InitialDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    version: int = 0
    step: int = Field(default=1, ge=1, le=5)
    completed_step: int = 0
    config: dict[str, Any]
    model: str = ""
    result: dict[str, Any] = Field(default_factory=dict)
    operations: dict[str, str] = Field(default_factory=dict)
    env_revision: str
    status: str = "draft"


class InitialSetup:
    def __init__(self, directory: Path, store: JsonStore, authorize: Callable[[str], bool],
                 sign: Callable[[str], str], checks: SetupChecks, web: dict[str, Any]):
        self.directory, self.store, self.authorize, self.sign, self.checks = directory, store, authorize, sign, checks
        self.web = web

    def environment(self) -> dict[str, str]:
        return {**_dotenv(self.directory / ".env"), **os.environ}

    def state(self) -> InitialDraft:
        value = self.store.load_model("initial-setup", InitialDraft)
        if value is not None:
            if value.status == "committing" and not (self.directory / "config.yaml").exists():
                value.status = "draft"
            return value
        raw = yaml.safe_load(default_file("initial-config.yaml"))
        raw["telegram"]["enabled"] = False
        raw["web"] = {**raw.get("web", {}), **self.web, "enabled": True}
        raw["data_directory"], raw["test_mode"] = "data", False
        raw["llm"] = {"provider": "openrouter", "ollama_address": "localhost:11434"}
        raw["logging"]["llm"].update(include_requests=False, include_responses=False)
        for name in raw["notifications"]["categories"]:
            raw["notifications"]["categories"][name] = []
        raw["imap"] = {"host": "imap.example.invalid", "port": 993, "connection_mode": "ssl",
                       "folders": ["INBOX"], "primary_folder": "INBOX", "drafts_folder": "Drafts",
                       "historical_start": datetime.now(ZoneInfo(raw["timezone"])).replace(
                           hour=0, minute=0, second=0, microsecond=0).isoformat()}
        raw["targets"].update(google_calendar="primary", todoist_project="inbox")
        return InitialDraft(config=raw, env_revision=file_hash(self.directory / ".env"))

    def _save(self, state: InitialDraft) -> None:
        self.store.save("initial-setup", state.model_dump(mode="json"))

    def credentials_changed(self, actor: str) -> None:
        with self.store.locked():
            self._guard(actor)
            state = self.state()
            state.env_revision = file_hash(self.directory / ".env")
            state.version += 1
            self._save(state)

    def _guard(self, actor: str) -> None:
        if not self.authorize(actor):
            raise PermissionError("Sitzung abgelaufen.")

    def prompts(self, state: InitialDraft) -> PromptConfig:
        path = self.directory / "prompts.yaml"
        raw = yaml.safe_load(path.read_text(encoding="utf-8") if path.exists() else default_file("prompts.yaml"))
        if state.model:
            raw["ollama"] = {**raw.get("ollama", {}), "model": state.model}
        return PromptConfig.model_validate(raw)

    def _candidate(self, state: InitialDraft, step: int, form: dict[str, str]) -> InitialDraft:
        candidate = state.model_copy(deep=True)
        for field in FIELDS[step]:
            if field in form:
                parent, _, name = field.rpartition(".")
                target = candidate.config[parent] if parent else candidate.config
                target[name] = int(form[field]) if field == "imap.port" else form[field]
        if step == 2:
            candidate.config["imap"]["folders"] = [candidate.config["imap"]["primary_folder"]]
        if step == 3 and form.get("model"):
            candidate.model = form["model"]
        Settings.model_validate(candidate.config)
        self.prompts(candidate)
        return candidate

    def save(self, actor: str, form: dict[str, str], *, probe: bool = False) -> InitialDraft:
        self._guard(actor)
        step, version, key = int(form["step"]), int(form["version"]), form["key"]
        if step not in FIELDS or not re.fullmatch(r"[a-f0-9]{32}", key):
            raise ValueError("Ungültiger Einrichtungsschritt.")
        signature = self.sign(json.dumps([actor, version, form, probe], sort_keys=True))
        with self.store.locked():
            before = self.state()
            if key in before.operations:
                if before.operations[key] != signature:
                    raise ValueError("Idempotenzkonflikt.")
                return before
            if (before.version != version or before.status != "draft" or step > before.completed_step + 1
                    or before.env_revision != file_hash(self.directory / ".env")):
                raise ValueError("Einrichtung inzwischen geändert; Seite neu laden.")
            candidate = self._candidate(before, step, form)
            env = self.environment()
            secrets = {name: form[name] for name in SECRET_FIELDS[step] if form.get(name)}
            env.update(secrets)
        # Network probes and scrypt do not hold the store lock.
        result: dict[str, Any] = {}
        if step == 1 and (form.get("password") or not WebPassword(self.store).state().digest):
            password = form.get("password", "")
            if not 12 <= len(password) <= 1024 or any(ord(c) < 32 for c in password):
                raise ValueError("Ein Web-Passwort mit mindestens 12 Zeichen ist erforderlich.")
        if probe:
            result = self._probe(step, candidate, env)
        with self.store.locked():
            self._guard(actor)
            if self.state() != before or file_hash(self.directory / ".env") != before.env_revision:
                raise ValueError("Einrichtung während der Prüfung geändert.")
            if step == 1 and form.get("password"):
                WebPassword(self.store).set(form["password"], WebPassword(self.store).state().version)
            if secrets:
                set_values(self.directory / ".env", secrets, before.env_revision)
            candidate.env_revision = file_hash(self.directory / ".env")
            candidate.result = result
            candidate.completed_step = max(candidate.completed_step, step)
            candidate.step = step if probe else min(step + 1, 5)
            candidate.operations = dict([*before.operations.items(), (key, signature)][-100:])
            candidate.version += 1
            self._save(candidate)
            return candidate

    def _probe(self, step: int, state: InitialDraft, env: dict[str, str]) -> dict[str, Any]:
        cfg = Settings.model_validate(state.config)
        if step == 2:
            return self.checks.imap(cfg, env)
        if step == 3:
            return self.checks.llm(cfg, env, self.prompts(state))
        return self.checks.targets(cfg, env)

    def finish(self, actor: str, version: int, key: str) -> None:
        self._guard(actor)
        if not re.fullmatch(r"[a-f0-9]{32}", key):
            raise ValueError("Idempotenzschlüssel fehlt.")
        with self.store.locked():
            before = self.state()
            if before.status == "done" and before.operations.get(key) == actor:
                return
            if before.version != version or before.completed_step != 4 or before.status != "draft":
                raise ValueError("Einrichtung unvollständig oder inzwischen geändert.")
            env_revision = file_hash(self.directory / ".env")
        env = self.environment()
        for step in (2, 3, 4):
            self._probe(step, before, env)
        if before.config.get("llm", {}).get("provider") == "ollama":
            result = self._probe(3, before, env)
            local = self.prompts(before).ollama
            if local is None or local.model not in result["models"]:
                raise ValueError("Ein installiertes Ollama-Modell auswählen.")
        with self.store.locked():
            self._guard(actor)
            if self.state() != before or file_hash(self.directory / ".env") != env_revision:
                raise ValueError("Einrichtung während der Prüfung geändert.")
            if not WebPassword(self.store).state().digest:
                raise ValueError("Web-Passwort fehlt.")
            if (self.directory / "config.yaml").exists():
                raise ValueError("Konfiguration existiert bereits.")
            before.status = "committing"
            self._save(before)
            for name in ("topics.yaml", "irrelevant_topics.yaml", "decisions_prompts.yaml"):
                path = self.directory / name
                if not path.exists():
                    atomic_replace(path, default_file(name))
            atomic_replace(self.directory / "prompts.yaml",
                           yaml.safe_dump(self.prompts(before).model_dump(mode="json"),
                                          allow_unicode=True, sort_keys=False))
            # Credentials already exist. Publishing config last makes restart activation atomic.
            atomic_replace(self.directory / "config.yaml",
                           yaml.safe_dump(before.config, allow_unicode=True, sort_keys=False))
            before.status, before.version = "done", before.version + 1
            before.operations[key] = actor
            self._save(before)
