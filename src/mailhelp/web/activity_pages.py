"""Pages of activity reports (2.2); every value from a mail is escaped, all works without JavaScript."""

from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

from ..activity.export import without_events
from ..activity.models import ActivityReport, ReportEvent, ReportMail, ReportStatus
from ..activity.presentation import ReportFilter, fingerprint, highlighted_text
from ..i18n import msg, tr
from .actions import new_key
from .pages import CUSTOMER_VIEW, e, layout, notice, page_head
from .settings_search import setting_href

__RESULTS_TEXT_1 = msg(
    '<div class="table-scroll"><table><thead><tr><th>Nr.</th><th>Datum</th><th>Uhrzeit</th'
    "><th>Termin</th><th>Ort</th><th>Quelle</th><th>Hinweis</th></tr></thead><tbody>{p0}</"
    "tbody></table></div>"
)

__RESULTS_TEXT_2 = msg(
    '<li><span>{p0}<br><span class="meta">{p1}</span></span><form method="post" '
    'action="/berichte/{p2}/mail/{p3}">{p4}<button class="button small">Doch '
    "relevant</button></form></li>"
)

STATUS_LABELS = {
    ReportStatus.COUNTING: msg("Zählt die Mails des Zeitraums …"),
    ReportStatus.READY: msg("Bereit – wartet auf den Start"),
    ReportStatus.RUNNING: msg("Läuft"),
    ReportStatus.PAUSED: msg("Pausiert"),
    ReportStatus.DONE: msg("Fertig"),
    ReportStatus.CANCELLED: msg("Abgebrochen"),
    ReportStatus.FAILED: msg("Fehlgeschlagen"),
}
ACTION_LABELS = {
    "start": msg("Bericht kostenpflichtig starten"),
    "pause": msg("Pausieren"),
    "resume": msg("Fortsetzen"),
    "cancel": msg("Abbrechen"),
    "delete": msg("Bericht löschen"),
}
# 8.7.7: customers start a report that uses points; prices and costs are the operator's.
CUSTOMER_ACTION_LABELS = {**ACTION_LABELS, "start": msg("Bericht starten (verbraucht Punkte)")}
ACTIONS = {ReportStatus.COUNTING: ["cancel"], ReportStatus.READY: ["start", "cancel", "delete"],
           ReportStatus.RUNNING: ["pause", "cancel"], ReportStatus.PAUSED: ["resume", "cancel", "delete"],
           ReportStatus.DONE: ["delete"], ReportStatus.CANCELLED: ["delete"], ReportStatus.FAILED: ["delete"]}
SKIPPED = {
    "sender": msg("ignorierter Absender"),
    "automated": msg("automatische Mail"),
    "size": msg("zu groß"),
    "suspicious": msg("verdächtiger Link"),
    "duplicate": msg("Duplikat"),
    "unreadable": msg("nicht lesbar"),
}
HELP = "/hilfe/dokumentation/web-einstellungen/taetigkeitsberichte"


def disabled_notice() -> str:
    """6.2.4: where to switch reports on – a link to the setting, not a key in config.yaml."""
    if CUSTOMER_VIEW.get():
        return notice(tr(
            "Tätigkeitsberichte sind in dieser Instanz ausgeschaltet; der Betreiber kann sie einschalten."))
    return tr(
        (
            '<p class="notice notice-info" role="status">Tätigkeitsberichte '
            "sind ausgeschaltet. Einschalten unter <a "
            'href="{p0}">Einstellungen → Tätigkeitsberichte aktivieren</a>. '
            "Die KI-Schritte <code>activity_relevance</code> und "
            "<code>activity_events</code> müssen in <code>prompts.yaml</code> "
            'stehen (<a href="{p1}">Hilfe zu Tätigkeitsberichten</a>).</p>'
        ),
        p0=e(setting_href("activity_report.enabled")),
        p1=HELP,
    )


INTRO = msg("Tätigkeitsberichte: Welche Termine gehörten im Zeitraum zu einem Thema?")


def _hidden(csrf: str, version: int, **fields: str) -> str:
    values = {"csrf": csrf, "key": new_key(), "version": str(version), **fields}
    return "".join(f'<input type="hidden" name="{e(name)}" value="{e(value)}">' for name, value in values.items())


def _day(value: date) -> str:
    return f"{value:%d.%m.%Y}"


def disabled_page(*, decisions: str = "") -> str:
    return layout(
        msg("Berichte"),
        page_head(msg("Berichte"), msg("Einblicke"), INTRO) + disabled_notice() + decisions,
        active="/berichte",
    )


def list_page(reports: list[ActivityReport], *, decisions: str = "") -> str:
    rows = "".join(
        tr(
            (
                '<li><span><a href="/berichte/{p0}">{p1}</a><br><span '
                'class="meta">{p2} – {p3} · {p4} · {p5} von {p6} '
                "Mails</span></span></li>"
            ),
            p0=report.id,
            p1=e(report.definition.title),
            p2=_day(report.definition.since),
            p3=_day(report.definition.until),
            p4=e(STATUS_LABELS[report.status]),
            p5=report.processed,
            p6=report.total,
        )
        for report in reports
    )
    body = (
        page_head(
            msg("Berichte"),
            msg("Einblicke"),
            INTRO + msg(" Mailhelp liest das Postfach dafür nur, verändert nichts und legt nichts an."),
        )
        + tr('<p><a class="button primary" href="/berichte/neu">Neuer Bericht</a></p>')
        + (f'<ul class="recent">{rows}</ul>' if rows else tr('<p class="meta">Noch keine Berichte.</p>'))
    )
    return layout(msg("Berichte"), body + decisions, active="/berichte")


def _mailbox_choice(mailboxes: list[tuple[int, str]], mailbox: int) -> str:
    """With several mailboxes: links that reload the folder suggestions of another one (no JavaScript)."""
    if len(mailboxes) < 2:
        return ""
    links = " · ".join(f"<strong>{e(label)}</strong>" if number == mailbox
                       else f'<a href="/berichte/neu?postfach={number}">{e(label)}</a>'
                       for number, label in mailboxes)
    return tr('<p class="meta">Postfach: {p0}</p>', p0=links)


def new_page(csrf: str, folders: list[str], values: dict[str, str] | None = None, error: str = "", *,
             mailboxes: list[tuple[int, str]] | None = None, mailbox: int = 1) -> str:
    """Folders are one per line: a checkbox per folder could exceed the form field limit."""
    if values is None:
        values = {"folders": "\n".join(folders), "include_sent": "on"}

    def checked(name: str) -> str:
        return " checked" if values.get(name) == "on" else ""

    body = tr(
        (
            '<h1>Neuer Tätigkeitsbericht</h1>{p0}{p1}<form method="post" '
            'action="/berichte" class="stack card"><input type="hidden" '
            'name="csrf" value="{p2}"><input type="hidden" name="key" '
            'value="{p3}"><input type="hidden" name="mailbox" '
            'value="{p4}"><label>Titel<input name="title" maxlength="120" '
            'required value="{p5}"></label><label>Thema – worum es geht, was '
            'dazugehört, was nicht<textarea name="topic" rows="5" '
            'maxlength="2000" '
            'required>{p6}</textarea></label><label>Von<input type="date" '
            'name="since" required value="{p7}"></label><label>Bis<input '
            'type="date" name="until" required '
            'value="{p8}"></label><label>Ordner – einer pro Zeile<textarea '
            'name="folders" rows="4" required>{p9}</textarea></label><label '
            'class="check"><input type="checkbox" name="include_sent"{p10}> '
            "Gesendete Mails einbeziehen (eigene Zusagen belegen "
            'Tätigkeiten)</label><label class="check"><input type="checkbox" '
            'name="skip_automated"{p11}> Automatische Mails und Newsletter '
            'überspringen</label><p class="meta">Zuerst werden nur die Mails '
            "des Zeitraums gezählt; Inhalte liest Mailhelp erst nach dem "
            'ausdrücklichen Start.</p><button class="button primary">Mails '
            "zählen</button></form>"
        ),
        p0=notice(error, "error") if error else "",
        p1=_mailbox_choice(mailboxes or [], mailbox),
        p2=e(csrf),
        p3=new_key(),
        p4=mailbox,
        p5=e(values.get("title", "")),
        p6=e(values.get("topic", "")),
        p7=e(values.get("since", "")),
        p8=e(values.get("until", "")),
        p9=e(values.get("folders", "")),
        p10=checked("include_sent"),
        p11=checked("skip_automated"),
    )
    return layout(tr("Neuer Bericht"), body, active="/berichte")


def _actions(report: ActivityReport, csrf: str) -> str:
    forms = []
    labels = CUSTOMER_ACTION_LABELS if CUSTOMER_VIEW.get() else ACTION_LABELS
    for action in ACTIONS[report.status]:
        kind = "primary" if action in {"start", "resume"} else "danger" if action == "delete" else ""
        forms.append(f'<form method="post" action="/berichte/{report.id}/aktion">'
                     f'{_hidden(csrf, report.version, action=action)}'
                     f'<button class="button {kind}">{labels[action]}</button></form>')
    return f'<div class="actions">{"".join(forms)}</div>'


def _facts(report: ActivityReport) -> str:
    counters = report.counters
    facts = [
        (msg("Zeitraum"), f"{_day(report.definition.since)} – {_day(report.definition.until)}"),
        (msg("Ordner"), ", ".join(item.folder for item in report.folders) or ", ".join(report.definition.folders)),
        (msg("Stand"), tr("{p0} von {p1} Mails gelesen", p0=f"{report.processed}", p1=f"{report.total}")),
        (
            msg("Übersprungen"),
            tr(
                "{p0} ignorierte Absender, {p1} Duplikate, {p2} sonstige",
                p0=f"{counters.skipped_sender}",
                p1=f"{counters.duplicates}",
                p2=f"{counters.skipped_other}",
            ),
        ),
        (msg("Bewertet"), tr("{p0} Mails, davon {p1} relevant", p0=counters.evaluated, p1=counters.relevant)),
        (msg("Termine"), str(counters.events)),
        (msg("KI-Aufrufe"), str(counters.llm_calls)),
    ]
    return '<dl class="facts">' + "".join(f"<dt>{label}</dt><dd>{e(value)}</dd>" for label, value in facts) + "</dl>"


def _estimate(report: ActivityReport) -> str:
    if report.status != ReportStatus.READY:
        return ""
    return notice(
        tr(
            (
                "{p0} Mails im Zeitraum. Der Start verursacht höchstens {p1} "
                "KI-Aufrufe für die Relevanzprüfung und je relevanter Mail einen "
                "weiteren für die Termine."
            ),
            p0=report.total,
            p1=report.total,
        ),
        "warn",
    )


def _mail_link(report: ActivityReport, index: int, mail: ReportMail) -> str:
    # 8.7.12: an own tap target; inside a table cell its height otherwise depended on the font's line breaks.
    subject = e(mail.subject or msg("(ohne Betreff)"))
    return f'<a class="cell-link" href="/berichte/{report.id}/mail/{index}">{subject}</a>'


def _results(report: ActivityReport, mails: list[ReportMail], csrf: str, filters: ReportFilter) -> str:
    position = {mail.key: index for index, mail in enumerate(mails)}
    rows = "".join(
        f"<tr><td>{number}</td><td>{_day(event.day)}</td><td>{e(event.start_time or '')}"
        f"{e('–' + event.end_time) if event.end_time else ''}</td><td>{e(event.title)}</td>"
        f"<td>{e(event.location or '')}</td><td>{_mail_link(report, position[mail.key], mail)}<br>"
        f'<span class="meta">{e(mail.sender)}</span></td><td>{e(_flags(event, mail))}</td></tr>'
        for number, event, mail in filters.rows(mails))
    table = (
        tr(
            (__RESULTS_TEXT_1),
            p0=rows,
        )
        if rows
        else tr('<p class="meta">Noch keine Termine erkannt.</p>')
    )
    unscheduled = "".join(f"<li>{_mail_link(report, position[mail.key], mail)}</li>" for mail in without_events(mails))
    rejected = [mail for mail in mails if mail.skipped is None and mail.relevant is not None
                and not mail.counts_as_relevant]
    rejected_items = "".join(
        tr(
            (__RESULTS_TEXT_2),
            p0=_mail_link(report, position[mail.key], mail),
            p1=e(mail.reason),
            p2=report.id,
            p3=position[mail.key],
            p4=_hidden(csrf, report.version, mode="relevant"),
        )
        for mail in rejected
    )
    export = (
        tr(
            ('<p><a class="button" href="/berichte/{p0}/export.xlsx">Als xlsx-Liste herunterladen</a></p>'),
            p0=report.id,
        )
        if mails
        else ""
    )
    return (
        tr("<h2>Termine</h2>{p0}{p1}", p0=table, p1=export)
        + (
            tr(('<h2>Relevante Mails ohne Termin</h2><ul class="recent">{p0}</ul>'), p0=unscheduled)
            if unscheduled
            else ""
        )
        + (
            tr(
                (
                    '<details class="disclosure"><summary>Als nicht relevant bewertet '
                    '({p0})</summary><ul class="recent">{p1}</ul></details>'
                ),
                p0=len(rejected),
                p1=rejected_items,
            )
            if rejected
            else ""
        )
    )


def _flags(event: ReportEvent, mail: ReportMail) -> str:
    flags = []
    if event.excluded or not mail.counts_as_relevant:
        flags.append("ausgeschlossen")
    if event.cancelled:
        flags.append(msg("abgesagt"))
    if mail.confidence == "low" and mail.user_relevant is None:
        flags.append(msg("unsicher"))
    if event.out_of_range:
        flags.append(msg("außerhalb des Zeitraums"))
    if event.manual:
        flags.append(msg("von Hand ergänzt"))
    elif event.edited:
        flags.append(msg("korrigiert"))
    return ", ".join(flags)


def report_page(report: ActivityReport, mails: list[ReportMail], csrf: str,
                filters: ReportFilter | None = None, costs: str = "") -> str:
    filters = filters or ReportFilter()
    message = notice(report.message, "warn") if report.message else ""
    body = (
        tr(
            (
                '<p><a href="/berichte">← Alle Berichte</a></p><h1>{p0}</h1><p '
                'class="meta">{p1}</p><section '
                'class="card"><h2>{p2}</h2>{p3}{p4}{p5}<p '
                'class="meta">{p6}</p>{p7}</section>'
            ),
            p0=e(report.definition.title),
            p1=e(report.definition.topic),
            p2=e(STATUS_LABELS[report.status]),
            p3=message,
            p4=_estimate(report),
            p5=_facts(report),
            p6=e(costs),
            p7=_actions(report, csrf),
        )
        + _filters(filters)
        + _results(report, mails, csrf, filters)
        + tr(
            (
                "<details><summary>Mit anderem Thema neu bewerten</summary><form "
                'method="post" action="/berichte/{p0}/aktion" '
                'class="stack">{p1}<label>Neues Thema<textarea name="topic" '
                'minlength="10" maxlength="2000" '
                "required>{p2}</textarea></label><p>Geladene Mailtexte werden "
                "wiederverwendet. Die neue KI-Analyse beginnt erst nach deiner "
                'Bestätigung.</p><button class="button">Neuen Bericht '
                "vorbereiten</button></form></details>"
            ),
            p0=report.id,
            p1=_hidden(csrf, report.version, action="repeat"),
            p2=e(report.definition.topic),
        )
    )
    # Without JavaScript the page reloads itself while the report counts or reads.
    refresh = 15 if report.status in {ReportStatus.COUNTING, ReportStatus.RUNNING} else None
    return layout(
        report.definition.title,
        body,
        active="/berichte",
        refresh=refresh,
        fingerprint=fingerprint(report, mails),
        state_url='/api/stand?bericht={p0}'.format(p0=f'{report.id}'),
    )


def _filters(filters: ReportFilter) -> str:
    return tr(
        (
            '<form method="get" class="filters"><label>Monat<input '
            'type="month" name="month" '
            'value="{p0}"></label><label>Absender<input name="sender" '
            'value="{p1}"></label><label><input type="checkbox" '
            'name="uncertain"{p2}> Nur unsichere</label><label><input '
            'type="checkbox" name="excluded"{p3}> Ausgeschlossene '
            'anzeigen</label><button class="button">Filtern</button></form>'
        ),
        p0=e(filters.month),
        p1=e(filters.sender),
        p2=" checked" if filters.uncertain else "",
        p3=" checked" if filters.excluded else "",
    )


def _event_form(report: ActivityReport, index: int, event: ReportEvent | None, csrf: str) -> str:
    fields = {"event": event.id} if event else {}
    title, day = (event.title, event.day.isoformat()) if event else ("", "")
    start, end, location = ((event.start_time or "", event.end_time or "", event.location or "") if event
                            else ("", "", ""))
    exclude = ""
    if event is not None:
        label = msg("Wieder aufnehmen") if event.excluded else msg("Ausschließen")
        exclude = (f'<form method="post" action="/berichte/{report.id}/mail/{index}">'
                   f'{_hidden(csrf, report.version, mode="include" if event.excluded else "exclude", event=event.id)}'
                   f'<button class="button small">{label}</button></form>')
    evidence = tr('<p class="meta">Beleg: „{p0}“</p>', p0=e(event.evidence)) if event and event.evidence else ""
    return tr(
        (
            '<li class="card">{p0}<form method="post" '
            'action="/berichte/{p1}/mail/{p2}" '
            'class="filters">{p3}<label>Termin<input name="title" '
            'maxlength="200" required value="{p4}"></label><label>Datum<input '
            'type="date" name="day" required '
            'value="{p5}"></label><label>Beginn<input type="time" '
            'name="start_time" value="{p6}"></label><label>Ende<input '
            'type="time" name="end_time" '
            'value="{p7}"></label><label>Ort<input name="location" '
            'maxlength="300" value="{p8}"></label><button class="button '
            'small">{p9}</button></form>{p10}</li>'
        ),
        p0=evidence,
        p1=report.id,
        p2=index,
        p3=_hidden(csrf, report.version, mode="event", **fields),
        p4=e(title),
        p5=e(day),
        p6=e(start),
        p7=e(end),
        p8=e(location),
        p9=msg("Speichern") if event else msg("Termin hinzufügen"),
        p10=exclude,
    )


def mail_page(report: ActivityReport, index: int, mail: ReportMail, csrf: str, zone: str) -> str:
    received = mail.received_at.astimezone(ZoneInfo(zone)).strftime(msg("%d.%m.%Y, %H:%M Uhr"))
    if mail.skipped is not None:
        verdict = tr("Übersprungen: {p0}.", p0=SKIPPED[mail.skipped])
    elif mail.failed_step == "relevance" and mail.user_relevant is None:
        verdict = msg("Die KI-Antwort war unbrauchbar. Bitte selbst entscheiden.")
    elif mail.relevant is None and mail.user_relevant is None:
        verdict = msg("Noch nicht bewertet.")
    else:
        verdict = ("Relevant" if mail.counts_as_relevant else msg("Nicht relevant")) + (
            msg(" (von dir festgelegt)")
            if mail.user_relevant is not None
            else tr(" (KI, Sicherheit: {p0}) – {p1}", p0=f"{mail.confidence}", p1=f"{mail.reason}")
        )
    toggle = ""
    if mail.skipped is None and (mail.relevant is not None or mail.failed_step is not None):
        mode, label = (
            ("irrelevant", msg("Nicht relevant")) if mail.counts_as_relevant else ("relevant", msg("Doch relevant"))
        )
        toggle = (f'<form method="post" action="/berichte/{report.id}/mail/{index}">'
                  f'{_hidden(csrf, report.version, mode=mode)}<button class="button">{label}</button></form>')
    events = "".join(_event_form(report, index, event, csrf) for event in mail.events)
    if mail.failed_step == "events":
        events = notice(tr("Die KI konnte die Termine nicht auslesen. Bitte von Hand ergänzen."), "warn") + events
    adding = _event_form(report, index, None, csrf) if mail.skipped is None else ""
    text = (
        tr('<p class="meta">Volltext nach Ablauf der Aufbewahrungsfrist entfernt.</p>')
        if mail.text_removed
        else f'<pre class="mail-text">{highlighted_text(mail)}</pre>'
    )
    attachments = (
        tr(
            '<p class="meta">Anhänge: {p0}</p>',
            p0=e(", ".join(mail.attachments)),
        )
        if mail.attachments
        else ""
    )
    body = tr(
        (
            '<p><a href="/berichte/{p0}">← Zum '
            "Bericht</a></p><h1>{p1}</h1><dl "
            'class="facts"><dt>Absender</dt><dd>{p2}</dd><dt>Eingang</dt><dd>{'
            "p3}</dd><dt>Ordner</dt><dd>{p4}</dd></dl><section "
            'class="card"><p>{p5}</p>{p6}</section><h2>Termine</h2><ul '
            'class="event-list">{p7}{p8}</ul><h2>Mail</h2>{p9}{p10}'
        ),
        p0=report.id,
        p1=e(mail.subject or msg("(ohne Betreff)")),
        p2=e(mail.sender),
        p3=e(received),
        p4=e(mail.folder),
        p5=e(verdict),
        p6=toggle,
        p7=events,
        p8=adding,
        p9=attachments,
        p10=text,
    )
    return layout(mail.subject or "Mail", body, active="/berichte")


__all__ = ["disabled_page", "list_page", "mail_page", "new_page", "report_page"]
