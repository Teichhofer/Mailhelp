"""Shared checks and write logging of the 2.3 providers (CalDAV, Microsoft Graph)."""
from __future__ import annotations

import time
import traceback
from abc import abstractmethod
from collections.abc import Callable
from typing import Any

from ..logging import EventLogger
from ..models import Proposal
from .contracts import PreparedWrite, TargetWriter, proposal_is_writable


class ProviderWriter(TargetWriter):
    """Target check, kind check and create logging shared by every new provider."""

    logger: EventLogger
    _read_cache: dict[tuple[Any, ...], tuple[float, Any]]

    def prepare(self, proposal: Proposal, key: str) -> PreparedWrite:
        if not proposal_is_writable(proposal):
            raise ValueError("Dieser Vorschlag darf nicht extern angelegt werden")
        if proposal.target != self.target:
            raise ValueError("Konfiguriertes Ziel weicht vom bestätigten Vorschlagsziel ab")
        self.logger.event("INFO", self.service, "create_started", call_id=key, mail_id=proposal.source_mail_id,
                          proposal_id=proposal.id)
        return self._prepare(proposal, key)

    @abstractmethod
    def _prepare(self, proposal: Proposal, key: str) -> PreparedWrite: ...

    def _logged(self, proposal: Proposal, key: str, operation: Callable[[], dict[str, Any]],
                event: str = "create_completed") -> dict[str, Any]:
        """Run one write; log its outcome without content and forget cached reads."""
        started = time.perf_counter()
        try:
            result = operation()
        except Exception as exc:
            self.logger.event("ERROR", self.service, "create_failed", call_id=key, mail_id=proposal.source_mail_id,
                              proposal_id=proposal.id, error=exc, stacktrace=traceback.format_exc(),
                              duration_ms=round((time.perf_counter() - started) * 1000, 3))
            raise
        self.logger.event("INFO", self.service, event, call_id=key, mail_id=proposal.source_mail_id,
                          proposal_id=proposal.id, duration_ms=round((time.perf_counter() - started) * 1000, 3))
        self._read_cache.clear()
        return result

    def _get_cached(self, key: tuple[Any, ...]) -> Any | None:
        if key in self._read_cache:
            stamp, value = self._read_cache[key]
            if time.time() - stamp < 60.0:
                return value
        return None

    def _set_cached(self, key: tuple[Any, ...], value: Any) -> None:
        self._read_cache[key] = (time.time(), value)
