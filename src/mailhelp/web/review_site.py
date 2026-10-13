"""Dedicated routes with unchanged authentication and response contracts."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .auth import WebSession
from .http import Request, Response

if TYPE_CHECKING:
    from .site import MailhelpSite
import re
from dataclasses import replace
from urllib.parse import parse_qs, quote

from .actions import proposal_actions, relevance_actions, result_kind
from .pages import error_page
from .review_pages import detail_page, mail_page, overview_page


class ReviewSite:
    def __init__(self, site: MailhelpSite):
        self.site = site

    def home(self, request: Request, session: WebSession) -> Response:
        csrf = self.site.auth.csrf_token(session.id)
        message, kind = self._result_notice(request, session)
        from .filters import FILTERS, chips, matches
        selected = parse_qs(request.query).get("filter", [""])[0]
        if selected not in FILTERS:
            return Response.text(422, "Ungültiger Filter.")
        overview = self.site.views.overview()
        def include(view):
            mail = self.site.views.mail(view.mail_id)
            return matches(selected, [view.card.kind.value], [view.status.value],
                           mail.extracted_attachments if mail else ())
        overview = replace(overview, open=tuple(view for view in overview.open if include(view)),
                           relevance=overview.relevance if selected in {"", "clarification"} else ())
        # The day's summary reads the history; only the finished, unfiltered state needs it.
        finished = not overview.open and not overview.relevance and not selected
        page = overview_page(overview, actions=proposal_actions(csrf),
                             relevance_actions=relevance_actions(csrf),
                             message=message, message_kind=kind, before=chips("/offen", selected),
                             empty=self.site.experience.inbox_zero() if finished else None)
        return Response.html(200, page)

    def _result_notice(self, request: Request, session: WebSession) -> tuple[str | None, str]:
        """The result of the action this browser just finished (?ergebnis=<id>)."""
        entry_id = parse_qs(request.query, max_num_fields=5).get("ergebnis", [""])[0] \
            if request.query else ""
        entry = self.site.commands.get(entry_id) if re.fullmatch(r"[a-f0-9]{32}", entry_id) else None
        if entry is None or entry.result is None or entry.command.actor != f"web:{session.id}":
            return None, "ok"
        return entry.result.message, result_kind(entry.result.status)

    def mail(self, request: Request, session: WebSession, mail_id: str) -> Response:
        view = self.site.views.mail(mail_id)
        if view is None:
            return Response.html(404, error_page("Nicht gefunden", "Diese Mail ist nicht (mehr) vorhanden."))
        question = next((item for item in self.site.views.overview().relevance if item.mail_id == mail_id), None)
        csrf = self.site.auth.csrf_token(session.id)
        message, kind = self._result_notice(request, session)
        page = mail_page(view, question, relevance_actions(csrf),
                         sender_actions=self.site.senders.actions(mail_id, view.sender, csrf),
                         message=message, message_kind=kind,
                         after=self.site.experience.editor(mail_id, csrf) + self.site.archive.analysis(mail_id))
        return Response.html(200, page)

    def attachment(self, request, session, mail_id, index):
        from ..attachments import AttachmentCache
        mail = self.site.views.mail(mail_id)
        if mail is None or mail.text is None or not any(
                item.preview is not None and item.preview.index == int(index) for item in mail.extracted_attachments):
            return Response.text(404, "Anhang nicht vorhanden.")
        data = AttachmentCache(self.site.views.store).read(mail_id, int(index))
        if data is None:
            return Response.text(404, "Anhang nicht vorhanden.")
        return Response(200, data, "image/jpeg", headers={
            "Content-Security-Policy": "default-src 'none'",
            "X-Content-Type-Options": "nosniff"}, cache="private, max-age=3600")

    def original(self, request, session, mail_id, index):
        """The original document, only as a download and never rendered by the browser."""
        from ..attachments import AttachmentCache, download_name
        mail = self.site.views.mail(mail_id)
        found = (AttachmentCache(self.site.views.store).original(mail_id, int(index))
                 if mail is not None and mail.text is not None else None)
        if found is None:
            return Response.text(404, "Original nicht vorhanden.")
        original, data = found
        name, fallback = download_name(original.filename, original.index)
        self.site.logger.event("INFO", "web", "attachment_downloaded", mail_id=mail_id, index=original.index,
                               size_bytes=len(data))
        return Response(200, data, original.content_type, headers={
            "Content-Disposition": f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(name, safe='')}",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "X-Content-Type-Options": "nosniff"}, cache="private, no-store")

    def detail(self, request: Request, session: WebSession, mail_id: str,
               proposal_id: str) -> Response:
        view = self.site.views.proposal(mail_id, proposal_id)
        if view is None:
            return Response.html(404, error_page(
                "Nicht gefunden", "Dieser Vorschlag ist nicht (mehr) vorhanden."))
        link = f'<p><a class="button" href="/vorschlag/{mail_id}/{proposal_id}/bearbeiten">Felder bearbeiten</a></p>'
        from .review_pages import disclosure
        extra = (link + self.site.experience.editor(mail_id, self.site.auth.csrf_token(session.id))
                 + disclosure("Revisionshistorie &amp; Differenzen", self.site.archive.revisions(mail_id, proposal_id))
                 + disclosure("Technische LLM-Analyse &amp; Metriken", self.site.archive.analysis(mail_id)))
        page = detail_page(view, actions=proposal_actions(self.site.auth.csrf_token(session.id)),
                           mail=self.site.views.mail(mail_id), after=extra)
        return Response.html(200, page)
