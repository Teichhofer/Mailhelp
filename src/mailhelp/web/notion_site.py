"""7.2.4: choose a Notion data source and map its properties in the browser.

Both steps only read Notion and store a settings draft; the draft is applied like every other
settings change. Saving reads the data source again, so a choice is never based on a stale list.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx

from ..config import NotionProperties
from ..external.notion import TYPES, DataSource, check_mapping, options
from ..runtime.notion_sources import data_sources, notion_token, schema
from .auth import WebSession
from .forms import post_form, select
from .http import Request, Response
from .pages import e, error_page, layout

LABELS = {"title": "Titel", "description": "Beschreibung", "due": "Frist", "source": "Quelle (Link zur Mail)",
          "operation_key": "Vorgangsschlüssel", "status": "Status (optional)"}
# The current targets of a profile and the draft version; and saving a patch of target fields.
Context = Callable[[int], tuple[Any, int]]
Save = Callable[[str, int, dict[str, Any], int, str], None]


class NotionSite:
    def __init__(self, site: Any, directory: Path, context: Context, save: Save,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.site, self.directory, self.context, self.save, self.transport = site, directory, context, save, transport
        for method, path, handler in (("GET", "/notion/datenquelle", self.sources),
                                      ("POST", "/notion/datenquelle", self.choose_source),
                                      ("GET", "/notion/zuordnung", self.mapping),
                                      ("POST", "/notion/zuordnung", self.choose_mapping)):
            site.app.route(method, path, site.signed_in(handler))

    @staticmethod
    def _profile(request: Request) -> int:
        number = int(parse_qs(request.query, max_num_fields=5).get("profile", ["1"])[0])
        if not 1 <= number <= 99:
            raise ValueError("Ungültiges Zielprofil.")
        return number

    @staticmethod
    def failed() -> Response:
        return Response.html(409, error_page(
            "Notion-Auswahl nicht möglich",
            "Notion-Token, Freigabe der Datenbank für die Verbindung und Zielprofil prüfen. "
            "Mailhelp legt in Notion nichts an."))

    def _token(self, profile: int) -> str:
        return notion_token(self.directory, profile)

    def sources(self, request: Request, session: WebSession) -> Response:
        try:
            profile = self._profile(request)
            choices = data_sources(self._token(profile), self.transport)
            current, version = self.context(profile)
        except Exception:
            return self.failed()
        body = ("<h1>Notion-Datenquelle auswählen</h1><p>Angezeigt werden die Datenquellen, die für die "
                "Verbindung freigegeben sind.</p>" + post_form(
                    "/notion/datenquelle", self.site.auth.csrf_token(session.id),
                    select("source", "Datenquelle", current.notion_data_source_id, choices),
                    "Als Entwurf speichern", profile=profile, version=version))
        return Response.html(200, layout("Notion-Datenquelle", body))

    def choose_source(self, _request: Request, session: WebSession, form: dict[str, str]) -> Response:
        try:
            profile = int(form["profile"])
            if form["source"] not in dict(data_sources(self._token(profile), self.transport)):
                raise ValueError("Datenquelle nicht verfügbar.")
            self.save("web:" + session.id, profile, {"notion_data_source_id": form["source"]},
                      int(form["version"]), form["key"])
        except Exception:
            return self.failed()
        return Response.redirect(f"/notion/zuordnung?profile={profile}")

    def _schema(self, profile: int, targets: Any) -> DataSource:
        if not targets.notion_data_source_id:
            raise ValueError("Zuerst eine Datenquelle wählen.")
        return schema(self._token(profile), targets.notion_data_source_id, self.transport)

    def mapping(self, request: Request, session: WebSession) -> Response:
        try:
            profile = self._profile(request)
            targets, version = self.context(profile)
            source = self._schema(profile, targets)
        except Exception:
            return self.failed()
        properties = list(source.properties.values())
        current = targets.notion_properties
        fields = ""
        for name, label in LABELS.items():
            fitting = [(item.id, f"{item.name or item.id} ({item.type})") for item in properties
                       if item.type in TYPES[name]]
            empty = [("", "– ohne Status –" if name == "status" else "– bitte wählen –")]
            fields += select(name, label, getattr(current, name), empty + fitting)
        states = [(option["id"], f"{item.name or item.id}: {option.get('name', option['id'])}")
                  for item in properties if item.type in {"status", "select"} for option in options(item)]
        fields += select("open", "Status neuer Seiten", targets.notion_open_status, [("", "–"), *states])
        fields += "<fieldset><legend>Gilt als erledigt</legend>" + "".join(
            f'<label><input type="checkbox" name="done_{e(value)}" value="1"'
            f'{" checked" if value in targets.notion_done_statuses else ""}> {e(text)}</label>'
            for value, text in states) + "</fieldset>"
        body = ("<h1>Notion-Eigenschaften zuordnen</h1><p>Mailhelp nutzt die IDs der Eigenschaften; ein "
                "späteres Umbenennen in Notion ändert nichts. Ohne Statusfeld erkennt Mailhelp erledigte "
                "Seiten nicht.</p>" + post_form("/notion/zuordnung", self.site.auth.csrf_token(session.id), fields,
                                               "Als Entwurf speichern", profile=profile, version=version))
        return Response.html(200, layout("Notion-Zuordnung", body))

    def choose_mapping(self, _request: Request, session: WebSession, form: dict[str, str]) -> Response:
        try:
            profile = int(form["profile"])
            targets, _version = self.context(profile)
            source = self._schema(profile, targets)
            fields = NotionProperties.model_validate({name: form.get(name, "") for name in LABELS})
            if not all(getattr(fields, name) for name in LABELS if name != "status"):
                raise ValueError("Pflichtfelder fehlen.")
            done = sorted(name.removeprefix("done_") for name, value in form.items()
                          if name.startswith("done_") and value == "1")
            open_status = form.get("open", "") if fields.status else ""
            done = done if fields.status else []
            # The same check as before every write: ids, types and status options of this source.
            check_mapping(source, fields, open_status, frozenset(done))
            self.save("web:" + session.id, profile, {"notion_properties": fields.model_dump(),
                                                      "notion_open_status": open_status,
                                                      "notion_done_statuses": done},
                      int(form["version"]), form["key"])
        except Exception:
            return self.failed()
        return Response.redirect("/einrichtung/start")
