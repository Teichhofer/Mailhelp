"""Pages of activity reports (2.2); every value from a mail is escaped, all works without JavaScript."""
from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

from ..activity.export import without_events
from ..activity.models import ActivityReport, ReportEvent, ReportMail, ReportStatus
from ..activity.presentation import ReportFilter, fingerprint, highlighted_text
from .actions import new_key
from .pages import e, layout, notice

STATUS_LABELS = {
    ReportStatus.COUNTING: "Zählt die Mails des Zeitraums …", ReportStatus.READY: "Bereit – wartet auf den Start",
    ReportStatus.RUNNING: "Läuft", ReportStatus.PAUSED: "Pausiert", ReportStatus.DONE: "Fertig",
    ReportStatus.CANCELLED: "Abgebrochen", ReportStatus.FAILED: "Fehlgeschlagen"}
ACTION_LABELS = {"start": "Bericht kostenpflichtig starten", "pause": "Pausieren", "resume": "Fortsetzen",
                 "cancel": "Abbrechen", "delete": "Bericht löschen"}
ACTIONS = {ReportStatus.COUNTING: ["cancel"], ReportStatus.READY: ["start", "cancel", "delete"],
           ReportStatus.RUNNING: ["pause", "cancel"], ReportStatus.PAUSED: ["resume", "cancel", "delete"],
           ReportStatus.DONE: ["delete"], ReportStatus.CANCELLED: ["delete"], ReportStatus.FAILED: ["delete"]}
SKIPPED = {"sender": "ignorierter Absender", "automated": "automatische Mail", "size": "zu groß",
           "suspicious": "verdächtiger Link", "duplicate": "Duplikat", "unreadable": "nicht lesbar"}
DISABLED = ("Tätigkeitsberichte sind ausgeschaltet. Sie werden mit activity_report.enabled in config.yaml "
            "und den Prompts activity_relevance und activity_events in prompts.yaml aktiviert.")


def _hidden(csrf: str, version: int, **fields: str) -> str:
    values = {"csrf": csrf, "key": new_key(), "version": str(version), **fields}
    return "".join(f'<input type="hidden" name="{e(name)}" value="{e(value)}">' for name, value in values.items())


def _day(value: date) -> str:
    return f"{value:%d.%m.%Y}"


def disabled_page() -> str:
    return layout("Berichte", f"<h1>Tätigkeitsberichte</h1>{notice(DISABLED)}", active="/berichte")


def list_page(reports: list[ActivityReport]) -> str:
    rows = "".join(
        f'<li><span><a href="/berichte/{report.id}">{e(report.definition.title)}</a><br>'
        f'<span class="meta">{_day(report.definition.since)} – {_day(report.definition.until)} · '
        f'{e(STATUS_LABELS[report.status])} · {report.processed} von {report.total} Mails</span></span></li>'
        for report in reports)
    body = ('<h1>Tätigkeitsberichte</h1><p class="meta">Welche Termine gehörten im Zeitraum zu einem Thema? '
            'Mailhelp liest das Postfach dafür nur, verändert nichts und legt nichts an.</p>'
            '<p><a class="button primary" href="/berichte/neu">Neuer Bericht</a></p>'
            + (f'<ul class="recent">{rows}</ul>' if rows else '<p class="meta">Noch keine Berichte.</p>'))
    return layout("Berichte", body, active="/berichte")


def _mailbox_choice(mailboxes: list[tuple[int, str]], mailbox: int) -> str:
    """With several mailboxes: links that reload the folder suggestions of another one (no JavaScript)."""
    if len(mailboxes) < 2:
        return ""
    links = " · ".join(f"<strong>{e(label)}</strong>" if number == mailbox
                       else f'<a href="/berichte/neu?postfach={number}">{e(label)}</a>'
                       for number, label in mailboxes)
    return f'<p class="meta">Postfach: {links}</p>'


def new_page(csrf: str, folders: list[str], values: dict[str, str] | None = None, error: str = "", *,
             mailboxes: list[tuple[int, str]] | None = None, mailbox: int = 1) -> str:
    """Folders are one per line: a checkbox per folder could exceed the form field limit."""
    if values is None:
        values = {"folders": "\n".join(folders), "include_sent": "on"}

    def checked(name: str) -> str:
        return " checked" if values.get(name) == "on" else ""

    body = (f'<h1>Neuer Tätigkeitsbericht</h1>{notice(error, "error") if error else ""}'
            f'{_mailbox_choice(mailboxes or [], mailbox)}'
            '<form method="post" action="/berichte" class="stack card">'
            f'<input type="hidden" name="csrf" value="{e(csrf)}"><input type="hidden" name="key" value="{new_key()}">'
            f'<input type="hidden" name="mailbox" value="{mailbox}">'
            f'<label>Titel<input name="title" maxlength="120" required value="{e(values.get("title", ""))}"></label>'
            '<label>Thema – worum es geht, was dazugehört, was nicht<textarea name="topic" rows="5" '
            f'maxlength="2000" required>{e(values.get("topic", ""))}</textarea></label>'
            f'<label>Von<input type="date" name="since" required value="{e(values.get("since", ""))}"></label>'
            f'<label>Bis<input type="date" name="until" required value="{e(values.get("until", ""))}"></label>'
            '<label>Ordner – einer pro Zeile<textarea name="folders" rows="4" required>'
            f'{e(values.get("folders", ""))}</textarea></label>'
            f'<label class="check"><input type="checkbox" name="include_sent"{checked("include_sent")}> '
            'Gesendete Mails einbeziehen (eigene Zusagen belegen Tätigkeiten)</label>'
            f'<label class="check"><input type="checkbox" name="skip_automated"{checked("skip_automated")}> '
            'Automatische Mails und Newsletter überspringen</label>'
            '<p class="meta">Zuerst werden nur die Mails des Zeitraums gezählt; Inhalte liest Mailhelp erst '
            'nach dem ausdrücklichen Start.</p>'
            '<button class="button primary">Mails zählen</button></form>')
    return layout("Neuer Bericht", body, active="/berichte")


def _actions(report: ActivityReport, csrf: str) -> str:
    forms = []
    for action in ACTIONS[report.status]:
        kind = "primary" if action in {"start", "resume"} else "danger" if action == "delete" else ""
        forms.append(f'<form method="post" action="/berichte/{report.id}/aktion">'
                     f'{_hidden(csrf, report.version, action=action)}'
                     f'<button class="button {kind}">{ACTION_LABELS[action]}</button></form>')
    return f'<div class="actions">{"".join(forms)}</div>'


def _facts(report: ActivityReport) -> str:
    counters = report.counters
    facts = [("Zeitraum", f"{_day(report.definition.since)} – {_day(report.definition.until)}"),
             ("Ordner", ", ".join(item.folder for item in report.folders) or ", ".join(report.definition.folders)),
             ("Stand", f"{report.processed} von {report.total} Mails gelesen"),
             ("Übersprungen", f"{counters.skipped_sender} ignorierte Absender, {counters.duplicates} Duplikate, "
                              f"{counters.skipped_other} sonstige"),
             ("Bewertet", f"{counters.evaluated} Mails, davon {counters.relevant} relevant"),
             ("Termine", str(counters.events)), ("KI-Aufrufe", str(counters.llm_calls))]
    return '<dl class="facts">' + "".join(f"<dt>{label}</dt><dd>{e(value)}</dd>" for label, value in facts) + "</dl>"


def _estimate(report: ActivityReport) -> str:
    if report.status != ReportStatus.READY:
        return ""
    return notice(f"{report.total} Mails im Zeitraum. Der Start verursacht höchstens {report.total} KI-Aufrufe für "
                  "die Relevanzprüfung und je relevanter Mail einen weiteren für die Termine.", "warn")


def _mail_link(report: ActivityReport, index: int, mail: ReportMail) -> str:
    return f'<a href="/berichte/{report.id}/mail/{index}">{e(mail.subject or "(ohne Betreff)")}</a>'


def _results(report: ActivityReport, mails: list[ReportMail], csrf: str, filters: ReportFilter) -> str:
    position = {mail.key: index for index, mail in enumerate(mails)}
    rows = "".join(
        f"<tr><td>{number}</td><td>{_day(event.day)}</td><td>{e(event.start_time or '')}"
        f"{e('–' + event.end_time) if event.end_time else ''}</td><td>{e(event.title)}</td>"
        f"<td>{e(event.location or '')}</td><td>{_mail_link(report, position[mail.key], mail)}<br>"
        f'<span class="meta">{e(mail.sender)}</span></td><td>{e(_flags(event, mail))}</td></tr>'
        for number, event, mail in filters.rows(mails))
    table = (f'<div class="table-scroll"><table><thead><tr><th>Nr.</th><th>Datum</th><th>Uhrzeit</th><th>Termin</th>'
             f'<th>Ort</th><th>Quelle</th><th>Hinweis</th></tr></thead><tbody>{rows}</tbody></table></div>'
             if rows else '<p class="meta">Noch keine Termine erkannt.</p>')
    unscheduled = "".join(f"<li>{_mail_link(report, position[mail.key], mail)}</li>" for mail in without_events(mails))
    rejected = [mail for mail in mails if mail.skipped is None and mail.relevant is not None
                and not mail.counts_as_relevant]
    rejected_items = "".join(
        f'<li><span>{_mail_link(report, position[mail.key], mail)}<br><span class="meta">{e(mail.reason)}</span>'
        f'</span><form method="post" action="/berichte/{report.id}/mail/{position[mail.key]}">'
        f'{_hidden(csrf, report.version, mode="relevant")}<button class="button small">Doch relevant</button></form>'
        f"</li>" for mail in rejected)
    export = (f'<p><a class="button" href="/berichte/{report.id}/export.xlsx">Als xlsx-Liste herunterladen</a></p>'
              if mails else "")
    return (f"<h2>Termine</h2>{table}{export}"
            + (f'<h2>Relevante Mails ohne Termin</h2><ul class="recent">{unscheduled}</ul>' if unscheduled else "")
            + (f'<details class="disclosure"><summary>Als nicht relevant bewertet ({len(rejected)})</summary>'
               f'<ul class="recent">{rejected_items}</ul></details>' if rejected else ""))


def _flags(event: ReportEvent, mail: ReportMail) -> str:
    flags = []
    if event.excluded or not mail.counts_as_relevant:
        flags.append("ausgeschlossen")
    if event.cancelled:
        flags.append("abgesagt")
    if mail.confidence == "low" and mail.user_relevant is None:
        flags.append("unsicher")
    if event.out_of_range:
        flags.append("außerhalb des Zeitraums")
    if event.manual:
        flags.append("von Hand ergänzt")
    elif event.edited:
        flags.append("korrigiert")
    return ", ".join(flags)


def report_page(report: ActivityReport, mails: list[ReportMail], csrf: str,
                filters: ReportFilter | None = None, costs: str = "") -> str:
    filters = filters or ReportFilter()
    message = notice(report.message, "warn") if report.message else ""
    body = (f'<p><a href="/berichte">← Alle Berichte</a></p><h1>{e(report.definition.title)}</h1>'
            f'<p class="meta">{e(report.definition.topic)}</p>'
            f'<section class="card"><h2>{e(STATUS_LABELS[report.status])}</h2>{message}{_estimate(report)}'
            f'{_facts(report)}<p class="meta">{e(costs)}</p>{_actions(report, csrf)}</section>'
            + _filters(filters) + _results(report, mails, csrf, filters)
            + f'<details><summary>Mit anderem Thema neu bewerten</summary>'
            f'<form method="post" action="/berichte/{report.id}/aktion" class="stack">'
            f'{_hidden(csrf, report.version, action="repeat")}'
            '<label>Neues Thema<textarea name="topic" minlength="10" maxlength="2000" required>'
            f'{e(report.definition.topic)}</textarea></label>'
            '<p>Geladene Mailtexte werden wiederverwendet. '
            'Die neue KI-Analyse beginnt erst nach deiner Bestätigung.</p>'
            '<button class="button">Neuen Bericht vorbereiten</button></form></details>')
    # Without JavaScript the page reloads itself while the report counts or reads.
    refresh = 15 if report.status in {ReportStatus.COUNTING, ReportStatus.RUNNING} else None
    return layout(report.definition.title, body, active="/berichte", refresh=refresh,
                  fingerprint=fingerprint(report, mails), state_url=f"/api/stand?bericht={report.id}")


def _filters(filters: ReportFilter) -> str:
    return ('<form method="get" class="filters">'
            f'<label>Monat<input type="month" name="month" value="{e(filters.month)}"></label>'
            f'<label>Absender<input name="sender" value="{e(filters.sender)}"></label>'
            f'<label><input type="checkbox" name="uncertain"{" checked" if filters.uncertain else ""}>'
            ' Nur unsichere</label>'
            f'<label><input type="checkbox" name="excluded"{" checked" if filters.excluded else ""}>'
            ' Ausgeschlossene anzeigen</label><button class="button">Filtern</button></form>')


def _event_form(report: ActivityReport, index: int, event: ReportEvent | None, csrf: str) -> str:
    fields = {"event": event.id} if event else {}
    title, day = (event.title, event.day.isoformat()) if event else ("", "")
    start, end, location = ((event.start_time or "", event.end_time or "", event.location or "") if event
                            else ("", "", ""))
    exclude = ""
    if event is not None:
        label = "Wieder aufnehmen" if event.excluded else "Ausschließen"
        exclude = (f'<form method="post" action="/berichte/{report.id}/mail/{index}">'
                   f'{_hidden(csrf, report.version, mode="include" if event.excluded else "exclude", event=event.id)}'
                   f'<button class="button small">{label}</button></form>')
    evidence = f'<p class="meta">Beleg: „{e(event.evidence)}“</p>' if event and event.evidence else ""
    return (f'<li class="card">{evidence}'
            f'<form method="post" action="/berichte/{report.id}/mail/{index}" class="filters">'
            f'{_hidden(csrf, report.version, mode="event", **fields)}'
            f'<label>Termin<input name="title" maxlength="200" required value="{e(title)}"></label>'
            f'<label>Datum<input type="date" name="day" required value="{e(day)}"></label>'
            f'<label>Beginn<input type="time" name="start_time" value="{e(start)}"></label>'
            f'<label>Ende<input type="time" name="end_time" value="{e(end)}"></label>'
            f'<label>Ort<input name="location" maxlength="300" value="{e(location)}"></label>'
            f'<button class="button small">{"Speichern" if event else "Termin hinzufügen"}</button></form>'
            f'{exclude}</li>')


def mail_page(report: ActivityReport, index: int, mail: ReportMail, csrf: str, zone: str) -> str:
    received = mail.received_at.astimezone(ZoneInfo(zone)).strftime("%d.%m.%Y, %H:%M Uhr")
    if mail.skipped is not None:
        verdict = f"Übersprungen: {SKIPPED[mail.skipped]}."
    elif mail.failed_step == "relevance" and mail.user_relevant is None:
        verdict = "Die KI-Antwort war unbrauchbar. Bitte selbst entscheiden."
    elif mail.relevant is None and mail.user_relevant is None:
        verdict = "Noch nicht bewertet."
    else:
        verdict = (("Relevant" if mail.counts_as_relevant else "Nicht relevant")
                   + (" (von dir festgelegt)" if mail.user_relevant is not None else
                      f" (KI, Sicherheit: {mail.confidence}) – {mail.reason}"))
    toggle = ""
    if mail.skipped is None and (mail.relevant is not None or mail.failed_step is not None):
        mode, label = ("irrelevant", "Nicht relevant") if mail.counts_as_relevant else ("relevant", "Doch relevant")
        toggle = (f'<form method="post" action="/berichte/{report.id}/mail/{index}">'
                  f'{_hidden(csrf, report.version, mode=mode)}<button class="button">{label}</button></form>')
    events = "".join(_event_form(report, index, event, csrf) for event in mail.events)
    if mail.failed_step == "events":
        events = notice("Die KI konnte die Termine nicht auslesen. Bitte von Hand ergänzen.", "warn") + events
    adding = _event_form(report, index, None, csrf) if mail.skipped is None else ""
    text = ("<p class=\"meta\">Volltext nach Ablauf der Aufbewahrungsfrist entfernt.</p>" if mail.text_removed
            else f'<pre class="mail-text">{highlighted_text(mail)}</pre>')
    attachments = (f'<p class="meta">Anhänge: {e(", ".join(mail.attachments))}</p>' if mail.attachments else "")
    body = (f'<p><a href="/berichte/{report.id}">← Zum Bericht</a></p><h1>{e(mail.subject or "(ohne Betreff)")}</h1>'
            f'<dl class="facts"><dt>Absender</dt><dd>{e(mail.sender)}</dd><dt>Eingang</dt><dd>{e(received)}</dd>'
            f'<dt>Ordner</dt><dd>{e(mail.folder)}</dd></dl>'
            f'<section class="card"><p>{e(verdict)}</p>{toggle}</section>'
            f'<h2>Termine</h2><ul class="event-list">{events}{adding}</ul>'
            f'<h2>Mail</h2>{attachments}{text}')
    return layout(mail.subject or "Mail", body, active="/berichte")


__all__ = ["disabled_page", "list_page", "mail_page", "new_page", "report_page"]
