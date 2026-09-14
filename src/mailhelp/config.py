"""Laden und Validieren von Konfiguration und Geheimnissen."""
from __future__ import annotations
import hashlib, json, os
from pathlib import Path
from typing import Any
import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timezone: str
    poll_interval_seconds: int = Field(ge=5)
    test_mode: bool = False
    data_directory: Path
    imap: dict[str, Any]
    telegram: dict[str, int]
    targets: dict[str, str]
    limits: dict[str, int]
    retries: dict[str, int]
    logging: dict[str, Any]


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
    examples: list[str] = []
    exclusions: list[str] = []


class PromptStep(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    system_prompt: str = Field(min_length=1)
    model: str | None = None
    parameters: dict[str, Any] = {}


class PromptConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    defaults: dict[str, Any]
    prompts: dict[str, PromptStep]

    @model_validator(mode="after")
    def required_steps(self) -> "PromptConfig":
        if set(self.prompts) != {"relevance", "summary", "actions"}:
            raise ValueError("prompts muss genau relevance, summary und actions enthalten")
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


def load_all(directory: Path, environ: dict[str, str] | None = None) -> tuple[Settings, Secrets, list[Topic], PromptConfig, str]:
    env = os.environ if environ is None else environ
    settings = Settings.model_validate(_yaml(directory / "config.yaml"))
    prompts = PromptConfig.model_validate(_yaml(directory / "prompts.yaml"))
    topics = [Topic.model_validate(x) for x in _yaml(directory / "topics.yaml").get("topics", [])]
    if not any(topic.enabled for topic in topics):
        raise ValueError("topics.yaml: mindestens ein Thema muss aktiviert sein")
    names = ["IMAP_USERNAME", "IMAP_PASSWORD", "OPENROUTER_API_KEY", "TELEGRAM_BOT_TOKEN", "TODOIST_TOKEN", "GOOGLE_ACCESS_TOKEN"]
    missing = [name for name in names if not env.get(name)]
    if missing:
        raise ValueError("Fehlende Geheimnisse: " + ", ".join(missing))
    secrets = Secrets.model_validate({name.lower(): env[name] for name in names})
    fingerprint = hashlib.sha256(json.dumps([settings.model_dump(mode="json"), prompts.model_dump(), [x.model_dump() for x in topics]], sort_keys=True).encode()).hexdigest()
    return settings, secrets, topics, prompts, fingerprint
