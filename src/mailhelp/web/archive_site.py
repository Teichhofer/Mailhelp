"""Authenticated archive, configuration, deterministic editing and stop pages."""
from __future__ import annotations

import json
import secrets
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from urllib.parse import parse_qs, urlencode

import yaml
from pydantic import ValidationError

from ..configuration import AdminCommand, AdminKind, ConfigurationConflict, LIVE_FIELDS, SETTINGS_FIELDS, file_hash
from ..models import MailState, Proposal, ProposalStatus
from ..review.commands import CommandKind, CommandSource, ReviewCommand
from ..review.editing import ProposalEditPatch
from ..review.inbox import CommandConflict, CommandInboxFull
from ..review.queries import ArchiveQueries, ArchiveQuery
from ..review.archive import AnalysisSnapshot
from ..storage import CorruptState
from .http import Response
from .pages import e, layout, notice
from .review_pages import detail_page


EDIT_LABELS = {"title": "Titel", "description": "Beschreibung", "target": "Ziel", "due": "Frist",
               "start": "Beginn", "end": "Ende", "all_day": "Ganztägig (true/false)", "location": "Ort",
               "video_link": "Videolink (HTTPS)"}
SETTING_LABELS = {"poll_interval_seconds": "Abrufintervall (Sekunden)", "timezone": "Zeitzone",
                  "test_mode": "Trockenlauf", "limits.llm_calls_per_minute": "KI-Aufrufe pro Minute",
                  "limits.max_mail_bytes": "Maximale Mailgröße (Bytes)",
                  "limits.max_llm_payload_bytes": "Maximale KI-Anfragegröße (Bytes)",
                  "retention.full_mail_days": "Mailtexte aufbewahren (Tage)",
                  "retention.debug_llm_days": "KI-Diagnosedaten aufbewahren (Tage)",
                  "retention.analysis_days": "Analysen aufbewahren (Tage)",
                  "retention.history_days": "Verlauf aufbewahren (Tage)",
                  "metrics.ollama_power_watts": "Ollama-Leistung (Watt)",
                  "metrics.electricity_eur_per_kwh": "Strompreis (EUR/kWh)",
                  "metrics.retention_days": "Einzelmessungen aufbewahren (Tage)",
                  "metrics.enabled": "Metrikerfassung aktivieren"}


MODE_LABELS = {"production": "Betrieb (Standard und Ollama)", "standard": "Betrieb mit Standard-KI",
               "local": "Betrieb mit Ollama", "decision_test": "Vergleichsläufe (Decision-Tests)"}
PERIODS = ((1, "Heute (24 Std.)"), (7, "7 Tage"), (30, "30 Tage"), (90, "90 Tage"))


def _number(value: object, digits: int = 2) -> str:
    """German number format; callers show missing figures as "—" or "unbekannt"."""
    return f"{float(value):,.{digits}f}".replace(",", " ").replace(".", ",").replace(" ", ".")


def _money(value: object, currency: str) -> str:
    return "unbekannt" if value is None else f"{_number(value, 4)} {currency}"


def select(name: str, label: str, value: object, options: list[tuple[object, str]]) -> str:
    rendered = "".join(f'<option value="{e(key)}"{" selected" if str(key) == str(value) else ""}>{e(text)}</option>'
                       for key, text in options)
    return f'<label>{e(label)}<select name="{e(name)}">{rendered}</select></label>'


def statistics_page(params: dict, report: dict, everything: list[dict]) -> str:
    """Costs and durations with readable labels; unknown values are never shown as zero."""
    def choices(key: str) -> list[tuple[str, str]]:
        return [("", "alle")] + [(value, value) for value in sorted({row[key] for row in everything})]

    form = ('<form method="get" class="filters">'
            + select("days", "Zeitraum", params["days"], list(PERIODS))
            + select("mode", "Erfassung", params["mode"], list(MODE_LABELS.items()))
            + select("model", "Modell", params.get("model", ""), choices("model"))
            + select("provider", "Anbieter", params.get("provider", ""), choices("provider"))
            + select("stage", "Verarbeitungsschritt", params.get("stage", ""), choices("stage"))
            + f'<label>Von<input type="date" name="since" value="{e(params.get("since", ""))}"></label>'
            + f'<label>Bis<input type="date" name="until" value="{e(params.get("until", ""))}"></label>'
            + '<button class="button primary">Auswerten</button></form>')
    rate = report["exchange_rate_date"]
    rows = [
        ("Aufrufe (einzelne Versuche)", str(report["count"])),
        ("davon fehlgeschlagen", str(report["failed"])),
        ("Gemeldete Cloudkosten", _money(report["usd"], "USD")),
        ("Cloudaufrufe ohne Kostenangabe", str(report["unknown_cost"])),
        ("Cloudkosten in Euro", _money(report["cloud_eur"], "EUR") + (f" (Wechselkurs vom {rate})" if rate else "")
         if report["cloud_eur"] is not None else "kein Wechselkurs hinterlegt"),
        ("Geschätzte Stromkosten Ollama", _money(report["electricity_eur"], "EUR")),
        ("Summierte Aufrufdauer", f'{_number(report["seconds"], 1)} s'),
        ("Dauer je Aufruf (Mittel / Median / 95 %)",
         " / ".join(f"{_number(report[key], 2)} s" if report[key] is not None else "—"
                    for key in ("mean", "median", "p95"))),
    ]
    if report["damaged"] or report["capture_failures"]:
        rows.append(("Unvollständige Erfassung",
                     f'{report["damaged"]} beschädigte Zeilen, {report["capture_failures"]} Erfassungsfehler'))
    body = ("<h1>Kosten und Zeiten</h1>" + form
            + '<dl class="facts-table">' + "".join(f"<dt>{e(k)}</dt><dd>{e(v)}</dd>" for k, v in rows) + "</dl>"
            + '<p class="meta">Kosten in USD stammen aus den Angaben des Anbieters; fehlt eine Angabe, ist sie '
              "unbekannt, nicht null. Stromkosten sind eine Schätzung aus der eingestellten Leistung und dem "
              "Strompreis (überlappende Aufrufe einmal gezählt); Leerlauf, Hardware und andere Serverlast sind "
              "nicht enthalten. Die summierte Aufrufdauer ist keine Durchlaufzeit.</p>")
    if report["groups"]:
        body += ('<h2>Nach Modell und Schritt</h2><div class="table-scroll"><table><thead><tr>'
                 "<th>Modell</th><th>Schritt</th><th>Anbieter</th><th>Aufrufe</th><th>Fehler</th>"
                 "<th>Summe</th><th>Median</th><th>95 %</th><th>USD</th></tr></thead><tbody>")
        for group in report["groups"]:
            body += (f'<tr><td>{e(group["model"])}</td><td>{e(group["stage"])}</td><td>{e(group["provider"])}</td>'
                     f'<td>{group["count"]}</td><td>{group["failed"]}</td><td>{_number(group["seconds"], 1)} s</td>'
                     f'<td>{_number(group["median"], 2)} s</td><td>{_number(group["p95"], 2)} s</td>'
                     f'<td>{_number(group["usd"], 4)}</td></tr>')
        body += "</tbody></table></div>"
    else:
        body += '<p class="empty">Für diese Auswahl gibt es keine erfassten Aufrufe.</p>'
    return body


def field(name: str, label: str, value: object = "", *, hidden: bool = False) -> str:
    if hidden:
        return f'<input type="hidden" name="{e(name)}" value="{e(value)}">'
    return (f'<label>{e(label)}<input type="text" name="{e(name)}" value="{e(value)}" '
            'maxlength="4000"></label>')


def post_form(action: str, csrf: str, body: str, label: str = "Speichern", **hidden) -> str:
    inputs = field("csrf", "", csrf, hidden=True) + field("key", "", secrets.token_hex(16), hidden=True)
    inputs += "".join(field(name, "", value, hidden=True) for name, value in hidden.items())
    return f'<form method="post" action="{e(action)}" class="stack">{inputs}{body}<button class="button">{e(label)}</button></form>'


class ArchiveSite:
    def __init__(self, site, configuration=None, metrics=None, lifecycle=None, models=None):
        self.site, self.configuration, self.metrics, self.lifecycle = site, configuration, metrics, lifecycle
        self.models = models or {}
        self.queries = ArchiveQueries(site.views.store, site.configured_timezone)
        routes = [("GET", "/mails", self.mails), ("GET", "/verlauf", self.history),
                  ("GET", "/auswertung", self.statistics), ("GET", "/einstellungen", self.settings),
                  ("POST", "/einstellungen/speichern", self.save_settings),
                  ("GET", "/themen", self.topics), ("POST", "/themen/speichern", self.save_topic),
                  ("GET", "/einstellungen/beenden", self.stop_page),
                  ("POST", "/einstellungen/beenden", self.stop),
                  ("GET", r"/vorschlag/(?P<mail_id>[a-f0-9]{24})/(?P<proposal_id>[A-Za-z0-9_-]{1,64})/version/(?P<version>[1-9][0-9]{0,5})", self.version),
                  ("GET", r"/vorschlag/(?P<mail_id>[a-f0-9]{24})/(?P<proposal_id>[A-Za-z0-9_-]{1,64})/bearbeiten", self.edit),
                  ("POST", r"/vorschlag/(?P<mail_id>[a-f0-9]{24})/(?P<proposal_id>[A-Za-z0-9_-]{1,64})/bearbeiten", self.save_edit)]
        for method, path, handler in routes:
            site.app.route(method, path, site.signed_in(handler))

    def parameters(self, request):
        values = parse_qs(request.query, max_num_fields=20)
        if any(len(value) != 1 for value in values.values()):
            raise ValueError("Doppelte Filter")
        return {key: value[0] for key, value in values.items()}

    def mails(self, request, session):
        try:
            query = ArchiveQuery.model_validate(self.parameters(request))
        except ValueError:
            return self.site._reply(request, 422, "Ungültige Suche oder Filter.")
        items, total = self.queries.search(query)
        fields = "".join(field(key, label, getattr(query, key) or "") for key, label in
                         (("q", "Suche: Absender, Betreff, Zusammenfassung"), ("relevance", "Relevanz"),
                          ("topic", "Themen-ID"), ("state", "Verarbeitung"), ("status", "Vorschlagsstatus"),
                          ("since", "Von (JJJJ-MM-TT)"), ("until", "Bis (JJJJ-MM-TT)")))
        rows = "".join(f'<li class="card"><a href="/mail/{e(item["id"])}">{e(item["subject"])}</a>'
                       f'<p>{e(item["sender"])} · {e(item["received"] or "Empfangszeit unbekannt")}</p>'
                       f'<p>{e(item["relevance"])} · {e(", ".join(item["topics"]))}</p>'
                       f'<p>{e(item["summary"])}</p></li>' for item in items)
        pages = []
        for number in (query.page - 1, query.page + 1):
            if 1 <= number <= max(1, (total + query.size - 1) // query.size):
                parameters = query.model_dump(mode="json", exclude_none=True)
                parameters["page"] = number
                parameters = {k: v for k, v in parameters.items() if v != ""}
                pages.append(f'<a class="button" href="/mails?{e(urlencode(parameters))}">Seite {number}</a>')
        body = f'<h1>Mails</h1><form method="get" class="stack">{fields}<button class="button">Suchen</button></form>'
        body += f'<p>{total} gespeicherte Vorgänge · Seite {query.page}</p><ul class="archive-list">{rows}</ul>'
        body += " ".join(pages) + notice(f"Beschädigte Datensätze: {self.queries.damaged}. Nur lokal gespeicherte Mails werden angezeigt.", "info")
        return Response.html(200, layout("Mails", body, active="/mails"))

    def analysis(self, mail_id):
        store = self.site.views.store
        try:
            state = store.peek_model(f"mail-{mail_id}", MailState)
            snapshot = store.peek_model(f"analysis-{mail_id}", AnalysisSnapshot)
            record = snapshot.model_dump(mode="json") if snapshot is not None else {}
        except CorruptState:
            return notice("Analyse beschädigt; bitte Protokolle prüfen.", "error")
        if state is None:
            return ""
        relevance = {} if record.get("removed") else record.get("relevance") or (state.relevance.model_dump(mode="json") if state.relevance else {})
        summary = {} if record.get("removed") else record.get("summary") or (state.summary.model_dump(mode="json") if state.summary else {})
        text = " ".join(summary.get("sentences", []))
        if not text:
            text = "Nicht erforderlich (irrelevant)." if relevance.get("decision") == "irrelevant" else "Nicht vorhanden, noch nicht erstellt oder nach Aufbewahrung entfernt."
        human = state.relevance_dialog.decision if state.relevance_dialog else None
        topics = record.get("topics", {})
        names = [topics.get(identifier, identifier) for identifier in relevance.get("topic_ids", [])]
        body = f'<section class="card"><h2>Zusammenfassung</h2><p>{e(text)}</p>'
        body += f'<p>Fristen: {e("; ".join(summary.get("deadlines", [])))}</p><h2>Relevanz und Themen</h2>'
        body += f'<p>Modellbewertung: {e(relevance.get("decision", "unbekannt"))} · Quelle: {e(record.get("source", "unbekannt"))}</p>'
        body += f'<p>{e(relevance.get("reason", "Keine Begründung mehr verfügbar"))}</p><p>Themen: {e(", ".join(names))}</p>'
        body += f'<p>Menschliche Entscheidung: {e(human or "keine")}</p><h2>Erkannte Aktionen</h2><ul>'
        body += "".join(f'<li><a href="/vorschlag/{mail_id}/{e(p.id)}">{e(p.title)}</a> · {e(p.status.value)}</li>' for p in state.proposals)
        return body + f'</ul><a class="button" href="/verlauf?q={mail_id}">Verlauf dieser Mail</a></section>'

    def history(self, request, session):
        try:
            params = self.parameters(request)
            query = ArchiveQuery.model_validate(params)
        except ValueError:
            return self.site._reply(request, 422, "Ungültige Verlaufsfilter.")
        rows = []
        store = self.site.views.store
        for row in self.queries.history():
            if query.q and query.q.casefold() not in (row["mail_id"] + row["title"]).casefold():
                continue
            day = datetime.fromisoformat(row["at"]).astimezone(ZoneInfo(self.site.configured_timezone)).date().isoformat()
            if query.since and day < query.since.isoformat() or query.until and day > query.until.isoformat():
                continue
            if query.status and str(query.status) != row["status"]:
                continue
            if query.kind and query.kind != row["kind"]:
                continue
            if query.proposal_kind and query.proposal_kind != row["proposal_kind"]:
                continue
            rows.append(row)
        rows.sort(key=lambda row: row["at"], reverse=True)
        total = len(rows)
        rows = rows[(query.page - 1)*query.size:query.page*query.size]
        body = '<h1>Verlauf</h1><form method="get" class="stack">' + field("q", "Betreff, Absender oder Mail-ID", query.q)
        body += field("status", "Vorschlagsstatus", query.status or "") + field("kind", "Ereignisart", query.kind) + field("proposal_kind", "Aufgabe (task) oder Termin (event)", query.proposal_kind) + field("since", "Von", query.since or "") + field("until", "Bis", query.until or "")
        body += '<button class="button">Filtern</button></form>' + f'<p>{total} Ereignisse · Seite {query.page}</p><ul class="archive-list">'
        for row in rows:
            link = (f'/vorschlag/{row["mail_id"]}/{row["proposal_id"]}/version/{row["version"]}'
                    if row["proposal_id"] else f'/mail/{row["mail_id"]}')
            body += f'<li class="card"><a href="{e(link)}">{e(row["title"])}</a><p>{e(row["at"])} · {e(row["status"])} · {e(row["source"])} · Version {e(row["version"])}</p></li>'
        body += '</ul>'
        if query.page > 1:
            params["page"] = query.page - 1
            body += f'<a class="button" href="/verlauf?{e(urlencode(params))}">Vorherige Seite</a>'
        if query.page * query.size < total:
            params["page"] = query.page + 1
            body += f'<a class="button" href="/verlauf?{e(urlencode(params))}">Weitere Ereignisse</a>'
        return Response.html(200, layout("Verlauf", body, active="/verlauf"))

    def version(self, request, session, mail_id, proposal_id, version):
        history = self.site.views.store.peek(f"history-{mail_id}", {})
        if history.get("removed"):
            return self.site._reply(request, 404, "Historische Inhalte nach Aufbewahrung entfernt.")
        view = self.site.views.proposal(mail_id, proposal_id, int(version))
        if view is None:
            return self.site._reply(request, 404, "Version nicht mehr vorhanden.")
        page = detail_page(view)
        previous = self.site.views.store.peek_model(f"proposal-{mail_id}-{proposal_id}-v{int(version)-1}", Proposal)
        current = self.site.views.store.peek_model(f"proposal-{mail_id}-{proposal_id}-v{version}", Proposal)
        diff = '<section class="card"><h2>Änderungen gegenüber vorheriger Version</h2>'
        if previous is None:
            diff += '<p>Vorherige Version nicht vorhanden.</p>'
        else:
            before, after = previous.model_dump(mode="json"), current.model_dump(mode="json")
            diff += '<dl>' + ''.join(f'<dt>{e(key)}</dt><dd>{e(before[key])} → {e(after[key])}</dd>'
                                    for key in ('title', 'description', 'target', 'due', 'start', 'end', 'all_day', 'location', 'video_link', 'status', 'open_questions') if before[key] != after[key]) + '</dl>'
        page = page.replace('</main>', diff + '</section></main>')
        return Response.html(200, page.replace('</main>', '<p>Historische Version – ausschließlich lesend.</p></main>'))

    def edit(self, request, session, mail_id, proposal_id, values=None, message=""):
        proposal = self.site.views.store.peek_model(f"proposal-{mail_id}-{proposal_id}", Proposal)
        if proposal is None:
            return self.site._reply(request, 404, "Vorschlag nicht gefunden.")
        if proposal.status not in {ProposalStatus.PENDING_CONFIRMATION, ProposalStatus.NEEDS_CLARIFICATION}:
            return self.site._reply(request, 409, "Nur offene Vorschläge sind bearbeitbar.")
        names = ["title", "description", "target"] + (["due"] if proposal.kind.value == "task" else
                 ["start", "end", "all_day", "location", "video_link"])
        data = values if values is not None else proposal.model_dump(mode="json")
        body = '<h1>Vorschlag bearbeiten</h1><p>Zeiten als ISO-Datum oder ISO-Datum mit Uhrzeit eingeben. Bei Zeitumstellungen UTC-Offset angeben. Speichern legt nichts extern an.</p>'
        body += notice(message, "warn") if message else ""
        inputs = "".join(field(name, EDIT_LABELS[name], data.get(name) or "") for name in names)
        body += post_form(request.path, self.site.auth.csrf_token(session.id), inputs, version=proposal.version)
        return Response.html(422 if message else 200, layout("Bearbeiten", body))

    def save_edit(self, request, session, form, mail_id, proposal_id):
        try:
            raw = {key: value for key, value in form.items() if key not in {"csrf", "key", "version"}}
            if "all_day" in raw:
                raw["all_day"] = {"true": True, "false": False, "": False}[raw["all_day"].lower()]
            patch = ProposalEditPatch.model_validate(raw)
            command = ReviewCommand(kind=CommandKind.EDIT, source=CommandSource.WEB, actor=f"web:{session.id}",
                                    idempotency_key=form["key"], mail_id=mail_id, proposal_id=proposal_id,
                                    version=int(form["version"]), patch=patch)
        except (ValueError, KeyError):
            return self.edit(request, session, mail_id, proposal_id, form, "Ungültige Eingaben; bitte prüfen.")
        stale = self.site._stale(command)
        if stale is not None and not any(entry.command == command for entry in self.site.commands._entries()):
            return self.site._reply(request, 409, stale)
        return self.queue(request, command)

    def queue(self, request, command):
        try:
            entry, _ = self.site.commands.submit(command)
        except (CommandConflict, CommandInboxFull):
            return self.site._reply(request, 409, "Bereits anders eingereicht oder Warteschlange voll.")
        return Response.redirect(f"/aktion/{entry.id}")

    def settings(self, request, session):
        body = '<h1>Einstellungen</h1><p><a href="/themen">Themen verwalten</a> · <a href="/geraete">Geräte verwalten</a> · <a href="/einstellungen/beenden">Mailhelp beenden</a></p>'
        body += '<h2>Aktive Modelle</h2><ul>' + "".join(f'<li>{e(k)}: {e(v)}</li>' for k, v in self.models.items()) + '</ul>'
        if self.configuration is None:
            return Response.html(200, layout("Einstellungen", body + notice("Konfigurationsdienst nicht verfügbar.", "warn")))
        raw = yaml.safe_load((self.configuration.directory / "config.yaml").read_text(encoding="utf-8"))
        active = self.configuration.active.model_dump(mode="json")
        revision = file_hash(self.configuration.directory / "config.yaml")
        body += '<p>Nur angebotene Werte werden bearbeitet. YAML-Kommentare werden beim Speichern nicht erhalten. Änderungen werden vor Speicherung nochmals angezeigt.</p>'
        for name in sorted(SETTINGS_FIELDS):
            current, saved = active, raw
            for part in name.split("."):
                current = current.get(part) if isinstance(current, dict) else None
                saved = saved.get(part) if isinstance(saved, dict) else None
            body += f'<section class="card"><h2>{e(SETTING_LABELS.get(name, name))}</h2><p class="meta">{e(name)}</p><p>Aktiv: {e(current)} · gespeichert: {e(saved)}. Quelle: config.yaml</p>'
            activation = "Nach sicherer Übernahme" if name.split(".")[0] in LIVE_FIELDS else "Beim nächsten Start"
            body += f'<p>Wirksam: {e(activation)}.</p>'
            body += post_form("/einstellungen/speichern", self.site.auth.csrf_token(session.id), field("value", "Neuer Wert (JSON-Skalar oder Text)", json.dumps(saved, ensure_ascii=False)),
                              name=name, expected_hash=revision) + '</section>'
        return Response.html(200, layout("Einstellungen", body, active="/einstellungen"))

    def save_settings(self, request, session, form):
        if self.configuration is None:
            return self.site._reply(request, 503, "Konfiguration nicht verfügbar.")
        try:
            try:
                value = json.loads(form["value"])
            except json.JSONDecodeError:
                value = form["value"]
            command = AdminCommand(kind=AdminKind.SETTINGS, actor=f"web:{session.id}", idempotency_key=form["key"],
                                   expected_hash=form["expected_hash"], patch={form["name"]: value}, acknowledged=True)
            self.configuration.candidate(command)
        except ConfigurationConflict:
            return self.site._reply(request, 409, "Einstellungsdatei geändert; bitte neu laden.")
        except (ValueError, KeyError, OSError):
            return self.site._reply(request, 422, "Ungültige oder inzwischen geänderte Einstellung; bitte neu prüfen.")
        if form.get("confirm") != "yes":
            body = '<h1>Änderung bestätigen</h1>' + notice('Aufbewahrung kann Inhalte unwiderruflich entfernen; Inhaltslogging speichert Maildaten. Echter Betrieb kann bestätigte Aktionen extern anlegen. Übrige Einstellungen benötigen teilweise einen Neustart.', "warn")
            hidden = {key: value for key, value in form.items() if key not in {"csrf", "key", "confirm"}}
            body += f'<p>{e(form["name"])} → {e(form["value"])}</p>'
            body += post_form(request.path, self.site.auth.csrf_token(session.id), "", "Änderung ausdrücklich speichern", confirm="yes", **hidden)
            return Response.html(200, layout("Bestätigen", body))
        return self.queue(request, command)

    def topics(self, request, session):
        if self.configuration is None:
            return self.site._reply(request, 503, "Themenverwaltung nicht verfügbar.")
        body = '<h1>Themen</h1><p>IDs bleiben stabil. Deaktivieren statt löschen. Änderungen gelten für neue Analysen; unabhängige Absender-Vorfilter bleiben erhalten.</p>'
        for category, filename in (("relevant", "topics.yaml"), ("irrelevant", "irrelevant_topics.yaml")):
            path = self.configuration.directory / filename
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            body += f'<h2>{e(filename)}</h2>'
            for topic in [*raw["topics"], {"id": "", "name": "", "enabled": True, "description": "", "examples": [], "exclusions": []}]:
                fields = "".join(field(key, key, "; ".join(value) if isinstance(value, list) else str(value).lower() if isinstance(value, bool) else value)
                                 for key, value in topic.items())
                fields += '<label><input type="checkbox" name="confirm" value="yes" required> Änderung ausdrücklich speichern</label>'
                body += post_form("/themen/speichern", self.site.auth.csrf_token(session.id), fields,
                                  category=category, expected_hash=file_hash(path), original_id=topic["id"])
        return Response.html(200, layout("Themen", body, active="/einstellungen"))

    def save_topic(self, request, session, form):
        try:
            if form.get("original_id") and form["id"] != form["original_id"]:
                raise ValueError("IDs dürfen nicht geändert werden")
            topic = {key: form[key] for key in ("id", "name", "description")}
            topic["enabled"] = {"true": True, "false": False}[form["enabled"].lower()]
            topic.update({key: [v.strip() for v in form[key].split(";") if v.strip()] for key in ("examples", "exclusions")})
            command = AdminCommand(kind=AdminKind.TOPICS, actor=f"web:{session.id}", idempotency_key=form["key"],
                                   expected_hash=form["expected_hash"], category=form["category"], patch=topic,
                                   acknowledged=form.get("confirm") == "yes")
            self.configuration.candidate(command)
        except ConfigurationConflict:
            return self.site._reply(request, 409, "Themendatei geändert; bitte neu laden.")
        except (ValueError, KeyError, OSError, AttributeError):
            return self.site._reply(request, 422, "Ungültige, unbestätigte oder inzwischen geänderte Themen.")
        return self.queue(request, command)

    def statistics(self, request, session):
        if self.metrics is None:
            return Response.html(200, layout("Auswertung", '<h1>Auswertung</h1><p>Noch keine Metrikerfassung verfügbar.</p>'))
        try:
            params = self.parameters(request)
            params["days"] = int(params.get("days", 30))
            params.setdefault("mode", "production")
            if params["mode"] not in MODE_LABELS:
                raise ValueError("Unbekannter Modus")
            selected = self.metrics.comparison if params["mode"] == "decision_test" and self.metrics.comparison is not None else self.metrics
            report = selected.report(**params)
        except (ValueError, TypeError):
            return self.site._reply(request, 422, "Ungültige Auswertungsfilter.")
        everything = selected.report(days=params["days"], mode=params["mode"])["records"]
        return Response.html(200, layout("Auswertung", statistics_page(params, report, everything),
                                         active="/auswertung"))

    def stop_page(self, request, session):
        if self.lifecycle is None:
            return self.site._reply(request, 503, "Beenden ist in dieser Instanz nicht verfügbar.")
        body = '<h1>Mailhelp beenden?</h1>' + notice('Danach ist diese Weboberfläche nicht erreichbar. Laufende Requests können bis zum Timeout dauern. Offene Vorgänge bleiben gespeichert. Neustart erfolgt am PC oder über den Container/Dienst; ein Supervisor kann automatisch neu starten. Windows und andere Prozesse werden nicht beendet.', "warn")
        body += post_form(request.path, self.site.auth.csrf_token(session.id), '', 'Mailhelp ausdrücklich beenden', process=self.lifecycle.process, confirm="yes")
        return Response.html(200, layout("Beenden", body))

    def stop(self, request, session, form):
        try:
            if self.lifecycle is None or form.get("confirm") != "yes":
                raise ValueError("Bestätigung fehlt")
            callback = self.lifecycle.request(form["process"], form["key"], f"web:{session.id}")
        except (ValueError, KeyError):
            return self.site._reply(request, 409, "Beenden nicht bestätigt oder Anforderung veraltet.")
        response = Response.html(202, layout("Beenden angefordert", '<h1>Beenden angefordert</h1><p>Mailhelp stoppt kontrolliert. Ein späterer Verbindungsabbruch bestätigt allein nicht den erfolgreichen Abschluss.</p>'))
        response.after_send = callback
        return response
