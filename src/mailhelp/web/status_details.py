"""Authenticated, read-only drilldowns of the status counters."""
from __future__ import annotations

from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from ..formatting import format_datetime_local
from .auth import WebSession
from .http import Request, Response
from .pages import e, layout
from .review_pages import proposal_card, relevance_card

if TYPE_CHECKING:
    from .site import MailhelpSite

TITLES = {"vorschlaege": "Offene Vorschläge", "relevanzfragen": "Relevanzfragen",
          "web-aktionen": "Wartende Web-Aktionen"}


class StatusDetails:
    def __init__(self, site: MailhelpSite):
        self.site = site
        site.app.route("GET", r"/status/(?P<section>vorschlaege|relevanzfragen|web-aktionen)",
                       site.signed_in(self.show))

    def show(self, request: Request, session: WebSession, section: str) -> Response:
        title = TITLES[section]
        body = (f'<h1>{title}</h1><p><a href="/status">Zur Statusseite</a></p>'
                '<p>Aktueller gespeicherter Stand. Das Öffnen dieser Übersicht führt keine Aktion aus.</p>')
        if section == "web-aktionen":
            entries = self.site.commands.queued()
            body += f'<p role="status">{len(entries)} wartende Web-Aktionen.</p>'
            body += '<ul class="status-command-list">'
            for entry in entries:
                when = format_datetime_local(entry.received_at, ZoneInfo(self.site.configured_timezone))
                if entry.command.actor == "web:" + session.id:
                    body += (f'<li><a href="/aktion/{entry.id}">Wartende Aktion ansehen</a>'
                             f' · wartet seit {e(when)}</li>')
                else:
                    body += f'<li>Aktion einer anderen Sitzung · wartet seit {e(when)}</li>'
            body += '</ul>'
            count = len(entries)
        else:
            overview = self.site.views.overview()
            body += '<h2>Einträge in diesem Status</h2>'
            if section == "vorschlaege":
                count = len(overview.open)
                cards = ''.join(proposal_card(view) for view in overview.open)
            else:
                count = len(overview.relevance)
                cards = ''.join(relevance_card(view) for view in overview.relevance)
            body += f'<p role="status">{count} Einträge.</p>' + cards
        if not count:
            body += '<p>Aktuell keine Einträge in diesem Status.</p>'
        body += '<p><a class="button" href="' + e(request.path) + '">Übersicht aktualisieren</a></p>'
        return Response.html(200, layout(title, body, active="/status"))
