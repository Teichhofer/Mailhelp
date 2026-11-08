"""Accessible HTML and equivalent plain text, with read-only links to authenticated review cards."""
from __future__ import annotations

from html import escape
from urllib.parse import quote, urlsplit

from ..formatting import format_datetime_local
from .briefing_aggregate import BriefingContent, BriefingItem

LIMIT = 50


def _base(value: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password
            or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
            or any(ord(char) < 33 or ord(char) == 127 for char in value)):
        raise ValueError("Briefing-Links benötigen eine vertrauenswürdige HTTP-/HTTPS-Basisadresse")
    return value.rstrip("/")


def _link(base: str, mail_id: str, proposal_id: str | None = None) -> str:
    mail = quote(mail_id, safe="")
    return (f"{base}/vorschlag/{mail}/{quote(proposal_id, safe='')}" if proposal_id is not None
            else f"{base}/mail/{mail}")


def _items(title: str, entries: tuple[BriefingItem, ...], base: str) -> tuple[list[str], str]:
    plain = [f"{title} ({len(entries)})"]
    html = f"<h2>{escape(title)} ({len(entries)})</h2><ul>"
    for item in entries[:LIMIT]:
        details = " · ".join(part for part in (item.when, item.state, f"Version {item.version}") if part)
        url = _link(base, item.mail_id, item.proposal_id)
        plain.extend([f"- {item.title}: {details}", *["  " + question for question in item.questions], url])
        html += (f'<li style="margin-bottom:16px"><strong>{escape(item.title)}</strong><br>'
                 f'{escape(details)}' + "".join(f"<p>{escape(question)}</p>" for question in item.questions)
                 + f'<br><a href="{escape(url, quote=True)}">In Mailhelp prüfen: {escape(item.title)}</a></li>')
    if len(entries) > LIMIT:
        extra = f"{len(entries) - LIMIT} weitere Einträge in Mailhelp."
        plain.append(extra)
        html += f"<li>{escape(extra)}</li>"
    return plain, html + "</ul>"


def render_briefing(content: BriefingContent, label: str, zone: str, base_url: str) -> dict[str, str]:
    base = _base(base_url)
    subject = f"[Mailhelp Briefing {label}] {len(content.events)} Termine, {len(content.tasks)} Aufgaben"
    interval = f"{format_datetime_local(content.start, zone)} bis {format_datetime_local(content.end, zone)}"
    plain = [subject, "Zeitraum: " + interval]
    html = (f'<h1 style="font-size:24px">{escape(subject)}</h1><p>Zeitraum: {escape(interval)}</p>')
    if content.empty:
        message = "Alles ruhig. Keine offenen Entscheidungen oder neuen relevanten Zusammenfassungen."
        plain.append(message)
        html += f"<p>{message}</p>"
    for title, entries in (("Termine zur Prüfung", content.events), ("Aufgaben zur Prüfung", content.tasks),
                           ("Relevanz klären", content.relevance)):
        if entries:
            lines, section = _items(title, entries, base)
            plain.extend(lines)
            html += section
    if content.summaries:
        plain.append("Neue Zusammenfassungen")
        html += "<h2>Neue Zusammenfassungen</h2>"
        for summary in content.summaries[:LIMIT]:
            url = _link(base, summary.mail_id)
            plain.extend([summary.subject, summary.text, *summary.deadlines, url])
            html += (f"<h3>{escape(summary.subject)}</h3><p>{escape(summary.text)}</p>"
                     + "".join(f"<p>Frist: {escape(deadline)}</p>" for deadline in summary.deadlines)
                     + f'<p><a href="{escape(url, quote=True)}">Mail in Mailhelp öffnen</a></p>')
        if len(content.summaries) > LIMIT:
            extra = f"{len(content.summaries) - LIMIT} weitere Zusammenfassungen in Mailhelp."
            plain.append(extra)
            html += f"<p>{extra}</p>"
    stats = f"{content.scanned} Mails ausgewertet, {content.irrelevant} als irrelevant aussortiert."
    plain.append(stats)
    html += f"<p>{stats}</p>"
    if content.damaged:
        notice = "Einige Datensätze sind beschädigt. Bitte die Diagnose in Mailhelp prüfen."
        plain.append(notice)
        html += f"<p><strong>{notice}</strong></p>"
    note = "Zum Freigeben die Karte in Mailhelp öffnen, prüfen und die angezeigte Version ausdrücklich bestätigen."
    plain.extend([note, base + "/offen"])
    html += f'<p>{note}</p><p><a href="{escape(base, quote=True)}/offen">Alle offenen Entscheidungen</a></p>'
    document = ('<!doctype html><html lang="de"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                f'<title>{escape(subject)}</title></head>'
                '<body style="margin:0;background:#f4f7fa;color:#153c30;font-family:Arial,sans-serif">'
                '<main style="max-width:680px;margin:0 auto;padding:20px;overflow-wrap:anywhere;'
                f'background:#fff;line-height:1.6">{html}</main></body></html>')
    return {"subject": subject, "text": "\n".join(plain), "html": document}
