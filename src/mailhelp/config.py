"""Laden und Validieren von Konfiguration und Geheimnissen."""
from __future__ import annotations

import ipaddress
import os
import re
from datetime import datetime
from importlib.resources import files
from pathlib import Path, PureWindowsPath
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator, model_validator

from .metrics import MetricsSettings


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ImapSettings(ConfigModel):
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(ge=1, le=65535)
    folders: list[str] = Field(min_length=1, max_length=100)
    primary_folder: str = "INBOX"
    connection_mode: Literal["ssl", "starttls", "plain"] = "ssl"
    historical_start: datetime | None = None
    batch_size: int = Field(default=25, ge=1, le=1000)
    global_newest_first: bool = False
    drafts_folder: str = Field(default="Drafts", min_length=1, max_length=500, pattern=r"^[^\x00-\x1f\x7f]+$")

    @model_validator(mode="before")
    @classmethod
    def default_primary_to_first_folder(cls, value: object) -> object:
        # Backwards-compatible loading gives old configurations the same clear
        # semantics: their first source is required, all following ones optional.
        if isinstance(value, dict) and "primary_folder" not in value:
            folders = value.get("folders")
            if isinstance(folders, list) and folders:
                value = {**value, "primary_folder": folders[0]}
        return value

    @field_validator("historical_start", mode="before")
    @classmethod
    def valid_historical_start(cls, value: object) -> datetime | None:
        if isinstance(value, str):
            value = re.sub(r"^(\d{4}-\d{2}-\d{2})\s*T\s*", r"\1T", value.strip())
            try:
                value = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("historical_start muss ISO 8601 entsprechen") from exc
        if value is not None and not isinstance(value, datetime):
            raise ValueError("historical_start muss ein Zeitpunkt oder null sein")
        if value is not None and value.tzinfo is None:
            raise ValueError("historical_start muss einen UTC-Offset enthalten")
        return value

    @field_validator("folders")
    @classmethod
    def valid_folders(cls, folders: list[str]) -> list[str]:
        if any(not folder.strip() or "\x00" in folder for folder in folders):
            raise ValueError("Ordnernamen dürfen nicht leer sein oder NUL enthalten")
        if len(folders) != len(set(folders)):
            raise ValueError("Ordnernamen dürfen nicht doppelt vorkommen")
        return folders

    @model_validator(mode="after")
    def primary_is_configured(self) -> ImapSettings:
        """The primary inbox is required; every other configured folder is optional."""
        if self.primary_folder not in self.folders:
            raise ValueError("primary_folder muss in folders enthalten sein")
        return self

    @property
    def required_folders(self) -> tuple[str, ...]:
        return (self.primary_folder,)

    @property
    def optional_folders(self) -> tuple[str, ...]:
        return tuple(folder for folder in self.folders if folder != self.primary_folder)


class TelegramSettings(ConfigModel):
    enabled: bool = True
    user_id: int = Field(default=1, gt=0)
    chat_id: int = 1
    sequential_questions: bool = True


class TargetSettings(ConfigModel):
    todoist_project: str = Field(min_length=1, max_length=500)
    google_calendar: str = Field(min_length=1, max_length=500)


class LimitSettings(ConfigModel):
    max_mail_bytes: int = Field(ge=1024, le=100_000_000)
    max_header_bytes: int = Field(default=64_000, ge=256, le=1_000_000)
    max_display_header_characters: int = Field(default=500, ge=1, le=10_000)
    max_mime_parts: int = Field(default=100, ge=1, le=10_000)
    max_decoded_text_bytes: int = Field(default=1_000_000, ge=1, le=100_000_000)
    max_html_characters: int = Field(default=1_000_000, ge=1, le=100_000_000)
    max_html_tags: int = Field(default=20_000, ge=1, le=1_000_000)
    max_html_depth: int = Field(default=100, ge=1, le=10_000)
    max_llm_payload_bytes: int = Field(default=500_000, ge=1, le=100_000_000)
    llm_calls_per_minute: int = Field(ge=1, le=600)


class AdapterPolicySettings(ConfigModel):
    timeout_seconds: float = Field(ge=1, le=300)
    retries: int = Field(ge=0, le=10)
    initial_backoff_seconds: float = Field(ge=0, le=30)
    max_backoff_seconds: float = Field(ge=0, le=60)

    @model_validator(mode="after")
    def valid_backoff(self) -> AdapterPolicySettings:
        if self.max_backoff_seconds < self.initial_backoff_seconds:
            raise ValueError("max_backoff_seconds muss mindestens initial_backoff_seconds sein")
        return self


class LocalLlmPolicySettings(AdapterPolicySettings):
    """Local models answer much slower than hosted ones: up to 1800 seconds."""

    timeout_seconds: float = Field(ge=1, le=1800)


class RetrySettings(ConfigModel):
    provider_retry: int = Field(ge=0, le=10)
    json_repair: int = Field(ge=0, le=10)
    schema_repair: int = Field(ge=0, le=10)
    interpretation_attempts: int = Field(default=3, ge=1, le=20)
    interpretation_backoff_seconds: int = Field(default=60, ge=1, le=86400)
    revision_attempts: int = Field(default=3, ge=1, le=20)
    revision_backoff_seconds: int = Field(default=60, ge=1, le=86400)


class TimeoutSettings(ConfigModel):
    imap: AdapterPolicySettings
    telegram: AdapterPolicySettings
    openrouter: AdapterPolicySettings
    todoist: AdapterPolicySettings
    google_calendar: AdapterPolicySettings
    telegram_poll_seconds: int = Field(ge=1, le=50)
    # Only used in the experimental local mode (--ollama). Local models are
    # much slower than hosted ones, hence the generous default and limit.
    ollama: LocalLlmPolicySettings = Field(default_factory=lambda: LocalLlmPolicySettings(
        timeout_seconds=1800, retries=1, initial_backoff_seconds=2, max_backoff_seconds=10))


LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class LogTargetSettings(ConfigModel):
    enabled: bool = True
    level: str = "INFO"
    format: Literal["text", "jsonl"] = "jsonl"

    @field_validator("level")
    @classmethod
    def valid_level(cls, value: str) -> str:
        if value not in LOG_LEVELS:
            raise ValueError("erlaubt sind DEBUG, INFO, WARNING, ERROR und CRITICAL")
        return value


class ConsoleLoggingSettings(LogTargetSettings):
    format: Literal["text", "jsonl"] = "text"


class RotatingLogSettings(LogTargetSettings):
    filename: Path
    max_bytes: int = Field(gt=0)
    backup_count: int = Field(ge=0)
    retention_days: int = Field(gt=0, le=3650)

    @field_validator("filename", mode="before")
    @classmethod
    def valid_filename(cls, value: object) -> Path:
        if not isinstance(value, (str, Path)):
            raise ValueError("Dateiname muss eine Zeichenkette sein")
        path = _valid_path(Path(value))
        if path.anchor or PureWindowsPath(path).anchor:
            raise ValueError("Log-Dateiname muss relativ zum Logverzeichnis sein")
        return path


class LlmLoggingSettings(RotatingLogSettings):
    include_requests: bool = False
    include_responses: bool = False


class TelegramLoggingSettings(RotatingLogSettings):
    """Separate audit trail containing Telegram message contents."""

    filename: Path = Path("telegram/messages.jsonl")
    max_bytes: int = Field(default=10_000_000, gt=0)
    backup_count: int = Field(default=5, ge=0)
    retention_days: int = Field(default=30, gt=0, le=3650)


class LoggingSettings(ConfigModel):
    directory: Path
    console: ConsoleLoggingSettings
    file: RotatingLogSettings
    modules: dict[str, str] = Field(default_factory=dict)
    llm: LlmLoggingSettings
    telegram: TelegramLoggingSettings = Field(default_factory=TelegramLoggingSettings)

    @field_validator("modules")
    @classmethod
    def valid_modules(cls, value: dict[str, str]) -> dict[str, str]:
        if any(not module.strip() or level not in LOG_LEVELS for module, level in value.items()):
            raise ValueError("Modulnamen müssen nicht leer sein und Log-Level gültig sein")
        return value

    @field_validator("directory", mode="before")
    @classmethod
    def valid_directory(cls, value: object) -> Path:
        if not isinstance(value, (str, Path)): raise ValueError("Pfad muss eine Zeichenkette sein")
        return _valid_path(Path(value))


RetentionPeriod = Annotated[int, Field(ge=1, le=3650)] | Literal["disabled", "unlimited"]


class RetentionSettings(ConfigModel):
    """Fristen für Inhalte abgeschlossener Vorgänge.

    Eine Zahl bezeichnet volle Tage, ``disabled`` entfernt den jeweiligen Inhalt
    beim nächsten Lauf sofort und ``unlimited`` schaltet dessen Bereinigung aus.
    """

    full_mail_days: RetentionPeriod = 30
    debug_llm_days: RetentionPeriod = "disabled"
    # None preserves the earlier debug retention for existing installations.
    analysis_days: RetentionPeriod | None = None
    history_days: RetentionPeriod = 90
    # Activity reports (2.2): full texts are removed, dates and senders stay.
    activity_report_days: RetentionPeriod = 365


class LearningSettings(ConfigModel):
    """Concurrency controls for the interactive learning workflow."""

    parallel_llm_calls: int = Field(default=4, ge=1, le=100)


_WEB_HOST = re.compile(r"[a-z0-9]([a-z0-9.-]*[a-z0-9])?(:[0-9]{1,5})?")


class WebSettings(ConfigModel):
    """Optional web interface; disabled by default (Mailhelp then behaves like 1.0)."""

    enabled: bool = False
    # 127.0.0.1 on Windows; 0.0.0.0 only inside a container whose port is
    # published on 127.0.0.1 of the host.
    host: str = "127.0.0.1"
    port: int = Field(default=8765, ge=1, le=65535)
    # Exact Host headers accepted (protection against DNS rebinding).
    allowed_hosts: list[str] = Field(
        default_factory=lambda: ["127.0.0.1:8765", "localhost:8765"], min_length=1, max_length=20)
    session_days: int = Field(default=30, ge=1, le=365)
    # Reachable in the home network under the PC's private IP address (plain
    # HTTP); /web then sends that address. Requires host 0.0.0.0.
    lan_access: bool = False

    @model_validator(mode="after")
    def lan_needs_all_interfaces(self) -> WebSettings:
        if self.lan_access and ipaddress.ip_address(self.host).is_loopback:
            raise ValueError("lan_access benötigt host 0.0.0.0")
        return self

    @field_validator("host")
    @classmethod
    def valid_host(cls, value: str) -> str:
        try:
            ipaddress.ip_address(value)
        except ValueError as exc:
            raise ValueError("host muss eine IP-Adresse sein") from exc
        return value

    @field_validator("allowed_hosts")
    @classmethod
    def valid_allowed_hosts(cls, value: list[str]) -> list[str]:
        if any(not _WEB_HOST.fullmatch(item) for item in value):
            raise ValueError("allowed_hosts enthält nur kleingeschriebene Hostnamen mit optionalem Port")
        return value


class VisionSettings(ConfigModel):
    """Multimodal OCR for image attachments and scanned PDFs (1.4).

    Model and prompt are the ``vision_ocr`` step in ``prompts.yaml``; without
    that step no image is sent.  The limits bound cost and data transfer.
    """

    enabled: bool = True
    max_images_per_mail: int = Field(default=3, ge=1, le=10)
    max_image_bytes: int = Field(default=10_485_760, ge=10_240, le=50_000_000)
    max_edge_pixels: int = Field(default=1600, ge=512, le=4096)


class PushSettings(ConfigModel):
    enabled: bool = False
    subject: str = Field(default="mailto:admin@example.invalid", pattern=r"^mailto:[^\s@]+@[^\s@]+$")


class ActivityReportSettings(ConfigModel):
    """Activity reports (2.2): read-only scans of the mailbox for one topic."""

    enabled: bool = False
    # A report pauses when one of these limits is reached.
    max_mails: int = Field(default=2000, ge=1, le=20000)
    max_llm_calls: int = Field(default=3000, ge=1, le=50000)
    # Share of limits.llm_calls_per_minute a running report may use.
    max_share_of_llm_budget: float = Field(default=0.5, gt=0, le=1)
    # Excel allows 32,767 characters per cell; the marker "… gekürzt" must fit as well.
    max_fulltext_chars: int = Field(default=30000, ge=1000, le=32000)
    export_mails_without_events: bool = True


class DailyBriefingSettings(ConfigModel):
    enabled: bool = False
    time: str = Field(default="07:30", pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
    include_calendar: bool = True
    include_tasks: bool = True
    include_open: bool = True


class Settings(ConfigModel):
    timezone: str
    poll_interval_seconds: int = Field(ge=5, le=86400)
    test_mode: bool = False
    data_directory: Path
    imap: ImapSettings
    telegram: TelegramSettings
    targets: TargetSettings
    limits: LimitSettings
    retries: RetrySettings
    timeouts: TimeoutSettings
    logging: LoggingSettings
    retention: RetentionSettings = Field(default_factory=RetentionSettings)
    learning: LearningSettings = Field(default_factory=LearningSettings)
    web: WebSettings = Field(default_factory=WebSettings)
    metrics: MetricsSettings = Field(default_factory=MetricsSettings)
    vision: VisionSettings = Field(default_factory=VisionSettings)
    push: PushSettings = Field(default_factory=lambda: PushSettings())
    daily_briefing: DailyBriefingSettings = Field(default_factory=lambda: DailyBriefingSettings())
    smart_reply: bool = False
    # Name, role, signature and similar facts the user wants in reply drafts.
    # Trusted context for draft_reply only; tab and line breaks are the only control characters.
    personal_info: str = Field(default="", max_length=2000, pattern=r"^[^\x00-\x08\x0b-\x1f\x7f]*$")
    activity_report: ActivityReportSettings = Field(default_factory=lambda: ActivityReportSettings())

    @model_validator(mode="after")
    def standalone_needs_web(self):
        if not self.telegram.enabled and not self.web.enabled:
            raise ValueError("Ohne Telegram muss web.enabled aktiviert sein")
        return self

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try: ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc: raise ValueError("unbekannte IANA-Zeitzone") from exc
        return value

    @field_validator("data_directory", mode="before")
    @classmethod
    def valid_data_directory(cls, value: object) -> Path:
        if not isinstance(value, (str, Path)): raise ValueError("Pfad muss eine Zeichenkette sein")
        return _valid_path(Path(value))


def _valid_path(value: Path) -> Path:
    if not str(value).strip() or "\x00" in str(value) or ".." in value.parts:
        raise ValueError("Pfad muss sicher und nicht leer sein")
    return value


class Secrets(BaseModel):
    model_config = ConfigDict(extra="forbid")
    imap_username: str
    imap_password: SecretStr
    openrouter_api_key: SecretStr
    telegram_bot_token: SecretStr = SecretStr("")
    todoist_token: SecretStr
    todoist_client_id: SecretStr
    todoist_client_secret: SecretStr
    google_oauth_client_id: SecretStr
    google_oauth_client_secret: SecretStr
    google_oauth_refresh_token: SecretStr
    # Signs web sessions and CSRF tokens; required only with web.enabled.
    mailhelp_web_secret: SecretStr | None = None


class Topic(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(pattern=r"^[a-z0-9_-]+$")
    name: str
    enabled: bool
    description: str
    examples: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)


class TopicsConfig(ConfigModel):
    """Geschlossene Wurzel der Themendatei mit eindeutigen stabilen IDs."""

    topics: list[Topic] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_enabled_topics(self) -> TopicsConfig:
        identifiers = [topic.id for topic in self.topics]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Themen-IDs dürfen nicht doppelt vorkommen")
        if not any(topic.enabled for topic in self.topics):
            raise ValueError("mindestens ein Thema muss aktiviert sein")
        return self


class IrrelevantTopicsConfig(ConfigModel):
    """Closed topic file used to recognize categories excluded from learning."""

    topics: list[Topic] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_topic_ids(self) -> IrrelevantTopicsConfig:
        identifiers = [topic.id for topic in self.topics]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Themen-IDs dürfen nicht doppelt vorkommen")
        return self


class PromptStep(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    system_prompt: str = Field(min_length=1)
    model: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    routes: list[LlmRoute] | None = None
    # Provider routing for the default route; keeps model and parameters from
    # ``defaults``/``parameters`` instead of duplicating them in ``routes``.
    provider_preferences: OpenRouterProviderPreferences | None = None
    provider_retries: int = Field(default=1, ge=0, le=10)
    output_token_retry: OutputTokenRetry | None = None

    @model_validator(mode="after")
    def valid_routes(self) -> PromptStep:
        if self.routes is not None and self.provider_preferences is not None:
            raise ValueError("provider_preferences gilt nur ohne routes; dort je Route angeben")
        if self.routes is not None:
            if not self.routes:
                raise ValueError("routes darf nicht leer sein")
            identities = [(route.provider, route.model,
                           tuple(route.provider_preferences.order))
                          for route in self.routes]
            if len(identities) != len(set(identities)):
                raise ValueError("LLM-Routen dürfen nicht doppelt vorkommen")
        return self


OPENROUTER_PARAMETER_KEYS = {
    "temperature", "max_tokens", "top_p", "top_k", "frequency_penalty",
    "presence_penalty", "repetition_penalty", "seed", "stop", "logit_bias",
    "min_p", "top_a", "reasoning",
}
REASONING_EFFORTS = {"minimal", "low", "medium", "high"}


def checked_parameters(value: dict[str, Any], message: str) -> dict[str, Any]:
    """Reject unknown request keys and validate the closed ``reasoning`` block.

    ``reasoning`` limits hidden reasoning of capable models with exactly one of
    ``effort`` or ``max_tokens`` and an optional ``exclude``.  Disabling it via
    ``enabled`` is not offered: providers may reject such requests permanently.
    """
    unknown = set(value) - OPENROUTER_PARAMETER_KEYS
    if unknown:
        raise ValueError(f"{message}: {sorted(unknown)}")
    reasoning = value.get("reasoning")
    if reasoning is None:
        return value
    if not isinstance(reasoning, dict) or set(reasoning) - {"effort", "max_tokens", "exclude"}:
        raise ValueError("reasoning erlaubt ausschließlich effort, max_tokens und exclude")
    if ("effort" in reasoning) == ("max_tokens" in reasoning):
        raise ValueError("reasoning benötigt genau eines von effort oder max_tokens")
    if "effort" in reasoning and reasoning["effort"] not in REASONING_EFFORTS:
        raise ValueError(f"reasoning.effort muss einer von {sorted(REASONING_EFFORTS)} sein")
    tokens = reasoning.get("max_tokens")
    if "max_tokens" in reasoning and (type(tokens) is not int or not 1 <= tokens <= 32000):
        raise ValueError("reasoning.max_tokens muss eine Ganzzahl von 1 bis 32000 sein")
    if "exclude" in reasoning and type(reasoning["exclude"]) is not bool:
        raise ValueError("reasoning.exclude muss ein Wahrheitswert sein")
    return value


class OpenRouterProviderPreferences(ConfigModel):
    """The closed subset of OpenRouter provider routing that Mailhelp accepts."""

    order: list[str] = Field(default_factory=list)
    allow_fallbacks: bool = True
    require_parameters: bool = False
    data_collection: Literal["allow", "deny"] | None = None
    sort: Literal["price", "throughput", "latency"] | None = None
    ignore: list[str] = Field(default_factory=list)

    @field_validator("order", "ignore")
    @classmethod
    def provider_names(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value) or len(value) != len(set(value)):
            raise ValueError("Providernamen müssen nicht leer und eindeutig sein")
        return value


class LlmRoute(ConfigModel):
    provider: Literal["openrouter"]
    model: str = Field(min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)
    provider_preferences: OpenRouterProviderPreferences = Field(
        default_factory=OpenRouterProviderPreferences
    )
    supports_json_schema: bool = True

    @field_validator("model")
    @classmethod
    def configured_model(cls, value: str) -> str:
        if value.startswith("<"):
            raise ValueError("Modell ist nicht eingerichtet")
        return value

    @field_validator("parameters")
    @classmethod
    def safe_parameters(cls, value: dict[str, Any]) -> dict[str, Any]:
        return checked_parameters(value, "Unbekannte oder reservierte Request-Schlüssel")


class OutputTokenRetry(ConfigModel):
    """A deliberately smaller, stage-specific request after truncated output."""
    system_prompt: str = Field(min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)
    # Only proposal revisions need to select writable fields.  Other stages can
    # use the generic prompt/parameter fallback without inventing revision data.
    change_fields: list[str] | None = Field(default=None, min_length=1)

    @field_validator("parameters")
    @classmethod
    def safe_parameters(cls, value: dict[str, Any]) -> dict[str, Any]:
        return checked_parameters(value, "Unbekannte Retry-Parameter")

# Context window of the experimental local mode. It matches the instance that
# is preloaded on the Ollama server; any other value makes Ollama reload the
# model, which takes several minutes for large models.
LOCAL_NUM_CTX = 65536


class OllamaPromptSettings(ConfigModel):
    """Model of the experimental local mode; replaces every OpenRouter route."""

    model: str = Field(min_length=1, max_length=200, pattern=r"^[^<>\s]+$")
    num_ctx: int = Field(default=LOCAL_NUM_CTX, ge=2048, le=262144)
    num_thread: int | None = Field(default=None, ge=1, le=1024)
    think: bool | None = None


# Steps a prompts.yaml from an earlier release may lack; the feature is then off.
OPTIONAL_PROMPT_STEPS = frozenset({"vision_ocr", "draft_reply", "activity_relevance", "activity_events"})


class PromptConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    defaults: dict[str, Any]
    prompts: dict[str, PromptStep]
    ollama: OllamaPromptSettings | None = None
    suspicious_link_hosts: list[Annotated[str, Field(min_length=1, max_length=253)]] = Field(default_factory=list)
    suspicious_link_phrases: list[Annotated[str, Field(min_length=1, max_length=250)]] = Field(default_factory=list)

    @model_validator(mode="after")
    def required_steps(self) -> PromptConfig:
        required = {"relevance", "summary", "action_router", "task_extraction",
                    "event_extraction", "mail_question_resolution", "telegram_answer_interpretation",
                    "telegram_answer_clarification", "proposal_revision", "learning_classification",
                    "learning_abstraction", "calendar_duplicate"}
        if not required <= set(self.prompts) <= required | OPTIONAL_PROMPT_STEPS:
            raise ValueError("prompts enthält nicht genau die erforderlichen Schritte")
        default_model = self.defaults.get("model")
        for name, step in self.prompts.items():
            if step.routes is None and not step.model and not default_model:
                raise ValueError(f"prompts.{name} benötigt ein Primärmodell")
        return self

    def resolved(self, step: str) -> tuple[str, dict[str, Any], str]:
        item = self.prompts[step]
        model = item.model or self.defaults.get("model")
        if not isinstance(model, str) or not model or model.startswith("<"):
            raise ValueError(f"prompts.{step}.model ist nicht eingerichtet")
        parameters = _deep_merge(self.defaults.get("parameters", {}), item.parameters)
        forbidden = {"model", "messages", "response_format"} & parameters.keys()
        if forbidden:
            raise ValueError(f"Reservierte OpenRouter-Parameter: {sorted(forbidden)}")
        return model, parameters, item.system_prompt

    def resolved_routes(self, step: str) -> tuple[list[LlmRoute], str, int]:
        """Return an ordered, validated strategy (primary route first)."""
        item = self.prompts[step]
        if item.routes is not None:
            return item.routes, item.system_prompt, item.provider_retries
        model, parameters, prompt = self.resolved(step)
        checked_parameters(parameters, "Unbekannte oder reservierte Request-Schlüssel")
        return [LlmRoute(provider="openrouter", model=model, parameters=parameters,
                         provider_preferences=(item.provider_preferences
                                               or OpenRouterProviderPreferences()))
                ], prompt, item.provider_retries


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        result[key] = _deep_merge(result[key], value) if isinstance(value, dict) and isinstance(result.get(key), dict) else value
    return result


def read_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        value = yaml.safe_load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: Wurzel muss ein Objekt sein")
    return value


def _dotenv(path: Path) -> dict[str, str]:
    """Read the deliberately small, non-expanding KEY=VALUE .env format."""
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for number, original in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = original.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"{path}: ungültige Zeile {number}")
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise ValueError(f"{path}: ungültiger Schlüssel in Zeile {number}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        result[key] = value
    return result


DEFAULT_TOPIC_FILES = ("topics.yaml", "irrelevant_topics.yaml")


def _create_missing_topic_files(directory: Path) -> None:
    """Restore distributed topic files without replacing user configuration."""
    defaults = files("mailhelp").joinpath("defaults")
    for name in DEFAULT_TOPIC_FILES:
        path = directory / name
        if path.exists():
            continue
        content = defaults.joinpath(name).read_text(encoding="utf-8")
        try:
            with path.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
        except FileExistsError:
            # A concurrently starting process already restored the file.
            pass


def load_all(directory: Path, environ: dict[str, str] | None = None) -> tuple[Settings, Secrets, list[Topic], list[Topic], PromptConfig, str]:
    env = {**_dotenv(directory / ".env"), **(os.environ if environ is None else environ)}
    settings = validated_file(directory / "config.yaml", Settings, read_yaml(directory / "config.yaml"))
    prompts = validated_file(directory / "prompts.yaml", PromptConfig, read_yaml(directory / "prompts.yaml"))
    _create_missing_topic_files(directory)
    topics = validated_file(directory / "topics.yaml", TopicsConfig, read_yaml(directory / "topics.yaml")).topics
    irrelevant_topics = validated_file(
        directory / "irrelevant_topics.yaml", IrrelevantTopicsConfig,
        read_yaml(directory / "irrelevant_topics.yaml"),
    ).topics
    names = ["IMAP_USERNAME", "IMAP_PASSWORD", "OPENROUTER_API_KEY", "TELEGRAM_BOT_TOKEN", "TODOIST_TOKEN",
             "TODOIST_CLIENT_ID", "TODOIST_CLIENT_SECRET", "GOOGLE_OAUTH_CLIENT_ID",
             "GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_OAUTH_REFRESH_TOKEN"]
    missing = [name for name in names if not env.get(name)]
    if not settings.telegram.enabled:
        names.remove("TELEGRAM_BOT_TOKEN")
        missing = [name for name in missing if name != "TELEGRAM_BOT_TOKEN"]
    if missing:
        raise ValueError("Fehlende Geheimnisse: " + ", ".join(missing))
    values = {name.lower(): env[name] for name in names}
    if settings.web.enabled:
        web_secret = env.get("MAILHELP_WEB_SECRET", "")
        if not web_secret:
            raise ValueError("Fehlende Geheimnisse: MAILHELP_WEB_SECRET (benötigt für web.enabled)")
        if len(web_secret) < 32:
            raise ValueError("MAILHELP_WEB_SECRET muss mindestens 32 Zeichen lang sein")
        values["mailhelp_web_secret"] = web_secret
    secrets = Secrets.model_validate(values)
    # Only analysis-relevant settings: operational changes (web, polling, logging,
    # retention, timeouts, metrics) must not hold back mails that are running.
    from .fingerprints import config_fingerprint
    fingerprint = config_fingerprint(settings, prompts, topics)
    return settings, secrets, topics, irrelevant_topics, prompts, fingerprint


def validated_file(path: Path, model: type[BaseModel], value: Any, prefix: str = "") -> Any:
    try: return model.model_validate(value)
    except ValidationError as exc:
        locations = []
        for error in exc.errors(include_input=False):
            location = ".".join(str(part) for part in error["loc"]) or "<root>"
            locations.append(f"{prefix}.{location}" if prefix else location)
        raise ValueError(f"{path}: ungültige Schlüsselpfade: {', '.join(locations)}") from exc
