"""Browser consent, persistent device-code progress and the bundled Playground guide."""
from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlencode

from ..runtime.google_calendars import google_calendars
from ..runtime.initial_setup import default_file
from ..runtime.oauth_web import BrowserOAuth
from .auth import WebSession
from .forms import post_form, select
from .http import Request, Response
from .login_site import SESSION_COOKIE
from .pages import e, error_page, layout


class OAuthSite:
    def __init__(self, site: Any, service: BrowserOAuth,
                 calendar_context: Callable[[int], tuple[str, int]],
                 save_calendar: Callable[[str, int, str, int, str], None]):
        self.site, self.service = site, service
        self.calendar_context, self.save_calendar = calendar_context, save_calendar
        for method, path, handler in (
            ("GET", "/hilfe/google-playground", self.guide),
            ("GET", "/auth/google/start", self.google_start),
            ("POST", "/auth/google/start", self.start_google),
            ("GET", "/auth/microsoft", self.microsoft_start),
            ("POST", "/auth/microsoft/device", self.start_microsoft),
            ("GET", "/auth/microsoft/poll", self.progress),
            ("GET", r"/auth/status/(?P<identity>[a-f0-9]{64})", self.progress),
            ("GET", "/auth/google/kalender", self.calendars),
            ("POST", "/auth/google/kalender", self.choose_calendar)):
            site.app.route(method, path, site.signed_in(handler))
        site.app.route("GET", "/auth/google/callback", self.google_callback)

    @staticmethod
    def _profile(request: Request) -> int:
        values = parse_qs(request.query, max_num_fields=5)
        number = int(values.get("profile", ["1"])[0])
        if not 1 <= number <= 99:
            raise ValueError("Ungültiges Zielprofil.")
        return number

    @staticmethod
    def failed() -> Response:
        return Response.html(409, error_page("Anmeldung nicht abgeschlossen",
            "Sitzung, Zielprofil und Zugangsdaten prüfen oder die Anmeldung erneut starten. "
            "Die Google-Anleitung ist unter /hilfe/google-playground verfügbar."))

    def guide(self, _request: Request, _session: WebSession) -> Response:
        body = ('<h1>Google OAuth 2.0 Playground</h1><p>'
                '<a href="https://console.cloud.google.com/" rel="noreferrer">Google Cloud Console öffnen</a> · '
                '<a href="https://developers.google.com/oauthplayground/" rel="noreferrer">Playground öffnen</a></p>'
                '<pre class="mail-text">' + e(default_file("google-oauth-playground.md")) + '</pre>')
        return Response.html(200, layout("Google einrichten", body))

    def _start_page(self, request: Request, session: WebSession, provider: str) -> Response:
        try:
            profile = self._profile(request)
            revision = self.service.revision(profile, provider)
        except (ValueError, LookupError):
            return self.failed()
        path = "/auth/google/start" if provider == "google" else "/auth/microsoft/device"
        body = (f'<h1>{e(provider.title())} verbinden</h1><p>Zielprofil {profile}. '
                'Clientdaten zuerst in den Zugangsdaten speichern. '
                'Die Anmeldung erstellt keine Termine oder Aufgaben.</p>'
                '<p><a href="/hilfe/google-playground">Google: Playground-Anleitung</a></p>')
        body += post_form(path, self.site.auth.csrf_token(session.id), "", "Anmeldung starten",
                          profile=profile, revision=revision)
        return Response.html(200, layout("Konto verbinden", body))

    def google_start(self, request: Request, session: WebSession) -> Response:
        return self._start_page(request, session, "google")

    def microsoft_start(self, request: Request, session: WebSession) -> Response:
        return self._start_page(request, session, "microsoft")

    def start_google(self, _request: Request, session: WebSession, form: dict[str, str]) -> Response:
        return self._start(session, form, "google")

    def start_microsoft(self, _request: Request, session: WebSession, form: dict[str, str]) -> Response:
        return self._start(session, form, "microsoft")

    def _start(self, session: WebSession, form: dict[str, str], provider: Any) -> Response:
        try:
            job = self.service.start(provider, "web:" + session.id, int(form["profile"]), form["key"], form["revision"])
        except (ValueError, KeyError, PermissionError, LookupError):
            return self.failed()
        if provider == "google":
            return Response(303, headers={"Location": job.uri})
        return Response.redirect("/auth/status/" + job.id)

    def google_callback(self, request: Request) -> Response:
        try:
            query = parse_qs(request.query, max_num_fields=6)
            identity = query["state"][0]
            if not re.fullmatch(r"[a-f0-9]{64}", identity) or "error" in query:
                return self.failed()
            code = query["code"][0]
            if not 1 <= len(code) <= 4096:
                return self.failed()
            session = self.site.auth.authenticate(request.cookies().get(SESSION_COOKIE))
            if session is None:
                # SameSite=Strict cookies are intentionally absent on Google's cross-site return.
                # A same-origin user click then carries the session; no token exchange happens here.
                href = "/auth/google/callback?" + urlencode({"state": identity, "code": code})
                return Response.html(200, layout("Google-Anmeldung abschließen",
                    '<h1>Zurück bei Mailhelp</h1><p>Die Anmeldung im ursprünglichen Browser abschließen.</p>'
                    f'<a class="button" href="{e(href)}">Google-Anmeldung abschließen</a>', signed_in=False))
            job = self.service.google_callback(identity, "web:" + session.id, code)
        except (ValueError, KeyError, PermissionError, LookupError):
            return self.failed()
        return Response.redirect("/auth/status/" + job.id)

    def progress(self, request: Request, session: WebSession, identity: str = "") -> Response:
        try:
            if not identity:
                identity = parse_qs(request.query, max_num_fields=2)["id"][0]
            job = self.service.job(identity, "web:" + session.id)
        except (ValueError, KeyError, PermissionError):
            return self.failed()
        pending = job.status in {"starting", "pending", "committing", "exchanging"}
        body = f'<h1>Konto verbinden</h1><p role="status">Status: {e(job.status)}</p>'
        if job.provider == "microsoft" and job.uri:
            body += ('<section role="dialog" aria-modal="false" aria-label="Microsoft-Anmeldung">'
                     f'<p>Code: <strong>{e(job.user_code)}</strong></p>'
                     f'<button type="button" data-copy-code="{e(job.user_code)}">Code kopieren</button>'
                     f'<p><a href="{e(job.uri)}" target="_blank" rel="noreferrer">'
                     'Bei Microsoft anmelden</a></p></section>')
        if job.status == "done":
            body += ('<p>Anmeldung gespeichert. Nach dem nächsten Neustart nutzt der Mailabruf die neuen Daten.</p>'
                     '<p><a href="/einrichtung/start">Zur Einrichtung</a> · '
                     f'<a href="/auth/google/kalender?profile={job.profile}">Google-Kalender auswählen</a></p>')
        return Response.html(200, layout("Anmeldestatus", body, refresh=2 if pending else None,
            after='<script src="/static/setup.js" defer></script>'))

    def calendars(self, request: Request, session: WebSession) -> Response:
        try:
            profile = self._profile(request)
            choices = google_calendars(self.service.directory, profile, self.service.config(profile, "google"),
                                       self.service.transport)
            current, version = self.calendar_context(profile)
        except Exception:
            return self.failed()
        body = '<h1>Google-Kalender auswählen</h1>' + post_form("/auth/google/kalender",
            self.site.auth.csrf_token(session.id), select("calendar", "Kalender mit Schreibrecht", current, choices),
            "Als Entwurf speichern", profile=profile, version=version,
            revision=self.service.revision(profile, "google"))
        return Response.html(200, layout("Kalenderauswahl", body))

    def choose_calendar(self, _request: Request, session: WebSession, form: dict[str, str]) -> Response:
        try:
            profile = int(form["profile"])
            if self.service.revision(profile, "google") != form["revision"]:
                raise ValueError("Zugangsdaten geändert.")
            choices = google_calendars(self.service.directory, profile, self.service.config(profile, "google"),
                                       self.service.transport)
            if form["calendar"] not in dict(choices):
                raise ValueError("Kalender nicht verfügbar.")
            self.save_calendar("web:" + session.id, profile, form["calendar"], int(form["version"]), form["key"])
        except Exception:
            return self.failed()
        return Response.redirect("/einrichtung/start")
