"""Validated local configuration commands, optimistic concurrency and recovery."""
from __future__ import annotations

import hashlib
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .config import IrrelevantTopicsConfig, Settings, Topic, TopicsConfig
from .domain.relevance import IrrelevantSenders
from .learning import topics_document
from .review.commands import CommandSource
from .review.results import ResultStatus, ReviewResult
from .sender_filter import change_irrelevant_senders
from .storage import JsonStore, atomic_replace
from .yaml_edit import YamlEditError, set_scalars


class ConfigurationConflict(ValueError):
    """A validated edit no longer refers to the file currently on disk."""


class AdminKind(StrEnum):
    SETTINGS = "settings"
    TOPICS = "topics"
    SENDERS = "senders"


class AdminCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: AdminKind
    source: Literal[CommandSource.WEB] = CommandSource.WEB
    actor: str = Field(pattern=r"^web:[a-f0-9]{16}$")
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")
    # File edits are bound to the file they were checked against.  Sender
    # changes are idempotent and commutative and need no such binding.
    expected_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    category: str = Field(default="relevant", pattern=r"^(relevant|irrelevant)$")
    patch: dict = Field(max_length=30)
    acknowledged: bool = False

    @model_validator(mode="after")
    def file_edits_need_a_hash(self) -> AdminCommand:
        if self.kind != AdminKind.SENDERS and self.expected_hash is None:
            raise ValueError("Dateiänderungen benötigen den erwarteten Dateihash")
        return self


class SenderChange(BaseModel):
    """Add or remove ignored senders; ``mail_id`` names the mail it came from."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    action: Literal["add", "remove"]
    addresses: list[str] = Field(default_factory=list, max_length=10)
    domains: list[str] = Field(default_factory=list, max_length=10)
    mail_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{24}$")

    @model_validator(mode="after")
    def valid_entries(self) -> SenderChange:
        if not self.addresses and not self.domains:
            raise ValueError("Mindestens eine Adresse oder Domain angeben")
        IrrelevantSenders(addresses=sorted(set(self.addresses)), domains=sorted(set(self.domains)))
        return self

    @property
    def entries(self) -> str:
        return ", ".join([*self.addresses, *self.domains])


SETTINGS_FIELDS = {
    "poll_interval_seconds", "timezone", "test_mode", "personal_info",
    "targets.todoist_project", "targets.google_calendar",
    "limits.llm_calls_per_minute", "limits.max_mail_bytes", "limits.max_llm_payload_bytes",
    "retention.full_mail_days", "retention.debug_llm_days", "retention.analysis_days", "retention.history_days",
    "logging.console.level", "logging.file.level", "logging.llm.include_requests", "logging.llm.include_responses",
    "metrics.enabled", "metrics.retention_days", "metrics.usd_per_eur", "metrics.exchange_rate_date",
    "metrics.ollama_power_watts", "metrics.electricity_eur_per_kwh",
}
for service in ("imap", "telegram", "openrouter", "ollama", "todoist", "google_calendar"):
    SETTINGS_FIELDS.update(f"timeouts.{service}.{field}" for field in
                           ("timeout_seconds", "retries", "initial_backoff_seconds", "max_backoff_seconds"))
for field in ("interpretation_attempts", "interpretation_backoff_seconds", "revision_attempts",
              "revision_backoff_seconds"):
    SETTINGS_FIELDS.add(f"retries.{field}")

LIVE_FIELDS = {"poll_interval_seconds", "retention", "metrics", "personal_info"}


STEP_LABELS = {
    "relevance": "Relevanz (Rückfall)", "summary": "Zusammenfassung", "action_router": "Aktionszuordnung",
    "task_extraction": "Aufgabenerkennung", "event_extraction": "Terminerkennung",
    "mail_question_resolution": "Rückfragen aus der Mail", "telegram_answer_interpretation": "Antworten verstehen",
    "telegram_answer_clarification": "Nachfragen formulieren", "proposal_revision": "Vorschläge überarbeiten",
    "learning_classification": "Lernmodus: Einordnung", "learning_abstraction": "Lernmodus: Themen",
    "calendar_duplicate": "Kalender-Dubletten", "vision_ocr": "Bilderkennung (OCR)",
}


def effective_models(prompts, jev_model: str | None, local_model: str | None) -> list[tuple[str, str, str, str]]:
    """(step, model, parameters, source) of the running process, read-only.

    No prompt texts, provider addresses or secrets are included.
    """
    rows = []
    if local_model:
        rows.append(("Alle Schritte", local_model, "", "Startparameter --ollama"))
    elif jev_model:
        rows.append(("Relevanz", jev_model, "unklare Fälle: Rückfall auf das Relevanzmodell",
                     "decisions_prompts.yaml"))
    for step in prompts.prompts:
        routes = prompts.resolved_routes(step)[0]
        parameters = "; ".join(", ".join(f"{key} {value}" for key, value in sorted(route.parameters.items()))
                               for route in routes if route.parameters)
        rows.append((STEP_LABELS.get(step, step), ", ".join(route.model for route in routes),
                     parameters, "Startparameter --ollama ersetzt" if local_model else "prompts.yaml"))
    return rows


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def apply_settings(raw: dict, patch: dict, acknowledged: bool) -> dict:
    import copy
    candidate = copy.deepcopy(raw)
    if set(patch) - SETTINGS_FIELDS:
        raise ValueError("Nicht angebotene Einstellung")
    if patch and not acknowledged:
        raise ValueError("Änderungen und ihre Folgen müssen bestätigt werden")
    for dotted, value in patch.items():
        parts = dotted.split(".")
        target = candidate
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = value
    Settings.model_validate(candidate)
    return candidate


class ConfigurationService:
    def __init__(self, directory: Path, store: JsonStore, active: Settings,
                 authorize: Callable[[str], bool], activate: Callable[[Settings], None],
                 activate_topics: Callable[[list[Topic]], None] = lambda topics: None,
                 senders: JsonStore | None = None):
        self.directory, self.store, self.active = directory, store, active
        self.authorize, self.activate = authorize, activate
        self.activate_topics = activate_topics
        # Holds irrelevant-senders, which the orchestrator reads for every mail.
        self.senders = senders

    def blocked_senders(self) -> IrrelevantSenders:
        """Current list for display; read without quarantining a damaged file."""
        if self.senders is None:
            return IrrelevantSenders()
        blocked = self.senders.peek_model("irrelevant-senders", IrrelevantSenders, IrrelevantSenders())
        assert isinstance(blocked, IrrelevantSenders)
        return blocked

    def _current_senders(self) -> IrrelevantSenders:
        if self.senders is None:
            raise OSError("Absenderliste nicht verfügbar")
        blocked = self.senders.load_model("irrelevant-senders", IrrelevantSenders, IrrelevantSenders())
        assert isinstance(blocked, IrrelevantSenders)
        return blocked

    def change_senders(self, command: AdminCommand) -> ReviewResult:
        """Apply an idempotent sender change; it takes effect with the next mail."""
        try:
            change = SenderChange.model_validate(command.patch)
            current = self._current_senders()
            updated = change_irrelevant_senders(current, change.action == "add",
                                                change.addresses, change.domains)
            if updated == current:
                message = (f"„{change.entries}“ wird bereits ignoriert." if change.action == "add"
                           else f"„{change.entries}“ stand nicht auf der Liste.")
            else:
                assert self.senders is not None  # _current_senders() refused a missing list
                self.senders.save("irrelevant-senders", updated.model_dump(mode="json"))
                message = (f"„{change.entries}“ wird ab sofort ignoriert: neue Mails werden ohne "
                           "KI-Aufruf und ohne Benachrichtigung aussortiert."
                           if change.action == "add" else
                           f"„{change.entries}“ wird künftig wieder normal verarbeitet.")
            return ReviewResult(status=ResultStatus.DONE, message=message)
        except (ValueError, OSError):
            return ReviewResult(status=ResultStatus.INVALID,
                                message="Absenderliste nicht geändert: ungültig oder nicht schreibbar.")

    def path(self, command: AdminCommand) -> Path:
        filename = "config.yaml" if command.kind == AdminKind.SETTINGS else (
            "topics.yaml" if command.category == "relevant" else "irrelevant_topics.yaml")
        return self.directory / filename

    def candidate(self, command: AdminCommand) -> dict:
        path = self.path(command)
        if file_hash(path) != command.expected_hash:
            raise ConfigurationConflict("Datei wurde inzwischen geändert; bitte neu laden")
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if command.kind == AdminKind.SETTINGS:
            return apply_settings(raw, command.patch, command.acknowledged)
        if not command.acknowledged:
            raise ValueError("Themenänderung muss bestätigt werden")
        topic = Topic.model_validate(command.patch)
        existing = [Topic.model_validate(item) for item in raw["topics"]]
        topics = [topic if item.id == topic.id else item for item in existing]
        if not any(item.id == topic.id for item in existing):
            topics.append(topic)
        model = TopicsConfig if command.category == "relevant" else IrrelevantTopicsConfig
        return model(topics=topics).model_dump(mode="json")

    def render(self, command: AdminCommand, candidate: dict) -> str:
        """New file content; config.yaml keeps its comments and layout."""
        if command.kind != AdminKind.SETTINGS:
            return topics_document([Topic.model_validate(item) for item in candidate["topics"]])
        content = set_scalars(self.path(command).read_text(encoding="utf-8"), command.patch)
        if yaml.safe_load(content) != candidate:
            # Never write a file whose meaning differs from the validated candidate.
            raise YamlEditError("config.yaml lässt sich hier nicht sicher ändern")
        return content

    def execute(self, command: AdminCommand) -> ReviewResult:
        if not self.authorize(command.actor):
            return ReviewResult(status=ResultStatus.UNAUTHORIZED, message="Nicht autorisiert.")
        if command.kind == AdminKind.SENDERS:
            return self.change_senders(command)
        try:
            candidate = self.candidate(command)
            content = self.render(command, candidate)
            journal = {"schema_version": 1, "command": command.model_dump(mode="json"),
                       "candidate_hash": hashlib.sha256(content.encode()).hexdigest(), "status": "prepared"}
            self.store.save(f"configuration-{command.idempotency_key}", journal)
            atomic_replace(self.path(command), content)
            journal["status"] = "saved"
            self.store.save(f"configuration-{command.idempotency_key}", journal)
            if command.kind == AdminKind.SETTINGS:
                Settings.model_validate(candidate)
                live = self.active.model_dump(mode="json")
                for field in LIVE_FIELDS:
                    live[field] = candidate.get(field, live[field])
                self.active = Settings.model_validate(live)
                self.activate(self.active)
                message = ("Gespeichert. Pollintervall, Aufbewahrung, Metrikannahmen und persönliche Angaben "
                           "übernommen; übrige Änderungen beim nächsten Start.")
            else:
                if command.category == "relevant":
                    self.activate_topics([Topic.model_validate(item) for item in candidate["topics"]])
                message = "Themen gespeichert; neue Analysen übernehmen sie am nächsten sicheren Verarbeitungspunkt."
            return ReviewResult(status=ResultStatus.DONE, message=message)
        except ConfigurationConflict:
            return ReviewResult(status=ResultStatus.STALE, message="Datei inzwischen geändert; bitte neu laden.")
        except (ValueError, OSError):
            return ReviewResult(status=ResultStatus.INVALID,
                                message="Konfiguration nicht übernommen: ungültig, geändert oder nicht schreibbar.")

    def reconcile(self, command: AdminCommand) -> ReviewResult:
        if command.kind == AdminKind.SENDERS:
            # Never repeated: done if the list already shows the requested state.
            try:
                change = SenderChange.model_validate(command.patch)
                current = self._current_senders()
                done = change_irrelevant_senders(current, change.action == "add", change.addresses,
                                                 change.domains) == current
            except (ValueError, OSError):
                done = False
            if done:
                return ReviewResult(status=ResultStatus.DONE,
                                    message="Absenderliste nach Neustart abgeglichen.")
            return ReviewResult(status=ResultStatus.FAILED,
                                message="Absenderänderung unterbrochen; bitte erneut auslösen.")
        journal = self.store.load(f"configuration-{command.idempotency_key}", {})
        if journal.get("candidate_hash") == file_hash(self.path(command)):
            return ReviewResult(status=ResultStatus.DONE,
                                message="Gespeicherte Konfiguration nach Neustart abgeglichen.")
        return ReviewResult(status=ResultStatus.FAILED,
                            message="Konfigurationsänderung unterbrochen; bitte neu prüfen.")
