"""Authenticated learning pages; editing drafts never authorizes external writes."""

from __future__ import annotations

import json
import secrets
from decimal import Decimal
from typing import Any

from ..i18n import msg, tr
from ..runtime.learning_jobs import LearningConflict, LearningSelection
from ..usage.budget import decimal_of, limit_float, minimum_points, parse_points, points_to_usd, tokens_to_points
from ..usage.points import Valuation
from . import consumption
from .http import Response
from .labels import count_text
from .learning_pages import heading
from .learning_setup import setup_form
from .pages import e, layout, notice

# 8.7.4: what a customer sees instead of the money wording of the shared job texts.
CUSTOMER_MESSAGES = {
    "Angehalten: Budget, Sitzung oder Konfiguration prüfen.":
        msg("Angehalten: Punktegrenze, Sitzung oder Konfiguration prüfen."),
    "Budget reicht für den geschätzten Lauf nicht aus.":
        msg("Die Punktegrenze reicht für die Schätzung nicht aus."),
    "Auswahl gemeinsam gespeichert. Konfiguration neu laden.":
        msg("Auswahl gemeinsam gespeichert. Neue Analysen übernehmen die Themen am nächsten sicheren "
            "Verarbeitungspunkt, neue Abrufordner beim nächsten Start."),
}
CUSTOMER_KEYS = {"mailbox", "folders", "count", "points", "revision"}
NOT_SET_UP = msg("Lernen aus dem Postfach ist vom Betreiber noch nicht eingerichtet.")
REVALUED = msg("Bewertung geändert, bitte Schätzung prüfen.")

_REVIEW_TEXT_1 = msg(
    '<input type="hidden" name="name" value="{p0}"><label><input type="checkbox" '
    'name="selected"{p1}>{p2}</label><button class="button">Ordnerauswahl '
    "speichern</button>"
)

_REVIEW_TEXT_2 = msg(
    "<p>Alle gespeicherten Auswahlen gemeinsam übernehmen?</p><button "
    'class="button">Ausgewählte Themen, Filter und Ordner ausdrücklich übernehmen</button>'
)

_REVIEW_TEXT_3 = msg(
    '<h3>{p0}</h3><input type="hidden" name="index" value="{p1}"><label>Titel<input '
    'name="name" value="{p2}" required></label><label '
    'for="learning-description-{p3}">Beschreibung</label><textarea '
    'id="learning-description-{p4}" name="description" required>{p5}</textarea><label '
    'for="learning-kind-{p6}">Übernahme</label><select id="learning-kind-{p7}" '
    'name="kind">{p8}</select><label><input type="checkbox" name="global"{p9}>Für alle '
    'Postfächer</label><label><input type="checkbox" name="block_senders"{p10}>Absender '
    "bei Ausschlussthema ignorieren</label><ul>"
)

LABELS = {
    "empty": msg("Bereit"),
    "running": msg("Läuft"),
    "paused": msg("Pausiert"),
    "cancelled": msg("Abgebrochen"),
    "review": msg("Ergebnisse prüfen"),
    "committing": msg("Übernahme wird abgeschlossen"),
    "done": msg("Übernommen"),
}


class LearningSite:
    def __init__(self, site: Any, worker: Any) -> None:
        self.site, self.worker = site, worker
        self.jobs = worker.jobs
        site.learning_overview.worker = worker
        site.app.route("GET", "/lernen/postfach", site.signed_in(self.home))
        site.app.route("GET", "/api/lernen", site.signed_in(self.status))
        site.app.route("POST", "/lernen/postfach", site.signed_in(self.act))

    def form(self, session: Any, state: Any, action: Any, content: Any) -> str:
        return (
            '<form method="post" action="/lernen/postfach">'
            f'<input type="hidden" name="csrf" value="{e(self.site.auth.csrf_token(session.id))}">'
            f'<input type="hidden" name="version" value="{state.version}">'
            f'<input type="hidden" name="key" value="{secrets.token_hex(16)}">'
            f'<input type="hidden" name="action" value="{e(action)}">{content}</form>'
        )

    def customer(self, session: Any) -> bool:
        return not self.site.auth.is_operator(session)

    def priced(self) -> tuple[Valuation, Decimal] | None:
        """Valuation in force and the operator's price assumption; both are needed for points."""
        found = consumption.valuation(self.site.usage.meter, self.site.clock())
        price = self.site.learning_price
        return (found, price) if found is not None and price is not None else None

    def home(self, request: Any, session: Any) -> Response:
        state = self.jobs.state()
        customer = self.customer(session)
        content = heading(
            msg("Aus dem Postfach lernen"),
            msg(
                "Entdecke neue Themen in vorhandenen Mails. Prüfe erst Auswahl und Verbrauch, "
                "dann gib den lesenden Lauf ausdrücklich frei."
            ) if customer else msg(

                    "Entdecke neue Themen in vorhandenen Mails. Prüfe erst Auswahl und Kosten, "
                    "dann gib den lesenden Lauf ausdrücklich frei."

            ),
        ) + tr(
            '<p role="status">{p0}: {p1} geprüft, {p2} Fehler.</p>',
            p0=e(LABELS[state.status]),
            p1=count_text(state.cursor, "Mail", "Mails"),
            p2=state.failures,
        )
        message = CUSTOMER_MESSAGES.get(state.message, state.message) if customer else state.message
        content += notice(message) if message else ""
        stale = self.jobs.stale(state)
        if stale:
            content += notice(
                tr(
                    "Die Konfiguration wurde seit dem Start geändert. Dieser Lauf "
                    "kann nicht fortgesetzt werden; ein neuer Lernlauf ersetzt ihn."
                ),
                "warn",
            )
        if state.status in {"empty", "done", "cancelled", "review"} or stale:
            content += (self.customer_start_form(request, session, state) if customer
                        else self.start_form(request, session, state))
        actions = {
            "running": (("pause", msg("Pausieren")), ("cancel", "Abbrechen")),
            "paused": (
                (("cancel", "Abbrechen"),) if stale else (("resume", msg("Fortsetzen")), ("cancel", "Abbrechen"))
            ),
            "review": (("cancel", msg("Verwerfen")),),
        }.get(state.status, ())
        for action, label in actions:
            content += self.form(session, state, action, f'<button class="button">{label}</button>')
        if state.selection is not None:
            if not customer:
                cost = state.reserved_tokens * state.selection.usd_per_million_tokens / 1000000
                content += tr(
                    "<p>Reserviert: {p0} Tokens, {p1} USD des gewählten Budgets.</p>",
                    p0=state.reserved_tokens,
                    p1=f"{cost:.6f}",
                )
            content += self.points_usage(state, customer)
        if state.status == "review":
            content += self.review(session, state)
        if state.status == "done" and not customer:
            content += tr('<p><a class="button" href="/dienst/neu-laden">Konfiguration neu laden</a></p>')
        return Response.html(
            200,
            layout(
                msg("Lernmodus"),
                content,
                active="/lernen",
                refresh=3 if state.status == "running" else None,
                fingerprint=f"learning-{state.version}-{state.cursor}-{state.status}",
                state_url="/api/lernen",
            ),
        )

    def start_form(self, request: Any, session: Any, state: Any) -> str:
        content, query = setup_form(self.worker, request.query)
        if request.query and "prepare" not in query:
            try:
                selection = LearningSelection(
                    mailbox=int(query["mailbox"][0]),
                    count=int(query["count"][0]),
                    folders=list(dict.fromkeys(query.get("folder", [])
                                               + query.get("folders", [""])[0].splitlines())),
                    budget_usd=float(query["budget"][0]),
                    usd_per_million_tokens=float(query["price"][0]),
                )
                if selection.mailbox not in {box.id for box in self.worker.app.settings.imap.enabled_mailboxes()}:
                    raise ValueError("Postfach nicht verfügbar")
                tokens, ceiling = self.worker.estimate(selection), self.worker.maximum(selection)
                price = selection.usd_per_million_tokens / 1000000
                content += tr(
                    (
                        "<p>Auswahl: Postfach {p0}, {p1} Mails, Ordner "
                        "{p2}.</p><p>Typische Schätzung: {p3} Tokens, etwa {p4} USD zur "
                        "Preisannahme. Ungünstigster Fall (jede Mail an der Größengrenze, "
                        "alle Wiederholungen): {p5} Tokens, {p6} USD. Das Budget wird vor "
                        "jedem Aufruf geprüft; der Lauf hält an, bevor es überschritten "
                        "würde.</p>"
                    ),
                    p0=selection.mailbox,
                    p1=selection.count,
                    p2=e(", ".join(selection.folders)),
                    p3=tokens,
                    p4=f"{tokens * price:.6f}",
                    p5=ceiling,
                    p6=f"{ceiling * price:.6f}",
                )
                if tokens * price > selection.budget_usd:
                    # The start would be refused; say what is needed instead of offering the button.
                    content += notice(
                        tr(
                            (
                                "Das Budget reicht für die typische Schätzung nicht aus. Bitte "
                                "mindestens {p0} USD angeben."
                            ),
                            p0=f"{tokens * price:.6f}",
                        ),
                        "error",
                    )
                else:
                    content += self.form(
                        session,
                        state,
                        "start",
                        tr(
                            (
                                '<input type="hidden" name="selection" value="{p0}"><button '
                                'class="button">Lesenden Lernlauf kostenpflichtig starten</button>'
                            ),
                            p0=f"{e(selection.model_dump_json())}",
                        ),
                    )
            except (ValueError, KeyError):
                content += notice(tr("Angaben für die Schätzung prüfen."), "error")
        return content

    def points_usage(self, state: Any, customer: bool) -> str:
        """Reservation and actual usage in points; nothing while usage is not recorded."""
        limit = self.jobs.points(state)
        meter = self.site.usage.meter
        rated = consumption.valuation(meter, self.site.clock(), limit.revision if limit is not None else None)
        if rated is None:
            return ""
        assert meter is not None and state.selection is not None
        reserved = tokens_to_points(state.reserved_tokens, decimal_of(state.selection.usd_per_million_tokens), rated)
        text = consumption.reserved_text(reserved, int(limit.points) if limit is not None else None)
        text += " " + consumption.actual_text(consumption.learning_usage(meter, state.started_at))
        return f'<p class="{"" if customer else "meta"}">{e(text)}</p>'

    @staticmethod
    def selection(mailbox: int, folders: list[str], count: int, limit: int, rated: Valuation,
                  price: Decimal) -> LearningSelection:
        """The run's internal limits, computed on the server from the points limit."""
        return LearningSelection(mailbox=mailbox, folders=folders, count=count,
                                 budget_usd=limit_float(points_to_usd(limit, rated)),
                                 usd_per_million_tokens=float(price))

    def customer_start_form(self, request: Any, session: Any, state: Any) -> str:
        priced = self.priced()
        if priced is None:
            return notice(NOT_SET_UP, "warn")
        rated, price = priced
        content, query = setup_form(self.worker, request.query, customer=True)
        if request.query and "prepare" not in query:
            try:
                limit = parse_points(query["points"][0])
                folders = list(dict.fromkeys(query.get("folder", []) + query.get("folders", [""])[0].splitlines()))
                selection = self.selection(int(query["mailbox"][0]), folders, int(query["count"][0]), limit,
                                           rated, price)
                if selection.mailbox not in {box.id for box in self.worker.app.settings.imap.enabled_mailboxes()}:
                    raise ValueError("Postfach nicht verfügbar")
                tokens, ceiling = self.worker.estimate(selection), self.worker.maximum(selection)
                content += tr("<p>Auswahl: Postfach {p0}, {p1} Mails, Ordner {p2}.</p>", p0=selection.mailbox,
                              p1=selection.count, p2=e(", ".join(selection.folders)))
                content += "<p>" + e(consumption.estimate_text(tokens_to_points(tokens, price, rated),
                                                               tokens_to_points(ceiling, price, rated)))
                content += " " + tr("Die Punktegrenze wird vor jedem Aufruf geprüft; der Lauf hält an, bevor sie "
                                    "überschritten würde.") + "</p>"
                needed = minimum_points(tokens, price, rated)
                if limit < needed:
                    content += notice(tr("Die Punktegrenze reicht für die Schätzung nicht aus. Bitte mindestens "
                                         "{p0} angeben.", p0=consumption.points_text(Decimal(needed))), "error")
                else:
                    chosen = {"mailbox": selection.mailbox, "folders": selection.folders, "count": selection.count,
                              "points": str(limit), "revision": rated.revision}
                    content += self.form(session, state, "start", tr(
                        '<input type="hidden" name="selection" value="{p0}"><button class="button">'
                        "Lesenden Lernlauf starten (verbraucht Punkte)</button>",
                        p0=e(json.dumps(chosen, ensure_ascii=False))))
            except (ValueError, KeyError):
                content += notice(tr("Angaben für die Schätzung prüfen."), "error")
        return content

    def customer_payload(self, raw: str) -> tuple[dict[str, Any], tuple[int, int]]:
        """Only mailbox, folders, count, points and revision; any money field refuses the whole start."""
        data = json.loads(raw)
        if (not isinstance(data, dict) or set(data) != CUSTOMER_KEYS or type(data["points"]) is not str
                or type(data["revision"]) is not int):
            raise ValueError("Ungültige Auswahl")
        priced = self.priced()
        if priced is None:
            raise LearningConflict(NOT_SET_UP)
        rated, price = priced
        if data["revision"] != rated.revision:
            raise LearningConflict(REVALUED)
        limit = parse_points(data["points"])
        payload = {"mailbox": data["mailbox"], "folders": data["folders"], "count": data["count"],
                   "budget_usd": limit_float(points_to_usd(limit, rated)), "usd_per_million_tokens": float(price)}
        return payload, (limit, rated.revision)

    def review(self, session: Any, state: Any) -> str:
        content = tr("<h2>Themen, Ausschlüsse und Belege</h2>")
        for index, card in enumerate(state.cards):
            choice = state.choices.get(str(index), {})
            kind = choice.get("kind", "skip")
            options = "".join(
                f'<option value="{value}"{" selected" if kind == value else ""}>{label}</option>'
                for value, label in (
                    ("skip", msg("Nicht übernehmen")),
                    ("relevant", msg("Thema")),
                    ("irrelevant", msg("Ausschlussthema")),
                )
            )
            body = (
                tr(
                    (_REVIEW_TEXT_3),
                    p0=e(card.category.name),
                    p1=index,
                    p2=e(choice.get("name", card.category.name)),
                    p3=index,
                    p4=index,
                    p5=e(choice.get("description", card.category.description)),
                    p6=index,
                    p7=index,
                    p8=options,
                    p9=" checked" if choice.get("global") else "",
                    p10=" checked" if choice.get("block_senders") else "",
                )
                + "".join(f"<li>{e(item)}</li>" for item in card.evidence)
                + tr(
                    ('</ul><p>Absender: {p0}</p><button class="button">Auswahl als Entwurf speichern</button>'),
                    p0=e(", ".join(card.senders)),
                )
            )
            content += '<section class="card">' + self.form(session, state, "edit", body) + "</section>"
        content += tr("<h2>Zusätzliche Abrufordner</h2>")
        for name, selected in state.folders.items():
            content += self.form(
                session,
                state,
                "folder",
                tr(
                    (_REVIEW_TEXT_1),
                    p0=e(name),
                    p1=" checked" if selected else "",
                    p2=e(name),
                ),
            )
        return content + self.form(
            session,
            state,
            "apply",
            tr(_REVIEW_TEXT_2),
        )

    def status(self, request: Any, session: Any) -> Response:
        state = self.jobs.state()
        return Response.json(200, {"fingerprint": f"learning-{state.version}-{state.cursor}-{state.status}"})

    def act(self, request: Any, session: Any, form: Any) -> Response:
        customer = self.customer(session)
        limit = None
        try:
            action = form["action"]
            payload: dict[str, Any] = {}
            if action == "start" and customer:
                payload, limit = self.customer_payload(form["selection"])
            elif action == "start":
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
            self.jobs.change("web:" + session.id, int(form["version"]), form["key"], action, payload, limit)
        except LearningConflict as exc:
            # The reason is one of Mailhelp's own fixed texts, never mail content.
            reason = str(exc)
            return self._rejected(type(exc).__name__, CUSTOMER_MESSAGES.get(reason, reason) if customer else reason)
        except (ValueError, KeyError, TypeError) as exc:
            return self._rejected(type(exc).__name__, msg("Auswahl ungültig oder inzwischen geändert."))
        return Response.redirect("/lernen/postfach")

    def _rejected(self, error_class: str, reason: str) -> Response:
        self.site.logger.event("WARNING", "learning", "action_rejected", error_class=error_class, reason=reason)
        return Response.html(
            409,
            layout(
                tr("Lernstand prüfen"),
                notice(reason, "error") + tr('<p><a href="/lernen/postfach">Lernlauf neu laden</a></p>'),
                active="/lernen",
            ),
        )
