"""Explicitly confirmed, controlled stop or restart of the service."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..i18n import msg, tr
from ..runtime.lifecycle import StopRefused
from .auth import WebSession
from .forms import post_form
from .http import Request, Response
from .pages import layout, notice

if TYPE_CHECKING:
    from .archive_site import ArchiveSite


class ShutdownSite:
    def __init__(self, archive: ArchiveSite) -> None:
        self.archive, self.site = archive, archive.site
        for method, handler in (("GET", self.stop_page), ("POST", self.stop)):
            self.site.app.route(method, "/einstellungen/beenden", self.site.signed_in(handler))
        for method, restart_handler in (("GET", self.restart_page), ("POST", self.restart)):
            self.site.app.route(method, "/einstellungen/neustarten", self.site.signed_in(restart_handler))

    def restart_page(self, request: Request, session: WebSession) -> Response:
        return self.stop_page(request, session, restart=True)

    def restart(self, request: Request, session: WebSession, form: dict[str, str]) -> Response:
        return self.stop(request, session, form, restart=True)

    def stop_page(self, request: Request, session: WebSession, *, restart: bool = False) -> Response:
        lifecycle = self.archive.lifecycle
        action = msg("Neustart") if restart else msg("Beenden")
        if lifecycle is None:
            return self.site._reply(request, 503, tr("{p0} ist in dieser Instanz nicht verfügbar.", p0=action))
        explanation = (
            msg(
                
                    "Mailhelp stoppt kontrolliert und startet anschließend mit den "
                    "gespeicherten Einstellungen und Zugangsdaten neu. Offene Vorgänge bleiben "
                    "erhalten. Die Weboberfläche ist kurz nicht erreichbar; danach die Seite neu laden."
                
            )
            if restart
            else msg(
                
                    "Danach ist diese Weboberfläche nicht erreichbar. Laufende Requests können "
                    "bis zum Timeout dauern. Offene Vorgänge bleiben gespeichert. Neustart "
                    "erfolgt am PC oder über den Container/Dienst; ein Supervisor kann "
                    "automatisch neu starten. Windows und andere Prozesse werden nicht beendet."
                
            )
        )
        heading = msg("Mailhelp neu starten?") if restart else msg("Mailhelp beenden?")
        body = f'<h1>{heading}</h1>' + notice(explanation, "warn")
        body += self._form(request, session, restart)
        return Response.html(200, layout(action, body))

    def _form(self, request: Request, session: WebSession, restart: bool) -> str:
        """A fresh confirmation bound to the running process."""
        assert self.archive.lifecycle is not None
        button = msg("Mailhelp ausdrücklich neu starten") if restart else msg("Mailhelp ausdrücklich beenden")
        return post_form(request.path, self.site.auth.csrf_token(session.id), '', button,
                         process=self.archive.lifecycle.process, confirm="yes")

    def stop(self, request: Request, session: WebSession, form: dict[str, str], *, restart: bool = False) -> Response:
        lifecycle = self.archive.lifecycle
        action = msg("Neustart") if restart else msg("Beenden")
        if lifecycle is None:
            return self.site._reply(request, 409, tr("{p0} nicht bestätigt oder Anforderung veraltet.", p0=action))
        try:
            if form.get("confirm") != "yes":
                raise StopRefused("unconfirmed", "Bestätigung fehlt")
            callback = lifecycle.request(form.get("process", ""), form.get("key", ""), f"web:{session.id}",
                                         restart=restart)
        except StopRefused as refused:
            return self._refused(request, session, refused.reason, restart)
        heading = tr("{p0} angefordert", p0=f"{action}")
        explanation = (
            tr(
                "Mailhelp startet nach dem kontrollierten Stopp neu. Anschließend "
                '<a href="/">Weboberfläche erneut öffnen</a>.'
            )
            if restart
            else msg(
                
                    "Mailhelp stoppt kontrolliert. Ein späterer Verbindungsabbruch bestätigt "
                    "allein nicht den erfolgreichen Abschluss."
                
            )
        )
        response = Response.html(202, layout(
            heading, f'<h1>{heading}</h1><p>{explanation}</p>'))
        response.after_send = callback
        return response

    def _refused(self, request: Request, session: WebSession, reason: str, restart: bool) -> Response:
        """Say why, log a fixed reason code and offer a fresh confirmation where it can help."""
        action = msg("Neustart") if restart else msg("Beenden")
        self.site.logger.event("WARNING", "lifecycle", "stop_refused", reason=reason, restart=restart)
        text = REFUSALS[reason].format(action=action)
        if request.wants_json():
            return Response.json(409, {"error": text, "reason": reason})
        body = tr("<h1>{p0} nicht ausgeführt</h1>", p0=action) + notice(text, "warn")
        if reason in RETRYABLE:
            body += self._form(request, session, restart)
        return Response.html(409, layout(action, body))


# Fixed texts for the refusal codes of :class:`StopRefused`; no request data is shown.
REFUSALS = {
    "stale_process": (
        msg(
            "Die Bestätigung stammte von einem früheren Mailhelp-Start, zum Beispiel von vor einem "
            "Neustart. Bitte hier erneut bestätigen."
        )
    ),
    "unconfirmed": msg("Die Bestätigung war unvollständig. Bitte hier erneut bestätigen."),
    "invalid_key": msg("Die Bestätigung war unvollständig. Bitte hier erneut bestätigen."),
    "unauthorized": msg("Die Anmeldung dieses Geräts ist nicht mehr gültig. Bitte neu anmelden."),
    "already_requested": msg("{action} wurde bereits angefordert und läuft."),
}
RETRYABLE = {"stale_process", "unconfirmed", "invalid_key"}
