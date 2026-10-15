"""Ignored senders in the web interface (1.4).

A mail's sender can be ignored or allowed again from its page, and the whole
list is managed under ``/einstellungen/ignorierte-absender``.  Every change is
an idempotent :class:`AdminCommand` executed by the main thread; the next mail
from an ignored sender is sorted out before any LLM call.
"""
from __future__ import annotations

from ..configuration import AdminCommand, AdminKind, SenderChange
from ..sender_filter import sender_addresses, sender_entry
from .http import Request, Response
from .pages import layout
from .sender_pages import LIST_PATH, sender_actions, senders_page


class SenderSite:
    def __init__(self, site) -> None:
        self.site = site
        for method, path, handler in (
                ("POST", r"/mail/(?P<mail_id>[a-f0-9]{24})/absender-ignorieren", self.ignore),
                ("POST", r"/mail/(?P<mail_id>[a-f0-9]{24})/absender-zulassen", self.allow),
                ("GET", LIST_PATH, self.list),
                ("POST", LIST_PATH, self.add),
                ("POST", f"{LIST_PATH}/entfernen", self.remove)):
            site.app.route(method, path, site.signed_in(handler))

    @property
    def configuration(self):
        # Created after the web components, together with the main-thread services.
        return self.site.archive.configuration

    def actions(self, mail_id: str, sender: str, csrf: str) -> str:
        if self.configuration is None:
            return ""
        return sender_actions(mail_id, sender, self.configuration.blocked_senders(), csrf)

    def _submit(self, request: Request, session, form: dict[str, str], change: SenderChange) -> Response:
        try:
            command = AdminCommand(kind=AdminKind.SENDERS, actor=f"web:{session.id}",
                                   idempotency_key=form.get("key", ""),
                                   patch=change.model_dump(exclude_none=True), acknowledged=True)
        except ValueError:
            return self.site._reply(request, 422, "Die Aktion ist unvollständig oder ungültig.")
        return self.site.archive.queue(request, command)

    def _mail_change(self, request: Request, session, form: dict[str, str], mail_id: str,
                     action: str) -> Response:
        if self.configuration is None:
            return self.site._reply(request, 503, "Absenderverwaltung nicht verfügbar.")
        view = self.site.views.mail(mail_id)
        if view is None:
            return self.site._reply(request, 404, "Diese Mail ist nicht (mehr) vorhanden.")
        addresses = sorted(sender_addresses(view.sender))
        if not addresses:
            return self.site._reply(request, 422, "Die Mail hat keine gültige Absenderadresse.")
        return self._submit(request, session, form,
                            SenderChange(action=action, addresses=addresses, mail_id=mail_id))

    def ignore(self, request: Request, session, form: dict[str, str], mail_id: str) -> Response:
        return self._mail_change(request, session, form, mail_id, "add")

    def allow(self, request: Request, session, form: dict[str, str], mail_id: str) -> Response:
        return self._mail_change(request, session, form, mail_id, "remove")

    def list(self, request: Request, session) -> Response:
        if self.configuration is None:
            return self.site._reply(request, 503, "Absenderverwaltung nicht verfügbar.")
        message, kind = self.site.review._result_notice(request, session)
        page = senders_page(self.configuration.blocked_senders(), self.site.auth.csrf_token(session.id),
                            message, kind)
        return Response.html(200, layout("Ignorierte Absender", page, active="/einstellungen"))

    def _entry_change(self, request: Request, session, form: dict[str, str], action: str) -> Response:
        if self.configuration is None:
            return self.site._reply(request, 503, "Absenderverwaltung nicht verfügbar.")
        try:
            kind, value = sender_entry(form.get("eintrag", ""))
        except ValueError:
            return self.site._reply(request, 422, "Bitte eine gültige E-Mail-Adresse oder Domain angeben, "
                                                  "z. B. newsletter@example.com oder example.com.")
        change = SenderChange(action=action, **{"addresses" if kind == "address" else "domains": [value]})
        return self._submit(request, session, form, change)

    def add(self, request: Request, session, form: dict[str, str]) -> Response:
        return self._entry_change(request, session, form, "add")

    def remove(self, request: Request, session, form: dict[str, str]) -> Response:
        return self._entry_change(request, session, form, "remove")


__all__ = ["LIST_PATH", "SenderSite"]
