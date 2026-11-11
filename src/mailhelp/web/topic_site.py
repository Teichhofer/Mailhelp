"""Compact topic catalog and individual forms; writes use SettingsSite/AdminCommand."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

import yaml

from ..config import IrrelevantTopicsConfig, Topic, TopicsConfig, read_yaml
from ..configuration import AdminCommand, AdminKind, file_hash
from .forms import post_form
from .http import Request, Response
from .pages import e, layout
from .settings_search import normalize

if TYPE_CHECKING:
    from .site import MailhelpSite

KINDS = {"relevant": ("relevant", "topics.yaml", "Relevante Themen"),
         "ausschluss": ("irrelevant", "irrelevant_topics.yaml", "Ausschlussthemen")}


def topic_link(kind: str, identity: str) -> str:
    return f"/themen/{kind}/{identity}" + ("?vorhanden=1" if identity == "neu" else "")


def matches(topic: Topic, query: str, status: str) -> bool:
    text = normalize(" ".join([topic.id, topic.name, topic.description, *topic.examples, *topic.exclusions]))
    return (all(word in text for word in normalize(query).split())
            and (status == "alle" or (status == "aktiv") == topic.enabled))


class TopicSite:
    def __init__(self, settings: Any):
        self.settings, self.archive = settings, settings.archive
        self.site: MailhelpSite = settings.site
        self.site.app.route("GET", "/themen", self.site.signed_in(self.home))
        self.site.app.route("GET", r"/themen/(?P<kind>relevant|ausschluss)/(?P<identity>[a-z0-9_-]{1,64})",
                            self.site.signed_in(self.editor))

    def documents(self) -> dict[str, list[Topic]]:
        result = {}
        for kind, (category, filename, _title) in KINDS.items():
            model = TopicsConfig if category == "relevant" else IrrelevantTopicsConfig
            result[kind] = model.model_validate(read_yaml(self.archive.configuration.directory / filename)).topics
        return result

    def pending(self) -> set[tuple[str, str]]:
        return {(entry.command.category, str(entry.command.patch.get("id", "")))
                for entry in self.site.commands.queued()
                if isinstance(entry.command, AdminCommand) and entry.command.kind == AdminKind.TOPICS}

    def scope(self, topic: Topic) -> str:
        if topic.mailboxes is None:
            return "alle Postfächer"
        names = {box.id: box.label for box in self.archive.configuration.active.imap.configured_mailboxes()}
        return ", ".join(names.get(number, f"Postfach {number}") for number in topic.mailboxes) or "keine Postfächer"

    def home(self, request: Request, session: Any) -> Response:
        if self.archive.configuration is None:
            return self.site._reply(request, 503, "Themenverwaltung nicht verfügbar.")
        try:
            parameters = self.archive.parameters(request)
            kind, query, status = (parameters.get("art", "relevant"), parameters.get("suche", "")[:80],
                                   parameters.get("status", "alle"))
            if kind not in KINDS or status not in {"alle", "aktiv", "deaktiviert"}:
                raise ValueError("Unbekannter Filter")
            documents = self.documents()
        except (ValueError, KeyError, OSError, yaml.YAMLError):
            return self.site._reply(request, 400, "Themen oder Filter nicht lesbar; Angaben und Dateien prüfen.")
        body = ('<div class="page-heading"><p class="eyebrow">Einstellungen</p><h1>Themen</h1>'
                '<p>Themen auf einen Blick. Deaktivieren statt löschen; Änderungen gelten für neue Analysen.</p></div>'
                '<section class="card"><p>Regeln aus Ihren Entscheidungen verbessern.</p>'
                '<p><a class="button" href="/lernen/entscheidungen">Aus Entscheidungen lernen</a></p></section>'
                '<nav class="topic-tabs" aria-label="Themenarten">')
        for category, (_internal, _filename, title) in KINDS.items():
            href = "/themen?" + urlencode({"art": category, "suche": query, "status": status})
            body += (f'<a class="button" href="{e(href)}"'
                     f'{" aria-current=\"page\"" if category == kind else ""}>{title} ({len(documents[category])})</a>')
        description = ("Mails zu diesen Themen werden ausgewertet." if kind == "relevant" else
                       "Negative Themen für Lern- und Entscheidungstests. Im Mailbetrieb wirken die Ausschlüsse "
                       "der relevanten Themen; ein Ausschlussthema ist kein zusätzlicher globaler Vorfilter.")
        body += ('</nav>' + f'<p>{e(description)}</p><form method="get" action="/themen" id="topic-filter">'
                 f'<input type="hidden" name="art" value="{kind}">'
                 '<label for="topic-query">Themen durchsuchen</label>'
                 f'<input id="topic-query" name="suche" value="{e(query)}" maxlength="80" type="search">'
                 '<label for="topic-status">Status filtern</label><select id="topic-status" name="status">')
        for value, title in (("alle", "Alle"), ("aktiv", "Aktiv"), ("deaktiviert", "Deaktiviert")):
            body += f'<option value="{value}"{" selected" if value == status else ""}>{title}</option>'
        body += ('</select><button class="button">Themen suchen</button></form>'
                 f'<p><a class="button" href="/themen/{kind}/neu">Neues Thema</a></p>')
        selected = sorted(documents[kind], key=lambda item: (not item.enabled, item.name.casefold(), item.id))
        count = sum(matches(topic, query, status) for topic in selected)
        body += ('<p role="status" id="topic-count" aria-live="polite">'
                 f'{count} von {len(selected)} Themen angezeigt.</p>'
                 f'<p id="topic-empty"{" hidden" if count else ""}>Keine passenden Themen.</p>'
                 '<table class="topic-table"><caption>Themenübersicht</caption><thead><tr>'
                 '<th scope="col">Thema</th><th scope="col">Status</th><th scope="col">Geltungsbereich</th>'
                 '<th scope="col">Beispiele / Ausschlüsse</th><th scope="col">Beschreibung</th>'
                 '<th scope="col">Bearbeiten</th></tr></thead><tbody>')
        pending = self.pending()
        for topic in selected:
            body += self.row(kind, topic, (KINDS[kind][0], topic.id) in pending, not matches(topic, query, status))
        body += '</tbody></table><script src="/static/topics.js" defer></script>'
        return Response.html(200, layout("Themen", body, active="/einstellungen"))

    def row(self, kind: str, topic: Topic, pending: bool, hidden: bool) -> str:
        text = normalize(" ".join([topic.id, topic.name, topic.description, *topic.examples, *topic.exclusions]))
        description = re.split(r"(?<=[.!?])\s+", topic.description.strip(), maxsplit=1)[0]
        description = description[:159] + "…" if len(description) > 160 else description
        return (f'<tr data-topic-row data-topic-search="{e(text)}" data-enabled="{str(topic.enabled).lower()}"'
                f' class="topic-row{" is-disabled" if not topic.enabled else ""}"{" hidden" if hidden else ""}>'
                f'<td data-label="Thema"><strong>{e(topic.name)}</strong><small>{e(topic.id)}</small>'
                + ('<span class="badge">Änderung ausstehend</span>' if pending else "")
                + '</td><td data-label="Status"><span class="badge">'
                f'{"aktiv" if topic.enabled else "deaktiviert"}</span>'
                f'</td><td data-label="Geltungsbereich">{e(self.scope(topic))}</td>'
                f'<td data-label="Beispiele / Ausschlüsse">{len(topic.examples)} / {len(topic.exclusions)}</td>'
                f'<td data-label="Beschreibung">{e(description)}</td><td>'
                f'<a class="button" href="{topic_link(kind, topic.id)}" aria-label="{e(topic.name)} bearbeiten">'
                'Bearbeiten</a></td></tr>')

    def editor(self, request: Request, session: Any, kind: str, identity: str) -> Response:
        if self.archive.configuration is None:
            return self.site._reply(request, 503, "Themenverwaltung nicht verfügbar.")
        try:
            documents = self.documents()
            parameters = self.archive.parameters(request)
            new = identity == "neu" and parameters.get("vorhanden") != "1"
            topic = (Topic(id="neu", name="", description="", enabled=True) if new else
                     next((item for item in documents[kind] if item.id == identity), None))
            if topic is None:
                return self.site._reply(request, 404, "Thema nicht gefunden.")
            revision = file_hash(self.archive.configuration.directory / KINDS[kind][1])
        except (ValueError, KeyError, OSError, yaml.YAMLError):
            return self.site._reply(request, 400, "Themendatei nicht lesbar.")
        return Response.html(200, layout("Thema bearbeiten", self.edit_form(kind, topic, new, revision, session),
                                        active="/einstellungen"))

    def edit_form(self, kind: str, topic: Topic, new: bool, revision: str, session: Any) -> str:
        body = ('<div class="page-heading"><p class="eyebrow">Themen</p><h1>'
                + ("Neues Thema" if new else e(topic.name)) + '</h1></div>'
                f'<p><a href="/themen?art={kind}">Zur Themenübersicht</a></p>'
                f'<p>Geltungsbereich: {e(self.scope(topic))}</p>')
        fields = (f'<label>Themen-ID<input name="id" value="{"" if new else e(topic.id)}"'
                  f'{"" if new else " readonly"} required></label>'
                  f'<label>Name<input name="name" value="{e(topic.name)}" required></label>')
        for key, title, value in (("description", "Beschreibung", topic.description),
                                  ("examples", "Beispiele (ein Eintrag je Zeile)", "\n".join(topic.examples)),
                                  ("exclusions", "Ausschlüsse (ein Eintrag je Zeile)", "\n".join(topic.exclusions))):
            fields += f'<label>{title}<textarea name="{key}" rows="4">{e(value)}</textarea></label>'
        fields += ('<label>Aktiv<select name="enabled">'
                   f'<option value="true"{" selected" if topic.enabled else ""}>Ja</option>'
                   f'<option value="false"{" selected" if not topic.enabled else ""}>Nein</option></select></label>'
                   '<label><input type="checkbox" name="confirm" value="yes" required> '
                   'Änderung ausdrücklich speichern</label>')
        return body + post_form("/themen/speichern", self.site.auth.csrf_token(session.id), fields,
                                category=KINDS[kind][0], expected_hash=revision,
                                original_id="" if new else topic.id, list_format="lines")
