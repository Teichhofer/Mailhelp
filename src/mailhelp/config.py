"""Laden und Validieren von Konfiguration und Geheimnissen."""
from __future__ import annotations
import hashlib, json, os, re
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
    connection_mode: Literal["ssl", "starttls", "plain"] = "ssl"
    historical_start: datetime | None = None
    batch_size: int = Field(default=25, ge=1, le=1000)

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


class TelegramSettings(ConfigModel):
    user_id: int = Field(gt=0)
    chat_id: int


class TargetSettings(ConfigModel):
    todoist_project: str = Field(min_length=1, max_length=500)
    google_calendar: str | None = Field(default=None, min_length=1, max_length=500)


class LimitSettings(ConfigModel):
    max_mail_bytes: int = Field(ge=1024, le=100_000_000)
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


class TimeoutSettings(ConfigModel):
    imap: AdapterPolicySettings
    telegram: AdapterPolicySettings
    openrouter: AdapterPolicySettings
    todoist: AdapterPolicySettings
    google_calendar: AdapterPolicySettings | None = None
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
    # Accepted temporarily so existing .env files remain valid; calendar files
    # do not read or require these legacy Google credentials.
    google_oauth_client_id: SecretStr | None = None
    google_oauth_client_secret: SecretStr | None = None
    google_oauth_refresh_token: SecretStr | None = None


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


class PromptStep(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    system_prompt: str = Field(min_length=1)
    model: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class PromptConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    defaults: dict[str, Any]
    prompts: dict[str, PromptStep]

    @model_validator(mode="after")
    def required_steps(self) -> "PromptConfig":
        if set(self.prompts) != {"relevance", "summary", "actions", "proposal_revision"}:
            raise ValueError("prompts muss genau relevance, summary, actions und proposal_revision enthalten")
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


def load_all(directory: Path, environ: dict[str, str] | None = None) -> tuple[Settings, Secrets, list[Topic], PromptConfig, str]:
    env = {**_dotenv(directory / ".env"), **(os.environ if environ is None else environ)}
    settings = _validated_file(directory / "config.yaml", Settings, _yaml(directory / "config.yaml"))
    prompts = _validated_file(directory / "prompts.yaml", PromptConfig, _yaml(directory / "prompts.yaml"))
    topics = _validated_file(directory / "topics.yaml", TopicsConfig, _yaml(directory / "topics.yaml")).topics
    names = ["IMAP_USERNAME", "IMAP_PASSWORD", "OPENROUTER_API_KEY", "TELEGRAM_BOT_TOKEN", "TODOIST_TOKEN",
             "TODOIST_CLIENT_ID", "TODOIST_CLIENT_SECRET"]
    missing = [name for name in names if not env.get(name)]
    if missing:
        raise ValueError("Fehlende Geheimnisse: " + ", ".join(missing))
    optional = ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_OAUTH_REFRESH_TOKEN")
    values = {name.lower(): env[name] for name in names}
    values.update({name.lower(): env[name] for name in optional if env.get(name)})
    secrets = Secrets.model_validate(values)
    fingerprint = hashlib.sha256(json.dumps([settings.model_dump(mode="json"), prompts.model_dump(), [x.model_dump() for x in topics]], sort_keys=True).encode()).hexdigest()
    return settings, secrets, topics, prompts, fingerprint


def _validated_file(path: Path, model: type[BaseModel], value: Any, prefix: str = "") -> Any:
    try: return model.model_validate(value)
    except ValidationError as exc:
        locations = []
        for error in exc.errors(include_input=False):
            location = ".".join(str(part) for part in error["loc"]) or "<root>"
            locations.append(f"{prefix}.{location}" if prefix else location)
        raise ValueError(f"{path}: ungültige Schlüsselpfade: {', '.join(locations)}") from exc
