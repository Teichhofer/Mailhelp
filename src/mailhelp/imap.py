"""Schreibfreier IMAP-Adapter (BODY.PEEK verändert \\Seen nicht)."""
from __future__ import annotations
import imaplib
from dataclasses import dataclass
from typing import Callable
from .adapter import RetryPolicy
from .logging import EventLogger, NullLogger
import time, traceback


@dataclass(frozen=True)
class FetchedMail:
    folder: str
    uidvalidity: int
    uid: int
    raw: bytes


class ImapReader:
    def __init__(self, host: str, port: int, username: str, password: str, timeout: float = 30, factory: Callable[..., imaplib.IMAP4] = imaplib.IMAP4_SSL, policy: RetryPolicy | None = None, logger: EventLogger | None = None):
        self.policy = policy or RetryPolicy(0, 0, 0, lambda _delay: False)
        self.logger = logger or NullLogger()
        self.connection = factory(host, port, timeout=timeout)
        self.last_uidvalidity: int | None = None
        try:
            self.connection.login(username, password)
        except BaseException:
            self.connection.logout()
            raise

    def fetch_since(self, folder: str, after_uid: int = 0, expected_uidvalidity: int | None = None) -> list[FetchedMail]:
        started = time.perf_counter()
        self.logger.event("INFO", "imap", "request_started", folder=folder, after_uid=after_uid)
        try:
            result = self.policy.run(lambda: self._fetch_since(folder, after_uid, expected_uidvalidity),
                                     lambda attempt: self.logger.event("DEBUG", "imap", "request_attempt", folder=folder, attempt=attempt),
                                     lambda attempt, exc: self.logger.event("WARNING", "imap", "request_retry", folder=folder, attempt=attempt, error=exc))
        except Exception as exc:
            self.logger.event("ERROR", "imap", "request_failed", folder=folder, error=exc, stacktrace=traceback.format_exc(), duration_ms=round((time.perf_counter()-started)*1000, 3))
            raise
        self.logger.event("INFO", "imap", "request_completed", folder=folder, count=len(result), duration_ms=round((time.perf_counter()-started)*1000, 3))
        return result

    def fetch_uid(self, folder: str, uid: int, expected_uidvalidity: int) -> FetchedMail:
        """Load one known message without setting ``\\Seen``."""
        status, _data = self.connection.select(folder, readonly=True)
        if status != "OK": raise RuntimeError(f"IMAP-Ordner nicht lesbar: {folder}")
        status, validity = self.connection.response("UIDVALIDITY")
        if status != "UIDVALIDITY" or not validity: raise RuntimeError("IMAP lieferte keine UIDVALIDITY")
        uidvalidity = int(validity[0]); self.last_uidvalidity = uidvalidity
        if uidvalidity != expected_uidvalidity:
            raise RuntimeError(f"IMAP-UIDVALIDITY hat sich geändert: {folder}")
        status, body = self.connection.uid("fetch", str(uid).encode(), "(BODY.PEEK[])")
        if status != "OK" or not body or not isinstance(body[0], tuple):
            raise RuntimeError(f"IMAP-Abruf fehlgeschlagen: UID {uid}")
        return FetchedMail(folder, uidvalidity, uid, body[0][1])

    def _fetch_since(self, folder: str, after_uid: int, expected_uidvalidity: int | None) -> list[FetchedMail]:
        status, data = self.connection.select(folder, readonly=True)
        if status != "OK": raise RuntimeError(f"IMAP-Ordner nicht lesbar: {folder}")
        status, validity = self.connection.response("UIDVALIDITY")
        if status != "UIDVALIDITY" or not validity: raise RuntimeError("IMAP lieferte keine UIDVALIDITY")
        uidvalidity = int(validity[0]); self.last_uidvalidity = uidvalidity
        if expected_uidvalidity != uidvalidity:
            after_uid = 0
        status, matches = self.connection.uid("search", None, f"UID {after_uid + 1}:*")
        if status != "OK": raise RuntimeError("IMAP-Suche fehlgeschlagen")
        result = []
        for token in matches[0].split():
            uid = int(token); status, body = self.connection.uid("fetch", token, "(BODY.PEEK[])")
            if status != "OK" or not body or not isinstance(body[0], tuple): raise RuntimeError(f"IMAP-Abruf fehlgeschlagen: UID {uid}")
            result.append(FetchedMail(folder, uidvalidity, uid, body[0][1]))
        return result

    def close(self) -> None:
        self.connection.logout()
