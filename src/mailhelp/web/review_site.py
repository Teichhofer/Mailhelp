"""Dedicated routes with unchanged authentication and response contracts."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..domain.proposal_sources import ProposalReference
from ..persistence.storage import CorruptState
from ..processing.attachments import AttachmentCache, download_name
from ..review import CommandKind
from ..review.filters import matches
from ..review.proposal_evaluation import get_learning_run_hint, sender_hint_for_sender
from . import open_toolbar as tools
from .actions import confirm_remove_page
from .auth import WebSession
from .command_cards import CommandCards
from .http import Request, Response
from .pages import notice
from .proposal_evaluation_pages import learning_run_hint_banner
from .review_pages import disclosure

if TYPE_CHECKING:
    from .site import MailhelpSite
import re
from dataclasses import replace
from urllib.parse import parse_qs, quote

from ..processing.mail_recheck import recheck_round
from ..review.proposal_evaluation import SenderHint
from ..review.views import ProposalView
from .actions import recheck_form, relevance_actions, result_kind
from .pages import error_page
from .review_pages import detail_page, mail_page, overview_page


def refresh_target(request: Request) -> str:
    """The current page without its fragment, for the reload fallback without JavaScript."""
    # Browsers never send a fragment; tolerate clients that do.
    return (request.path + (f"?{request.query}" if request.query else "")).split("#", 1)[0]


class ReviewSite:
    def __init__(self, site: MailhelpSite):
        self.site = site

    def home(self, request: Request, session: WebSession) -> Response:
        csrf = self.site.auth.csrf_token(session.id)
        try:
            choice = tools.parse(request.query)
        except ValueError:
            return Response.text(422, "Ungültiger Filter.")
        selected = choice.filter
        overview = self.site.overview()
        total = len(overview.open) + len(overview.relevance)
        def include(view: ProposalView) -> bool:
            # Only the attachment filter needs the mail; reading it for every card cost ~1 ms each.
            mail = self.site.views.mail(view.mail_id) if selected == "attachments" else None
            return matches(selected, [view.card.kind.value], [view.status.value],
                           mail.extracted_attachments if mail else ())
        overview = replace(overview, open=tuple(view for view in overview.open if include(view)),
                           relevance=overview.relevance if selected in {"", "clarification"} else ())
        # 6.0.6: search, then sort; the tool row only changes what is shown.
        overview = replace(overview,
                           open=tools.ordered(tools.search_open(overview.open, choice.q), choice.sort),
                           relevance=tools.ordered(tools.search_relevance(overview.relevance, choice.q),
                                                   choice.sort))
        # The day's summary reads the history; only the finished, unfiltered state needs it.
        finished = not overview.open and not overview.relevance and not choice.narrowed
        hint_cache: dict[tuple[int, int, float], list[SenderHint]] = {}
        cards = CommandCards(self.site.commands._entries(), csrf, refresh_target(request),
                             sender_hint_lookup=lambda mail_id: self._sender_hint(mail_id, hint_cache),
                             views=self.site.views)
        references: set[tuple[str, str | None]] = {(view.mail_id, view.proposal_id) for view in overview.open}
        references.update((view.mail_id, None) for view in overview.relevance)
        damaged = len(tuple((self.site.commands.incoming.directory / "quarantine").glob("*.invalid")))
        warning = (notice("Beschädigte Web-Eingaben wurden isoliert. Bitte die Protokolle prüfen.", "error")
                   if damaged else "")
        cfg = getattr(self.site.archive, "configuration", None)
        l_cfg = getattr(cfg.active, "learning", None) if cfg and hasattr(cfg, "active") else None
        run_hints_enabled = l_cfg.learning_run_hints_enabled if l_cfg is not None else True
        min_rejections = l_cfg.learning_run_hint_rejections if l_cfg is not None else 20
        learning_hint = get_learning_run_hint(self.site.views.store, enabled=run_hints_enabled, min_rejections=min_rejections)
        hint_banner = learning_run_hint_banner(learning_hint, csrf) if learning_hint else ""
        # 4.4: every review result is shown on its card (or as "Deine Aktion"); no second
        # copy from ?ergebnis= on top, which would be announced twice.
        page = overview_page(overview, actions=cards.proposal,
                             relevance_actions=cards.relevance,
                             before=warning + hint_banner + tools.toolbar("/offen", choice),
                             empty=self.site._empty if finished else None,
                             after=cards.detached(references),
                             count=tools.count(len(overview.open) + len(overview.relevance), total, choice),
                             sections=tools.groups(overview.relevance, overview.open) if choice.group else None,
                             no_match=tools.NO_MATCH.format(path="/offen") if choice.narrowed else None)
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
                         + self.site.archive.mail_archive.processing_path(mail_id)
                         + (self.site.reanalysis_page.section(mail_id, csrf)
                            if self.site.reanalysis_page is not None else "")
                         + self.site.experience.editor(mail_id, csrf)
                         + self.site.archive.mail_archive.analysis(mail_id)
                         + self.site.archive.mail_archive.analysis_actions(mail_id, csrf))
        return Response.html(200, page)

    def attachment(self, request: Request, session: WebSession, mail_id: str, index: str) -> Response:
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
        archive = self.site.archive.mail_archive
        extra = (link + self.site.reconciliation_page.fragment(mail_id, proposal_id)
                 + (self.site.mailbox_page.target_forms(proposal, session) if proposal is not None else "")
                 + self.site.experience.editor(mail_id, self.site.auth.csrf_token(session.id))
                 + disclosure("Revisionshistorie &amp; Differenzen", archive.revisions(mail_id, proposal_id))
                 + disclosure("Technische LLM-Analyse &amp; Metriken", archive.analysis(mail_id)))
        cards = CommandCards(self.site.commands._entries(), self.site.auth.csrf_token(session.id),
                             refresh_target(request), sender_hint_lookup=self._sender_hint, views=self.site.views)
        page = detail_page(view, actions=cards.proposal,
                           mail=self.site.views.mail(mail_id), after=extra)
        return Response.html(200, page)

    def confirm_remove(self, request: Request, session: WebSession, mail_id: str,
                       proposal_id: str) -> Response:
        view = self.site.views.proposal(mail_id, proposal_id)
        if view is None or not view.can_remove:
            return Response.html(404, error_page(
                "Nicht möglich", "Dieser Eintrag kann nicht wieder entfernt werden."))
        csrf = self.site.auth.csrf_token(session.id)
        return Response.html(200, confirm_remove_page(view, csrf))

    def execute_remove(self, request: Request, session: WebSession, form: dict[str, str],
                       mail_id: str, proposal_id: str) -> Response:
        form = dict(form)
        form.setdefault("kind", CommandKind.REMOVE_CREATED.value)
        form.setdefault("mail_id", mail_id)
        form.setdefault("proposal_id", proposal_id)
        return self.site.act(request, session, form)

    def _sender_hint(self, mail_id: str,
                     request_cache: dict[tuple[int, int, float], list[SenderHint]] | None = None) -> Any:
        mail = self.site.views.mail(mail_id)
        if mail and mail.sender:
            cfg = getattr(self.site.archive, "configuration", None)
            l_cfg = getattr(cfg.active, "learning", None) if cfg and hasattr(cfg, "active") else None
            kwargs = {}
            if l_cfg is not None:
                kwargs = {
                    "days": l_cfg.sender_hint_days,
                    "min_proposals": l_cfg.sender_hint_min_proposals,
                    "max_acceptance_rate": l_cfg.sender_hint_max_acceptance_rate,
                }
            return sender_hint_for_sender(self.site.views.store, mail.sender, cfg,
                                           request_cache=request_cache, **kwargs)
        return None
