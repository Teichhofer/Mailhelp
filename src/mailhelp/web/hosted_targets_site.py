"""8.2: central Inboxstride OAuth flows for Microsoft (Graph Calendar & To Do) and Notion targets."""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx

from ..external.hosted_oauth import HostedAuthClient, HostedRefused, HostedUnavailable, forget_locally
from ..i18n import msg, tr
from ..persistence.storage import JsonStore
from ..runtime.notion_sources import data_sources
from .auth import WebSession
from .forms import field, post_form, select
from .hosted_google_site import session_reference
from .http import CONTENT_SECURITY_POLICY, Request, Response
from .pages import e, error_page, layout

PENDING = "hosted-targets"
LIFETIME = timedelta(minutes=10)
PROVIDERS: dict[str, tuple[str, str, str]] = {
    "microsoft": ("microsoft_targets", "microsoft_connection", "login.microsoftonline.com"),
    "notion": ("notion", "notion_connection", "api.notion.com"),
}
_TARGET_ID = re.compile(r"^[A-Za-z0-9=_+/-]{1,500}$")


@dataclass(frozen=True)
class HostedTargetContext:
    read: Callable[[int, str], tuple[str, int]]
    save: Callable[[str, int, dict[str, Any], int, str], None]
    target: Callable[[int], str]


class HostedTargetsSite:
    def __init__(self, site: Any, store: JsonStore, client: Callable[[], HostedAuthClient | None],
                 context: HostedTargetContext, setup_path: str, *, transport: httpx.BaseTransport | None = None,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC), navigation: bool = True) -> None:
        self.site, self.store, self.client, self.context = site, store, client, context
        self.setup_path, self.transport, self.clock, self.navigation = setup_path, transport, clock, navigation
        for provider in PROVIDERS:
            base = f"/{provider}"
            ret = f"/einrichtung/{provider}/abschluss"
            for method, path, handler in (("GET", f"{base}/verbinden", self.offer),
                                          ("POST", f"{base}/verbinden", self.start),
                                          ("POST", ret, self.redeem),
                                          ("GET", f"{base}/ziele", self.targets),
                                          ("POST", f"{base}/ziele", self.adopt),
                                          ("POST", f"{base}/trennen", self.disconnect)):
                site.app.route(method, path, site.signed_in(self._bind(provider, handler)))
            site.app.route("GET", ret, self._bind(provider, self.returned))

    @staticmethod
    def _bind(provider: str, handler: Callable[..., Response]) -> Callable[..., Response]:
        def wrapped(request: Request, *args: Any) -> Response:
            return handler(provider, request, *args)
        return wrapped

    def _page(self, status: int, title: str, body: str) -> Response:
        response = Response.html(status, layout(title, body, signed_in=self.navigation))
        response.headers.update({"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
        return response

    def _failed(self, text: str, status: int = 409) -> Response:
        response = Response.html(status, error_page(tr("Zielverbindung nicht möglich"), text))
        response.headers["Cache-Control"] = "no-store"
        return response

    @staticmethod
    def _profile(values: dict[str, list[str]] | dict[str, str]) -> int:
        raw = values.get("profile", "1")
        number = int(raw[0] if isinstance(raw, list) else raw)
        if not 1 <= number <= 99:
            raise ValueError("Ungültiges Zielprofil.")
        return number

    def _hub(self, purpose: str) -> HostedAuthClient:
        client = self.client()
        if client is None or purpose not in client.post("/intern/providers", {}).get("providers", []):
            raise HostedUnavailable("nicht eingerichtet")
        return client

    def offer(self, provider: str, request: Request, session: WebSession) -> Response:
        purpose, field_name, host = PROVIDERS[provider]
        try:
            self._hub(purpose)
            profile = self._profile(parse_qs(request.query, max_num_fields=5))
            connection, version = self.context.read(profile, field_name)
        except (ValueError, LookupError):
            return self._failed(tr("Dieses Zielprofil gibt es nicht."), 404)
        except (HostedRefused, HostedUnavailable):
            return self._failed(tr("Die Zielverbindung über Inboxstride ist für diese Installation nicht "
                                   "eingerichtet. Bitte den Betreiber informieren."), 503)
        title = tr("Microsoft verbinden") if provider == "microsoft" else tr("Notion verbinden")
        csrf = self.site.auth.csrf_token(session.id)
        body = (f"<h1>{e(title)}</h1>"
                + tr("<p>Zielprofil {profile}. Nach der Anmeldung beim Anbieter prüfst du hier die Zielauswahl "
                     "und übernimmst die Verbindung ausdrücklich. Die Verbindung selbst legt keine Einträge an.</p>",
                     profile=profile)
                + post_form(f"/{provider}/verbinden", csrf, "", msg("Weiter zum Anbieter"),
                            primary=True, profile=profile))
        if connection:
            body += post_form(f"/{provider}/trennen", csrf, "", msg("Verbindung trennen"),
                              profile=profile, version=version)
        response = self._page(200, title, body)
        response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY.replace(
            "form-action 'self'", f"form-action 'self' https://{host}")
        return response

    def start(self, provider: str, _request: Request, session: WebSession, form: dict[str, str]) -> Response:
        purpose, field_name, host = PROVIDERS[provider]
        try:
            client = self._hub(purpose)
            profile = self._profile(form)
            connection, version = self.context.read(profile, field_name)
            reference = session_reference(session)
            answer = client.post("/intern/start", {
                "session": reference, "target": self.context.target(profile), "purpose": purpose,
                "operation": "reauthorize" if connection else "connect", "key": form["key"]})
            destination = urlsplit(str(answer.get("url", "")))
            if destination.scheme != "https" or destination.netloc != host:
                raise ValueError("Ungültiges Weiterleitungsziel")
            with self.store.locked():
                pending = self.store.load(PENDING, {})
                pending[f"{provider}:{reference}"] = {
                    "job": answer["job"], "profile": profile, "version": version, "provider": provider,
                    "purpose": purpose, "expires": (self.clock() + LIFETIME).isoformat()}
                self.store.save(PENDING, pending)
            return Response(303, headers={"Location": answer["url"], "Cache-Control": "no-store"})
        except (KeyError, ValueError, LookupError, HostedRefused):
            return self._failed(tr("Die Anfrage war unvollständig oder veraltet. Bitte erneut versuchen."))
        except HostedUnavailable:
            return self._failed(tr("Der Inboxstride-Anmeldedienst ist gerade nicht erreichbar."), 503)

    def returned(self, provider: str, request: Request) -> Response:
        query = parse_qs(request.query, max_num_fields=5)
        receipt = (query.get("beleg") or [""])[0]
        if query.get("abbruch") or not re.fullmatch(r"[A-Za-z0-9_-]{16,120}", receipt):
            return self._failed(tr("Die Anmeldung beim Anbieter wurde abgebrochen oder ist abgelaufen."))
        body = (tr("<h1>Anmeldung zurückgekehrt</h1><p>Zum sicheren Abschluss bitte die Zielauswahl öffnen.</p>")
                + f'<p><a class="button primary" href="/{provider}/ziele?beleg={e(receipt)}">'
                  f'{e(tr("Zielverbindung prüfen"))}</a></p>')
        return self._page(200, tr("Anmeldung zurückgekehrt"), body)

    def _pending(self, session: WebSession, provider: str) -> dict[str, Any]:
        record: dict[str, Any] = self.store.load(PENDING, {})[f"{provider}:{session_reference(session)}"]
        if datetime.fromisoformat(record["expires"]) <= self.clock():
            raise ValueError("expired")
        _connection, version = self.context.read(record["profile"], PROVIDERS[provider][1])
        if version != record["version"]:
            raise ValueError("version_changed")
        return record

    def redeem(self, provider: str, _request: Request, session: WebSession, form: dict[str, str]) -> Response:
        purpose, _field, _host = PROVIDERS[provider]
        try:
            pending = self._pending(session, provider)
            reference = session_reference(session)
            result = self._hub(purpose).post("/intern/redeem", {"session": reference, "receipt": form["receipt"]})
            if (result.get("job"), result.get("target"), result.get("purpose")) != (
                    pending["job"], self.context.target(pending["profile"]), purpose):
                raise ValueError("wrong_binding")
            with self.store.locked():
                records = self.store.load(PENDING, {})
                records[f"{provider}:{reference}"] = {**pending, "connection": result["connection"],
                                                      "job_version": result["version"]}
                self.store.save(PENDING, records)
            return Response.redirect(f"/{provider}/ziele")
        except (KeyError, ValueError, LookupError, HostedRefused):
            return self._failed(tr("Der Abschlussbeleg ist ungültig oder abgelaufen. Bitte erneut starten."))
        except HostedUnavailable:
            return self._failed(tr("Der Inboxstride-Anmeldedienst ist gerade nicht erreichbar."), 503)

    def _candidate_token(self, pending: dict[str, Any]) -> str:
        connection = str(pending.get("connection", ""))
        if not connection:
            raise ValueError("missing_candidate")
        answer = self._hub(pending["purpose"]).post(
            "/intern/token", {"connection": connection, "purpose": pending["purpose"]})
        token = answer.get("access_token")
        if not isinstance(token, str) or not token:
            raise ValueError("missing_token")
        return token

    def targets(self, provider: str, request: Request, session: WebSession) -> Response:
        query = parse_qs(request.query, max_num_fields=5)
        csrf = self.site.auth.csrf_token(session.id)
        if "beleg" in query:
            receipt = query["beleg"][0]
            body = (tr("<h1>Zielverbindung prüfen</h1><p>Mit deiner aktuellen Sitzung bestätigen.</p>")
                    + post_form(f"/einrichtung/{provider}/abschluss", csrf,
                                field("receipt", "", receipt, hidden=True), msg("Zielverbindung prüfen"), primary=True))
            return self._page(200, tr("Zielverbindung prüfen"), body)
        try:
            pending = self._pending(session, provider)
            token = self._candidate_token(pending)
            if provider == "microsoft":
                controls = (field("outlook_calendar", msg("Outlook-Kalender-ID"), "default")
                            + field("microsoft_todo_list", msg("Microsoft-To-Do-Liste"), "default"))
            else:
                choices = data_sources(token, self.transport)
                if not choices:
                    raise ValueError("no_sources")
                controls = select("source", msg("Notion-Datenquelle"), choices[0][0], choices)
        except (KeyError, ValueError, LookupError, HostedRefused, httpx.HTTPError):
            return self._failed(tr("Die Ziele konnten nicht gelesen werden oder der Vorgang ist abgelaufen."))
        except HostedUnavailable:
            return self._failed(tr("Der Inboxstride-Anmeldedienst ist gerade nicht erreichbar."), 503)
        body = (tr("<h1>Ziel auswählen und übernehmen</h1><p>Zielprofil {profile}.</p>", profile=pending["profile"])
                + post_form(f"/{provider}/ziele", csrf, controls, msg("Zielverbindung übernehmen"), primary=True))
        return self._page(200, tr("Ziel auswählen und übernehmen"), body)

    def _patch(self, provider: str, pending: dict[str, Any], token: str, form: dict[str, str]) -> dict[str, Any]:
        connection = str(pending["connection"])
        if provider == "microsoft":
            calendar = form.get("outlook_calendar", "").strip()
            todo = form.get("microsoft_todo_list", "").strip()
            if not _TARGET_ID.fullmatch(calendar) or not _TARGET_ID.fullmatch(todo):
                raise ValueError("invalid_microsoft_targets")
            return {"microsoft_connection": connection, "outlook_calendar": calendar, "microsoft_todo_list": todo}
        source = form.get("source", "").strip()
        if source not in dict(data_sources(token, self.transport)):
            raise ValueError("invalid_notion_source")
        return {"notion_connection": connection, "notion_data_source_id": source}

    def adopt(self, provider: str, _request: Request, session: WebSession, form: dict[str, str]) -> Response:
        purpose, field_name, _host = PROVIDERS[provider]
        try:
            pending = self._pending(session, provider)
            token = self._candidate_token(pending)
            patch = self._patch(provider, pending, token, form)
            if pending.get("adopting") and pending["adopting"] != patch:
                raise ValueError("adoption_changed")
            reference = session_reference(session)
            slot = f"{provider}:{reference}"
            if not pending.get("saved"):
                self.context.save("web:" + session.id, pending["profile"], patch, pending["version"], form["key"])
                _conn, new_version = self.context.read(pending["profile"], field_name)
                with self.store.locked():
                    records = self.store.load(PENDING, {})
                    records[slot] = {**pending, "version": new_version, "saved": True, "adopting": patch}
                    self.store.save(PENDING, records)
            if not self.site.auth.active(session.id):
                raise ValueError("session_expired")
            activated = self._hub(purpose).post("/intern/activate", {
                "session": reference, "job": pending["job"], "version": int(pending["job_version"])})
            if activated.get("connection") != pending["connection"]:
                raise ValueError("activation_mismatch")
            with self.store.locked():
                records = self.store.load(PENDING, {})
                records.pop(slot, None)
                self.store.save(PENDING, records)
        except (KeyError, ValueError, LookupError, HostedRefused, httpx.HTTPError):
            return self._failed(tr("Die Verbindung wurde inzwischen geändert oder ist abgelaufen. Bitte erneut "
                                   "starten; die bisherige Verbindung bleibt unverändert."))
        except HostedUnavailable:
            return self._failed(tr("Der Inboxstride-Anmeldedienst ist gerade nicht erreichbar."), 503)
        if provider == "notion" and self.navigation:
            return Response.redirect(f'/notion/zuordnung?profile={pending["profile"]}')
        return Response.redirect(self.site.setup_return(session, self.setup_path))

    def disconnect(self, provider: str, _request: Request, session: WebSession, form: dict[str, str]) -> Response:
        purpose, field_name, _host = PROVIDERS[provider]
        try:
            client = self._hub(purpose)
            profile = self._profile(form)
            connection, version = self.context.read(profile, field_name)
            if not connection or int(form["version"]) != version or not form["key"]:
                raise ValueError("changed")
            client.post("/intern/disconnect", {"connection": connection})
            forget_locally(connection)
        except (KeyError, ValueError, LookupError, HostedRefused):
            return self._failed(tr("Die Verbindung wurde inzwischen geändert oder ist abgelaufen. Bitte erneut "
                                   "starten; die bisherige Verbindung bleibt unverändert."))
        except HostedUnavailable:
            return self._failed(tr("Der Inboxstride-Anmeldedienst ist gerade nicht erreichbar."), 503)
        return Response.redirect(self.site.setup_return(session, self.setup_path))


__all__ = ["PROVIDERS", "HostedTargetContext", "HostedTargetsSite"]
