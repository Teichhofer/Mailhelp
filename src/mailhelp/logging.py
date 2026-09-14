"""Strukturierte, getrennte und geheimnisbereinigte JSONL-Protokolle."""
from __future__ import annotations
import json, re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SENSITIVE = re.compile(r"(?i)(bearer\s+)[^\s]+|((?:token|password|api[_-]?key)[\"'=:\s]+)[^\s,}\"]+")


def redact(value: Any) -> Any:
    if isinstance(value, dict): return {key: "***" if any(x in key.lower() for x in ("token", "password", "authorization", "api_key")) else redact(item) for key, item in value.items()}
    if isinstance(value, list): return [redact(x) for x in value]
    if isinstance(value, str): return SENSITIVE.sub(lambda m: (m.group(1) or m.group(2)) + "***", value)
    return value


class JsonlLogger:
    def __init__(self, directory: Path, include_llm_requests: bool = False, include_llm_responses: bool = False):
        self.app = directory / "application.jsonl"; self.llm = directory / "llm" / "requests.jsonl"
        self.include_requests, self.include_responses = include_llm_requests, include_llm_responses

    def _write(self, path: Path, level: str, module: str, event: str, **context: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {"timestamp": datetime.now(timezone.utc).isoformat(), "level": level, "module": module, "event": event, **redact(context)}
        with path.open("a", encoding="utf-8") as stream: stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    def event(self, level: str, module: str, event: str, **context: Any) -> None: self._write(self.app, level, module, event, **context)
    def llm_event(self, event: str, request: Any = None, response: Any = None, **context: Any) -> None:
        if request is not None and self.include_requests: context["request"] = request
        if response is not None and self.include_responses: context["response"] = response
        self._write(self.llm, "DEBUG", "openrouter", event, **context)

