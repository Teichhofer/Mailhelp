"""Settings and topics: every change is shown first and queued as an explicit command."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

import yaml

from ..configuration import AdminCommand, AdminKind, ConfigurationConflict, file_hash
from ..credentials import CredentialService, CredentialUnauthorized
from ..storage import CorruptState
from .http import Response
from .pages import layout, notice
from .settings_pages import TEXT_SETTINGS, settings_confirmation, settings_page, topics_page

if TYPE_CHECKING:
    from .archive_site import ArchiveSite

TOPIC_FILES = (("relevant", "topics.yaml"), ("irrelevant", "irrelevant_topics.yaml"))


class SettingsSite:
    def __init__(self, archive: ArchiveSite):
        self.archive, self.site = archive, archive.site
        for method, path, handler in (
                ("GET", "/einstellungen", self.settings), ("POST", "/einstellungen/speichern", self.save_settings),
                ("POST", "/einstellungen/zugangsdaten/speichern", self.save_credentials),
                ("GET", "/themen", self.topics), ("POST", "/themen/speichern", self.save_topic)):
            self.site.app.route(method, path, self.site.signed_in(handler))

    def settings(self, request, session):
        configuration = self.archive.configuration
        raw = active = None
        revision = ""
        if configuration is not None:
            path = configuration.directory / "config.yaml"
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            active = configuration.active.model_dump(mode="json")
            revision = file_hash(path)
        csrf = self.site.auth.csrf_token(session.id)
        service = self.credential_service()
        try:
            credentials = service.snapshot() if service is not None else None
        except (OSError, ValueError):
            credentials = None
        page = settings_page(self.archive.models, raw, active, revision, csrf, credentials)
        page += self.site.experience.controls(csrf)
        page += self.site.setup_page.links()
        return Response.html(200, layout("Einstellungen", page, active="/einstellungen"))

    def credential_service(self):
        configuration = self.archive.configuration
        if configuration is None:
            return None
        return CredentialService(configuration.directory, self.site.views.store, self.site.auth.active,
                                 lambda payload: self.site.auth.csrf_token("credential-edit:" + payload))

    def save_credentials(self, request, session, form):
        service = self.credential_service()
        if service is None:
            return self.site._reply(request, 503, "Zugangsdatenverwaltung nicht verfügbar.")
        try:
            value = form["value"]
            service.save(session.id, form["key"], form["name"], value, form["expected"], form["config_revision"])
            if hasattr(self.site.logger, "secrets") and value not in self.site.logger.secrets:
                self.site.logger.secrets = (*self.site.logger.secrets, value)
        except CredentialUnauthorized:
            return self.site._reply(request, 403, "Sitzung nicht mehr gültig. Bitte erneut anmelden.")
        except ConfigurationConflict:
            return self.site._reply(request, 409, "Die Änderung ist veraltet oder wurde bereits anders gesendet. "
                                    "Bitte die Einstellungen neu laden.")
        except (ValueError, KeyError):
            return self.site._reply(request, 422, "Ungültige Zugangsdatenänderung. "
                                    "Bitte einen angebotenen Zugang und einen einzeiligen neuen Wert verwenden.")
        except (OSError, CorruptState):
            return self.site._reply(request, 503, "Zugangsdaten konnten nicht sicher gespeichert werden. "
                                    "Bitte Dateizugriff prüfen und mit demselben Formular erneut versuchen.")
        return Response.html(200, layout("Zugangsdaten gespeichert", '<h1>Zugangsdaten gespeichert</h1>' + notice(
            "Zugangsdaten in .env gespeichert. Sie werden nach einem Neustart verwendet; "
            "Prozessvariablen haben weiterhin Vorrang.", "ok")
            + '<p><a class="button" href="/einstellungen#settings-credentials">Zurück zu Zugangsdaten</a></p>',
            active="/einstellungen"))

    def save_settings(self, request, session, form):
        configuration = self.archive.configuration
        if configuration is None:
            return self.site._reply(request, 503, "Konfiguration nicht verfügbar.")
        try:
            if form["name"] in TEXT_SETTINGS:
                # Browsers send line breaks as CRLF; the file keeps plain LF.
                value = form["value"].replace("\r\n", "\n").strip()
            else:
                try:
                    value = json.loads(form["value"])
                except json.JSONDecodeError:
                    value = form["value"]
            command = AdminCommand(kind=AdminKind.SETTINGS, actor=f"web:{session.id}", idempotency_key=form["key"],
                                   expected_hash=form["expected_hash"], patch={form["name"]: value},
                                   acknowledged=True)
            configuration.candidate(command)
        except ConfigurationConflict:
            return self.site._reply(request, 409, "Einstellungsdatei geändert; bitte neu laden.")
        except (ValueError, KeyError, OSError):
            return self.site._reply(request, 422,
                                    "Ungültige oder inzwischen geänderte Einstellung; bitte neu prüfen.")
        if form.get("confirm") != "yes":
            body = settings_confirmation(form, request.path, self.site.auth.csrf_token(session.id))
            return Response.html(200, layout("Bestätigen", body))
        return self.archive.queue(request, command)

    def topics(self, request, session):
        configuration = self.archive.configuration
        if configuration is None:
            return self.site._reply(request, 503, "Themenverwaltung nicht verfügbar.")
        files = []
        for category, filename in TOPIC_FILES:
            path = configuration.directory / filename
            files.append((category, filename, yaml.safe_load(path.read_text(encoding="utf-8")), file_hash(path)))
        body = topics_page(files, self.site.auth.csrf_token(session.id))
        return Response.html(200, layout("Themen", body, active="/einstellungen"))

    def save_topic(self, request, session, form):
        try:
            if form.get("original_id") and form["id"] != form["original_id"]:
                raise ValueError("IDs dürfen nicht geändert werden")
            topic = {key: form[key] for key in ("id", "name", "description")}
            topic["enabled"] = {"true": True, "false": False}[form["enabled"].lower()]
            topic.update({key: [v.strip() for v in form[key].split(";") if v.strip()]
                          for key in ("examples", "exclusions")})
            command = AdminCommand(kind=AdminKind.TOPICS, actor=f"web:{session.id}", idempotency_key=form["key"],
                                   expected_hash=form["expected_hash"], category=form["category"], patch=topic,
                                   acknowledged=form.get("confirm") == "yes")
            self.archive.configuration.candidate(command)
        except ConfigurationConflict:
            return self.site._reply(request, 409, "Themendatei geändert; bitte neu laden.")
        except (ValueError, KeyError, OSError, AttributeError):
            return self.site._reply(request, 422, "Ungültige, unbestätigte oder inzwischen geänderte Themen.")
        return self.archive.queue(request, command)
