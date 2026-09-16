"""Laden und Validieren von Konfiguration und Geheimnissen."""
from __future__ import annotations
import hashlib, json, os, re
from pathlib import Path
from typing import Any, Literal
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
    google_calendar: str = Field(min_length=1, max_length=500)


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
    validation: int = Field(ge=0, le=10)


class TimeoutSettings(ConfigModel):
    imap: AdapterPolicySettings
    telegram: AdapterPolicySettings
    openrouter: AdapterPolicySettings
    todoist: AdapterPolicySettings
    google_calendar: AdapterPolicySettings
    telegram_poll_seconds: int = Field(ge=1, le=50)


class LoggingSettings(ConfigModel):
    directory: Path
    level: str
    include_llm_requests: bool = False
    include_llm_responses: bool = False
    module_levels: dict[str, str] = Field(default_factory=dict)

    @field_validator("level")
    @classmethod
    def valid_level(cls, value: str) -> str:
        if value not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("erlaubt sind DEBUG, INFO, WARNING, ERROR und CRITICAL")
        return value

    @field_validator("module_levels")
    @classmethod
    def valid_module_levels(cls, value: dict[str, str]) -> dict[str, str]:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if any(not module.strip() or level not in allowed for module, level in value.items()):
            raise ValueError("Modulnamen müssen nicht leer sein und Log-Level gültig sein")
        return value

    @field_validator("directory", mode="before")
    @classmethod
    def valid_directory(cls, value: object) -> Path:
        if not isinstance(value, (str, Path)): raise ValueError("Pfad muss eine Zeichenkette sein")
        return _valid_path(Path(value))


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
    google_access_token: SecretStr


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
    names = ["IMAP_USERNAME", "IMAP_PASSWORD", "OPENROUTER_API_KEY", "TELEGRAM_BOT_TOKEN", "TODOIST_TOKEN", "GOOGLE_ACCESS_TOKEN"]
    missing = [name for name in names if not env.get(name)]
    if missing:
        raise ValueError("Fehlende Geheimnisse: " + ", ".join(missing))
    secrets = Secrets.model_validate({name.lower(): env[name] for name in names})
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
