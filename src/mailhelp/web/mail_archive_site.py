"""Search over stored mails and the stored analysis of one mail."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .. import state_names
from ..models import MailState
from ..review.archive import AnalysisSnapshot
from ..review.queries import ArchiveQuery
from ..storage import CorruptState
from .archive_pages import analysis_section, mail_list_page, revisions_list
from .http import Response
from .pages import layout, notice

if TYPE_CHECKING:
    from .archive_site import ArchiveSite


class MailArchiveSite:
    def __init__(self, archive: ArchiveSite):
        self.archive, self.site = archive, archive.site
        self.site.app.route("GET", "/mails", self.site.signed_in(self.mails))

    def mails(self, request, session):
        queries = self.archive.queries
        try:
            query = ArchiveQuery.model_validate(self.archive.parameters(request))
        except ValueError:
            return self.site._reply(request, 422, "Ungültige Suche oder Filter.")
        items, total = queries.search(query)
        topics = sorted({topic for item in queries.items() for topic in item["topics"]})
        page = mail_list_page(query, items, total, queries.damaged, topics, self.site.configured_timezone,
                              queries.mailboxes)
        from .filters import chips
        page = chips("/mails", query.filter) + page
        return Response.html(200, layout("Mails", page, active="/mails"))

    def analysis(self, mail_id):
        store = self.site.views.store
        try:
            state = store.peek_model(state_names.mail(mail_id), MailState)
            snapshot = store.peek_model(f"analysis-{mail_id}", AnalysisSnapshot)
            record = snapshot.model_dump(mode="json") if snapshot is not None else {}
        except CorruptState:
            return notice("Analyse beschädigt; bitte Protokolle prüfen.", "error")
        if state is None:
            return ""
        return analysis_section(mail_id, state, record)

    def revisions(self, mail_id, proposal_id):
        """Recorded events of one proposal with links to every stored version."""
        rows = sorted((row for row in self.archive.queries.history()
                       if row["mail_id"] == mail_id and row["proposal_id"] == proposal_id),
                      key=lambda row: row["at"], reverse=True)
        return revisions_list(mail_id, proposal_id, rows)
