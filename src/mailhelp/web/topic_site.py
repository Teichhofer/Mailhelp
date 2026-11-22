"""Compact topic catalog and individual forms; writes use SettingsSite/AdminCommand."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

import yaml

from ..config import IrrelevantTopicsConfig, Topic, TopicsConfig, read_yaml
from ..config.configuration import AdminCommand, AdminKind
from ..i18n import msg, tr
from .http import Request, Response
from .pages import e, layout, page_head
from .settings_search import normalize
from .topic_editor import KINDS, TopicEditor, topic_link

_HOME_TEXT_1 = msg(
    '</nav><div class="topic-toolbar"><form method="get" action="/themen" '
    'id="topic-filter"><input type="hidden" name="art" value="{p0}"><div '
    'class="topic-search"><label for="topic-query">Themen durchsuchen</label><input '
    'id="topic-query" name="suche" value="{p1}" maxlength="80" type="search"></div><div '
    'class="topic-state"><label for="topic-status">Status filtern</label><select '
    'id="topic-status" name="status">'
)

_HOME_TEXT_2 = msg(
    '</select></div><button class="button">Themen suchen</button></form><a class="button '
    'primary topic-new" href="/themen/{p0}/neu">Neues Thema</a></div>'
)

_HOME_TEXT_3 = msg(
    '<p role="status" id="topic-count" aria-live="polite">{p0} von {p1} Themen '
    'angezeigt.</p><p id="topic-empty"{p2}>Keine passenden Themen.</p><table '
    'class="topic-table"><caption>Themenübersicht</caption><thead><tr><th '
    'scope="col">Thema</th><th scope="col">Status</th><th '
    'scope="col">Geltungsbereich</th><th scope="col">Beispiele / Ausschlüsse</th><th '
    'scope="col">Beschreibung</th><th scope="col" class="topic-action"><span '
    'class="visually-hidden">Bearbeiten</span></th></tr></thead><tbody>'
)

_HOME_TEXT_4 = msg(
    '</tbody></table><details class="topic-guidance"><summary>Hinweise und '
    "Lernen</summary><p>Themen auf einen Blick. Deaktivieren statt löschen; Änderungen "
    "gelten für neue Analysen.</p><p>{p0}</p></details><p><a "
    'href="/lernen/entscheidungen">Aus Entscheidungen lernen</a></p><script '
    'src="/static/topics.js" defer></script>'
)

if TYPE_CHECKING:
    from .site import MailhelpSite


def matches(topic: Topic, query: str, status: str) -> bool:
    text = normalize(" ".join([topic.id, topic.name, topic.description, *topic.examples, *topic.exclusions]))
    return (all(word in text for word in normalize(query).split())
            and (status == "alle" or (status == "aktiv") == topic.enabled))


class TopicSite:
    def __init__(self, settings: Any) -> None:
        self.settings, self.archive = settings, settings.archive
        self.site: MailhelpSite = settings.site
        self.site.app.route("GET", "/themen", self.site.signed_in(self.home))
        self.editing = TopicEditor(self)

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
            return msg("alle Postfächer")
        names = {box.id: box.label for box in self.archive.configuration.active.imap.configured_mailboxes()}
        return ", ".join(names.get(number, tr("Postfach {p0}", p0=number)) for number in topic.mailboxes) or msg(
            "keine Postfächer"
        )

    def home(self, request: Request, session: Any) -> Response:
        if self.archive.configuration is None:
            return self.site._reply(request, 503, msg("Themenverwaltung nicht verfügbar."))
        try:
            parameters = self.archive.parameters(request)
            kind, query, status = (
                parameters.get("art", "relevant"),
                parameters.get("suche", "")[:80],
                parameters.get("status", msg("alle")),
            )
            if kind not in KINDS or status not in {"alle", "aktiv", "deaktiviert"}:
                raise ValueError("Unbekannter Filter")
            documents = self.documents()
        except (ValueError, KeyError, OSError, yaml.YAMLError):
            return self.site._reply(request, 400, msg("Themen oder Filter nicht lesbar; Angaben und Dateien prüfen."))
        body = (
            '<div class="topic-heading">' + page_head(msg("Themen"), msg("Einstellungen")) + "</div>"
            '<nav class="topic-tabs" aria-label="Themenarten">'
        )
        for category, (_internal, _filename, title) in KINDS.items():
            href = "/themen?" + urlencode({"art": category, "suche": query, "status": status})
            body += (f'<a class="button" href="{e(href)}"'
                     f'{" aria-current=\"page\"" if category == kind else ""}>{title} ({len(documents[category])})</a>')
        description = (
            msg("Mails zu diesen Themen werden ausgewertet.")
            if kind == "relevant"
            else msg(
                
                    "Negative Themen für Lern- und Entscheidungstests. Im Mailbetrieb wirken "
                    "die Ausschlüsse der relevanten Themen; ein Ausschlussthema ist kein "
                    "zusätzlicher globaler Vorfilter."
                
            )
        )
        # 5.9.6: search, status, filter button and "Neues Thema" share one tool row from 720 px.
        body += tr(
            (_HOME_TEXT_1),
            p0=kind,
            p1=e(query),
        )
        for value, title in (
            ('alle', msg("Alle")),
            ('aktiv', msg("Aktiv")),
            ('deaktiviert', msg("Deaktiviert")),
        ):
            body += f'<option value="{value}"{" selected" if value == status else ""}>{title}</option>'
        body += tr(
            (_HOME_TEXT_2),
            p0=kind,
        )
        selected = sorted(documents[kind], key=lambda item: (not item.enabled, item.name.casefold(), item.id))
        drafts = self.editing.drafts("web:" + session.id)
        if drafts:
            body += f'<section class="card"><h2>{e(tr("Ausstehende Themenänderungen"))}</h2><ul>'
            body += "".join(
                tr(
                    ('<li><a href="/themen/entwurf/{p0}">{p1}: Vorschau anzeigen</a></li>'),
                    p0=identity,
                    p1=e(name),
                )
                for identity, _category, _topic_id, name in drafts
            )
            body += '</ul></section>'
        count = sum(matches(topic, query, status) for topic in selected)
        body += tr(
            (_HOME_TEXT_3),
            p0=count,
            p1=len(selected),
            p2=" hidden" if count else "",
        )
        pending = self.pending()
        pending.update((category, identity) for _draft, category, identity, _name in drafts)
        for topic in selected:
            body += self.row(kind, topic, (KINDS[kind][0], topic.id) in pending, not matches(topic, query, status))
        body += tr(
            (_HOME_TEXT_4),
            p0=e(description),
        )
        return Response.html(200, layout(msg("Themen"), body, active="/einstellungen", wide=True))

    def row(self, kind: str, topic: Topic, pending: bool, hidden: bool) -> str:
        text = normalize(" ".join([topic.id, topic.name, topic.description, *topic.examples, *topic.exclusions]))
        description = re.split(r"(?<=[.!?])\s+", topic.description.strip(), maxsplit=1)[0]
        description = description[:159] + "…" if len(description) > 160 else description
        return (
            f'<tr data-topic-row data-topic-search="{e(text)}" data-enabled="{str(topic.enabled).lower()}"'
            f' class="topic-row{" is-disabled" if not topic.enabled else ""}"{" hidden" if hidden else ""}>'
            f'<td data-label="Thema"><strong>{e(topic.name)}</strong><small>{e(topic.id)}</small>'
            + (tr('<span class="badge">Änderung ausstehend</span>') if pending else "")
            + tr(
                (
                    '</td><td data-label="Status"><span '
                    'class="badge">{p0}</span></td><td '
                    'data-label="Geltungsbereich">{p1}</td><td data-label="Beispiele '
                    '/ Ausschlüsse">{p2} / {p3}</td><td '
                    'data-label="Beschreibung">{p4}</td><td class="topic-action"><a '
                    'class="button" href="{p5}" aria-label="{p6} '
                    'bearbeiten">Bearbeiten</a></td></tr>'
                ),
                p0=msg("aktiv") if topic.enabled else msg("deaktiviert"),
                p1=e(self.scope(topic)),
                p2=len(topic.examples),
                p3=len(topic.exclusions),
                p4=e(description),
                p5=topic_link(kind, topic.id),
                p6=e(topic.name),
            )
        )
