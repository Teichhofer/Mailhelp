"""Operating status renderer, independent of proposal and mail rendering."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..formatting import duration_text, format_datetime_local
from ..i18n import msg, tr
from ..review.inbox import CommandStatus
from ..review.views import STAGE_LABELS, STATUS_LABELS, Overview, RunStatus, SystemStatus, german_number
from .labels import count_text
from .pages import e, layout, notice, page_head

RUN_LABELS = (
    ("discovered", msg("Gefunden")),
    ("queued", msg("In Warteschlange")),
    ("processing", msg("In Bearbeitung")),
    ("completed", msg("Abgeschlossen")),
    ("waiting_for_user", msg("Warten auf dich")),
    ("failed", msg("Fehlgeschlagen")),
    ("skipped", msg("Übersprungen")),
)

ANALYSIS_LABELS = (
    ("completed", msg("Relevant und ausgewertet")),
    ("irrelevant", msg("Irrelevant")),
    ("duplicate", msg("Doppelt erhalten")),
    ("failed", msg("Fehlgeschlagen")),
    ("skipped", msg("Übersprungen")),
)
COMMAND_LABELS = (
    (CommandStatus.QUEUED, msg("wartend")),
    (CommandStatus.RUNNING, msg("laufend")),
    (CommandStatus.DONE, msg("erledigt")),
    (CommandStatus.REJECTED, msg("abgelehnt")),
    (CommandStatus.FAILED, msg("fehlgeschlagen")),
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
    runtime: dict[str, Any] | None = None
    services: tuple[str, ...] = ()
    fingerprint: str | None = None
    accounts: tuple[tuple[str, str], ...] = ()
    monthly_cost: tuple[str, int] | None = None
    last_polls: tuple[tuple[str, str], ...] = ()
    command_latencies: dict[str, float] | None = None
    acceptance_latencies: dict[str, float] | None = None
    push_warnings: tuple[str, ...] = ()


RUNTIME_STAGES = {
    "idle": msg("Leerlauf – wartet auf den nächsten Mailabruf"),
    "waiting_for_user": msg("Wartet auf deine Relevanzentscheidung"),
    "failed": msg("Letzte Verarbeitung fehlgeschlagen"),
    "unknown": msg("Unbekannter Schritt"),
}


def _runtime_section(info: ServiceInfo, zone: ZoneInfo) -> str:
    """What the main thread is doing now and the last known successful contacts."""

    runtime = info.runtime
    if runtime is None:
        return ""
    stage = runtime["stage"]
    label = RUNTIME_STAGES.get(stage) or STAGE_LABELS.get(stage) or stage
    # 6.1.8: seconds instead of whole minutes, comparable with the usual duration next to it.
    since = duration_text(max(0.0, runtime["elapsed"]))
    if runtime.get("usual_ms"):
        # 6.1.8: e.g. "41 s · üblich 6,0 s" – the median of this step from the step journal.
        since += tr(" · üblich {p0}", p0=duration_text(runtime["usual_ms"] / 1000))
    rows = [(msg("Schritt"), tr(label)), (tr("Seit"), since)]
    mail = runtime.get("mail_id")
    next_poll = runtime.get("next_poll")
    if next_poll:
        rows.append((tr("Nächster Mailabruf"), _when(datetime.fromisoformat(next_poll), zone)))
    section = tr("<h2>Aktuelle Verarbeitung</h2>") + _facts(rows)
    if mail:
        section += tr('<p><a href="/mail/{p0}">Bearbeitete Mail öffnen</a></p>', p0=f"{e(mail)}")
    contacts = runtime.get("contacts", {})
    services = list(info.services) + sorted(set(contacts) - set(info.services))
    contact_rows = [
        (
            service,
            (msg("zuletzt erfolgreich ") + _when(datetime.fromisoformat(contacts[service]), zone))
            if service in contacts
            else msg("unbekannt"),
        )
        for service in services
    ]
    section += tr("<h2>Dienste</h2>") + _facts(contact_rows)
    section += tr(
        '<p class="meta">„Unbekannt“: seit dem Start kein belegter erfolgreicher Kontakt. '
        "Die Seite selbst prüft keinen Dienst.</p>"
    )
    return section


def _when(value: datetime | None, zone: ZoneInfo) -> str:
    return format_datetime_local(value, zone) if value else "—"


def _processed_sentence(system: SystemStatus, zone: ZoneInfo) -> str:
    """5.9.7: e.g. Bisher 1.234 Mails verarbeitet, zuletzt am 12.11.2026, 07:45 Uhr."""
    count = system.mails_processed
    total = tr("Bisher {p0} {p1} verarbeitet", p0=german_number(count),
               p1=msg("Mail") if count == 1 else msg("Mails"))
    if system.last_processed is None:
        return f"{total}."
    return tr("{p0}, zuletzt am {p1}.", p0=f"{total}", p1=f"{_when(system.last_processed, zone)}")


def _imap_error_section(info: ServiceInfo, zone: ZoneInfo) -> str:
    errors = (info.runtime or {}).get("imap_errors", [])
    if not errors:
        return ""
    items = []
    for error in errors:
        kind = tr("Hauptordner") if error["required"] else tr("zusätzlicher Ordner")
        label = tr("Postfach {p0} · {p1}: {p2}", p0=error["mailbox"], p1=kind, p2=error["folder"])
        when = _when(datetime.fromisoformat(error["occurred_at"]), zone)
        items.append(
            f'<li><strong>{e(tr(label))}</strong><br><span class="meta">{e(error["cause"])} · {e(when)}</span></li>'
        )
    return (
        tr('<h2 id="imap-fehler">Aktuelle IMAP-Abruffehler</h2>')
        + notice(
            tr(
                "Mindestens ein Mailordner konnte nicht gelesen werden. "
                "Der letzte Durchlauf kann deshalb unvollständig sein."
            ),
            "error",
        )
        + '<ul class="recent">'
        + "".join(items)
        + "</ul>"
    )


def _duration(seconds: float) -> str:
    minutes = int(seconds // 60)
    days, minutes = divmod(minutes, 24 * 60)
    hours, minutes = divmod(minutes, 60)
    if days:
        return tr("{days} T {hours} Std.", days=days, hours=hours)
    if hours:
        return tr("{hours} Std. {minutes} Min.", hours=hours, minutes=minutes)
    return tr("{minutes} Min.", minutes=minutes)


def _facts(rows: list[tuple[str, str]]) -> str:
    return ('<dl class="facts-table">'
            + "".join(f"<dt>{e(label)}</dt><dd>{e(value)}</dd>" for label, value in rows)
            + "</dl>")


def _stats(items: list[tuple[int, str]]) -> str:
    return (
        '<div class="stats">'
        + "".join(
            f'<div class="stat"><strong>{value}</strong><span>{e(tr(label))}</span></div>' for value, label in items
        )
        + "</div>"
    )


def _status_links(overview: Overview, system: SystemStatus, info: ServiceInfo) -> str:
    items = (
        (len(overview.open), tr("Offene Vorschläge"), "/status/vorschlaege"),
        (len(overview.relevance), tr("Relevanzfragen"), "/status/relevanzfragen"),
        (system.mails_failed, tr("Mails mit Fehler"), "/mails?state=failed"),
        (info.commands.get(CommandStatus.QUEUED, 0), tr("Wartende Web-Aktionen"), "/status/web-aktionen"),
    )
    return (
        tr('<nav class="stats" aria-label="Statusübersichten">')
        + "".join(
            f'<a class="stat status-link" href="{href}"><strong>{value}</strong><span>{e(tr(label))}</span></a>'
            for value, label, href in items
        )
        + "</nav>"
    )


def _run_section(run: RunStatus, system: SystemStatus, zone: ZoneInfo) -> list[str]:
    """Progress and counters of the last mailbox run."""
    parts: list[str] = []
    parts.append(tr("<h2>Letzter Mail-Durchlauf</h2>"))
    progress = (
        tr("{p0} von {p1} Mails analysiert", p0=f"{system.run_finished}", p1=f"{system.run_total}")
        if system.run_total
        else tr("Keine Mails im aktuellen Durchlauf")
    )
    parts.append(
        _facts(
            [
                (tr("Gestartet"), _when(run.started_at, zone)),
                (msg("Stand"), (tr("abgeschlossen") if run.run_complete else tr("läuft noch")) + f" · {progress}"),
            ]
        )
    )
    if system.run_total:
        parts.append(
            tr(
                (
                    '<progress class="run-progress" max="{p0}" value="{p1}" '
                    'aria-label="Fortschritt des Durchlaufs">{p2} von {p3}</progress>'
                ),
                p0=f"{system.run_total}",
                p1=f"{system.run_finished}",
                p2=f"{system.run_finished}",
                p3=f"{system.run_total}",
            )
        )
    parts.append(_stats([(run.counters.get(key, 0), label) for key, label in RUN_LABELS]))
    if system.analysis:
        parts.append(tr("<h3>Ergebnis der Analyse</h3>"))
        parts.append(_stats([(system.analysis.get(key, 0), label) for key, label in ANALYSIS_LABELS]))
    return parts


def _error_section(system: SystemStatus, zone: ZoneInfo) -> list[str]:
    """The latest stored mail failures with their next automatic attempt."""
    parts: list[str] = []
    parts.append(tr("<h2>Letzte Fehler und Handlungsbedarf</h2>"))
    if system.errors:
        items = []
        for error in system.errors:
            retry = tr(" · wird automatisch wiederholt") if error.retryable else ""
            if error.attempts:
                retry = tr(" · aufgegeben") if error.abandoned else tr(" · wird erneut versucht")
                retry += tr(" ({p0} von 5 Versuchen)", p0=f"{error.attempts}")
                retry += tr(" · seit {p0}", p0=_when(error.first_failed_at, zone))
            if error.next_attempt is not None:
                retry += tr(" · nächster Versuch: {p0}", p0=_when(error.next_attempt, zone))
            items.append(
                f'<li><span><a href="/mail/{e(error.mail_id)}">{e(error.subject)}</a><br>'
                f'<span class="meta">{e(error.cause)} · {e(error.stage)} · '
                f'{e(_when(error.occurred_at, zone))}{retry}</span></span></li>')
        parts.append(f'<ul class="recent">{"".join(items)}</ul>')
    else:
        parts.append(tr('<p class="meta">Keine Fehler bei gespeicherten Mails.</p>'))
    return parts


def _verdict(overview: Overview, system: SystemStatus, info: ServiceInfo) -> str:
    """6.2.9 (UI-08): one line on top – everything fine, or what needs attention with a way to it."""
    problems = []
    if system.mails_failed:
        failed = count_text(system.mails_failed, tr("Mail mit Fehler"), tr("Mails mit Fehler"))
        problems.append(f'<a href="/mails?state=failed">{failed}</a>')
    imap = len((info.runtime or {}).get("imap_errors", []))
    if imap:
        problems.append(f'<a href="#imap-fehler">{count_text(imap, tr("Abruffehler"), tr("Abruffehler"))}</a>')
    if overview.damaged:
        problems.append(
            e(count_text(overview.damaged, tr("beschädigter Datensatz"), tr("beschädigte Datensätze")))
            + tr(" – bitte Protokolle prüfen")
        )
    if not problems:
        return tr(
            '<p class="notice notice-ok status-verdict" role="status"><strong>Alles in Ordnung.</strong> '
            "Keine Mailfehler, keine Abruffehler und keine beschädigten Datensätze.</p>"
        )
    kind = "error" if overview.damaged else "warn"
    return (
        tr(
            ('<p class="notice notice-{p0} status-verdict" role="alert"><strong>Handlungsbedarf:</strong> '),
            p0=f"{kind}",
        )
        + " · ".join(problems)
        + "</p>"
    )


def _service_details(info: ServiceInfo, zone: ZoneInfo) -> list[str]:
    """Version, mode, runtime, costs, last polls and configured accounts."""
    parts: list[str] = []
    parts.append("<h2>Mailhelp</h2>")
    parts.append(
        _facts(
            [
                (tr("Version"), info.version),
                (tr("Modus"), tr("Testmodus – Einträge werden nur simuliert" if info.test_mode else "Produktiv")),
                (
                    tr("Läuft seit"),
                    f"{_when(info.started_at, zone)} ({_duration((info.now - info.started_at).total_seconds())})",
                ),
                (msg("Weboberfläche"), info.address),
                (tr("Gekoppelte Geräte"), str(info.devices)),
            ]
        )
    )

    parts.append(_runtime_section(info, zone))
    if info.monthly_cost is not None:
        usd, unknown = info.monthly_cost
        parts.append(
            tr("<h2>Kosten im laufenden Monat</h2>")
            + _facts([(tr("Erfasste Cloudkosten (USD)"), usd), (tr("Aufrufe ohne Kostenangabe"), str(unknown))])
        )
    if info.last_polls:
        parts.append(tr("<h2>Letzte Abfrage je Postfach</h2>") + _facts(list(info.last_polls)))
    if info.accounts:
        parts.append(tr("<h2>Konfigurierte Konten</h2>") + _facts(list(info.accounts)))
        parts.append(
            tr(
                '<p class="meta">Beobachteter Stand seit Dienststart; diese Seite führt keine '
                "Verbindungsprüfung aus. Geänderte Verbindungen werden über „Konfiguration neu laden“ aktiviert; "
                "nicht übernommene Einrichtungsentwürfe sind nicht enthalten.</p>"
            )
        )
    return parts


def _mail_and_proposal_details(system: SystemStatus, zone: ZoneInfo) -> list[str]:
    """Counters of stored mails and proposals."""
    parts: list[str] = []
    parts.append(tr("<h2>Mails</h2>"))
    parts.append(
        _facts(
            [
                (tr("Verarbeitet (abgeschlossen)"), german_number(system.mails_processed)),
                (tr("Gespeichert (alle Zustände)"), german_number(system.mails_total)),
                (tr("Zuletzt verarbeitet"), _when(system.last_processed, zone)),
                (tr("Warten auf Relevanzentscheidung"), str(system.mails_waiting_relevance)),
                (tr("Zurückgestellt (neuer Versuch später)"), str(system.mails_deferred)),
            ]
        )
    )

    parts.append(tr("<h2>Vorschläge</h2>"))
    if system.proposals:
        parts.append(
            _stats(
                [
                    (
                        system.proposals[status] - (system.already_done if status.value == "rejected" else 0),
                        STATUS_LABELS[status],
                    )
                    for status in STATUS_LABELS
                    if status in system.proposals
                ]
                + ([(system.already_done, tr("Schon erledigt"))] if system.already_done else [])
            )
        )
    else:
        parts.append(tr('<p class="meta">Noch keine Vorschläge gespeichert.</p>'))
    return parts


def _channel_details(info: ServiceInfo, system: SystemStatus) -> list[str]:
    """Telegram, web actions and the AI call budget."""
    parts: list[str] = []
    parts.append(tr("<h2>Telegram, Web und KI</h2>"))
    if info.acceptance_latencies:
        values = info.acceptance_latencies
        parts.append(
            _facts(
                [
                    (
                        tr("Web-Aktionen: Annahmezeit (letzte 20 gemessene)"),
                        f"Median {values['median_ms']:.1f} ms · Maximum {values['max_ms']:.1f} ms",
                    ),
                ]
            )
        )
    if info.command_latencies:
        values = info.command_latencies
        parts.append(
            _facts(
                [
                    (
                        tr("Web-Aktionen: Wartezeit bis Beginn (letzte 20 gemessene)"),
                        f"Median {values['median_ms']:.1f} ms · Maximum {values['max_ms']:.1f} ms",
                    ),
                ]
            )
        )
    commands = ", ".join(f"{info.commands.get(status, 0)} {tr(label)}" for status, label in COMMAND_LABELS)
    llm = (
        tr("{p0} von höchstens {p1}", p0=system.llm_calls_last_minute, p1=info.llm_calls_per_minute)
        if info.llm_calls_per_minute
        else str(system.llm_calls_last_minute)
    )
    parts.append(
        _facts(
            [
                (tr("Zurückgehaltene Telegram-Nachrichten"), str(system.telegram_held)),
                (tr("Unverarbeitete Telegram-Eingänge"), str(system.telegram_unprocessed)),
                (tr("Web-Aktionen (letzte 24 Std.)"), commands),
                (tr("KI-Aufrufe in der letzten Minute"), llm),
            ]
        )
    )
    return parts


def status_page(run: RunStatus, overview: Overview, configured_timezone: str,
                system: SystemStatus, info: ServiceInfo) -> str:
    zone = ZoneInfo(configured_timezone)
    parts = [page_head("Status", msg("Einblicke"), tr("Ob Mailhelp arbeitet und wo etwas zu tun ist."))]
    parts.extend(notice(text, "warn") for text in info.push_warnings)
    # An unreadable source must remain visible before any technical disclosure.
    parts.append(_imap_error_section(info, zone))
    parts.append(_verdict(overview, system, info))
    parts.extend(_error_section(system, zone))
    parts.append(_status_links(overview, system, info))
    parts.append(
        tr(
            (
                '<section class="card status-summary"><p>{p0}</p><p><a class="button" '
                'href="/dienst/selbsttest">Verbindungen lesend prüfen</a> <a class="button" '
                'href="/">Offene Entscheidungen bearbeiten</a></p><p '
                'class="meta">„Verbunden“ bezeichnet nur die Verbindung zwischen Browser '
                "und Mailhelp. Kalender, Aufgabenanbieter und Mailzugänge sind damit nicht "
                "geprüft.</p></section>"
            ),
            p0=f"{e(_processed_sentence(system, zone))}",
        )
    )

    parts.append(tr('<details class="status-details"><summary>Betriebsdetails und Zähler anzeigen</summary>'))
    parts.extend(_service_details(info, zone))
    parts.extend(_run_section(run, system, zone))

    parts.extend(_mail_and_proposal_details(system, zone))
    parts.extend(_channel_details(info, system))
    parts.append(
        tr(
            '<p class="meta">Die Seite zeigt den gespeicherten Stand dieses PCs und aktualisiert '
            "sich, sobald sich offene Entscheidungen ändern. Schläft der PC oder läuft Mailhelp "
            "nicht, ist die Weboberfläche nicht erreichbar.</p>"
        )
    )
    parts.append('</details>')
    return layout("Status", "\n".join(parts), active="/status",
                  fingerprint=info.fingerprint or overview.fingerprint,
                  state_url="/api/stand?seite=status")
