"""Pairing by a one-time Telegram code, revocable sessions and CSRF tokens.

Tailscale Serve forwards requests from 127.0.0.1 exactly like a local browser,
so identity headers such as ``Tailscale-User-Login`` cannot be told apart from
forged local requests and are ignored.  Instead a browser is paired once: it
requests a code, Mailhelp sends the code to the configured Telegram chat, and
entering it creates a long-lived session.

* Codes are valid for 10 minutes, bound to the requesting browser and stored
  only as an HMAC.  A code is spent after five wrong attempts; codes can be
  requested at most three times in ten minutes; more than twenty wrong
  attempts in an hour lock the pairing for the rest of that hour.
* Session tokens are random and stored only as a hash.  Sessions expire after
  ``session_days``, show device and last use, and can be revoked one by one or
  all at once (also with the Telegram command ``/web_abmelden``).
* CSRF tokens are HMACs of the session (or pairing) identifier.

Web threads write only these web-owned records (``web-sessions``,
``web-pairing``), under a lock, never review state.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..storage import JsonStore

SESSIONS = "web-sessions"
PAIRING = "web-pairing"
CODE_LIFETIME = timedelta(minutes=10)
CODE_ATTEMPTS = 5
CODE_REQUESTS = 3
CODE_REQUEST_WINDOW = timedelta(minutes=10)
FAILURE_LIMIT = 20
FAILURE_WINDOW = timedelta(hours=1)
# last_used_at is refreshed at most this often to keep writes rare.
TOUCH_INTERVAL = timedelta(minutes=5)
MAX_SESSIONS = 20
DEVICE_LIMIT = 60


class PairingRefused(ValueError):
    """The code was wrong, expired or not requested by this browser."""


class PairingLimited(RuntimeError):
    """Too many requests or failures; try again later."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PendingCode(_Model):
    # None: issued with the Telegram command /web and valid in any browser.
    browser_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    code_hmac: str = Field(pattern=r"^[a-f0-9]{64}$")
    expires_at: datetime
    attempts: int = Field(default=0, ge=0)


class PairingState(_Model):
    schema_version: Literal[1] = 1
    codes: list[PendingCode] = Field(default_factory=list)
    requests: list[datetime] = Field(default_factory=list)
    failures: list[datetime] = Field(default_factory=list)


class WebSession(_Model):
    id: str = Field(pattern=r"^[a-f0-9]{16}$")
    token_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    device: str = Field(min_length=1, max_length=DEVICE_LIMIT)
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime


class SessionState(_Model):
    schema_version: Literal[1] = 1
    sessions: list[WebSession] = Field(default_factory=list)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


def device_name(user_agent: str | None, chosen: str | None = None) -> str:
    """A short label: the chosen name, else system and browser from the User-Agent."""
    name = " ".join((chosen or "").split())[:DEVICE_LIMIT]
    if name:
        return name
    agent = user_agent or ""
    system = next((label for pattern, label in (
        ("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"), ("Windows", "Windows"),
        ("Macintosh", "Mac"), ("Linux", "Linux")) if pattern in agent), "Unbekanntes Gerät")
    browser = next((label for pattern, label in (
        ("Edg/", "Edge"), ("Firefox/", "Firefox"), ("CriOS/", "Chrome"), ("Chrome/", "Chrome"),
        ("Safari/", "Safari")) if pattern in agent), None)
    return f"{system} · {browser}" if browser else system


class WebAuth:
    """Pairing, sessions and CSRF for exactly one authorized person."""

    def __init__(self, store: JsonStore, secret: str, session_days: int,
                 notify: Callable[[str], None], clock: Callable[[], datetime] = _now):
        self.store, self.notify, self.clock = store, notify, clock
        # "telegram", or "console" when Mailhelp runs without Telegram (standalone, 2.0).
        self.channel = "telegram"
        self._key = secret.encode("utf-8")
        self.session_lifetime = timedelta(days=session_days)
        self._lock = Lock()

    # --- tokens ------------------------------------------------------------------

    def _mac(self, purpose: str, value: str) -> str:
        return hmac.new(self._key, f"{purpose}:{value}".encode(), hashlib.sha256).hexdigest()

    def csrf_token(self, binding: str) -> str:
        """CSRF token for a session id or a browser pairing nonce."""
        return self._mac("csrf", binding)

    def csrf_valid(self, binding: str, token: str | None) -> bool:
        return token is not None and hmac.compare_digest(
            self.csrf_token(binding).encode("utf-8"), token.encode("utf-8")
        )

    @staticmethod
    def new_browser_nonce() -> str:
        return secrets.token_urlsafe(32)

    # --- pairing -------------------------------------------------------------------

    def _pairing(self) -> PairingState:
        state = self.store.load_model(PAIRING, PairingState, PairingState())
        assert isinstance(state, PairingState)
        now = self.clock()
        state.codes = [code for code in state.codes if code.expires_at > now]
        state.requests = [time for time in state.requests if time > now - CODE_REQUEST_WINDOW]
        state.failures = [time for time in state.failures if time > now - FAILURE_WINDOW]
        return state

    def code_requested(self, browser_nonce: str) -> bool:
        with self._lock:
            browser = _sha256(browser_nonce)
            return any(code.browser_hash in {browser, None} for code in self._pairing().codes)

    def request_code(self, browser_nonce: str, device: str) -> None:
        """Send a new code for this browser to Telegram; replaces its earlier code."""
        with self._lock:
            state = self._pairing()
            if len(state.failures) >= FAILURE_LIMIT or len(state.requests) >= CODE_REQUESTS:
                raise PairingLimited("Zu viele Anfragen – bitte später erneut versuchen.")
            code = f"{secrets.randbelow(10 ** 4):04d}"
            browser = _sha256(browser_nonce)
            state.codes = [item for item in state.codes if item.browser_hash != browser]
            state.codes.append(PendingCode(browser_hash=browser, code_hmac=self._mac("code", code),
                                           expires_at=self.clock() + CODE_LIFETIME))
            state.requests.append(self.clock())
            self.store.save(PAIRING, state.model_dump(mode="json"))
        self.notify(f"🔐 Mailhelp-Webanmeldung für „{device}“: Code {code}\n"
                    "Gültig 10 Minuten. Nur eingeben, wenn du die Anmeldung selbst gestartet hast.")

    def issue_code(self) -> str:
        """A code for the Telegram command /web: not bound to a browser, replaces the previous one.

        Only the authorized Telegram chat receives it, exactly like a requested code.
        """
        with self._lock:
            state = self._pairing()
            if len(state.failures) >= FAILURE_LIMIT or len(state.requests) >= CODE_REQUESTS:
                raise PairingLimited("Zu viele Codes angefordert – bitte später erneut versuchen.")
            code = f"{secrets.randbelow(10 ** 4):04d}"
            state.codes = [item for item in state.codes if item.browser_hash is not None]
            state.codes.append(PendingCode(code_hmac=self._mac("code", code),
                                           expires_at=self.clock() + CODE_LIFETIME))
            state.requests.append(self.clock())
            self.store.save(PAIRING, state.model_dump(mode="json"))
        return code

    def redeem(self, browser_nonce: str, code: str, device: str) -> str:
        """Exchange a correct code for a new session; returns the session token."""
        entered = re.sub(r"\s", "", code)
        with self._lock:
            state = self._pairing()
            if len(state.failures) >= FAILURE_LIMIT:
                raise PairingLimited("Zu viele Fehlversuche – bitte später erneut versuchen.")
            browser = _sha256(browser_nonce)
            # The code requested in this browser, then one sent with /web.
            candidates = [item for item in state.codes if item.browser_hash == browser]
            candidates += [item for item in state.codes if item.browser_hash is None]
            if not candidates:
                raise PairingRefused("Kein gültiger Code angefordert oder Code abgelaufen.")
            mac = self._mac("code", entered)
            pending = next((item for item in candidates
                            if hmac.compare_digest(item.code_hmac, mac)), None)
            if pending is None:
                state.failures.append(self.clock())
                for item in candidates:
                    item.attempts += 1
                    if item.attempts >= CODE_ATTEMPTS:
                        state.codes.remove(item)
                self.store.save(PAIRING, state.model_dump(mode="json"))
                raise PairingRefused("Der Code stimmt nicht.")
            state.codes.remove(pending)
            self.store.save(PAIRING, state.model_dump(mode="json"))
            token = secrets.token_urlsafe(32)
            now = self.clock()
            sessions = self._sessions()
            sessions.sessions.append(WebSession(
                id=secrets.token_hex(8), token_hash=_sha256(token), device=device,
                created_at=now, last_used_at=now, expires_at=now + self.session_lifetime))
            # Keep the most recently used sessions if the limit is exceeded.
            sessions.sessions = sorted(sessions.sessions, key=lambda item: item.last_used_at)[-MAX_SESSIONS:]
            self.store.save(SESSIONS, sessions.model_dump(mode="json"))
        self.notify(f"🔐 Neues Gerät für die Mailhelp-Weboberfläche gekoppelt: „{device}“.\n"
                    "Warst du das nicht? /web_abmelden meldet alle Geräte ab.")
        return token

    # --- sessions ------------------------------------------------------------------

    def _sessions(self) -> SessionState:
        state = self.store.load_model(SESSIONS, SessionState, SessionState())
        assert isinstance(state, SessionState)
        now = self.clock()
        state.sessions = [item for item in state.sessions if item.expires_at > now]
        return state

    def authenticate(self, token: str | None) -> WebSession | None:
        """The live session for a cookie token, or None."""
        if not token:
            return None
        digest = _sha256(token)
        with self._lock:
            state = self._sessions()
            session = next((item for item in state.sessions
                            if hmac.compare_digest(item.token_hash, digest)), None)
            if session is None:
                return None
            now = self.clock()
            if now - session.last_used_at >= TOUCH_INTERVAL:
                session.last_used_at = now
                self.store.save(SESSIONS, state.model_dump(mode="json"))
            return session

    def active(self, session_id: str) -> bool:
        """Whether a session still exists (checked again when a command runs)."""
        with self._lock:
            return any(item.id == session_id for item in self._sessions().sessions)

    def sessions(self) -> list[WebSession]:
        with self._lock:
            return sorted(self._sessions().sessions, key=lambda item: item.last_used_at, reverse=True)

    def revoke(self, session_id: str) -> bool:
        with self._lock:
            state = self._sessions()
            remaining = [item for item in state.sessions if item.id != session_id]
            found = len(remaining) != len(state.sessions)
            state.sessions = remaining
            self.store.save(SESSIONS, state.model_dump(mode="json"))
            return found

    def revoke_all(self) -> int:
        with self._lock:
            count = len(self._sessions().sessions)
            self.store.save(SESSIONS, SessionState().model_dump(mode="json"))
            return count


__all__ = ["CODE_ATTEMPTS", "CODE_LIFETIME", "CODE_REQUESTS", "FAILURE_LIMIT", "MAX_SESSIONS",
           "PAIRING", "PairingLimited", "PairingRefused", "SESSIONS", "WebAuth", "WebSession",
           "device_name"]
