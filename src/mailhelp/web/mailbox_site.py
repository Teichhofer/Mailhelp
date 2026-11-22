"""Mailbox policies and profile management through the existing authenticated draft."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs

from ..config import Settings, Topic, read_yaml
from ..config.env_file import file_hash as connection_hash
from ..domain.proposal import Proposal
from ..i18n import msg, tr
from ..mailbox.mailbox_settings import effective_settings
from . import mailbox_draft, mailbox_profiles
from .auth import WebSession
from .forms import post_form
from .http import Request, Response
from .pages import e, layout, notice
from .provider_fields import mailbox_oauth_controls
from .setup_site import CHOICES
from .setup_site import LABELS as TARGET_LABELS

_INDEX_TEXT_1 = msg(
    '<p class="settings-shortcuts"><a class="button small" '
    'href="#postfach-hinzufuegen">Postfach hinzufügen</a> <a class="button small" '
    'href="/einstellungen/iserv">IServ-Konten</a> <a class="button small" '
    'href="/einstellungen/zielprofile">Zielprofile</a> <a class="button small" '
    'href="/einstellungen/absender">Globale Absenderfilter</a> <a class="button small" '
    'href="/einstellungen/zugangsdaten">Zugangsdaten</a></p>'
)

_INDEX_TEXT_2 = msg(
    '<details class="card"><summary>Stattdessen nur als Entwurf hinzufügen</summary><p '
    'class="meta">Ohne Verbindungsprüfung; Zugangsdaten danach unter Zugangsdaten '
    "eintragen, den Entwurf übernehmen und Mailhelp neu starten.</p>"
)

_INDEX_TEXT_3 = msg(
    '<section class="card"><h2><a href="/einstellungen/postfaecher/{p0}">{p1}</a> · '
    '{p2}</h2><p class="meta">{p3}:{p4} · {p5} · {p6}</p><p><a class="button small" '
    'href="/einstellungen/postfaecher/{p7}">Einstellungen</a></p></section>'
)

if TYPE_CHECKING:
    from .site import MailhelpSite

TABS = {
    "targets": msg("Ziele"),
    "filters": msg("Filter"),
    "topics": msg("Themen"),
    "replies": msg("Antworten"),
    "notifications": msg("Benachrichtigungen"),
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
    "target_profile": msg("Zielprofil"),
    "personal_info": msg("Signatur, Rolle und Anrede"),
    "smart_reply": msg("Antwortentwürfe anbieten"),
    "auto_draft": msg("Antwortentwürfe automatisch im Postfach ablegen"),
    "activity_report_folder": msg("Standardordner für Tätigkeitsberichte"),
    "retention.full_mail_days": msg("Mailinhalt aufbewahren (Tage, disabled oder unlimited)"),
    "event_defaults.video_duration_minutes": msg("Standarddauer Videokonferenz (Minuten)"),
    "event_defaults.in_person_duration_minutes": msg("Standarddauer Präsenztermin (Minuten)"),
    "daily_briefing": msg("Dieses Postfach im Tagesüberblick zeigen"),
    "mail_client": msg("Link „Original-Mail öffnen“ öffnet"),
    "notifications.quiet_hours.enabled": msg("Ruhezeit aktiv"),
    "notifications.quiet_hours.start": msg("Ruhe ab"),
    "notifications.quiet_hours.end": msg("Ruhe bis"),
    "notifications.quiet_hours.allow_system_errors": msg("Betriebsprobleme von der Ruhezeit ausnehmen"),
    "notifications.categories.decisions": msg("Kanäle für Entscheidungen"),
    "notifications.categories.action_results": msg("Kanäle für Aktionsergebnisse"),
    "notifications.categories.daily_briefing": msg("Kanäle für Tagesüberblicke"),
    "notifications.categories.system_errors": msg("Kanäle für Betriebsprobleme"),
}
LABELS.update(
    {
        "id": msg("Stabile Nummer"),
        "label": msg("Anzeigename"),
        "host": msg("IMAP-Server"),
        "port": msg("IMAP-Port"),
        "folders": msg("Quellordner (kommagetrennt)"),
        "entry": msg("Absenderadresse oder Domain"),
    }
)


MAIL_CLIENTS = {
    "auto": msg("Automatisch (Gmail-Server: Gmail im Browser, sonst Apple Mail)"),
    "apple_mail": msg("Apple Mail (message://)"),
    "gmail_web": msg("Gmail im Browser"),
    "outlook_web": msg("Outlook im Browser (Suche nach der Message-ID)"),
    "none": msg("Keinen Link einfügen"),
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
            ("[]", msg("Keine")),
            ('["telegram"]', "Telegram"),
            ('["web_push"]', "Web-Push"),
            ('["telegram","web_push"]', msg("Telegram und Web-Push")),
        ]
        shown = json.dumps(value or [], separators=(",", ":"))
    elif isinstance(value, bool):
        options, shown = [("true", msg("Ja")), ("false", msg("Nein"))], str(value).lower()
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
    elif name == "calendar_reminder_minutes":
        field = f'<input id="{identity}" type="number" min="0" max="1440" step="1" name="value" value="{e(shown)}">'
    else:
        field = f'<input id="{identity}" name="value" value="{e(shown)}" maxlength="2000">'
    return f'<label for="{identity}">{e(title)}</label>{field}'


class MailboxSite:
    def __init__(self, site: MailhelpSite) -> None:
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
        return Response.text(503, msg("Einrichtungsdienst nicht verfügbar."))

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
        body = notice(msg("Postfach nicht aktiviert. ") + problem, "error") if problem else ""
        if parse_qs(request.query).get("aktiviert"):
            body += notice(
                tr(
                    "Verbindung geprüft und Postfach gespeichert. Der Abruf startet "
                    "ohne Neustart im nächsten sicheren Mailzyklus."
                )
            )
        body += tr(_INDEX_TEXT_1)
        for box in cfg.imap.configured_mailboxes():
            if box.id not in saved:
                state = msg("Entwurf – noch nicht aktiviert")
            elif box.id not in running:
                state = msg("gespeichert – Aktivierung ausstehend")
            else:
                state = msg("aktiv") if box.enabled else msg("deaktiviert")
                state += msg(" · Änderungen im Entwurf") if box != saved[box.id] else ""
            body += tr(
                (_INDEX_TEXT_3),
                p0=box.id,
                p1=e(box.label),
                p2=box.id,
                p3=e(box.host),
                p4=box.port,
                p5=e(", ".join(box.folders)),
                p6=state,
                p7=box.id,
            )
        body += self.site.mailbox_add.section(session, cfg, values)
        fields = "".join(
            control(name, value)
            for name, value in (("id", ""), ("label", ""), ("host", ""), ("port", 993), ("folders", "INBOX"))
        )
        # Each control has a separate name in this multi-field form.
        for name in ("id", "label", "host", "port", "folders"):
            fields = fields.replace(f'id="mailbox-{name}" name="value"', f'id="mailbox-{name}" name="{name}"')
        body += tr(_INDEX_TEXT_2)
        body += post_form(
            "/einstellungen/postfaecher/speichern",
            self.site.auth.csrf_token(session.id),
            fields,
            msg("Postfach als Entwurf hinzufügen"),
            action="add",
            version=self.runtime.setup.state().version,
        )
        return self.page(msg("Postfächer"), body + "</details>" + self.preview(session))

    def mailbox(self, request: Request, session: WebSession, number: str) -> Response:
        if self.runtime is None:
            return self.unavailable()
        cfg, mailbox_number = self.runtime.setup.draft_settings(), int(number)
        box = cfg.imap.mailbox(mailbox_number)
        if box is None:
            return Response.text(404, msg("Postfach nicht vorhanden."))
        tab = parse_qs(request.query).get("tab", ["targets"])[0]
        if tab not in TABS:
            return Response.text(422, msg("Unbekannter Einstellungsbereich."))
        body = (
            '<nav aria-label="Postfacheinstellungen">'
            + "".join(f'<a class="button" href="?tab={key}">{title}</a>' for key, title in TABS.items())
            + "</nav>"
        )
        csrf, version = self.site.auth.csrf_token(session.id), self.runtime.setup.state().version
        if box.auth_method == "password":
            body += f'<p><a href="/einstellungen/postfaecher/{mailbox_number}/anbieter">'
            body += e(tr("Mailanbieter ändern")) + "</a></p>"
        if cfg.hosted_auth.enabled:
            directory = self.runtime.app.configuration.directory
            revision = connection_hash(directory / "config.yaml") + ":" + connection_hash(directory / ".env")
            body += mailbox_oauth_controls(box, csrf, version, revision)
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
            msg("Postfach entfernen"),
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
                "Erbt global" if own is None or field == "target_profile" and own == 1 else msg("Eigener Wert")
            ) + "</p>"
            body += post_form(
                "/einstellungen/postfaecher/speichern",
                csrf,
                control(field, value),
                msg("Im Entwurf speichern"),
                number=mailbox_number,
                field=field,
                version=version,
            )
            body += (
                post_form(
                    "/einstellungen/postfaecher/speichern",
                    csrf,
                    "",
                    msg("Zurücksetzen auf global"),
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
                    + (msg("Gilt global") if topic.mailboxes is None else msg("Postfächer: ") + e(topic.mailboxes))
                    + "</p>"
                )
                for scope, title in (
                    ("own", msg("Nur dieses Postfach")),
                    ("all", msg("Für alle Postfächer")),
                    ("exclude", msg("Hier ausschließen")),
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
        body += tr("<p>Globale Sperren: ") + e([*blocked.addresses, *blocked.domains]) + "</p>"
        body += tr("<p>Eigene Sperren und Ausnahmen: ") + e(rules.model_dump() if rules else {}) + "</p>"
        body += post_form(
            "/einstellungen/postfaecher/filter",
            csrf,
            control("entry", "")
            + tr(
                '<label for="filter-action">Änderung</label><select '
                'id="filter-action" name="action"><option value="add">Hier '
                'ignorieren</option><option value="remove">Eigene Sperre '
                'entfernen</option><option value="allow">Globale Sperre hier '
                'ausnehmen</option><option value="unallow">Ausnahme '
                "entfernen</option></select>"
            ),
            msg("Filteränderung vormerken"),
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
