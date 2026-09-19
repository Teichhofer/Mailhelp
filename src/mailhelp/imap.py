"""Schreibfreier IMAP-Adapter (BODY.PEEK verändert \\Seen nicht)."""
from __future__ import annotations
import imaplib
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
    account_id: str = "0" * 24
    received_at: datetime = datetime.min.replace(tzinfo=timezone.utc)


class UIDValidityChanged(RuntimeError):
    """Report a new UID generation before any message body is fetched."""

    def __init__(self, folder: str, previous: int, current: int):
        super().__init__(f"IMAP-UIDVALIDITY hat sich geändert: {folder}")
        self.previous = previous
        self.current = current


def _fetched_mail(folder: str, uidvalidity: int, uid: int, data: object,
                  mailbox: str) -> FetchedMail:
    """Validate the deliberately combined FETCH response without trusting its shape."""
    if not isinstance(data, list):
        raise RuntimeError(f"IMAP-Abruf fehlgeschlagen: UID {uid}")
    item = next((part for part in data if isinstance(part, tuple) and len(part) >= 2), None)
    if item is None or not isinstance(item[0], bytes) or not isinstance(item[1], bytes):
        raise RuntimeError(f"IMAP-Abruf fehlgeschlagen: UID {uid}")
    match = re.search(rb'\bINTERNALDATE\s+"([^"]+)"', item[0], re.IGNORECASE)
    if match is None:
        raise RuntimeError(f"IMAP lieferte kein gültiges INTERNALDATE: UID {uid}")
    try:
        received_at = datetime.strptime(match.group(1).decode("ascii"), "%d-%b-%Y %H:%M:%S %z")
    except (UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError(f"IMAP lieferte kein gültiges INTERNALDATE: UID {uid}") from exc
    return FetchedMail(folder, uidvalidity, uid, item[1], mailbox, received_at)


def account_id(host: str, port: int, username: str) -> str:
    """Return a stable, non-secret identifier for one configured mailbox."""
    normalized = f"{host.strip().rstrip('.').lower()}\n{port}\n{username.strip().lower()}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


class ImapReader:
    def __init__(self, host: str, port: int, username: str, password: str, timeout: float = 30, factory: Callable[..., imaplib.IMAP4] = imaplib.IMAP4_SSL, policy: RetryPolicy | None = None, logger: EventLogger | None = None, starttls: bool = False, batch_size: int = 25):
        self.policy = policy or RetryPolicy(0, 0, 0, lambda _delay: False)
        self.logger = logger or NullLogger()
        self.batch_size = batch_size
        self.connection = factory(host, port, timeout=timeout)
        self.account_id = account_id(host, port, username)
        self.last_uidvalidity: int | None = None
        try:
            if starttls:
                status, _ = self.connection.starttls()
                if status != "OK":
                    raise RuntimeError("IMAP STARTTLS fehlgeschlagen")
            try:
                self.connection.login(username, password)
            except imaplib.IMAP4.error:
                raise RuntimeError(
                    "IMAP-Anmeldung abgelehnt. Punkte und Bindestriche im "
                    "Benutzernamen werden unverändert unterstützt; vollständige "
                    "E-Mail-Adresse, Passwort beziehungsweise App-Passwort und "
                    "IMAP-Freischaltung beim Anbieter prüfen"
                ) from None
        except BaseException:
            self.connection.logout()
            raise

    def check_access(self, folders: list[str]) -> None:
        """Verify read-only access without searching for or fetching messages."""
        for folder in folders:
            status, _ = self.connection.select(folder, readonly=True)
            if status != "OK":
                raise RuntimeError(f"IMAP-Ordner nicht lesbar: {folder}")

    def fetch_since(self, folder: str, after_uid: int = 0,
                    expected_uidvalidity: int | None = None,
                    max_count: int | None = None,
                    completed_uid_ranges: tuple[tuple[int, int], ...] = ()) -> list[FetchedMail]:
        started = time.perf_counter()
        self.logger.event("INFO", "imap", "request_started", folder=folder, after_uid=after_uid)
        try:
            result = self.policy.run(lambda: self._fetch_since(folder, after_uid, expected_uidvalidity, max_count, completed_uid_ranges),
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
        status, body = self.connection.uid("fetch", str(uid).encode(), "(BODY.PEEK[] INTERNALDATE)")
        if status != "OK":
            raise RuntimeError(f"IMAP-Abruf fehlgeschlagen: UID {uid}")
        return _fetched_mail(folder, uidvalidity, uid, body, self.account_id)

    def determine_start_uid(self, folder: str, start: datetime) -> int:
        """Resolve an absolute historical boundary once, without changing flags."""
        status, _ = self.connection.select(folder, readonly=True)
        if status != "OK": raise RuntimeError(f"IMAP-Ordner nicht lesbar: {folder}")
        status, validity = self.connection.response("UIDVALIDITY")
        if status != "UIDVALIDITY" or not validity: raise RuntimeError("IMAP lieferte keine UIDVALIDITY")
        self.last_uidvalidity = int(validity[0])
        # IMAP SEARCH only has day precision. Search one day early and inspect
        # INTERNALDATE so the configured instant remains exact and timezone-safe.
        utc_start = start.astimezone(timezone.utc)
        since = (utc_start - timedelta(days=1)).strftime("%d-%b-%Y")
        status, matches = self.connection.uid("search", None, "SINCE", since)
        if status != "OK": raise RuntimeError("IMAP-Suche nach Startgrenze fehlgeschlagen")
        candidates = matches[0].split() if matches else []
        for token in candidates:
            status, data = self.connection.uid("fetch", token, "(INTERNALDATE)")
            if status != "OK":
                raise RuntimeError(f"IMAP-INTERNALDATE-Abruf abgelehnt: {status}")
            metadata = []
            for part in data or []:
                candidate = part[0] if isinstance(part, tuple) and part else part
                if isinstance(candidate, bytes) and candidate.strip() != b")":
                    metadata.append(candidate)
            match = next((found for item in metadata
                          if (found := re.search(
                              rb'\bINTERNALDATE\s+"([^"]*)"', item,
                              re.IGNORECASE)) is not None), None)
            if match is None:
                raise RuntimeError(
                    "IMAP-INTERNALDATE-Antwort leer oder strukturell unbrauchbar")
            try:
                instant = datetime.strptime(match.group(1).decode("ascii"), "%d-%b-%Y %H:%M:%S %z")
            except (UnicodeDecodeError, ValueError) as exc:
                raise RuntimeError("IMAP lieferte ungültigen INTERNALDATE-Datumswert") from exc
            if instant >= utc_start:
                return max(0, int(token) - 1)
        status, all_matches = self.connection.uid("search", None, "ALL")
        if status != "OK": raise RuntimeError("IMAP-Suche fehlgeschlagen")
        all_uids = all_matches[0].split() if all_matches else []
        return int(all_uids[-1]) if all_uids else 0

    def _fetch_since(self, folder: str, after_uid: int,
                     expected_uidvalidity: int | None,
                     max_count: int | None,
                     completed_uid_ranges: tuple[tuple[int, int], ...] = ()) -> list[FetchedMail]:
        status, data = self.connection.select(folder, readonly=True)
        if status != "OK": raise RuntimeError(f"IMAP-Ordner nicht lesbar: {folder}")
        status, validity = self.connection.response("UIDVALIDITY")
        if status != "UIDVALIDITY" or not validity: raise RuntimeError("IMAP lieferte keine UIDVALIDITY")
        uidvalidity = int(validity[0]); self.last_uidvalidity = uidvalidity
        if expected_uidvalidity is not None and expected_uidvalidity != uidvalidity:
            # Do not search or fetch in a UID generation whose durable boundary
            # has not been resolved yet.  In particular, BODY.PEEK must not run.
            raise UIDValidityChanged(folder, expected_uidvalidity, uidvalidity)
        status, matches = self.connection.uid("search", None, f"UID {after_uid + 1}:*")
        if status != "OK": raise RuntimeError("IMAP-Suche fehlgeschlagen")
        tokens = matches[0].split() if matches else []
        def completed(uid: int) -> bool:
            return any(start <= uid <= end for start, end in completed_uid_ranges)
        available = [token for token in reversed(tokens) if not completed(int(token))]
        fetch_count = self.batch_size if max_count is None else min(self.batch_size, max_count)
        selected = available[:fetch_count]
        self.logger.event("INFO", "imap", "messages_discovered", folder=folder,
                          available_count=len(available), batch_count=len(selected))
        result = []
        for token in selected:
            uid = int(token); status, body = self.connection.uid("fetch", token, "(BODY.PEEK[] INTERNALDATE)")
            if status != "OK": raise RuntimeError(f"IMAP-Abruf fehlgeschlagen: UID {uid}")
            result.append(_fetched_mail(folder, uidvalidity, uid, body, self.account_id))
            self.logger.event("INFO", "imap", "message_fetched", folder=folder, uid=uid,
                              batch_index=len(result), batch_count=len(selected))
        return result

    def close(self) -> None:
        self.connection.logout()
