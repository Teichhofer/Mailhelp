"""Search over stored mails and the stored analysis of one mail."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .. import state_names
from ..domain.mail import MailState
from ..persistence.archive import AnalysisSnapshot
from ..persistence.storage import CorruptState
from ..review.consistency import hints
from ..review.explanation import explain
from ..review.queries import ArchiveQuery
from .actions import failure_forms, result_kind
from .archive_pages import analysis_section, mail_list_page, processing_path_section, revisions_list
from .auth import WebSession
from .http import Request, Response
from .pages import layout, notice

if TYPE_CHECKING:
    from .archive_site import ArchiveSite


class MailArchiveSite:
    def __init__(self, archive: ArchiveSite) -> None:
        self.archive, self.site = archive, archive.site
        self.site.app.route("GET", "/mails", self.site.signed_in(self.mails))

    def mails(self, request: Request, session: WebSession) -> Response:
        queries = self.archive.queries
        try:
            parameters = self.archive.parameters(request)
            result = self._result(parameters.pop("ergebnis", ""), session)
            query = ArchiveQuery.model_validate(parameters)
        except ValueError:
            return self.site._reply(request, 422, "Ungültige Suche oder Filter.")
        items, total = queries.search(query)
        topics = sorted({topic for item in queries.items() for topic in item["topics"]})
        page = mail_list_page(query, items, total, queries.damaged, topics, self.site.configured_timezone,
                              queries.mailboxes, self.site.auth.csrf_token(session.id), result=result)
        return Response.html(200, layout("Mails", page, active="/mails"))

    def _result(self, entry_id: str, session: WebSession) -> str:
        """7.3: the result of this browser's action from the failure list (?ergebnis=<id>)."""
        entry = self.site.commands.get(entry_id) if re.fullmatch(r"[a-f0-9]{32}", entry_id) else None
        if entry is None or entry.result is None or entry.command.actor != f"web:{session.id}":
            return ""
        return notice(entry.result.message, result_kind(entry.result.status))

    def analysis(self, mail_id: str) -> str:
        store = self.site.views.store
        try:
            state = store.peek_model(state_names.mail(mail_id), MailState)
            snapshot = store.peek_model(f"analysis-{mail_id}", AnalysisSnapshot)
            record = snapshot.model_dump(mode="json") if snapshot is not None else {}
        except CorruptState:
            return notice("Analyse beschädigt; bitte Protokolle prüfen.", "error")
        if state is None:
            return ""
        controls = ""
        if state.processing_filed:
            controls = notice("Nicht verarbeitet – bewusst abgelegt.", "info")
        elif state.error is not None:
            controls = '<p>Diese Mail hat einen Verarbeitungsfehler.</p>'
        return controls + analysis_section(mail_id, state, record)

    def analysis_actions(self, mail_id: str, csrf: str) -> str:
        state = self.site.views.store.peek_model(state_names.mail(mail_id), MailState)
        if state is None or state.error is None or state.processing_filed:
            return ""
        return failure_forms(csrf, state.id, state.analysis_round, retryable=not state.missing_analysis_steps)

    def processing_path(self, mail_id: str) -> str:
        """5.1.1: the stored processing path of a mail, explained without a model call."""
        store = self.site.views.store
        try:
            state = store.peek_model(state_names.mail(mail_id), MailState)
            snapshot = store.peek_model(f"analysis-{mail_id}", AnalysisSnapshot)
        except CorruptState:
            return notice("Verarbeitungsweg beschädigt; bitte Protokolle prüfen.", "error")
        if state is None:
            return ""
        topics = snapshot.topics if snapshot is not None else {}
        return processing_path_section(explain(state), topics, hints(state))

    def revisions(self, mail_id: str, proposal_id: str) -> str:
        """Recorded events of one proposal with links to every stored version."""
        rows = sorted((row for row in self.archive.queries.history_of(mail_id)
                       if row["proposal_id"] == proposal_id),
                      key=lambda row: row["at"], reverse=True)
        return revisions_list(mail_id, proposal_id, rows, self.site.configured_timezone)
