"""Version-bound mailbox OAuth, shared by first setup and running installations."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

from ..config import MailboxSettings
from ..external.hosted_oauth import HostedAuthClient, forget_locally
from ..i18n import msg, tr
from ..mailbox.provider_presets import providers
from ..persistence.storage import JsonStore
from .auth import WebSession
from .forms import field, post_form, select
from .hosted_google_site import session_reference
from .http import CONTENT_SECURITY_POLICY, Request, Response
from .pages import e, layout

PENDING = "mailbox-oauth"
BASE = "/postfach/oauth"
RETURN = "/einrichtung/postfach/abschluss"


@dataclass(frozen=True)
class MailboxOAuthContext:
    # The revision includes private-file hashes, never their contents.
    read: Callable[[int], tuple[MailboxSettings, int, str]]
    save: Callable[[str, MailboxSettings, str, int, str, str], None]
    probe: Callable[[MailboxSettings, str], list[tuple[str, str | None]]]


class MailboxOAuthSite:
    def __init__(self, site: Any, store: JsonStore, client: Callable[[], HostedAuthClient | None],
                 context: MailboxOAuthContext, back: str) -> None:
        self.site, self.store, self.client, self.context, self.back = site, store, client, context, back
        for method, path, handler in (("GET", BASE, self.offer), ("POST", BASE, self.start),
                                      ("POST", RETURN, self.redeem), ("GET", BASE + "/ordner", self.folders),
                                      ("POST", BASE + "/ordner", self.adopt),
                                      ("POST", BASE + "/trennen", self.disconnect)):
            site.app.route(method, path, site.signed_in(handler))
        site.app.route("GET", RETURN, self.returned)

    @staticmethod
    def page(body: str, status: int = 200) -> Response:
        answer = Response.html(status, layout(tr("Postfach verbinden"), body, signed_in=False))
        answer.headers.update({"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
        return answer

    def failed(self) -> Response:
        return self.page(tr("<h1>Postfach nicht verbunden</h1><p>Verbindung, Berechtigungen oder "
                            "Einrichtungsstand prüfen und den Vorgang erneut starten. Der Betreiber muss "
                            "den Postfachzugang beim Anbieter freischalten.</p>"), 409)

    def hub(self) -> HostedAuthClient:
        client = self.client()
        if client is None:
            raise ValueError("not_configured")
        return client

    def offer(self, request: Request, session: WebSession) -> Response:
        try:
            query = parse_qs(request.query, max_num_fields=5)
            purpose, number = query["provider"][0], int(query["mailbox"][0])
            if purpose not in {"gmail", "microsoft"}:
                raise ValueError("provider")
            mailbox, version, revision = self.context.read(number)
            if purpose not in self.hub().post("/intern/providers", {}).get("providers", []):
                raise ValueError("not_configured")
        except Exception:
            return self.failed()
        csrf = self.site.auth.csrf_token(session.id)
        controls = field("username", msg("E-Mail-Adresse des Postfachs"))
        body = tr("<h1>Postfach verbinden</h1><p>Diese Freigabe betrifft den Mailabruf. "
                  "Kalenderverbindungen bleiben getrennt. Erst nach der Ordnerprüfung übernimmst du den Zugang.</p>")
        body += post_form(BASE, csrf, controls, msg("Beim Anbieter anmelden"), mailbox=mailbox.id,
                          purpose=purpose, version=version, revision=revision)
        response = self.page(body)
        response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY.replace(
            "form-action 'self'", "form-action 'self' https://accounts.google.com https://login.microsoftonline.com")
        return response

    def start(self, _request: Request, session: WebSession, form: dict[str, str]) -> Response:
        try:
            number, version = int(form["mailbox"]), int(form["version"])
            _mailbox, current, revision = self.context.read(number)
            purpose, username = form["purpose"], form["username"].strip()
            if (purpose not in {"gmail", "microsoft"} or current != version or revision != form["revision"]
                    or not username or len(username) > 254 or any(ord(char) < 32 for char in username)):
                raise ValueError("stale_or_invalid")
            reference = session_reference(session)
            result = self.hub().post("/intern/start", {"session": reference, "target": f"mailbox:{number}",
                "purpose": purpose, "operation": "replace", "key": form["key"]})
            destination = urlsplit(result["url"])
            expected = "login.microsoftonline.com" if purpose == "microsoft" else "accounts.google.com"
            if destination.scheme != "https" or destination.netloc != expected:
                raise ValueError("redirect")
            with self.store.locked():
                pending = self.store.load(PENDING, {})
                pending[reference] = {"job": result["job"], "mailbox": number, "version": version,
                    "revision": revision, "purpose": purpose, "username": username,
                    "expires": (datetime.now(UTC) + timedelta(minutes=10)).isoformat()}
                self.store.save(PENDING, pending)
            return Response(303, headers={"Location": result["url"], "Cache-Control": "no-store"})
        except Exception:
            return self.failed()

    def returned(self, request: Request) -> Response:
        try:
            query = parse_qs(request.query, max_num_fields=5)
            receipt, = query["beleg"]
            if not receipt or len(receipt) > 200:
                raise ValueError("receipt")
        except (ValueError, KeyError):
            return self.failed()
        # A cross-site return may have no Strict cookie. The following same-origin POST must authenticate it.
        # CSRF is supplied by the normal authenticated GET below, never by the public callback.
        body = tr("<h1>Anmeldung zurückgekehrt</h1><p>Zum sicheren Abschluss bitte die Verbindung öffnen.</p>")
        body += f'<a href="{BASE}/ordner?beleg={e(receipt)}">{e(tr("Postfach prüfen"))}</a>'
        return self.page(body)

    def _pending(self, session: WebSession) -> dict[str, Any]:
        pending: dict[str, Any] = self.store.load(PENDING, {})[session_reference(session)]
        if datetime.fromisoformat(pending["expires"]) <= datetime.now(UTC):
            raise ValueError("expired")
        mailbox, version, revision = self.context.read(pending["mailbox"])
        if (version, revision) != (pending["version"], pending["revision"]):
            raise ValueError("changed")
        return pending

    def folders(self, request: Request, session: WebSession) -> Response:
        try:
            pending = self._pending(session)
            query = parse_qs(request.query, max_num_fields=5)
            if "beleg" in query:
                receipt, = query["beleg"]
                return self.page(post_form(RETURN, self.site.auth.csrf_token(session.id),
                    field("receipt", "", receipt, hidden=True), msg("Postfach prüfen")))
            mailbox = self._mailbox(pending)
            folders = self.context.probe(mailbox, pending["username"])
            choices = [(name, name) for name, _role in folders]
            inbox = next((name for name, role in folders if role == "inbox"), mailbox.primary_folder)
            drafts = next((name for name, role in folders if role == "drafts"), mailbox.drafts_folder)
            controls = select("inbox", msg("Posteingang"), inbox, choices)
            controls += select("drafts", msg("Entwurfsordner"), drafts, choices)
            return self.page(post_form(BASE + "/ordner", self.site.auth.csrf_token(session.id), controls,
                                       msg("Postfachverbindung übernehmen")))
        except Exception:
            return self.failed()

    def redeem(self, _request: Request, session: WebSession, form: dict[str, str]) -> Response:
        try:
            pending = self._pending(session)
            result = self.hub().post("/intern/redeem", {
                "session": session_reference(session), "receipt": form["receipt"]})
            if (result["job"], result["target"], result["purpose"]) != (
                    pending["job"], f'mailbox:{pending["mailbox"]}', pending["purpose"]):
                raise ValueError("wrong_binding")
            with self.store.locked():
                records = self.store.load(PENDING, {})
                records[session_reference(session)] = {**pending, "connection": result["connection"],
                                                        "job_version": result["version"]}
                self.store.save(PENDING, records)
            return Response.redirect(BASE + "/ordner")
        except Exception:
            return self.failed()

    def _mailbox(self, pending: dict[str, Any]) -> MailboxSettings:
        mailbox, _version, _revision = self.context.read(pending["mailbox"])
        host = providers()["gmail" if pending["purpose"] == "gmail" else "outlook"].host
        return MailboxSettings.model_validate({**mailbox.model_dump(), "host": host, "port": 993,
            "connection_mode": "ssl", "auth_method": pending["purpose"], "oauth_connection": pending["connection"]})

    def adopt(self, _request: Request, session: WebSession, form: dict[str, str]) -> Response:
        try:
            pending = self._pending(session)
            mailbox = self._mailbox(pending)
            names = {name for name, _role in self.context.probe(mailbox, pending["username"])}
            if form["inbox"] not in names or form["drafts"] not in names:
                raise ValueError("unknown_folder")
            mailbox = MailboxSettings.model_validate({**mailbox.model_dump(), "folders": [form["inbox"]],
                "primary_folder": form["inbox"], "drafts_folder": form["drafts"]})
            existing, _version, _revision = self.context.read(pending["mailbox"])
            if pending.get("adopting") and pending["adopting"] != mailbox.model_dump(mode="json"):
                raise ValueError("adoption_changed")
            with self.store.locked():
                records = self.store.load(PENDING, {})
                records[session_reference(session)] = {**pending, "adopting": mailbox.model_dump(mode="json")}
                self.store.save(PENDING, records)
            if existing.model_dump() != mailbox.model_dump():
                self.context.save("web:" + session.id, mailbox, pending["username"], pending["version"],
                                  form["key"], pending["revision"])
                _saved, version, revision = self.context.read(pending["mailbox"])
                with self.store.locked():
                    records = self.store.load(PENDING, {})
                    records[session_reference(session)].update(version=version, revision=revision)
                    self.store.save(PENDING, records)
            if not self.site.auth.active(session.id):
                raise PermissionError("session_expired")
            state = self.hub().post("/intern/connection", {"connection": pending["connection"]})
            if state["target"] != f'mailbox:{pending["mailbox"]}':
                raise ValueError("wrong_target")
            if state["status"] != "active":
                active = self.hub().post("/intern/activate", {"session": session_reference(session),
                    "job": pending["job"], "version": pending["job_version"]})
                if (active["connection"], active["target"]) != (pending["connection"], state["target"]):
                    raise ValueError("wrong_activation")
            with self.store.locked():
                records = self.store.load(PENDING, {})
                records.pop(session_reference(session), None)
                self.store.save(PENDING, records)
            return Response.redirect(self.back)
        except Exception:
            return self.failed()

    def disconnect(self, _request: Request, session: WebSession, form: dict[str, str]) -> Response:
        # The configuration reference remains, so disconnect cannot silently fall back to a password.
        try:
            mailbox, version, revision = self.context.read(int(form["mailbox"]))
            if version != int(form["version"]) or revision != form["revision"] or not mailbox.oauth_connection:
                raise ValueError("changed")
            self.hub().post("/intern/disconnect", {"connection": mailbox.oauth_connection})
            forget_locally(mailbox.oauth_connection)
            return Response.redirect(self.back)
        except Exception:
            return self.failed()
