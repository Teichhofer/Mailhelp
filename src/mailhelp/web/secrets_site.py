"""Credentials in the web interface, write-only (3.3.11).

The page lists the credentials the current draft configuration needs and whether each is set.
It never shows a stored value, not even masked.  Saving needs a live session (checked again
right before writing), the CSRF token, an idempotency key, an explicit confirmation and the
.env content the page was built from.  Logs and the journal contain names only.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, quote

from ..config.env_file import EnvFileConflict, file_hash, set_value
from ..i18n import msg, stored, tr
from .auth import WebSession
from .forms import post_form
from .http import Request, Response
from .pages import e, layout, notice

if TYPE_CHECKING:
    from .site import MailhelpSite

ROUTE = "/einstellungen/zugangsdaten"
OPERATIONS = "secret-operations"
MAX_OPERATIONS = 100


class SecretsSite:
    def __init__(self, site: MailhelpSite) -> None:
        self.site = site
        # SettingsSite owns the shared POST route and dispatches by form version.
        site.app.route("GET", ROUTE, site.signed_in(self.index))

    @property
    def runtime(self) -> Any:
        return self.site.setup_page.runtime

    @property
    def path(self) -> Path:
        directory: Path = self.runtime.app.configuration.directory
        return directory / ".env"

    def index(self, request: Request, session: WebSession) -> Response:
        if self.runtime is None:
            return Response.text(503, msg("Einrichtungsdienst nicht verfügbar."))
        saved = parse_qs(request.query).get("gespeichert", [""])[0]
        env, current = self.runtime.environment(), file_hash(self.path)
        csrf = self.site.auth.csrf_token(session.id)
        body = tr("<h1>Zugangsdaten</h1>")
        if re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", saved):
            body += notice(
                tr(
                    (
                        "{p0} gespeichert. Diagnose und Einrichtung verwenden den Wert "
                        "sofort, der Mailabruf nach dem nächsten Neustart."
                    ),
                    p0=saved,
                )
            )
        body += tr(
            "<p>Gespeicherte Werte werden nie angezeigt. Ein neuer Wert "
            "ersetzt den bisherigen in der Datei .env im "
            "Konfigurationsverzeichnis. MAILHELP_WEB_SECRET wird hier nicht "
            "geändert, weil das alle Sitzungen beenden würde.</p>"
        )
        group = None
        for heading, name in self.runtime.secret_fields():
            if heading != group:
                close = "</section>" if group is not None else ""
                body += f'{close}<section class="card"><h2>{e(stored(heading))}</h2>'
                group = heading
            state = msg("hinterlegt") if env.get(name) else msg("fehlt")
            body += f'<p><strong>{e(name)}</strong> · {state}</p>'
            if name in os.environ:
                body += tr('<p class="meta">In der Prozessumgebung gesetzt; dieser Wert hat Vorrang vor .env.</p>')
            identity = "secret-" + name.lower().replace("_", "-")
            kind = "text" if name.endswith("_USERNAME") else "password"
            body += post_form(
                ROUTE + "/speichern",
                csrf,
                tr(
                    (
                        '<label for="{p0}">Neuer Wert für {p1}</label><input id="{p2}" '
                        'type="{p3}" name="value" autocomplete="off" maxlength="4096" '
                        'required><label><input type="checkbox" name="confirm" '
                        'value="yes" required> Wert ausdrücklich in .env speichern</label>'
                    ),
                    p0=identity,
                    p1=e(name),
                    p2=identity,
                    p3=kind,
                ),
                msg("Speichern"),
                name=name,
                expected_hash=current,
            )
        body += "</section>" if group is not None else ""
        body += tr('<p><a class="button" href="/einstellungen/iserv">IServ-Verbindung prüfen und aktivieren</a></p>')
        return Response.html(200, layout(msg("Zugangsdaten"), '<div class="setup-page">' + body + "</div>"))

    def save(self, request: Request, session: WebSession, form: dict[str, str]) -> Response:
        if self.runtime is None:
            return Response.text(503, msg("Einrichtungsdienst nicht verfügbar."))
        name, key = form.get("name", ""), form.get("key", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", key) or form.get("confirm") != "yes":
            return Response.text(422, msg("Speichern nicht bestätigt."))
        store = self.site.views.store
        with store.locked():
            operations = store.load(OPERATIONS, {})
            if key in operations:
                # A repeated request (reload, double click) does not write again.
                return (
                    Response.redirect('{p0}?gespeichert={p1}'.format(p0=f'{ROUTE}', p1=f'{quote(name)}'))
                    if operations[key] == name
                    else Response.text(409, msg("Idempotenzschlüssel bereits verwendet."))
                )
            if name not in {field for _, field in self.runtime.secret_fields()}:
                return Response.text(422, msg("Dieser Name wird von der Konfiguration nicht verwendet."))
            if not self.site.auth.active(session.id, operator=True):
                return Response.text(403, msg("Sitzung abgelaufen."))
            try:
                set_value(self.path, name, form.get("value", ""), form.get("expected_hash", ""))
            except EnvFileConflict:
                return Response.text(409, msg(".env wurde inzwischen geändert; Seite neu laden."))
            except ValueError:
                return Response.text(422, msg("Wert leer, zu lang oder mit Steuerzeichen."))
            except OSError:
                return Response.text(503, msg(".env ist nicht beschreibbar; in Docker beschreibbar einbinden."))
            operations[key] = name
            store.save(OPERATIONS, dict(list(operations.items())[-MAX_OPERATIONS:]))
        logger = self.runtime.app.logger
        if hasattr(logger, "secrets"):
            logger.secrets = (*logger.secrets, form["value"])
        logger.event("INFO", "web", "secret_saved", name=name)
        return Response.redirect('{p0}?gespeichert={p1}'.format(p0=f'{ROUTE}', p1=f'{quote(name)}'))


__all__ = ["ROUTE", "SecretsSite"]
