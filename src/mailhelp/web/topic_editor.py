"""Two-step topic editing; only an explicitly confirmed AdminCommand is queued."""
from __future__ import annotations

import json
import re
import time
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import ValidationError
from pydantic_core import ErrorDetails

from ..configuration import AdminCommand, AdminKind, ConfigurationConflict, file_hash
from ..review.inbox import CommandConflict
from ..rule_learning.models import RuleTopic
from ..storage import CorruptState, JsonStore
from .forms import field, post_form
from .http import Request, Response
from .pages import e, layout
from .rule_compare import compare
from .topic_drafts import TopicDraft, TopicFieldError, draft_id, owner, proposed_id
from .topic_site import KINDS, topic_link

if TYPE_CHECKING:
    from .site import MailhelpSite

LABELS = {"id": "Themen-ID", "name": "Name", "description": "Beschreibung", "examples": "Beispiele",
          "exclusions": "Ausschlüsse", "enabled": "Aktiv", "mailboxes": "Geltungsbereich"}
HELP = {"name": "Höchstens 200 Zeichen.", "description": "Woran erkennt man das Thema? Höchstens 1000 Zeichen.",
        "examples": "Ein typischer Betreff oder Satz je Zeile; höchstens 30 Einträge mit je 500 Zeichen.",
        "exclusions": "Was trotz Ähnlichkeit nicht dazugehört, je Zeile; höchstens 30 Einträge mit je 500 Zeichen."}


def entries(text: str) -> list[str]:
    """One entry per line; blank lines and surrounding spaces are not entries (a ";" stays inside)."""
    return [line.strip() for line in text.splitlines() if line.strip()]


def validation_message(error: ErrorDetails) -> str:
    kind, context = error["type"], error.get("ctx", {})
    if kind == "string_too_short":
        return f'Bitte mindestens {context["min_length"]} Zeichen eingeben.'
    if kind == "string_too_long":
        return f'Höchstens {context["max_length"]} Zeichen sind erlaubt.'
    if kind == "too_long":
        return f'Höchstens {context["max_length"]} Einträge sind erlaubt.'
    if kind == "value_error":
        return str(error["msg"]).removeprefix("Value error, ")
    return "Ungültige Angabe. Bitte Format und Feldhilfe beachten."


class TopicEditor:
    def __init__(self, catalog: Any):
        self.catalog, self.archive = catalog, catalog.archive
        self.site: MailhelpSite = catalog.site
        self.store: JsonStore = self.site.views.store
        self.clock = time.time
        self.site.app.route("GET", r"/themen/(?P<kind>relevant|ausschluss)/(?P<identity>[a-z0-9_-]{1,64})",
                            self.site.signed_in(self.show))
        self.site.app.route("POST", "/themen/pruefen", self.site.signed_in(self.preview))
        self.site.app.route("GET", r"/themen/entwurf/(?P<identity>[a-f0-9]{64})", self.site.signed_in(self.resume))

    def check(self, actor: str) -> None:
        if not self.archive.configuration.authorize(actor):
            raise PermissionError("Sitzung inzwischen abgelaufen.")

    def load(self, identity: str, actor: str) -> TopicDraft:
        if not re.fullmatch(r"[a-f0-9]{64}", identity):
            raise PermissionError("Ungültiger Entwurf.")
        state = self.store.load_model("topic-draft-" + identity, TopicDraft, TopicDraft())
        if state.owner and state.owner != owner(actor):
            raise PermissionError("Kein eigener Themenentwurf.")
        if state.created_at and self.clock() - state.created_at > 86400:
            state = TopicDraft(version=state.version + 1, owner=owner(actor))
            self.store.save("topic-draft-" + identity, state.model_dump(mode="json"))
        return state

    def context(self, kind: str, original: str) -> tuple[Any, str, Any]:
        documents = self.catalog.documents()
        before = next((topic for topic in documents[kind] if topic.id == original), None)
        if original and before is None:
            raise TopicFieldError("id", "Thema nicht gefunden.", 404)
        revision = file_hash(self.archive.configuration.directory / KINDS[kind][1])
        return before, revision, documents

    def show(self, request: Request, session: Any, kind: str, identity: str) -> Response:
        if self.archive.configuration is None:
            return self.site._reply(request, 503, "Themenverwaltung nicht verfügbar.")
        try:
            parameters = self.archive.parameters(request)
            original = "" if identity == "neu" and parameters.get("vorhanden") != "1" else identity
            before, revision, _documents = self.context(kind, original)
            state = self.load(draft_id("web:" + session.id, kind, original), "web:" + session.id)
            values = self.values(state.topic if state.topic is not None and state.expected_hash == revision else before)
            return self.form(session, kind, original, before, revision, state.version, values)
        except TopicFieldError as error:
            return self.site._reply(request, error.status, str(error))
        except PermissionError:
            return self.site._reply(request, 403, "Kein eigener Themenentwurf.")
        except (ValueError, KeyError, OSError, CorruptState, yaml.YAMLError):
            return self.site._reply(request, 400, "Themendatei oder Entwurf nicht lesbar.")

    @staticmethod
    def values(topic: Any) -> dict[str, str]:
        if topic is None:
            return {"id": "", "name": "", "description": "", "examples": "", "exclusions": "", "enabled": "yes"}
        return {"id": topic.id, "name": topic.name, "description": topic.description,
                "examples": "\n".join(topic.examples), "exclusions": "\n".join(topic.exclusions),
                "enabled": "yes" if topic.enabled else ""}

    def form(self, session: Any, kind: str, original: str, before: Any, revision: str, version: int,
             values: dict[str, str], errors: dict[str, str] | None = None, status: int = 200) -> Response:
        errors = errors or {}
        title = e(before.name) if before is not None else "Neues Thema"
        body = ('<div class="page-heading"><p class="eyebrow">'
                + ("Thema bearbeiten" if original else KINDS[kind][2]) + f'</p><h1>{title}</h1></div>'
                f'<p><a href="/themen?art={kind}">Zur Themenübersicht</a></p>'
                f'<p>Geltungsbereich: {e(self.catalog.scope(before) if before else "alle Postfächer")}</p>')
        if errors:
            body += ('<section id="form-errors" class="notice notice-error" tabindex="-1" autofocus '
                     'aria-labelledby="form-errors-title"><h2 id="form-errors-title">Eingaben prüfen</h2><ul>')
            for key, message in errors.items():
                body += (f'<li>{e(message)}</li>' if key == "__all__" else
                         f'<li><a href="#topic-{key}">{e(LABELS[key])}: {e(message)}</a></li>')
            body += '</ul></section>'
        if status == 409:
            href = topic_link(kind, original) if original else f"/themen/{kind}/neu"
            body += f'<p><a href="{href}">Neu laden</a></p>'
        fields = ""
        for key in ("name", "id", "description", "examples", "exclusions"):
            fields += '<div class="topic-field">'
            if key == "id" and original:
                fields += f'<p>Themen-ID: <code>{e(original)}</code></p>' + field("id", "", original, hidden=True)
            else:
                invalid = ' aria-invalid="true"' if key in errors else ""
                invalid += (f' aria-describedby="topic-{key}-help'
                            + (f' topic-{key}-error' if key in errors else "") + '"')
                fields += f'<label for="topic-{key}">{LABELS[key]}</label>'
                value = values.get(key, "")
                fields += (f'<textarea id="topic-{key}" name="{key}" rows="4"{invalid}>{e(value)}</textarea>'
                           if key in {"description", "examples", "exclusions"} else
                           f'<input id="topic-{key}" name="{key}" value="{e(value)}"{invalid} '
                           f'{"maxlength=64" if key == "id" else "maxlength=200"}>')
                help_text = HELP.get(key, "Aus dem Namen vorgeschlagen; vor dem Speichern änderbar.")
                fields += f'<p class="meta" id="topic-{key}-help">{e(help_text)}</p>'
            if key in errors:
                fields += (f'<p id="topic-{key}-error" class="notice notice-error" role="alert">'
                           f'{e(LABELS[key])}: {e(errors[key])}</p>')
            fields += '</div>'
        invalid = ' aria-invalid="true" aria-describedby="topic-enabled-error"' if "enabled" in errors else ""
        fields += (f'<label for="topic-enabled"><input id="topic-enabled" type="checkbox" name="enabled" value="yes"'
                   f'{invalid}'
                   f'{" checked" if values.get("enabled") == "yes" else ""}> Aktiv</label>')
        if "enabled" in errors:
            fields += (f'<p id="topic-enabled-error" class="notice notice-error" role="alert">'
                       f'Aktiv: {e(errors["enabled"])}</p>')
        body += post_form("/themen/pruefen", self.site.auth.csrf_token(session.id), fields, "Änderung prüfen",
                          kind=kind, original_id=original, expected_hash=revision, draft_version=version)
        representation: dict[str, Any] = {key: values.get(key, "") for key in ("id", "name", "description")}
        representation.update({key: values.get(key, "").splitlines() for key in ("examples", "exclusions")})
        representation.update(enabled=values.get("enabled") == "yes", mailboxes=before.mailboxes if before else None)
        body += ('<details><summary>Erweitert</summary><p>Themen-YAML nur zum Lesen und Kopieren.</p><pre>'
                 + e(yaml.safe_dump(representation, allow_unicode=True, sort_keys=False))
                 + '</pre></details><script src="/static/topics.js" defer></script>')
        return Response.html(status, layout("Thema bearbeiten", body, active="/einstellungen"))

    def validated(self, kind: str, original: str, before: Any, documents: Any,
                  values: dict[str, str], revision: str, actor: str, key: str) -> RuleTopic:
        if original and values["id"] != original:
            raise TopicFieldError("id", "Die bestehende Themen-ID darf nicht geändert werden.")
        values["id"] = values["id"] or proposed_id(values["name"])
        if values.get("enabled") not in {"", "yes"}:
            raise TopicFieldError("enabled", "Ungültiger Aktivierungswert.")
        if not original and any(topic.id == values["id"] for topics in documents.values() for topic in topics):
            raise TopicFieldError("id", "Diese Themen-ID ist bereits vergeben.")
        topic = RuleTopic(id=values["id"], name=values["name"], description=values["description"],
                          enabled=values.get("enabled", "") == "yes", examples=entries(values["examples"]),
                          exclusions=entries(values["exclusions"]), mailboxes=before.mailboxes if before else None)
        command = AdminCommand(kind=AdminKind.TOPICS, actor=actor, idempotency_key=key, expected_hash=revision,
                               category=KINDS[kind][0], patch=topic.model_dump(mode="json"), acknowledged=True)
        try:
            self.archive.configuration.candidate(command)
        except ConfigurationConflict as error:
            raise TopicFieldError("__all__", "Datei während der Prüfung geändert; bitte neu laden.", 409) from error
        except ValueError as error:
            raise TopicFieldError("enabled" if not topic.enabled else "__all__", str(error)) from error
        return topic

    def prepare(self, session: Any, form: dict[str, str], values: dict[str, str]) -> tuple[str, TopicDraft]:
        actor, kind, original = "web:" + session.id, form["kind"], form["original_id"]
        self.check(actor)
        before, revision, documents = self.context(kind, original)
        if revision != form["expected_hash"]:
            raise TopicFieldError("__all__", "Datei inzwischen geändert. Neu laden, bevor Sie erneut bestätigen.", 409)
        identity = draft_id(actor, kind, original)
        state = self.load(identity, actor)
        fingerprint = owner(json.dumps([kind, original, revision, values], sort_keys=True))
        if state.key == form["key"]:
            if state.input_hash != fingerprint:
                raise TopicFieldError("__all__", "Idempotenzschlüssel bereits anders verwendet.", 409)
            return identity, state
        if int(form["draft_version"]) != state.version:
            raise TopicFieldError("__all__", "Ein neuerer Entwurf liegt vor. Bitte neu laden.", 409)
        topic = self.validated(kind, original, before, documents, values, revision, actor, form["key"])
        self.check(actor)
        state = TopicDraft(version=state.version + 1, owner=owner(actor), created_at=self.clock(), kind=kind,
                           original_id=original, expected_hash=revision, key=form["key"], input_hash=fingerprint,
                           topic=topic, before=before)
        self.store.save("topic-draft-" + identity, state.model_dump(mode="json"))
        return identity, state

    def preview(self, request: Request, session: Any, form: dict[str, str]) -> Response:
        if self.archive.configuration is None:
            return self.site._reply(request, 503, "Themenverwaltung nicht verfügbar.")
        values = {key: form.get(key, "").replace("\r\n", "\n") for key in LABELS if key != "mailboxes"}
        try:
            with self.store.locked():
                identity, state = self.prepare(session, form, values)
            return self.review(session, identity, state)
        except PermissionError:
            return self.site._reply(request, 403, "Sitzung nicht mehr gültig.")
        except ValidationError as error:
            errors = {str(item["loc"][0]): validation_message(item) for item in error.errors()}
            status = 422
        except TopicFieldError as error:
            errors, status = {error.field: str(error)}, error.status
        except (KeyError, ValueError):
            errors, status = {"__all__": "Ungültiges oder veraltetes Formular."}, 422
        except (OSError, CorruptState, yaml.YAMLError):
            errors, status = {"__all__": "Entwurf nicht gespeichert: Themendatei oder Ablage nicht lesbar."}, 503
        try:
            before, revision, _documents = self.context(form["kind"], form["original_id"])
            state = self.load(draft_id("web:" + session.id, form["kind"], form["original_id"]), "web:" + session.id)
        except (ValueError, KeyError, OSError, CorruptState, yaml.YAMLError):
            return self.site._reply(request, status, errors.get("__all__", "Themenangaben prüfen."))
        return self.form(session, form["kind"], form["original_id"], before, revision, state.version,
                         values, errors, status)

    def review(self, session: Any, identity: str, state: TopicDraft) -> Response:
        if state.topic is None:
            return self.site._reply(Request("GET", "/themen"), 422, "Kein gültiger Prüfentwurf; neu laden.")
        if state.before is not None and state.topic.model_dump() == state.before.model_dump():
            return Response.html(200, layout("Unverändert", '<div class="page-heading"><p class="eyebrow">'
                + KINDS[state.kind][2] + '</p><h1>Keine Änderung</h1><p>Es gibt nichts zu bestätigen.</p></div>'
                '<p><a href="/themen">Zur Themenübersicht</a></p>',
                active="/einstellungen"))
        before = state.before.model_dump(mode="json") if state.before is not None else None
        body = ('<div class="page-heading"><p class="eyebrow">' + KINDS[state.kind][2] + '</p>'
                '<h1>Änderung prüfen</h1><p>Bisherige und neue Regel im Vergleich. Gespeichert wird erst nach '
                f'Ihrer ausdrücklichen Bestätigung.</p></div><p>Themen-ID: <code>{e(state.topic.id)}</code></p>'
                + compare(before, state.topic.model_dump(mode="json")))
        body += '<form method="post" action="/themen/speichern" class="stack confirm-bar">'
        for key, value in {"csrf": self.site.auth.csrf_token(session.id), "key": state.key, "draft_id": identity,
                           "draft_version": state.version, "expected_hash": state.expected_hash}.items():
            body += field(key, "", value, hidden=True)
        href = topic_link(state.kind, state.original_id) if state.original_id else "/themen/" + state.kind + "/neu"
        body += ('<label><input type="checkbox" name="confirm" value="yes" required> '
                 'Änderung ausdrücklich speichern</label><button class="button">Änderung speichern</button></form>'
                 f'<p><a href="{href}">'
                 'Weiter bearbeiten</a></p>')
        return Response.html(200, layout("Änderung prüfen", body, active="/einstellungen"))

    def resume(self, request: Request, session: Any, identity: str) -> Response:
        try:
            state = self.load(identity, "web:" + session.id)
            return self.review(session, identity, state)
        except PermissionError:
            return self.site._reply(request, 403, "Kein eigener Entwurf.")
        except (OSError, CorruptState):
            return self.site._reply(request, 503, "Entwurf nicht lesbar.")

    def command(self, actor: str, state: TopicDraft, form: dict[str, str]) -> AdminCommand:
        self.check(actor)
        if state.topic is None or int(form["draft_version"]) != state.version or form["key"] != state.key:
            raise TopicFieldError("__all__", "Prüfentwurf inzwischen geändert; neu laden.", 409)
        if form.get("confirm") != "yes" or form["expected_hash"] != state.expected_hash:
            raise TopicFieldError("__all__", "Gezeigte Änderung ausdrücklich bestätigen.", 422)
        if state.before is not None and state.topic.model_dump() == state.before.model_dump():
            raise TopicFieldError("__all__", "Keine Änderung zu bestätigen.")
        return AdminCommand(kind=AdminKind.TOPICS, actor=actor, idempotency_key=state.key,
                            expected_hash=state.expected_hash, category=KINDS[state.kind][0],
                            patch=state.topic.model_dump(mode="json"), acknowledged=True)

    def confirm(self, request: Request, session: Any, form: dict[str, str]) -> Response:
        try:
            state = self.load(form["draft_id"], "web:" + session.id)
            command = self.command("web:" + session.id, state, form)
            existing = self.site.commands.existing(command)
            if existing is not None:
                return Response.redirect("/aktion/" + existing.id)
            self.archive.configuration.candidate(command)
            self.check("web:" + session.id)
            response: Response = self.archive.queue(request, command)
            return response
        except PermissionError:
            return self.site._reply(request, 403, "Sitzung oder Entwurf nicht gültig.")
        except (ConfigurationConflict, CommandConflict):
            return self.site._reply(request, 409, "Datei oder Befehl geändert; bitte neu laden.")
        except TopicFieldError as error:
            return self.site._reply(request, error.status, str(error))
        except (ValueError, KeyError):
            return self.site._reply(request, 422, "Ungültige Themenbestätigung.")
        except (OSError, CorruptState):
            return self.site._reply(request, 503, "Speichern unterbrochen; dieselbe Bestätigung erneut senden.")

    def drafts(self, actor: str) -> list[tuple[str, str, str, str]]:
        """Own previews still waiting for confirmation; a preview of an older file revision is stale."""
        found = []
        revisions = {kind: file_hash(self.archive.configuration.directory / filename)
                     for kind, (_category, filename, _title) in KINDS.items()}
        for name in self.store.names("topic-draft-"):
            try:
                state = self.load(name.removeprefix("topic-draft-"), actor)
                if state.topic is not None and state.expected_hash == revisions[state.kind]:
                    command = self.command(actor, state, {"draft_version": str(state.version), "key": state.key,
                        "expected_hash": state.expected_hash, "confirm": "yes"})
                    if self.site.commands.existing(command) is None:
                        found.append((name.removeprefix("topic-draft-"), KINDS[state.kind][0],
                                      state.topic.id, state.topic.name))
            except (PermissionError, CorruptState, TopicFieldError, CommandConflict):
                continue
        return found
