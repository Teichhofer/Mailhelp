"""Gemeinsame, begrenzte Wiederholungsregeln fuer externe Adapter."""
from __future__ import annotations

from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from time import time
from typing import Callable, TypeVar

import httpx
import imaplib

T = TypeVar("T")
RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


class PermanentError(RuntimeError):
    """Die identische Anfrage darf nicht erneut gesendet werden."""

    def __init__(self, message: str, *, safe_detail: str | None = None):
        self.safe_detail = safe_detail
        super().__init__(f"{message}: {safe_detail}" if safe_detail else message)


class RetryableError(RuntimeError):
    """Eine eindeutig lesende/idempotente Operation ist temporaer gescheitert."""


class UncertainWriteError(RuntimeError):
    """Ein Schreibzugriff kann trotz fehlender Antwort erfolgt sein."""


class RetryInterrupted(RetryableError):
    """Der kontrollierte Shutdown hat einen Backoff abgebrochen."""


def _error_message(default: str, exc: Exception) -> str:
    """Add only an adapter-provided, explicitly safe diagnostic."""
    detail = getattr(exc, "safe_detail", None)
    return f"{default}: {detail}" if isinstance(detail, str) and detail else default


@dataclass(frozen=True)
class RetryPolicy:
    retries: int
    initial_backoff_seconds: float
    max_backoff_seconds: float
    wait: Callable[[float], bool]
    clock: Callable[[], float] = time

    def run(self, operation: Callable[[], T], on_attempt: Callable[[int], None] | None = None, on_error: Callable[[int, Exception], None] | None = None) -> T:
        attempt = 0
        while True:
            if on_attempt is not None:
                on_attempt(attempt + 1)
            try:
                return operation()
            except (httpx.TransportError, httpx.HTTPStatusError, imaplib.IMAP4.abort,
                    TimeoutError, EOFError, OSError) as exc:
                if on_error is not None:
                    on_error(attempt + 1, exc)
                delay = self._delay(exc, attempt)
                if delay is None or attempt == self.retries:
                    if self._retryable(exc):
                        raise RetryableError(_error_message("Wiederholbare Anfrage ist ausgeschoepft", exc)) from exc
                    raise PermanentError(
                        "Permanente Adapterantwort",
                        safe_detail=getattr(exc, "safe_detail", None),
                    ) from exc
                if self.wait(delay):
                    raise RetryInterrupted("Shutdown waehrend Adapter-Backoff") from exc
                attempt += 1

    def _delay(self, exc: Exception, attempt: int) -> float | None:
        if not self._retryable(exc):
            return None
        exponential = min(self.max_backoff_seconds, self.initial_backoff_seconds * 2 ** attempt)
        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
            header = exc.response.headers.get("Retry-After")
            if header:
                try:
                    retry_after = max(0.0, float(header))
                except ValueError:
                    try:
                        retry_after = max(0.0, parsedate_to_datetime(header).timestamp() - self.clock())
                    except (TypeError, ValueError, OverflowError):
                        retry_after = exponential
                return min(self.max_backoff_seconds, max(exponential, retry_after))
        return exponential

    @staticmethod
    def _retryable(exc: Exception) -> bool:
        return isinstance(exc, (httpx.TransportError, imaplib.IMAP4.abort,
                                TimeoutError, EOFError, OSError)) or (
            isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in RETRYABLE_STATUS
        )


def uncertain_write(operation: Callable[[], T]) -> T:
    """Schreibzugriffe nie blind wiederholen; unklare Ergebnisse markieren."""
    try:
        return operation()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code not in RETRYABLE_STATUS:
            raise PermanentError(_error_message("Permanente Adapterantwort", exc)) from exc
        raise UncertainWriteError(_error_message("Unklarer externer Schreiberfolg", exc)) from exc
    except httpx.TransportError as exc:
        raise UncertainWriteError("Unklarer externer Schreiberfolg") from exc
