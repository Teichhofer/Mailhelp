"""Authenticated archive, configuration, deterministic editing and stop pages."""
from __future__ import annotations

import json
import secrets
from datetime import datetime
from decimal import Decimal
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
from .setting_help import SETTING_HELP, EXTRA_HELP, help_bubble
from .. import state_names


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
                  "metrics.enabled": "Metrikerfassung aktivieren",
                  "personal_info": "Persönliche Angaben für Antworten"}
# Free text settings: edited in a text area and never parsed as JSON.
TEXT_SETTINGS = {"personal_info": ("Zum Beispiel Name, Rolle, Signatur oder gewünschte Anrede. Die Angaben gehen "
                                   "nur in Antwort-Entwürfe ein und werden dafür an das KI-Modell übergeben.")}


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
                 "<th>Summe</th><th>Median</th><th>95 %</th><th>$Cent</th></tr></thead><tbody>")
        for group in report["groups"]:
            model_short = group["model"].rsplit("/", 1)[-1]
            cent = Decimal(str(group["usd"])) * 100
            body += (f'<tr><td title="{e(group["model"])}">{e(model_short)}</td><td>{e(group["stage"])}</td><td>{e(group["provider"])}</td>'
                     f'<td>{group["count"]}</td><td>{group["failed"]}</td><td>{_number(group["seconds"], 1)} s</td>'
                     f'<td>{_number(group["median"], 2)} s</td><td>{_number(group["p95"], 2)} s</td>'
                     f'<td title="{_number(group["usd"], 4)} USD">{_number(cent, 2)}</td></tr>')
        body += "</tbody></table></div>"
    else:
        body += '<p class="empty">Für diese Auswahl gibt es keine erfassten Aufrufe.</p>'
    return body


SETTING_GROUPS = (
    ("Mailabruf und Betrieb", ("poll_interval_seconds", "timezone", "test_mode")),
    ("Antworten", ("personal_info",)),
    ("Ziele", ("targets.",)),
    ("Aufrufbudget und Mailgrenzen", ("limits.",)),
    ("Zeitlimits und Wiederholungen", ("timeouts.", "retries.")),
    ("Aufbewahrung", ("retention.",)),
    ("Protokollierung", ("logging.",)),
    ("Kosten und Messung", ("metrics.",)),
)
SERVICE_LABELS = {"imap": "IMAP", "telegram": "Telegram", "openrouter": "OpenRouter", "ollama": "Ollama",
                  "todoist": "Todoist", "google_calendar": "Google Kalender"}
TIMEOUT_LABELS = {"timeout_seconds": "Zeitlimit (s)", "retries": "Wiederholungen",
                  "initial_backoff_seconds": "erste Wartezeit (s)", "max_backoff_seconds": "längste Wartezeit (s)"}
EXTRA_LABELS = {
    "targets.todoist_project": "Todoist-Projekt", "targets.google_calendar": "Google-Kalender",
    "logging.console.level": "Konsole: Mindeststufe", "logging.file.level": "Logdatei: Mindeststufe",
    "logging.llm.include_requests": "KI-Anfragen vollständig protokollieren",
    "logging.llm.include_responses": "KI-Antworten vollständig protokollieren",
    "metrics.usd_per_eur": "Wechselkurs (USD je EUR)", "metrics.exchange_rate_date": "Wechselkurs vom",
    "retries.interpretation_attempts": "Antworten verstehen: Versuche",
    "retries.interpretation_backoff_seconds": "Antworten verstehen: Wartezeit (s)",
    "retries.revision_attempts": "Überarbeitung: Versuche", "retries.revision_backoff_seconds": "Überarbeitung: Wartezeit (s)",
}
LEVEL_CHOICES = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def setting_label(name: str) -> str:
    if name in SETTING_LABELS or name in EXTRA_LABELS:
        return SETTING_LABELS.get(name) or EXTRA_LABELS[name]
    _, service, key = name.split(".")
    return f"{SERVICE_LABELS[service]}: {TIMEOUT_LABELS[key]}"


def _lookup(values: dict | None, name: str) -> object:
    for part in name.split("."):
        values = values.get(part) if isinstance(values, dict) else None
    return values


def _shown(name: str, value: object) -> str:
    """A readable value; target IDs are masked, missing values marked."""
    if value is None or value == "":
        return "nicht gesetzt"
    if name in TEXT_SETTINGS:
        line = " ".join(str(value).split())
        return line if len(line) <= 60 else line[:59] + "…"
    if isinstance(value, bool):
        return "ja" if value else "nein"
    text = str(value)
    if name.startswith("targets.") and len(text) > 8:
        return f"{text[:3]}…{text[-3:]}"
    return text


def _input(name: str, saved: object) -> str:
    label = "Neuer Wert"
    if name in TEXT_SETTINGS:
        return (f'<label>{label}<textarea name="value" rows="6" maxlength="2000">{e(saved or "")}</textarea></label>'
                f'<p class="meta">{e(TEXT_SETTINGS[name])}</p>')
    if isinstance(saved, bool):
        return select("value", label, json.dumps(saved), [("true", "ja"), ("false", "nein")])
    if name.endswith(".level"):
        return select("value", label, saved, [(level, level) for level in LEVEL_CHOICES])
    kind = "number" if isinstance(saved, (int, float)) else "text"
    step = ' step="any"' if kind == "number" else ""
    shown = "" if saved is None else saved
    return (f'<label>{label}<input type="{kind}"{step} name="value" value="{e(shown)}" '
            'maxlength="200" required></label>')


def settings_page(models: list, raw: dict | None, active: dict | None, revision: str, csrf: str) -> str:
    body = ('<h1>Einstellungen</h1><p class="card-links"><a class="button small" href="/themen">Themen</a> '
            '<a class="button small" href="/einstellungen/ignorierte-absender">Ignorierte Absender</a> '
            '<a class="button small" href="/geraete">Geräte</a> '
            '<a class="button small danger" href="/einstellungen/beenden">Mailhelp beenden</a></p>')
    body += '<div class="setting-row"><h2>Modelle (nur lesend)</h2>' + help_bubble("models", "Modelle", EXTRA_HELP["models"]) + "</div>"
    if models:
        body += ('<div class="table-scroll"><table><thead><tr><th>Schritt</th>'
                 "<th>Modell</th><th>Parameter</th><th>Quelle</th></tr></thead><tbody>"
                 + "".join(f"<tr><td>{e(step)}</td><td>{e(model)}</td><td>{e(parameters or '—')}</td><td>{e(source)}</td></tr>"
                           for step, model, parameters, source in models)
                 + "</tbody></table></div>")
    else:
        body += '<p class="meta">Keine Modellangaben verfügbar.</p>'
    if raw is None:
        return body + notice("Konfigurationsdienst nicht verfügbar.", "warn")
    body += ('<p class="meta">Quelle aller folgenden Werte: <code>config.yaml</code>. Gespeichert wird nur der '
             "geänderte Wert; Kommentare und Aufbau der Datei bleiben erhalten. Vor dem Speichern wird die "
             "Änderung noch einmal angezeigt.</p>")
    for title, prefixes in SETTING_GROUPS:
        names = sorted(name for name in SETTINGS_FIELDS
                       if any(name == prefix or name.startswith(prefix) for prefix in prefixes))
        body += f"<h2>{e(title)}</h2>"
        for name in names:
            current, saved = _lookup(active, name), _lookup(raw, name)
            live = name.split(".")[0] in LIVE_FIELDS
            if current == saved:
                state = "aktiv"
            else:
                state = ("gespeichert – wird an der nächsten sicheren Stelle übernommen" if live
                         else "gespeichert – wirkt erst nach einem Neustart")
            timing = "sofort nach dem Speichern" if live else "beim nächsten Start"
            form = post_form("/einstellungen/speichern", csrf, _input(name, saved), "Prüfen",
                             name=name, expected_hash=revision)
            body += (f'<div class="setting-row"><details class="setting"><summary><span>{e(setting_label(name))}</span>'
                     f'<strong>{e(_shown(name, current))}</strong></summary>'
                     f'<p class="meta">Gespeichert: {e(_shown(name, saved))} · {e(state)} · '
                     f'Änderungen wirken {e(timing)}.</p>{form}</details>'
                     + help_bubble(name, setting_label(name), SETTING_HELP[name]) + '</div>')
    return body


RELEVANCE_LABELS = {"relevant": "relevant", "irrelevant": "irrelevant", "unclear": "unklar",
                    "unknown": "nicht mehr bekannt"}
STATE_FILTERS = (("", "alle"), ("waiting", "wartet auf dich"), ("failed", "mit Fehler"),
                 ("completed", "abgeschlossen"), ("no_action", "ohne Vorschlag"))
SORTS = (("received", "Empfangszeit"), ("updated", "zuletzt bearbeitet"))


def _local_time(value: str | None, zone: str) -> str:
    if not value:
        return "Empfangszeit unbekannt"
    return datetime.fromisoformat(value).astimezone(ZoneInfo(zone)).strftime("%d.%m.%Y, %H:%M Uhr")


def mail_list_page(query, items: list[dict], total: int, damaged: int, topics: list[str], zone: str) -> str:
    """Search and filters for stored mails; works without JavaScript."""
    from ..review.cards import sender_name
    from ..review.views import STATUS_LABELS

    status = "" if query.status is None else str(query.status)
    status_choices = [("", "alle")] + [(item.value, label) for item, label in STATUS_LABELS.items()]
    filters = (select("relevance", "Relevanz", query.relevance,
                      [("", "alle"), *((key, label) for key, label in RELEVANCE_LABELS.items())])
               + select("topic", "Thema", query.topic, [("", "alle"), *((topic, topic) for topic in topics)])
               + select("state", "Verarbeitung", query.state, list(STATE_FILTERS))
               + select("status", "Vorschläge", status, status_choices)
               + f'<label>Von<input type="date" name="since" value="{e(query.since or "")}"></label>'
               + f'<label>Bis<input type="date" name="until" value="{e(query.until or "")}"></label>'
               + select("sort", "Sortierung", query.sort, list(SORTS)))
    active = any((query.relevance, query.topic, query.state, status, query.since, query.until,
                  query.sort != "received"))
    body = ('<h1>Mails</h1><form method="get" class="stack">'
            f'<label>Suche (Absender, Betreff, Zusammenfassung)<input type="search" name="q" '
            f'value="{e(query.q)}" maxlength="200"></label>'
            f'<details class="filter-box"{" open" if active else ""}><summary>Filter</summary>'
            f'<div class="filters">{filters}</div></details>'
            '<button class="button primary">Suchen</button></form>')
    body += f'<p class="meta">{total} gespeicherte Mails · Seite {query.page}</p>'
    if not items:
        body += '<p class="empty">Keine gespeicherte Mail passt zu dieser Suche.</p>'
    rows = []
    for item in items:
        badges = [f'<span class="badge">{e(RELEVANCE_LABELS.get(item["relevance"], item["relevance"]))}</span>']
        if item["waiting"]:
            badges.append('<span class="badge warn">wartet auf dich</span>')
        if item["failed"]:
            badges.append('<span class="badge danger">Fehler</span>')
        counts: dict[str, int] = {}
        for value in item["statuses"]:
            counts[value] = counts.get(value, 0) + 1
        for value, count in sorted(counts.items()):
            label = next(text for state, text in STATUS_LABELS.items() if state.value == value)
            badges.append(f'<span class="badge accent">{count} × {e(label)}</span>')
        summary = f'<p>{e(item["summary"])}</p>' if item["summary"] else ""
        rows.append(f'<li class="card"><h3><a href="/mail/{e(item["id"])}">{e(item["subject"])}</a></h3>'
                    f'<p class="source">{e(sender_name(item["sender"]))} · {e(_local_time(item["received"], zone))}</p>'
                    f'<p class="labels">{" ".join(badges)}</p>{summary}</li>')
    body += f'<ul class="archive-list">{"".join(rows)}</ul>'
    pages = []
    for number, label in ((query.page - 1, "Vorherige Seite"), (query.page + 1, "Nächste Seite")):
        if 1 <= number <= max(1, (total + query.size - 1) // query.size):
            parameters = query.model_dump(mode="json", exclude_none=True)
            parameters["page"] = number
            parameters = {k: v for k, v in parameters.items() if v not in ("", None)}
            pages.append(f'<a class="button" href="/mails?{e(urlencode(parameters))}">{label}</a>')
    if pages:
        body += f'<p class="actions">{" ".join(pages)}</p>'
    if damaged:
        body += notice(f"{damaged} gespeicherte Datensätze sind beschädigt und werden nicht angezeigt.", "warn")
    return body + '<p class="meta">Gezeigt werden nur Mails, die Mailhelp noch gespeichert hat – nicht der ganze Posteingang.</p>'


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
        topics = sorted({topic for item in self.queries.items() for topic in item["topics"]})
        page = mail_list_page(query, items, total, self.queries.damaged, topics, self.site.configured_timezone)
        from .filters import chips
        page = chips("/mails", query.filter) + page
        return Response.html(200, layout("Mails", page, active="/mails"))

    def analysis(self, mail_id):
        store = self.site.views.store
        try:
            state = store.peek_model(state_names.mail(mail_id), MailState)
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

    def revisions(self, mail_id, proposal_id):
        """Recorded events of one proposal with links to every stored version."""
        rows = sorted((row for row in self.queries.history()
                       if row["mail_id"] == mail_id and row["proposal_id"] == proposal_id),
                      key=lambda row: row["at"], reverse=True)
        if not rows:
            return '<p class="meta">Noch keine Revisionen erfasst.</p>'
        items = "".join(
            f'<li><a href="/vorschlag/{mail_id}/{e(proposal_id)}/version/{e(row["version"])}">'
            f'Version {e(row["version"])}</a> · {e(row["at"])} · {e(row["status"])} · {e(row["source"])}</li>'
            for row in rows)
        return f'<ul class="archive-list">{items}</ul>'

    def history(self, request, session):
        try:
            params = self.parameters(request)
            query = ArchiveQuery.model_validate(params)
        except ValueError:
            return self.site._reply(request, 422, "Ungültige Verlaufsfilter.")
        rows = []
        store = self.site.views.store
        for row in self.queries.history():
            from .filters import matches
            source = next(item for item in self.queries.items() if item["id"] == row["mail_id"])
            if not matches(query.filter, [row["proposal_kind"]], [row["status"]], source["attachments"], source["duplicate"]):
                continue
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
        from .filters import chips
        body = chips("/verlauf", query.filter) + body
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
        previous = self.site.views.store.peek_model(state_names.proposal(mail_id, proposal_id, int(version)-1), Proposal)
        current = self.site.views.store.peek_model(state_names.proposal(mail_id, proposal_id, version), Proposal)
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
        proposal = self.site.views.store.peek_model(state_names.proposal(mail_id, proposal_id), Proposal)
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
        configuration = self.configuration
        raw = active = None
        revision = ""
        if configuration is not None:
            path = configuration.directory / "config.yaml"
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            active = configuration.active.model_dump(mode="json")
            revision = file_hash(path)
        page = settings_page(self.models, raw, active, revision, self.site.auth.csrf_token(session.id))
        page += self.site.experience.controls(self.site.auth.csrf_token(session.id))
        return Response.html(200, layout("Einstellungen", page, active="/einstellungen"))

    def save_settings(self, request, session, form):
        if self.configuration is None:
            return self.site._reply(request, 503, "Konfiguration nicht verfügbar.")
        try:
            if form["name"] in TEXT_SETTINGS:
                # Browsers send line breaks as CRLF; the file keeps plain LF.
                value = form["value"].replace("\r\n", "\n").strip()
            else:
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
            body += f'<p>{e(form["name"])} →</p><pre>{e(form["value"])}</pre>'
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
