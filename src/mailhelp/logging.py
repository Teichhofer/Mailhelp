"""Strukturierte, getrennte und geheimnisbereinigte JSONL-Protokolle."""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
SENSITIVE_KEYS = ("token", "password", "authorization", "api_key", "apikey", "secret", "cookie")
SENSITIVE = re.compile(
    r"(?i)(bearer\s+)[^\s,;}]+|((?:token|password|api[_-]?key|secret|authorization|cookie)[\"'=:\s]+)[^\s,;}\"]+"
)


class EventLogger(Protocol):
    def event(self, level: str, module: str, event: str, **context: Any) -> None: ...
    def llm_event(self, event: str, request: Any = None, response: Any = None, **context: Any) -> None: ...


class NullLogger:
    """Explizite Logging-Schnittstelle für isoliert verwendete Adapter."""

    def event(self, level: str, module: str, event: str, **context: Any) -> None:
        _validate_level(level)

    def llm_event(self, event: str, request: Any = None, response: Any = None, **context: Any) -> None:
        return None


def _validate_level(level: str) -> str:
    if level not in LEVELS:
        raise ValueError(f"Ungültiges Log-Level {level!r}; erlaubt sind {', '.join(LEVELS)}")
    return level


def redact(value: Any, secrets: tuple[str, ...] | list[str] | set[str] = ()) -> Any:
    """Bereinige beliebig verschachtelte, nicht vertrauenswürdige Logdaten."""
    known = tuple(secret for secret in secrets if isinstance(secret, str) and secret)

    def clean(item: Any) -> Any:
        if isinstance(item, BaseException):
            return clean(f"{type(item).__name__}: {item}")
        if isinstance(item, Mapping):
            return {
                str(key): "***" if _sensitive_key(str(key)) else clean(child)
                for key, child in item.items()
            }
        if isinstance(item, (list, tuple, set, frozenset)):
            return [clean(child) for child in item]
        if isinstance(item, bytes):
            return clean(item.decode("utf-8", errors="replace"))
        if isinstance(item, str):
            result = SENSITIVE.sub(lambda match: (match.group(1) or match.group(2)) + "***", item)
            for secret in known:
                result = result.replace(secret, "***")
            return result
        if item is None or isinstance(item, (bool, int, float)):
            return item
        return clean(str(item))

    return clean(value)


def _sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    if normalized in SENSITIVE_KEYS or normalized.endswith(("_password", "_secret", "_api_key", "_apikey", "_authorization", "_cookie")):
        return True
    return normalized.endswith("_token") and normalized not in {"input_token", "output_token"}


class JsonlLogger:
    def __init__(
        self,
        directory: Path,
        include_llm_requests: bool = False,
        include_llm_responses: bool = False,
        level: str = "DEBUG",
        module_levels: Mapping[str, str] | None = None,
        secrets: tuple[str, ...] | list[str] | set[str] = (),
    ):
        self.app = directory / "application.jsonl"
        self.llm = directory / "llm" / "requests.jsonl"
        self.include_requests, self.include_responses = include_llm_requests, include_llm_responses
        self.level = _validate_level(level)
        self.module_levels = {str(module): _validate_level(item) for module, item in (module_levels or {}).items()}
        self.secrets = tuple(secret for secret in secrets if secret)

    def enabled(self, level: str, module: str) -> bool:
        return LEVELS[_validate_level(level)] >= LEVELS[self.module_levels.get(module, self.level)]

    def _write(self, path: Path, level: str, module: str, event: str, **context: Any) -> None:
        if not self.enabled(level, module):
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        record = redact({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "module": module,
            "event": event,
            **context,
        }, self.secrets)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    def event(self, level: str, module: str, event: str, **context: Any) -> None:
        self._write(self.app, level, module, event, **context)

    def llm_event(self, event: str, request: Any = None, response: Any = None, **context: Any) -> None:
        if request is not None and self.include_requests:
            context["request"] = request
        if response is not None and self.include_responses:
            context["response"] = response
        self._write(self.llm, context.pop("level", "INFO"), "openrouter", event, **context)
