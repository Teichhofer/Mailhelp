"""HTML of the ignored-sender list and of the sender actions on a mail page."""
from __future__ import annotations

import secrets

from ..domain.relevance import IrrelevantSenders
from ..sender_filter import is_irrelevant_sender, sender_addresses
from .pages import e, notice

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


__all__ = ["LIST_PATH", "action_form", "sender_actions", "senders_page"]
