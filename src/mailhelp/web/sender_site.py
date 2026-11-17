"""Sender rules in the web interface (1.4, 7.7.3).

A mail's sender can be ignored, its domain ignored or the sender made a VIP from the mail page, and
every rule is managed under ``/einstellungen/absender``. Every change is an idempotent
:class:`AdminCommand` executed by the main thread; changes from the rules page are bound to the
version of the rule file they were made on.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs

from ..config.configuration import AdminCommand, AdminKind, ConfigurationService, RuleChange, SenderChange, file_hash
from ..domain.relevance import PrefilterHits
from ..i18n import tr
from ..mailbox.sender_filter import FREEMAIL, HITS, new_rule, rule_hits, sender_addresses, sender_entry
from .auth import WebSession
from .http import Request, Response
from .pages import layout
from .sender_pages import (
    LIST_PATH,
    OLD_PATH,
    RULE_PATH,
    is_freemail,
    preview_text,
    sender_actions,
    senders_page,
)

if TYPE_CHECKING:
    from .site import MailhelpSite

# The preview counts over the most recent mails only.
PREVIEW_MAILS = 200


class SenderSite:
    def __init__(self, site: MailhelpSite) -> None:
        self.site = site
        site.app.route("GET", OLD_PATH, site.signed_in(lambda request, session: Response.redirect(LIST_PATH)))
        for method, path, handler in (
                ("POST", r"/mail/(?P<mail_id>[a-f0-9]{24})/absender-ignorieren", self.ignore),
                ("POST", r"/mail/(?P<mail_id>[a-f0-9]{24})/absender-zulassen", self.allow),
                ("POST", r"/mail/(?P<mail_id>[a-f0-9]{24})/domain-ignorieren", self.ignore_domain),
                ("POST", r"/mail/(?P<mail_id>[a-f0-9]{24})/absender-vip", self.make_vip),
                ("GET", LIST_PATH, self.list),
                ("POST", f"{LIST_PATH}/entfernen", self.remove),
                ("POST", RULE_PATH, self.add_rule),
                ("POST", rf"{RULE_PATH}/(?P<step>entfernen|enable|disable)", self.change_rule),
                ("POST", f"{LIST_PATH}/ausnahme-vip", self.promote),
                ("POST", f"{LIST_PATH}/kopfzeilen", self.header_mode),
                ("POST", rf"{LIST_PATH}/verteiler/(?P<step>hinzufuegen|entfernen)", self.list_exception)):
            site.app.route(method, path, site.signed_in(handler))

    @property
    def configuration(self) -> ConfigurationService | None:
        # Created after the web components, together with the main-thread services.
        return self.site.archive.configuration

    def actions(self, mail_id: str, sender: str, csrf: str) -> str:
        if self.configuration is None:
            return ""
        return sender_actions(mail_id, sender, self.configuration.blocked_senders(), csrf)

    def _stand(self) -> str:
        assert self.configuration is not None and self.configuration.senders is not None
        return file_hash(self.configuration.senders.directory / "irrelevant-senders.json")

    def _submit(self, request: Request, session: WebSession, form: dict[str, str], patch: dict[str, Any],
                stand: str | None = None) -> Response:
        try:
            command = AdminCommand(kind=AdminKind.SENDERS, actor=f"web:{session.id}",
                                   idempotency_key=form.get("key", ""), expected_hash=stand,
                                   patch=patch, acknowledged=True)
        except ValueError:
            return self.site._reply(request, 422, tr("Die Aktion ist unvollständig oder ungültig."))
        return self.site.archive.queue(request, command)

    def _unavailable(self, request: Request) -> Response | None:
        if self.configuration is None or self.configuration.senders is None:
            return self.site._reply(request, 503, tr("Absenderverwaltung nicht verfügbar."))
        return None

    def _mail_addresses(self, request: Request, mail_id: str) -> list[str] | Response:
        if (refused := self._unavailable(request)) is not None:
            return refused
        view = self.site.views.mail(mail_id)
        if view is None:
            return self.site._reply(request, 404, tr("Diese Mail ist nicht (mehr) vorhanden."))
        addresses = sorted(sender_addresses(view.sender))
        if not addresses:
            return self.site._reply(request, 422, tr("Die Mail hat keine gültige Absenderadresse."))
        return addresses

    def _mail_change(self, request: Request, session: WebSession, form: dict[str, str], mail_id: str,
                     action: str) -> Response:
        addresses = self._mail_addresses(request, mail_id)
        if isinstance(addresses, Response):
            return addresses
        return self._submit(request, session, form, SenderChange(action=action, addresses=addresses,
                                                                 mail_id=mail_id).model_dump(exclude_none=True))

    def ignore(self, request: Request, session: WebSession, form: dict[str, str], mail_id: str) -> Response:
        return self._mail_change(request, session, form, mail_id, "add")

    def allow(self, request: Request, session: WebSession, form: dict[str, str], mail_id: str) -> Response:
        return self._mail_change(request, session, form, mail_id, "remove")

    def _mail_rule(self, request: Request, session: WebSession, form: dict[str, str], mail_id: str,
                   kind: str, action: str) -> Response:
        addresses = self._mail_addresses(request, mail_id)
        if isinstance(addresses, Response):
            return addresses
        value = addresses[0] if kind == "address" else addresses[0].rsplit("@", 1)[1]
        if len(addresses) != 1 or (kind == "domain" and value in FREEMAIL):
            return self.site._reply(request, 422, tr("Für diesen Absender ist diese Regel nicht möglich."))
        return self._submit(request, session, form, RuleChange(
            rule_action="add", kind=kind, value=value, action=action, origin="mail",
            mail_id=mail_id).model_dump(exclude_none=True))

    def ignore_domain(self, request: Request, session: WebSession, form: dict[str, str], mail_id: str) -> Response:
        return self._mail_rule(request, session, form, mail_id, "domain", "ignore")

    def make_vip(self, request: Request, session: WebSession, form: dict[str, str], mail_id: str) -> Response:
        return self._mail_rule(request, session, form, mail_id, "address", "vip")

    def _preview(self, values: dict[str, str]) -> tuple[str, bool]:
        try:
            rule = new_rule(values.get("art", ""), values.get("wert", ""), values.get("aktion", "ignore"),  # type: ignore[arg-type]
                            self.site.clock(), mailbox=int(values["postfach"]) if values.get("postfach") else None)
        except (ValueError, KeyError):
            return (tr("Diese Regel ist ungültig. Muster dürfen nur * als Platzhalter enthalten, höchstens dreimal."),
                    False)
        recent = sorted(self.site.archive.queries.items(), key=lambda item: item["updated"], reverse=True)
        mails = [(item["sender"], item["subject"]) for item in recent[:PREVIEW_MAILS]]
        return preview_text(rule_hits(rule, mails), len(mails), is_freemail(rule)), True

    def list(self, request: Request, session: WebSession) -> Response:
        if (refused := self._unavailable(request)) is not None:
            return refused
        assert self.configuration is not None
        values = {key: value[0] for key, value in parse_qs(request.query, max_num_fields=10).items()
                  if key in {"art", "wert", "aktion", "postfach", "notiz", "vorschau"}}
        # A preview carries the whole form and is never the page of a result.
        message, kind = (None, "ok") if values.get("vorschau") else self.site.review._result_notice(request, session)
        preview, savable = self._preview(values) if values.get("vorschau") else (None, False)
        hits = self.site.views.store.peek_model(HITS, PrefilterHits, PrefilterHits())
        page = senders_page(self.configuration.blocked_senders(), hits, self.site.auth.csrf_token(session.id),
                            self._stand(), self.site.configured_timezone, message, kind, values, preview, savable)
        return Response.html(200, layout(tr("Absender-Regeln"), page, active="/einstellungen"))

    def remove(self, request: Request, session: WebSession, form: dict[str, str]) -> Response:
        """Remove an entry of the simple lists of schema 2; new entries are rules (7.7.3)."""
        if (refused := self._unavailable(request)) is not None:
            return refused
        try:
            kind, value = sender_entry(form.get("eintrag", ""))
        except ValueError:
            return self.site._reply(request, 422, tr("Bitte eine gültige E-Mail-Adresse oder Domain angeben, "
                                                     "z. B. newsletter@example.com oder example.com."))
        change = SenderChange(action="remove", **{"addresses" if kind == "address" else "domains": [value]})
        return self._submit(request, session, form, change.model_dump(exclude_none=True))

    def _rule_command(self, request: Request, session: WebSession, form: dict[str, str],
                      fields: dict[str, Any]) -> Response:
        if (refused := self._unavailable(request)) is not None:
            return refused
        try:
            patch = RuleChange(**fields).model_dump(exclude_none=True)
        except ValueError:
            return self.site._reply(request, 422, tr("Die Aktion ist unvollständig oder ungültig."))
        return self._submit(request, session, form, patch, form.get("stand") or None)

    def add_rule(self, request: Request, session: WebSession, form: dict[str, str]) -> Response:
        mailbox = form.get("postfach", "")
        return self._rule_command(request, session, form, {
            "rule_action": "add", "kind": form.get("art"), "value": form.get("wert", ""),
            "action": form.get("aktion", "ignore"), "note": form.get("notiz", ""),
            "origin": "hint" if form.get("herkunft") == "hint" else "manual",
            "mailbox_id": int(mailbox) if mailbox.isdigit() else None})

    def change_rule(self, request: Request, session: WebSession, form: dict[str, str], step: str) -> Response:
        return self._rule_command(request, session, form, {
            "rule_action": "remove" if step == "entfernen" else step, "rule_id": form.get("regel")})

    def promote(self, request: Request, session: WebSession, form: dict[str, str]) -> Response:
        mailbox = form.get("postfach", "")
        return self._rule_command(request, session, form, {
            "rule_action": "promote", "value": form.get("adresse", ""),
            "mailbox_id": int(mailbox) if mailbox.isdigit() else None})


    def header_mode(self, request: Request, session: WebSession, form: dict[str, str]) -> Response:
        return self._rule_command(request, session, form, {
            "rule_action": "header_mode", "header": form.get("filter"), "mode": form.get("modus")})

    def list_exception(self, request: Request, session: WebSession, form: dict[str, str], step: str) -> Response:
        return self._rule_command(request, session, form, {
            "rule_action": "list_exception_add" if step == "hinzufuegen" else "list_exception_remove",
            "value": form.get("verteiler", "")})


__all__ = ["LIST_PATH", "OLD_PATH", "SenderSite"]
