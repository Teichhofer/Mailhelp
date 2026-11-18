"""Add an IMAP mailbox from one authenticated form, like IServ accounts (3.5).

Server, folders, start boundary and credentials are checked together; only a successful
connection saves config.yaml and .env, and the mail loop starts the mailbox without restart.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from ..config import MAX_MAILBOXES, MailboxSettings
from ..config.configuration import ConfigurationConflict, file_hash
from ..config.env_file import EnvFileConflict
from ..config.env_file import file_hash as env_hash
from ..i18n import msg, tr
from ..mailbox.connection_activation import ActivationProblem
from ..mailbox.mailbox_activation import MailboxActivation
from .auth import WebSession
from .forms import post_form
from .http import Request, Response
from .iserv_site import reason, start_boundary
from .pages import e

_SECTION_TEXT_1 = msg(
    '<section class="card" id="postfach-hinzufuegen"><h2>Postfach '
    "hinzufügen</h2><p>Mailhelp meldet sich an, prüft die Ordner und startet den Abruf "
    "ohne Neustart. Erst nach erfolgreicher Prüfung werden Postfach {p0} und die "
    "Zugangsdaten <code>{p1}</code>/<code>{p2}</code> gespeichert. Ein Datum gilt ab "
    "00:00 Uhr in {p3}.</p>"
)

_SECTION_TEXT_2 = msg(
    '<label for="mailbox-add-connection_mode">Verbindungsart</label><select '
    'id="mailbox-add-connection_mode" '
    'name="connection_mode">{p0}</select></fieldset><fieldset><legend>Anmeldung</legend>'
)

if TYPE_CHECKING:
    from ..config import Settings
    from .site import MailhelpSite

ROUTE = "/einstellungen/postfaecher"
ACTIVATE = ROUTE + "/aktivieren"
MODES = (
    ("ssl", msg("SSL/TLS (meist Port 993)")),
    ("starttls", msg("STARTTLS (meist Port 143)")),
    ("plain", msg("Unverschlüsselt (nur im eigenen Netz)")),
)
FIELD_NAMES = {
    "host": msg("IMAP-Server"),
    "port": msg("Port"),
    "folders": msg("Ordner"),
    "primary_folder": msg("Ordner"),
    "drafts_folder": msg("Entwurfsordner"),
    "historical_start": msg("Startgrenze"),
    "label": msg("Anzeigename"),
    "connection_mode": msg("Verbindungsart"),
}


def _input(name: str, label: str, value: object, kind: str = "text", **attrs: str) -> str:
    extra = "".join(f' {key}="{e(item)}"' for key, item in attrs.items())
    return (f'<label for="mailbox-add-{name}">{e(label)}</label>'
            f'<input id="mailbox-add-{name}" type="{kind}" name="{name}" value="{e(value)}"{extra}>')


class MailboxAddSite:
    def __init__(self, site: MailhelpSite) -> None:
        self.site = site
        site.app.route("POST", ACTIVATE, site.signed_in(self.activate))

    @property
    def runtime(self) -> Any:
        return self.site.setup_page.runtime

    def section(self, session: WebSession, cfg: Settings, values: dict[str, str] | None = None) -> str:
        """The card with the activation form; *values* refill it after a rejected attempt."""
        boxes = cfg.imap.configured_mailboxes()
        if len(boxes) >= MAX_MAILBOXES:
            return tr('<p class="meta">Es sind bereits {p0} Postfächer eingerichtet.</p>', p0=MAX_MAILBOXES)
        used = {box.id for box in boxes}
        number = next(number for number in range(1, 100) if number not in used)
        today = self.site.clock().astimezone(ZoneInfo(cfg.timezone)).strftime("%d.%m.%Y")
        given = {"label": "", "host": "", "port": "993", "connection_mode": "ssl", "folders": "INBOX",
                 "drafts_folder": "Drafts", "historical_start": today, "username": "", **(values or {})}
        env = self.runtime.environment()
        user_name, password_name = f"IMAP_{number}_USERNAME", f"IMAP_{number}_PASSWORD"
        stored = bool(env.get(user_name) and env.get(password_name))
        fields = _activation_fields(given, stored, number)
        path = self.runtime.app.configuration.directory
        form = post_form(
            ACTIVATE,
            self.site.auth.csrf_token(session.id),
            fields,
            msg("Verbindung prüfen und Postfach aktivieren"),
            id=number,
            version=self.runtime.setup.state().version,
            revision=file_hash(path / "config.yaml"),
            env_revision=env_hash(path / ".env"),
        )
        return (
            tr(
                (_SECTION_TEXT_1),
                p0=number,
                p1=user_name,
                p2=password_name,
                p3=e(cfg.timezone),
            )
            + form
            + "</section>"
        )

    def activate(self, request: Request, session: WebSession, form: dict[str, str]) -> Response:
        if self.runtime is None:
            return self.site.mailbox_page.unavailable()
        values = {name: form.get(name, "") for name in ("label", "host", "port", "connection_mode", "folders",
                                                         "drafts_folder", "historical_start", "username")}
        try:
            number = int(form["id"])
            folders = [folder.strip() for folder in form["folders"].split(",") if folder.strip()]
            mailbox = MailboxSettings.model_validate(
                {
                    "id": number,
                    "label": form["label"].strip() or tr("Postfach {p0}", p0=number),
                    "host": form["host"].strip(),
                    "port": int(form["port"]),
                    "connection_mode": form["connection_mode"],
                    "folders": folders,
                    "drafts_folder": form["drafts_folder"].strip(),
                    "historical_start": start_boundary(
                        form["historical_start"], self.runtime.setup.draft_settings().timezone
                    ),
                }
            )
            MailboxActivation(self.runtime).activate(
                f"web:{session.id}", int(form["version"]), form["key"], form["revision"], form["env_revision"],
                mailbox, form.get("username", "").strip(), form.get("password", ""))
        except (ConfigurationConflict, EnvFileConflict):
            return Response.text(
                409, msg("Konfiguration, Zugangsdaten oder Entwurf geändert; Seite neu laden und prüfen.")
            )
        except PermissionError:
            return Response.text(403, msg("Sitzung abgelaufen; erneut anmelden."))
        except ActivationProblem as exc:
            return self.rejected(request, session, str(exc), values)
        except ValidationError as exc:
            return self.rejected(request, session, reason(exc, FIELD_NAMES), values)
        except (KeyError, ValueError):
            return self.rejected(
                request,
                session,
                msg("Angaben und Zugangsdaten prüfen. Bei gesetzten Prozessvariablen haben deren Werte Vorrang."),
                values,
            )
        except Exception:
            # External errors may contain submitted secrets; never render or log them.
            return self.rejected(
                request,
                session,
                msg(
                    
                        "Speichern fehlgeschlagen. Postfach nicht vollständig aktiviert; "
                        "gespeicherten Stand prüfen und erneut versuchen."
                    
                ),
                values,
            )
        return Response.redirect(ROUTE + msg("?aktiviert=1"))

    def rejected(self, request: Request, session: WebSession, message: str, values: dict[str, str]) -> Response:
        page = self.site.mailbox_page.index(request, session, message, values)
        page.status = 422
        return page


__all__ = ["ACTIVATE", "MailboxAddSite"]


def _activation_fields(given: dict[str, str], stored: bool, number: int) -> str:
    keep = {} if stored else {"required": "required"}
    modes = "".join(f'<option value="{key}"{" selected" if key == given["connection_mode"] else ""}>'
                    f'{e(text)}</option>' for key, text in MODES)
    fields = (
        "<fieldset><legend>Server</legend>"
        + _input(
            "label", msg("Anzeigename"), given["label"], maxlength="40", placeholder=tr("Postfach {p0}", p0=number)
        )
        + _input(
            "host",
            "IMAP-Server",
            given["host"],
            required="required",
            maxlength="253",
            placeholder="imap.example.org",
            autocomplete="off",
        )
        + _input("port", "Port", given["port"], "number", required="required", min="1", max="65535")
        + tr(
            (_SECTION_TEXT_2),
            p0=modes,
        )
        + _input(
            "username",
            msg("Benutzername (meist die vollständige E-Mail-Adresse)")
            + (msg(" – leer: hinterlegten verwenden") if stored else ""),
            given["username"],
            autocomplete="username",
            maxlength="4096",
            **keep,
        )
        + _input(
            "password",
            msg("Passwort oder App-Passwort") + (msg(" – leer: hinterlegtes verwenden") if stored else ""),
            "",
            "password",
            autocomplete="new-password",
            maxlength="4096",
            **keep,
        )
        + tr("</fieldset><fieldset><legend>Abruf</legend>")
        + _input(
            "folders",
            msg("Ordner (kommagetrennt, der erste ist der Posteingang)"),
            given["folders"],
            required="required",
            maxlength="2000",
        )
        + _input(
            "drafts_folder",
            msg("Ordner für Antwortentwürfe"),
            given["drafts_folder"],
            required="required",
            maxlength="500",
        )
        + _input(
            "historical_start",
            msg("Ältere Mails nicht verarbeiten vor (leer: alle vorhandenen Mails)"),
            given["historical_start"],
            maxlength="40",
            placeholder=msg("TT.MM.JJJJ"),
        )
        + "</fieldset>"
    )
    return fields
