"""Credentials in the web interface, write-only (3.3.11).

The page lists the credentials the current draft configuration needs and whether each is set.
It never shows a stored value, not even masked.  Saving needs a live session (checked again
right before writing), the CSRF token, an idempotency key, an explicit confirmation and the
.env content the page was built from.  Logs and the journal contain names only.
"""
from __future__ import annotations

import os
import re
from urllib.parse import parse_qs, quote

from ..env_file import EnvFileConflict, file_hash, set_value
from .forms import post_form
from .http import Response
from .pages import e, layout, notice

ROUTE = "/einstellungen/zugangsdaten"
OPERATIONS = "secret-operations"
MAX_OPERATIONS = 100


class SecretsSite:
    def __init__(self, site):
        self.site = site
        # SettingsSite owns the shared POST route and dispatches by form version.
        site.app.route("GET", ROUTE, site.signed_in(self.index))

    @property
    def runtime(self):
        return self.site.setup_page.runtime

    @property
    def path(self):
        return self.runtime.app.configuration.directory / ".env"

    def index(self, request, session):
        if self.runtime is None:
            return Response.text(503, "Einrichtungsdienst nicht verfügbar.")
        saved = parse_qs(request.query).get("gespeichert", [""])[0]
        env, current = self.runtime.environment(), file_hash(self.path)
        csrf = self.site.auth.csrf_token(session.id)
        body = '<h1>Zugangsdaten</h1>'
        if re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", saved):
            body += notice(f"{saved} gespeichert. Diagnose und Einrichtung verwenden den Wert sofort, der "
                           "Mailabruf nach dem nächsten Neustart.")
        body += ('<p>Gespeicherte Werte werden nie angezeigt. Ein neuer Wert ersetzt den bisherigen in der Datei '
                 '.env im Konfigurationsverzeichnis. MAILHELP_WEB_SECRET wird hier nicht geändert, weil das alle '
                 'Sitzungen beenden würde.</p>')
        group = None
        for heading, name in self.runtime.secret_fields():
            if heading != group:
                body += ("</section>" if group is not None else "") + f'<section class="card"><h2>{e(heading)}</h2>'
                group = heading
            state = "hinterlegt" if env.get(name) else "fehlt"
            body += f'<p><strong>{e(name)}</strong> · {state}</p>'
            if name in os.environ:
                body += ('<p class="meta">In der Prozessumgebung gesetzt; dieser Wert hat Vorrang vor .env.</p>')
            identity = "secret-" + name.lower().replace("_", "-")
            kind = "text" if name.endswith("_USERNAME") else "password"
            body += post_form(
                ROUTE + "/speichern", csrf,
                f'<label for="{identity}">Neuer Wert für {e(name)}</label>'
                f'<input id="{identity}" type="{kind}" name="value" autocomplete="off" maxlength="4096" required>'
                f'<label><input type="checkbox" name="confirm" value="yes" required> '
                f'Wert ausdrücklich in .env speichern</label>',
                "Speichern", name=name, expected_hash=current)
        body += "</section>" if group is not None else ""
        return Response.html(200, layout("Zugangsdaten", '<div class="setup-page">' + body + "</div>"))

    def save(self, request, session, form):
        if self.runtime is None:
            return Response.text(503, "Einrichtungsdienst nicht verfügbar.")
        name, key = form.get("name", ""), form.get("key", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", key) or form.get("confirm") != "yes":
            return Response.text(422, "Speichern nicht bestätigt.")
        store = self.site.views.store
        with store.locked():
            operations = store.load(OPERATIONS, {})
            if key in operations:
                # A repeated request (reload, double click) does not write again.
                return (Response.redirect(f"{ROUTE}?gespeichert={quote(name)}") if operations[key] == name
                        else Response.text(409, "Idempotenzschlüssel bereits verwendet."))
            if name not in {field for _, field in self.runtime.secret_fields()}:
                return Response.text(422, "Dieser Name wird von der Konfiguration nicht verwendet.")
            if not self.site.auth.active(session.id):
                return Response.text(403, "Sitzung abgelaufen.")
            try:
                set_value(self.path, name, form.get("value", ""), form.get("expected_hash", ""))
            except EnvFileConflict:
                return Response.text(409, ".env wurde inzwischen geändert; Seite neu laden.")
            except ValueError:
                return Response.text(422, "Wert leer, zu lang oder mit Steuerzeichen.")
            except OSError:
                return Response.text(503, ".env ist nicht beschreibbar; in Docker beschreibbar einbinden.")
            operations[key] = name
            store.save(OPERATIONS, dict(list(operations.items())[-MAX_OPERATIONS:]))
        logger = self.runtime.app.logger
        if hasattr(logger, "secrets"):
            logger.secrets = (*logger.secrets, form["value"])
        logger.event("INFO", "web", "secret_saved", name=name)
        return Response.redirect(f"{ROUTE}?gespeichert={quote(name)}")


__all__ = ["ROUTE", "SecretsSite"]
