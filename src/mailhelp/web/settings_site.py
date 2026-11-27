"""Settings and topics: every change is shown first and queued as an explicit command."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, quote

import yaml

from ..config import Settings
from ..config.configuration import SETTINGS_FIELDS, AdminCommand, AdminKind, ConfigurationConflict, file_hash
from ..i18n import COOKIE, msg, tr
from ..persistence.storage import CorruptState
from ..runtime.credentials import CredentialService, CredentialUnauthorized
from .auth import WebSession
from .customer_settings import GENERAL_FIELDS, customer_general_page, customer_settings_page
from .http import Request, Response, cookie
from .pages import layout, notice
from .settings_pages import (
    AREA_KEYS,
    GENERAL_PATH,
    LEGACY_AREAS,
    NO_DEFAULT,
    SETTING_PREFIX,
    TEXT_SETTINGS,
    _lookup,
    default_value,
    setting_label,
    settings_back,
    settings_confirmation,
    settings_page,
    settings_review,
)
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


def _parsed(name: str, text: str, saved: object = None, *, typed: bool = False) -> Any:
    """A form value as the configuration stores it.

    *typed* (8.5 section forms) keeps saved strings as text and an emptied optional value as
    ``None``, so an unchanged value such as a numeric project ID is never reported as a change.
    """
    if name == "briefings.times":
        return [part for part in re.split(r"[,;\s]+", text.strip()) if part]
    if name in TEXT_SETTINGS:
        # Browsers send line breaks as CRLF; the file keeps plain LF.
        return text.replace("\r\n", "\n").strip()
    if typed and saved is None and text == "":
        return None
    if typed and isinstance(saved, str):
        return text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _section_patch(form: dict[str, str], saved: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """The changed values of a section form; ``zuruecksetzen`` asks for one default value instead."""
    reset = form.get("zuruecksetzen")
    if reset:
        default = default_value(reset) if reset in SETTINGS_FIELDS else NO_DEFAULT
        if default is NO_DEFAULT:
            raise ValueError("Kein Standardwert")
        text = default if isinstance(default, str) else json.dumps(default)
        return {reset: default}, {reset: text}
    patch: dict[str, Any] = {}
    texts: dict[str, str] = {}
    for key, text in form.items():
        if not key.startswith(SETTING_PREFIX):
            continue
        name = key.removeprefix(SETTING_PREFIX)
        if name not in SETTINGS_FIELDS:
            raise ValueError("Nicht angebotene Einstellung")
        current = _lookup(saved, name)
        value = _parsed(name, text, current, typed=True)
        if value != current:
            patch[name], texts[name] = value, text
    return patch, texts


TOPIC_FILES = (("relevant", "topics.yaml"), ("irrelevant", "irrelevant_topics.yaml"))


class SettingsSite:
    def __init__(self, archive: ArchiveSite) -> None:
        self.archive, self.site = archive, archive.site
        for method, path, handler in (
                ("GET", "/einstellungen", self.settings), ("POST", "/einstellungen/speichern", self.save_settings),
                ("GET", GENERAL_PATH, self.general), ("POST", GENERAL_PATH, self.save_general),
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
        if not self.site.auth.is_operator(session):
            return Response.html(200, layout(msg("Einstellungen"), customer_settings_page(), active="/einstellungen"))
        query = parse_qs(request.query)
        area = query.get("bereich", [""])[0]
        if area in LEGACY_AREAS:
            # 8.5: bookmarks and help links of the former areas keep working.
            return Response(308, headers={"Location": f"/einstellungen?bereich={LEGACY_AREAS[area]}"})
        if area and area not in AREA_KEYS:
            return self.site._reply(request, 404, msg("Unbekannter Einstellungsbereich."))
        raw, active, revision = self._saved()
        csrf = self.site.auth.csrf_token(session.id)
        service = self.credential_service()
        try:
            credentials = service.snapshot() if service is not None else None
        except (OSError, ValueError):
            credentials = None
        page = settings_page(self.archive.models, raw, active, revision, csrf, credentials, area,
                             query.get("suche", [""])[0][:80], self.site.experience.controls(csrf, session.id))
        return Response.html(200, layout(msg("Einstellungen"), page, active="/einstellungen"))

    def _saved(self) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str]:
        configuration = self.archive.configuration
        if configuration is None:
            return None, None, ""
        path = configuration.directory / "config.yaml"
        return (_effective(yaml.safe_load(path.read_text(encoding="utf-8"))),
                configuration.active.model_dump(mode="json"), file_hash(path))

    def general(self, _request: Request, session: WebSession) -> Response:
        """8.8.2: the customer's personal values on their own page (also open for the operator)."""
        raw, active, revision = self._saved()
        page = customer_general_page(raw, active, revision, self.site.auth.csrf_token(session.id))
        return Response.html(200, layout(msg("Allgemein"), page, active="/einstellungen"))

    def save_general(self, request: Request, session: WebSession, form: dict[str, str]) -> Response:
        """Only the page's own fields; everything else is refused before a draft or command exists."""
        if self.archive.configuration is None:
            return self.site._reply(request, 503, msg("Konfiguration nicht verfügbar."))
        names = [key.removeprefix(SETTING_PREFIX) for key in form if key.startswith(SETTING_PREFIX)]
        if form.get("zuruecksetzen"):
            names.append(form["zuruecksetzen"])
        if "name" in form or any(name not in GENERAL_FIELDS for name in names):
            self.site.logger.event("WARNING", "web", "general_field_refused")
            return self.site._reply(request, 403, msg("Diese Einstellung ist hier nicht änderbar."))
        return self._save_section(request, session, form, GENERAL_PATH)

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
        if "name" not in form:
            return self._save_section(request, session, form)
        value: Any
        try:
            value = _parsed(form["name"], form["value"])
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
        return self._queued(request, command)

    def _queued(self, request: Request, command: AdminCommand) -> Response:
        response = self.archive.queue(request, command)
        if "language" in command.patch:
            language = str(command.patch["language"])
            response.cookies.append(cookie(request, COOKIE, language, 31536000, http_only=False, same_site="Lax"))
        return response

    def _save_section(self, request: Request, session: WebSession, form: dict[str, str],
                      route: str = "/einstellungen/speichern") -> Response:
        """8.5: the changed values of one section form; checked together, taken over together."""
        configuration = self.archive.configuration
        assert configuration is not None  # checked by save_settings
        area = form.get("bereich", "")
        try:
            raw = yaml.safe_load((configuration.directory / "config.yaml").read_text(encoding="utf-8"))
            saved = _effective(raw)
            patch, texts = _section_patch(form, saved)
            if not patch:
                return self._unchanged(area)
            command = AdminCommand(kind=AdminKind.SETTINGS, actor=f"web:{session.id}", idempotency_key=form["key"],
                                   expected_hash=form["expected_hash"], patch=patch, acknowledged=True)
            try:
                configuration.candidate(command)
            except ConfigurationConflict:
                raise
            except ValueError:
                return self._invalid(configuration, command)
        except ConfigurationConflict:
            return self.site._reply(request, 409, msg("Einstellungsdatei geändert; bitte neu laden."))
        except (ValueError, KeyError, OSError):
            return self.site._reply(
                request, 422, msg("Ungültige oder inzwischen geänderte Einstellung; bitte neu prüfen.")
            )
        if form.get("confirm") != "yes":
            body = settings_review(patch, texts, form["expected_hash"], self.site.auth.csrf_token(session.id),
                                   saved, area, route)
            return Response.html(200, layout(tr("Änderungen prüfen"), body, active="/einstellungen"))
        return self._queued(request, command)

    @staticmethod
    def _unchanged(area: str) -> Response:
        back = settings_back(area)
        body = (tr("<h1>Keine Änderung</h1>") + notice(tr("Alle Werte entsprechen dem gespeicherten Stand."), "info")
                + f'<p><a class="button" href="{back}">{tr("Zurück")}</a></p>')
        return Response.html(200, layout(tr("Keine Änderung"), body, active="/einstellungen"))

    @staticmethod
    def _invalid(configuration: Any, command: AdminCommand) -> Response:
        """Name every value the configuration would reject; nothing is taken over."""
        refused = []
        for name, value in command.patch.items():
            try:
                configuration.candidate(command.model_copy(update={"patch": {name: value}}))
            except ValueError:
                refused.append(str(setting_label(name)))
        if not refused:  # valid alone, but not together
            refused = [str(setting_label(name)) for name in command.patch]
        body = (tr("<h1>Nicht übernommen</h1>")
                + notice(tr("Ungültiger Wert bei: {p0}. Es wurde nichts gespeichert.", p0=", ".join(refused)),
                         "error"))
        return Response.html(422, layout(tr("Nicht übernommen"), body, active="/einstellungen"))

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
