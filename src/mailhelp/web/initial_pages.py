"""Five-step initial setup, with empty secret inputs on every render."""
from __future__ import annotations

from typing import Any

from ..runtime.initial_setup import FIELDS, SECRET_FIELDS, InitialDraft
from ..runtime.setup_messages import CATALOGUE, CheckResult
from .forms import field, post_form, select
from .pages import e, layout

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
    # 6.1: names in the links of the check result.
    "password": "Web-Passwort", "model": "Ollama-Modell",
}
CHOICES = {"imap.connection_mode": ("ssl", "starttls", "plain"), "llm.provider": ("openrouter", "ollama"),
           "targets.calendar_provider": ("google", "caldav", "outlook"),
           "targets.task_provider": ("todoist", "microsoft_todo", "caldav", "apple_reminders")}


def _found(check: CheckResult | None) -> dict[str, Any] | None:
    """The choices of a fresh check in the shape of the stored probe result."""
    if check is None or not check.choices:
        return None
    choices = check.choices
    return {"folders": choices.get("folders", []), "inbox": (choices.get("inbox") or [""])[0],
            "drafts": (choices.get("drafts") or [""])[0], "models": choices.get("models", [])}


def check_box(results: list[CheckResult]) -> str:
    """6.1: the result above the form – what is wrong, which field and what to do; only catalogue texts."""
    if not results:
        return ""
    failed = any(not result.ok for result in results)
    warned = any(result.warnings for result in results)
    kind = "error" if failed else "warn" if warned else "ok"
    title = ("Prüfung fehlgeschlagen" if failed else "Geprüft – mit Hinweisen" if warned
             else "Geprüft – alles in Ordnung")
    role = "alert" if failed else "status"
    body = (f'<section class="notice notice-{kind} check-result" id="pruefergebnis" role="{role}" tabindex="-1" '
            f'aria-labelledby="pruefergebnis-titel"><h2 id="pruefergebnis-titel">{title}</h2>')
    for result in results:
        if len(results) > 1:
            mark = "✓" if result.ok else "✗"
            body += (f'<h3>{mark} Schritt {result.step}: {e(TITLES[result.step - 1])} '
                     f'<a href="/einrichtung/schritt/{result.step}">Zu Schritt {result.step}</a></h3>')
        for item in result.findings:
            message = CATALOGUE[item.code]
            label = LABELS.get(item.field or "", item.field or "")
            target = (f' <a href="#feld-{_slug(item.field)}">Feld „{e(label)}“</a>'
                      if item.field and item.severity != "ok" else "")
            detail = f' <span class="meta">({e(item.detail)})</span>' if item.detail else ""
            body += (f'<div class="check-finding {item.severity}" id="meldung-{_slug(item.field or item.code)}">'
                     f'<p><strong>{e(message.cause)}</strong>{detail}{target}</p>')
            if message.steps and item.severity != "ok":
                body += "<ul>" + "".join(f"<li>{e(step)}</li>" for step in message.steps) + "</ul>"
            body += "</div>"
        if result.facts:
            body += "<dl class=\"check-facts\">" + "".join(
                f"<dt>{e(key)}</dt><dd>{e(value)}</dd>" for key, value in result.facts.items()) + "</dl>"
    return body + "</section>"


def _identify(controls: str, step: int, results: list[CheckResult]) -> str:
    """Give every field an id for the links of the result box; a field with a problem says so (ARIA)."""
    wrong = {item.field for result in results for item in result.findings
             if item.field and item.severity == "error"}
    names = [*FIELDS.get(step, ()), *SECRET_FIELDS.get(step, ()), "password", "model"]
    for name in names:
        marker = f'name="{name}"'
        if marker not in controls:
            continue
        extra = f' id="feld-{_slug(name)}"'
        if name in wrong:
            extra += f' aria-invalid="true" aria-describedby="meldung-{_slug(name)}"'
        controls = controls.replace(marker, marker + extra, 1)
    return controls


def _slug(name: str) -> str:
    return "".join(char if char.isalnum() else "-" for char in name.lower())


def initial_page(state: InitialDraft, csrf: str, step: int, *, checks: list[CheckResult] | None = None,
                 values: dict[str, str] | None = None) -> str:
    navigation = '<nav aria-label="Einrichtungsschritte">' + " · ".join(
        f'<a class="button" href="/einrichtung/schritt/{index}">{index}. {e(title)}</a>'
        if index <= state.completed_step + 1 else f'<span>{index}. {e(title)}</span>'
        for index, title in enumerate(TITLES, 1)) + '</nav>'
    body = f'<h1>Mailhelp einrichten: {e(TITLES[step - 1])}</h1><p>Schritt {step} von 5</p>{navigation}'
    controls = ""
    if step == 5:
        controls = ('<p>Die Verbindungen werden erneut lesend geprüft. Danach wird die Konfiguration aktiviert '
                    'und der Normalbetrieb im selben Prozess gestartet. '
                    'Anschließend steht der Web-Lernmodus bereit.</p>'
                    '<label><input type="checkbox" name="confirm" value="yes" required> '
                    'Konfiguration speichern und Normalbetrieb starten</label>')
    else:
        check = checks[0] if checks else None
        controls = _fields(state, step, values, _found(check))
        for name in SECRET_FIELDS[step]:
            controls += (f'<label>{e(name)}<input type="password" name="{e(name)}" maxlength="4096" '
                         'autocomplete="new-password" placeholder="Leer: gespeicherten Wert behalten"></label>')
        if step == 1:
            controls += ('<label>Web-Passwort (mindestens 12 Zeichen)<input type="password" name="password" '
                         'minlength="12" maxlength="1024" autocomplete="new-password"></label>')
        if step == 3:
            found = _found(checks[0] if checks else None)
            models = (found or {}).get("models", [])
            controls += (select("model", "Ollama-Modell", state.model, [(name, name) for name in models])
                         if models and state.config.get("llm", {}).get("provider") == "ollama"
                         else field("model", "Ollama-Modell (nur für lokalen Betrieb)", state.model))
        # 6.1: every step can be checked; checking changes nothing.
        # formnovalidate: the server explains a too short password instead of a bare browser bubble.
        controls += ('<button type="submit" class="button" formaction="/einrichtung/pruefen" data-check '
                     'formnovalidate>Prüfen</button>')
    if step == 5:
        controls += ('<button type="submit" class="button" formaction="/einrichtung/pruefen" data-check '
                     'formnovalidate>Alles prüfen</button>')
    controls = _identify(controls, step, checks or [])
    body += check_box(checks or []) + '<p class="meta" role="status" data-check-status></p>'
    body += post_form("/einrichtung/speichern", csrf, controls,
                      "Speichern und starten" if step == 5 else "Speichern und weiter",
                      version=state.version, step=step)
    if step == 4:
        body += ('<p><a href="/hilfe/google-playground">Google: Anleitung zum OAuth 2.0 Playground</a></p>'
                 '<p>Zuerst Clientdaten speichern; dann bei Bedarf direkt verbinden:</p>'
                 '<p><a href="/auth/google/start">Google verbinden</a> · '
                 '<a href="/auth/microsoft">Microsoft verbinden</a> · '
                 '<a href="/auth/google/kalender">Google-Kalender auswählen</a></p>')
    return layout("Ersteinrichtung", '<section class="card">' + body + '</section>', signed_in=False,
                  after='<script src="/static/setup.js" defer></script>')


def _fields(state: InitialDraft, step: int, values: dict[str, str] | None = None,
            found: dict[str, Any] | None = None) -> str:
    """Saved values, or the entered ones after a check; *found* offers folders checked just now."""
    body = ""
    found = found or {}
    for name in FIELDS[step]:
        parent, _, key = name.rpartition(".")
        value: Any = state.config[parent][key] if parent else state.config[key]
        value = (values or {}).get(name, value)
        choices = CHOICES.get(name)
        if name == "imap.primary_folder" or name == "imap.drafts_folder":
            folders = found.get("folders", [])
            if folders:
                suggested = found.get("inbox" if "primary" in name else "drafts", value)
                value = value if value in folders else suggested
                body += select(name, LABELS[name], value, [(f, f) for f in folders])
                continue
        body += (select(name, LABELS[name], value, [(choice, choice) for choice in choices]) if choices
                 else field(name, LABELS[name], value))
    return body
