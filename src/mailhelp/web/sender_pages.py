"""HTML of the sender rules page and of the sender actions on a mail page (1.4, 7.7.3)."""
from __future__ import annotations

import secrets

from ..domain.relevance import HeaderPrefilter, IrrelevantSenders, PrefilterHits, RuleHits, SenderRule, SenderRules
from ..formatting import format_datetime_local
from ..i18n import tr
from ..mailbox.sender_filter import AUTOMATED, FREEMAIL, LISTS, HeaderFilter, prefilter, sender_addresses
from .pages import e, notice

LIST_PATH = "/einstellungen/absender"
# 7.7.3: the page of 1.4; it leads to the new page.
OLD_PATH = "/einstellungen/ignorierte-absender"
RULE_PATH = f"{LIST_PATH}/regel"
KIND_LABELS = {"address": "Adresse", "domain": "Domain", "pattern": "Muster", "subject": "Betreff"}
ACTION_LABELS = {"ignore": "Ignorieren", "vip": "VIP – immer relevant", "allow_only": "Nur Ausnahme"}


def action_form(action: str, csrf: str, label: str, style: str = "button small", body: str = "",
                **hidden: str) -> str:
    fields = {"csrf": csrf, "key": secrets.token_hex(16), **hidden}
    inputs = "".join(f'<input type="hidden" name="{e(name)}" value="{e(value)}">'
                     for name, value in fields.items())
    return (f'<form method="post" action="{e(action)}" class="inline-form">{inputs}{body}'
            f'<button class="{style}">{e(label)}</button></form>')


def sender_actions(mail_id: str, sender: str, blocked: IrrelevantSenders, csrf: str) -> str:
    """Badge and buttons next to the sender of one mail."""
    addresses = sorted(sender_addresses(sender))
    if not addresses:
        return f'<p class="meta">{tr("Keine Absenderadresse erkennbar.")}</p>'
    match = prefilter(sender, "", None, blocked)
    manage = f'<a href="{LIST_PATH}">{tr("Regeln verwalten")}</a>'
    if set(addresses) & set(blocked.addresses):
        content = (f'<span class="badge danger">{tr("Absender wird ignoriert")}</span>'
                   + action_form(f"/mail/{mail_id}/absender-zulassen", csrf, tr("Absender wieder zulassen")))
    elif match is not None and match.action == "vip":
        content = f'<span class="badge ok">⭐ {tr("VIP-Absender")}</span> {manage}'
    elif match is not None:
        legacy = any(address.rsplit("@", 1)[1] in blocked.domains for address in addresses)
        label = tr("Domain wird ignoriert") if legacy else tr("Wird durch eine Regel ignoriert")
        content = f'<span class="badge danger">{label}</span> {manage}'
    else:
        domains = sorted({address.rsplit("@", 1)[1] for address in addresses} - FREEMAIL)
        content = (action_form(f"/mail/{mail_id}/absender-ignorieren", csrf, "🚫 " + tr("Absender ignorieren"),
                               "button small danger")
                   + (action_form(f"/mail/{mail_id}/domain-ignorieren", csrf,
                                  "🌐 " + tr("Domain {domain} ignorieren", domain=domains[0]), "button small")
                      if len(domains) == 1 else "")
                   + action_form(f"/mail/{mail_id}/absender-vip", csrf, "⭐ " + tr("Als VIP einstufen"), "button small")
                   + '<p class="meta">' + tr("Neue Mails von {senders} werden dann ohne KI-Aufruf und ohne "
                                             "Benachrichtigung aussortiert.", senders=", ".join(addresses))
                   + " " + tr("Als VIP gelten sie ohne Relevanzprüfung als relevant; jeder Eintrag braucht "
                              "weiterhin deine Bestätigung.") + "</p>")
    return f'<div class="sender-actions">{content}</div>'


def _when(hits: RuleHits, zone: str) -> str:
    if hits.last is None:
        return tr("nie")
    return format_datetime_local(hits.last, zone)


def _rule_row(rule: SenderRule, hits: RuleHits, csrf: str, stand: str, zone: str) -> str:
    scope = tr("Postfach {number}", number=rule.mailbox) if rule.mailbox else tr("alle Postfächer")
    state = "" if rule.enabled else f' <span class="badge">{tr("aus")}</span>'
    switch = ("disable", tr("Ausschalten")) if rule.enabled else ("enable", tr("Einschalten"))
    meta = tr("{scope} · Treffer: {count} · zuletzt: {when}", scope=scope, count=hits.count, when=_when(hits, zone))
    note = f' · {e(rule.note)}' if rule.note else ""
    return (f'<li><span class="sender-entry">{e(rule.value)}</span>'
            f'<span class="badge accent">{tr(KIND_LABELS[rule.kind])}</span>{state}'
            f'<span class="meta">{meta}{note}</span>'
            + action_form(f"{RULE_PATH}/{switch[0]}", csrf, switch[1], stand=stand, regel=rule.id)
            + action_form(f"{RULE_PATH}/entfernen", csrf, tr("Entfernen"), stand=stand, regel=rule.id) + "</li>")


def _legacy_rows(blocked: IrrelevantSenders, hits: PrefilterHits, csrf: str, zone: str) -> list[str]:
    rows = []
    entries = [(item, "address") for item in blocked.addresses] + [(item, "domain") for item in blocked.domains]
    for value, kind in entries:
        count = hits.rules.get(SenderRule.identity(kind, value, None), RuleHits())
        meta = tr("alle Postfächer · Treffer: {count} · zuletzt: {when}", count=count.count, when=_when(count, zone))
        rows.append(f'<li><span class="sender-entry">{e(value)}</span>'
                    f'<span class="badge accent">{tr(KIND_LABELS[kind])}</span><span class="meta">{meta}</span>'
                    + action_form(f"{LIST_PATH}/entfernen", csrf, tr("Entfernen"), eintrag=value) + "</li>")
    return rows


def _exceptions(mailboxes: dict[str, SenderRules], csrf: str, stand: str) -> list[str]:
    return [f'<li><span class="sender-entry">{e(address)}</span>'
            f'<span class="meta">{tr("Postfach {number}", number=number)} · {tr("hebt nur die Sperre auf")}</span>'
            + action_form(f"{LIST_PATH}/ausnahme-vip", csrf, tr("Als VIP übernehmen"), stand=stand, postfach=number,
                          adresse=address) + "</li>"
            for number, scope in sorted(mailboxes.items(), key=lambda item: int(item[0])) for address in scope.allow]


def _section(title: str, explanation: str, rows: list[str], empty: str) -> str:
    items = f'<ul class="sender-list">{"".join(rows)}</ul>' if rows else f'<p class="empty">{empty}</p>'
    return f'<h2>{title} ({len(rows)})</h2><p class="meta">{explanation}</p>{items}'


def rule_form(csrf: str, stand: str, values: dict[str, str], preview: str | None, savable: bool) -> str:
    def options(labels: dict[str, str], chosen: str) -> str:
        return "".join(f'<option value="{key}"{" selected" if key == chosen else ""}>{tr(label)}</option>'
                       for key, label in labels.items())
    hint = tr("z. B. newsletter@shop.de, shop.de, no-reply@* oder einen Betreff")
    kinds = options(KIND_LABELS, values.get("art", "address"))
    actions = options(ACTION_LABELS, values.get("aktion", "ignore"))
    fields = (f'<label>{tr("Art")}<select name="art">{kinds}</select></label>'
              f'<label>{tr("Wert")}<input type="text" name="wert" maxlength="320" required autocomplete="off" '
              f'value="{e(values.get("wert", ""))}" placeholder="{hint}"></label>'
              f'<label>{tr("Wirkung")}<select name="aktion">{actions}</select></label>'
              f'<label>{tr("Nur für Postfach (leer: alle)")}<input type="number" name="postfach" min="1" max="99" '
              f'value="{e(values.get("postfach", ""))}"></label>'
              f'<label>{tr("Notiz")}<input type="text" name="notiz" maxlength="200" '
              f'value="{e(values.get("notiz", ""))}"></label>')
    shown = notice(preview, "info") if preview else ""
    preview_form = (f'<form method="get" action="{LIST_PATH}" class="stack">{fields}'
                    f'<button class="button" name="vorschau" value="1">{tr("Treffer prüfen")}</button></form>')
    save = action_form(RULE_PATH, csrf, tr("Regel speichern"), "button primary", stand=stand,
                       **{key: values[key] for key in ("art", "wert", "aktion", "postfach", "notiz") if key in values})
    return f'<h2>{tr("Neue Regel")}</h2>{shown}{preview_form}' + (save if savable else "")


def senders_page(blocked: IrrelevantSenders, hits: PrefilterHits, csrf: str, stand: str, zone: str,
                 message: str | None = None, message_kind: str = "ok", values: dict[str, str] | None = None,
                 preview: str | None = None, savable: bool = False) -> str:
    rules = {action: [rule for rule in blocked.rules if rule.action == action] for action in ACTION_LABELS}

    def rows(action: str) -> list[str]:
        return [_rule_row(rule, hits.rules.get(rule.id, RuleHits()), csrf, stand, zone) for rule in rules[action]]
    body = f'<p><a href="/einstellungen">← {tr("Einstellungen")}</a></p><h1>{tr("Absender-Regeln")}</h1>'
    if message:
        body += notice(message, message_kind)
    body += ('<p>' + tr("Diese Regeln entscheiden vor jedem KI-Aufruf. Ein VIP-Absender spart nur die "
                        "Relevanzprüfung; Termine und Aufgaben brauchen weiterhin deine Bestätigung.") + '</p>')
    body += (f'<p><a href="/lernen/vorschlaege#vorfilter-hinweise">'
             f'{tr("Vorschläge für neue Regeln aus deinen Entscheidungen")}</a></p>')
    body += rule_form(csrf, stand, values or {}, preview, savable)
    body += _section(tr("VIP-Absender"), tr("Immer relevant, auch wenn eine Sperre passt."), rows("vip"),
                     tr("Noch kein VIP-Absender."))
    body += _section(tr("Ignorierte Absender"), tr("Werden ohne KI-Aufruf und ohne Benachrichtigung aussortiert. "
                                                    "Neue Domainregeln umfassen auch Subdomains."),
                     _legacy_rows(blocked, hits, csrf, zone) + rows("ignore"),
                     tr("Derzeit wird kein Absender ignoriert."))
    body += _section(tr("Ausnahmen"), tr("Heben jede Sperre für diesen Absender auf, ohne ihn zum VIP zu machen."),
                     _exceptions(blocked.mailboxes, csrf, stand) + rows("allow_only"), tr("Keine Ausnahmen."))
    return body + header_section(blocked.headers, hits, csrf, stand, zone)


HEADERS: dict[HeaderFilter, tuple[str, str, str]] = {
    "automated": (AUTOMATED, "Automatische Systemmails",
                  "Auto-Submitted (z. B. Abwesenheitsnotizen) oder Precedence: bulk, junk, list."),
    "lists": (LISTS, "Newsletter und Verteiler",
              "List-Id oder List-Unsubscribe – auch Rundbriefe von Schule oder Verein."),
}
MODES = {"off": "aus", "trial": "Probelauf", "on": "an"}


def header_section(headers: HeaderPrefilter, hits: PrefilterHits, csrf: str, stand: str, zone: str) -> str:
    """7.7.4: off after an update; a trial only counts what would have been sorted out."""
    rows = []
    for key, (rule_id, name, explanation) in HEADERS.items():
        mode = getattr(headers, key)
        options = "".join(f'<option value="{value}"{" selected" if value == mode else ""}>{tr(label)}</option>'
                          for value, label in MODES.items())
        select = f'<label>{tr(name)}<select name="modus">{options}</select></label>'
        trial = ""
        if mode == "trial":
            counted = hits.trial.get(rule_id, RuleHits())
            trial = '<p class="meta">' + tr("Probelauf seit {since}: {count} Mails wären aussortiert worden "
                                             "(zuletzt: {when}). Entschieden hat weiter die KI.",
                                             since=format_datetime_local(headers.trial_since[key], zone),
                                             count=counted.count, when=_when(counted, zone)) + "</p>"
        rows.append(f'<li><span class="meta">{tr(explanation)}</span>{trial}'
                    + action_form(f"{LIST_PATH}/kopfzeilen", csrf, tr("Übernehmen"), "button small", select,
                                  stand=stand, filter=key) + "</li>")
    exceptions = [f'<li><span class="sender-entry">{e(item)}</span>'
                  + action_form(f"{LIST_PATH}/verteiler/entfernen", csrf, tr("Entfernen"), stand=stand, verteiler=item)
                  + "</li>" for item in headers.list_exceptions]
    field = (f'<label>{tr("List-Id")}<input type="text" name="verteiler" maxlength="200" required '
             'autocomplete="off" placeholder="&lt;eltern.schule.de&gt;"></label>')
    return (f'<h2>{tr("Kopfzeilen-Vorfilter")}</h2><p class="meta">'
            + tr("Standardmäßig aus. Ein Probelauf zählt nur, was aussortiert würde; erst „an“ spart KI-Aufrufe.")
            + f'</p><ul class="sender-list">{"".join(rows)}</ul>'
            + _section(tr("Verteiler-Ausnahmen"), tr("Diese Verteiler sortiert der Filter für Newsletter nie aus."),
                       exceptions, tr("Keine Verteiler-Ausnahmen."))
            + action_form(f"{LIST_PATH}/verteiler/hinzufuegen", csrf, tr("Ausnahme hinzufügen"), "button small",
                          field, stand=stand))


def preview_text(matched: int, total: int, conflict: bool) -> str:
    text = tr("Diese Regel würde {matched} der letzten {total} Mails treffen.", matched=matched, total=total)
    if conflict:
        text += " " + tr("Achtung: Das ist ein großer Mailanbieter; die Regel träfe sehr viele Absender.")
    return text


def is_freemail(rule: SenderRule) -> bool:
    return rule.kind == "domain" and rule.value in FREEMAIL


__all__ = ["LIST_PATH", "OLD_PATH", "RULE_PATH", "action_form", "is_freemail", "preview_text",
           "rule_form", "sender_actions", "senders_page"]
