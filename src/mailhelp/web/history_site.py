"""The audit history, stored proposal versions and the cost evaluation (all read only)."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from .. import state_names
from ..models import Proposal
from ..review.filters import matches
from ..review.queries import ArchiveQuery
from .archive_pages import MODE_LABELS, history_page, statistics_page, version_diff
from .auth import WebSession
from .http import Request, Response
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
                ("GET", "/auswertung/aufrufe", self.calls), ("GET", "/auswertung/schritte", self.steps),
                ("GET", PROPOSAL_PATH + r"/version/(?P<version>[1-9][0-9]{0,5})", self.version)):
            self.site.app.route(method, path, self.site.signed_in(handler))

    def _matches(self, row: dict[str, Any], query: ArchiveQuery, source: dict[str, Any]) -> bool:
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

    def history(self, request: Request, session: WebSession) -> Response:
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

    def version(self, request: Request, session: WebSession, mail_id: str, proposal_id: str, version: str) -> Response:
        store = self.site.views.store
        if store.peek(f"history-{mail_id}", {}).get("removed"):
            return self.site._reply(request, 404, "Historische Inhalte nach Aufbewahrung entfernt.")
        view = self.site.views.proposal(mail_id, proposal_id, int(version))
        if view is None:
            return self.site._reply(request, 404, "Version nicht mehr vorhanden.")
        previous = store.peek_model(state_names.proposal(mail_id, proposal_id, int(version)-1), Proposal)
        current = store.peek_model(state_names.proposal(mail_id, proposal_id, version), Proposal)
        assert current is not None  # the view above was read from this very version
        return Response.html(200, detail_page(view, after=version_diff(previous, current)))

    def _report(self, params: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
        """The selected journal and its report; raises ValueError or TypeError for invalid filters."""
        params["days"] = int(params.get("days", 30))
        params.setdefault("mode", "production")
        if params["mode"] not in MODE_LABELS:
            raise ValueError("Unbekannter Modus")
        metrics = self.archive.metrics
        assert metrics is not None  # both callers answer without metrics before reading a report
        comparison = metrics.comparison
        selected = comparison if params["mode"] == "decision_test" and comparison is not None else metrics
        return selected, selected.report(**params)

    def calls(self, request: Request, session: WebSession) -> Response:
        """5.9.11: read only; unknown figures, sort orders or filters are rejected with 422."""
        from .calls_page import METRICS, SORTS, STATUSES, calls_page
        metrics = self.archive.metrics
        if metrics is None:
            return Response.html(200, layout("Auswertung",
                                             '<h1>Auswertung</h1><p>Noch keine Metrikerfassung verfügbar.</p>'))
        try:
            params: dict[str, Any] = dict(self.archive.parameters(request))
            metric = params.pop("metric", "calls")
            sort = params.pop("sort", "")
            status = params.pop("status", None)
            page = int(params.pop("page", "1"))
            if metric not in METRICS or (sort and sort not in SORTS) or (status is not None and status not in STATUSES):
                raise ValueError("Unbekannte Auswahl")
            if not 1 <= page <= 10_000:
                raise ValueError("Ungültige Seite")
            selected, report = self._report(params)
        except (ValueError, TypeError):
            return self.site._reply(request, 422, "Ungültige Auswertungsfilter.")
        views = self.site.views

        def subject(mail_id: str) -> str | None:
            mail = views.mail(mail_id)
            return mail.subject if mail is not None else None
        html = calls_page(metric, params, sort, status, page, report, selected.settings,
                          self.site.configured_timezone, subject, MODE_LABELS)
        return Response.html(200, layout(METRICS[metric].title, html, active="/auswertung"))

    def steps(self, request: Request, session: WebSession) -> Response:
        """6.1.8: the slowest runs of one step; read only, unknown values are rejected with 422."""
        from ..runtime.stage_metrics import report as stage_report
        from .stage_page import SORTS, STAGES, stage_page, title
        metrics = self.archive.metrics
        if metrics is None:
            return Response.html(200, layout("Auswertung",
                                             '<h1>Auswertung</h1><p>Noch keine Metrikerfassung verfügbar.</p>'))
        try:
            params: dict[str, Any] = dict(self.archive.parameters(request))
            stage = params.pop("stage", "total")
            sort = params.pop("sort", "duration")
            page = int(params.pop("page", "1"))
            if stage not in STAGES or sort not in SORTS or not 1 <= page <= 10_000:
                raise ValueError("Unbekannte Auswahl")
            selected, _ = self._report(params)
            steps = stage_report(selected.stages, **{key: params[key] for key in ("days", "mode", "since", "until")
                                                     if key in params})
        except (ValueError, TypeError):
            return self.site._reply(request, 422, "Ungültige Auswertungsfilter.")
        views = self.site.views

        def subject(mail_id: str) -> str | None:
            mail = views.mail(mail_id)
            return mail.subject if mail is not None else None
        html = stage_page(stage, params, sort, page, steps, self.site.configured_timezone, subject, MODE_LABELS)
        return Response.html(200, layout(title(stage), html, active="/auswertung"))

    def statistics(self, request: Request, session: WebSession) -> Response:
        metrics = self.archive.metrics
        if metrics is None:
            return Response.html(200, layout("Auswertung",
                                             '<h1>Auswertung</h1><p>Noch keine Metrikerfassung verfügbar.</p>'))
        try:
            params: dict[str, Any] = dict(self.archive.parameters(request))
            selected, report = self._report(params)
        except (ValueError, TypeError):
            return self.site._reply(request, 422, "Ungültige Auswertungsfilter.")
        everything = selected.report(days=params["days"], mode=params["mode"])["records"]
        from ..runtime.stage_metrics import report as stage_report
        steps = stage_report(selected.stages, **{key: params[key] for key in
                                                 ("days", "mode", "stage", "since", "until") if key in params})
        return Response.html(200, layout("Auswertung", statistics_page(params, report, everything,
                                                                         self.site.configured_timezone, steps=steps),
                                         active="/auswertung"))
