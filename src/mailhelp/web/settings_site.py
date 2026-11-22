"""Settings and topics: every change is shown first and queued as an explicit command."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, quote

import yaml

from ..config import Settings
from ..config.configuration import AdminCommand, AdminKind, ConfigurationConflict, file_hash
from ..i18n import COOKIE, msg, tr
from ..persistence.storage import CorruptState
from ..runtime.credentials import CredentialService, CredentialUnauthorized
from .auth import WebSession
from .http import Request, Response, cookie
from .pages import layout, notice
from .settings_pages import AREA_KEYS, TEXT_SETTINGS, settings_confirmation, settings_page
from .settings_search import LIVE_LIMIT, bounded, search
from .topic_site import TopicSite

if TYPE_CHECKING:
    from .archive_site import ArchiveSite


def _effective(raw: dict[str, Any]) -> dict[str, Any]:
    """The saved values as the next start would apply them, defaults included.

    A setting left out of config.yaml is not a pending change; a file the
    program would reject keeps its literal values.
    """
    try:
        return Settings.model_validate(raw).model_dump(mode="json")
    except ValueError:
        return raw


TOPIC_FILES = (("relevant", "topics.yaml"), ("irrelevant", "irrelevant_topics.yaml"))


class SettingsSite:
    def __init__(self, archive: ArchiveSite) -> None:
        self.archive, self.site = archive, archive.site
        for method, path, handler in (
                ("GET", "/einstellungen", self.settings), ("POST", "/einstellungen/speichern", self.save_settings),
                ("POST", "/einstellungen/zugangsdaten/speichern", self.save_credentials),
                ("POST", "/themen/speichern", self.save_topic),
                ("GET", "/api/einstellungen/suche", self.live_search)):
            self.site.app.route(method, path, self.site.signed_in(handler))
        self.topic_site = TopicSite(self)

    def live_search(self, request: Request, session: WebSession) -> Response:
        """5.3: matches of the shared search while typing; only public metadata, never values."""
        query = bounded(parse_qs(request.query).get("suche", [""])[0])
        results = search(query)
        return Response.json(200, {
            "query": query, "total": len(results), "all": "/einstellungen?suche=" + quote(query),
            "results": [{"id": item.id, "label": item.label, "area": item.area, "summary": item.summary,
                         "key": item.key, "href": item.href, "path": item.path} for item in results[:LIVE_LIMIT]]})

    def settings(self, request: Request, session: WebSession) -> Response:
        query = parse_qs(request.query)
        area = query.get("bereich", [""])[0]
        if area and area not in AREA_KEYS:
            return self.site._reply(request, 404, msg("Unbekannter Einstellungsbereich."))
        configuration = self.archive.configuration
        raw = active = None
        revision = ""
        if configuration is not None:
            path = configuration.directory / "config.yaml"
            raw = _effective(yaml.safe_load(path.read_text(encoding="utf-8")))
            active = configuration.active.model_dump(mode="json")
            revision = file_hash(path)
        csrf = self.site.auth.csrf_token(session.id)
        service = self.credential_service()
        try:
            credentials = service.snapshot() if service is not None else None
        except (OSError, ValueError):
            credentials = None
        page = settings_page(self.archive.models, raw, active, revision, csrf, credentials, area,
                             query.get("suche", [""])[0][:80], self.site.experience.controls(csrf, session.id))
        return Response.html(200, layout(msg("Einstellungen"), page, active="/einstellungen"))

    def credential_service(self) -> CredentialService | None:
        configuration = self.archive.configuration
        if configuration is None:
            return None
        return CredentialService(configuration.directory, self.site.views.store, self.site.auth.active,
                                 lambda payload: self.site.auth.csrf_token("credential-edit:" + payload))

    def save_credentials(self, request: Request, session: WebSession, form: dict[str, str]) -> Response:
        if "expected_hash" in form:
            return self.site.secrets_page.save(request, session, form)
        service = self.credential_service()
        if service is None:
            return self.site._reply(request, 503, msg("Zugangsdatenverwaltung nicht verfügbar."))
        try:
            value = form["value"]
            service.save(session.id, form["key"], form["name"], value, form["expected"], form["config_revision"])
            if hasattr(self.site.logger, "secrets") and value not in self.site.logger.secrets:
                self.site.logger.secrets = (*self.site.logger.secrets, value)
        except CredentialUnauthorized:
            return self.site._reply(request, 403, msg("Sitzung nicht mehr gültig. Bitte erneut anmelden."))
        except ConfigurationConflict:
            return self.site._reply(
                request,
                409,
                msg(
                    "Die Änderung ist veraltet oder wurde bereits anders gesendet. Bitte die Einstellungen neu laden."
                ),
            )
        except (ValueError, KeyError):
            return self.site._reply(
                request,
                422,
                msg(
                    
                        "Ungültige Zugangsdatenänderung. Bitte einen angebotenen Zugang und einen "
                        "einzeiligen neuen Wert verwenden."
                    
                ),
            )
        except (OSError, CorruptState):
            return self.site._reply(
                request,
                503,
                msg(
                    
                        "Zugangsdaten konnten nicht sicher gespeichert werden. Bitte Dateizugriff "
                        "prüfen und mit demselben Formular erneut versuchen."
                    
                ),
            )
        return Response.html(
            200,
            layout(
                tr("Zugangsdaten gespeichert"),
                tr("<h1>Zugangsdaten gespeichert</h1>")
                + notice(
                    tr(
                        "Zugangsdaten in .env gespeichert. Sie werden nach einem Neustart "
                        "verwendet; Prozessvariablen haben weiterhin Vorrang."
                    ),
                    "ok",
                )
                + tr('<p><a class="button" href="/einstellungen?bereich=zugangsdaten">Zurück zu Zugangsdaten</a></p>'),
                active="/einstellungen",
            ),
        )

    def save_settings(self, request: Request, session: WebSession, form: dict[str, str]) -> Response:
        configuration = self.archive.configuration
        if configuration is None:
            return self.site._reply(request, 503, msg("Konfiguration nicht verfügbar."))
        value: Any
        try:
            if form["name"] == "briefings.times":
                value = [part for part in re.split(r"[,;\s]+", form["value"].strip()) if part]
            elif form["name"] in TEXT_SETTINGS:
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
            raw = yaml.safe_load((configuration.directory / "config.yaml").read_text(encoding="utf-8"))
            configuration.candidate(command)
        except ConfigurationConflict:
            return self.site._reply(request, 409, msg("Einstellungsdatei geändert; bitte neu laden."))
        except (ValueError, KeyError, OSError):
            return self.site._reply(
                request, 422, msg("Ungültige oder inzwischen geänderte Einstellung; bitte neu prüfen.")
            )
        if form.get("confirm") != "yes":
            body = settings_confirmation(form, request.path, self.site.auth.csrf_token(session.id), raw, value)
            return Response.html(200, layout(tr("Bestätigen"), body))
        response = self.archive.queue(request, command)
        if form["name"] == "language":
            response.cookies.append(cookie(request, COOKIE, str(value), 31536000, http_only=False, same_site="Lax"))
        return response

    def save_topic(self, request: Request, session: WebSession, form: dict[str, str]) -> Response:
        configuration = self.archive.configuration
        if configuration is None:
            return self.site._reply(request, 503, msg("Themenverwaltung nicht verfügbar."))
        if "draft_id" in form:
            return self.topic_site.editing.confirm(request, session, form)
        try:
            if form.get("original_id") and form["id"] != form["original_id"]:
                raise ValueError("IDs dürfen nicht geändert werden")
            topic: dict[str, Any] = {key: form[key] for key in ("id", "name", "description")}
            topic["enabled"] = {"true": True, "false": False}[form["enabled"].lower()]
            topic.update({key: [v.strip() for v in (form[key].splitlines() if form.get("list_format") == "lines"
                                                 else form[key].split(";")) if v.strip()]
                          for key in ("examples", "exclusions")})
            filename = dict(TOPIC_FILES)[form["category"]]
            saved_topics = yaml.safe_load((configuration.directory / filename).read_text(encoding="utf-8"))["topics"]
            existing: dict[str, Any] = next((item for item in saved_topics if item["id"] == topic["id"]), {})
            topic["mailboxes"] = existing.get("mailboxes")
            command = AdminCommand(kind=AdminKind.TOPICS, actor=f"web:{session.id}", idempotency_key=form["key"],
                                   expected_hash=form["expected_hash"], category=form["category"], patch=topic,
                                   acknowledged=form.get("confirm") == "yes")
            configuration.candidate(command)
        except ConfigurationConflict:
            return self.site._reply(request, 409, msg("Themendatei geändert; bitte neu laden."))
        except (ValueError, KeyError, OSError):
            return self.site._reply(request, 422, msg("Ungültige, unbestätigte oder inzwischen geänderte Themen."))
        return self.archive.queue(request, command)
