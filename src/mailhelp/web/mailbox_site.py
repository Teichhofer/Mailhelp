"""Mailbox policies and profile management through the existing authenticated draft."""

import json
from urllib.parse import parse_qs

from ..config import TargetProfileSettings, Topic, read_yaml
from ..configuration import MAILBOX_POLICY_FIELDS
from ..mailbox_settings import effective_settings, mailbox_fingerprint
from ..profile_binding import choices
from ..profile_usage import profile_references
from ..review.commands import CommandKind, CommandSource, ReviewCommand
from ..sender_filter import sender_entry
from .archive_site import post_form
from .http import Response
from .pages import e, layout

TABS = {
    "targets": "Ziele",
    "filters": "Filter",
    "topics": "Themen",
    "replies": "Antworten",
    "notifications": "Benachrichtigungen",
}
FIELDS = {
    "targets": ("target_profile", "event_defaults.video_duration_minutes", "event_defaults.in_person_duration_minutes"),
    "replies": ("personal_info", "smart_reply", "activity_report_folder", "retention.full_mail_days"),
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
    "activity_report_folder": "Standardordner für Tätigkeitsberichte",
    "retention.full_mail_days": "Mailinhalt aufbewahren (Tage, disabled oder unlimited)",
    "event_defaults.video_duration_minutes": "Standarddauer Videokonferenz (Minuten)",
    "event_defaults.in_person_duration_minutes": "Standarddauer Präsenztermin (Minuten)",
    "daily_briefing": "Dieses Postfach im Tagesüberblick zeigen",
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


def lookup(value, name):
    for part in name.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def control(name, value, prefix="mailbox"):
    from .setup_site import CHOICES
    from .setup_site import LABELS as TARGET_LABELS

    identity = prefix + "-" + name.replace(".", "-")
    title = LABELS.get(name, TARGET_LABELS.get("targets." + name, name))
    if "targets." + name in CHOICES:
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
    def __init__(self, site):
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
    def runtime(self):
        return self.site.setup_page.runtime

    def page(self, title, body):
        return Response.html(200, layout(title, '<div class="setup-page"><h1>' + e(title) + "</h1>" + body + "</div>"))

    def unavailable(self):
        return Response.text(503, "Einrichtungsdienst nicht verfügbar.")

    def preview(self, session):
        state = self.runtime.setup.state()
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
                cfg = self.runtime.setup.draft_settings()
                if "imap.mailboxes" in state.patch:
                    for box in cfg.imap.configured_mailboxes():
                        text += f"<dt>Postfach {box.id} ({e(box.label)})</dt><dd>"
                        text += (
                            e(
                                {
                                    LABELS.get(name, name): value
                                    for name, value in box.model_dump(exclude_none=True).items()
                                    if name in MAILBOX_POLICY_FIELDS
                                }
                            )
                            + "</dd>"
                        )
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
            for number, count in self.affected().items():
                text += (f"<dt>Laufende Mails in Postfach {number}</dt><dd>{count} werden mit "
                         "configuration_changed zurückgehalten.</dd>")
            text += '</dl><p><a href="/diagnose">Zugriffe prüfen</a></p>'
            csrf = self.site.auth.csrf_token(session.id)
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

    def affected(self):
        from ..decisions import relevance_fingerprint
        from ..models import MailState
        from ..storage import mail_state_names

        app = self.runtime.app
        cfg = self.runtime.setup.draft_settings()
        topics = app.orchestrator.topics
        state = self.runtime.setup.state()
        if state.kind == "topics" and state.category == "relevant":
            changed = Topic.model_validate(state.patch)
            topics = [changed if topic.id == changed.id else topic for topic in topics]
        result = {}
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

    def index(self, request, session):
        if self.runtime is None:
            return self.unavailable()
        cfg = self.runtime.setup.draft_settings()
        body = (
            '<p><a href="/einstellungen/zielprofile">Zielprofile verwalten</a> · '
            '<a href="/einstellungen/absender">Globale Absenderfilter</a></p><ul>'
        )
        for box in cfg.imap.configured_mailboxes():
            body += (
                f'<li><a class="button" href="/einstellungen/postfaecher/{box.id}">{e(box.label)} · {box.id}</a></li>'
            )
        body += '</ul><section class="card"><h2>Postfach hinzufügen</h2>'
        fields = "".join(
            control(name, value)
            for name, value in (("id", ""), ("label", ""), ("host", ""), ("port", 993), ("folders", "INBOX"))
        )
        # Each control has a separate name in this multi-field form.
        for name in ("id", "label", "host", "port", "folders"):
            fields = fields.replace(f'id="mailbox-{name}" name="value"', f'id="mailbox-{name}" name="{name}"')
        body += post_form(
            "/einstellungen/postfaecher/speichern",
            self.site.auth.csrf_token(session.id),
            fields,
            "Postfach als Entwurf hinzufügen",
            action="add",
            version=self.runtime.setup.state().version,
        )
        return self.page("Postfächer", body + "</section>" + self.preview(session))

    def mailbox(self, request, session, number):
        if self.runtime is None:
            return self.unavailable()
        cfg, number = self.runtime.setup.draft_settings(), int(number)
        box = cfg.imap.mailbox(number)
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
            effective = effective_settings(cfg, number).model_dump(mode="json")
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
                    number=number,
                    field=field,
                    version=version,
                )
                body += (
                    post_form(
                        "/einstellungen/postfaecher/speichern",
                        csrf,
                        "",
                        "Zurücksetzen auf global",
                        number=number,
                        field=field,
                        version=version,
                        action="reset",
                    )
                    + "</section>"
                )
        elif tab == "topics":
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
                            number=number,
                            topic=topic.id,
                            category=category,
                            scope=scope,
                            version=version,
                        )
                    body += "</section>"
        else:
            blocked = self.runtime.setup.configuration.blocked_senders()
            rules = blocked.mailboxes.get(str(number))
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
                number=number,
                version=version,
            )
        body += post_form(
            "/einstellungen/postfaecher/speichern",
            csrf,
            "",
            "Postfach entfernen",
            number=number,
            action="remove",
            version=version,
        )
        return self.page(box.label, body + self.preview(session))

    def save(self, request, session, form):
        if self.runtime is None:
            return self.unavailable()
        try:
            cfg = self.runtime.setup.draft_settings()
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
                    value = {"target_profile": 1, "daily_briefing": True}.get(field)
                    field = "retention" if field == "retention.full_mail_days" else field
                elif (
                    field.endswith(("minutes", "days"))
                    or field == "target_profile"
                    or field.startswith("notifications.categories.")
                    or field in {"smart_reply", "daily_briefing"}
                    or field.endswith((".enabled", ".allow_system_errors"))
                ):
                    value = (
                        json.loads(form["value"]) if form["value"] not in {"disabled", "unlimited"} else form["value"]
                    )
                else:
                    value = form["value"]
                from ..configuration import set_dotted

                set_dotted(box, field, value)
            self.runtime.setup.save(
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

    def topic(self, request, session, form):
        if self.runtime is None:
            return self.unavailable()
        try:
            number, category = int(form["number"]), form["category"]
            if category not in {"relevant", "irrelevant"}:
                raise ValueError("Unbekannte Themenliste")
            filename = "topics.yaml" if category == "relevant" else "irrelevant_topics.yaml"
            cfg = self.runtime.setup.draft_settings()
            topic = next(
                Topic.model_validate(value)
                for value in read_yaml(self.runtime.setup.configuration.directory / filename)["topics"]
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
            self.runtime.setup.save_local(
                f"web:{session.id}", int(form["version"]), form["key"], "topics", patch, category
            )
        except (ValueError, KeyError, StopIteration, PermissionError):
            return Response.text(409, "Themenentwurf nicht gespeichert.")
        return Response.redirect("/einstellungen/postfaecher")

    def filter(self, request, session, form):
        if self.runtime is None:
            return self.unavailable()
        try:
            kind, entry = sender_entry(form["value"])
            patch = {
                "action": form["action"],
                "mailbox_id": int(form["number"]),
                "addresses" if kind == "address" else "domains": [entry],
            }
            self.runtime.setup.save_local(f"web:{session.id}", int(form["version"]), form["key"], "senders", patch)
        except (ValueError, KeyError, PermissionError):
            return Response.text(409, "Filterentwurf nicht gespeichert.")
        return Response.redirect("/einstellungen/postfaecher")

    def discard(self, request, session, form):
        if self.runtime is None:
            return self.unavailable()
        try:
            self.runtime.setup.discard(f"web:{session.id}", int(form["version"]), form["key"])
        except (ValueError, KeyError, PermissionError):
            return Response.text(409, "Entwurf nicht verworfen; Version und Sitzung prüfen.")
        return Response.redirect("/einstellungen/postfaecher")

    def profiles(self, request, session):
        if self.runtime is None:
            return self.unavailable()
        cfg = self.runtime.setup.draft_settings()
        body = (
            '<p><a href="/einstellungen/postfaecher">Postfächer</a> · '
            '<a href="/diagnose">Diagnose je Profil</a> · <a href="/einrichtung">Standardprofil 1 bearbeiten</a></p>'
        )
        for profile in cfg.target_profiles:
            references = profile_references(self.site.views.store, cfg, profile.id)
            body += '<section class="card"><h2>' + e(profile.label) + f" · {profile.id}</h2>"
            for field, value in profile.model_dump().items():
                if field == "id":
                    continue
                body += post_form(
                    "/einstellungen/zielprofile/speichern",
                    self.site.auth.csrf_token(session.id),
                    control(field, value, prefix=f"profile-{profile.id}"),
                    "Profiländerung vormerken",
                    number=profile.id,
                    field=field,
                    version=self.runtime.setup.state().version,
                )
            body += "<p>Verwendet von: " + e(references) + "</p>"
            if not references:
                body += post_form(
                    "/einstellungen/zielprofile/speichern",
                    self.site.auth.csrf_token(session.id),
                    "",
                    "Profil entfernen",
                    number=profile.id,
                    action="remove",
                    version=self.runtime.setup.state().version,
                )
            body += "</section>"
        body += '<section class="card"><h2>Zielprofil hinzufügen</h2>'
        fields = "".join(
            control(name, value, prefix="new-profile").replace('name="value"', f'name="{name}"')
            for name, value in (
                ("id", ""),
                ("label", ""),
                ("calendar_provider", "google"),
                ("google_calendar", "primary"),
                ("task_provider", "todoist"),
                ("todoist_project", ""),
            )
        )
        body += post_form(
            "/einstellungen/zielprofile/speichern",
            self.site.auth.csrf_token(session.id),
            fields,
            "Neues Profil vormerken",
            action="add",
            version=self.runtime.setup.state().version,
        )
        return self.page("Zielprofile", body + "</section>" + self.preview(session))

    def save_profile(self, request, session, form):
        if self.runtime is None:
            return self.unavailable()
        try:
            cfg = self.runtime.setup.draft_settings()
            profiles = [profile.model_dump() for profile in cfg.target_profiles]
            if form.get("action") == "add":
                profile = {
                    name: form[name]
                    for name in ("label", "calendar_provider", "google_calendar", "task_provider", "todoist_project")
                }
                profile["id"] = int(form["id"])
                profiles.append(TargetProfileSettings.model_validate(profile).model_dump())
            elif form.get("action") == "remove":
                profiles = [value for value in profiles if value["id"] != int(form["number"])]
            else:
                value = next(profile for profile in profiles if profile["id"] == int(form["number"]))
                if form["field"] not in TargetProfileSettings.model_fields or form["field"] == "id":
                    raise ValueError("Profilnummern bleiben stabil")
                value[form["field"]] = form["value"]
            self.runtime.setup.save(
                f"web:{session.id}",
                int(form["version"]),
                form["key"],
                6,
                {"target_profiles": profiles},
                request_signature={name: value for name, value in form.items() if name not in {"csrf", "key"}},
            )
        except (ValueError, KeyError, StopIteration, PermissionError):
            return Response.text(409, "Profilentwurf nicht gespeichert; Verweise, Angaben und Version prüfen.")
        return Response.redirect("/einstellungen/zielprofile")

    def target_forms(self, proposal, session):
        if self.runtime is None:
            return ""
        cfg = self.runtime.app.settings
        body = ""
        for number, name, digest in choices(cfg, proposal):
            body += post_form(
                "/einstellungen/zielprofile/umstellen",
                self.site.auth.csrf_token(session.id),
                "",
                f"Auf Zielprofil {name} umstellen",
                mail_id=proposal.source_mail_id,
                proposal_id=proposal.id,
                version=proposal.version,
                number=number,
                digest=digest,
            )
        return body

    def retarget(self, request, session, form):
        try:
            command = ReviewCommand(
                kind=CommandKind.RETARGET,
                source=CommandSource.WEB,
                actor=f"web:{session.id}",
                mail_id=form["mail_id"],
                proposal_id=form["proposal_id"],
                version=int(form["version"]),
                idempotency_key=form["key"],
                target_profile=int(form["number"]),
                proposal_hash=form["digest"],
            )
        except (ValueError, KeyError):
            return Response.text(422, "Ungültige Zielwahl.")
        return self.site.archive.queue(request, command)
