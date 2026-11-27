"""8.0: "Mit Google verbinden" through the central Inboxstride service (Planung 8.0, sections 4 and 5).

Start, return and adoption are separate, protected steps. Google's return lands on the
central service; the browser comes back here with a short one-time receipt only. A neutral page
asks for a same-origin POST, so the original session (its ``SameSite=Strict`` cookie) proves who
continues. The new access is read-only checked by listing the writable calendars, and it becomes
the profile's access only after the user explicitly adopts one calendar. Nothing here creates an
event or a task; the adopted values are a setup draft that is applied like every other change.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs

import httpx

from ..external.hosted_oauth import HostedAuthClient, HostedRefused, HostedUnavailable, forget_locally
from ..i18n import msg, tr
from ..persistence.storage import JsonStore
from ..runtime.google_calendars import listed_targets
from .auth import WebSession
from .forms import post_form, select
from .http import CONTENT_SECURITY_POLICY, Request, Response
from .login_site import SESSION_COOKIE
from .pages import e, error_page, layout

PENDING = "hosted-google"
LIFETIME = timedelta(minutes=10)


@dataclass(frozen=True)
class HostedProfiles:
    """How a setup flow reads and saves the Google access of a target profile.

    *draft* gives (current connection, draft version); *save* stores adopted values as a draft;
    *target* names the binding at the central service (``profile:<n>`` or the setup draft).
    """

    draft: Callable[[int], tuple[str, int]]
    save: Callable[[str, int, dict[str, str], int, str], None]
    target: Callable[[int], str]


def session_reference(session: WebSession) -> str:
    """The opaque session reference the central service binds a sign-in to; never the session id."""
    return hashlib.sha256(("mailhelp-session:" + session.id).encode("utf-8")).hexdigest()


class HostedGoogleSite:
    def __init__(self, site: Any, store: JsonStore, client: Callable[[], HostedAuthClient | None],
                 profiles: HostedProfiles, setup_path: str, *, transport: httpx.BaseTransport | None = None,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC), navigation: bool = True) -> None:
        """*navigation* is off in the initial setup, whose server has no other pages yet."""
        self.navigation = navigation
        self.site, self.store, self.client = site, store, client
        self.draft, self.save, self.target = profiles.draft, profiles.save, profiles.target
        self.setup_path, self.transport, self.clock = setup_path, transport, clock
        for method, path, handler in (("GET", "/google/verbinden", self.offer),
                                      ("POST", "/google/verbinden", self.start),
                                      ("POST", "/einrichtung/google/abschluss", self.redeem),
                                      ("GET", "/google/kalender", self.calendars),
                                      ("POST", "/google/kalender", self.adopt),
                                      ("GET", "/google/kalender/wechseln", self.other_calendars),
                                      ("POST", "/google/kalender/wechseln", self.change_calendar),
                                      ("POST", "/google/trennen", self.disconnect)):
            site.app.route(method, path, site.signed_in(handler))
        site.app.route("GET", "/einrichtung/google/abschluss", self.returned)

    # Pages --------------------------------------------------------------------------------------

    def _page(self, status: int, title: str, body: str, *, signed_in: bool = True) -> Response:
        response = Response.html(status, layout(title, body, signed_in=signed_in and self.navigation))
        response.headers.update({"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
        return response

    def _failed(self, text: str, status: int = 409) -> Response:
        response = Response.html(status, error_page(tr("Google-Verbindung nicht möglich"), text))
        response.headers["Cache-Control"] = "no-store"
        return response

    @staticmethod
    def _profile(values: dict[str, list[str]] | dict[str, str]) -> int:
        raw = values.get("profile", "1")
        number = int(raw[0] if isinstance(raw, list) else raw)
        if not 1 <= number <= 99:
            raise ValueError("Ungültiges Zielprofil.")
        return number

    def offer(self, request: Request, session: WebSession) -> Response:
        if self.client() is None:
            return self._failed(tr("Die Google-Verbindung über Inboxstride ist für diese Installation nicht "
                                   "eingerichtet. Bitte den Betreiber informieren."), 503)
        try:
            profile = self._profile(parse_qs(request.query, max_num_fields=5))
            connection, version = self.draft(profile)
        except (ValueError, LookupError):
            return self._failed(tr("Dieses Zielprofil gibt es nicht."), 404)
        title = tr("Google erneut verbinden") if connection else tr("Mit Google verbinden")
        csrf = self.site.auth.csrf_token(session.id)
        body = (f"<h1>{e(title)}</h1>"
                + tr("<p>Zielprofil {profile}. Bei Google wählst du dein Konto und erlaubst den Zugriff auf "
                     "deine Kalender. Danach wählst du hier den Kalender und übernimmst die Verbindung "
                     "ausdrücklich. Die Verbindung selbst legt keine Termine an.</p>", profile=profile)
                + post_form("/google/verbinden", csrf, "", msg("Weiter zu Google"), primary=True, profile=profile))
        if connection:
            # Planung 8.0, section 5: change the calendar without a new sign-in, or end the connection.
            body += (tr('<p><a href="/google/kalender/wechseln?profile={profile}">Anderen Kalender wählen</a></p>'
                        "<p>Trennen beendet die Tokenausgabe für diese Verbindung. Bereits angelegte Termine "
                        "bleiben; die Freigabe bei Google selbst wird nicht widerrufen.</p>", profile=profile)
                     + post_form("/google/trennen", csrf, "", msg("Verbindung trennen"), profile=profile,
                                 version=version))
        response = self._page(200, title, body)
        # Browsers check the redirect after a POST against form-action: only this page may continue to Google.
        response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY.replace(
            "form-action 'self'", "form-action 'self' https://accounts.google.com")
        return response

    def other_calendars(self, request: Request, session: WebSession) -> Response:
        """Another calendar of the existing access; a read only, then a separate adoption."""
        client = self.client()
        try:
            if client is None:
                raise HostedUnavailable("nicht eingerichtet")
            profile = self._profile(parse_qs(request.query, max_num_fields=5))
            connection, version = self.draft(profile)
            if not connection:
                raise LookupError("Keine Verbindung")
            choices = self._choices(client, connection)
        except LookupError:
            return self._failed(tr("Dieses Zielprofil hat keine Google-Verbindung über Inboxstride."), 404)
        except (ValueError, HostedRefused, HostedUnavailable, httpx.HTTPError):
            return self._failed(tr("Die Kalender konnten nicht gelesen werden. Die bisherige Verbindung bleibt "
                                   "unverändert."), 503)
        body = (tr("<h1>Anderen Kalender wählen</h1><p>Zielprofil {profile}. Offene Vorschläge brauchen nach "
                   "dem Wechsel eine neue Bestätigung.</p>", profile=profile)
                + post_form("/google/kalender/wechseln", self.site.auth.csrf_token(session.id),
                            select("calendar", msg("Google-Kalender"), "", choices), msg("Kalender übernehmen"),
                            primary=True, profile=profile, version=version))
        return self._page(200, tr("Anderen Kalender wählen"), body)

    def change_calendar(self, _request: Request, session: WebSession, form: dict[str, str]) -> Response:
        client = self.client()
        try:
            if client is None:
                raise HostedUnavailable("nicht eingerichtet")
            profile = self._profile(form)
            connection, _version = self.draft(profile)
            if not connection or form["calendar"] not in dict(self._choices(client, connection)):
                raise ValueError("Kalender nicht verfügbar")
            self.save("web:" + session.id, profile, {"google_calendar": form["calendar"]}, int(form["version"]),
                      form["key"])
        except (KeyError, ValueError, LookupError, HostedRefused):
            return self._failed(tr("Die Verbindung wurde inzwischen geändert oder ist abgelaufen. Bitte erneut "
                                   "starten; die bisherige Verbindung bleibt unverändert."))
        except (HostedUnavailable, httpx.HTTPError):
            return self._failed(tr("Der Inboxstride-Anmeldedienst ist gerade nicht erreichbar."), 503)
        return Response.redirect(self.site.setup_return(session, self.setup_path))

    def disconnect(self, _request: Request, session: WebSession, form: dict[str, str]) -> Response:
        """Stop the token issue for this profile's access; entries already written stay.

        The reference stays in the profile so it remains valid without own Google secrets; the
        warning of 7.9.2 then leads to "Google erneut verbinden". The central call is idempotent.
        """
        client = self.client()
        try:
            if client is None:
                raise HostedUnavailable("nicht eingerichtet")
            profile = self._profile(form)
            connection, version = self.draft(profile)
            if not connection or int(form["version"]) != version or not form["key"]:
                raise ValueError("Verbindung geändert")
            client.post("/intern/disconnect", {"connection": connection})
            forget_locally(connection)
        except (KeyError, ValueError, LookupError, HostedRefused):
            return self._failed(tr("Die Verbindung wurde inzwischen geändert oder ist abgelaufen. Bitte erneut "
                                   "starten; die bisherige Verbindung bleibt unverändert."))
        except HostedUnavailable:
            return self._failed(tr("Der Inboxstride-Anmeldedienst ist gerade nicht erreichbar."), 503)
        return Response.redirect(self.site.setup_return(session, self.setup_path))

    def start(self, _request: Request, session: WebSession, form: dict[str, str]) -> Response:
        client = self.client()
        try:
            if client is None:
                raise HostedUnavailable("nicht eingerichtet")
            profile = self._profile(form)
            connection, _version = self.draft(profile)
            answer = client.post("/intern/start", {
                "session": session_reference(session), "target": self.target(profile),
                "operation": "reauthorize" if connection else "connect", "key": form["key"]})
        except (ValueError, LookupError, KeyError):
            return self._failed(tr("Die Anfrage war unvollständig. Bitte erneut versuchen."), 400)
        except (HostedRefused, HostedUnavailable):
            return self._failed(tr("Der Inboxstride-Anmeldedienst ist gerade nicht erreichbar. Die bisherige "
                                   "Verbindung bleibt unverändert."), 503)
        url = answer.get("url")
        if not isinstance(url, str) or not url.startswith("https://accounts.google.com/"):
            return self._failed(tr("Der Anmeldedienst lieferte keine gültige Google-Adresse."), 502)
        return Response(303, headers={"Location": url, "Cache-Control": "no-store"})

    def returned(self, request: Request) -> Response:
        """Google's way back: a neutral page; only a same-origin POST continues."""
        query = parse_qs(request.query, max_num_fields=3)
        if "abbruch" in query:
            return self._page(200, tr("Google-Verbindung abgebrochen"),
                              tr("<h1>Google-Verbindung abgebrochen</h1><p>Die bisherige Verbindung bleibt "
                                 "unverändert. Du kannst es jederzeit erneut versuchen.</p>"), signed_in=False)
        receipt = (query.get("beleg") or [""])[0]
        if not re.fullmatch(r"[A-Za-z0-9_-]{16,200}", receipt):
            return self._failed(tr("Der Abschlussbeleg fehlt oder ist ungültig."), 400)
        session = self.site.auth.authenticate(request.cookies().get(SESSION_COOKIE))
        if session is None:
            # The strict session cookie is absent on a cross-site return; a same-origin click carries it.
            href = "/einrichtung/google/abschluss?" + "beleg=" + receipt
            return self._page(200, tr("Google-Verbindung fortsetzen"),
                              tr('<h1>Zurück bei Inboxstride</h1><p>Bitte im ursprünglichen Browser fortsetzen.</p>'
                                 '<p><a class="button" href="{href}">Fortsetzen</a></p>', href=e(href)),
                              signed_in=False)
        body = (tr("<h1>Google-Verbindung fortsetzen</h1><p>Die Anmeldung bei Google ist abgeschlossen. "
                   "Als Nächstes wählst du den Kalender.</p>")
                + post_form("/einrichtung/google/abschluss", self.site.auth.csrf_token(session.id), "",
                            msg("Kalender auswählen"), primary=True, beleg=receipt))
        return self._page(200, tr("Google-Verbindung fortsetzen"), body)

    def redeem(self, _request: Request, session: WebSession, form: dict[str, str]) -> Response:
        client = self.client()
        try:
            if client is None:
                raise HostedUnavailable("nicht eingerichtet")
            answer = client.post("/intern/redeem", {"session": session_reference(session),
                                                    "receipt": form["beleg"]})
            profile = self._profile_of(str(answer["target"]))
        except (KeyError, ValueError, HostedRefused):
            return self._failed(tr("Der Abschlussbeleg ist abgelaufen oder gehört zu einer anderen Sitzung. "
                                   "Bitte „Mit Google verbinden“ erneut starten."))
        except HostedUnavailable:
            return self._failed(tr("Der Inboxstride-Anmeldedienst ist gerade nicht erreichbar."), 503)
        pending = {"job": str(answer["job"]), "version": int(answer["version"]),
                   "connection": str(answer["connection"]), "profile": profile,
                   "expires": (self.clock() + LIFETIME).isoformat()}
        with self.store.locked():
            entries = self.store.load(PENDING, {})
            entries[session_reference(session)] = pending
            self.store.save(PENDING, entries)
        return Response.redirect("/google/kalender")

    def _profile_of(self, target: str) -> int:
        for profile in range(1, 100):
            try:
                if self.target(profile) == target:
                    return profile
            except LookupError:
                continue
        raise ValueError("Unbekanntes Ziel")

    def _pending(self, session: WebSession) -> dict[str, Any]:
        entry = self.store.load(PENDING, {}).get(session_reference(session))
        if entry is None or datetime.fromisoformat(entry["expires"]) <= self.clock():
            raise LookupError("Kein offener Google-Vorgang")
        return dict(entry)

    def _choices(self, client: HostedAuthClient, connection: str) -> list[tuple[str, str]]:
        token = client.post("/intern/token", {"connection": connection})["access_token"]
        return listed_targets(str(token), self.transport)

    def calendars(self, _request: Request, session: WebSession) -> Response:
        client = self.client()
        try:
            if client is None:
                raise HostedUnavailable("nicht eingerichtet")
            pending = self._pending(session)
            choices = self._choices(client, pending["connection"])
            _connection, version = self.draft(pending["profile"])
        except LookupError:
            return self._failed(tr("Kein offener Google-Vorgang. Bitte „Mit Google verbinden“ erneut starten."))
        except (HostedRefused, HostedUnavailable, httpx.HTTPError, ValueError):
            return self._failed(tr("Die Kalender konnten nicht gelesen werden. Die bisherige Verbindung bleibt "
                                   "unverändert."), 503)
        if not choices:
            return self._failed(tr("Für dieses Google-Konto gibt es keinen Kalender mit Schreibrecht. Bitte ein "
                                   "anderes Konto verbinden."))
        body = (tr("<h1>Kalender auswählen</h1><p>Zielprofil {profile}. Übernehmen ersetzt eine bisherige "
                   "Google-Verbindung dieses Profils; offene Vorschläge brauchen danach eine neue Bestätigung.</p>",
                   profile=pending["profile"])
                + post_form("/google/kalender", self.site.auth.csrf_token(session.id),
                            select("calendar", msg("Google-Kalender"), "", choices),
                            msg("Verbindung übernehmen"), primary=True, version=version))
        return self._page(200, tr("Kalender auswählen"), body)

    def adopt(self, _request: Request, session: WebSession, form: dict[str, str]) -> Response:
        """Save the profile first, then activate centrally.

        Bugfix 7.9.8: activation replaces the previous access of the target and deletes its secret, so it
        must be the last step. The candidate keeps its id when it becomes active; a repeated adoption after
        an outage saves the same values again and repeats the activation without a second effect.
        """
        client = self.client()
        try:
            if client is None:
                raise HostedUnavailable("nicht eingerichtet")
            pending = self._pending(session)
            if form["calendar"] not in dict(self._choices(client, pending["connection"])):
                raise ValueError("Kalender nicht verfügbar")
            previous, _version = self.draft(pending["profile"])
            self.save("web:" + session.id, pending["profile"],
                      {"calendar_provider": "google", "google_calendar": form["calendar"],
                       "google_connection": pending["connection"]}, int(form["version"]), form["key"])
            activated = client.post("/intern/activate", {"session": session_reference(session),
                                                         "job": pending["job"], "version": pending["version"]})
            if activated.get("connection") != pending["connection"]:
                raise HostedRefused("connection_changed")
        except LookupError:
            return self._failed(tr("Kein offener Google-Vorgang. Bitte „Mit Google verbinden“ erneut starten."))
        except (KeyError, ValueError, HostedRefused):
            return self._failed(tr("Die Verbindung wurde inzwischen geändert oder ist abgelaufen. Bitte erneut "
                                   "starten; die bisherige Verbindung bleibt unverändert."))
        except (HostedUnavailable, httpx.HTTPError):
            return self._failed(tr("Der Inboxstride-Anmeldedienst ist gerade nicht erreichbar."), 503)
        if previous and previous != activated["connection"]:
            try:
                # The replaced access of this profile issues no further tokens; Google's grant stays.
                client.post("/intern/disconnect", {"connection": previous})
            except (HostedRefused, HostedUnavailable):
                pass
        with self.store.locked():
            entries = self.store.load(PENDING, {})
            entries.pop(session_reference(session), None)
            self.store.save(PENDING, entries)
        return Response.redirect(self.site.setup_return(session, self.setup_path))


__all__ = ["LIFETIME", "PENDING", "HostedGoogleSite", "HostedProfiles", "session_reference"]
