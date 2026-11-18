"""Authenticated, read-only drilldowns of the status counters."""

from __future__ import annotations

from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from ..formatting import format_datetime_local
from ..i18n import msg, tr
from .auth import WebSession
from .http import Request, Response
from .pages import e, layout
from .review_pages import proposal_card, relevance_card

if TYPE_CHECKING:
    from .site import MailhelpSite

TITLES = {
    "vorschlaege": msg("Offene Vorschläge"),
    "relevanzfragen": msg("Relevanzfragen"),
    "web-aktionen": msg("Wartende Web-Aktionen"),
}


class StatusDetails:
    def __init__(self, site: MailhelpSite) -> None:
        self.site = site
        site.app.route("GET", r"/status/(?P<section>vorschlaege|relevanzfragen|web-aktionen)",
                       site.signed_in(self.show))

    def show(self, request: Request, session: WebSession, section: str) -> Response:
        title = TITLES[section]
        body = tr(
            (
                '<h1>{p0}</h1><p><a href="/status">Zur '
                "Statusseite</a></p><p>Aktueller gespeicherter Stand. Das Öffnen "
                "dieser Übersicht führt keine Aktion aus.</p>"
            ),
            p0=title,
        )
        if section == "web-aktionen":
            entries = self.site.commands.queued()
            body += tr('<p role="status">{p0} wartende Web-Aktionen.</p>', p0=len(entries))
            body += '<ul class="status-command-list">'
            for entry in entries:
                when = format_datetime_local(entry.received_at, ZoneInfo(self.site.configured_timezone))
                if entry.command.actor == "web:" + session.id:
                    body += tr(
                        ('<li><a href="/aktion/{p0}">Wartende Aktion ansehen</a> · wartet seit {p1}</li>'),
                        p0=entry.id,
                        p1=e(when),
                    )
                else:
                    body += tr("<li>Aktion einer anderen Sitzung · wartet seit {p0}</li>", p0=e(when))
            body += '</ul>'
            count = len(entries)
        else:
            overview = self.site.views.overview()
            body += tr("<h2>Einträge in diesem Status</h2>")
            if section == "vorschlaege":
                count = len(overview.open)
                cards = ''.join(proposal_card(view) for view in overview.open)
            else:
                count = len(overview.relevance)
                cards = ''.join(relevance_card(view) for view in overview.relevance)
            body += tr('<p role="status">{p0} Einträge.</p>', p0=count) + cards
        if not count:
            body += tr("<p>Aktuell keine Einträge in diesem Status.</p>")
        body += '<p><a class="button" href="' + e(request.path) + tr('">Übersicht aktualisieren</a></p>')
        return Response.html(200, layout(title, body, active="/status"))
