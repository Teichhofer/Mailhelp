"""8.8.4 (Planung 8.8 AP4): "Eigene Verbindungen prüfen" – read-only checks of own mailboxes and targets.

Only checks of the instance's own connections run (no model call, no message, no file system). Each
check keeps its own time limit; one pass also has a total limit, runs once at a time and a session
waits a short cooldown before the next pass. Results name a status and a next step only – never a
provider, a token, a path or the name of a credential.
"""

from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Callable
from threading import Lock
from typing import Any

from ..i18n import msg, tr
from ..runtime.diagnostics import DiagnosticResult
from .auth import WebSession
from .forms import post_form
from .http import Response
from .pages import e, layout, notice

OWN_CHECKS = re.compile(r"imap|calendar|todoist|(?:calendar|tasks):[1-9][0-9]?")
PATH = "/einstellungen/verbindungen/pruefen"
BACK = ("/einstellungen/postfaecher", "/einstellungen/zielprofile")
COOLDOWN_SECONDS, BUDGET_SECONDS = 15.0, 30.0
_RENEW = {"auth", "permission", "unauthorized"}
_LATER = {"network", "tls", "service", "timeout", "interrupted"}


def label(name: str) -> str:
    if name == "imap":
        return tr("Postfächer")
    number = name.split(":")[1] if ":" in name else "1"
    if name.startswith("calendar"):
        return tr("Kalender (Zielprofil {p0})", p0=number)
    return tr("Aufgaben (Zielprofil {p0})", p0=number)


def status(result: DiagnosticResult) -> tuple[str, str]:
    """A customer's view of one result: the state and the next step, without technical details."""
    if result.status == "ready":
        return tr("erreichbar"), ""
    if result.status in {"unchecked", "running", "disabled", "limited"}:
        return {"unchecked": (tr("noch nicht geprüft"), ""), "running": (tr("wird geprüft"), ""),
                "disabled": (tr("nicht eingerichtet"), ""),
                "limited": (tr("eingeschränkt erreichbar"), tr("Später erneut prüfen."))}[result.status]
    if result.code in _RENEW:
        return tr("Anmeldung erneuern"), tr("Die Verbindung erneut verbinden oder das Passwort neu eintragen.")
    if result.code in _LATER:
        return tr("vorübergehend nicht erreichbar"), tr("Später erneut prüfen.")
    return tr("Einstellung prüfen"), tr("Adresse, Ordner oder Ziel der Verbindung prüfen.")


def names(runtime: Any) -> list[str]:
    runtime.update_profile_checks()
    return [name for name in runtime.diagnostics.checks if OWN_CHECKS.fullmatch(name)]


def results(runtime: Any, shown: list[str]) -> str:
    state = runtime.diagnostics.state()
    rows = ""
    for name in shown:
        text, step = status(state.results.get(name, DiagnosticResult()))
        rows += (f"<li><strong>{e(label(name))}</strong>: {e(text)}"
                 + (f' <span class="meta">{e(step)}</span>' if step else "") + "</li>")
    # The live region wraps the list; a role on the list itself would hide its items from assistive technology.
    return f'<div role="status"><ul class="own-checks">{rows}</ul></div>'


def section(runtime: Any, csrf: str, back: str) -> str:
    """Results of the last checks and the button for a new read-only pass."""
    shown = names(runtime)
    return (tr('<section class="card"><h2>Eigene Verbindungen</h2><p>Prüft lesend, ob Postfächer, Kalender und '
               'Aufgabenlisten erreichbar sind. Es wird nichts angelegt oder gesendet.</p>')
            + results(runtime, shown)
            + post_form(PATH, csrf, "", msg("Eigene Verbindungen prüfen"), zurueck=back) + "</section>")


class OwnChecks:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self._guard, self._running = Lock(), Lock()
        self._last: dict[str, float] = {}

    def _wait(self, text: str) -> Response:
        body = tr("<h1>Bitte kurz warten</h1>") + notice(text, "info")
        response = Response.html(429, layout(tr("Bitte kurz warten"), body))
        response.headers["Retry-After"] = str(int(COOLDOWN_SECONDS))
        return response

    def run(self, runtime: Any, session: WebSession, form: dict[str, str]) -> Response:
        if runtime is None:
            return Response.text(503, msg("Einrichtungsdienst nicht verfügbar."))
        back = form.get("zurueck", "")
        back = back if back in BACK else BACK[0]
        key = form.get("key", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", key):
            return Response.text(409, msg("Prüfung nicht gestartet; Seite neu laden und Sitzung prüfen."))
        now = self.clock()
        with self._guard:
            last = self._last.get(session.id)
            if last is not None and now - last < COOLDOWN_SECONDS:
                return self._wait(tr("Die Verbindungen wurden gerade geprüft. In einigen Sekunden erneut versuchen."))
            if not self._running.acquire(blocking=False):
                return self._wait(tr("Eine Prüfung läuft bereits. In einigen Sekunden erneut versuchen."))
            self._last = {sid: at for sid, at in self._last.items() if now - at < COOLDOWN_SECONDS}
            self._last[session.id] = now
        try:
            diagnostics = runtime.diagnostics
            for name in names(runtime):
                if self.clock() - now >= BUDGET_SECONDS:
                    break  # the remaining ones keep their last result
                child = hashlib.sha256(f"{key}:{name}".encode()).hexdigest()[:40]
                try:
                    diagnostics.run(session.id, name, diagnostics.state().version, child)
                except ValueError:
                    continue  # this check is running elsewhere; its result appears when it is done
        except PermissionError:
            return Response.redirect("/anmelden")
        finally:
            self._running.release()
        return Response.redirect(back + "?geprueft=1")


__all__ = ["BACK", "BUDGET_SECONDS", "COOLDOWN_SECONDS", "OWN_CHECKS", "PATH", "OwnChecks", "label", "names",
           "results", "section", "status"]
