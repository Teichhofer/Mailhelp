"""Independent bounded read-only checks; external error text never escapes."""
from __future__ import annotations

import imaplib
import platform
import re
import ssl
import time
from datetime import UTC, datetime
from threading import Event, Lock, Thread
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from . import __version__
from .adapter import PermanentError

STATES = {"unchecked": "nicht geprüft", "running": "wird geprüft", "ready": "bereit",
          "limited": "eingeschränkt", "failed": "fehlgeschlagen", "disabled": "deaktiviert"}
HELP = {"": "Keine weitere Maßnahme erforderlich.",
        "network": "Verbindung und Erreichbarkeit prüfen; andere Dienste bleiben nutzbar.",
        "tls": "TLS-Zertifikat und Systemzeit prüfen.",
        "auth": "Zugangsdaten oder App-Passwort in .env beziehungsweise Prozessumgebung prüfen.",
        "permission": "Berechtigung und ausgewähltes Ziel prüfen.",
        "configuration": "Lokale Konfiguration und vorhandene Ordner prüfen.",
        "service": "Dienst derzeit nicht nutzbar; später erneut prüfen.",
        "timeout": "Zeitlimit erreicht; Verbindung prüfen und später erneut starten.",
        "interrupted": "Prüfung durch Neustart unterbrochen; erneut starten.",
        "draft_readonly": "Entwurfsordner lesbar. Eine Schreibberechtigung wurde nicht geprüft.",
        "browser": "HTTPS, Browserberechtigung und Geräteabonnement prüfen.",
        "unauthorized": "Sitzung abgelaufen; erneut anmelden."}


class DiagnosticResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["unchecked", "running", "ready", "limited", "failed", "disabled"] = "unchecked"
    checked_at: datetime | None = None
    duration_ms: int = Field(default=0, ge=0)
    config_revision: str = Field(default="", pattern=r"^(?:[a-f0-9]{64})?$")
    code: Literal["", "network", "tls", "auth", "permission", "configuration", "service", "timeout",
                  "interrupted", "draft_readonly", "browser", "unauthorized"] = ""


class DiagnosticsState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    version: int = 0
    results: dict[str, DiagnosticResult] = Field(default_factory=dict)
    operations: dict[str, str] = Field(default_factory=dict)


def error_code(exc: Exception) -> str:
    if isinstance(exc, ssl.SSLError):
        return "tls"
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return "timeout"
    if isinstance(exc, imaplib.IMAP4.error):
        return "auth"
    if isinstance(exc, PermissionError):
        return "permission"
    if isinstance(exc, httpx.HTTPStatusError):
        return {401: "auth", 403: "permission"}.get(exc.response.status_code, "service")
    if isinstance(exc, (ConnectionError, OSError, httpx.TransportError)):
        return "network"
    if isinstance(exc, ValueError):
        return "configuration"
    if isinstance(exc, PermanentError):
        return "permission"
    return "service"


class DiagnosticsService:
    def __init__(self, store, active, checks, timeout=10, clock=lambda: datetime.now(UTC), revision=lambda: ""):
        self.store, self.active, self.checks, self.timeout, self.clock = store, active, checks, timeout, clock
        self.revision = revision
        self._lock, self._busy = Lock(), set()
        state = self.state()
        for result in state.results.values():
            if result.status == "running":
                result.status, result.code = "failed", "interrupted"
        self._save(state)

    def state(self) -> DiagnosticsState:
        return self.store.load_model("diagnostics-state", DiagnosticsState, DiagnosticsState())

    def _save(self, state):
        self.store.save("diagnostics-state", state.model_dump(mode="json"))

    def run(self, actor, name, version, key):
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", key) or name not in self.checks:
            raise ValueError("Ungültige Prüfung oder Idempotenzschlüssel")
        with self._lock:
            if not self.active(actor):
                raise PermissionError("Sitzung abgelaufen")
            state = self.state()
            operation = f"{actor}:{key}"
            signature = f"{name}:{version}"
            if operation in state.operations:
                if state.operations[operation] != signature:
                    raise ValueError("Idempotenzkonflikt")
                return
            if version != state.version or name in self._busy:
                raise ValueError("Prüfstand geändert oder Prüfung läuft")
            state.version += 1
            state.operations[operation] = signature
            state.operations = dict(list(state.operations.items())[-500:])
            state.results[name] = DiagnosticResult(status="running")
            self._save(state)
            self._busy.add(name)
        completed, outcome = Event(), []
        started = time.monotonic()
        revision = self.revision()
        def execute():
            try:
                if not self.active(actor):
                    outcome.append(("failed", "unauthorized"))
                else:
                    outcome.append(self.checks[name](actor))
            except Exception as exc:
                outcome.append(("failed", error_code(exc)))
            finally:
                completed.set()
        Thread(target=execute, name=f"mailhelp-diagnostic-{name}", daemon=True).start()
        finished = completed.wait(self.timeout)
        status, code = outcome[0] if finished else ("failed", "timeout")
        if revision != self.revision():
            status, code = "failed", "configuration"
        with self._lock:
            state = self.state()
            state.results[name] = DiagnosticResult(status=status, code=code, checked_at=self.clock(),
                                                   config_revision=revision,
                                                   duration_ms=int((time.monotonic() - started) * 1000))
            self._save(state)
            if finished:
                self._busy.remove(name)
        # A timed-out worker keeps this component busy until restart. It cannot
        # accumulate more workers or deliver a late success over the timeout.

    def report(self):
        """Allowlist export excludes configured targets, paths, identities and secrets."""
        return {"schema_version": 1, "version": __version__,
                "platform": "Windows" if platform.system() == "Windows" else "Linux",
                "components": {name: result.model_dump(mode="json", exclude={"config_revision"})
                               for name, result in self.state().results.items()}}
