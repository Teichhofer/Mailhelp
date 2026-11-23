"""Accessible HTML setup, diagnostics, notification profile and delivery history."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, cast

import yaml

from ..config import Settings
from ..config.configuration import LIVE_FIELDS, MAILBOX_SETUP_FIELDS, ConfigurationConflict, file_hash, set_dotted
from ..config.notifications import CATEGORIES, effective_profile
from ..i18n import msg, tr
from ..runtime.diagnostics import HELP, STATES, DiagnosticResult
from ..runtime.setup import DiagnosisRequired
from .auth import PairingLimited, WebSession
from .forms import post_form
from .http import Request, Response
from .local_pairing import issue
from .pages import e, layout, notice

_SETUP_TEXT_1 = msg(
    "<p>Windows 11 oder Docker unter Linux. Zugangsdaten unter <a "
    'href="/einstellungen/zugangsdaten">Zugangsdaten</a> eintragen (oder in .env bzw. der '
    "Prozessumgebung). Entwurf speichern verändert die aktive Konfiguration noch "
    "nicht.</p>"
)

_SETUP_TEXT_2 = msg(
    "<p>Verbindungsänderungen benötigen eine aktuelle erfolgreiche Diagnose des Entwurfs. "
    "Verbindungseinstellungen benötigen nach Übernahme einen Neustart. Übernahme "
    "autorisiert keine Kalendertermine oder Aufgaben.</p>"
)

# 8.4.3: shown before the approval and when it is refused for a missing check.
_DIAGNOSIS_NEEDED = msg(
    "Der Entwurf ändert eine Verbindung, die seit der Änderung noch nicht erfolgreich geprüft wurde. "
    "Bitte zuerst die Verbindungen prüfen und danach die Einstellungen übernehmen."
)


def _diagnosis_needed(kind: str) -> str:
    return (notice(tr(_DIAGNOSIS_NEEDED), kind)
            + f'<p><a class="button primary" href="/diagnose">{e(tr("Verbindungen prüfen"))}</a></p>')

_SETUP_TEXT_3 = msg(
    "<p>Welche Modelle mit welchen Parametern arbeiten, zeigt <a "
    'href="/einstellungen?bereich=ki">Einstellungen → KI und Auswertung</a>; geändert '
    "werden sie in <code>prompts.yaml</code>. Tests unter Diagnose starten.</p>"
)

if TYPE_CHECKING:
    from .site import MailhelpSite

STEPS = (
    msg("Betriebsart"),
    msg("Postfach"),
    msg("Analyse und Ziele"),
    msg("Web und Geräte"),
    msg("Benachrichtigungen"),
    msg("Prüfen und übernehmen"),
)
FIELDS = {
    1: ("timezone", "telegram.enabled"),
    2: ("imap.host", "imap.port", "imap.connection_mode", "imap.folders", "imap.primary_folder", "imap.drafts_folder",
        "imap.historical_start"),
    3: ("targets.calendar_provider", "targets.google_calendar", "targets.caldav_calendar_url",
        "targets.outlook_calendar", "targets.task_provider", "targets.todoist_project", "targets.caldav_task_url",
        "targets.microsoft_todo_list", "targets.microsoft_tenant", "targets.google_tasks_list",
        "event_defaults.video_duration_minutes", "event_defaults.in_person_duration_minutes"),
    4: ("push.enabled", "push.subject"),
    5: ("notifications.quiet_hours.enabled", "notifications.quiet_hours.start", "notifications.quiet_hours.end",
        "notifications.quiet_hours.allow_system_errors", "notifications.batching.enabled",
        "notifications.batching.window_seconds", "notifications.telegram_content", "daily_briefing.enabled",
        "daily_briefing.time"),
    6: (),
}
LABELS = {
    "event_defaults.video_duration_minutes": msg("Standarddauer Videokonferenz (Minuten)"),
    "event_defaults.in_person_duration_minutes": msg("Standarddauer Präsenztermin (Minuten)"),
    "timezone": msg("Zeitzone (IANA)"),
    "telegram.enabled": msg("Telegram verwenden"),
    "imap.host": msg("IMAP-Server"),
    "imap.port": msg("IMAP-Port"),
    "imap.connection_mode": msg("IMAP-Verbindungsart"),
    "imap.folders": msg("Quellordner (JSON-Liste)"),
    "imap.primary_folder": msg("Hauptordner"),
    "imap.drafts_folder": msg("Entwurfsordner"),
    "imap.historical_start": msg("Ältere Mails nicht verarbeiten vor (ISO 8601; null: keine Grenze)"),
    "imap.label": msg("Anzeigename"),
    "imap.enabled": msg("Postfach abrufen"),
    "targets.google_calendar": msg("Google-Kalender"),
    "targets.todoist_project": msg("Todoist-Projekt"),
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
    "push.enabled": msg("Web-Push am Server aktivieren"),
    "push.subject": msg("VAPID-Kontaktadresse (mailto:name@domain)"),
    "notifications.quiet_hours.enabled": msg("Ruhezeiten aktivieren"),
    "notifications.quiet_hours.start": msg("Ruhe ab"),
    "notifications.quiet_hours.end": msg("Ruhe bis"),
    "notifications.quiet_hours.allow_system_errors": msg("Betriebsprobleme von Ruhezeiten ausnehmen"),
    "notifications.batching.enabled": msg("Meldungen bündeln"),
    "notifications.batching.window_seconds": msg("Bündelungsfenster (Sekunden)"),
    "notifications.telegram_content": msg("Telegram-Inhalte"),
    "daily_briefing.enabled": msg("Tagesüberblick aktivieren"),
    "daily_briefing.time": msg("Tagesüberblick um"),
    # 8.5: readable names instead of configuration keys.
    "notifications.categories.decisions": msg("Entscheidungen melden über"),
    "notifications.categories.action_results": msg("Aktionsergebnisse melden über"),
    "notifications.categories.daily_briefing": msg("Tagesüberblick senden über"),
    "notifications.categories.system_errors": msg("Betriebsprobleme melden über"),
    "notifications.delivery.max_attempts": msg("Zustellung: höchstens Versuche"),
    "notifications.delivery.initial_backoff_seconds": msg("Zustellung: erste Wartezeit (Sekunden)"),
    "notifications.delivery.max_backoff_seconds": msg("Zustellung: längste Wartezeit (Sekunden)"),
    "notifications.delivery.history_days": msg("Zustellhistorie aufbewahren (Tage)"),
    "notifications.delivery.max_pending": msg("Zustellung: höchstens wartende Meldungen"),
}
# 8.5: what a choice means instead of its stored value; the value sent stays the same.
CHOICE_LABELS = {
    "true": msg("Ja"), "false": msg("Nein"),
    "[]": msg("Keinen Kanal"), '["telegram"]': msg("Telegram"), '["web_push"]': msg("Push im Browser"),
    '["telegram", "web_push"]': msg("Telegram und Web-Push"),
    "ssl": msg("SSL/TLS (meist Port 993)"), "starttls": msg("STARTTLS (meist Port 143)"),
    "plain": msg("Unverschlüsselt (nur im eigenen Netz)"),
    "neutral": msg("Neutral (ohne Mailinhalte)"), "summary": msg("Zusammenfassung (Betreffzeilen an Telegram)"),
    "google": msg("Google Kalender"), "caldav": msg("CalDAV"), "outlook": msg("Outlook / Microsoft 365"),
    "todoist": msg("Todoist"), "microsoft_todo": msg("Microsoft To Do"), "apple_reminders": msg("Apple Erinnerungen"),
    "google_tasks": msg("Google Tasks"),
}
# 8.5: the secrets the setup reports as missing or present, by name.
SECRET_LABELS = {
    "openrouter_api_key": msg("OpenRouter-API-Schlüssel"), "telegram_bot_token": msg("Telegram-Bot-Token"),
    "todoist_token": msg("Todoist-Token"), "google_oauth_refresh_token": msg("Google-Anmeldung (Refresh-Token)"),
    "caldav_username": msg("CalDAV-Benutzername"), "caldav_password": msg("CalDAV-Passwort"),
    "microsoft_client_id": msg("Microsoft-Client-ID"),
}
CHOICES = {"telegram.enabled": ("true", "false"), "push.enabled": ("true", "false"),
           "imap.connection_mode": ("ssl", "starttls", "plain"),
           "notifications.telegram_content": ("neutral", "summary"),
           "targets.calendar_provider": ("google", "caldav", "outlook"),
           "targets.task_provider": ("todoist", "microsoft_todo", "caldav", "apple_reminders", "google_tasks")}


def lookup(raw: Any, dotted: str) -> Any:
    for part in dotted.split("."):
        raw = raw[int(part)] if isinstance(raw, list) else raw[part]
    return raw


def step_fields(raw: dict[str, Any], step: int) -> tuple[str, ...]:
    """Fields of one step; the 3.1 format shows the mailbox fields of every configured mailbox."""
    mailboxes = raw["imap"].get("mailboxes")
    if step != 2 or mailboxes is None:
        return FIELDS[step]
    return tuple(f"imap.mailboxes.{index}.{name}" for index in range(len(mailboxes)) for name in MAILBOX_SETUP_FIELDS)


def field_label(raw: dict[str, Any], name: str) -> str:
    parts = name.split(".")
    if parts[:2] != ["imap", "mailboxes"]:
        return LABELS.get(name, name)
    mailbox = raw["imap"]["mailboxes"][int(parts[2])]
    return tr("{p0} – Postfach {p1} ({p2})", p0=LABELS["imap." + parts[3]], p1=mailbox["id"], p2=mailbox["label"])


def _secret_label(name: str) -> str:
    if "/" in name:  # the user name and password pair of one mailbox or IServ account
        return tr("IServ-Zugang ({p0})", p0=name) if name.startswith("ISERV") else tr("Postfachzugang ({p0})", p0=name)
    return str(SECRET_LABELS.get(name, name))


def input_field(name: str, value: object, choices: Sequence[str] | None = None, label: str | None = None) -> str:
    label = label or LABELS.get(name, name)
    identity = "setting-" + name.replace(".", "-")
    shown = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    if choices is None and isinstance(value, bool):
        choices = ("true", "false")
    if choices is not None:
        control = f'<select id="{identity}" name="value">' + "".join(
            f'<option value="{e(item)}"{" selected" if item == shown else ""}>{e(CHOICE_LABELS.get(item, item))}'
            '</option>' for item in choices) + '</select>'
    else:
        control = f'<input id="{identity}" name="value" value="{e(shown)}" maxlength="4000" required>'
    return f'<label for="{identity}">{e(label)}</label>{control}'


class SetupSite:
    def __init__(self, site: MailhelpSite) -> None:
        # The SetupRuntime, attached once the services exist.
        self.site, self.runtime = site, cast(Any, None)
        for method, path, handler in (
            ("GET", "/einrichtung", self.setup), ("POST", "/einrichtung/speichern", self.save),
            ("POST", "/einrichtung/uebernehmen", self.apply), ("GET", "/diagnose", self.diagnose),
            ("POST", "/diagnose/pruefen", self.check), ("GET", "/diagnose/bericht", self.report),
            ("GET", "/einstellungen/benachrichtigungen", self.profile),
            ("GET", "/benachrichtigungen", self.history)):
            site.app.route(method, path, site.signed_in(handler))
        site.app.route("POST", "/api/local-pair", self.local_pair)

    @staticmethod
    def links() -> str:
        return tr(
            '<p class="card-links"><a class="button" '
            'href="/einrichtung">Einrichtung</a> <a class="button" '
            'href="/einstellungen/postfaecher">Postfächer</a> <a '
            'class="button" href="/einstellungen/iserv">IServ-Konten</a> <a '
            'class="button" '
            'href="/einstellungen/zugangsdaten">Zugangsdaten</a> <a '
            'class="button" href="/einstellungen/zielprofile">Zielprofile</a> '
            '<a class="button" href="/diagnose">Verbindungen prüfen</a> <a '
            'class="button" '
            'href="/einstellungen/benachrichtigungen">Benachrichtigungsprofil<'
            '/a> <a class="button" '
            'href="/benachrichtigungen">Zustellhistorie</a></p>'
        )

    def _unavailable(self) -> Response:
        return Response.text(503, msg("Einrichtungsdienst nicht verfügbar."))

    def _raw(self, *, with_patch: bool = True) -> dict[str, Any]:
        service = self.runtime.setup
        raw = yaml.safe_load((service.configuration.directory / "config.yaml").read_text(encoding="utf-8"))
        cfg = Settings.model_validate(raw)
        result = cfg.model_dump(mode="json")
        result["notifications"] = effective_profile(cfg).model_dump()
        if cfg.imap.legacy_format:
            # Show the effective values, including defaults that config.yaml leaves out.
            result["imap"].update(cfg.imap.configured_mailboxes()[0].model_dump(
                mode="json", include=set(MAILBOX_SETUP_FIELDS)))
        state = service.state()
        for name, value in (state.patch.items() if with_patch and state.kind == "settings" else ()):
            set_dotted(result, name, value)
        return result

    def _fields(self, session: WebSession, fields: Sequence[str], step: int) -> str:
        service, raw = self.runtime.setup, self._raw()
        state, csrf = service.state(), self.site.auth.csrf_token(session.id)
        body = ""
        for name in fields:
            # _raw() is validated: settings missing in an older config.yaml show their default.
            value = lookup(raw, name)
            choices = CHOICES.get(name)
            if name.startswith("imap.mailboxes."):
                choices = CHOICES.get("imap." + name.rsplit(".", 1)[-1])
            if name.endswith((".primary_folder", ".drafts_folder")):
                listed = self.site.views.store.load("setup-folders", {})
                if name.startswith("imap.mailboxes."):
                    number = str(raw["imap"]["mailboxes"][int(name.split(".")[2])]["id"])
                    choices = listed.get("mailboxes", {}).get(number) or None
                else:
                    choices = listed.get("folders") or None
            if name.startswith("notifications.categories."):
                channels = ["[]"]
                if raw["telegram"]["enabled"]:
                    channels.append('["telegram"]')
                if raw["push"]["enabled"]:
                    channels.append('["web_push"]')
                if raw["telegram"]["enabled"] and raw["push"]["enabled"]:
                    channels.append('["telegram", "web_push"]')
                choices = tuple(channels)
            body += post_form(
                "/einrichtung/speichern",
                csrf,
                input_field(name, value, choices, field_label(raw, name)),
                msg("Entwurf speichern"),
                name=name,
                version=state.version,
                step=step,
            )
        return body

    def _listed_folders(self) -> str:
        """Folders of the last diagnosis, per mailbox for the 3.1 format."""
        listed = self.site.views.store.load("setup-folders", {})
        mailboxes = self._raw()["imap"].get("mailboxes")
        if mailboxes is None:
            parts = [", ".join(listed.get("folders", [])) or tr("noch nicht geprüft")]
        else:
            parts = [
                tr("Postfach {p0}: ", p0=item["id"])
                + (", ".join(listed.get("mailboxes", {}).get(str(item["id"]), [])) or tr("noch nicht geprüft"))
                for item in mailboxes
            ]
        return (
            tr("<p>Vorhandene Ordner aus der letzten Diagnose: ")
            + e("; ".join(str(part) for part in parts))
            + tr(
                ". Lesbarkeit beweist keine Schreibberechtigung. Postfächer "
                "hinzufügen oder entfernen: <a "
                'href="/einstellungen/postfaecher">Einstellungen → '
                "Postfächer</a>.</p>"
            )
        )

    def setup(self, request: Request, session: WebSession) -> Response:
        if self.runtime is None:
            return self._unavailable()
        state, cfg = self.runtime.setup.state(), self.runtime.setup.configuration
        body = tr("<h1>Einrichtung</h1>") + self.links()
        body += tr("<p>Aktueller Schritt: {p0} · Entwurfsversion: {p1}</p>", p0=state.step, p1=state.version)
        body += '<ul>' + "".join(f'<li>{e(_secret_label(name))}: {e(tr(status))}</li>'
                                  for name, status in self.runtime.secret_status().items()) + '</ul>'
        body += tr(_SETUP_TEXT_1)
        for index, title in enumerate(STEPS, 1):
            opened = " open" if index in {state.step, 6} else ""
            body += (f'<section class="card"><details{opened}><summary><h2>{index}. {title}</h2></summary>'
                     + self._fields(session, step_fields(self._raw(), index), index))
            if index == 2:
                body += self._listed_folders()
            if index == 3:
                body += tr(_SETUP_TEXT_3)
            if index == 4:
                body += self.site.experience.controls(self.site.auth.csrf_token(session.id))
                body += tr("<p>Push benötigt HTTPS oder localhost, Browserunterstützung, Berechtigung und ein ")
                body += tr('<a href="/einstellungen">Geräteabonnement</a>. Ohne JavaScript sind Browserberechtigungen ')
                body += tr("und Abonnements nicht steuerbar. Auf iOS zuerst zum Home-Bildschirm hinzufügen.</p>")
            body += '</details></section>'
        current = file_hash(cfg.directory / "config.yaml")
        if state.base_hash != current:
            body += tr('<p role="status">Konfiguration neu einlesen und die Differenz erneut prüfen.</p>')
            body += post_form(
                "/einrichtung/speichern",
                self.site.auth.csrf_token(session.id),
                "",
                msg("Konfiguration neu einlesen"),
                version=state.version,
                step=6,
                refresh="yes",
            )
        baseline = self._raw(with_patch=False)
        body += f'<h2>{e(tr("Änderungsliste"))}</h2><ul>' + "".join(
            f'<li>{e(name)}: {e(json.dumps(lookup(baseline, name), ensure_ascii=False))} '
            f'→ {e(json.dumps(value, ensure_ascii=False))} '
            f'({e(tr("sofort") if name.split(".")[0] in LIVE_FIELDS else tr("Neustart erforderlich"))})</li>'
            for name, value in state.patch.items() if lookup(baseline, name) != value) + '</ul>'
        body += tr(_SETUP_TEXT_2)
        if self.runtime.setup.diagnosis_gaps():
            # 8.4.3: the approval would be refused; say why before the button, with the next step.
            body += _diagnosis_needed("warn")
        body += post_form(
            "/einrichtung/uebernehmen",
            self.site.auth.csrf_token(session.id),
            tr(
                '<label><input type="checkbox" name="confirm" value="yes" '
                "required> Gezeigte Änderungen ausdrücklich übernehmen</label>"
            ),
            msg("Einstellungen übernehmen"),
            version=state.version,
            expected_hash=state.base_hash,
        )
        return Response.html(200, layout(msg("Einrichtung"), '<div class="setup-page">' + body + "</div>"))

    def save(self, request: Request, session: WebSession, form: dict[str, str]) -> Response:
        if self.runtime is None:
            return self._unavailable()
        try:
            patch = {}
            if "name" in form:
                try:
                    value = json.loads(form["value"])
                except json.JSONDecodeError:
                    value = form["value"]
                patch[form["name"]] = value
            self.runtime.setup.save(f"web:{session.id}", int(form["version"]), form["key"],
                                    int(form["step"]), patch, refresh=form.get("refresh") == "yes")
        except ConfigurationConflict:
            return Response.text(409, msg("Konfiguration oder Entwurf geändert; neu einlesen und Differenz prüfen."))
        except (ValueError, KeyError, PermissionError, OSError):
            return Response.text(422, msg("Entwurf nicht gespeichert; Angaben und Sitzung prüfen."))
        return Response.redirect("/einrichtung")

    def apply(self, request: Request, session: WebSession, form: dict[str, str]) -> Response:
        if self.runtime is None:
            return self._unavailable()
        try:
            if form.get("confirm") != "yes":
                raise ValueError("Übernahme nicht bestätigt")
            command = self.runtime.setup.command(f"web:{session.id}", int(form["version"]),
                                                 form["key"], form["expected_hash"])
        except ConfigurationConflict:
            return Response.text(409, msg("Konfiguration oder Entwurf geändert; Differenz erneut prüfen."))
        except DiagnosisRequired:
            # 8.4.3: the pilot of 8.0 ended here with the general message below; name the missing check.
            title = tr("Einstellungen noch nicht übernommen")
            return Response.html(409, layout(title, f'<section class="card narrow"><h1>{e(title)}</h1>'
                                                    + _diagnosis_needed("error") + "</section>"))
        except (ValueError, KeyError, PermissionError, OSError):
            return Response.text(422, msg("Einstellungen nicht übernommen; Bestätigung und Sitzung prüfen."))
        return self.site.archive.queue(request, command)

    def diagnose(self, request: Request, session: WebSession) -> Response:
        if self.runtime is None:
            return self._unavailable()
        service = self.runtime.diagnostics
        self.runtime.update_profile_checks()
        state = service.state()
        body = (
            tr("<h1>Verbindungen prüfen</h1>")
            + self.links()
            + tr("<p>Unabhängige Prüfungen mit Zeitlimit. Zugangsdaten ")
        )
        body += tr("werden nicht angezeigt. Kalender, Todoist und IMAP werden ausschließlich gelesen.</p>")
        body += tr('<p><a class="button" href="/dienst/selbsttest">Alles auf einmal prüfen (Selbsttest)</a></p>')
        for name in service.checks:
            result = state.results.get(name, DiagnosticResult())
            if result.checked_at is not None and result.config_revision != self.runtime.setup.fingerprint():
                result = DiagnosticResult(status="unchecked", code="configuration")
            label = {
                "telegram_test": msg("Neutrale Telegram-Testnachricht senden"),
                "push_test": msg("Test-Push an dieses Gerät senden"),
                "llm_test": msg("Synthetischen LLM-Test starten (kann Kosten verursachen)"),
            }.get(name, tr("{p0} prüfen", p0=name))
            body += f'<section class="card"><h2>{e(name)}</h2><p role="status">{e(STATES[result.status])} · '
            body += f'{e(result.checked_at or msg('noch nicht geprüft'))} · {result.duration_ms} ms</p>'
            body += f'<p>{e(HELP[result.code])}</p>'
            body += post_form("/diagnose/pruefen", self.site.auth.csrf_token(session.id), "", label,
                              name=name, version=state.version) + '</section>'
        body += tr('<p><a href="/diagnose/bericht">Bereinigten Diagnosebericht herunterladen</a></p>')
        return Response.html(200, layout(msg("Verbindungen prüfen"), '<div class="setup-page">' + body + "</div>"))

    def check(self, request: Request, session: WebSession, form: dict[str, str]) -> Response:
        if self.runtime is None:
            return self._unavailable()
        try:
            self.runtime.update_profile_checks()
            self.runtime.diagnostics.run(session.id, form["name"], int(form["version"]), form["key"])
        except (ValueError, KeyError, PermissionError):
            return Response.text(409, msg("Prüfung nicht gestartet; Seite neu laden und Sitzung prüfen."))
        return Response.redirect("/diagnose")

    def report(self, request: Request, session: WebSession) -> Response:
        if self.runtime is None:
            return self._unavailable()
        response = Response.json(200, self.runtime.diagnostics.report())
        response.headers["Content-Disposition"] = msg('attachment; filename="mailhelp-diagnose.json"')
        return response

    def profile(self, request: Request, session: WebSession) -> Response:
        if self.runtime is None:
            return self._unavailable()
        body = tr("<h1>Benachrichtigungsprofil</h1>") + self.links()
        body += tr(
            "<p>Die lokale Anzeige bleibt verfügbar. Web-Push ist immer "
            "neutral. Telegram summary übermittelt Betreffzeilen und den "
            "Tagesüberblick an Telegram. Diese Inhaltsfreigabe bewusst "
            "auswählen. Bestehende Inhaltsfreigaben werden beim Upgrade "
            "übernommen.</p>"
        )
        body += tr('<p>Fehlende Kanäle zuerst in der <a href="/diagnose">Diagnose</a> und Einrichtung aktivieren. ')
        body += tr("Ein Push-Abonnement gilt nur für sein Gerät.</p>")
        fields = tuple(f"notifications.categories.{name}" for name in CATEGORIES) + FIELDS[5]
        fields += tuple("notifications.delivery." + name for name in
                        ("max_attempts", "initial_backoff_seconds", "max_backoff_seconds",
                         "history_days", "max_pending"))
        body += self._fields(session, fields, 5)
        body += tr(
            '<p><a class="button primary" href="/einrichtung">Differenz prüfen und ausdrücklich übernehmen</a></p>'
        )
        return Response.html(200, layout(msg("Benachrichtigungsprofil"), '<div class="setup-page">' + body + "</div>"))

    def history(self, request: Request, session: WebSession) -> Response:
        runtime = self.site.notification_runtime
        if runtime is None:
            return self._unavailable()
        body = tr("<h1>Zustellhistorie</h1>") + self.links()
        body += tr("<p>sent bei Push bedeutet an den Dienst übergeben; kein Nachweis über Lesen am Endgerät. ")
        body += tr("uncertain wird ohne belastbaren Abgleich nicht automatisch wiederholt.</p><ul>")
        for item in runtime.queue.state().entries.values():
            body += f'<li>{e(item.category)} · {e(item.channel)} · {e(item.status)} · '
            body += tr(
                "{p0} · Versuche: {p1} · {p2}</li>",
                p0=f"{e(item.updated_at)}",
                p1=f"{item.attempts}",
                p2=f"{e(item.error)}",
            )
        return Response.html(200, layout(msg("Zustellhistorie"), body + "</ul>"))

    def local_pair(self, request: Request) -> Response:
        form = self.site._form(request)
        if isinstance(form, Response):
            return form
        try:
            code = issue(self.site.auth, form.get("message", ""), form.get("signature", ""))
        except PermissionError:
            return Response.text(403, msg("Lokale Kopplung nicht autorisiert."))
        except PairingLimited:
            return Response.text(429, msg("Zu viele Kopplungsversuche."))
        return Response.json(200, {"code": code})
