"""Accessible HTML setup, diagnostics, notification profile and delivery history."""
from __future__ import annotations

import json

import yaml

from ..configuration import LIVE_FIELDS, ConfigurationConflict, file_hash
from ..diagnostics import HELP, STATES, DiagnosticResult
from ..local_pairing import issue
from ..notification_config import CATEGORIES, effective_profile
from .archive_site import post_form
from .auth import PairingLimited
from .http import Response
from .pages import e, layout

STEPS = ("Betriebsart", "Postfach", "Analyse und Ziele", "Web und Geräte", "Benachrichtigungen",
         "Prüfen und übernehmen")
FIELDS = {
    1: ("timezone", "telegram.enabled"),
    2: ("imap.host", "imap.port", "imap.connection_mode", "imap.folders", "imap.primary_folder", "imap.drafts_folder"),
    3: ("targets.google_calendar", "targets.todoist_project"),
    4: ("push.enabled",),
    5: ("notifications.quiet_hours.enabled", "notifications.quiet_hours.start", "notifications.quiet_hours.end",
        "notifications.quiet_hours.allow_system_errors", "notifications.batching.enabled",
        "notifications.batching.window_seconds", "notifications.telegram_content", "daily_briefing.enabled",
        "daily_briefing.time"),
    6: (),
}
LABELS = {"timezone": "Zeitzone (IANA)", "telegram.enabled": "Telegram verwenden",
          "imap.host": "IMAP-Server", "imap.port": "IMAP-Port", "imap.connection_mode": "IMAP-Verbindungsart",
          "imap.folders": "Quellordner (JSON-Liste)", "imap.primary_folder": "Hauptordner",
          "imap.drafts_folder": "Entwurfsordner", "targets.google_calendar": "Google-Kalender",
          "targets.todoist_project": "Todoist-Projekt", "push.enabled": "Web-Push am Server aktivieren",
          "notifications.quiet_hours.enabled": "Ruhezeiten aktivieren", "notifications.quiet_hours.start": "Ruhe ab",
          "notifications.quiet_hours.end": "Ruhe bis", "notifications.quiet_hours.allow_system_errors":
          "Betriebsprobleme von Ruhezeiten ausnehmen", "notifications.batching.enabled": "Meldungen bündeln",
          "notifications.batching.window_seconds": "Bündelungsfenster (Sekunden)",
          "notifications.telegram_content": "Telegram-Inhalte", "daily_briefing.enabled": "Tagesüberblick aktivieren",
          "daily_briefing.time": "Tagesüberblick um"}
CHOICES = {"telegram.enabled": ("true", "false"), "push.enabled": ("true", "false"),
           "imap.connection_mode": ("ssl", "starttls", "plain"),
           "notifications.telegram_content": ("neutral", "summary")}


def lookup(raw, dotted):
    for part in dotted.split("."):
        raw = raw[part]
    return raw


def input_field(name, value, choices=None):
    label = LABELS.get(name, name)
    identity = "setting-" + name.replace(".", "-")
    shown = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    if choices is None and isinstance(value, bool):
        choices = ("true", "false")
    if choices is not None:
        control = f'<select id="{identity}" name="value">' + "".join(
            f'<option value="{e(item)}"{" selected" if item == shown else ""}>{e(item)}</option>'
            for item in choices) + '</select>'
    else:
        control = f'<input id="{identity}" name="value" value="{e(shown)}" maxlength="4000" required>'
    return f'<label for="{identity}">{e(label)}</label>{control}'


class SetupSite:
    def __init__(self, site):
        self.site, self.runtime = site, None
        for method, path, handler in (
            ("GET", "/einrichtung", self.setup), ("POST", "/einrichtung/speichern", self.save),
            ("POST", "/einrichtung/uebernehmen", self.apply), ("GET", "/diagnose", self.diagnose),
            ("POST", "/diagnose/pruefen", self.check), ("GET", "/diagnose/bericht", self.report),
            ("GET", "/einstellungen/benachrichtigungen", self.profile),
            ("GET", "/benachrichtigungen", self.history)):
            site.app.route(method, path, site.signed_in(handler))
        site.app.route("POST", "/api/local-pair", self.local_pair)

    @staticmethod
    def links():
        return ('<p class="card-links"><a class="button" href="/einrichtung">Einrichtung</a> '
                '<a class="button" href="/diagnose">Diagnose</a> '
                '<a class="button" href="/einstellungen/benachrichtigungen">Benachrichtigungsprofil</a> '
                '<a class="button" href="/benachrichtigungen">Zustellhistorie</a></p>')

    def _unavailable(self):
        return Response.text(503, "Einrichtungsdienst nicht verfügbar.")

    def _raw(self, *, with_patch=True):
        service = self.runtime.setup
        raw = yaml.safe_load((service.configuration.directory / "config.yaml").read_text(encoding="utf-8"))
        from ..config import Settings
        cfg = Settings.model_validate(raw)
        result = cfg.model_dump(mode="json")
        result["notifications"] = effective_profile(cfg).model_dump()
        for name, value in (service.state().patch.items() if with_patch else ()):
            target = result
            parts = name.split(".")
            for part in parts[:-1]:
                target = target[part]
            target[parts[-1]] = value
        return result

    def _fields(self, session, fields, step):
        service, raw = self.runtime.setup, self._raw()
        state, csrf = service.state(), self.site.auth.csrf_token(session.id)
        body = ""
        for name in fields:
            value = lookup(raw, name)
            choices = CHOICES.get(name)
            if name in {"imap.primary_folder", "imap.drafts_folder"}:
                choices = self.site.views.store.load("setup-folders", {}).get("folders") or None
            if name.startswith("notifications.categories."):
                choices = ["[]"]
                if raw["telegram"]["enabled"]:
                    choices.append('["telegram"]')
                if raw["push"]["enabled"]:
                    choices.append('["web_push"]')
                if raw["telegram"]["enabled"] and raw["push"]["enabled"]:
                    choices.append('["telegram", "web_push"]')
            body += post_form("/einrichtung/speichern", csrf, input_field(name, value, choices),
                              "Entwurf speichern", name=name, version=state.version, step=step)
        return body

    def setup(self, request, session):
        if self.runtime is None:
            return self._unavailable()
        state, cfg = self.runtime.setup.state(), self.runtime.setup.configuration
        body = '<h1>Einrichtung</h1>' + self.links()
        body += f'<p>Aktueller Schritt: {state.step} · Entwurfsversion: {state.version}</p>'
        body += '<ul>' + "".join(f'<li>{e(name)}: {status}</li>'
                                  for name, status in self.runtime.secret_status().items()) + '</ul>'
        body += ('<p>Windows 11 oder Docker unter Linux. Zugangsdaten lokal in .env oder der Prozessumgebung '
                 'einrichten. Entwurf speichern verändert die aktive Konfiguration noch nicht.</p>')
        for index, title in enumerate(STEPS, 1):
            opened = " open" if index in {state.step, 6} else ""
            body += (f'<section class="card"><details{opened}><summary><h2>{index}. {title}</h2></summary>'
                     + self._fields(session, FIELDS[index], index))
            if index == 2:
                folders = self.site.views.store.load("setup-folders", {}).get("folders", [])
                body += '<p>Vorhandene Ordner aus der letzten Diagnose: ' + e(
                    ", ".join(folders) or "noch nicht geprüft")
                body += '. Lesbarkeit beweist keine Schreibberechtigung.</p>'
            if index == 3:
                body += '<p>Modelle und Parameter werden in prompts.yaml gepflegt. Tests unter Diagnose starten.</p>'
            if index == 4:
                body += self.site.experience.controls(self.site.auth.csrf_token(session.id))
                body += '<p>Push benötigt HTTPS oder localhost, Browserunterstützung, Berechtigung und ein '
                body += '<a href="/einstellungen">Geräteabonnement</a>. Ohne JavaScript sind Browserberechtigungen '
                body += 'und Abonnements nicht steuerbar. Auf iOS zuerst zum Home-Bildschirm hinzufügen.</p>'
            body += '</details></section>'
        current = file_hash(cfg.directory / "config.yaml")
        if state.base_hash != current:
            body += '<p role="status">Konfiguration neu einlesen und die Differenz erneut prüfen.</p>'
            body += post_form("/einrichtung/speichern", self.site.auth.csrf_token(session.id), "",
                              "Konfiguration neu einlesen", version=state.version, step=6, refresh="yes")
        baseline = self._raw(with_patch=False)
        body += '<h2>Änderungsliste</h2><ul>' + "".join(
            f'<li>{e(name)}: {e(json.dumps(lookup(baseline, name), ensure_ascii=False))} '
            f'→ {e(json.dumps(value, ensure_ascii=False))} '
            f'({"sofort" if name.split(".")[0] in LIVE_FIELDS else "Neustart erforderlich"})</li>'
            for name, value in state.patch.items() if lookup(baseline, name) != value) + '</ul>'
        body += ('<p>Verbindungsänderungen benötigen eine aktuelle erfolgreiche Diagnose des Entwurfs. '
                 'Verbindungseinstellungen benötigen nach Übernahme '
                 'einen Neustart. Übernahme autorisiert keine Kalendertermine oder Aufgaben.</p>')
        body += post_form("/einrichtung/uebernehmen", self.site.auth.csrf_token(session.id),
                          '<label><input type="checkbox" name="confirm" value="yes" required> '
                          'Gezeigte Änderungen ausdrücklich übernehmen</label>', "Einstellungen übernehmen",
                          version=state.version, expected_hash=state.base_hash)
        return Response.html(200, layout("Einrichtung", '<div class="setup-page">' + body + '</div>'))

    def save(self, request, session, form):
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
            return Response.text(409, "Konfiguration oder Entwurf geändert; neu einlesen und Differenz prüfen.")
        except (ValueError, KeyError, PermissionError, OSError):
            return Response.text(422, "Entwurf nicht gespeichert; Angaben und Sitzung prüfen.")
        return Response.redirect("/einrichtung")

    def apply(self, request, session, form):
        if self.runtime is None:
            return self._unavailable()
        try:
            if form.get("confirm") != "yes":
                raise ValueError("Übernahme nicht bestätigt")
            command = self.runtime.setup.command(f"web:{session.id}", int(form["version"]),
                                                 form["key"], form["expected_hash"])
        except ConfigurationConflict:
            return Response.text(409, "Konfiguration oder Entwurf geändert; Differenz erneut prüfen.")
        except (ValueError, KeyError, PermissionError, OSError):
            return Response.text(422, "Einstellungen nicht übernommen; Bestätigung und Sitzung prüfen.")
        return self.site.archive.queue(request, command)

    def diagnose(self, request, session):
        if self.runtime is None:
            return self._unavailable()
        service = self.runtime.diagnostics
        state = service.state()
        body = '<h1>Diagnose</h1>' + self.links() + '<p>Unabhängige Prüfungen mit Zeitlimit. Zugangsdaten '
        body += 'werden nicht angezeigt. Kalender, Todoist und IMAP werden ausschließlich gelesen.</p>'
        for name in service.checks:
            result = state.results.get(name, DiagnosticResult())
            if result.checked_at is not None and result.config_revision != self.runtime.setup.fingerprint():
                result = DiagnosticResult(status="unchecked", code="configuration")
            label = {"telegram_test": "Neutrale Telegram-Testnachricht senden",
                     "push_test": "Test-Push an dieses Gerät senden",
                     "llm_test": "Synthetischen LLM-Test starten (kann Kosten verursachen)"}.get(name, f"{name} prüfen")
            body += f'<section class="card"><h2>{e(name)}</h2><p role="status">{e(STATES[result.status])} · '
            body += f'{e(result.checked_at or "noch nicht geprüft")} · {result.duration_ms} ms</p>'
            body += f'<p>{e(HELP[result.code])}</p>'
            body += post_form("/diagnose/pruefen", self.site.auth.csrf_token(session.id), "", label,
                              name=name, version=state.version) + '</section>'
        body += '<p><a href="/diagnose/bericht">Bereinigten Diagnosebericht herunterladen</a></p>'
        return Response.html(200, layout("Diagnose", '<div class="setup-page">' + body + '</div>'))

    def check(self, request, session, form):
        if self.runtime is None:
            return self._unavailable()
        try:
            self.runtime.diagnostics.run(session.id, form["name"], int(form["version"]), form["key"])
        except (ValueError, KeyError, PermissionError):
            return Response.text(409, "Prüfung nicht gestartet; Seite neu laden und Sitzung prüfen.")
        return Response.redirect("/diagnose")

    def report(self, request, session):
        if self.runtime is None:
            return self._unavailable()
        response = Response.json(200, self.runtime.diagnostics.report())
        response.headers["Content-Disposition"] = 'attachment; filename="mailhelp-diagnose.json"'
        return response

    def profile(self, request, session):
        if self.runtime is None:
            return self._unavailable()
        body = '<h1>Benachrichtigungsprofil</h1>' + self.links()
        body += ('<p>Die lokale Anzeige bleibt verfügbar. Web-Push ist immer neutral. Telegram summary '
                 'übermittelt Betreffzeilen und den Tagesüberblick an Telegram. Diese Inhaltsfreigabe bewusst '
                 'auswählen. Bestehende Inhaltsfreigaben werden beim Upgrade übernommen.</p>')
        body += '<p>Fehlende Kanäle zuerst in der <a href="/diagnose">Diagnose</a> und Einrichtung aktivieren. '
        body += 'Ein Push-Abonnement gilt nur für sein Gerät.</p>'
        fields = tuple(f"notifications.categories.{name}" for name in CATEGORIES) + FIELDS[5]
        fields += tuple("notifications.delivery." + name for name in
                        ("max_attempts", "initial_backoff_seconds", "max_backoff_seconds",
                         "history_days", "max_pending"))
        body += self._fields(session, fields, 5)
        body += ('<p><a class="button primary" href="/einrichtung">'
                 'Differenz prüfen und ausdrücklich übernehmen</a></p>')
        return Response.html(200, layout("Benachrichtigungsprofil", '<div class="setup-page">' + body + '</div>'))

    def history(self, request, session):
        runtime = self.site.notification_runtime
        if runtime is None:
            return self._unavailable()
        body = '<h1>Zustellhistorie</h1>' + self.links()
        body += '<p>sent bei Push bedeutet an den Dienst übergeben; kein Nachweis über Lesen am Endgerät. '
        body += 'uncertain wird ohne belastbaren Abgleich nicht automatisch wiederholt.</p><ul>'
        for item in runtime.queue.state().entries.values():
            body += f'<li>{e(item.category)} · {e(item.channel)} · {e(item.status)} · '
            body += f'{e(item.updated_at)} · Versuche: {item.attempts} · {e(item.error)}</li>'
        return Response.html(200, layout("Zustellhistorie", body + '</ul>'))

    def local_pair(self, request):
        form = self.site._form(request)
        if isinstance(form, Response):
            return form
        try:
            code = issue(self.site.auth, form.get("message", ""), form.get("signature", ""))
        except PermissionError:
            return Response.text(403, "Lokale Kopplung nicht autorisiert.")
        except PairingLimited:
            return Response.text(429, "Zu viele Kopplungsversuche.")
        return Response.json(200, {"code": code})
