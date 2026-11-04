"""Authenticated learning pages; editing drafts never authorizes external writes."""

from __future__ import annotations

import json
import secrets
from typing import Any
from urllib.parse import parse_qs

from ..runtime.learning_jobs import LearningConflict, LearningSelection
from .http import Response
from .pages import e, layout, notice

LABELS = {
    "empty": "Bereit",
    "running": "Läuft",
    "paused": "Pausiert",
    "cancelled": "Abgebrochen",
    "review": "Ergebnisse prüfen",
    "committing": "Übernahme wird abgeschlossen",
    "done": "Übernommen",
}


class LearningSite:
    def __init__(self, site: Any, worker: Any) -> None:
        self.site, self.worker = site, worker
        self.jobs = worker.jobs
        site.app.route("GET", "/lernen", site.signed_in(self.home))
        site.app.route("GET", "/api/lernen", site.signed_in(self.status))
        site.app.route("POST", "/lernen", site.signed_in(self.act))

    def form(self, session: Any, state: Any, action: Any, content: Any) -> str:
        return (
            '<form method="post" action="/lernen">'
            f'<input type="hidden" name="csrf" value="{e(self.site.auth.csrf_token(session.id))}">'
            f'<input type="hidden" name="version" value="{state.version}">'
            f'<input type="hidden" name="key" value="{secrets.token_hex(16)}">'
            f'<input type="hidden" name="action" value="{e(action)}">{content}</form>'
        )

    def home(self, request: Any, session: Any) -> Response:
        state = self.jobs.state()
        content = (
            "<h1>Lernmodus</h1>"
            f'<p role="status">{e(LABELS[state.status])}: {state.cursor} Mails geprüft, {state.failures} Fehler.</p>'
        )
        content += notice(state.message) if state.message else ""
        if state.status in {"empty", "done", "cancelled", "review"}:
            content += self.start_form(request, session, state)
        actions = {
            "running": (("pause", "Pausieren"), ("cancel", "Abbrechen")),
            "paused": (("resume", "Fortsetzen"), ("cancel", "Abbrechen")),
            "review": (("cancel", "Verwerfen"),),
        }.get(state.status, ())
        for action, label in actions:
            content += self.form(session, state, action, f'<button class="button">{label}</button>')
        if state.selection is not None:
            cost = state.reserved_tokens * state.selection.usd_per_million_tokens / 1000000
            content += f"<p>Reserviert: {state.reserved_tokens} Tokens, {cost:.6f} USD des gewählten Budgets.</p>"
        if state.status == "review":
            content += self.review(session, state)
        if state.status == "done":
            content += '<p><a class="button" href="/dienst/neu-laden">Konfiguration neu laden</a></p>'
        return Response.html(
            200,
            layout(
                "Lernmodus",
                content,
                active="/lernen",
                refresh=3 if state.status == "running" else None,
                fingerprint=f"learning-{state.version}-{state.cursor}-{state.status}",
                state_url="/api/lernen",
            ),
        )

    def start_form(self, request: Any, session: Any, state: Any) -> str:
        boxes = self.worker.app.settings.imap.enabled_mailboxes()
        options = "".join(f'<option value="{box.id}">{e(box.label)}</option>' for box in boxes)
        content = (
            '<h2>Neuer Lernlauf</h2><form method="get" action="/lernen">'
            '<label for="learning-mailbox">Postfach</label>'
            f'<select id="learning-mailbox" name="mailbox">{options}</select>'
            '<label for="learning-folders">Ordner (ein Name je Zeile)</label>'
            '<textarea id="learning-folders" name="folders" required>INBOX</textarea>'
            '<label>Anzahl Mails<input name="count" type="number" min="1" max="1000" value="20" required></label>'
            '<label>Preisobergrenze USD je Million Tokens<input name="price" type="number" min="0.000001" '
            'step="any" required></label><label>Budget USD<input name="budget" type="number" min="0.000001" '
            'step="any" required></label><button class="button">Schätzung anzeigen</button></form>'
            "<p>Aktuelle Modellpreise einschließlich Ausgabe und Reasoning selbst prüfen. "
            "Die Preisobergrenze ist Ihre Annahme; Anbieterabrechnungen können abweichen. "
            "Gelesen wird ohne Änderung am Postfach. Es entstehen keine Termine oder Aufgaben.</p>"
        )
        catalog = self.jobs.store.load("mailbox-folders", {}).get("mailboxes", {})
        for box in boxes:
            names = [entry["name"] for entry in catalog.get(str(box.id), {}).get("folders", [])]
            content += f"<p>{e(box.label)} – verfügbare Ordner: {e(', '.join(names or box.folders))}</p>"
        if request.query:
            try:
                query = parse_qs(request.query, max_num_fields=10)
                selection = LearningSelection(
                    mailbox=int(query["mailbox"][0]),
                    count=int(query["count"][0]),
                    folders=query["folders"][0].splitlines(),
                    budget_usd=float(query["budget"][0]),
                    usd_per_million_tokens=float(query["price"][0]),
                )
                tokens = self.worker.estimate(selection)
                cost = tokens * selection.usd_per_million_tokens / 1000000
                content += (
                    f"<p>Auswahl: Postfach {selection.mailbox}, {selection.count} Mails, "
                    f"Ordner {e(', '.join(selection.folders))}.</p>"
                )
                content += f"<p>Konservative Schätzung: {tokens} Tokens, höchstens {cost:.6f} USD zur Preisannahme.</p>"
                content += self.form(
                    session,
                    state,
                    "start",
                    f'<input type="hidden" name="selection" value="{e(selection.model_dump_json())}">'
                    '<button class="button">Lesenden Lernlauf kostenpflichtig starten</button>',
                )
            except (ValueError, KeyError):
                content += notice("Angaben für die Schätzung prüfen.", "error")
        return content

    def review(self, session: Any, state: Any) -> str:
        content = "<h2>Themen, Ausschlüsse und Belege</h2>"
        for index, card in enumerate(state.cards):
            choice = state.choices.get(str(index), {})
            kind = choice.get("kind", "skip")
            options = "".join(
                f'<option value="{value}"{" selected" if kind == value else ""}>{label}</option>'
                for value, label in (
                    ("skip", "Nicht übernehmen"),
                    ("relevant", "Thema"),
                    ("irrelevant", "Ausschlussthema"),
                )
            )
            body = (
                f'<h3>{e(card.category.name)}</h3><input type="hidden" name="index" value="{index}">'
                f'<label>Titel<input name="name" value="{e(choice.get("name", card.category.name))}" required></label>'
                f'<label for="learning-description-{index}">Beschreibung</label>'
                f'<textarea id="learning-description-{index}" name="description" required>'
                f"{e(choice.get('description', card.category.description))}</textarea>"
                f'<label for="learning-kind-{index}">Übernahme</label>'
                f'<select id="learning-kind-{index}" name="kind">{options}</select>'
                f'<label><input type="checkbox" name="global"{" checked" if choice.get("global") else ""}>'
                'Für alle Postfächer</label><label><input type="checkbox" name="block_senders"'
                f"{' checked' if choice.get('block_senders') else ''}>Absender bei Ausschlussthema ignorieren</label>"
                "<ul>" + "".join(f"<li>{e(item)}</li>" for item in card.evidence) + "</ul>"
                f'<p>Absender: {e(", ".join(card.senders))}</p>'
                '<button class="button">Auswahl als Entwurf speichern</button>'
            )
            content += '<section class="card">' + self.form(session, state, "edit", body) + "</section>"
        content += "<h2>Zusätzliche Abrufordner</h2>"
        for name, selected in state.folders.items():
            content += self.form(
                session,
                state,
                "folder",
                f'<input type="hidden" name="name" value="{e(name)}">'
                f'<label><input type="checkbox" name="selected"{" checked" if selected else ""}>{e(name)}</label>'
                '<button class="button">Ordnerauswahl speichern</button>',
            )
        return content + self.form(
            session,
            state,
            "apply",
            "<p>Alle gespeicherten Auswahlen gemeinsam übernehmen?</p>"
            '<button class="button">Ausgewählte Themen, Filter und Ordner ausdrücklich übernehmen</button>',
        )

    def status(self, request: Any, session: Any) -> Response:
        state = self.jobs.state()
        return Response.json(200, {"fingerprint": f"learning-{state.version}-{state.cursor}-{state.status}"})

    def act(self, request: Any, session: Any, form: Any) -> Response:
        try:
            action = form["action"]
            payload = {}
            if action == "start":
                payload = json.loads(form["selection"])
            elif action == "edit":
                payload = {
                    "index": int(form["index"]),
                    "kind": form["kind"],
                    "name": form["name"],
                    "description": form["description"],
                    "global": "global" in form,
                    "block_senders": "block_senders" in form,
                }
            elif action == "folder":
                payload = {"name": form["name"], "selected": "selected" in form}
            self.jobs.change("web:" + session.id, int(form["version"]), form["key"], action, payload)
        except (ValueError, KeyError, TypeError, LearningConflict) as exc:
            self.site.logger.event("WARNING", "learning", "action_rejected", error_class=type(exc).__name__)
            return Response.html(
                409,
                layout(
                    "Lernstand prüfen",
                    notice("Auswahl ungültig oder inzwischen geändert.", "error")
                    + '<p><a href="/lernen">Lernlauf neu laden</a></p>',
                ),
            )
        return Response.redirect("/lernen")
