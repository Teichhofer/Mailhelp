"""Authenticated proposal evaluation site under /lernen/vorschlaege (Planung 6.5, 3.1, 3.3)."""
from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

from .. import state_names
from ..config.configuration import AdminCommand, AdminKind, ConfigurationService, SenderChange, file_hash
from ..domain.mail import MailState
from ..mailbox.sender_filter import sender_addresses
from ..review.proposal_evaluation import (
    ACCEPTED_STATUSES,
    dismiss_learning_run_hint,
    dismiss_sender_hint,
    evaluate_proposals,
    get_learning_run_hint,
    list_dismissed_sender_hints,
    restore_sender_hint,
    sender_hint_for_sender,
    sender_hints,
)
from .actions import new_key
from .http import Request, Response
from .pages import error_page, layout
from .proposal_evaluation_pages import learning_run_hint_banner, proposal_evaluation_page, sender_hint_page


class ProposalEvaluationSite:
    def __init__(self, site: Any) -> None:
        self.site = site
        site.app.route("GET", "/lernen/vorschlaege", site.signed_in(self.home))
        site.app.route("GET", "/lernen/absender-hinweis", site.signed_in(self.sender_hint_preview))
        site.app.route("POST", "/lernen/absender-hinweis/uebernehmen", site.signed_in(self.apply_sender_filter))
        site.app.route("POST", "/lernen/absender-hinweis/nicht-mehr-vorschlagen", site.signed_in(self.dismiss_sender))
        site.app.route("POST", "/lernen/absender-hinweis/wieder-zulassen", site.signed_in(self.restore_sender))
        site.app.route("POST", "/lernen/hinweis-ausblenden", site.signed_in(self.dismiss_learning_hint))

    @property
    def configuration(self) -> ConfigurationService | None:
        return getattr(self.site.archive, "configuration", None)

    def home(self, request: Request, session: Any) -> Response:
        query = parse_qs(request.query)
        try:
            days = int(query.get("days", ["0"])[0])
        except (ValueError, TypeError):
            days = 0

        params = {
            "days": days,
            "sort_topic": query.get("sort_topic", ["decided"])[0],
            "sort_sender": query.get("sort_sender", ["rejected"])[0],
        }
        store = self.site.views.store
        report = evaluate_proposals(store, days=days)
        cfg = self.configuration
        l_cfg = getattr(cfg.active, "learning", None) if cfg and hasattr(cfg, "active") else None
        hints_kwargs = {}
        run_hints_kwargs = {}
        if l_cfg is not None:
            hints_kwargs = {
                "enabled": l_cfg.sender_hints_enabled,
                "days": l_cfg.sender_hint_days,
                "min_proposals": l_cfg.sender_hint_min_proposals,
                "max_acceptance_rate": l_cfg.sender_hint_max_acceptance_rate,
            }
            run_hints_kwargs = {
                "enabled": l_cfg.learning_run_hints_enabled,
                "min_rejections": l_cfg.learning_run_hint_rejections,
            }
        hints = sender_hints(store, self.configuration, **hints_kwargs)
        dismissed = list_dismissed_sender_hints(store)
        csrf = self.site.auth.csrf_token(session.id)
        html = proposal_evaluation_page(report, params, hints=hints, dismissed=dismissed, csrf=csrf)

        learning_hint = get_learning_run_hint(store, **run_hints_kwargs)
        if learning_hint:
            html = learning_run_hint_banner(learning_hint, csrf) + html

        return Response.html(200, layout("Vorschläge", html, active="/lernen"))

    def sender_hint_preview(self, request: Request, session: Any) -> Response:
        query = parse_qs(request.query)
        sender = query.get("sender", [""])[0]
        if not sender:
            return Response.html(404, error_page("Nicht gefunden", "Kein Absender angegeben."))

        store = self.site.views.store
        cfg = self.configuration
        l_cfg = getattr(cfg.active, "learning", None) if cfg and hasattr(cfg, "active") else None
        hints_kwargs = {}
        if l_cfg is not None:
            hints_kwargs = {
                "days": l_cfg.sender_hint_days,
                "min_proposals": l_cfg.sender_hint_min_proposals,
                "max_acceptance_rate": l_cfg.sender_hint_max_acceptance_rate,
            }
        hint = sender_hint_for_sender(store, sender, self.configuration, **hints_kwargs)
        if hint is None:
            return Response.html(404, error_page("Nicht gefunden", f"Kein Hinweis für Absender „{sender}“ gefunden."))

        # Collect stored mails from this sender
        mails: list[dict[str, Any]] = []
        target_addresses = sender_addresses(sender)
        for name in store.names(state_names.MAIL_PREFIX):
            try:
                mail = store.load_model(name, MailState)
            except Exception:
                continue
            if mail is None:
                continue
            mail_sender = (mail.display_headers.sender if mail.display_headers and mail.display_headers.sender
                           else (mail.mail.get("headers", {}).get("from") or mail.mail.get("headers", {}).get("sender") or "")
                           if mail.mail and isinstance(mail.mail.get("headers"), dict) else "")
            if not (mail_sender == sender or (target_addresses and sender_addresses(mail_sender) & target_addresses)):
                continue

            mail_proposals = []
            for p in mail.proposals:
                is_acc = p.status in ACCEPTED_STATUSES
                mail_proposals.append({
                    "id": p.id,
                    "title": p.title,
                    "is_accepted": is_acc,
                    "status": p.status.value,
                })

            date_str = mail.created_at.strftime("%d.%m.%Y") if mail.created_at else "—"
            subject = mail.display_headers.subject if mail.display_headers else "Ohne Betreff"
            mails.append({
                "id": mail.id,
                "subject": subject,
                "date": date_str,
                "proposals": mail_proposals,
            })

        csrf = self.site.auth.csrf_token(session.id)
        expected_hash = None
        if self.configuration is not None:
            path = self.configuration.directory / "irrelevant-senders.json"
            if path.exists():
                expected_hash = file_hash(path)

        html = sender_hint_page(hint, mails, csrf, expected_hash)
        return Response.html(200, layout(f"Absender: {sender}", html, active="/lernen"))

    def apply_sender_filter(self, request: Request, session: Any, form: dict[str, str]) -> Response:
        if self.configuration is None:
            return self.site._reply(request, 503, "Absenderverwaltung nicht verfügbar.")
        sender = form.get("sender", "")
        addresses = sorted(sender_addresses(sender))
        if not addresses:
            return self.site._reply(request, 422, "Keine gültige E-Mail-Adresse für den Absender gefunden.")
        expected_hash = form.get("expected_hash") or None
        change = SenderChange(action="add", addresses=addresses)
        try:
            command = AdminCommand(kind=AdminKind.SENDERS, actor=f"web:{session.id}",
                                   idempotency_key=form.get("key", new_key()),
                                   expected_hash=expected_hash,
                                   patch=change.model_dump(exclude_none=True), acknowledged=True)
        except ValueError:
            return self.site._reply(request, 422, "Die Aktion ist unvollständig oder ungültig.")
        return self.site.archive.queue(request, command)

    def dismiss_sender(self, request: Request, session: Any, form: dict[str, str]) -> Response:
        sender = form.get("sender", "")
        if sender:
            dismiss_sender_hint(self.site.views.store, sender)
        return Response.redirect("/lernen/vorschlaege")

    def restore_sender(self, request: Request, session: Any, form: dict[str, str]) -> Response:
        sender = form.get("sender", "")
        if sender:
            restore_sender_hint(self.site.views.store, sender)
        return Response.redirect("/lernen/vorschlaege")

    def dismiss_learning_hint(self, request: Request, session: Any, form: dict[str, str]) -> Response:
        dismiss_learning_run_hint(self.site.views.store)
        return Response.redirect("/lernen")
