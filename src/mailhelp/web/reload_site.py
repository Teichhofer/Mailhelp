"""Explicit version-bound request to prepare the next runtime generation."""

import secrets
from typing import Any

from .http import Response
from .pages import e, layout, notice


class ReloadSite:
    def __init__(self, site: Any, service: Any) -> None:
        self.site, self.service = site, service
        site.app.route("GET", "/dienst/neu-laden", site.signed_in(self.home))
        site.app.route("POST", "/dienst/neu-laden", site.signed_in(self.act))
        site.app.route("GET", "/dienst/selbsttest", site.signed_in(self.selftest))
        site.app.route("POST", "/dienst/selbsttest", site.signed_in(self.test))

    def home(self, request: Any, session: Any) -> Response:
        state = self.service.state()
        body = "<h1>Konfiguration neu laden</h1>" + (notice(state.message) if state.message else "")
        body += (
            "<p>Themen, Prompts, Postfächer, Zugangsdaten und Zielprofile am nächsten sicheren Zeitpunkt übernehmen. "
            "Unfertige Analysen werden zuvor abgeschlossen. "
            "Web-Zugang und Datenverzeichnis benötigen einen Neustart.</p>"
            '<form method="post" action="/dienst/neu-laden">'
            f'<input type="hidden" name="csrf" value="{e(self.site.auth.csrf_token(session.id))}">'
            f'<input type="hidden" name="version" value="{state.version}">'
            f'<input type="hidden" name="key" value="{secrets.token_hex(16)}">'
            f'<input type="hidden" name="revision" value="{self.service.revision()}">'
            '<button class="button">Konfiguration ausdrücklich neu laden</button></form>'
        )
        return Response.html(
            200, layout("Konfiguration neu laden", body, refresh=3 if state.status in {"pending", "running"} else None)
        )

    def act(self, request: Any, session: Any, form: Any) -> Response:
        try:
            self.service.request("web:" + session.id, int(form["version"]), form["key"], form["revision"])
        except (ValueError, KeyError):
            return Response.html(
                409, layout("Neuladen prüfen", notice("Stand oder Sitzung geändert; neu laden.", "error"))
            )
        return Response.redirect("/dienst/neu-laden")

    def selftest(self, request: Any, session: Any) -> Response:
        service = self.site.setup_page.runtime.diagnostics
        body = (
            "<h1>Selbsttest</h1>"
            "<p>Alle Komponenten lesend prüfen. Ergebnisse und Handlungsempfehlungen stehen in der Diagnose.</p>"
            '<form method="post" action="/dienst/selbsttest">'
            f'<input type="hidden" name="csrf" value="{e(self.site.auth.csrf_token(session.id))}">'
            f'<input type="hidden" name="version" value="{service.state().version}">'
            f'<input type="hidden" name="key" value="{secrets.token_hex(12)}">'
            '<button class="button">Lesenden Selbsttest starten</button></form>'
        )
        return Response.html(200, layout("Selbsttest", body))

    def test(self, request: Any, session: Any, form: Any) -> Response:
        try:
            self.site.setup_page.runtime.update_profile_checks()
            self.site.setup_page.runtime.diagnostics.run_all(session.id, int(form["version"]), form["key"])
        except (ValueError, KeyError, PermissionError):
            return Response.html(409, layout("Selbsttest prüfen", notice("Stand oder Sitzung geändert.", "error")))
        return Response.redirect("/diagnose")
