"""HTML of the settings and topic pages; no routing, no file access."""
from __future__ import annotations

import json

from ..configuration import LIVE_FIELDS, SETTINGS_FIELDS
from .forms import field, post_form, select
from .pages import e, notice
from .setting_help import EXTRA_HELP, SETTING_HELP, help_bubble

SETTING_LABELS = {"poll_interval_seconds": "Abrufintervall (Sekunden)", "timezone": "Zeitzone",
                  "test_mode": "Trockenlauf", "limits.llm_calls_per_minute": "KI-Aufrufe pro Minute",
                  "limits.max_mail_bytes": "Maximale Mailgröße (Bytes)",
                  "limits.max_llm_payload_bytes": "Maximale KI-Anfragegröße (Bytes)",
                  "retention.full_mail_days": "Mailtexte aufbewahren (Tage)",
                  "retention.debug_llm_days": "KI-Diagnosedaten aufbewahren (Tage)",
                  "retention.analysis_days": "Analysen aufbewahren (Tage)",
                  "retention.history_days": "Verlauf aufbewahren (Tage)",
                  "metrics.ollama_power_watts": "Ollama-Leistung (Watt)",
                  "metrics.electricity_eur_per_kwh": "Strompreis (EUR/kWh)",
                  "metrics.retention_days": "Einzelmessungen aufbewahren (Tage)",
                  "metrics.enabled": "Metrikerfassung aktivieren",
                  "personal_info": "Persönliche Angaben für Antworten"}
# Free text settings: edited in a text area and never parsed as JSON.
TEXT_SETTINGS = {"personal_info": ("Zum Beispiel Name, Rolle, Signatur oder gewünschte Anrede. Die Angaben gehen "
                                   "nur in Antwort-Entwürfe ein und werden dafür an das KI-Modell übergeben.")}
SETTING_GROUPS = (
    ("Mailabruf und Betrieb", ("poll_interval_seconds", "timezone", "test_mode", "imap.")),
    ("Antworten", ("personal_info", "smart_reply")),
    ("Telegram", ("telegram.",)),
    ("Bildauswertung", ("vision.",)),
    ("Tagesüberblick", ("daily_briefing.",)),
    ("Tätigkeitsberichte", ("activity_report.",)),
    ("Lernmodus", ("learning.",)),
    ("Weboberfläche", ("web.",)),
    ("Termindauern und Vorschlagsabgleich", ("event_defaults.", "proposal_reconciliation.")),
    ("Ziele", ("targets.",)),
    ("Originalanhänge", ("attachments.",)),
    ("Aufrufbudget und Mailgrenzen", ("limits.",)),
    ("Zeitlimits und Wiederholungen", ("timeouts.", "retries.")),
    ("Aufbewahrung", ("retention.",)),
    ("Protokollierung", ("logging.",)),
    ("Kosten und Messung", ("metrics.",)),
)
SERVICE_LABELS = {"imap": "IMAP", "telegram": "Telegram", "openrouter": "OpenRouter", "ollama": "Ollama",
                  "todoist": "Todoist", "google_calendar": "Google Kalender", "caldav": "CalDAV",
                  "microsoft": "Microsoft 365"}
TIMEOUT_LABELS = {"timeout_seconds": "Zeitlimit (s)", "retries": "Wiederholungen",
                  "initial_backoff_seconds": "erste Wartezeit (s)", "max_backoff_seconds": "längste Wartezeit (s)"}
EXTRA_LABELS = {
    "event_defaults.video_duration_minutes": "Standarddauer Videokonferenz (Minuten)",
    "event_defaults.in_person_duration_minutes": "Standarddauer Präsenztermin (Minuten)",
    "proposal_reconciliation.max_semantic_candidates": "Abgleich: höchstens KI-Kandidaten",
    "targets.todoist_project": "Todoist-Projekt", "targets.google_calendar": "Google-Kalender",
    "targets.calendar_provider": "Kalenderdienst", "targets.task_provider": "Aufgabendienst",
    "targets.caldav_calendar_url": "CalDAV-Kalender (Adresse)",
    "targets.caldav_task_url": "CalDAV-Aufgabenliste (Adresse)",
    "targets.outlook_calendar": "Outlook-Kalender", "targets.microsoft_todo_list": "Microsoft-To-Do-Liste",
    "targets.microsoft_tenant": "Microsoft-Mandant",
    "attachments.store_originals": "Originale speichern",
    "attachments.max_original_bytes": "Höchstgröße je Datei (Bytes)",
    "attachments.max_total_bytes": "Höchstgröße je Mail (Bytes)",
    "logging.console.level": "Konsole: Mindeststufe", "logging.file.level": "Logdatei: Mindeststufe",
    "logging.llm.include_requests": "KI-Anfragen vollständig protokollieren",
    "logging.llm.include_responses": "KI-Antworten vollständig protokollieren",
    "metrics.usd_per_eur": "Wechselkurs (USD je EUR)", "metrics.exchange_rate_date": "Wechselkurs vom",
    "retries.interpretation_attempts": "Antworten verstehen: Versuche",
    "retries.interpretation_backoff_seconds": "Antworten verstehen: Wartezeit (s)",
    "retries.revision_attempts": "Überarbeitung: Versuche",
    "retries.revision_backoff_seconds": "Überarbeitung: Wartezeit (s)",
    "imap.batch_size": "Mails je Abrufdurchlauf",
    "imap.global_newest_first": "Neueste Mails zuerst (alle Postfächer)",
    "telegram.user_id": "Telegram: berechtigte Benutzer-ID",
    "telegram.chat_id": "Telegram: Chat für Nachrichten",
    "telegram.sequential_questions": "Telegram: Entscheidungen nacheinander",
    "smart_reply": "Antwortentwürfe anbieten",
    "vision.enabled": "Bildanhänge und Scans auswerten",
    "vision.max_images_per_mail": "Bildauswertung: Bilder je Mail",
    "vision.max_image_bytes": "Bildauswertung: Höchstgröße je Bild (Bytes)",
    "vision.max_edge_pixels": "Bildauswertung: längste Kante (Pixel)",
    "daily_briefing.include_calendar": "Tagesüberblick: Termine",
    "daily_briefing.include_tasks": "Tagesüberblick: Aufgaben",
    "daily_briefing.include_open": "Tagesüberblick: offene Entscheidungen",
    "activity_report.enabled": "Tätigkeitsberichte aktivieren",
    "activity_report.max_mails": "Tätigkeitsbericht: höchstens Mails",
    "activity_report.max_llm_calls": "Tätigkeitsbericht: höchstens KI-Aufrufe",
    "activity_report.max_share_of_llm_budget": "Tätigkeitsbericht: Anteil am KI-Budget",
    "activity_report.max_fulltext_chars": "Tätigkeitsbericht: Zeichen je Volltext",
    "activity_report.export_mails_without_events": "Tätigkeitsbericht: Mails ohne Termine exportieren",
    "learning.parallel_llm_calls": "Lernmodus: parallele KI-Aufrufe",
    "web.session_days": "Web: Sitzungsdauer (Tage)",
    "web.lan_access": "Web: Zugriff im eigenen Netzwerk",
    "logging.console.enabled": "Konsolenausgabe aktivieren",
    "logging.file.enabled": "Logdatei aktivieren",
    "logging.llm.enabled": "KI-Log aktivieren",
    "logging.llm.level": "KI-Log: Mindeststufe",
    "logging.telegram.enabled": "Telegram-Log aktivieren",
    "logging.telegram.level": "Telegram-Log: Mindeststufe",
    "retention.activity_report_days": "Tätigkeitsberichte aufbewahren (Tage)",
}
LEVEL_CHOICES = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
PROVIDER_CHOICES = {
    "targets.calendar_provider": (("google", "Google Kalender"), ("caldav", "CalDAV (Nextcloud, iCloud, …)"),
                                  ("outlook", "Outlook / Microsoft 365")),
    "targets.task_provider": (("todoist", "Todoist"), ("microsoft_todo", "Microsoft To Do"),
                              ("caldav", "CalDAV-Aufgaben (VTODO)"),
                              ("apple_reminders", "Apple Erinnerungen (iCloud)")),
}


def setting_label(name: str) -> str:
    if name in SETTING_LABELS or name in EXTRA_LABELS:
        return SETTING_LABELS.get(name) or EXTRA_LABELS[name]
    _, service, key = name.split(".")
    return f"{SERVICE_LABELS[service]}: {TIMEOUT_LABELS[key]}"


def _lookup(values: dict | None, name: str) -> object:
    for part in name.split("."):
        values = values.get(part) if isinstance(values, dict) else None
    return values


def _shown(name: str, value: object) -> str:
    """A readable value; target IDs are masked, missing values marked."""
    if value is None or value == "":
        return "nicht gesetzt"
    if name in TEXT_SETTINGS:
        line = " ".join(str(value).split())
        return line if len(line) <= 60 else line[:59] + "…"
    if isinstance(value, bool):
        return "ja" if value else "nein"
    text = str(value)
    if name in PROVIDER_CHOICES:
        return dict(PROVIDER_CHOICES[name]).get(text, text)
    if name.startswith("targets.") and len(text) > 8:
        return f"{text[:3]}…{text[-3:]}"
    return text


def _input(name: str, saved: object) -> str:
    label = "Neuer Wert"
    if name in TEXT_SETTINGS:
        return (f'<label>{label}<textarea name="value" rows="6" maxlength="2000">{e(saved or "")}</textarea></label>'
                f'<p class="meta">{e(TEXT_SETTINGS[name])}</p>')
    if isinstance(saved, bool):
        return select("value", label, json.dumps(saved), [("true", "ja"), ("false", "nein")])
    if name.endswith(".level"):
        return select("value", label, saved, [(level, level) for level in LEVEL_CHOICES])
    if name in PROVIDER_CHOICES:
        return select("value", label, saved, list(PROVIDER_CHOICES[name]))
    kind = "number" if isinstance(saved, (int, float)) else "text"
    step = ' step="any"' if kind == "number" else ""
    shown = "" if saved is None else saved
    return (f'<label>{label}<input type="{kind}"{step} name="value" value="{e(shown)}" '
            'maxlength="200" required></label>')


def _models_table(models: list) -> str:
    if not models:
        return '<p class="meta">Keine Modellangaben verfügbar.</p>'
    return ('<div class="table-scroll"><table><thead><tr><th>Schritt</th>'
            "<th>Modell</th><th>Parameter</th><th>Quelle</th></tr></thead><tbody>"
            + "".join(f"<tr><td>{e(step)}</td><td>{e(model)}</td><td>{e(parameters or '—')}</td>"
                      f"<td>{e(source)}</td></tr>"
                      for step, model, parameters, source in models)
            + "</tbody></table></div>")


def _setting_row(name: str, raw: dict, active: dict | None, revision: str, csrf: str) -> str:
    current, saved = _lookup(active, name), _lookup(raw, name)
    live = name.split(".")[0] in LIVE_FIELDS
    if current == saved:
        state = "aktiv"
    else:
        state = ("gespeichert – wird an der nächsten sicheren Stelle übernommen" if live
                 else "gespeichert – wirkt erst nach einem Neustart")
    timing = "sofort nach dem Speichern" if live else "beim nächsten Start"
    form = post_form("/einstellungen/speichern", csrf, _input(name, saved), "Prüfen",
                     name=name, expected_hash=revision)
    return ('<div class="setting-row"><details class="setting">'
            f'<summary><span>{e(setting_label(name))}</span>'
            f'<strong>{e(_shown(name, current))}</strong></summary>'
            f'<p class="meta">Gespeichert: {e(_shown(name, saved))} · {e(state)} · '
            f'Änderungen wirken {e(timing)}.</p>{form}</details>'
            + help_bubble(name, setting_label(name), SETTING_HELP[name]) + '</div>')


def settings_page(models: list, raw: dict | None, active: dict | None, revision: str, csrf: str) -> str:
    body = ('<div class="page-heading"><p class="eyebrow">Verwaltung</p><h1>Einstellungen</h1>'
            '<p class="page-intro">Globale Regeln verwalten und gezielt je Postfach anpassen.</p></div>'
            '<p class="settings-shortcuts"><a class="button small" href="/themen">Themen</a> '
            '<a class="button small" href="/einstellungen/ignorierte-absender">Ignorierte Absender</a> '
            '<a class="button small" href="/geraete">Geräte</a> '
            '<a class="button small danger" href="/einstellungen/beenden">Mailhelp beenden</a></p>')
    body += ('<details class="model-overview"><summary>Verwendete KI-Modelle</summary>'
             '<div class="setting-row"><h2>Modelle (nur lesend)</h2>'
             + help_bubble("models", "Modelle", EXTRA_HELP["models"]) + "</div>")
    body += _models_table(models) + "</details>"
    if raw is None:
        return body + notice("Konfigurationsdienst nicht verfügbar.", "warn")
    body += ('<p class="meta">Quelle aller folgenden Werte: <code>config.yaml</code>. Gespeichert wird nur der '
             "geänderte Wert; Kommentare und Aufbau der Datei bleiben erhalten. Vor dem Speichern wird die "
             "Änderung noch einmal angezeigt.</p>")
    links = "".join(f'<a href="#settings-{index}">{e(title)}</a>'
                    for index, (title, _) in enumerate(SETTING_GROUPS))
    body += ('<div class="settings-layout"><nav class="settings-index" aria-label="Einstellungsbereiche">'
             '<p class="eyebrow">Bereiche</p>' + links + '</nav><div class="settings-values">')
    for index, (title, prefixes) in enumerate(SETTING_GROUPS):
        names = sorted(name for name in SETTINGS_FIELDS
                       if any(name == prefix or name.startswith(prefix) for prefix in prefixes))
        body += f'<section class="settings-section" id="settings-{index}"><h2>{e(title)}</h2>'
        body += "".join(_setting_row(name, raw, active, revision, csrf) for name in names) + "</section>"
    return body + "</div></div>"


def settings_confirmation(form: dict[str, str], route: str, csrf: str) -> str:
    """The explicit second step before a setting is written."""
    body = '<h1>Änderung bestätigen</h1>' + notice(
        'Aufbewahrung kann Inhalte unwiderruflich entfernen; Inhaltslogging speichert Maildaten. '
        'Echter Betrieb kann bestätigte Aktionen extern anlegen. Übrige Einstellungen benötigen '
        'teilweise einen Neustart.', "warn")
    hidden = {key: value for key, value in form.items() if key not in {"csrf", "key", "confirm"}}
    body += f'<p>{e(form["name"])} →</p><pre>{e(form["value"])}</pre>'
    return body + post_form(route, csrf, "", "Änderung ausdrücklich speichern", confirm="yes", **hidden)


def _topic_value(value: object) -> object:
    """Topic lists as "a; b", booleans as "true"/"false", everything else unchanged."""
    if isinstance(value, list):
        return "; ".join(value)
    return str(value).lower() if isinstance(value, bool) else value


def topics_page(files: list[tuple[str, str, dict, str]], csrf: str) -> str:
    """One form per topic and an empty one per file; *files* are (category, name, content, hash)."""
    body = ('<h1>Themen</h1><p>IDs bleiben stabil. Deaktivieren statt löschen. Änderungen gelten für neue '
            'Analysen; unabhängige Absender-Vorfilter bleiben erhalten.</p>')
    empty = {"id": "", "name": "", "enabled": True, "description": "", "examples": [], "exclusions": []}
    for category, filename, raw, revision in files:
        body += f'<h2>{e(filename)}</h2>'
        for topic in [*raw["topics"], empty]:
            fields = "".join(field(key, key, _topic_value(value)) for key, value in topic.items())
            fields += ('<label><input type="checkbox" name="confirm" value="yes" required> '
                       'Änderung ausdrücklich speichern</label>')
            body += post_form("/themen/speichern", csrf, fields, category=category, expected_hash=revision,
                              original_id=topic["id"])
    return body
