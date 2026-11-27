"""Validated local configuration commands, optimistic concurrency and recovery."""
from __future__ import annotations

import copy
import hashlib
import re
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..domain.relevance import IrrelevantSenders, list_key
from ..i18n import de
from ..llm.learning import topics_document
from ..mailbox.sender_filter import (
    change_irrelevant_senders,
    change_list_exception,
    drop_rule,
    new_rule,
    promote_exception,
    put_rule,
    rule_value,
    save_sender_filter,
    set_header_mode,
    switch_rule,
)
from ..persistence.storage import JsonStore, atomic_replace
from ..review.commands import CommandSource
from ..review.results import ResultStatus, ReviewResult
from ..support.yaml_edit import YamlEditError, replace_block, set_list, set_scalars
from . import (
    MAILBOX_FIELDS,
    IrrelevantTopicsConfig,
    PromptConfig,
    Settings,
    Topic,
    TopicsConfig,
    read_yaml,
)


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


HEADER_NAMES = {"automated": "Automatische Systemmails", "lists": "Newsletter und Verteiler"}
MODE_NAMES = {"off": "aus", "trial": "Probelauf", "on": "an"}


class RuleChange(BaseModel):
    """7.7.3: one change of a prefilter rule; idempotent through the rule's stable id."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    rule_action: Literal["add", "remove", "enable", "disable", "promote", "header_mode", "list_exception_add",
                         "list_exception_remove"]
    kind: Literal["address", "domain", "pattern", "subject"] | None = None
    value: str = Field(default="", max_length=320)
    action: Literal["ignore", "vip", "allow_only"] = "ignore"
    mailbox_id: int | None = Field(default=None, ge=1, le=99)
    topic_ids: list[str] = Field(default_factory=list, max_length=20)
    note: str = Field(default="", max_length=200)
    origin: Literal["manual", "mail", "hint", "telegram"] = "manual"
    rule_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{16}$")
    mail_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{24}$")
    # 7.7.4: the header filters and their list exceptions.
    header: Literal["automated", "lists"] | None = None
    mode: Literal["off", "trial", "on"] | None = None

    @model_validator(mode="after")
    def complete(self) -> RuleChange:
        needed = {"add": self.kind is not None and self.value.strip() != "",
                  "promote": self.mailbox_id is not None and self.value.strip() != "",
                  "header_mode": self.header is not None and self.mode is not None,
                  "list_exception_add": self.value.strip() != "",
                  "list_exception_remove": self.value.strip() != ""}
        if not needed.get(self.rule_action, self.rule_id is not None):
            raise ValueError("Regeländerung unvollständig")
        return self


SETTINGS_FIELDS = {
    "poll_interval_seconds", "timezone", "language", "test_mode", "personal_info",
    "drafts.enabled", "drafts.folder", "auto_draft",
    "briefings.enabled", "briefings.times", "briefings.mailbox", "briefings.skip_empty",
    "event_defaults.video_duration_minutes", "event_defaults.in_person_duration_minutes",
    "proposal_reconciliation.max_semantic_candidates",
    "targets.todoist_project", "targets.google_calendar", "targets.calendar_provider", "targets.task_provider",
    "targets.caldav_calendar_url", "targets.caldav_task_url", "targets.outlook_calendar",
    "targets.microsoft_todo_list", "targets.microsoft_tenant", "targets.google_tasks_list",
    "targets.calendar_reminder_enabled", "targets.calendar_reminder_minutes",
    "attachments.store_originals", "attachments.max_original_bytes", "attachments.max_total_bytes",
    "limits.llm_calls_per_minute", "limits.max_mail_bytes", "limits.max_attachment_bytes",
    "limits.max_llm_payload_bytes",
    "retention.full_mail_days", "retention.debug_llm_days", "retention.analysis_days", "retention.history_days",
    "logging.console.level", "logging.file.level", "logging.llm.include_requests", "logging.llm.include_responses",
    "metrics.enabled", "metrics.retention_days", "metrics.usd_per_eur", "metrics.exchange_rate_date",
    "metrics.ollama_power_watts", "metrics.electricity_eur_per_kwh",
}
for service in ("imap", "telegram", "openrouter", "ollama", "todoist", "google_calendar", "caldav", "microsoft",
                "google_tasks", "notion"):
    SETTINGS_FIELDS.update(f"timeouts.{service}.{field}" for field in
                           ("timeout_seconds", "retries", "initial_backoff_seconds", "max_backoff_seconds"))
# 3.3.12 (Planung 3.4): further operational settings; not data_directory, log paths, web host/port/hosts.
SETTINGS_FIELDS.update({
    "activity_report.enabled",
    "activity_report.export_mails_without_events",
    "activity_report.max_fulltext_chars",
    "activity_report.max_llm_calls",
    "activity_report.max_mails",
    "activity_report.max_share_of_llm_budget",
    "daily_briefing.include_calendar",
    "daily_briefing.include_open",
    "daily_briefing.include_tasks",
    "imap.batch_size",
    "imap.global_newest_first",
    "learning.parallel_llm_calls",
    "learning.decision_llm_content",
    "logging.console.enabled",
    "logging.verbose",
    "logging.file.enabled",
    "logging.llm.enabled",
    "logging.llm.level",
    "logging.telegram.enabled",
    "logging.telegram.level",
    "retention.activity_report_days",
    "retention.decision_learning_days",
    "retention.cleanup_interval_minutes",
    "smart_reply",
    "telegram.chat_id",
    "telegram.sequential_questions",
    "telegram.user_id",
    "vision.enabled",
    "vision.max_edge_pixels",
    "vision.max_image_bytes",
    "vision.max_images_per_mail",
    "web.lan_access",
    "web.session_days",
    "help_chat.enabled",
    "help_chat.max_question_chars",
    "help_chat.max_context_bytes",
    "help_chat.requests_per_minute_per_session",
})
for field in ("interpretation_attempts", "interpretation_backoff_seconds", "revision_attempts",
              "revision_backoff_seconds"):
    SETTINGS_FIELDS.add(f"retries.{field}")

LIVE_FIELDS = {"poll_interval_seconds", "retention", "metrics", "personal_info", "notifications", "help_chat",
               "event_defaults", "proposal_reconciliation", "drafts", "auto_draft", "briefings"}
SETUP_FIELDS = {"timezone", "imap.host", "imap.port", "imap.connection_mode", "imap.folders",
                "event_defaults.video_duration_minutes", "event_defaults.in_person_duration_minutes",
                "imap.primary_folder", "imap.drafts_folder", "imap.historical_start", "telegram.enabled",
                "push.enabled", "push.subject",
                "targets.todoist_project", "targets.google_calendar", "targets.calendar_provider",
                "targets.task_provider", "targets.caldav_calendar_url", "targets.caldav_task_url",
                "targets.outlook_calendar", "targets.microsoft_todo_list", "targets.microsoft_tenant",
                "targets.google_tasks_list", "targets.notion_data_source_id", "targets.notion_properties",
                "targets.notion_open_status", "targets.notion_done_statuses",
                "daily_briefing.enabled", "daily_briefing.time"}
for section, fields in {
    "quiet_hours": ("enabled", "start", "end", "allow_system_errors"),
    "batching": ("enabled", "window_seconds"),
    "categories": ("decisions", "action_results", "daily_briefing", "system_errors"),
    "delivery": ("max_attempts", "initial_backoff_seconds", "max_backoff_seconds", "history_days", "max_pending"),
}.items():
    SETUP_FIELDS.update(f"notifications.{section}.{name}" for name in fields)
SETUP_FIELDS.add("notifications.telegram_content")
# 7.9.8 / 8.2: written only by the explicit adoption of a hosted OAuth sign-in;
# no form offers it as an input field.
SETUP_FIELDS.update({"targets.google_connection", "targets.microsoft_connection", "targets.notion_connection"})
# Mailbox fields of the 3.1 format; the index is the position in imap.mailboxes.
MAILBOX_SETUP_FIELDS = ("label", "enabled", "host", "port", "connection_mode", "folders", "primary_folder",
                        "drafts_folder", "historical_start")
MAILBOX_POLICY_FIELDS = {
    "target_profile",
    "personal_info",
    "smart_reply",
    "auto_draft",
    "daily_briefing",
    "activity_report_folder",
    "retention",
    "retention.full_mail_days",
    "event_defaults.video_duration_minutes",
    "event_defaults.in_person_duration_minutes",
    # 4.7: applied without a restart; it only affects mails prepared afterwards.
    "mail_client",
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
    if setup and (name in {"imap.mailboxes", "target_profiles", "iserv.accounts"} or
            re.fullmatch(r"imap\.mailboxes\.[0-9]\.(.+)", name)
            and name.split(".", 3)[3] in MAILBOX_POLICY_FIELDS):
        return True
    return name in (SETUP_FIELDS if setup else SETTINGS_FIELDS)


# 8.7: the settings a customer may change in customer mode – an explicit list, nothing else. AI
# configuration, limits, logging, retention, timeouts, metrics (including the exchange rate), the web
# server, test mode and every other technical setting stay with the operator.
CUSTOMER_FIELDS = frozenset({
    "language", "timezone", "personal_info", "smart_reply", "auto_draft",
    "drafts.enabled", "drafts.folder",
    "briefings.enabled", "briefings.times", "briefings.mailbox", "briefings.skip_empty",
    "daily_briefing.enabled", "daily_briefing.time", "daily_briefing.include_calendar",
    "daily_briefing.include_open", "daily_briefing.include_tasks",
    "event_defaults.video_duration_minutes", "event_defaults.in_person_duration_minutes",
    "telegram.chat_id", "telegram.user_id", "telegram.sequential_questions", "push.enabled",
    "imap.host", "imap.port", "imap.connection_mode", "imap.folders", "imap.primary_folder",
    "imap.drafts_folder", "imap.historical_start", "imap.mailboxes", "target_profiles",
    "notifications.telegram_content",
})
_CUSTOMER_PREFIXES = ("targets.", "notifications.quiet_hours.", "notifications.batching.",
                      "notifications.categories.")


def customer_may_change(name: str) -> bool:
    if name in CUSTOMER_FIELDS or name.startswith(_CUSTOMER_PREFIXES):
        return True
    match = re.fullmatch(r"imap\.mailboxes\.[0-9]\.(.+)", name)
    return match is not None and (match.group(1) in MAILBOX_SETUP_FIELDS or match.group(1) in MAILBOX_POLICY_FIELDS)


def changed_fields(patch: dict[str, Any], current: list[dict[str, Any]]) -> list[str]:
    """The patch's fields; a whole mailbox list counts by what really differs (8.7.15).

    The mailbox pages always save the complete list. Compared with *current* (the configured
    mailboxes), only an added or removed mailbox counts as ``imap.mailboxes``; otherwise each
    differing field of a mailbox is named by its list position, like ``imap.mailboxes.1.label``.
    """
    fields = [name for name in patch if name != "imap.mailboxes"]
    if "imap.mailboxes" not in patch:
        return fields
    before = {box["id"]: box for box in current}
    proposed = patch["imap.mailboxes"]
    if sorted(before) != sorted(box["id"] for box in proposed):
        return [*fields, "imap.mailboxes"]
    for index, box in enumerate(proposed):
        fields += _differences(f"imap.mailboxes.{index}", before[box["id"]], box)
    return fields


def _differences(prefix: str, old: Any, new: Any) -> list[str]:
    """Dotted names of the differing leaves; an unset section (``None``) compares as empty."""
    if isinstance(old, dict) or isinstance(new, dict):
        if (old is None or isinstance(old, dict)) and (new is None or isinstance(new, dict)):
            old, new = old or {}, new or {}
            return [name for key in sorted({*old, *new})
                    for name in _differences(f"{prefix}.{key}", old.get(key), new.get(key))]
    return [prefix] if old != new else []


def customer_command_allowed(command: AdminCommand, current: list[dict[str, Any]] | None = None) -> bool:
    """Topics and sender rules are the customer's; settings only with customer fields, never partially.

    A mailbox list (8.7.15) counts by its changed fields against *current*; adding or removing one
    of the instance's own mailboxes is a customer change as well.
    """
    if command.kind in {AdminKind.TOPICS, AdminKind.SENDERS}:
        return True
    if "imap.mailboxes" in command.patch and current is None:
        return False
    fields = changed_fields(command.patch, current or [])
    return all(name == "imap.mailboxes" or customer_may_change(name) for name in fields)


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
    "decision_rule_learning": "Themen aus Entscheidungen",
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
                 senders: JsonStore | None = None) -> None:
        self.directory, self.store, self.active = directory, store, active
        self.authorize, self.activate = authorize, activate
        # 8.7: whether the actor is a customer session in customer mode (set by the composition).
        self.restricted: Callable[[str], bool] = lambda actor: False
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

    def _require_mailbox(self, mailbox_id: int | None) -> None:
        if mailbox_id is not None:
            path = self.directory / "config.yaml"
            active = Settings.model_validate(read_yaml(path)) if path.exists() else self.active
            if active.imap.mailbox(mailbox_id) is None:
                raise ValueError("Postfach nicht konfiguriert")

    def change_rules(self, actor: str, change: RuleChange, *, verified: bool = False) -> ReviewResult:
        """7.7.3: add, remove, switch or promote one rule; a repeated change changes nothing.

        ``verified``: the caller already checked the sender (the Telegram user and chat of the button);
        a web change is checked again here, right before writing.
        """
        try:
            self._require_mailbox(change.mailbox_id)
            current, now = self._current_senders(), datetime.now(UTC)
            if change.rule_action == "add":
                assert change.kind is not None  # RuleChange.complete
                rule = new_rule(change.kind, change.value, change.action, now, mailbox=change.mailbox_id,
                                topic_ids=change.topic_ids, note=change.note, origin=change.origin)
                updated, outcome = put_rule(current, rule)
                message = {"exists": de("Diese Regel gibt es bereits."),
                           "changed": de("Regel für „{value}“ geändert.", value=rule.value),
                           "added": {"ignore": de("„{value}“ wird künftig ohne KI-Aufruf aussortiert.",
                                                  value=rule.value),
                                     "vip": de("„{value}“ gilt künftig ohne Relevanzprüfung als relevant.",
                                               value=rule.value),
                                     "allow_only": de("„{value}“ wird nie vorgefiltert.", value=rule.value),
                                     }[rule.action]}[outcome]
            elif change.rule_action == "remove":
                assert change.rule_id is not None
                updated, removed = drop_rule(current, change.rule_id)
                message = (de("Regel für „{value}“ entfernt.", value=removed.value) if removed is not None
                           else de("Diese Regel gibt es nicht mehr."))
            elif change.rule_action in {"enable", "disable"}:
                assert change.rule_id is not None
                updated = switch_rule(current, change.rule_id, change.rule_action == "enable")
                message = de("Regel eingeschaltet.") if change.rule_action == "enable" else de("Regel ausgeschaltet.")
            elif change.rule_action == "header_mode":
                assert change.header is not None and change.mode is not None
                updated = set_header_mode(current, change.header, change.mode, now)
                message = de("{filter}: {mode}.", filter=de(HEADER_NAMES[change.header]),
                             mode=de(MODE_NAMES[change.mode]))
            elif change.rule_action in {"list_exception_add", "list_exception_remove"}:
                key = list_key(change.value)
                added = change.rule_action == "list_exception_add"
                updated = change_list_exception(current, key, added)
                message = (de("Verteiler {list} wird nie vorgefiltert.", list=key) if added
                           else de("Ausnahme für Verteiler {list} entfernt.", list=key))
            else:
                assert change.mailbox_id is not None
                address = rule_value("address", change.value)
                updated = promote_exception(current, change.mailbox_id, address, now)
                message = de("„{value}“ gilt jetzt als VIP-Absender.", value=address)
            if updated != current:
                assert self.senders is not None  # _current_senders() refused a missing list
                if not verified and not self.authorize(actor):
                    return ReviewResult(status=ResultStatus.UNAUTHORIZED, message=de("Sitzung inzwischen abgelaufen."))
                save_sender_filter(self.senders, updated)
            return ReviewResult(status=ResultStatus.DONE, message=message)
        except (ValueError, OSError):
            return ReviewResult(status=ResultStatus.INVALID,
                                message=de("Regel nicht geändert: ungültig oder nicht schreibbar."))

    def change_senders(self, command: AdminCommand) -> ReviewResult:
        """Apply an idempotent sender change; it takes effect with the next mail."""
        try:
            if command.expected_hash is not None and command.expected_hash != file_hash(self.path(command)):
                raise ConfigurationConflict("Absenderfilter inzwischen geändert")
            if "rule_action" in command.patch:
                return self.change_rules(command.actor, RuleChange.model_validate(command.patch))
            change = SenderChange.model_validate(command.patch)
            self._require_mailbox(change.mailbox_id)
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
            # The list lives where its store keeps it; the version check must read that file.
            return (self.senders.directory if self.senders is not None else self.directory) / "irrelevant-senders.json"
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
                # Late: against the layer direction, named in tests/unit/test_layers.py.
                from ..proposals.profile_usage import profile_references
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
        roots = {"imap.mailboxes": "imap", "target_profiles": "target_profiles", "iserv.accounts": "iserv"}
        complex_roots = {roots[name] for name in command.patch if name in roots}
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
        with self.store._thread_lock:
            return self._execute(command)

    def permitted(self, command: AdminCommand) -> bool:
        """Session still valid and, for a customer, only customer fields (checked again before writing)."""
        if not self.authorize(command.actor):
            return False
        if not self.restricted(command.actor):
            return True
        current = None
        if "imap.mailboxes" in command.patch and command.kind in {AdminKind.SETTINGS, AdminKind.SETUP}:
            current = self.configured_mailboxes()
        return customer_command_allowed(command, current)

    def configured_mailboxes(self) -> list[dict[str, Any]]:
        """The mailboxes of config.yaml as the mailbox pages write them (also the 3.0 single format)."""
        settings = Settings.model_validate(read_yaml(self.directory / "config.yaml"))
        return [box.model_dump(mode="json") for box in settings.imap.configured_mailboxes()]

    def _execute(self, command: AdminCommand) -> ReviewResult:
        if not self.permitted(command):
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
            if not self.permitted(command):
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
        # Late: against the layer direction, named in tests/unit/test_layers.py.
        from ..runtime.setup import SetupState
        draft = self.store.load_model("setup-state", SetupState)
        # Setup drafts (mailboxes, IServ accounts, profiles) share kind "settings"; once approved they
        # are part of config.yaml, and a stale draft on the old file would block every later change.
        if (draft is not None and draft.patch == command.patch
                and (draft.kind != "settings" or command.kind == AdminKind.SETUP)):
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
