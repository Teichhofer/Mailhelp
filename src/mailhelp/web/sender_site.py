"""Ignored senders in the web interface (1.4).

A mail's sender can be ignored or allowed again from its page, and the whole
list is managed under ``/einstellungen/ignorierte-absender``.  Every change is
an idempotent :class:`AdminCommand` executed by the main thread; the next mail
from an ignored sender is sorted out before any LLM call.
"""
from __future__ import annotations

import secrets

from ..configuration import AdminCommand, AdminKind, SenderChange
from ..domain.relevance import IrrelevantSenders
from ..sender_filter import is_irrelevant_sender, sender_addresses, sender_entry
from .http import Request, Response
from .pages import e, layout, notice

LIST_PATH = "/einstellungen/ignorierte-absender"


def action_form(action: str, csrf: str, label: str, style: str = "button small", body: str = "",
                **hidden: str) -> str:
    fields = {"csrf": csrf, "key": secrets.token_hex(16), **hidden}
    inputs = "".join(f'<input type="hidden" name="{e(name)}" value="{e(value)}">'
                     for name, value in fields.items())
    return (f'<form method="post" action="{e(action)}" class="inline-form">{inputs}{body}'
            f'<button class="{style}">{e(label)}</button></form>')


def sender_actions(mail_id: str, sender: str, blocked: IrrelevantSenders, csrf: str) -> str:
    """Badge and button next to the sender of one mail."""
    addresses = sorted(sender_addresses(sender))
    if not addresses:
        return '<p class="meta">Keine Absenderadresse erkennbar.</p>'
    if set(addresses) & set(blocked.addresses):
        content = ('<span class="badge danger">Absender wird ignoriert</span>'
                   + action_form(f"/mail/{mail_id}/absender-zulassen", csrf, "Absender wieder zulassen"))
    elif is_irrelevant_sender(sender, blocked):
        content = ('<span class="badge danger">Domain wird ignoriert</span> '
                   f'<a href="{LIST_PATH}">Liste verwalten</a>')
    else:
        content = (action_form(f"/mail/{mail_id}/absender-ignorieren", csrf, "🚫 Absender ignorieren",
                               "button small danger")
                   + f'<p class="meta">Neue Mails von {e(", ".join(addresses))} werden dann ohne '
                     "KI-Aufruf und ohne Benachrichtigung aussortiert.</p>")
    return f'<div class="sender-actions">{content}</div>'


def senders_page(blocked: IrrelevantSenders, csrf: str, message: str | None = None,
                 message_kind: str = "ok") -> str:
    entries = ([(address, "Adresse") for address in blocked.addresses]
               + [(domain, "Domain") for domain in blocked.domains])
    body = '<p><a href="/einstellungen">← Einstellungen</a></p><h1>Ignorierte Absender</h1>'
    if message:
        body += notice(message, message_kind)
    body += ('<p>Mails dieser Adressen und Domains werden vor jedem KI-Aufruf als irrelevant '
             "aussortiert, ohne Benachrichtigung. Eine Domain umfasst alle ihre Adressen.</p>")
    field = ('<label>Adresse oder Domain<input type="text" name="eintrag" maxlength="320" required '
             'autocomplete="off" placeholder="newsletter@example.com oder example.com"></label>')
    body += ('<h2>Hinzufügen</h2>'
             + action_form(LIST_PATH, csrf, "Ignorieren", "button", field).replace(
                 'class="inline-form"', 'class="stack"', 1))
    body += f"<h2>Liste ({len(entries)})</h2>"
    if not entries:
        return body + '<p class="empty">Derzeit wird kein Absender ignoriert.</p>'
    items = "".join(
        f'<li><span class="sender-entry">{e(entry)}</span><span class="badge accent">{kind}</span>'
        + action_form(f"{LIST_PATH}/entfernen", csrf, "Entfernen", eintrag=entry) + "</li>"
        for entry, kind in entries)
    return body + f'<ul class="sender-list">{items}</ul>'


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


__all__ = ["LIST_PATH", "SenderSite", "action_form", "sender_actions", "senders_page"]
