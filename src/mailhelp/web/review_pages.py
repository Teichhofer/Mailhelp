"""Pages built from the review read models: overview, proposal detail, run status.

They show the same content as the compact Telegram card; description and
evidence can be expanded.  Every value is escaped.  Links contained in mails
are shown as plain text; only an ``https`` video link and the link of an entry
Mailhelp created itself are clickable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from ..models import ProposalKind, ProposalStatus
from ..review.inbox import CommandStatus
from ..review.views import (STATUS_LABELS, MailView, Overview, ProposalView, RelevanceView,
                            RunStatus, SystemStatus)
from .pages import e, layout, notice

# Renders the action forms of a card (phase 6); None shows the card read-only.
Actions = Callable[[ProposalView], str]
RelevanceActions = Callable[[RelevanceView], str]

_STATE_BADGE = {
    ProposalStatus.PENDING_CONFIRMATION: "accent",
    ProposalStatus.NEEDS_CLARIFICATION: "warn",
    ProposalStatus.CREATED: "ok",
    ProposalStatus.SIMULATED: "ok",
    ProposalStatus.REJECTED: "",
    ProposalStatus.FAILED: "danger",
    ProposalStatus.UNCERTAIN: "warn",
    ProposalStatus.CONFIRMED: "accent",
    ProposalStatus.WRITING: "accent",
}
RUN_LABELS = (
    ("discovered", "Gefunden"), ("queued", "In Warteschlange"), ("processing", "In Bearbeitung"),
    ("completed", "Abgeschlossen"), ("waiting_for_user", "Warten auf dich"),
    ("failed", "Fehlgeschlagen"), ("skipped", "Übersprungen"),
)


def https_link(value: str | None) -> str | None:
    """The value if it is an absolute https URL, else None."""
    if not value:
        return None
    parts = urlsplit(value)
    return value if parts.scheme == "https" and parts.netloc else None


def _fact(icon: str, text: str, label: str) -> str:
    return (f'<li><span class="icon" aria-hidden="true">{icon}</span>'
            f'<span><span class="visually-hidden">{label}: </span>{text}</span></li>')


def _expandable(short: str, full: str, label: str, quote: bool) -> str:
    tag = "blockquote" if quote else "p"
    if short == full:
        return f"<{tag}>{e(short)}</{tag}>"
    return (f"<{tag}>{e(short)}</{tag}><details><summary>{label} vollständig anzeigen</summary>"
            f'<p class="full">{e(full)}</p></details>')


def proposal_card(view: ProposalView, *, actions: Actions | None = None,
                  detail_link: bool = True) -> str:
    card = view.card
    event = card.kind == ProposalKind.EVENT
    facts = []
    if card.when:
        facts.append(_fact("🕒", e(card.when), "Zeit"))
    if card.due:
        facts.append(_fact("🕒", f"Fällig: {e(card.due)}", "Frist"))
    if card.location:
        facts.append(_fact("📍", e(card.location), "Ort"))
    if card.video_link:
        link = https_link(card.video_link)
        text = (f'<a href="{e(link)}" rel="noopener noreferrer" target="_blank">{e(link)}</a>'
                if link else e(card.video_link))
        facts.append(_fact("🔗", text, "Videolink"))
    labels = [f'<span class="badge {_STATE_BADGE[view.status]}">{e(view.state)}</span>']
    if view.current:
        labels.append('<span class="badge accent">Aktuell in Telegram</span>')
    if view.queued:
        labels.append('<span class="badge">Folgt in Telegram</span>')
    for value, prefix in ((card.responsibility, "Zuständig"), (card.certainty, "Sicherheit"),
                          (card.classification, "Einordnung")):
        if value:
            labels.append(f'<span class="badge warn">{prefix}: {e(value)}</span>')
    warnings = []
    # With open questions the answers decide whether it can be created.
    if not card.writable and not card.questions and view.status in {
            ProposalStatus.PENDING_CONFIRMATION, ProposalStatus.NEEDS_CLARIFICATION}:
        warnings.append(notice("Kann nicht automatisch angelegt werden – bitte manuell prüfen.", "warn"))
    elif card.test_mode:
        warnings.append(notice("Testmodus: Der Eintrag wird nur simuliert.", "info"))
    questions = ""
    if card.questions:
        items = "".join(f"<li>{e(question)}</li>" for question in card.questions)
        questions = f'<div class="questions"><p>Offene Fragen</p><ul>{items}</ul></div>'
    description = (_expandable(card.description, card.description_full or card.description,
                               "Beschreibung", False) if card.description else "")
    evidence = _expandable(card.evidence, card.evidence_full, "Beleg", True)
    created = https_link(view.external_link)
    created_link = (f'<p><a href="{e(created)}" rel="noopener noreferrer" target="_blank">'
                    f'{"Im Kalender öffnen" if event else "In Todoist öffnen"}</a></p>'
                    if created else "")
    version = f" · Version {view.version}" if view.version > 1 else ""
    title = e(card.title)
    if detail_link:
        title = f'<a href="/vorschlag/{e(view.mail_id)}/{e(view.proposal_id)}">{title}</a>'
    current = " current" if view.current else ""
    details = (f'<p class="card-links"><a class="button small" '
               f'href="/vorschlag/{e(view.mail_id)}/{e(view.proposal_id)}">Details</a></p>'
               if detail_link else "")
    return f"""<article class="card{current}" id="v-{e(view.mail_id)}-{e(view.proposal_id)}">
<p class="kind">{"📅 Termin" if event else "✅ Aufgabe"}{version}</p>
<div class="card-head"><h3>{title}</h3></div>
<p class="source">✉️ {e(view.sender)} · {e(view.subject)}</p>
<p class="labels">{" ".join(labels)}</p>
<ul class="facts">{"".join(facts)}</ul>
{"".join(warnings)}{questions}{description}{evidence}{created_link}{details}
{actions(view) if actions else ""}
</article>"""


def relevance_card(view: RelevanceView, actions: RelevanceActions | None = None,
                   detail_link: bool = True) -> str:
    details = (f'<p class="card-links"><a class="button small" href="/mail/{e(view.mail_id)}">'
               'Details</a></p>' if detail_link else "")
    return f"""<article class="card" id="r-{e(view.mail_id)}">
<p class="kind">❔ Relevanz</p>
<h3>{e(view.subject)}</h3>
<p class="source">✉️ {e(view.sender)}</p>
<p>Ist diese Mail für dich relevant? Bis zur Antwort wartet die Mailanalyse.</p>
{details}
{actions(view) if actions else ""}
</article>"""


def overview_page(overview: Overview, *, actions: Actions | None = None,
                  relevance_actions: RelevanceActions | None = None,
                  message: str | None = None, message_kind: str = "ok") -> str:
    parts = [f'<h1>Offene Entscheidungen <span class="count">{len(overview.open) + len(overview.relevance)}</span></h1>']
    if message:
        parts.append(notice(message, message_kind))
    if overview.damaged:
        parts.append(notice(f"{overview.damaged} gespeicherte Datensätze sind beschädigt und werden "
                            "nicht angezeigt. Bitte die Protokolle prüfen.", "error"))
    if overview.relevance:
        parts.append("<h2>Relevanz klären</h2>")
        parts.extend(relevance_card(view, relevance_actions) for view in overview.relevance)
    if overview.open:
        parts.append("<h2>Vorschläge</h2>")
        parts.extend(proposal_card(view, actions=actions) for view in overview.open)
    if not overview.open and not overview.relevance:
        parts.append('<p class="empty">Nichts zu entscheiden. Neue Vorschläge erscheinen hier automatisch.</p>')
    if overview.recent:
        items = []
        for view in overview.recent:
            items.append(
                f'<li><span><a href="/vorschlag/{e(view.mail_id)}/{e(view.proposal_id)}">'
                f'{e(view.card.title)}</a></span>'
                f'<span class="badge {_STATE_BADGE[view.status]}">{e(view.state)}</span></li>')
        parts.append(f'<h2>Zuletzt erledigt</h2><ul class="recent">{"".join(items)}</ul>')
    return layout("Offen", "\n".join(parts), active="/", fingerprint=overview.fingerprint)


def mail_section(mail: MailView | None) -> str:
    """The complete stored mail as text; links in it stay plain text."""
    if mail is None:
        return ""
    facts = [("Von", mail.sender), ("Betreff", mail.subject)]
    if mail.received:
        facts.append(("Datum", mail.received))
    rows = "".join(f"<dt>{label}</dt><dd>{e(value)}</dd>" for label, value in facts)
    notes = []
    if mail.attachments_omitted:
        notes.append(f"{mail.attachments_omitted} Anhang/Anhänge nicht ausgewertet und nicht gespeichert.")
    if mail.text_shortened:
        notes.append("Der Text wurde für die Auswertung gekürzt.")
    if mail.text is None:
        body = notice("Der vollständige Mailtext ist nicht mehr gespeichert "
                      "(automatische Löschung nach Abschluss und Aufbewahrungsfrist).", "info")
    else:
        body = f'<div class="mail-text">{e(mail.text)}</div>'
    hints = "".join(f'<p class="meta">{e(note)}</p>' for note in notes)
    return f"""<section class="card mail" id="mail" aria-labelledby="mail-titel">
<h2 id="mail-titel">Mail</h2>
<dl class="mail-head">{rows}</dl>
{body}{hints}
</section>"""


def detail_page(view: ProposalView, *, actions: Actions | None = None,
                mail: MailView | None = None) -> str:
    content = f"""<p><a href="/">← Zur Übersicht</a></p>
<h1>{"Termin" if view.card.kind == ProposalKind.EVENT else "Aufgabe"}</h1>
{proposal_card(view, actions=actions, detail_link=False)}
{mail_section(mail)}"""
    return layout(view.card.title, content, active="/")


def mail_page(mail: MailView, relevance: RelevanceView | None = None,
              actions: RelevanceActions | None = None) -> str:
    """A mail on its own, with the relevance question if it is still open."""
    question = relevance_card(relevance, actions, detail_link=False) if relevance else ""
    content = f"""<p><a href="/">← Zur Übersicht</a></p>
<h1>Mail</h1>
{question}
{mail_section(mail)}"""
    return layout(mail.subject, content, active="/")


ANALYSIS_LABELS = (
    ("completed", "Relevant und ausgewertet"), ("irrelevant", "Irrelevant"),
    ("duplicate", "Doppelt erhalten"), ("failed", "Fehlgeschlagen"), ("skipped", "Übersprungen"),
)
COMMAND_LABELS = (
    (CommandStatus.QUEUED, "wartend"), (CommandStatus.RUNNING, "laufend"),
    (CommandStatus.DONE, "erledigt"), (CommandStatus.REJECTED, "abgelehnt"),
    (CommandStatus.FAILED, "fehlgeschlagen"),
)


@dataclass(frozen=True)
class ServiceInfo:
    """Facts about the running Mailhelp process, supplied by the web site."""

    version: str
    test_mode: bool
    started_at: datetime
    now: datetime
    address: str
    devices: int
    llm_calls_per_minute: int | None
    commands: dict[CommandStatus, int]


def _when(value: datetime | None, zone: ZoneInfo) -> str:
    return value.astimezone(zone).strftime("%d.%m.%Y, %H:%M Uhr") if value else "—"


def _duration(seconds: float) -> str:
    minutes = int(seconds // 60)
    days, minutes = divmod(minutes, 24 * 60)
    hours, minutes = divmod(minutes, 60)
    if days:
        return f"{days} T {hours} Std."
    if hours:
        return f"{hours} Std. {minutes} Min."
    return f"{minutes} Min."


def _facts(rows: list[tuple[str, str]]) -> str:
    return ('<dl class="facts-table">'
            + "".join(f"<dt>{e(label)}</dt><dd>{e(value)}</dd>" for label, value in rows)
            + "</dl>")


def _stats(items: list[tuple[int, str]]) -> str:
    return ('<div class="stats">'
            + "".join(f'<div class="stat"><strong>{value}</strong><span>{e(label)}</span></div>'
                      for value, label in items)
            + "</div>")


def status_page(run: RunStatus, overview: Overview, configured_timezone: str,
                system: SystemStatus, info: ServiceInfo) -> str:
    zone = ZoneInfo(configured_timezone)
    parts = ["<h1>Status</h1>"]
    if overview.damaged:
        parts.append(notice(f"{overview.damaged} beschädigte Datensätze – bitte Protokolle prüfen.", "error"))
    parts.append(_stats([
        (len(overview.open), "Offene Vorschläge"), (len(overview.relevance), "Relevanzfragen"),
        (system.mails_failed, "Mails mit Fehler"),
        (info.commands.get(CommandStatus.QUEUED, 0), "Wartende Web-Aktionen")]))

    parts.append("<h2>Mailhelp</h2>")
    parts.append(_facts([
        ("Version", info.version),
        ("Modus", "Testmodus – Einträge werden nur simuliert" if info.test_mode else "Produktiv"),
        ("Läuft seit", f"{_when(info.started_at, zone)} ({_duration((info.now - info.started_at).total_seconds())})"),
        ("Weboberfläche", info.address),
        ("Gekoppelte Geräte", str(info.devices)),
    ]))

    parts.append("<h2>Letzter Mail-Durchlauf</h2>")
    progress = (f"{system.run_finished} von {system.run_total} Mails analysiert"
                if system.run_total else "Keine Mails im aktuellen Durchlauf")
    parts.append(_facts([
        ("Gestartet", _when(run.started_at, zone)),
        ("Stand", ("abgeschlossen" if run.run_complete else "läuft noch") + f" · {progress}"),
    ]))
    if system.run_total:
        parts.append(f'<progress class="run-progress" max="{system.run_total}" '
                     f'value="{system.run_finished}" aria-label="Fortschritt des Durchlaufs">'
                     f'{system.run_finished} von {system.run_total}</progress>')
    parts.append(_stats([(run.counters.get(key, 0), label) for key, label in RUN_LABELS]))
    if system.analysis:
        parts.append("<h3>Ergebnis der Analyse</h3>")
        parts.append(_stats([(system.analysis.get(key, 0), label) for key, label in ANALYSIS_LABELS]))

    parts.append("<h2>Mails</h2>")
    parts.append(_facts([
        ("Gespeichert", str(system.mails_total)),
        ("Zuletzt verarbeitet", _when(system.last_processed, zone)),
        ("Warten auf Relevanzentscheidung", str(system.mails_waiting_relevance)),
        ("Zurückgestellt (neuer Versuch später)", str(system.mails_deferred)),
    ]))

    parts.append("<h2>Vorschläge</h2>")
    if system.proposals:
        parts.append(_stats([(system.proposals[status], STATUS_LABELS[status])
                             for status in STATUS_LABELS if status in system.proposals]))
    else:
        parts.append('<p class="meta">Noch keine Vorschläge gespeichert.</p>')

    parts.append("<h2>Letzte Fehler</h2>")
    if system.errors:
        items = []
        for error in system.errors:
            retry = " · wird automatisch wiederholt" if error.retryable else ""
            if error.next_attempt is not None:
                retry += f" · nächster Versuch: {_when(error.next_attempt, zone)}"
            items.append(
                f'<li><span><a href="/mail/{e(error.mail_id)}">{e(error.subject)}</a><br>'
                f'<span class="meta">{e(error.cause)} · {e(error.stage)} · '
                f'{e(_when(error.occurred_at, zone))}{retry}</span></span></li>')
        parts.append(f'<ul class="recent">{"".join(items)}</ul>')
    else:
        parts.append('<p class="meta">Keine Fehler bei gespeicherten Mails.</p>')

    parts.append("<h2>Telegram, Web und KI</h2>")
    commands = ", ".join(f"{info.commands.get(status, 0)} {label}" for status, label in COMMAND_LABELS)
    llm = (f"{system.llm_calls_last_minute} von höchstens {info.llm_calls_per_minute}"
           if info.llm_calls_per_minute else str(system.llm_calls_last_minute))
    parts.append(_facts([
        ("Zurückgehaltene Telegram-Nachrichten", str(system.telegram_held)),
        ("Unverarbeitete Telegram-Eingänge", str(system.telegram_unprocessed)),
        ("Web-Aktionen (letzte 24 Std.)", commands),
        ("KI-Aufrufe in der letzten Minute", llm),
    ]))
    parts.append('<p class="meta">Die Seite zeigt den gespeicherten Stand dieses PCs und aktualisiert '
                 "sich, sobald sich offene Entscheidungen ändern. Schläft der PC oder läuft Mailhelp "
                 "nicht, ist die Weboberfläche nicht erreichbar.</p>")
    return layout("Status", "\n".join(parts), active="/status", fingerprint=overview.fingerprint)


__all__ = ["ANALYSIS_LABELS", "COMMAND_LABELS", "RUN_LABELS", "ServiceInfo", "detail_page", "https_link", "mail_page", "mail_section",
           "overview_page", "proposal_card",
           "relevance_card", "status_page"]
