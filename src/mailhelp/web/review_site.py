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

from ..processing.mail_recheck import recheck_round
from ..review.views import ProposalView
from .actions import recheck_form, relevance_actions, result_kind
from .pages import error_page
from .review_pages import detail_page, mail_page, overview_page


class ReviewSite:
    def __init__(self, site: MailhelpSite):
        self.site = site

    def home(self, request: Request, session: WebSession) -> Response:
        csrf = self.site.auth.csrf_token(session.id)
        message, kind = self._result_notice(request, session)
        from ..review.filters import FILTERS, matches
        from .filters import chips
        selected = parse_qs(request.query).get("filter", [""])[0]
        if selected not in FILTERS:
            return Response.text(422, "Ungültiger Filter.")
        overview = self.site.overview()
        def include(view: ProposalView) -> bool:
            # Only the attachment filter needs the mail; reading it for every card cost ~1 ms each.
            mail = self.site.views.mail(view.mail_id) if selected == "attachments" else None
            return matches(selected, [view.card.kind.value], [view.status.value],
                           mail.extracted_attachments if mail else ())
        overview = replace(overview, open=tuple(view for view in overview.open if include(view)),
                           relevance=overview.relevance if selected in {"", "clarification"} else ())
        # The day's summary reads the history; only the finished, unfiltered state needs it.
        finished = not overview.open and not overview.relevance and not selected
        from .command_cards import CommandCards
        cards = CommandCards(self.site.commands._entries(), csrf)
        references = {(view.mail_id, view.proposal_id) for view in overview.open}
        references.update((view.mail_id, None) for view in overview.relevance)
        from .pages import notice
        damaged = len(tuple((self.site.commands.incoming.directory / "quarantine").glob("*.invalid")))
        warning = notice("Beschädigte Web-Eingaben wurden isoliert. Bitte die Protokolle prüfen.", "error") if damaged else ""
        page = overview_page(overview, actions=cards.proposal,
                             relevance_actions=cards.relevance,
                             message=message, message_kind=kind, before=warning + chips("/offen", selected),
                             empty=self.site._empty if finished else None,
                             after=cards.detached(references))
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
        analysis_round = recheck_round(self.site.views.store, mail_id)
        recheck = (f'<section class="card"><h2>Aussortiert</h2><p>Mailhelp hat diese Mail als nicht relevant '
                   f'eingestuft. Nach einer Änderung der Themen kann sie mit der aktuellen Konfiguration erneut '
                   f'geprüft werden; das Ergebnis erscheint nach dem nächsten Abruf.</p>'
                   f'{recheck_form(csrf, mail_id, analysis_round)}</section>'
                   if analysis_round is not None else "")
        page = mail_page(view, question, relevance_actions(csrf), recheck=recheck,
                         sender_actions=self.site.senders.actions(mail_id, view.sender, csrf),
                         message=message, message_kind=kind,
                         after=self.site.reconciliation_page.mail_summary(mail_id)
                         + self.site.experience.editor(mail_id, csrf)
                         + self.site.archive.mail_archive.analysis(mail_id))
        return Response.html(200, page)

    def attachment(self, request: Request, session: WebSession, mail_id: str, index: str) -> Response:
        from ..processing.attachments import AttachmentCache
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

    def original(self, request: Request, session: WebSession, mail_id: str, index: str) -> Response:
        """The original document, only as a download and never rendered by the browser."""
        from ..processing.attachments import AttachmentCache, download_name
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
        from ..domain.proposal_sources import ProposalReference
        from ..storage import CorruptState
        try:
            proposal = self.site.reconciliation_page.service.resolve(
                ProposalReference(mail_id=mail_id, proposal_id=proposal_id))
        except (ValueError, CorruptState):
            return self.site._reply(request, 409, "Ungültige kanonische Vorschlagsreferenz.")
        if proposal is not None and (proposal.source_mail_id, proposal.id) != (mail_id, proposal_id):
            return Response.redirect(f"/vorschlag/{proposal.source_mail_id}/{proposal.id}")
        view = self.site.views.proposal(mail_id, proposal_id)
        if view is None:
            return Response.html(404, error_page(
                "Nicht gefunden", "Dieser Vorschlag ist nicht (mehr) vorhanden."))
        link = f'<p><a class="button" href="/vorschlag/{mail_id}/{proposal_id}/bearbeiten">Felder bearbeiten</a></p>'
        from .review_pages import disclosure
        archive = self.site.archive.mail_archive
        extra = (link + self.site.reconciliation_page.fragment(mail_id, proposal_id)
                 + (self.site.mailbox_page.target_forms(proposal, session) if proposal is not None else "")
                 + self.site.experience.editor(mail_id, self.site.auth.csrf_token(session.id))
                 + disclosure("Revisionshistorie &amp; Differenzen", archive.revisions(mail_id, proposal_id))
                 + disclosure("Technische LLM-Analyse &amp; Metriken", archive.analysis(mail_id)))
        from .command_cards import CommandCards
        cards = CommandCards(self.site.commands._entries(), self.site.auth.csrf_token(session.id))
        page = detail_page(view, actions=cards.proposal,
                           mail=self.site.views.mail(mail_id), after=extra)
        return Response.html(200, page)
