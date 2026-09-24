"""Strukturierte, getrennte und geheimnisbereinigte JSONL-Protokolle."""
from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol, TextIO

LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
SENSITIVE_KEYS = ("token", "password", "authorization", "api_key", "apikey", "secret", "cookie")
SENSITIVE = re.compile(
    r"(?i)(bearer\s+)[^\s,;}]+|((?:token|password|api[_-]?key|secret|authorization|cookie)[\"'=:\s]+)[^\s,;}\"]+"
)


class EventLogger(Protocol):
    def event(self, level: str, module: str, event: str, **context: Any) -> None: ...
    def llm_event(self, event: str, request: Any = None, response: Any = None, **context: Any) -> None: ...
    def telegram_event(self, direction: str, **context: Any) -> None: ...


class NullLogger:
    """Explizite Logging-Schnittstelle für isoliert verwendete Adapter."""

    def event(self, level: str, module: str, event: str, **context: Any) -> None:
        _validate_level(level)

    def llm_event(self, event: str, request: Any = None, response: Any = None, **context: Any) -> None:
        return None

    def telegram_event(self, direction: str, **context: Any) -> None:
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
        *,
        file_enabled: bool = True,
        file_name: Path | str = "application.jsonl",
        file_format: str = "jsonl",
        file_max_bytes: int = 10_000_000,
        file_backup_count: int = 5,
        file_retention_days: int = 30,
        console_enabled: bool = False,
        console_level: str = "INFO",
        console_format: str = "text",
        console: TextIO | None = None,
        llm_enabled: bool = True,
        llm_level: str | None = None,
        llm_name: Path | str = "llm/requests.jsonl",
        llm_format: str = "jsonl",
        llm_max_bytes: int = 10_000_000,
        llm_backup_count: int = 5,
        llm_retention_days: int = 30,
        telegram_enabled: bool = True,
        telegram_level: str = "INFO",
        telegram_name: Path | str = "telegram/messages.jsonl",
        telegram_format: str = "jsonl",
        telegram_max_bytes: int = 10_000_000,
        telegram_backup_count: int = 5,
        telegram_retention_days: int = 30,
    ):
        self.app = directory / file_name
        self.llm = directory / llm_name
        self.telegram = directory / telegram_name
        self.include_requests, self.include_responses = include_llm_requests, include_llm_responses
        self.level = _validate_level(level)
        self.module_levels = {str(module): _validate_level(item) for module, item in (module_levels or {}).items()}
        self.secrets = tuple(secret for secret in secrets if secret)
        self.file_enabled, self.llm_enabled = file_enabled, llm_enabled
        self.telegram_enabled = telegram_enabled
        self.console_enabled = console_enabled
        self.console_level = _validate_level(console_level)
        self.llm_level = _validate_level(llm_level or level)
        self.telegram_level = _validate_level(telegram_level)
        self.console_format = _validate_format(console_format)
        self.file_format = _validate_format(file_format)
        self.llm_format = _validate_format(llm_format)
        self.telegram_format = _validate_format(telegram_format)
        self.console = console or sys.stderr
        self.file_policy = (file_max_bytes, file_backup_count, file_retention_days)
        self.llm_policy = (llm_max_bytes, llm_backup_count, llm_retention_days)
        self.telegram_policy = (telegram_max_bytes, telegram_backup_count, telegram_retention_days)
        for size, backups, days in (self.file_policy, self.llm_policy, self.telegram_policy):
            if size <= 0 or backups < 0 or days <= 0:
                raise ValueError("Loggröße und Aufbewahrung müssen positiv, Backup-Anzahl darf null sein")
        self._prune(self.app, file_retention_days)
        self._prune(self.llm, llm_retention_days)
        self._prune(self.telegram, telegram_retention_days)

    def enabled(self, level: str, module: str) -> bool:
        configured = self.level
        parts = module.split(".")
        for length in range(len(parts), 0, -1):
            inherited = self.module_levels.get(".".join(parts[:length]))
            if inherited is not None:
                configured = inherited
                break
        return LEVELS[_validate_level(level)] >= LEVELS[configured]

    def _record(self, level: str, module: str, event: str, context: Mapping[str, Any]) -> dict[str, Any]:
        return redact({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "module": module,
            "event": event,
            **context,
        }, self.secrets)

    @staticmethod
    def _render(record: Mapping[str, Any], format_name: str) -> str:
        if format_name == "jsonl":
            return json.dumps(record, ensure_ascii=False) + "\n"
        context = {key: value for key, value in record.items() if key not in {"timestamp", "level", "module", "event"}}
        suffix = f" {json.dumps(context, ensure_ascii=False)}" if context else ""
        return f"{record['timestamp']} {record['level']} {record['module']} {record['event']}{suffix}\n"

    @staticmethod
    def _prune(path: Path, retention_days: int) -> None:
        cutoff = datetime.now(timezone.utc).timestamp() - timedelta(days=retention_days).total_seconds()
        parent = path.parent
        if not parent.exists():
            return
        pattern = re.compile(re.escape(path.name) + r"(?:\.\d+)?$")
        for candidate in parent.iterdir():
            if pattern.fullmatch(candidate.name) and candidate.is_file() and not candidate.is_symlink() and candidate.stat().st_mtime < cutoff:
                candidate.unlink()

    @staticmethod
    def _rotate(path: Path, incoming_bytes: int, max_bytes: int, backup_count: int) -> None:
        if not path.exists() or path.stat().st_size + incoming_bytes <= max_bytes:
            return
        if backup_count == 0:
            path.unlink()
            return
        oldest = path.with_name(f"{path.name}.{backup_count}")
        if oldest.exists():
            oldest.unlink()
        for number in range(backup_count - 1, 0, -1):
            source = path.with_name(f"{path.name}.{number}")
            if source.exists():
                os.replace(source, path.with_name(f"{path.name}.{number + 1}"))
        os.replace(path, path.with_name(f"{path.name}.1"))

    def _write_file(self, path: Path, record: Mapping[str, Any], format_name: str, policy: tuple[int, int, int]) -> None:
        rendered = self._render(record, format_name)
        encoded_size = len(rendered.encode("utf-8"))
        path.parent.mkdir(parents=True, exist_ok=True)
        self._prune(path, policy[2])
        self._rotate(path, encoded_size, policy[0], policy[1])
        with path.open("a", encoding="utf-8") as stream:
            stream.write(rendered)

    def event(self, level: str, module: str, event: str, **context: Any) -> None:
        level = _validate_level(level)
        write_file = self.file_enabled and self.enabled(level, module)
        write_console = self.console_enabled and LEVELS[level] >= LEVELS[self.console_level]
        if not write_file and not write_console:
            return
        record = self._record(level, module, event, context)
        if write_file:
            self._write_file(self.app, record, self.file_format, self.file_policy)
        if write_console:
            self.console.write(self._render(record, self.console_format))
            self.console.flush()

    def llm_event(self, event: str, request: Any = None, response: Any = None, **context: Any) -> None:
        level = _validate_level(context.pop("level", "INFO"))
        if not self.llm_enabled or LEVELS[level] < LEVELS[self.llm_level]:
            return
        # Callers may only place full prompt/model content in the two explicit
        # channels.  This also protects against accidentally smuggling it through
        # generic context while both opt-in switches are disabled.
        if not self.include_requests:
            for key in ("request", "prompt", "messages", "system", "payload"):
                context.pop(key, None)
        if not self.include_responses:
            for key in ("response", "content", "completion"):
                context.pop(key, None)
        if request is not None and self.include_requests:
            context["request"] = request
        if response is not None and self.include_responses:
            context["response"] = response
        # Deliberately bypass application module filters and console output.
        record = self._record(level, "openrouter", event, context)
        self._write_file(self.llm, record, self.llm_format, self.llm_policy)

    def telegram_event(self, direction: str, **context: Any) -> None:
        """Write one successfully sent or validated received Telegram message."""
        if direction not in {"sent", "received"}:
            raise ValueError("Telegram-Richtung muss sent oder received sein")
        if not self.telegram_enabled:
            return
        record = self._record(self.telegram_level, "telegram", "message", {
            "direction": direction, **context,
        })
        self._write_file(
            self.telegram, record, self.telegram_format, self.telegram_policy,
        )


def _validate_format(value: str) -> str:
    if value not in {"text", "jsonl"}:
        raise ValueError("Logformat muss text oder jsonl sein")
    return value
