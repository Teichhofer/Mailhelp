"""Five-step initial setup, with empty secret inputs on every render."""
from __future__ import annotations

from typing import Any

from ..runtime.initial_setup import FIELDS, SECRET_FIELDS, InitialDraft
from .forms import field, post_form, select
from .pages import e, layout, notice

TITLES = ("Web-Zugang und Zeitzone", "Postfach", "KI-Anbieter", "Kalender und Aufgaben", "Abschluss")
LABELS = {
    "timezone": "Zeitzone", "imap.host": "IMAP-Server", "imap.port": "Port",
    "imap.connection_mode": "Verschlüsselung", "imap.primary_folder": "Posteingang",
    "imap.drafts_folder": "Entwurfsordner", "llm.provider": "KI-Anbieter",
    "llm.ollama_address": "Ollama-Adresse (HOST:PORT)", "targets.calendar_provider": "Kalenderdienst",
    "targets.task_provider": "Aufgabendienst", "targets.google_calendar": "Google-Kalender-ID",
    "targets.todoist_project": "Todoist-Projekt-ID", "targets.caldav_calendar_url": "CalDAV-Kalenderadresse",
    "targets.caldav_task_url": "CalDAV-Aufgabenadresse", "targets.outlook_calendar": "Outlook-Kalender-ID",
    "targets.microsoft_todo_list": "Microsoft-To-Do-Liste", "targets.microsoft_tenant": "Microsoft-Mandant",
    "web.google_redirect_uri": "Google-Rückleitungsadresse (Webanwendungs-Client)",
}
CHOICES = {"imap.connection_mode": ("ssl", "starttls", "plain"), "llm.provider": ("openrouter", "ollama"),
           "targets.calendar_provider": ("google", "caldav", "outlook"),
           "targets.task_provider": ("todoist", "microsoft_todo", "caldav", "apple_reminders")}


def initial_page(state: InitialDraft, csrf: str, step: int, message: str = "", *, error: bool = False) -> str:
    navigation = '<nav aria-label="Einrichtungsschritte">' + " · ".join(
        f'<a href="/einrichtung/schritt/{index}">{index}. {e(title)}</a>'
        if index <= state.completed_step + 1 else f'<span>{index}. {e(title)}</span>'
        for index, title in enumerate(TITLES, 1)) + '</nav>'
    body = f'<h1>Mailhelp einrichten: {e(TITLES[step - 1])}</h1><p>Schritt {step} von 5</p>{navigation}'
    if message:
        body += notice(message, "error" if error else "info")
    controls = ""
    if step == 5:
        controls = ('<p>Die Verbindungen werden erneut lesend geprüft. Danach wird die Konfiguration aktiviert '
                    'und Mailhelp kontrolliert neu gestartet. Der Web-Lernmodus folgt in Version 4.0.</p>'
                    '<label><input type="checkbox" name="confirm" value="yes" required> '
                    'Konfiguration speichern und Normalbetrieb starten</label>')
    else:
        controls = _fields(state, step)
        for name in SECRET_FIELDS[step]:
            controls += (f'<label>{e(name)}<input type="password" name="{e(name)}" maxlength="4096" '
                         'autocomplete="new-password" placeholder="Leer: gespeicherten Wert behalten"></label>')
        if step == 1:
            controls += ('<label>Web-Passwort (mindestens 12 Zeichen)<input type="password" name="password" '
                         'minlength="12" maxlength="1024" autocomplete="new-password"></label>')
        if step == 3:
            models = state.result.get("models", [])
            controls += (select("model", "Ollama-Modell", state.model, [(name, name) for name in models])
                         if models and state.config.get("llm", {}).get("provider") == "ollama"
                         else field("model", "Ollama-Modell (nur für lokalen Betrieb)", state.model))
        if step in {2, 3, 4}:
            path = {2: "imap", 3: "llm", 4: "ziele"}[step]
            controls += (f'<button type="submit" formaction="/einrichtung/test/{path}">'
                         'Verbindung jetzt prüfen</button>')
    body += post_form("/einrichtung/speichern", csrf, controls,
                      "Speichern und starten" if step == 5 else "Speichern und weiter",
                      version=state.version, step=step)
    if state.result:
        body += '<section aria-label="Prüfergebnis"><h2>Prüfergebnis</h2><ul>' + "".join(
            f'<li>{e(key)}: {e(value)}</li>' for key, value in state.result.items()) + '</ul></section>'
    if step == 4:
        body += ('<p><a href="/hilfe/google-playground">Google: Anleitung zum OAuth 2.0 Playground</a></p>'
                 '<p>Zuerst Clientdaten speichern; dann bei Bedarf direkt verbinden:</p>'
                 '<p><a href="/auth/google/start">Google verbinden</a> · '
                 '<a href="/auth/microsoft">Microsoft verbinden</a> · '
                 '<a href="/auth/google/kalender">Google-Kalender auswählen</a></p>')
    return layout("Ersteinrichtung", '<section class="card">' + body + '</section>', signed_in=False,
                  after='<script src="/static/setup.js" defer></script>')


def _fields(state: InitialDraft, step: int) -> str:
    body = ""
    for name in FIELDS[step]:
        parent, _, key = name.rpartition(".")
        value: Any = state.config[parent][key] if parent else state.config[key]
        choices = CHOICES.get(name)
        if name == "imap.primary_folder" or name == "imap.drafts_folder":
            folders = state.result.get("folders", [])
            if folders:
                suggested = state.result.get("inbox" if "primary" in name else "drafts", value)
                value = value if value in folders else suggested
                body += select(name, LABELS[name], value, [(f, f) for f in folders])
                continue
        body += (select(name, LABELS[name], value, [(choice, choice) for choice in choices]) if choices
                 else field(name, LABELS[name], value))
    return body
