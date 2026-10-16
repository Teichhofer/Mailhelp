"""Explicitly confirmed, controlled stop or restart of the service."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .forms import post_form
from .http import Response
from .pages import layout, notice

if TYPE_CHECKING:
    from .archive_site import ArchiveSite


class ShutdownSite:
    def __init__(self, archive: ArchiveSite):
        self.archive, self.site = archive, archive.site
        for method, handler in (("GET", self.stop_page), ("POST", self.stop)):
            self.site.app.route(method, "/einstellungen/beenden", self.site.signed_in(handler))
        for method, restart_handler in (("GET", self.restart_page), ("POST", self.restart)):
            self.site.app.route(method, "/einstellungen/neustarten", self.site.signed_in(restart_handler))

    def restart_page(self, request, session):
        return self.stop_page(request, session, restart=True)

    def restart(self, request, session, form):
        return self.stop(request, session, form, restart=True)

    def stop_page(self, request, session, *, restart=False):
        lifecycle = self.archive.lifecycle
        action = "Neustart" if restart else "Beenden"
        if lifecycle is None:
            return self.site._reply(request, 503, f"{action} ist in dieser Instanz nicht verfügbar.")
        explanation = (
            'Mailhelp stoppt kontrolliert und startet anschließend mit den gespeicherten Einstellungen '
            'und Zugangsdaten neu. Offene Vorgänge bleiben erhalten. Die Weboberfläche ist kurz nicht erreichbar; '
            'danach die Seite neu laden.' if restart else
            'Danach ist diese Weboberfläche nicht erreichbar. Laufende Requests können bis zum Timeout dauern. '
            'Offene Vorgänge bleiben gespeichert. Neustart erfolgt am PC oder über den Container/Dienst; '
            'ein Supervisor kann automatisch neu starten. Windows und andere Prozesse werden nicht beendet.')
        heading = "Mailhelp neu starten?" if restart else "Mailhelp beenden?"
        button = "Mailhelp ausdrücklich neu starten" if restart else "Mailhelp ausdrücklich beenden"
        body = f'<h1>{heading}</h1>' + notice(explanation, "warn")
        body += post_form(request.path, self.site.auth.csrf_token(session.id), '', button,
                          process=lifecycle.process, confirm="yes")
        return Response.html(200, layout(action, body))

    def stop(self, request, session, form, *, restart=False):
        lifecycle = self.archive.lifecycle
        action = "Neustart" if restart else "Beenden"
        try:
            if lifecycle is None or form.get("confirm") != "yes":
                raise ValueError("Bestätigung fehlt")
            callback = lifecycle.request(form["process"], form["key"], f"web:{session.id}", restart=restart)
        except (ValueError, KeyError):
            return self.site._reply(request, 409, f"{action} nicht bestätigt oder Anforderung veraltet.")
        heading = f"{action} angefordert"
        explanation = ('Mailhelp startet nach dem kontrollierten Stopp neu. Anschließend '
                       '<a href="/">Weboberfläche erneut öffnen</a>.' if restart else
                       'Mailhelp stoppt kontrolliert. Ein späterer Verbindungsabbruch bestätigt allein '
                       'nicht den erfolgreichen Abschluss.')
        response = Response.html(202, layout(
            heading, f'<h1>{heading}</h1><p>{explanation}</p>'))
        response.after_send = callback
        return response
