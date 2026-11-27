"""HTML of the settings and topic pages; no routing, no file access."""

from __future__ import annotations

import json
import secrets
from typing import Any

from pydantic import BaseModel

from ..config import Settings
from ..config.configuration import LIVE_FIELDS, SETTINGS_FIELDS
from ..i18n import msg, tr
from ..runtime.credentials import CredentialSnapshot
from .credential_pages import credentials_section
from .forms import field, post_form, select
from .pages import e, notice, page_head
from .setting_help import EXTRA_HELP, SETTING_HELP, help_bubble
from .settings_search import anchor, search

SETTING_LABELS = {
    "poll_interval_seconds": msg("Abrufintervall (Sekunden)"),
    "timezone": msg("Zeitzone"),
    "language": msg("Sprache der Oberfläche"),
    "test_mode": msg("Trockenlauf"),
    "limits.llm_calls_per_minute": msg("KI-Aufrufe pro Minute"),
    "limits.max_mail_bytes": msg("Maximale Mailgröße (Bytes)"),
    "limits.max_attachment_bytes": msg("Texterkennung: maximale Anhanggröße (Bytes)"),
    "limits.max_llm_payload_bytes": msg("Maximale KI-Anfragegröße (Bytes)"),
    "retention.full_mail_days": msg("Mailtexte aufbewahren (Tage)"),
    "retention.debug_llm_days": msg("KI-Diagnosedaten aufbewahren (Tage)"),
    "retention.analysis_days": msg("Analysen aufbewahren (Tage)"),
    "retention.history_days": msg("Verlauf aufbewahren (Tage)"),
    "metrics.ollama_power_watts": msg("Ollama-Leistung (Watt)"),
    "metrics.electricity_eur_per_kwh": msg("Strompreis (EUR/kWh)"),
    "metrics.retention_days": msg("Einzelmessungen aufbewahren (Tage)"),
    "metrics.enabled": msg("Metrikerfassung aktivieren"),
    "personal_info": msg("Persönliche Angaben für Antworten"),
}
# Free text settings: edited in a text area and never parsed as JSON.
TEXT_SETTINGS = {
    "personal_info": (
        msg(
            "Zum Beispiel Name, Rolle, Signatur oder gewünschte Anrede. Die Angaben gehen "
            "nur in Antwort-Entwürfe ein und werden dafür an das KI-Modell übergeben."
        )
    )
}
SETTING_GROUPS = (
    (msg("Mailabruf und Betrieb"), ("poll_interval_seconds", "timezone", "language", "test_mode", "imap.")),
    (msg("Antworten"), ("personal_info", "smart_reply", "auto_draft", "drafts.")),
    ("Telegram", ("telegram.",)),
    (msg("Bildauswertung"), ("vision.",)),
    (msg("Tagesüberblick"), ("daily_briefing.",)),
    (msg("Postfach-Briefings"), ("briefings.",)),
    (msg("Tätigkeitsberichte"), ("activity_report.",)),
    (msg("Lernmodus"), ("learning.",)),
    (msg("Hilfschat"), ("help_chat.",)),
    (msg("Weboberfläche"), ("web.",)),
    (msg("Termindauern und Vorschlagsabgleich"), ("event_defaults.", "proposal_reconciliation.")),
    (msg("Ziele"), ("targets.",)),
    (msg("Originalanhänge"), ("attachments.",)),
    (msg("Aufrufbudget und Mailgrenzen"), ("limits.",)),
    (msg("Zeitlimits und Wiederholungen"), ("timeouts.", "retries.")),
    (msg("Aufbewahrung"), ("retention.",)),
    (msg("Protokollierung"), ("logging.",)),
    (msg("Kosten und Messung"), ("metrics.",)),
)
SERVICE_LABELS = {
    "imap": msg("IMAP"),
    "telegram": msg("Telegram"),
    "openrouter": msg("OpenRouter"),
    "ollama": msg("Ollama"),
    "todoist": msg("Todoist"),
    "google_calendar": msg("Google Kalender"),
    "caldav": msg("CalDAV"),
    "microsoft": msg("Microsoft 365"),
    "google_tasks": msg("Google Tasks"),
    "notion": msg("Notion"),
}
TIMEOUT_LABELS = {
    "timeout_seconds": msg("Zeitlimit (s)"),
    "retries": msg("Wiederholungen"),
    "initial_backoff_seconds": msg("erste Wartezeit (s)"),
    "max_backoff_seconds": msg("längste Wartezeit (s)"),
}
EXTRA_LABELS = {
    "event_defaults.video_duration_minutes": msg("Standarddauer Videokonferenz (Minuten)"),
    "event_defaults.in_person_duration_minutes": msg("Standarddauer Präsenztermin (Minuten)"),
    "proposal_reconciliation.max_semantic_candidates": msg("Abgleich: höchstens KI-Kandidaten"),
    "targets.todoist_project": msg("Todoist-Projekt"),
    "targets.google_calendar": msg("Google-Kalender"),
    "targets.calendar_provider": msg("Kalenderdienst"),
    "targets.task_provider": msg("Aufgabendienst"),
    "targets.caldav_calendar_url": msg("CalDAV-Kalender (Adresse)"),
    "targets.caldav_task_url": msg("CalDAV-Aufgabenliste (Adresse)"),
    "targets.outlook_calendar": msg("Outlook-Kalender"),
    "targets.microsoft_todo_list": msg("Microsoft-To-Do-Liste"),
    "targets.microsoft_tenant": msg("Microsoft-Mandant"),
    "targets.google_tasks_list": msg("Google-Tasks-Liste"),
    "targets.calendar_reminder_enabled": msg("Kalendererinnerung hinzufügen"),
    "targets.calendar_reminder_minutes": msg("Minuten vor Beginn"),
    "attachments.store_originals": msg("Originale speichern"),
    "attachments.max_original_bytes": msg("Höchstgröße je Datei (Bytes)"),
    "attachments.max_total_bytes": msg("Höchstgröße je Mail (Bytes)"),
    "logging.console.level": msg("Konsole: Mindeststufe"),
    "logging.file.level": msg("Logdatei: Mindeststufe"),
    "logging.llm.include_requests": msg("KI-Anfragen vollständig protokollieren"),
    "logging.llm.include_responses": msg("KI-Antworten vollständig protokollieren"),
    "metrics.usd_per_eur": msg("Wechselkurs (USD je EUR)"),
    "metrics.exchange_rate_date": msg("Wechselkurs vom"),
    "retries.interpretation_attempts": msg("Antworten verstehen: Versuche"),
    "retries.interpretation_backoff_seconds": msg("Antworten verstehen: Wartezeit (s)"),
    "retries.revision_attempts": msg("Überarbeitung: Versuche"),
    "retries.revision_backoff_seconds": msg("Überarbeitung: Wartezeit (s)"),
    "imap.batch_size": msg("Mails je Abrufdurchlauf"),
    "imap.global_newest_first": msg("Neueste Mails zuerst (alle Postfächer)"),
    "telegram.user_id": msg("Telegram: berechtigte Benutzer-ID"),
    "telegram.chat_id": msg("Telegram: Chat für Nachrichten"),
    "telegram.sequential_questions": msg("Telegram: Entscheidungen nacheinander"),
    "smart_reply": msg("Antwortentwürfe anbieten"),
    "briefings.enabled": msg("Briefings als Postfachentwurf aktivieren"),
    "briefings.times": msg("Uhrzeiten für Postfach-Briefings"),
    "briefings.mailbox": msg("Zielpostfach für Briefings"),
    "briefings.skip_empty": msg("Leere Postfach-Briefings auslassen"),
    "auto_draft": msg("Antwortentwürfe automatisch im Postfach ablegen"),
    "drafts.enabled": msg("Antwortentwürfe zulassen"),
    "drafts.folder": msg("Entwurfsordner überschreiben (null: Postfachvorgabe)"),
    "vision.enabled": msg("Bildanhänge und Scans auswerten"),
    "help_chat.enabled": msg("Hilfschat anbieten"),
    "help_chat.max_question_chars": msg("Hilfschat: längste Frage (Zeichen)"),
    "help_chat.max_context_bytes": msg("Hilfschat: Dokumentation je Frage (Bytes)"),
    "help_chat.requests_per_minute_per_session": msg("Hilfschat: Fragen je Minute"),
    "vision.max_images_per_mail": msg("Bildauswertung: Bilder je Mail"),
    "vision.max_image_bytes": msg("Bildauswertung: Höchstgröße je Bild (Bytes)"),
    "vision.max_edge_pixels": msg("Bildauswertung: längste Kante (Pixel)"),
    "daily_briefing.include_calendar": msg("Tagesüberblick: Termine"),
    "daily_briefing.include_tasks": msg("Tagesüberblick: Aufgaben"),
    "daily_briefing.include_open": msg("Tagesüberblick: offene Entscheidungen"),
    "activity_report.enabled": msg("Tätigkeitsberichte aktivieren"),
    "activity_report.max_mails": msg("Tätigkeitsbericht: höchstens Mails"),
    "activity_report.max_llm_calls": msg("Tätigkeitsbericht: höchstens KI-Aufrufe"),
    "activity_report.max_share_of_llm_budget": msg("Tätigkeitsbericht: Anteil am KI-Budget"),
    "activity_report.max_fulltext_chars": msg("Tätigkeitsbericht: Zeichen je Volltext"),
    "activity_report.export_mails_without_events": msg("Tätigkeitsbericht: Mails ohne Termine exportieren"),
    "learning.parallel_llm_calls": msg("Lernmodus: parallele KI-Aufrufe"),
    "web.session_days": msg("Web: Sitzungsdauer (Tage)"),
    "web.lan_access": msg("Web: Zugriff im eigenen Netzwerk"),
    "logging.console.enabled": msg("Konsolenausgabe aktivieren"),
    "logging.verbose": msg("Ausführliches Protokoll"),
    "logging.file.enabled": msg("Logdatei aktivieren"),
    "logging.llm.enabled": msg("KI-Log aktivieren"),
    "logging.llm.level": msg("KI-Log: Mindeststufe"),
    "logging.telegram.enabled": msg("Telegram-Log aktivieren"),
    "logging.telegram.level": msg("Telegram-Log: Mindeststufe"),
    "retention.activity_report_days": msg("Tätigkeitsberichte aufbewahren (Tage)"),
    "retention.decision_learning_days": msg("Lernbestand der Entscheidungen aufbewahren (Tage)"),
    "retention.cleanup_interval_minutes": msg("Bereinigung alle (Minuten)"),
    "learning.decision_llm_content": msg("Lernbestand: vollständige KI-Inhalte übernehmen"),
}
LEVEL_CHOICES = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
PROVIDER_CHOICES = {
    "language": (("de", msg("Deutsch")), ("en", msg("English"))),
    "targets.calendar_provider": (
        ("google", msg("Google Kalender")),
        ("caldav", msg("CalDAV (Nextcloud, iCloud, …)")),
        ("outlook", msg("Outlook / Microsoft 365")),
    ),
    "targets.task_provider": (
        ("todoist", msg("Todoist")),
        ("microsoft_todo", msg("Microsoft To Do")),
        ("caldav", msg("CalDAV-Aufgaben (VTODO)")),
        ("apple_reminders", msg("Apple Erinnerungen (iCloud)")),
        ("google_tasks", msg("Google Tasks")),
        ("notion", msg("Notion")),
    ),
}


def setting_label(name: str) -> str:
    if name in SETTING_LABELS or name in EXTRA_LABELS:
        return SETTING_LABELS.get(name) or EXTRA_LABELS[name]
    _, service, key = name.split(".")
    return f"{SERVICE_LABELS[service]}: {TIMEOUT_LABELS[key]}"


def _lookup(values: dict[str, Any] | None, name: str) -> object:
    for part in name.split("."):
        values = values.get(part) if isinstance(values, dict) else None
    return values


def _shown(name: str, value: object) -> str:
    """A readable value; target IDs are masked, missing values marked."""
    if value is None or value == "":
        return msg("nicht gesetzt")
    if name in TEXT_SETTINGS:
        line = " ".join(str(value).split())
        return line if len(line) <= 60 else line[:59] + "…"
    if isinstance(value, bool):
        return "ja" if value else msg("nein")
    text = str(value)
    if name in PROVIDER_CHOICES:
        return dict(PROVIDER_CHOICES[name]).get(text, text)
    if name.startswith("targets.") and len(text) > 8:
        return f"{text[:3]}…{text[-3:]}"
    return text


def _input(name: str, saved: object, raw: dict[str, Any] | None = None, *, key: str = "value",
           label: str | None = None) -> str:
    """The control of one setting; *key* is the form field (8.5: ``setting:<name>`` in section forms)."""
    label = label or msg("Neuer Wert")
    if name == "briefings.times":
        return field(key, label, ", ".join(saved if isinstance(saved, list) else []))
    if name == "briefings.mailbox":
        boxes = (raw or {}).get("imap", {}).get("mailboxes") or [{"id": 1, "label": "Standard"}]
        options = [("default", msg("Erstes aktives Postfach"))] + [
            (str(box["id"]), box["label"]) for box in boxes if box.get("enabled", True)
        ]
        return select(key, label, str(saved or "default"), options)
    if name in TEXT_SETTINGS:
        return (f'<label>{label}<textarea name="{e(key)}" rows="6" maxlength="2000">{e(saved or "")}</textarea>'
                f'</label><p class="meta">{e(TEXT_SETTINGS[name])}</p>')
    if isinstance(saved, bool):
        return select(key, label, json.dumps(saved), [("true", msg("Ja")), ("false", msg("Nein"))])
    if name.endswith(".level"):
        return select(key, label, saved, [(level, level) for level in LEVEL_CHOICES])
    if name in PROVIDER_CHOICES:
        return select(key, label, saved, list(PROVIDER_CHOICES[name]))
    if name == "targets.calendar_reminder_minutes":
        shown = "" if saved is None else saved
        inactive = (raw or {}).get("targets", {}).get("calendar_reminder_enabled") is False
        off = tr("Kalendererinnerung ist aktuell deaktiviert; dieser Minutenwert bleibt als Vorbereitung gespeichert.")
        hint = f'<p class="meta">{e(off)}</p>' if inactive else ""
        return (f'<label>{label}<input type="number" min="0" max="1440" step="1" name="{e(key)}" '
                f'value="{e(shown)}" required></label>{hint}')
    kind = "number" if isinstance(saved, (int, float)) else "text"
    step = ' step="any"' if kind == "number" else ""
    shown = "" if saved is None else saved
    # 8.5: an optional value may stay empty; required would block the whole section form.
    required = "" if saved is None else " required"
    return (f'<label>{label}<input type="{kind}"{step} name="{e(key)}" value="{e(shown)}" '
            f'maxlength="200"{required}></label>')


def _models_table(models: list[tuple[str, str, str, str]]) -> str:
    if not models:
        return tr('<p class="meta">Keine Modellangaben verfügbar.</p>')
    return (
        tr(
            
                '<div class="table-scroll"><table><thead><tr><th>Schritt</th><th>Modell</th>'
                "<th>Parameter</th><th>Quelle</th></tr></thead><tbody>"
            
        )
        + "".join(
            f"<tr><td>{e(step)}</td><td>{e(model)}</td><td>{e(parameters or '—')}</td><td>{e(source)}</td></tr>"
            for step, model, parameters, source in models
        )
        + "</tbody></table></div>"
    )


def _setting_row(name: str, raw: dict[str, Any], active: dict[str, Any] | None, revision: str, csrf: str) -> str:
    current, saved = _lookup(active, name), _lookup(raw, name)
    live = name.split(".")[0] in LIVE_FIELDS
    if current == saved:
        state = msg("aktiv")
    else:
        state = (
            msg("gespeichert – wird an der nächsten sicheren Stelle übernommen")
            if live
            else msg("gespeichert – wirkt erst nach einem Neustart")
        )
    timing = msg("sofort nach dem Speichern") if live else msg("beim nächsten Start")
    form = post_form(
        "/einstellungen/speichern", csrf, _input(name, saved, raw), msg("Prüfen"), name=name, expected_hash=revision
    )
    return (
        tr(
            (
                '<div class="setting-row" id="{p0}"><details '
                'class="setting"><summary><span>{p1}</span><strong>{p2}</strong></'
                'summary><p class="meta">Gespeichert: {p3} · {p4} · Änderungen '
                "wirken {p5}.</p>{p6}</details>"
            ),
            p0=anchor(name),
            p1=e(setting_label(name)),
            p2=e(_shown(name, current)),
            p3=e(_shown(name, saved)),
            p4=e(state),
            p5=e(timing),
            p6=form,
        )
        + help_bubble(name, setting_label(name), SETTING_HELP[name])
        + tr('<a class="ask-help" href="/hilfe?einstellung={p0}">Dazu fragen</a></div>', p0=e(name))
    )


NO_DEFAULT = object()
# 8.5: section forms send each value as ``setting:<name>``; the prefix keeps them apart from the form's own fields.
SETTING_PREFIX = "setting:"


def default_value(name: str) -> object:
    """The value a missing setting takes, as JSON; :data:`NO_DEFAULT` for required settings."""
    model: Any = Settings
    value: Any = NO_DEFAULT
    for part in name.split("."):
        if model is None:  # below a plain default value (a dictionary)
            value = value.get(part, NO_DEFAULT) if isinstance(value, dict) else NO_DEFAULT
            if value is NO_DEFAULT:
                return NO_DEFAULT
            continue
        info = model.model_fields.get(part)
        if info is None:
            return NO_DEFAULT
        if info.is_required():
            # A required section still gives its own fields defaults (e.g. ``limits``).
            section = info.annotation
            if not (isinstance(section, type) and issubclass(section, BaseModel)):
                return NO_DEFAULT
            model = section
            continue
        default = info.get_default(call_default_factory=True)
        if isinstance(default, BaseModel):
            model, value = type(default), default.model_dump(mode="json")
        else:
            model, value = None, default
    return value


def _badges(name: str, raw: dict[str, Any], active: dict[str, Any] | None) -> str:
    saved, current = _lookup(raw, name), _lookup(active, name)
    live = name.split(".")[0] in LIVE_FIELDS
    parts = [msg("wirkt sofort") if live else msg("wirkt nach Neustart")]
    default = default_value(name)
    if default is not NO_DEFAULT:
        parts.append(msg("Standard") if saved == default
                     else tr("angepasst (Standard: {p0})", p0=_shown(name, default)))
    if active is not None and current != saved:
        parts.append(msg("gespeichert, noch nicht aktiv"))
    return " · ".join(e(part) for part in parts)


def _field_row(name: str, raw: dict[str, Any], active: dict[str, Any] | None) -> str:
    """One labelled control of a section form with its effect, default state and help."""
    saved = _lookup(raw, name)
    label = setting_label(name)
    default = default_value(name)
    reset = ""
    if default is not NO_DEFAULT and saved != default:
        reset = (f'<button class="button small link-button" name="zuruecksetzen" value="{e(name)}">'
                 f'{e(tr("Auf Standard zurücksetzen"))}</button>')
    return (
        f'<div class="setting-field" id="{anchor(name)}">'
        + _input(name, saved, raw, key=SETTING_PREFIX + name, label=label)
        + help_bubble(name, label, SETTING_HELP[name])
        + f'<p class="meta setting-badges">{_badges(name, raw, active)} · '
        + f'<a class="ask-help" href="/hilfe?einstellung={e(name)}">{e(tr("Dazu fragen"))}</a></p>'
        + reset
        + f'<details class="setting-technical"><summary>{e(tr("Technische Details"))}</summary>'
        + f'<p class="meta"><code>{e(name)}</code> · {e(tr("gespeichert"))}: {e(_shown(name, saved))} · '
        + f'{e(tr("aktiv"))}: {e(_shown(name, _lookup(active, name)))}</p></details></div>'
    )


def _timeouts_table(names: list[str], raw: dict[str, Any], active: dict[str, Any] | None) -> str:
    """8.5: the timeouts of all services as one table: a row per service, a column per value."""
    services = sorted({name.split(".")[1] for name in names}, key=lambda service: str(SERVICE_LABELS[service]))
    head = "".join(f'<th scope="col">{e(TIMEOUT_LABELS[key])}</th>' for key in TIMEOUT_LABELS)
    rows = ""
    for service in services:
        cells = ""
        for key in TIMEOUT_LABELS:
            name = f"timeouts.{service}.{key}"
            value = _lookup(raw, name)
            identity = "help-" + name.replace(".", "-")
            cells += (f'<td><input type="number" step="any" name="{e(SETTING_PREFIX + name)}" value="{e(value)}" '
                      f'aria-label="{e(setting_label(name))}" aria-describedby="{e(identity)}" id="{anchor(name)}" '
                      f'required><span class="visually-hidden" id="{e(identity)}">{e(SETTING_HELP[name])}</span></td>')
        rows += f'<tr><th scope="row">{e(SERVICE_LABELS[service])}</th>{cells}</tr>'
    pending = [f"{setting_label(name)}: {_shown(name, _lookup(raw, name))}" for name in names
               if active is not None and _lookup(active, name) != _lookup(raw, name)]
    note = (f'<p class="meta">{e(tr("Gespeichert, noch nicht aktiv"))}: {e("; ".join(pending))}</p>'
            if pending else "")
    # A scrolling wrapper is reachable by keyboard (axe: scrollable-region-focusable).
    return (f'<div class="table-scroll" tabindex="0" role="region" aria-label="{e(tr("Zeitlimits"))}">'
            f'<table class="timeouts-table"><thead><tr><th scope="col">'
            f'{e(tr("Dienst"))}</th>{head}</tr></thead><tbody>{rows}</tbody></table></div>'
            f'<p class="meta">{e(tr("Zeitlimits und Wartezeiten in Sekunden; wirken nach einem Neustart."))}</p>'
            + note)


def _section(group: str, raw: dict[str, Any], active: dict[str, Any] | None, revision: str, csrf: str,
             area: str, names: list[str] | None = None, action: str = "/einstellungen/speichern") -> str:
    """8.5: one form per section; only changed values are taken over on the review page.

    8.8.2: *names* and *action* give the customer page ``/einstellungen/allgemein`` its own form.
    """
    names = _names(group) if names is None else names
    timeouts = [name for name in names if name.startswith("timeouts.")]
    fields = "".join(_field_row(name, raw, active) for name in names if name not in timeouts)
    if timeouts:
        fields += _timeouts_table(timeouts, raw, active)
    bar = (f'<div class="settings-savebar" data-settings-savebar><span class="meta" data-settings-changes '
           f'role="status" aria-live="polite"></span><button class="button primary">{e(tr("Änderungen prüfen"))}'
           f'</button></div>')
    hidden = (field("csrf", "", csrf, hidden=True) + field("key", "", secrets.token_hex(16), hidden=True)
              + field("expected_hash", "", revision, hidden=True) + field("bereich", "", area, hidden=True))
    return (f'<section class="settings-section"><h2>{e(group)}</h2><form method="post" '
            f'action="{action}" class="stack settings-form" data-settings-form>{hidden}'
            f'{fields}{bar}</form></section>')


# Areas of /einstellungen?bereich=…: (key, title, description, groups of SETTING_GROUPS).
# 8.5: grouped by the user's tasks; rarely needed values are under "Erweitert".
AREAS = (
    (
        "allgemein",
        msg("Allgemein"),
        msg("Sprache, Zeitzone, Abrufintervall und Trockenlauf"),
        (msg("Mailabruf und Betrieb"),),
    ),
    (
        'benachrichtigungen',
        msg("Benachrichtigungen"),
        msg("Telegram, Tagesüberblick und Postfach-Briefings"),
        (msg("Telegram"), msg("Tagesüberblick"), msg("Postfach-Briefings")),
    ),
    (
        'antworten',
        msg("Antworten und Termine"),
        msg("Antwortentwürfe, persönliche Angaben, Termindauern und Ziele"),
        (msg("Antworten"), msg("Termindauern und Vorschlagsabgleich"), msg("Ziele")),
    ),
    (
        "ki",
        msg("KI und Auswertung"),
        msg("Modelle, Bildauswertung, Lernmodus, Hilfschat, Tätigkeitsberichte und Kosten"),
        (
            msg("Bildauswertung"),
            msg("Lernmodus"),
            msg("Hilfschat"),
            msg("Tätigkeitsberichte"),
            msg("Kosten und Messung"),
        ),
    ),
    (
        'daten',
        msg("Daten und Datenschutz"),
        msg("Originalanhänge, Aufbewahrung und Protokollierung"),
        (msg("Originalanhänge"), msg("Aufbewahrung"), msg("Protokollierung")),
    ),
    (
        "erweitert",
        msg("Erweitert"),
        msg("Aufrufbudget, Mailgrenzen, Zeitlimits, Wiederholungen, Weboberfläche und System"),
        (msg("Aufrufbudget und Mailgrenzen"), msg("Zeitlimits und Wiederholungen"), msg("Weboberfläche")),
    ),
)
CREDENTIALS_AREA = 'zugangsdaten'
AREA_KEYS = frozenset({key for key, *_ in AREAS} | {CREDENTIALS_AREA})
# 8.8.2: the customer's own page; its forms carry this area and lead back to it.
GENERAL_AREA, GENERAL_PATH = "kunde-allgemein", "/einstellungen/allgemein"


def settings_back(area: str) -> str:
    """Where a settings form returns to: its area, the customer page or the overview."""
    if area == GENERAL_AREA:
        return GENERAL_PATH
    return "/einstellungen?bereich=" + area if area in AREA_KEYS else "/einstellungen"
# 8.5: addresses of the former areas lead to the area that holds their settings now.
LEGACY_AREAS = {"abruf": "allgemein", "briefing": "benachrichtigungen", "system": "erweitert"}
_GROUPS = dict(SETTING_GROUPS)


def _names(group: str) -> list[str]:
    return sorted(name for name in SETTINGS_FIELDS
                  if any(name == prefix or name.startswith(prefix) for prefix in _GROUPS[group]))


def _tile(href: str, title: str, text: str, extra: str = "", kind: str = "") -> str:
    return (f'<a class="settings-tile{" " + kind if kind else ""}" href="{e(href)}"><strong>{e(title)}</strong>'
            f'<span>{e(text)}</span>{extra}</a>')


def _tiles(title: str, tiles: str) -> str:
    return f'<section class="settings-section"><h2>{e(title)}</h2><div class="settings-tiles">{tiles}</div></section>'


def _nav(current: str) -> str:
    entries = [("/einstellungen", msg("Übersicht"), "")] + [
        ('/einstellungen?bereich={p0}'.format(p0=f'{key}'), title, key) for key, title, *_ in AREAS
    ]
    entries.append((f'/einstellungen?bereich={CREDENTIALS_AREA}', msg("Zugangsdaten"), CREDENTIALS_AREA))
    links = "".join(f'<a href="{href}"{' aria-current="page"' if key == current else ""}>{e(title)}</a>'
                    for href, title, key in entries)
    # 8.5: on a phone one compact choice instead of nine buttons; a GET form works without JavaScript.
    options = "".join(f'<option value="{e(key)}"{" selected" if key == current else ""}>{e(title)}</option>'
                      for _href, title, key in entries)
    chooser = (f'<form method="get" action="/einstellungen" class="settings-chooser"><label>'
               f'{e(tr("Bereich"))}<select name="bereich">{options}</select></label>'
               f'<button class="button small">{e(tr("Öffnen"))}</button></form>')
    return (tr('<nav class="settings-index" aria-label="Einstellungsbereiche"><p class="eyebrow">Bereiche</p>')
            + links + "</nav>" + chooser)


def _search(query: str) -> str:
    """The search form; with JavaScript, matches appear below it while typing (5.3)."""
    return tr(
        (
            '<form method="get" action="/einstellungen" '
            'class="settings-search" role="search"><label '
            'for="settings-search">Einstellung suchen</label><div '
            'class="settings-search-row"><input id="settings-search" '
            'type="search" name="suche" value="{p0}" maxlength="80" '
            'autocomplete="off" data-live-search="/api/einstellungen/suche" '
            'aria-controls="settings-live-results" placeholder="z. B. '
            'Zeitzone, Aufbewahrung, Telegram"><button '
            'class="button">Suchen</button></div><p class="meta '
            'settings-live-status" id="settings-live-status" role="status" '
            'aria-live="polite"></p><ul class="settings-live-results" '
            'id="settings-live-results" aria-label="Sofort gefundene '
            'Einstellungen" hidden></ul></form>'
        ),
        p0=e(query),
    )


def _pending(raw: dict[str, Any] | None, active: dict[str, Any] | None, groups: tuple[str, ...]) -> int:
    names = [name for group in groups for name in _names(group)]
    return sum(_lookup(active, name) != _lookup(raw, name) for name in names) if raw is not None else 0


def _attention(raw: dict[str, Any] | None, active: dict[str, Any] | None,
               credentials: CredentialSnapshot | None) -> str:
    """8.5: what needs the user first; the accounts and areas follow below."""
    items = []
    pending = sum(_pending(raw, active, groups) for *_head, groups in AREAS)
    if pending:
        items.append(tr('<li>{p0} gespeicherte Änderungen sind noch nicht aktiv. <a href="/dienst/neu-laden">'
                        'Konfiguration neu laden</a> oder <a href="/einstellungen/neustarten">Mailhelp neu '
                        'starten</a>.</li>', p0=pending))
    missing = [item for item in credentials.fields if not item.present] if credentials is not None else []
    if missing:
        items.append(tr('<li>{p0} Zugangsdaten fehlen. <a href="/einstellungen?bereich=zugangsdaten">'
                        'Zugangsdaten ansehen</a></li>', p0=len(missing)))
    if not items:
        return notice(tr("Keine offenen Punkte: alle Einstellungen sind aktiv."), "ok")
    return (f'<section class="settings-section settings-attention"><h2>{e(tr("Handlungsbedarf"))}</h2>'
            f'<ul>{"".join(items)}</ul></section>')


def _overview(raw: dict[str, Any] | None, active: dict[str, Any] | None,
              credentials: CredentialSnapshot | None = None) -> str:
    counted = active is not None
    mailboxes: Any = _lookup(active, "imap.mailboxes") or [None]
    accounts: Any = _lookup(active, "iserv.accounts") or []
    body = _attention(raw, active, credentials) + _tiles(
        msg("Konten und Verbindungen"),
        (
            _tile(
                "/einstellungen/postfaecher",
                msg("Postfächer"),
                (tr("{p0} eingerichtet · ", p0=f"{len(mailboxes)}") if counted else "")
                + msg("hinzufügen, prüfen und anpassen"),
            )
            + _tile(
                "/einstellungen/iserv",
                msg("IServ-Konten"),
                (tr("{p0} eingerichtet · ", p0=f"{len(accounts)}") if counted else "") + msg("Elternbriefe abrufen"),
            )
            + _tile("/einstellungen/zielprofile", msg("Kalender und Aufgaben"),
                    msg("Zielprofile: Kalender und Aufgabenlisten je Postfach"))
            + _tile(
                '/einstellungen?bereich={p0}'.format(p0=f'{CREDENTIALS_AREA}'),
                msg("Zugangsdaten"),
                msg("Passwörter und API-Schlüssel"),
            )
            # 6.2.9: one entry for every read-only check (diagnosis per service and the whole self-test).
            + _tile(
                "/diagnose", msg("Verbindungen prüfen"), msg("Lesend prüfen: einzelne Dienste oder alles auf einmal")
            )
        ),
    )
    tiles = ""
    for key, title, text, groups in AREAS:
        changed = _pending(raw, active, groups)
        badge = (
            tr(
                '<em class="badge warn">{p0} {p1} ausstehend</em>',
                p0=f"{changed}",
                p1=f"{(msg('Änderung') if changed == 1 else msg('Änderungen'))}",
            )
            if changed
            else ""
        )
        tiles += _tile('/einstellungen?bereich={p0}'.format(p0=f'{key}'), title, text, badge)
    body += _tiles(msg("Bereiche"), tiles)
    # 6.2.9: profile and delivery history are part of "Benachrichtigungen"; devices are in the main navigation.
    body += _tiles(
        msg("Inhalte"),
        (
            _tile("/themen", msg("Themen"), msg("Relevante und irrelevante Themen"))
            + _tile("/einstellungen/absender", msg("Absender-Regeln"), msg("Ignorieren, VIP-Absender und Ausnahmen"))
        ),
    )
    body += _tiles(
        "System",
        (
            _tile("/einrichtung", msg("Einrichtung"), msg("Verbindungen Schritt für Schritt einrichten"))
            + _tile(
                "/einstellungen/neustarten", msg("Mailhelp neu starten"), msg("Kontrollierter Neustart mit Bestätigung")
            )
            + _tile(
                "/dienst/neu-laden", msg("Konfiguration neu laden"), msg("Verbindungen ohne Prozessneustart wechseln")
            )
            + _tile(
                "/einstellungen/beenden", msg("Mailhelp beenden"), msg("Dienst kontrolliert anhalten"), kind="danger"
            )
        ),
    )
    return body


def _area(key: str, raw: dict[str, Any] | None, active: dict[str, Any] | None, revision: str, csrf: str,
          models: list[tuple[str, str, str, str]], push: str) -> str:
    groups = next(groups for name, _title, _text, groups in AREAS if name == key)
    body = ""
    if key == "benachrichtigungen":
        body += (
            tr(
                '<p class="settings-shortcuts"><a class="button small" '
                'href="/einstellungen/benachrichtigungen">Benachrichtigungsprofil:'
                ' Ruhezeiten und Kanäle</a> <a class="button small" '
                'href="/benachrichtigungen">Zustellhistorie</a></p>'
            )
            + push
        )
    elif key == "ki":
        body += (
            tr('<section class="settings-section"><div class="setting-row"><h2>Modelle (nur lesend)</h2>')
            + help_bubble("models", msg("Modelle"), EXTRA_HELP["models"])
            + "</div>"
            + _models_table(models)
            + "</section>"
        )
    elif key == "erweitert":
        body += tr(
            '<p class="settings-shortcuts"><a class="button small" '
            'href="/geraete">Geräte</a> <a class="button small" '
            'href="/einstellungen/neustarten">Mailhelp neu starten</a> <a '
            'class="button small danger" '
            'href="/einstellungen/beenden">Mailhelp beenden</a></p>'
        )
    if raw is None:
        return body + notice(tr("Konfigurationsdienst nicht verfügbar."), "warn")
    return body + "".join(_section(group, raw, active, revision, csrf, key) for group in groups)


def _found(query: str, raw: dict[str, Any] | None, active: dict[str, Any] | None, revision: str, csrf: str) -> str:
    """5.3: the full result page of the shared search; same matches and order as the live search."""
    if raw is None:
        return notice(tr("Konfigurationsdienst nicht verfügbar."), "warn")
    results = search(query)
    if not results:
        return notice(tr("Keine Einstellung zu „{p0}“ gefunden.", p0=query), "info")
    areas = {title: key for key, title, *_ in AREAS}
    rows = "".join(
        tr('<p class="meta">Bereich <a href="/einstellungen?bereich={p0}">{p1}</a> · {p2}</p>',
           p0=areas[item.area], p1=e(item.area), p2=e(item.group))
        + _setting_row(item.key, raw, active, revision, csrf)
        for item in results if item.key is not None and item.path == "Weboberfläche"
    )
    pages = "".join(f'<li><a href="{e(item.href)}">{e(item.label)}</a> '
                    f'<span class="meta">{e(item.path)} · {e(item.summary)}</span></li>'
                    for item in results if item.path != "Weboberfläche")
    count = len(results)
    body = tr('<p class="meta" role="status">{p0} Treffer für „{p1}“</p>', p0=count, p1=e(query))
    if rows:
        body += tr('<section class="settings-section"><h2>Einstellungen</h2>{p0}</section>', p0=rows)
    if pages:
        body += tr(
            ('<section class="settings-section"><h2>Seiten</h2><ul class="search-pages">{p0}</ul></section>'),
            p0=f"{pages}",
        )
    return body


def settings_page(models: list[tuple[str, str, str, str]], raw: dict[str, Any] | None,
                  active: dict[str, Any] | None, revision: str, csrf: str,
                  credentials: CredentialSnapshot | None = None, area: str = "", query: str = "",
                  push: str = "") -> str:
    """The overview, one area or search results; *area* is empty or one of :data:`AREA_KEYS`."""
    query = query.strip()
    titles = {key: (title, text) for key, title, text, _groups in AREAS}
    titles[CREDENTIALS_AREA] = (msg("Zugangsdaten"), msg("Passwörter und API-Schlüssel"))
    if area and not query:
        # 8.5: the area is the page title; the eyebrow and the back link name where it belongs.
        title, text = titles[area]
        body = page_head(title, msg("Einstellungen"), text, back=("/einstellungen", msg("Alle Einstellungen")))
    else:
        body = page_head(
            msg("Einstellungen"),
            msg("Verwaltung"),
            tr(
                "Konten verbinden, allgemeine Regeln festlegen und gezielt je "
                "Postfach anpassen. Jede Änderung wird vor dem Speichern noch "
                "einmal angezeigt."
            ),
        ) + tr('<p><a class="button" href="/hilfe">Hilfe zu Einstellungen</a></p>')
    if query:
        content = _search(query) + _found(query, raw, active, revision, csrf)
    elif area == CREDENTIALS_AREA:
        content = credentials_section(credentials, csrf)
    elif area:
        content = _search("") + _area(area, raw, active, revision, csrf, models, push)
    else:
        content = _search("") + _overview(raw, active, credentials)
    return (body + '<div class="settings-layout">' + (_nav("" if query else area) if area or query else "")
            + '<div class="settings-values">' + content + "</div></div>")


def _warnings(name: str, value: object) -> str:
    """Consequences that need attention before a value is taken over."""
    body = ""
    if name.startswith("retention."):
        body += notice(tr("Aufbewahrung kann Inhalte unwiderruflich entfernen."), "warn")
    if (
        name in {"logging.llm.include_requests", "logging.llm.include_responses", "learning.decision_llm_content"}
        and value is True
    ):
        body += notice(tr("Inhaltslogging speichert vollständige LLM-Inhalte einschließlich Maildaten."), "warn")
    if name == "test_mode" and value is False:
        body += notice(tr("Produktivbetrieb: ausdrücklich bestätigte Aktionen können extern angelegt werden."), "warn")
    return body


def _compared(name: str, old_value: object, value: object) -> tuple[str, str]:
    old_text = str(old_value) if name in TEXT_SETTINGS and old_value else _shown(name, old_value)
    new_text = str(value) if name in TEXT_SETTINGS and value else _shown(name, value)
    return old_text, new_text


def settings_confirmation(form: dict[str, str], route: str, csrf: str,
                          raw: dict[str, Any], value: object) -> str:
    """The explicit second step before a setting is written."""
    name = form["name"]
    timing = (
        msg("Wird an der nächsten sicheren Stelle übernommen.")
        if name.split(".")[0] in LIVE_FIELDS
        else msg("Wird nach einem Neustart verwendet.")
    )
    body = tr("<h1>Änderung bestätigen</h1><h2>{p0}</h2><p>{p1}</p>", p0=e(setting_label(name)), p1=timing)
    body += _warnings(name, value)
    hidden: dict[str, Any] = {key: value for key, value in form.items() if key not in {"csrf", "key", "confirm"}}
    old_text, new_text = _compared(name, _lookup(raw, name), value)
    body += tr(
        (
            '<dl class="facts-table"><dt>Bisher gespeichert</dt><dd '
            'class="compare-text">{p0}</dd><dt>Neu</dt><dd '
            'class="compare-text">{p1}</dd></dl>'
        ),
        p0=e(old_text),
        p1=e(new_text),
    )
    return body + post_form(route, csrf, "", msg("Änderung ausdrücklich speichern"), confirm="yes", **hidden)


def settings_review(patch: dict[str, Any], texts: dict[str, str], expected_hash: str, csrf: str,
                    raw: dict[str, Any], area: str, route: str = "/einstellungen/speichern") -> str:
    """8.5: all changes of one section form; one confirmation takes them over together."""
    rows = ""
    for name, value in patch.items():
        old_text, new_text = _compared(name, _lookup(raw, name), value)
        timing = msg("sofort") if name.split(".")[0] in LIVE_FIELDS else msg("nach Neustart")
        rows += (f'<tr><th scope="row">{e(setting_label(name))}</th><td class="compare-text">{e(old_text)}</td>'
                 f'<td class="compare-text">{e(new_text)}</td><td>{e(timing)}</td></tr>')
    count = len(patch)
    body = (tr("<h1>Änderungen prüfen</h1><p>{p0} Änderung wird übernommen.</p>", p0=count) if count == 1
            else tr("<h1>Änderungen prüfen</h1><p>{p0} Änderungen werden gemeinsam übernommen.</p>", p0=count))
    body += "".join(_warnings(name, value) for name, value in patch.items())
    body += (f'<div class="table-scroll" tabindex="0" role="region" aria-label="{e(tr("Änderungen"))}">'
             f'<table class="settings-review"><thead><tr><th scope="col">'
             f'{e(tr("Einstellung"))}</th><th scope="col">{e(tr("Bisher"))}</th><th scope="col">{e(tr("Neu"))}'
             f'</th><th scope="col">{e(tr("Wirkt"))}</th></tr></thead><tbody>{rows}</tbody></table></div>')
    hidden = {SETTING_PREFIX + name: texts[name] for name in patch}
    back = settings_back(area)
    return (body + post_form(route, csrf, "", msg("Änderungen ausdrücklich speichern"),
                             primary=True, confirm="yes", expected_hash=expected_hash, bereich=area, **hidden)
            + f'<p><a href="{e(back)}">{e(tr("Abbrechen und zurück"))}</a></p>')
