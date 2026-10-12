"""Logger doubles that implement the real ``EventLogger`` protocol (Planung 2.1, T2)."""
from __future__ import annotations

from typing import Any

from mailhelp.logging import NullLogger


class RecordingLogger(NullLogger):
    """Record ``((level, module, event), fields)``; an invalid level fails like in production."""

    def __init__(self) -> None:
        self.events: list[tuple[tuple[str, str, str], dict[str, Any]]] = []

    def event(self, level: str, module: str, event: str, **fields: Any) -> None:
        super().event(level, module, event, **fields)
        self.events.append(((level, module, event), fields))
