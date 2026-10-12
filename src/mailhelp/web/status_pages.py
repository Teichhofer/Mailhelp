"""Operating status renderer, independent of proposal and mail rendering."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
from ..review.inbox import CommandStatus
from ..review.views import STATUS_LABELS, Overview, RunStatus, SystemStatus
from .pages import e, layout, notice

RUN_LABELS = (
    ("discovered", "Gefunden"), ("queued", "In Warteschlange"), ("processing", "In Bearbeitung"),
    ("completed", "Abgeschlossen"), ("waiting_for_user", "Warten auf dich"),
    ("failed", "Fehlgeschlagen"), ("skipped", "Übersprungen"),
)

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
    # Live snapshot of the main thread (stage, mail, next poll, contacts) if recorded.
    runtime: dict | None = None
    services: tuple[str, ...] = ()
    fingerprint: str | None = None


RUNTIME_STAGES = {
    "idle": "Leerlauf – wartet auf den nächsten Mailabruf",
    "waiting_for_user": "Wartet auf deine Relevanzentscheidung",
    "failed": "Letzte Verarbeitung fehlgeschlagen",
    "unknown": "Unbekannter Schritt",
}


def _runtime_section(info: ServiceInfo, zone: ZoneInfo) -> str:
    """What the main thread is doing now and the last known successful contacts."""
    from ..review.views import STAGE_LABELS

    runtime = info.runtime
    if runtime is None:
        return ""
    stage = runtime["stage"]
    label = RUNTIME_STAGES.get(stage) or STAGE_LABELS.get(stage) or stage
    rows = [("Schritt", label), ("Seit", _duration(runtime["elapsed"]))]
    mail = runtime.get("mail_id")
    next_poll = runtime.get("next_poll")
    if next_poll:
        rows.append(("Nächster Mailabruf", _when(datetime.fromisoformat(next_poll), zone)))
    section = "<h2>Aktuelle Verarbeitung</h2>" + _facts(rows)
    if mail:
        section += f'<p><a href="/mail/{e(mail)}">Bearbeitete Mail öffnen</a></p>'
    contacts = runtime.get("contacts", {})
    services = list(info.services) + sorted(set(contacts) - set(info.services))
    contact_rows = [(service, ("zuletzt erfolgreich " + _when(datetime.fromisoformat(contacts[service]), zone))
                     if service in contacts else "unbekannt")
                    for service in services]
    section += "<h2>Dienste</h2>" + _facts(contact_rows)
    section += ('<p class="meta">„Unbekannt“: seit dem Start kein belegter erfolgreicher Kontakt. '
                "Die Seite selbst prüft keinen Dienst.</p>")
    return section


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


def _run_section(run: RunStatus, system: SystemStatus, zone: ZoneInfo) -> list[str]:
    """Progress and counters of the last mailbox run."""
    parts: list[str] = []
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
    return parts


def _error_section(system: SystemStatus, zone: ZoneInfo) -> list[str]:
    """The latest stored mail failures with their next automatic attempt."""
    parts: list[str] = []
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
    return parts


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

    parts.append(_runtime_section(info, zone))

    parts.extend(_run_section(run, system, zone))

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

    parts.extend(_error_section(system, zone))

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
    return layout("Status", "\n".join(parts), active="/status",
                  fingerprint=info.fingerprint or overview.fingerprint,
                  state_url="/api/stand?seite=status")

