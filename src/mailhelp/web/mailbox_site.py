"""Mailbox policies and profile management through the existing authenticated draft."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs

from ..config import Settings, Topic, read_yaml
from ..domain.proposal import Proposal
from ..mailbox.mailbox_settings import effective_settings
from . import mailbox_draft, mailbox_profiles
from .auth import WebSession
from .forms import post_form
from .http import Request, Response
from .pages import e, layout, notice
from .setup_site import CHOICES
from .setup_site import LABELS as TARGET_LABELS

if TYPE_CHECKING:
    from .site import MailhelpSite

TABS = {
    "targets": "Ziele",
    "filters": "Filter",
    "topics": "Themen",
    "replies": "Antworten",
    "notifications": "Benachrichtigungen",
}
FIELDS = {
    "targets": ("target_profile", "event_defaults.video_duration_minutes", "event_defaults.in_person_duration_minutes",
                "mail_client"),
    "replies": ("personal_info", "smart_reply", "auto_draft", "activity_report_folder", "retention.full_mail_days"),
    "notifications": (
        "daily_briefing",
        "notifications.quiet_hours.enabled",
        "notifications.quiet_hours.start",
        "notifications.quiet_hours.end",
        "notifications.quiet_hours.allow_system_errors",
        "notifications.categories.decisions",
        "notifications.categories.action_results",
        "notifications.categories.daily_briefing",
        "notifications.categories.system_errors",
    ),
}
LABELS = {
    "target_profile": "Zielprofil",
    "personal_info": "Signatur, Rolle und Anrede",
    "smart_reply": "Antwortentwürfe anbieten",
    "auto_draft": "Antwortentwürfe automatisch im Postfach ablegen",
    "activity_report_folder": "Standardordner für Tätigkeitsberichte",
    "retention.full_mail_days": "Mailinhalt aufbewahren (Tage, disabled oder unlimited)",
    "event_defaults.video_duration_minutes": "Standarddauer Videokonferenz (Minuten)",
    "event_defaults.in_person_duration_minutes": "Standarddauer Präsenztermin (Minuten)",
    "daily_briefing": "Dieses Postfach im Tagesüberblick zeigen",
    "mail_client": "Link „Original-Mail öffnen“ öffnet",
    "notifications.quiet_hours.enabled": "Ruhezeit aktiv",
    "notifications.quiet_hours.start": "Ruhe ab",
    "notifications.quiet_hours.end": "Ruhe bis",
    "notifications.quiet_hours.allow_system_errors": "Betriebsprobleme von der Ruhezeit ausnehmen",
    "notifications.categories.decisions": "Kanäle für Entscheidungen",
    "notifications.categories.action_results": "Kanäle für Aktionsergebnisse",
    "notifications.categories.daily_briefing": "Kanäle für Tagesüberblicke",
    "notifications.categories.system_errors": "Kanäle für Betriebsprobleme",
}
LABELS.update(
    {
        "id": "Stabile Nummer",
        "label": "Anzeigename",
        "host": "IMAP-Server",
        "port": "IMAP-Port",
        "folders": "Quellordner (kommagetrennt)",
        "entry": "Absenderadresse oder Domain",
    }
)


MAIL_CLIENTS = {
    "auto": "Automatisch (Gmail-Server: Gmail im Browser, sonst Apple Mail)",
    "apple_mail": "Apple Mail (message://)",
    "gmail_web": "Gmail im Browser",
    "outlook_web": "Outlook im Browser (Suche nach der Message-ID)",
    "none": "Keinen Link einfügen",
}


def lookup(value: Any, name: str) -> Any:
    for part in name.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def control(name: str, value: object, prefix: str = "mailbox") -> str:

    identity = prefix + "-" + name.replace(".", "-")
    title = LABELS.get(name, TARGET_LABELS.get("targets." + name, name))
    if name == "mail_client":
        options, shown = list(MAIL_CLIENTS.items()), str(value or "auto")
    elif "targets." + name in CHOICES:
        options, shown = [(item, item) for item in CHOICES["targets." + name]], str(value)
    elif name.startswith("notifications.categories."):
        options = [
            ("[]", "Keine"),
            ('["telegram"]', "Telegram"),
            ('["web_push"]', "Web-Push"),
            ('["telegram","web_push"]', "Telegram und Web-Push"),
        ]
        shown = json.dumps(value or [], separators=(",", ":"))
    elif isinstance(value, bool):
        options, shown = [("true", "Ja"), ("false", "Nein")], str(value).lower()
    else:
        options, shown = [], str(value if value is not None else "")
    if options:
        field = (
            f'<select id="{identity}" name="value">'
            + "".join(
                f'<option value="{e(key)}"{" selected" if key == shown else ""}>{e(text)}</option>'
                for key, text in options
            )
            + "</select>"
        )
    else:
        field = f'<input id="{identity}" name="value" value="{e(shown)}" maxlength="2000">'
    return f'<label for="{identity}">{e(title)}</label>{field}'


class MailboxSite:
    def __init__(self, site: MailhelpSite):
        self.site = site
        for method, path, handler in (
            ("GET", "/einstellungen/postfaecher", self.index),
            ("GET", r"/einstellungen/postfaecher/(?P<number>[1-9][0-9]?)", self.mailbox),
            ("POST", "/einstellungen/postfaecher/speichern", self.save),
            ("POST", "/einstellungen/postfaecher/thema", self.topic),
            ("POST", "/einstellungen/postfaecher/filter", self.filter),
            ("POST", "/einstellungen/postfaecher/verwerfen", self.discard),
            ("GET", "/einstellungen/zielprofile", self.profiles),
            ("POST", "/einstellungen/zielprofile/speichern", self.save_profile),
            ("POST", "/einstellungen/zielprofile/umstellen", self.retarget),
        ):
            site.app.route(method, path, site.signed_in(handler))

    @property
    def runtime(self) -> Any:
        return self.site.setup_page.runtime

    def page(self, title: str, body: str) -> Response:
        return Response.html(200, layout(title, '<div class="setup-page"><h1>' + e(title) + "</h1>" + body + "</div>"))

    def unavailable(self) -> Response:
        return Response.text(503, "Einrichtungsdienst nicht verfügbar.")

    def preview(self, session: WebSession) -> str:
        return mailbox_draft.preview(self, session)

    def affected(self) -> dict[int, int]:

        return mailbox_draft.affected(self)

    def index(self, request: Request, session: WebSession, problem: str = "",
              values: dict[str, str] | None = None) -> Response:
        if self.runtime is None:
            return self.unavailable()
        cfg = self.runtime.setup.draft_settings()
        saved = {box.id: box for box in Settings.model_validate(
            read_yaml(self.runtime.app.configuration.directory / "config.yaml")).imap.configured_mailboxes()}
        running = {box.id for box in self.runtime.app.configuration.active.imap.configured_mailboxes()}
        body = notice("Postfach nicht aktiviert. " + problem, "error") if problem else ""
        if parse_qs(request.query).get("aktiviert"):
            body += notice("Verbindung geprüft und Postfach gespeichert. Der Abruf startet ohne Neustart im "
                           "nächsten sicheren Mailzyklus.")
        body += (
            '<p class="settings-shortcuts">'
            '<a class="button small" href="#postfach-hinzufuegen">Postfach hinzufügen</a> '
            '<a class="button small" href="/einstellungen/iserv">IServ-Konten</a> '
            '<a class="button small" href="/einstellungen/zielprofile">Zielprofile</a> '
            '<a class="button small" href="/einstellungen/absender">Globale Absenderfilter</a> '
            '<a class="button small" href="/einstellungen/zugangsdaten">Zugangsdaten</a></p>'
        )
        for box in cfg.imap.configured_mailboxes():
            if box.id not in saved:
                state = "Entwurf – noch nicht aktiviert"
            elif box.id not in running:
                state = "gespeichert – Aktivierung ausstehend"
            else:
                state = "aktiv" if box.enabled else "deaktiviert"
                state += " · Änderungen im Entwurf" if box != saved[box.id] else ""
            body += (
                f'<section class="card"><h2><a href="/einstellungen/postfaecher/{box.id}">{e(box.label)}</a> · '
                f'{box.id}</h2><p class="meta">{e(box.host)}:{box.port} · {e(", ".join(box.folders))} · {state}</p>'
                f'<p><a class="button small" href="/einstellungen/postfaecher/{box.id}">Einstellungen</a></p></section>'
            )
        body += self.site.mailbox_add.section(session, cfg, values)
        fields = "".join(
            control(name, value)
            for name, value in (("id", ""), ("label", ""), ("host", ""), ("port", 993), ("folders", "INBOX"))
        )
        # Each control has a separate name in this multi-field form.
        for name in ("id", "label", "host", "port", "folders"):
            fields = fields.replace(f'id="mailbox-{name}" name="value"', f'id="mailbox-{name}" name="{name}"')
        body += ('<details class="card"><summary>Stattdessen nur als Entwurf hinzufügen</summary>'
                 '<p class="meta">Ohne Verbindungsprüfung; Zugangsdaten danach unter Zugangsdaten eintragen, '
                 'den Entwurf übernehmen und Mailhelp neu starten.</p>')
        body += post_form(
            "/einstellungen/postfaecher/speichern",
            self.site.auth.csrf_token(session.id),
            fields,
            "Postfach als Entwurf hinzufügen",
            action="add",
            version=self.runtime.setup.state().version,
        )
        return self.page("Postfächer", body + "</details>" + self.preview(session))

    def mailbox(self, request: Request, session: WebSession, number: str) -> Response:
        if self.runtime is None:
            return self.unavailable()
        cfg, mailbox_number = self.runtime.setup.draft_settings(), int(number)
        box = cfg.imap.mailbox(mailbox_number)
        if box is None:
            return Response.text(404, "Postfach nicht vorhanden.")
        tab = parse_qs(request.query).get("tab", ["targets"])[0]
        if tab not in TABS:
            return Response.text(422, "Unbekannter Einstellungsbereich.")
        body = (
            '<nav aria-label="Postfacheinstellungen">'
            + "".join(f'<a class="button" href="?tab={key}">{title}</a>' for key, title in TABS.items())
            + "</nav>"
        )
        csrf, version = self.site.auth.csrf_token(session.id), self.runtime.setup.state().version
        if tab in FIELDS:
            body += self._field_sections(cfg, box, mailbox_number, tab, csrf, version)
        elif tab == "topics":
            body += self._topic_sections(mailbox_number, csrf, version)
        else:
            body += self._filter_section(mailbox_number, csrf, version)
        body += post_form(
            "/einstellungen/postfaecher/speichern",
            csrf,
            "",
            "Postfach entfernen",
            number=mailbox_number,
            action="remove",
            version=version,
        )
        return self.page(box.label, body + self.preview(session))


    def _field_sections(self, cfg: Any, box: Any, mailbox_number: int, tab: str, csrf: str, version: int) -> str:
        """One card per setting of the tab: own value or inherited, with save and reset."""
        body = ""
        effective = effective_settings(cfg, mailbox_number).model_dump(mode="json")
        for field in FIELDS[tab]:
            own = lookup(box.model_dump(), field)
            value = own if own is not None else lookup(effective, field)
            body += '<section class="card"><h2>' + e(LABELS[field]) + "</h2><p>"
            body += (
                "Erbt global" if own is None or field == "target_profile" and own == 1 else "Eigener Wert"
            ) + "</p>"
            body += post_form(
                "/einstellungen/postfaecher/speichern",
                csrf,
                control(field, value),
                "Im Entwurf speichern",
                number=mailbox_number,
                field=field,
                version=version,
            )
            body += (
                post_form(
                    "/einstellungen/postfaecher/speichern",
                    csrf,
                    "",
                    "Zurücksetzen auf global",
                    number=mailbox_number,
                    field=field,
                    version=version,
                    action="reset",
                )
                + "</section>"
            )
        return body

    def _topic_sections(self, mailbox_number: int, csrf: str, version: int) -> str:
        """Every relevant and excluded topic with its scope for this mailbox."""
        assert self.runtime is not None
        body = ""
        for category, filename in (("relevant", "topics.yaml"), ("irrelevant", "irrelevant_topics.yaml")):
            for data in read_yaml(self.runtime.setup.configuration.directory / filename)["topics"]:
                topic = Topic.model_validate(data)
                body += '<section class="card"><h2>' + e(topic.name) + "</h2>"
                body += (
                    "<p>"
                    + ("Gilt global" if topic.mailboxes is None else "Postfächer: " + e(topic.mailboxes))
                    + "</p>"
                )
                for scope, title in (
                    ("own", "Nur dieses Postfach"),
                    ("all", "Für alle Postfächer"),
                    ("exclude", "Hier ausschließen"),
                ):
                    body += post_form(
                        "/einstellungen/postfaecher/thema",
                        csrf,
                        "",
                        title,
                        number=mailbox_number,
                        topic=topic.id,
                        category=category,
                        scope=scope,
                        version=version,
                    )
                body += "</section>"
        return body

    def _filter_section(self, mailbox_number: int, csrf: str, version: int) -> str:
        """Global and own sender blocks of this mailbox and the form to change them."""
        assert self.runtime is not None
        body = ""
        blocked = self.runtime.setup.configuration.blocked_senders()
        rules = blocked.mailboxes.get(str(mailbox_number))
        body += "<p>Globale Sperren: " + e([*blocked.addresses, *blocked.domains]) + "</p>"
        body += "<p>Eigene Sperren und Ausnahmen: " + e(rules.model_dump() if rules else {}) + "</p>"
        body += post_form(
            "/einstellungen/postfaecher/filter",
            csrf,
            control("entry", "")
            + '<label for="filter-action">Änderung</label><select id="filter-action" name="action">'
            '<option value="add">Hier ignorieren</option><option value="remove">Eigene Sperre entfernen</option>'
            '<option value="allow">Globale Sperre hier ausnehmen</option>'
            '<option value="unallow">Ausnahme entfernen</option>'
            "</select>",
            "Filteränderung vormerken",
            number=mailbox_number,
            version=version,
        )
        return body

    def save(self, request: Request, session: WebSession, form: dict[str, str]) -> Response:
        return mailbox_draft.save(self, request, session, form)

    def topic(self, request: Request, session: WebSession, form: dict[str, str]) -> Response:
        return mailbox_draft.topic(self, request, session, form)

    def filter(self, request: Request, session: WebSession, form: dict[str, str]) -> Response:
        return mailbox_draft.filter(self, request, session, form)

    def discard(self, request: Request, session: WebSession, form: dict[str, str]) -> Response:
        return mailbox_draft.discard(self, request, session, form)

    def profiles(self, request: Request, session: WebSession) -> Response:
        return mailbox_profiles.profiles(self, request, session)

    def save_profile(self, request: Request, session: WebSession, form: dict[str, str]) -> Response:
        return mailbox_profiles.save_profile(self, request, session, form)

    def target_forms(self, proposal: Proposal, session: WebSession) -> str:
        return mailbox_profiles.target_forms(self, proposal, session)

    def retarget(self, request: Request, session: WebSession, form: dict[str, str]) -> Response:
        return mailbox_profiles.retarget(self, request, session, form)
