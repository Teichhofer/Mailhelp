"""IServ connection checks and activation from one authenticated form; drafts remain optional."""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from ..config import IServAccountSettings, Settings, read_yaml
from ..config.configuration import ConfigurationConflict, file_hash
from ..config.env_file import EnvFileConflict
from ..config.env_file import file_hash as env_hash
from ..i18n import msg, tr
from ..mailbox.iserv import IServSignInError
from ..mailbox.iserv_activation import IServActivation
from .auth import WebSession
from .forms import post_form
from .http import Request, Response
from .pages import e, notice

_INDEX_TEXT_1 = msg(
    "<p>Schuladresse, Postfach und Zugangsdaten gemeinsam prüfen und aktivieren. Der "
    "Abruf startet ohne manuellen Neustart. Leere Zugangsfelder verwenden vorhandene "
    "Werte. Elternbriefe gelten immer als relevant.</p><p>Ein Datum wie 01.09.2026 oder "
    "2026-09-01 gilt ab 00:00 Uhr in {p0}. Ein ISO-8601-Zeitpunkt benötigt einen "
    "UTC-Offset, z. B. 2026-09-01T00:00:00+02:00.</p>"
)

_INDEX_TEXT_2 = msg(
    "Verbindung geprüft und Konto gespeichert. Der Abruf startet ohne Neustart im "
    "nächsten sicheren Mailzyklus; offene Rückfragen gegebenenfalls zuerst beantworten."
)

if TYPE_CHECKING:
    from .site import MailhelpSite

ROUTE = "/einstellungen/iserv"
_GERMAN_DATE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})(?:\s+(\d{1,2}):(\d{2}))?")


def start_boundary(text: str, zone: str) -> str | None:
    """ISO 8601 as entered, or TT.MM.JJJJ [HH:MM] in the configured time zone; empty means none."""
    text = text.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return datetime.fromisoformat(text).replace(tzinfo=ZoneInfo(zone)).isoformat()
    match = _GERMAN_DATE.fullmatch(text)
    if match is None:
        return text or None
    day, month, year, hour, minute = match.groups()
    try:
        moment = datetime(int(year), int(month), int(day), int(hour or 0), int(minute or 0),
                          tzinfo=ZoneInfo(zone))
    except ValueError as exc:
        raise ValueError("Die Startgrenze ist kein gültiges Datum") from exc
    return moment.isoformat()


FIELD_NAMES = {
    "server": msg("IServ-Adresse"),
    "historical_start": msg("Startgrenze"),
    "mailbox": msg("Postfach"),
    "label": msg("Anzeigename"),
}


def reason(exc: Exception, names: dict[str, str] = FIELD_NAMES) -> str:
    """A readable cause for the page; never a stack trace or form contents."""
    if isinstance(exc, ValidationError):
        error = exc.errors(include_input=False)[0]
        field = names.get(str(error["loc"][-1]) if error["loc"] else "", msg("Eingabe"))
        return f"{field}: {str(error['msg']).removeprefix('Value error, ')}"
    return str(exc) or msg("Angaben, Version und Sitzung prüfen.")


def _input(name: str, label: str, value: object, suffix: str, kind: str = "text", **attrs: str) -> str:
    extra = "".join(f' {key}="{e(item)}"' for key, item in attrs.items())
    identity = f"iserv-{name}-{suffix}"
    return (f'<label for="{identity}">{e(label)}</label><input id="{identity}" type="{kind}" name="{name}" '
            f'value="{e(value)}"{extra}>')


def _account_fields(account: dict[str, Any], mailboxes: list[tuple[int, str]], suffix: str) -> str:
    options = "".join(f'<option value="{number}"{" selected" if number == account.get("mailbox", 1) else ""}>'
                      f'{number} · {e(label)}</option>' for number, label in mailboxes)
    start = account.get("historical_start") or ""
    return (
        _input("label", msg("Anzeigename"), account.get("label", msg("Elternbriefe")), suffix, maxlength="40")
        + _input(
            "server",
            msg("IServ-Adresse der Schule (https://…)"),
            account.get("server", ""),
            suffix,
            required="required",
            maxlength="2000",
            inputmode="url",
        )
        + tr(
            (
                '<label for="iserv-mailbox-{p0}">Einstellungen und Zielprofil von '
                'Postfach</label><select id="iserv-mailbox-{p1}" '
                'name="mailbox">{p2}</select>'
            ),
            p0=suffix,
            p1=suffix,
            p2=options,
        )
        + _input(
            "historical_start",
            msg("Ältere Briefe nicht verarbeiten vor (leer: Postfachgrenze)"),
            start,
            suffix,
            maxlength="40",
            placeholder=msg("TT.MM.JJJJ"),
        )
    )


class IServSite:
    def __init__(self, site: MailhelpSite) -> None:
        self.site = site
        for method, path, handler in (("GET", ROUTE, self.index), ("POST", ROUTE + "/speichern", self.save),
                                      ("POST", ROUTE + "/aktivieren", self.activate)):
            site.app.route(method, path, site.signed_in(handler))

    @property
    def runtime(self) -> Any:
        return self.site.setup_page.runtime

    def index(self, request: Request, session: WebSession, problem: str = "") -> Response:
        mailboxes_page = self.site.mailbox_page
        if self.runtime is None:
            return mailboxes_page.unavailable()
        cfg = self.runtime.setup.draft_settings()
        saved = Settings.model_validate(read_yaml(self.runtime.app.configuration.directory / "config.yaml"))
        csrf, version = self.site.auth.csrf_token(session.id), self.runtime.setup.state().version
        mailboxes = [(box.id, box.label) for box in cfg.imap.enabled_mailboxes()]
        body = notice(msg("Entwurf nicht gespeichert. ") + problem, "error") if problem else ""
        if parse_qs(request.query).get("aktiviert"):
            body += notice(tr(_INDEX_TEXT_2))
        body += tr(
            (_INDEX_TEXT_1),
            p0=e(cfg.timezone),
        )
        body += _account_cards(self, cfg, saved, session, mailboxes, csrf, version)
        used = {account.id for account in cfg.iserv.accounts}
        free = next((number for number in range(1, 11) if number not in used), None)
        if free is None:
            body += tr('<p class="meta">Es sind bereits zehn IServ-Konten eingerichtet.</p>')
        else:
            body += tr(
                ('<section class="card"><h2>IServ-Konto hinzufügen</h2><p class="meta">Nummer {p0}</p>'), p0=free
            )
            body += self.activation_form(session, {"id": free}, mailboxes, 'neu')
            body += tr("<details><summary>Stattdessen als Entwurf speichern</summary>")
            body += tr(
                ('<p class="meta">Zugangsdaten ISERV_{p0}_USERNAME und ISERV_{p1}_PASSWORD.</p>'),
                p0=free,
                p1=free,
            )
            body += post_form(
                ROUTE + "/speichern",
                csrf,
                _account_fields({}, mailboxes, 'neu'),
                msg("IServ-Konto als Entwurf hinzufügen"),
                action="add",
                id=free,
                version=version,
            )
            body += "</details></section>"
        body += '<section class="card"><h2>Alternativer Entwurfsablauf</h2>'
        body += mailboxes_page.preview(session) + '</section>'
        return mailboxes_page.page(msg("IServ-Konten"), body)

    def activation_form(self, session: WebSession, data: dict[str, Any], mailboxes: list[tuple[int, str]],
                        suffix: str) -> str:
        path = self.runtime.app.configuration.directory
        fields = _account_fields(data, mailboxes, 'aktivieren-' + suffix)
        fields += _input(
            "username",
            msg("Benutzername (leer: vorhandenen verwenden)"),
            "",
            'aktivieren-' + suffix,
            autocomplete="username",
            maxlength="4096",
        )
        fields += _input(
            "password",
            msg("Passwort (leer: vorhandenes verwenden)"),
            "",
            'aktivieren-' + suffix,
            "password",
            autocomplete="new-password",
            maxlength="4096",
        )
        return tr("<h3>Direkt aktivieren</h3>") + post_form(
            ROUTE + "/aktivieren",
            self.site.auth.csrf_token(session.id),
            fields,
            msg("Verbindung prüfen und Konto aktivieren"),
            id=data["id"],
            version=self.runtime.setup.state().version,
            revision=file_hash(path / "config.yaml"),
            env_revision=env_hash(path / ".env"),
        )

    def activate(self, request: Request, session: WebSession, form: dict[str, str]) -> Response:
        if self.runtime is None:
            return self.site.mailbox_page.unavailable()
        try:
            account = IServAccountSettings.model_validate(
                {
                    "id": int(form["id"]),
                    "label": form["label"].strip() or msg("Elternbriefe"),
                    "server": form["server"].strip(),
                    "mailbox": int(form["mailbox"]),
                    "historical_start": start_boundary(
                        form["historical_start"], self.runtime.setup.draft_settings().timezone
                    ),
                }
            )
            IServActivation(self.runtime).activate(f"web:{session.id}", int(form["version"]), form["key"],
                form["revision"], form["env_revision"], account, form.get("username", ""), form.get("password", ""))
        except (ConfigurationConflict, EnvFileConflict):
            return Response.text(
                409, msg("Konfiguration, Zugangsdaten oder Entwurf geändert; Seite neu laden und prüfen.")
            )
        except PermissionError:
            return Response.text(403, msg("Sitzung abgelaufen; erneut anmelden."))
        except IServSignInError:
            return self.activation_error(
                request, session, msg("Anmeldung fehlgeschlagen. Benutzername und Passwort prüfen.")
            )
        except (KeyError, ValueError):
            return self.activation_error(
                request,
                session,
                msg(
                    
                        "Angaben und Zugangsdaten prüfen. Bei gesetzten Prozessvariablen haben "
                        "deren Werte Vorrang. Das Postfach muss bereits aktiv sein."
                    
                ),
            )
        except Exception:
            # External errors may contain submitted secrets; never render or log them.
            return self.activation_error(
                request,
                session,
                msg(
                    
                        "Verbindung oder Speichern fehlgeschlagen. Konto nicht vollständig "
                        "aktiviert; gespeicherten Stand prüfen und erneut versuchen."
                    
                ),
            )
        return Response.redirect(ROUTE + msg("?aktiviert=1"))

    def activation_error(self, request: Request, session: WebSession, message: str) -> Response:
        page = self.index(request, session)
        warning = notice(msg("Konto nicht aktiviert. ") + message, "error")
        page.body = page.body.replace(b'<h1>', (warning + '<h1>').encode(), 1)
        page.status = 422
        return page

    def save(self, request: Request, session: WebSession, form: dict[str, str]) -> Response:
        if self.runtime is None:
            return self.site.mailbox_page.unavailable()
        try:
            cfg = self.runtime.setup.draft_settings()
            accounts = [account.model_dump(mode="json") for account in cfg.iserv.accounts]
            number, action = int(form["id"]), form["action"]
            if action in {"add", "update"}:
                entry = {
                    "id": number,
                    "label": form["label"].strip() or msg("Elternbriefe"),
                    "server": form["server"].strip(),
                    "mailbox": int(form["mailbox"]),
                    "historical_start": start_boundary(form["historical_start"], cfg.timezone),
                }
                if action == "add":
                    if any(account["id"] == number for account in accounts):
                        raise ValueError("IServ-Konto existiert bereits")
                    accounts.append({**entry, "enabled": True})
                else:
                    current = next(account for account in accounts if account["id"] == number)
                    current.update(entry)
            elif action == "toggle":
                current = next(account for account in accounts if account["id"] == number)
                current["enabled"] = not current["enabled"]
            elif action == "remove":
                accounts = [account for account in accounts if account["id"] != number]
            else:
                raise ValueError("Unbekannte Aktion")
            # Stored as validated, e.g. the server as normalised HTTPS origin.
            accounts = [IServAccountSettings.model_validate(account).model_dump(mode="json") for account in accounts]
            self.runtime.setup.save(
                f"web:{session.id}", int(form["version"]), form["key"], 6, {"iserv.accounts": accounts},
                request_signature={name: value for name, value in form.items() if name not in {"csrf", "key"}})
        except ConfigurationConflict:
            return Response.text(409, msg("Konfiguration oder Entwurf geändert; neu einlesen und Änderungen prüfen."))
        except ValueError as exc:
            # Shown on the page itself, so the cause (e.g. an invalid address) is visible at once.
            page = self.index(request, session, reason(exc))
            page.status = 422
            return page
        except (KeyError, StopIteration, PermissionError):
            return Response.text(409, msg("Entwurf nicht gespeichert; Angaben, Version und Sitzung prüfen."))
        return Response.redirect(ROUTE)


__all__ = ["IServSite", "ROUTE"]




def _account_cards(self: IServSite, cfg: Settings, saved: Settings, session: WebSession,
                   mailboxes: list[tuple[int, str]], csrf: str, version: int) -> str:
    body = ""
    for account in cfg.iserv.accounts:
        data = account.model_dump(mode="json")
        state = msg("aktiv") if account.enabled else msg("deaktiviert")
        if account not in saved.iserv.accounts:
            state = msg("Entwurf – noch nicht aktiviert")
        elif account not in self.runtime.app.configuration.active.iserv.accounts:
            state = msg("gespeichert – Aktivierung ausstehend")
        body += tr(
            ('<section class="card"><h2>{p0} · {p1}</h2><p class="meta">{p2} · Postfach {p3} · {p4}</p>'),
            p0=e(account.label),
            p1=account.id,
            p2=e(account.server),
            p3=account.mailbox,
            p4=state,
        )
        body += self.activation_form(session, data, mailboxes, str(account.id))
        body += tr("<details><summary>Weitere Aktionen und Entwurf</summary>")
        body += f'<p class="meta">Separate Zugangsdatenpflege: {"/".join(account.secret_names)}</p>'
        body += post_form(
            ROUTE + "/speichern",
            csrf,
            _account_fields(data, mailboxes, str(account.id)),
            msg("Änderung im Entwurf speichern"),
            action="update",
            id=account.id,
            version=version,
        )
        body += post_form(
            ROUTE + "/speichern",
            csrf,
            "",
            msg("Deaktivieren") if account.enabled else msg("Aktivieren"),
            action="toggle",
            id=account.id,
            version=version,
        )
        body += (
            post_form(
                ROUTE + "/speichern",
                csrf,
                "",
                msg("IServ-Konto entfernen"),
                action="remove",
                id=account.id,
                version=version,
            )
            + "</details></section>"
        )
    return body
