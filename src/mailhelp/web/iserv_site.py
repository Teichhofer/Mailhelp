"""IServ accounts through the authenticated configuration draft (3.3.10).

Like mailboxes, every change is a draft of the whole ``iserv.accounts`` block: it is reviewed,
diagnosed and only written to config.yaml after an explicit, versioned approval.  Credentials are
never part of this page; they are entered under Einstellungen → Zugangsdaten.
"""
from __future__ import annotations

from typing import Any

from ..config import IServAccountSettings
from .forms import post_form
from .http import Response
from .pages import e

ROUTE = "/einstellungen/iserv"


def _input(name: str, label: str, value: object, suffix: str, kind: str = "text", **attrs: str) -> str:
    extra = "".join(f' {key}="{e(item)}"' for key, item in attrs.items())
    identity = f"iserv-{name}-{suffix}"
    return (f'<label for="{identity}">{e(label)}</label><input id="{identity}" type="{kind}" name="{name}" '
            f'value="{e(value)}"{extra}>')


def _account_fields(account: dict[str, Any], mailboxes: list[tuple[int, str]], suffix: str) -> str:
    options = "".join(f'<option value="{number}"{" selected" if number == account.get("mailbox", 1) else ""}>'
                      f'{number} · {e(label)}</option>' for number, label in mailboxes)
    start = account.get("historical_start") or ""
    return (_input("label", "Anzeigename", account.get("label", "Elternbriefe"), suffix, maxlength="40")
            + _input("server", "IServ-Adresse der Schule (https://…)", account.get("server", ""), suffix, "url",
                     required="required", maxlength="253")
            + f'<label for="iserv-mailbox-{suffix}">Einstellungen und Zielprofil von Postfach</label>'
            f'<select id="iserv-mailbox-{suffix}" name="mailbox">{options}</select>'
            + _input("historical_start", "Ältere Briefe nicht verarbeiten vor (ISO 8601, leer: Grenze des Postfachs)",
                     start, suffix, maxlength="40"))


class IServSite:
    def __init__(self, site):
        self.site = site
        for method, path, handler in (("GET", ROUTE, self.index), ("POST", ROUTE + "/speichern", self.save)):
            site.app.route(method, path, site.signed_in(handler))

    @property
    def runtime(self):
        return self.site.setup_page.runtime

    def index(self, request, session):
        mailboxes_page = self.site.mailbox_page
        if self.runtime is None:
            return mailboxes_page.unavailable()
        cfg = self.runtime.setup.draft_settings()
        csrf, version = self.site.auth.csrf_token(session.id), self.runtime.setup.state().version
        mailboxes = [(box.id, box.label) for box in cfg.imap.enabled_mailboxes()]
        body = ('<p>Elternbriefe aus IServ werden wie Mails verarbeitet und gelten immer als relevant. '
                'Zugangsdaten unter <a href="/einstellungen/zugangsdaten">Zugangsdaten</a> eintragen, danach unter '
                '<a href="/diagnose">Diagnose</a> „iserv“ prüfen und den Entwurf übernehmen. Änderungen wirken '
                'nach dem nächsten Dienststart.</p>')
        for account in cfg.iserv.accounts:
            data = account.model_dump(mode="json")
            state = "aktiv" if account.enabled else "deaktiviert"
            body += (f'<section class="card"><h2>{e(account.label)} · {account.id}</h2>'
                     f'<p class="meta">{e(account.server)} · Postfach {account.mailbox} · {state} · Zugangsdaten '
                     f'{"/".join(account.secret_names)}</p>')
            body += post_form(ROUTE + "/speichern", csrf, _account_fields(data, mailboxes, str(account.id)),
                              "Änderung im Entwurf speichern", action="update", id=account.id, version=version)
            body += post_form(ROUTE + "/speichern", csrf, "", "Deaktivieren" if account.enabled else "Aktivieren",
                              action="toggle", id=account.id, version=version)
            body += post_form(ROUTE + "/speichern", csrf, "", "IServ-Konto entfernen", action="remove",
                              id=account.id, version=version) + "</section>"
        used = {account.id for account in cfg.iserv.accounts}
        free = next((number for number in range(1, 11) if number not in used), None)
        if free is None:
            body += '<p class="meta">Es sind bereits zehn IServ-Konten eingerichtet.</p>'
        else:
            body += (f'<section class="card"><h2>IServ-Konto hinzufügen</h2><p class="meta">Nummer {free}; '
                     f'Zugangsdaten ISERV_{free}_USERNAME und ISERV_{free}_PASSWORD.</p>')
            body += post_form(ROUTE + "/speichern", csrf, _account_fields({}, mailboxes, "neu"),
                              "IServ-Konto als Entwurf hinzufügen", action="add", id=free, version=version)
            body += "</section>"
        return mailboxes_page.page("IServ-Konten", body + mailboxes_page.preview(session))

    def save(self, request, session, form):
        if self.runtime is None:
            return self.site.mailbox_page.unavailable()
        try:
            cfg = self.runtime.setup.draft_settings()
            accounts = [account.model_dump(mode="json") for account in cfg.iserv.accounts]
            number, action = int(form["id"]), form["action"]
            if action in {"add", "update"}:
                entry = {"id": number, "label": form["label"].strip() or "Elternbriefe",
                         "server": form["server"].strip(), "mailbox": int(form["mailbox"]),
                         "historical_start": form["historical_start"].strip() or None}
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
        except (ValueError, KeyError, StopIteration, PermissionError):
            return Response.text(409, "Entwurf nicht gespeichert; Angaben, Version und Sitzung prüfen.")
        return Response.redirect(ROUTE)


__all__ = ["IServSite", "ROUTE"]
