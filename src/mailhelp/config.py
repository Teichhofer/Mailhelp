"""Laden und Validieren von Konfiguration und Geheimnissen."""
from __future__ import annotations
import hashlib, json, os, re
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Any, Literal
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator, model_validator


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
    def primary_is_configured(self) -> "ImapSettings":
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
    user_id: int = Field(gt=0)
    chat_id: int


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
    def valid_backoff(self) -> "AdapterPolicySettings":
        if self.max_backoff_seconds < self.initial_backoff_seconds:
            raise ValueError("max_backoff_seconds muss mindestens initial_backoff_seconds sein")
        return self


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
        if path.is_absolute():
            raise ValueError("Log-Dateiname muss relativ zum Logverzeichnis sein")
        return path


class LlmLoggingSettings(RotatingLogSettings):
    include_requests: bool = False
    include_responses: bool = False


class LoggingSettings(ConfigModel):
    directory: Path
    console: ConsoleLoggingSettings
    file: RotatingLogSettings
    modules: dict[str, str] = Field(default_factory=dict)
    llm: LlmLoggingSettings

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


class LearningSettings(ConfigModel):
    """Concurrency controls for the interactive learning workflow."""

    parallel_llm_calls: int = Field(default=4, ge=1, le=100)


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
    telegram_bot_token: SecretStr
    todoist_token: SecretStr
    todoist_client_id: SecretStr
    todoist_client_secret: SecretStr
    google_oauth_client_id: SecretStr
    google_oauth_client_secret: SecretStr
    google_oauth_refresh_token: SecretStr


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
    def unique_enabled_topics(self) -> "TopicsConfig":
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
    def unique_topic_ids(self) -> "IrrelevantTopicsConfig":
        identifiers = [topic.id for topic in self.topics]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Themen-IDs dürfen nicht doppelt vorkommen")
        return self


class PromptStep(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    system_prompt: str = Field(min_length=1)
    model: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    routes: list["LlmRoute"] | None = None
    provider_retries: int = Field(default=1, ge=0, le=10)
    output_token_retry: "OutputTokenRetry | None" = None

    @model_validator(mode="after")
    def valid_routes(self) -> "PromptStep":
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
    "min_p", "top_a",
}


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
        unknown = set(value) - OPENROUTER_PARAMETER_KEYS
        if unknown:
            raise ValueError(f"Unbekannte oder reservierte Request-Schlüssel: {sorted(unknown)}")
        return value


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
        unknown = set(value) - OPENROUTER_PARAMETER_KEYS
        if unknown:
            raise ValueError(f"Unbekannte Retry-Parameter: {sorted(unknown)}")
        return value

class PromptConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    defaults: dict[str, Any]
    prompts: dict[str, PromptStep]

    @model_validator(mode="after")
    def required_steps(self) -> "PromptConfig":
        required = {"relevance", "summary", "action_router", "task_extraction",
                    "event_extraction", "telegram_answer_interpretation",
                    "telegram_answer_clarification", "proposal_revision", "learning_classification",
                    "learning_abstraction"}
        if set(self.prompts) != required:
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
        unknown = set(parameters) - OPENROUTER_PARAMETER_KEYS
        if unknown:
            raise ValueError(f"Unbekannte oder reservierte Request-Schlüssel: {sorted(unknown)}")
        return [LlmRoute(provider="openrouter", model=model,
                         parameters=parameters)], prompt, item.provider_retries


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        result[key] = _deep_merge(result[key], value) if isinstance(value, dict) and isinstance(result.get(key), dict) else value
    return result


def _yaml(path: Path) -> Any:
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
    settings = _validated_file(directory / "config.yaml", Settings, _yaml(directory / "config.yaml"))
    prompts = _validated_file(directory / "prompts.yaml", PromptConfig, _yaml(directory / "prompts.yaml"))
    _create_missing_topic_files(directory)
    topics = _validated_file(directory / "topics.yaml", TopicsConfig, _yaml(directory / "topics.yaml")).topics
    irrelevant_topics = _validated_file(
        directory / "irrelevant_topics.yaml", IrrelevantTopicsConfig,
        _yaml(directory / "irrelevant_topics.yaml"),
    ).topics
    names = ["IMAP_USERNAME", "IMAP_PASSWORD", "OPENROUTER_API_KEY", "TELEGRAM_BOT_TOKEN", "TODOIST_TOKEN",
             "TODOIST_CLIENT_ID", "TODOIST_CLIENT_SECRET", "GOOGLE_OAUTH_CLIENT_ID",
             "GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_OAUTH_REFRESH_TOKEN"]
    missing = [name for name in names if not env.get(name)]
    if missing:
        raise ValueError("Fehlende Geheimnisse: " + ", ".join(missing))
    values = {name.lower(): env[name] for name in names}
    secrets = Secrets.model_validate(values)
    fingerprint = hashlib.sha256(json.dumps([settings.model_dump(mode="json"), prompts.model_dump(), [x.model_dump() for x in topics]], sort_keys=True).encode()).hexdigest()
    return settings, secrets, topics, irrelevant_topics, prompts, fingerprint


def _validated_file(path: Path, model: type[BaseModel], value: Any, prefix: str = "") -> Any:
    try: return model.model_validate(value)
    except ValidationError as exc:
        locations = []
        for error in exc.errors(include_input=False):
            location = ".".join(str(part) for part in error["loc"]) or "<root>"
            locations.append(f"{prefix}.{location}" if prefix else location)
        raise ValueError(f"{path}: ungültige Schlüsselpfade: {', '.join(locations)}") from exc
