"""The pending mailbox draft: preview, affected mails and the forms that change it (7.0, R5)."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from ..config import Topic, read_yaml
from ..config.configuration import MAILBOX_POLICY_FIELDS, set_dotted
from ..domain.mail import MailState
from ..llm.decisions import relevance_fingerprint
from ..mailbox.mailbox_settings import mailbox_fingerprint
from ..mailbox.sender_filter import sender_entry
from ..state_names import mail_state_names
from . import mailbox_site as mailbox_site_module
from .auth import WebSession
from .forms import post_form
from .http import Request, Response
from .pages import e

if TYPE_CHECKING:
    from .mailbox_site import MailboxSite


def preview(site: MailboxSite, session: WebSession) -> str:
    state = site.runtime.setup.state()
    text = (
        "<p>Speichern ändert den Entwurf. Übernehmen erteilt keine externe Anlagefreigabe. "
        "Verbindungs- und Zieländerungen wirken nach dem nächsten Dienststart.</p>"
    )
    if state.patch:
        text += '<section class="card"><h2>Entwurf prüfen</h2><dl>'
        if state.kind == "topics":
            text += "<dt>Thema</dt><dd>" + e(state.patch["name"]) + "</dd><dt>Geltungsbereich</dt><dd>"
            text += (
                e(state.patch.get("mailboxes") if state.patch.get("mailboxes") is not None else "Alle Postfächer")
                + "</dd>"
            )
        elif state.kind == "senders":
            text += f"<dt>Postfach</dt><dd>{state.patch['mailbox_id']}</dd>"
            text += "<dt>Filteränderung</dt><dd>" + e(state.patch) + "</dd>"
        else:
            cfg = site.runtime.setup.draft_settings()
            if "imap.mailboxes" in state.patch:
                for box in cfg.imap.configured_mailboxes():
                    text += f"<dt>Postfach {box.id} ({e(box.label)})</dt><dd>"
                    text += (
                        e(
                            {
                                mailbox_site_module.LABELS.get(name, name): value
                                for name, value in box.model_dump(exclude_none=True).items()
                                if name in MAILBOX_POLICY_FIELDS
                            }
                        )
                        + "</dd>"
                    )
            if "iserv.accounts" in state.patch:
                for account in cfg.iserv.accounts:
                    text += f"<dt>IServ-Konto {account.id} ({e(account.label)})</dt><dd>"
                    text += e(f"{account.server} · Postfach {account.mailbox} · "
                              + ("aktiv" if account.enabled else "deaktiviert")) + "</dd>"
                if not cfg.iserv.accounts:
                    text += "<dt>IServ-Konten</dt><dd>keine</dd>"
            if "target_profiles" in state.patch:
                for profile in cfg.target_profiles:
                    text += f"<dt>Zielprofil {profile.id} ({e(profile.label)})</dt><dd>"
                    text += (
                        e(
                            profile.calendar_provider
                            + " → "
                            + profile.calendar_target
                            + " · "
                            + profile.task_provider
                            + " → "
                            + profile.task_target
                        )
                        + "</dd>"
                    )
        for number, count in site.affected().items():
            text += (f"<dt>Laufende Mails in Postfach {number}</dt><dd>{count} werden mit "
                     "configuration_changed zurückgehalten.</dd>")
        text += '</dl><p><a href="/diagnose">Zugriffe prüfen</a></p>'
        csrf = site.site.auth.csrf_token(session.id)
        text += post_form(
            "/einrichtung/uebernehmen",
            csrf,
            '<label><input type="checkbox" name="confirm" value="yes" required> '
            'Änderungen ausdrücklich übernehmen</label>',
            "Entwurf übernehmen",
            version=state.version,
            expected_hash=state.base_hash,
        )
        text += post_form(
            "/einstellungen/postfaecher/verwerfen", csrf, "", "Entwurf verwerfen", version=state.version
        )
        text += "</section>"
    return text


def affected(site: MailboxSite) -> dict[int, int]:

    app = site.runtime.app
    cfg = site.runtime.setup.draft_settings()
    topics = app.orchestrator.topics
    state = site.runtime.setup.state()
    if state.kind == "topics" and state.category == "relevant":
        edited = Topic.model_validate(state.patch)
        topics = [edited if topic.id == edited.id else topic for topic in topics]
    result: dict[int, int] = {}
    for name in mail_state_names(app.store):
        mail = app.store.peek_model(name, MailState)
        if mail is None or mail.steps.completion == "completed":
            continue
        number = app.orchestrator.mailbox_number(mail.imap.account_id)
        if cfg.imap.mailbox(number) is None:
            changed = True
        else:
            value = mailbox_fingerprint(cfg, app.analyzer.prompts, topics, number)
            if app.orchestrator.mailbox_jev is not None:
                value = relevance_fingerprint(value, app.orchestrator.mailbox_jev)
            changed = value != mail.config_fingerprint
            if changed and value == app.orchestrator.fingerprint_for(mail.imap.account_id):
                changed = not app.orchestrator.accepts_configuration(mail.config_fingerprint, mail.imap.account_id)
        if changed:
            result[number] = result.get(number, 0) + 1
    return result


def save(site: MailboxSite, request: Request, session: WebSession, form: dict[str, str]) -> Response:
    if site.runtime is None:
        return site.unavailable()
    try:
        cfg = site.runtime.setup.draft_settings()
        boxes = [box.model_dump(mode="json") for box in cfg.imap.configured_mailboxes()]
        if form.get("action") == "add":
            boxes.append(
                {
                    "id": int(form["id"]),
                    "label": form["label"],
                    "host": form["host"],
                    "port": int(form["port"]),
                    "folders": [value.strip() for value in form["folders"].split(",")],
                }
            )
        elif form.get("action") == "remove":
            boxes = [box for box in boxes if box["id"] != int(form["number"])]
        else:
            number, field = int(form["number"]), form["field"]
            if field not in MAILBOX_POLICY_FIELDS:
                raise ValueError("Unbekannte Einstellung")
            box = next(box for box in boxes if box["id"] == number)
            if form.get("action") == "reset":
                value: Any = {"target_profile": 1, "daily_briefing": True, "mail_client": "auto"}.get(field)
                field = "retention" if field == "retention.full_mail_days" else field
            elif (
                field.endswith(("minutes", "days"))
                or field == "target_profile"
                or field.startswith("notifications.categories.")
                or field in {"smart_reply", "auto_draft", "daily_briefing"}
                or field.endswith((".enabled", ".allow_system_errors"))
            ):
                value = (
                    json.loads(form["value"]) if form["value"] not in {"disabled", "unlimited"} else form["value"]
                )
            else:
                value = form["value"]

            set_dotted(box, field, value)
        site.runtime.setup.save(
            f"web:{session.id}",
            int(form["version"]),
            form["key"],
            6,
            {"imap.mailboxes": boxes},
            request_signature={name: value for name, value in form.items() if name not in {"csrf", "key"}},
        )
    except (ValueError, KeyError, StopIteration, PermissionError):
        return Response.text(409, "Entwurf nicht gespeichert; Angaben, Version und Sitzung prüfen.")
    return Response.redirect("/einstellungen/postfaecher")


def topic(site: MailboxSite, request: Request, session: WebSession, form: dict[str, str]) -> Response:
    if site.runtime is None:
        return site.unavailable()
    try:
        number, category = int(form["number"]), form["category"]
        if category not in {"relevant", "irrelevant"}:
            raise ValueError("Unbekannte Themenliste")
        filename = "topics.yaml" if category == "relevant" else "irrelevant_topics.yaml"
        cfg = site.runtime.setup.draft_settings()
        topic = next(
            Topic.model_validate(value)
            for value in read_yaml(site.runtime.setup.configuration.directory / filename)["topics"]
            if value["id"] == form["topic"]
        )
        if form["scope"] == "own":
            scope = [number]
        elif form["scope"] == "all":
            scope = None
        elif form["scope"] == "exclude":
            scope = sorted(
                set(
                    topic.mailboxes
                    if topic.mailboxes is not None
                    else [box.id for box in cfg.imap.configured_mailboxes()]
                )
                - {number}
            )
        else:
            raise ValueError("Ungültige Zuordnung")
        patch = topic.model_copy(update={"mailboxes": scope}).model_dump(mode="json")
        site.runtime.setup.save_local(
            f"web:{session.id}", int(form["version"]), form["key"], "topics", patch, category
        )
    except (ValueError, KeyError, StopIteration, PermissionError):
        return Response.text(409, "Themenentwurf nicht gespeichert.")
    return Response.redirect("/einstellungen/postfaecher")


def filter(site: MailboxSite, request: Request, session: WebSession, form: dict[str, str]) -> Response:
    if site.runtime is None:
        return site.unavailable()
    try:
        kind, entry = sender_entry(form["value"])
        patch = {
            "action": form["action"],
            "mailbox_id": int(form["number"]),
            "addresses" if kind == "address" else "domains": [entry],
        }
        site.runtime.setup.save_local(f"web:{session.id}", int(form["version"]), form["key"], "senders", patch)
    except (ValueError, KeyError, PermissionError):
        return Response.text(409, "Filterentwurf nicht gespeichert.")
    return Response.redirect("/einstellungen/postfaecher")


def discard(site: MailboxSite, request: Request, session: WebSession, form: dict[str, str]) -> Response:
    if site.runtime is None:
        return site.unavailable()
    try:
        site.runtime.setup.discard(f"web:{session.id}", int(form["version"]), form["key"])
    except (ValueError, KeyError, PermissionError):
        return Response.text(409, "Entwurf nicht verworfen; Version und Sitzung prüfen.")
    return Response.redirect("/einstellungen/postfaecher")
