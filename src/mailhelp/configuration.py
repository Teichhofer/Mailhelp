"""Validated local configuration commands, optimistic concurrency and recovery."""
from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .config import (
    MAILBOX_FIELDS,
    IrrelevantTopicsConfig,
    PromptConfig,
    Settings,
    Topic,
    TopicsConfig,
    read_yaml,
)
from .domain.relevance import IrrelevantSenders
from .learning import topics_document
from .review.commands import CommandSource
from .review.results import ResultStatus, ReviewResult
from .sender_filter import change_irrelevant_senders, save_sender_filter
from .storage import JsonStore, atomic_replace
from .yaml_edit import YamlEditError, replace_block, set_list, set_scalars


class ConfigurationConflict(ValueError):
    """A validated edit no longer refers to the file currently on disk."""


class AdminKind(StrEnum):
    SETTINGS = "settings"
    SETUP = "setup"
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
    patch: dict[str, Any] = Field(max_length=60)
    acknowledged: bool = False
    context_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def file_edits_need_a_hash(self) -> AdminCommand:
        if self.kind != AdminKind.SENDERS and self.expected_hash is None:
            raise ValueError("Dateiänderungen benötigen den erwarteten Dateihash")
        return self


class SenderChange(BaseModel):
    """Add or remove ignored senders; ``mail_id`` names the mail it came from."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    action: Literal["add", "remove", "allow", "unallow"]
    mailbox_id: int | None = Field(default=None, ge=1, le=99)
    addresses: list[str] = Field(default_factory=list, max_length=10)
    domains: list[str] = Field(default_factory=list, max_length=10)
    mail_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{24}$")

    @model_validator(mode="after")
    def valid_entries(self) -> SenderChange:
        if self.action in {"allow", "unallow"} and (self.mailbox_id is None or self.domains):
            raise ValueError("Ausnahmen benötigen ein Postfach und genaue Adressen")
        if not self.addresses and not self.domains:
            raise ValueError("Mindestens eine Adresse oder Domain angeben")
        IrrelevantSenders(addresses=sorted(set(self.addresses)), domains=sorted(set(self.domains)))
        return self

    @property
    def entries(self) -> str:
        return ", ".join([*self.addresses, *self.domains])


SETTINGS_FIELDS = {
    "poll_interval_seconds", "timezone", "test_mode", "personal_info",
    "event_defaults.video_duration_minutes", "event_defaults.in_person_duration_minutes",
    "proposal_reconciliation.max_semantic_candidates",
    "targets.todoist_project", "targets.google_calendar", "targets.calendar_provider", "targets.task_provider",
    "targets.caldav_calendar_url", "targets.caldav_task_url", "targets.outlook_calendar",
    "targets.microsoft_todo_list", "targets.microsoft_tenant",
    "attachments.store_originals", "attachments.max_original_bytes", "attachments.max_total_bytes",
    "limits.llm_calls_per_minute", "limits.max_mail_bytes", "limits.max_llm_payload_bytes",
    "retention.full_mail_days", "retention.debug_llm_days", "retention.analysis_days", "retention.history_days",
    "logging.console.level", "logging.file.level", "logging.llm.include_requests", "logging.llm.include_responses",
    "metrics.enabled", "metrics.retention_days", "metrics.usd_per_eur", "metrics.exchange_rate_date",
    "metrics.ollama_power_watts", "metrics.electricity_eur_per_kwh",
}
for service in ("imap", "telegram", "openrouter", "ollama", "todoist", "google_calendar", "caldav", "microsoft"):
    SETTINGS_FIELDS.update(f"timeouts.{service}.{field}" for field in
                           ("timeout_seconds", "retries", "initial_backoff_seconds", "max_backoff_seconds"))
for field in ("interpretation_attempts", "interpretation_backoff_seconds", "revision_attempts",
              "revision_backoff_seconds"):
    SETTINGS_FIELDS.add(f"retries.{field}")

LIVE_FIELDS = {"poll_interval_seconds", "retention", "metrics", "personal_info", "notifications",
               "event_defaults", "proposal_reconciliation"}
SETUP_FIELDS = {"timezone", "imap.host", "imap.port", "imap.connection_mode", "imap.folders",
                "event_defaults.video_duration_minutes", "event_defaults.in_person_duration_minutes",
                "imap.primary_folder", "imap.drafts_folder", "telegram.enabled", "push.enabled",
                "targets.todoist_project", "targets.google_calendar", "targets.calendar_provider",
                "targets.task_provider", "targets.caldav_calendar_url", "targets.caldav_task_url",
                "targets.outlook_calendar", "targets.microsoft_todo_list", "targets.microsoft_tenant",
                "daily_briefing.enabled", "daily_briefing.time"}
for section, fields in {
    "quiet_hours": ("enabled", "start", "end", "allow_system_errors"),
    "batching": ("enabled", "window_seconds"),
    "categories": ("decisions", "action_results", "daily_briefing", "system_errors"),
    "delivery": ("max_attempts", "initial_backoff_seconds", "max_backoff_seconds", "history_days", "max_pending"),
}.items():
    SETUP_FIELDS.update(f"notifications.{section}.{name}" for name in fields)
SETUP_FIELDS.add("notifications.telegram_content")
# Mailbox fields of the 3.1 format; the index is the position in imap.mailboxes.
MAILBOX_SETUP_FIELDS = ("label", "enabled", "host", "port", "connection_mode", "folders", "primary_folder",
                        "drafts_folder")
MAILBOX_POLICY_FIELDS = {
    "target_profile",
    "personal_info",
    "smart_reply",
    "daily_briefing",
    "activity_report_folder",
    "retention",
    "retention.full_mail_days",
    "event_defaults.video_duration_minutes",
    "event_defaults.in_person_duration_minutes",
    "notifications.quiet_hours.enabled",
    "notifications.quiet_hours.start",
    "notifications.quiet_hours.end",
    "notifications.quiet_hours.allow_system_errors",
    *(
        f"notifications.categories.{name}"
        for name in ("decisions", "action_results", "daily_briefing", "system_errors")
    ),
}
_MAILBOX_SETUP_FIELD = re.compile(r"^imap\.mailboxes\.[0-9]\.(?:" + "|".join(MAILBOX_SETUP_FIELDS) + r")$")


def offered(name: str, setup: bool) -> bool:
    """Whether the web interface offers *name* for editing."""
    if setup and _MAILBOX_SETUP_FIELD.match(name):
        return True
    if setup and (name in {"imap.mailboxes", "target_profiles"} or
            re.fullmatch(r"imap\.mailboxes\.[0-9]\.(.+)", name)
            and name.split(".", 3)[3] in MAILBOX_POLICY_FIELDS):
        return True
    return name in (SETUP_FIELDS if setup else SETTINGS_FIELDS)


def set_dotted(document: dict[str, Any], dotted: str, value: object) -> None:
    """Set *dotted* in *document*; numeric parts index lists (``imap.mailboxes.0.host``)."""
    *parents, name = dotted.split(".")
    target: Any = document
    for part in parents:
        if isinstance(target, dict) and target.get(part) is None:
            target[part] = {}
        target = target[int(part)] if isinstance(target, list) else target.setdefault(part, {})
    target[int(name) if isinstance(target, list) else name] = value


STEP_LABELS = {
    "relevance": "Relevanz (Rückfall)", "summary": "Zusammenfassung", "action_router": "Aktionszuordnung",
    "task_extraction": "Aufgabenerkennung", "event_extraction": "Terminerkennung",
    "mail_question_resolution": "Rückfragen aus der Mail", "telegram_answer_interpretation": "Antworten verstehen",
    "telegram_answer_clarification": "Nachfragen formulieren", "proposal_revision": "Vorschläge überarbeiten",
    "learning_classification": "Lernmodus: Einordnung", "learning_abstraction": "Lernmodus: Themen",
    "calendar_duplicate": "Kalender-Dubletten", "vision_ocr": "Bilderkennung (OCR)",
}


def effective_models(prompts: PromptConfig, jev_model: str | None,
                     local_model: str | None) -> list[tuple[str, str, str, str]]:
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
    return hashlib.sha256(path.read_bytes() if path.exists() else b"").hexdigest()


def apply_settings(raw: dict[str, Any], patch: dict[str, Any], acknowledged: bool, *,
                   setup: bool = False) -> dict[str, Any]:
    import copy
    candidate = copy.deepcopy(raw)
    if candidate.get("notifications") is None and any(name.startswith("notifications.") for name in patch):
        candidate.pop("notifications", None)
    if not all(offered(name, setup) for name in patch):
        raise ValueError("Nicht angebotene Einstellung")
    if patch and not acknowledged:
        raise ValueError("Änderungen und ihre Folgen müssen bestätigt werden")
    for dotted, value in patch.items():
        try:
            set_dotted(candidate, dotted, value)
        except (IndexError, TypeError) as exc:
            raise ValueError("Nicht angebotene Einstellung") from exc
    if "imap.mailboxes" in patch and raw.get("imap", {}).get("mailboxes") is None:
        for name in MAILBOX_FIELDS:
            candidate["imap"].pop(name, None)
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
            if command.expected_hash is not None and command.expected_hash != file_hash(self.path(command)):
                raise ConfigurationConflict("Absenderfilter inzwischen geändert")
            change = SenderChange.model_validate(command.patch)
            if change.mailbox_id is not None:
                path = self.directory / "config.yaml"
                active = Settings.model_validate(read_yaml(path)) if path.exists() else self.active
                if active.imap.mailbox(change.mailbox_id) is None:
                    raise ValueError("Postfach nicht konfiguriert")
            current = self._current_senders()
            updated = change_irrelevant_senders(current, change.action in {"add", "allow"},
                change.addresses, change.domains, change.mailbox_id, allow=change.action in {"allow", "unallow"})
            if updated == current:
                message = (f"„{change.entries}“ wird bereits ignoriert." if change.action == "add"
                           else f"„{change.entries}“ stand nicht auf der Liste.")
            else:
                assert self.senders is not None  # _current_senders() refused a missing list
                if not self.authorize(command.actor):
                    return ReviewResult(status=ResultStatus.UNAUTHORIZED, message="Sitzung inzwischen abgelaufen.")
                save_sender_filter(self.senders, updated)
                message = (f"„{change.entries}“ wird ab sofort ignoriert: neue Mails werden ohne "
                           "KI-Aufruf und ohne Benachrichtigung aussortiert."
                           if change.action == "add" else
                           f"„{change.entries}“ wird künftig wieder normal verarbeitet.")
            if change.action in {"allow", "unallow"}:
                message = f"Absender-Ausnahme für Postfach {change.mailbox_id} gespeichert."
            return ReviewResult(status=ResultStatus.DONE, message=message)
        except ConfigurationConflict:
            return ReviewResult(status=ResultStatus.STALE, message="Absenderfilter inzwischen geändert.")
        except (ValueError, OSError):
            return ReviewResult(status=ResultStatus.INVALID,
                                message="Absenderliste nicht geändert: ungültig oder nicht schreibbar.")

    def path(self, command: AdminCommand) -> Path:
        if command.kind == AdminKind.SENDERS:
            return self.directory / "irrelevant-senders.json"
        filename = "config.yaml" if command.kind in {AdminKind.SETTINGS, AdminKind.SETUP} else (
            "topics.yaml" if command.category == "relevant" else "irrelevant_topics.yaml")
        return self.directory / filename

    def candidate(self, command: AdminCommand) -> dict[str, Any]:
        path = self.path(command)
        if file_hash(path) != command.expected_hash:
            raise ConfigurationConflict("Datei wurde inzwischen geändert; bitte neu laden")
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if command.kind in {AdminKind.SETTINGS, AdminKind.SETUP}:
            candidate = apply_settings(raw, command.patch, command.acknowledged, setup=command.kind == AdminKind.SETUP)
            if "target_profiles" in command.patch:
                from .profile_usage import profile_references
                proposed = {item["id"] for item in candidate["target_profiles"]}
                for profile in raw.get("target_profiles", []):
                    if profile["id"] not in proposed and profile_references(self.store, self.active, profile["id"]):
                        raise ValueError("Zielprofil wird noch verwendet")
            return candidate
        if not command.acknowledged:
            raise ValueError("Themenänderung muss bestätigt werden")
        topic = Topic.model_validate(command.patch)
        if topic.mailboxes is not None:
            configured = Settings.model_validate(read_yaml(self.directory / "config.yaml")).imap.configured_mailboxes()
            if not set(topic.mailboxes) <= {box.id for box in configured}:
                raise ValueError("Thema verweist auf ein nicht konfiguriertes Postfach")
        existing = [Topic.model_validate(item) for item in raw["topics"]]
        topics = [topic if item.id == topic.id else item for item in existing]
        if not any(item.id == topic.id for item in existing):
            topics.append(topic)
        model = TopicsConfig if command.category == "relevant" else IrrelevantTopicsConfig
        return model(topics=topics).model_dump(mode="json")

    def render(self, command: AdminCommand, candidate: dict[str, Any]) -> str:
        """New file content; config.yaml keeps its comments and layout."""
        if command.kind not in {AdminKind.SETTINGS, AdminKind.SETUP}:
            return topics_document([Topic.model_validate(item) for item in candidate["topics"]])
        source = self.path(command).read_text(encoding="utf-8")
        if any(name.startswith("notifications.") for name in command.patch):
            source = re.sub(r"(?m)^(notifications:)[ \t]*(?:null|~)([ \t]*(?:#.*)?)$", r"\1\2", source)
        complex_roots = {"imap" if name.startswith("imap.mailboxes") else "target_profiles"
                         for name in command.patch if name in {"imap.mailboxes", "target_profiles"}}
        if complex_roots:
            simple = {name: value for name, value in command.patch.items()
                      if name.split(".", 1)[0] not in complex_roots}
            content = source
            content = set_scalars(
                content, {name: value for name, value in simple.items() if not isinstance(value, list)}
            )
            for name, value in simple.items():
                if isinstance(value, list):
                    content = set_list(content, name, value, allow_missing=True)
            for root in sorted(complex_roots):
                content = replace_block(content, root, candidate[root])
            if yaml.safe_load(content) != candidate:
                raise YamlEditError("Konfiguration und geprüfter Entwurf unterscheiden sich")
            return content
        scalars = {name: value for name, value in command.patch.items() if not isinstance(value, list)}
        content = set_scalars(source, scalars)
        for name, value in command.patch.items():
            if isinstance(value, list):
                content = set_list(content, name, value, allow_missing=True)
        if yaml.safe_load(content) != candidate:
            # Never write a file whose meaning differs from the validated candidate.
            raise YamlEditError("config.yaml lässt sich hier nicht sicher ändern")
        return content

    def execute(self, command: AdminCommand) -> ReviewResult:
        if not self.authorize(command.actor):
            return ReviewResult(status=ResultStatus.UNAUTHORIZED, message="Nicht autorisiert.")
        if command.context_hash is not None and command.context_hash != file_hash(self.directory / "config.yaml"):
            return ReviewResult(status=ResultStatus.STALE, message="Postfachkonfiguration inzwischen geändert.")
        if command.kind == AdminKind.SENDERS:
            result = self.change_senders(command)
            if result.status == ResultStatus.DONE:
                self.clear_local_draft(command)
            return result
        try:
            candidate = self.candidate(command)
            content = self.render(command, candidate)
            if not self.authorize(command.actor):
                return ReviewResult(status=ResultStatus.UNAUTHORIZED, message="Sitzung inzwischen abgelaufen.")
            journal = {"schema_version": 1, "command": command.model_dump(mode="json"),
                       "candidate_hash": hashlib.sha256(content.encode()).hexdigest(), "status": "prepared"}
            self.store.save(f"configuration-{command.idempotency_key}", journal)
            atomic_replace(self.path(command), content)
            journal["status"] = "saved"
            self.store.save(f"configuration-{command.idempotency_key}", journal)
            if command.kind in {AdminKind.SETTINGS, AdminKind.SETUP}:
                Settings.model_validate(candidate)
                live = self.active.model_dump(mode="json")
                for field in LIVE_FIELDS:
                    live[field] = candidate.get(field, live[field])
                configured = Settings.model_validate(candidate)
                # Operative overrides become effective at the next safe processing point.
                # Connection changes and the adapter set are rebuilt on restart.
                if not self.active.imap.legacy_format:
                    boxes = []
                    for box in self.active.imap.configured_mailboxes():
                        changed = configured.imap.mailbox(box.id)
                        policy = {name.split(".")[0] for name in MAILBOX_POLICY_FIELDS} - {"target_profile"}
                        update = ({name: getattr(changed, name) for name in policy} if changed is not None else {})
                        boxes.append(box.model_copy(update=update).model_dump(mode="json"))
                    live["imap"]["mailboxes"] = boxes
                self.active = Settings.model_validate(live)
                self.activate(self.active)
                message = ("Gespeichert. Pollintervall, Aufbewahrung, Metrikannahmen, Benachrichtigungsprofil "
                           "und persönliche Angaben "
                           "übernommen; übrige Änderungen beim nächsten Start.")
            else:
                if command.category == "relevant":
                    self.activate_topics([Topic.model_validate(item) for item in candidate["topics"]])
                message = "Themen gespeichert; neue Analysen übernehmen sie am nächsten sicheren Verarbeitungspunkt."
            self.clear_local_draft(command)
            return ReviewResult(status=ResultStatus.DONE, message=message)
        except ConfigurationConflict:
            return ReviewResult(status=ResultStatus.STALE, message="Datei inzwischen geändert; bitte neu laden.")
        except (ValueError, OSError):
            return ReviewResult(status=ResultStatus.INVALID,
                                message="Konfiguration nicht übernommen: ungültig, geändert oder nicht schreibbar.")

    def clear_local_draft(self, command: AdminCommand) -> None:
        from .setup import SetupState
        draft = self.store.load_model("setup-state", SetupState)
        if draft is not None and draft.kind != "settings" and draft.patch == command.patch:
            draft.kind, draft.patch, draft.base_hash, draft.configuration_hash = "settings", {}, "", ""
            draft.version += 1
            self.store.save("setup-state", draft.model_dump(mode="json"))

    def reconcile(self, command: AdminCommand) -> ReviewResult:
        if command.kind == AdminKind.SENDERS:
            # Never repeated: done if the list already shows the requested state.
            try:
                change = SenderChange.model_validate(command.patch)
                current = self._current_senders()
                done = change_irrelevant_senders(current, change.action in {"add", "allow"}, change.addresses,
                    change.domains, change.mailbox_id, allow=change.action in {"allow", "unallow"}) == current
            except (ValueError, OSError):
                done = False
            if done:
                self.clear_local_draft(command)
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
