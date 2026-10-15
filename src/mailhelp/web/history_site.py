"""The audit history, stored proposal versions and the cost evaluation (all read only)."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from .. import state_names
from ..models import Proposal
from ..review.filters import matches
from ..review.queries import ArchiveQuery
from .archive_pages import MODE_LABELS, history_page, statistics_page, version_diff
from .http import Response
from .pages import layout
from .review_pages import detail_page

if TYPE_CHECKING:
    from .archive_site import ArchiveSite

PROPOSAL_PATH = r"/vorschlag/(?P<mail_id>[a-f0-9]{24})/(?P<proposal_id>[A-Za-z0-9_-]{1,64})"


class HistorySite:
    def __init__(self, archive: ArchiveSite):
        self.archive, self.site = archive, archive.site
        for method, path, handler in (
                ("GET", "/verlauf", self.history), ("GET", "/auswertung", self.statistics),
                ("GET", PROPOSAL_PATH + r"/version/(?P<version>[1-9][0-9]{0,5})", self.version)):
            self.site.app.route(method, path, self.site.signed_in(handler))

    def _matches(self, row: dict, query: ArchiveQuery, source: dict) -> bool:
        if not matches(query.filter, [row["proposal_kind"]], [row["status"]], source["attachments"],
                       source["duplicate"]):
            return False
        if query.q and query.q.casefold() not in (row["mail_id"] + row["title"]).casefold():
            return False
        zone = ZoneInfo(self.site.configured_timezone)
        day = datetime.fromisoformat(row["at"]).astimezone(zone).date().isoformat()
        if query.since and day < query.since.isoformat() or query.until and day > query.until.isoformat():
            return False
        return not (query.status and str(query.status) != row["status"]
                    or query.kind and query.kind != row["kind"]
                    or query.proposal_kind and query.proposal_kind != row["proposal_kind"])

    def history(self, request, session):
        try:
            params = self.archive.parameters(request)
            query = ArchiveQuery.model_validate(params)
        except ValueError:
            return self.site._reply(request, 422, "Ungültige Verlaufsfilter.")
        queries = self.archive.queries
        # One lookup per history row instead of a scan over all mails.
        sources = {item["id"]: item for item in queries.items()}
        rows = [row for row in queries.history() if self._matches(row, query, sources[row["mail_id"]])]
        rows.sort(key=lambda row: row["at"], reverse=True)
        page = rows[(query.page - 1)*query.size:query.page*query.size]
        return Response.html(200, layout("Verlauf", history_page(query, page, len(rows), params), active="/verlauf"))

    def version(self, request, session, mail_id, proposal_id, version):
        store = self.site.views.store
        if store.peek(f"history-{mail_id}", {}).get("removed"):
            return self.site._reply(request, 404, "Historische Inhalte nach Aufbewahrung entfernt.")
        view = self.site.views.proposal(mail_id, proposal_id, int(version))
        if view is None:
            return self.site._reply(request, 404, "Version nicht mehr vorhanden.")
        previous = store.peek_model(state_names.proposal(mail_id, proposal_id, int(version)-1), Proposal)
        current = store.peek_model(state_names.proposal(mail_id, proposal_id, version), Proposal)
        return Response.html(200, detail_page(view, after=version_diff(previous, current)))

    def statistics(self, request, session):
        metrics = self.archive.metrics
        if metrics is None:
            return Response.html(200, layout("Auswertung",
                                             '<h1>Auswertung</h1><p>Noch keine Metrikerfassung verfügbar.</p>'))
        try:
            params = self.archive.parameters(request)
            params["days"] = int(params.get("days", 30))
            params.setdefault("mode", "production")
            if params["mode"] not in MODE_LABELS:
                raise ValueError("Unbekannter Modus")
            comparison = params["mode"] == "decision_test" and metrics.comparison is not None
            selected = metrics.comparison if comparison else metrics
            report = selected.report(**params)
        except (ValueError, TypeError):
            return self.site._reply(request, 422, "Ungültige Auswertungsfilter.")
        everything = selected.report(days=params["days"], mode=params["mode"])["records"]
        return Response.html(200, layout("Auswertung", statistics_page(params, report, everything,
                                                                         self.site.configured_timezone),
                                         active="/auswertung"))
