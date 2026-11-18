"""Search over stored mails and the stored analysis of one mail."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .. import state_names
from ..domain.mail import MailState
from ..i18n import heading, msg, tr
from ..persistence.archive import AnalysisSnapshot
from ..persistence.storage import CorruptState
from ..review.consistency import hints
from ..review.error_reporting import error_report, retry_pending
from ..review.explanation import explain
from ..review.queries import ArchiveQuery
from .actions import failure_forms, result_kind
from .archive_pages import analysis_section, mail_list_page, processing_path_section, revisions_list
from .auth import WebSession
from .failure_batch import batch_links
from .http import Request, Response
from .pages import e, layout, notice

if TYPE_CHECKING:
    from .archive_site import ArchiveSite


def _batch_result(queued: str, total: str) -> str:
    """7.3.3: how many mails a batch action queued; the rest had changed or were handled meanwhile."""
    if not (queued.isdigit() and total.isdigit()):
        return ""
    skipped = int(total) - int(queued)
    text = tr("{p0} Mails eingereiht.", p0=f"{queued}") + (
        tr(" {p0} übersprungen (bereits eingereiht oder inzwischen geändert).", p0=skipped) if skipped > 0 else ""
    )
    return notice(text, "ok" if skipped <= 0 else "info")


class MailArchiveSite:
    def __init__(self, archive: ArchiveSite) -> None:
        self.archive, self.site = archive, archive.site
        self.site.app.route("GET", "/mails", self.site.signed_in(self.mails))

    def mails(self, request: Request, session: WebSession) -> Response:
        queries = self.archive.queries
        try:
            parameters = self.archive.parameters(request)
            result = self._result(parameters.pop("ergebnis", ""), session) + _batch_result(
                parameters.pop("eingereiht", ""), parameters.pop("von", ""))
            query = ArchiveQuery.model_validate(parameters)
        except ValueError:
            return self.site._reply(request, 422, msg("Ungültige Suche oder Filter."))
        items, total = queries.search(query)
        topics = sorted({topic for item in queries.items() for topic in item["topics"]})
        if query.state == "failed":
            result += batch_links(items)
        page = mail_list_page(query, items, total, queries.damaged, topics, self.site.configured_timezone,
                              queries.mailboxes, self.site.auth.csrf_token(session.id), result=result)
        # 7.9.2: sign-in problems above the mail list; the page reloads only when they change.
        connections, digest = self.site.connection_state()
        return Response.html(200, layout(heading("Mails"), page, active="/mails", before=connections,
                                         fingerprint=digest, state_url="/api/stand?seite=verbindungen"))

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
            return notice(tr("Analyse beschädigt; bitte Protokolle prüfen."), "error")
        if state is None:
            return ""
        controls = ""
        if state.processing_filed:
            controls = notice(tr("Nicht verarbeitet – bewusst abgelegt."), "info")
        elif state.error is not None:
            controls = tr(
                "<p>Diese Mail hat einen Verarbeitungsfehler; Ursache und Aktionen stehen oben im Fehlerbericht.</p>"
            )
        return controls + analysis_section(mail_id, state, record)

    def failure_card(self, mail_id: str, subject: str, csrf: str) -> str:
        """7.3.2: cause, advice and actions of a failed mail at the top of its page; the full report
        opens below and can be copied. Works without JavaScript; the list's "Details" opens it as a dialog."""
        try:
            state = self.site.views.store.peek_model(state_names.mail(mail_id), MailState)
        except CorruptState:
            return ""  # the analysis section below names the damaged state
        report = error_report(state, subject, self.site.configured_timezone) if state is not None else None
        if state is None or report is None:
            return ""
        facts = [
            (msg("Betroffener Schritt"), report.stage_label),
            ("Fehlerursache", f"{report.label}. {report.explanation}"),
            ("Empfehlung", report.advice),
            (msg("Wiederholung"), report.retry),
            (msg("Fehler aufgetreten"), report.occurred),
            ("Erster Fehlversuch", report.first_failed),
            (msg("Letzter Versuch"), report.last_failed),
        ]
        facts += [("Feldpfade", ", ".join(report.paths))] if report.paths else []
        facts += [(msg("Modellaufrufe"), ", ".join(report.call_ids))] if report.call_ids else []
        rows = "".join(f"<dt>{e(name)}</dt><dd>{e(value)}</dd>" for name, value in facts)
        actions = failure_forms(csrf, state.id, state.analysis_round,
                                retryable=not state.missing_analysis_steps and not retry_pending(state))
        return tr(
            (
                '<section class="card error-card" id="fehlerbericht" '
                'aria-labelledby="fehlerbericht-titel"><h2 '
                'id="fehlerbericht-titel">Verarbeitungsfehler</h2><p>{p0} – '
                "Stufe: {p1}. {p2}</p>{p3}<details "
                'class="error-report"><summary>Fehlerbericht '
                'anzeigen</summary><dl class="facts">{p4}</dl><div '
                'class="report-box"><textarea readonly rows="8" '
                'aria-label="Fehlerbericht als Text">{p5}</textarea><button '
                'class="button small" type="button" data-copy-report>Bericht '
                'kopieren</button><p class="meta" role="status" '
                "data-copy-status></p></div></details></section>"
            ),
            p0=e(report.label),
            p1=e(report.stage_label),
            p2=e(report.retry),
            p3=actions,
            p4=rows,
            p5=e(report.text()),
        )

    def processing_path(self, mail_id: str) -> str:
        """5.1.1: the stored processing path of a mail, explained without a model call."""
        store = self.site.views.store
        try:
            state = store.peek_model(state_names.mail(mail_id), MailState)
            snapshot = store.peek_model(f"analysis-{mail_id}", AnalysisSnapshot)
        except CorruptState:
            return notice(tr("Verarbeitungsweg beschädigt; bitte Protokolle prüfen."), "error")
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
