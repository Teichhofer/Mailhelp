"""Explicitly confirmed, controlled stop of the service."""
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

    def stop_page(self, request, session):
        lifecycle = self.archive.lifecycle
        if lifecycle is None:
            return self.site._reply(request, 503, "Beenden ist in dieser Instanz nicht verfügbar.")
        body = '<h1>Mailhelp beenden?</h1>' + notice(
            'Danach ist diese Weboberfläche nicht erreichbar. Laufende Requests können bis zum Timeout dauern. '
            'Offene Vorgänge bleiben gespeichert. Neustart erfolgt am PC oder über den Container/Dienst; '
            'ein Supervisor kann automatisch neu starten. Windows und andere Prozesse werden nicht beendet.', "warn")
        body += post_form(request.path, self.site.auth.csrf_token(session.id), '', 'Mailhelp ausdrücklich beenden',
                          process=lifecycle.process, confirm="yes")
        return Response.html(200, layout("Beenden", body))

    def stop(self, request, session, form):
        lifecycle = self.archive.lifecycle
        try:
            if lifecycle is None or form.get("confirm") != "yes":
                raise ValueError("Bestätigung fehlt")
            callback = lifecycle.request(form["process"], form["key"], f"web:{session.id}")
        except (ValueError, KeyError):
            return self.site._reply(request, 409, "Beenden nicht bestätigt oder Anforderung veraltet.")
        response = Response.html(202, layout(
            "Beenden angefordert", '<h1>Beenden angefordert</h1><p>Mailhelp stoppt kontrolliert. Ein späterer '
            'Verbindungsabbruch bestätigt allein nicht den erfolgreichen Abschluss.</p>'))
        response.after_send = callback
        return response
