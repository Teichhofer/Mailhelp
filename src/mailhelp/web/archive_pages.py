"""HTML of the mail archive, the history and the cost evaluation; no routing, no state access."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, SupportsFloat
from urllib.parse import urlencode

from ..formatting import duration_text, format_datetime_local
from ..models import MailState, Proposal
from ..review.consistency import Hint
from ..review.explanation import OUTCOME_LABELS, Explanation, Outcome, Step
from ..review.queries import ArchiveQuery
from ..review.search import Hit
from .actions import recheck_form
from .filters import chips
from .forms import field, select
from .labels import EVENTS, SOURCES, STATUSES, count_text, label
from .pages import e, notice, page_head

MODE_LABELS = {"production": "Betrieb (Standard und Ollama)", "standard": "Betrieb mit Standard-KI",
               "local": "Betrieb mit Ollama", "decision_test": "Vergleichsläufe (Decision-Tests)"}
PERIODS = ((1, "Heute (24 Std.)"), (7, "7 Tage"), (30, "30 Tage"), (90, "90 Tage"))
RELEVANCE_LABELS = {"relevant": "relevant", "irrelevant": "irrelevant", "unclear": "unklar",
                    "unknown": "nicht mehr bekannt"}
STATE_FILTERS = (("", "alle"), ("waiting", "wartet auf dich"), ("failed", "mit Fehler"),
                 ("completed", "abgeschlossen"), ("no_action", "ohne Vorschlag"))
SORTS = (("received", "Empfangszeit"), ("updated", "zuletzt bearbeitet"))
SEARCH_SCOPES = (("all", "allem – auch Mailtext und Anhänge"),
                 ("meta", "nur Absender, Betreff und Zusammenfassung"))
# Fields compared between two stored versions of a proposal.
VERSION_FIELDS = ('title', 'description', 'target', 'due', 'start', 'end', 'all_day', 'location', 'video_link',
                  'status', 'open_questions')


def _number(value: SupportsFloat | str, digits: int = 2) -> str:
    """German number format; callers show missing figures as "—" or "unbekannt"."""
    return f"{float(value):,.{digits}f}".replace(",", " ").replace(".", ",").replace(" ", ".")


def _money(value: SupportsFloat | str | None, currency: str) -> str:
    return "unbekannt" if value is None else f"{_number(value, 4)} {currency}"


def _calls(count: int, one: str, many: str) -> str:
    """Spoken link label, e.g. "1 fehlgeschlagenen Aufruf anzeigen" / "3 fehlgeschlagene Aufrufe anzeigen"."""
    return f"{count} {one if count == 1 else many} anzeigen"


class _Html(str):
    """Markup that is already escaped."""


def _total_duration(seconds: float) -> str:
    """The readable sum; the exact seconds stay visible next to a larger unit (5.9.1)."""
    text = e(duration_text(seconds))
    return text if round(seconds, 1) < 60 else f'{text} <span class="meta">({_number(seconds, 0)} s)</span>'


def statistics_page(params: dict[str, Any], report: dict[str, Any], everything: list[dict[str, Any]], zone: str = "UTC",
                    now: datetime | None = None, steps: dict[str, Any] | None = None) -> str:
    """Costs and durations with readable labels and charts; unknown values are never shown as zero."""
    from datetime import UTC

    from .charts import statistics_charts
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
    from .calls_page import metric_link
    rate = report["exchange_rate_date"]
    # 5.9.11: every figure opens the call list with a matching preset (a native link, no JavaScript).
    figures: list[tuple[str, str, str, str]] = [
        ("Aufrufe (einzelne Versuche)", "calls", e(report["count"]),
         _calls(report["count"], "Aufruf", "Aufrufe")),
        ("davon fehlgeschlagen", "failed", e(report["failed"]),
         _calls(report["failed"], "fehlgeschlagenen Aufruf", "fehlgeschlagene Aufrufe")),
        ("Gemeldete Cloudkosten", "cloud_costs", e(_money(report["usd"], "USD")), "Aufrufe mit Kostenangabe anzeigen"),
        ("Cloudaufrufe ohne Kostenangabe", "unknown_cost", e(report["unknown_cost"]),
         _calls(report["unknown_cost"], "Cloudaufruf ohne Kostenangabe", "Cloudaufrufe ohne Kostenangabe")),
        ("Cloudkosten in Euro", "cloud_eur",
         e(_money(report["cloud_eur"], "EUR") + (f" (Wechselkurs vom {rate})" if rate else "")
           if report["cloud_eur"] is not None else "kein Wechselkurs hinterlegt"), "Umrechnung und Aufrufe anzeigen"),
        ("Geschätzte Stromkosten Ollama", "electricity", e(_money(report["electricity_eur"], "EUR")),
         "Ollama-Aufrufe und Berechnung anzeigen"),
        ("Summierte Aufrufdauer", "duration", _total_duration(report["seconds"]), "Längste Aufrufe anzeigen"),
        ("Dauer je Aufruf (Mittel / Median / 95 %)", "distribution",
         e(" / ".join(duration_text(report[key], precise=True) if report[key] is not None else "—"
                      for key in ("mean", "median", "p95"))), "Verteilung der Aufrufdauer anzeigen"),
    ]
    if report["damaged"] or report["capture_failures"]:
        figures.append(("Unvollständige Erfassung", "incomplete",
                        e(f'{report["damaged"]} beschädigte Zeilen, {report["capture_failures"]} Erfassungsfehler'),
                        "Bedeutung der unvollständigen Erfassung anzeigen"))
    rows = [(name, _Html(metric_link(metric, value, label, params))) for name, metric, value, label in figures]
    rows += _run_time_rows(params, steps)
    body = (page_head("Auswertung", "Einblicke", "Kosten und Zeiten der KI-Aufrufe und Verarbeitungsschritte.")
            + form
            + '<dl class="facts-table">'
            + "".join(f"<dt>{e(k)}</dt><dd>{v if isinstance(v, _Html) else e(v)}</dd>" for k, v in rows) + "</dl>"
            + '<p class="meta">Kosten in USD stammen aus den Angaben des Anbieters; fehlt eine Angabe, ist sie '
              "unbekannt, nicht null. Stromkosten sind eine Schätzung aus der eingestellten Leistung und dem "
              "Strompreis (überlappende Aufrufe einmal gezählt); Leerlauf, Hardware und andere Serverlast sind "
              "nicht enthalten. Die summierte Aufrufdauer ist keine Durchlaufzeit; die Durchlaufzeit je Mail "
              "steht darüber (ab 6.1.6 erfasst).</p>")
    from .calls_page import filters
    link = "/auswertung/schritte?" + urlencode(filters(params))
    charts = statistics_charts(report["records"], params["days"], zone, now or datetime.now(UTC), steps, link)
    return body + charts + _statistics_groups(report["groups"])


def _run_time_rows(params: dict[str, Any], steps: dict[str, Any] | None) -> list[tuple[str, _Html]]:
    """6.1.8: run time per mail and the waiting for decisions; a link to the slowest runs."""
    from .calls_page import filters
    total = (steps or {}).get("total") or {}
    if not total.get("count"):
        return []
    figures = " / ".join(duration_text(total[key] / 1000, precise=True) for key in ("median_ms", "p95_ms", "max_ms"))
    href = "/auswertung/schritte?" + urlencode({**filters(params), "stage": "total"})
    rows = [("Durchlaufzeit je Mail (Median / 95 % / Maximum)",
             _Html(f'<a class="fact-link" href="{e(href)}" aria-label="Langsamste Durchläufe anzeigen">'
                   f'{e(figures)} ›</a>'))]
    waiting = (steps or {}).get("waiting_median_ms")
    if waiting:
        rows.append(("Wartezeit auf Entscheidungen (Median)", _Html(e(duration_text(waiting / 1000)))))
    return rows


def _statistics_groups(groups: list[dict[str, Any]]) -> str:
    if not groups:
        return '<p class="empty">Für diese Auswahl gibt es keine erfassten Aufrufe.</p>'
    # Scrollable on phones, so it must be reachable by keyboard (axe scrollable-region-focusable).
    body = ('<h2>Nach Modell und Schritt</h2><div class="table-scroll" tabindex="0" role="region" '
            'aria-label="Nach Modell und Schritt"><table><thead><tr>'
            "<th>Modell</th><th>Schritt</th><th>Anbieter</th><th>Aufrufe</th><th>Fehler</th>"
            "<th>Summe</th><th>Median</th><th>95 %</th><th>$Cent</th></tr></thead><tbody>")
    for group in groups:
        model_short = group["model"].rsplit("/", 1)[-1]
        cent = Decimal(str(group["usd"])) * 100
        body += (f'<tr><td title="{e(group["model"])}">{e(model_short)}</td><td>{e(group["stage"])}</td>'
                 f'<td>{e(group["provider"])}</td><td>{group["count"]}</td><td>{group["failed"]}</td>'
                 f'<td>{_number(group["seconds"], 1)} s</td>'
                 f'<td>{_number(group["median"], 2)} s</td><td>{_number(group["p95"], 2)} s</td>'
                 f'<td title="{_number(group["usd"], 4)} USD">{_number(cent, 2)}</td></tr>')
    return body + "</tbody></table></div>"


def _hit(hit: Hit | None) -> str:
    """Where the first search word was found, with the match highlighted (all text escaped)."""
    if hit is None:
        return ""
    return (f'<p class="search-hit"><span class="meta">Gefunden in {e(hit.where)}:</span> '
            f'{e(hit.before)}<mark>{e(hit.match)}</mark>{e(hit.after)}</p>')


def _local_time(value: str | None, zone: str) -> str:
    if not value:
        return "Empfangszeit unbekannt"
    return format_datetime_local(datetime.fromisoformat(value), zone)


def _archive_filters(query: ArchiveQuery, topics: list[str], mailboxes: dict[str, tuple[int, str]]) -> str:
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
    if mailboxes:
        filters += select("postfach", "Postfach", "" if query.postfach is None else str(query.postfach),
                          [("", "alle"), *((str(number), label) for number, label in sorted(mailboxes.values()))])
    return filters


def _archive_row(item: dict[str, Any], zone: str, mailboxes: dict[str, tuple[int, str]], csrf: str = "") -> str:
    from ..review.cards import sender_name
    from ..review.views import STATUS_LABELS

    badges = [f'<span class="badge">{e(RELEVANCE_LABELS.get(item["relevance"], item["relevance"]))}</span>']
    if mailboxes:
        label = mailboxes.get(item["account"], (0, "Entferntes Postfach"))[1]
        badges.insert(0, f'<span class="badge">{e(label)}</span>')
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
    recheck = (recheck_form(csrf, item["id"], item["recheck_round"], small=True)
               if csrf and item.get("recheck_round") is not None else "")
    return (f'<li class="card"><h3><a href="/mail/{e(item["id"])}">{e(item["subject"])}</a></h3>'
            f'<p class="source">{e(sender_name(item["sender"]))} · '
            f'{e(_local_time(item["received"], zone))}</p>'
            f'<p class="labels">{" ".join(badges)}</p>{summary}{_hit(item.get("hit"))}{recheck}</li>')


def mail_list_page(query: ArchiveQuery, items: list[dict[str, Any]], total: int, damaged: int,
                   topics: list[str], zone: str, mailboxes: dict[str, tuple[int, str]] | None = None,
                   csrf: str = "") -> str:
    """Search and filters for stored mails; works without JavaScript."""
    mailboxes = mailboxes or {}
    active = any((query.relevance, query.topic, query.state, query.status is not None, query.since, query.until,
                  query.sort != "received", query.postfach))
    body = (page_head("Mails", "Arbeitsbereich", "Von Mailhelp gespeicherte Mails durchsuchen.")
            + chips("/mails", query.filter)
            + '<form method="get" class="stack">'
            f'<label>Suche<input type="search" name="q" value="{e(query.q)}" maxlength="200" '
            'aria-describedby="suche-hinweis"></label>'
            '<p class="meta" id="suche-hinweis">Alle Wörter müssen vorkommen; „genaue Wortfolge“ in '
            'Anführungszeichen. Groß-/Kleinschreibung und ä/ae, ö/oe, ü/ue, ß/ss sind gleichwertig.</p>'
            + select("scope", "Suchen in", query.scope, list(SEARCH_SCOPES)) +
            f'<details class="filter-box"{" open" if active else ""}><summary>Filter</summary>'
            f'<div class="filters">{_archive_filters(query, topics, mailboxes)}</div></details>'
            '<button class="button primary">Suchen</button></form>')
    body += f'<p class="meta">{count_text(total, "gespeicherte Mail", "gespeicherte Mails")} · Seite {query.page}</p>'
    if not items:
        body += '<p class="empty">Keine gespeicherte Mail passt zu dieser Suche.</p>'
    body += f'<ul class="archive-list">{"".join(_archive_row(item, zone, mailboxes, csrf) for item in items)}</ul>'
    pages = []
    for number, text in ((query.page - 1, "Vorherige Seite"), (query.page + 1, "Nächste Seite")):
        if 1 <= number <= max(1, (total + query.size - 1) // query.size):
            parameters = query.model_dump(mode="json", exclude_none=True)
            parameters["page"] = number
            parameters = {k: v for k, v in parameters.items() if v not in ("", None)}
            pages.append(f'<a class="button" href="/mails?{e(urlencode(parameters))}">{text}</a>')
    if pages:
        body += f'<p class="actions">{" ".join(pages)}</p>'
    if damaged:
        body += notice(f"{damaged} gespeicherte Datensätze sind beschädigt und werden nicht angezeigt.", "warn")
    return body + ('<p class="meta">Gezeigt werden nur Mails, die Mailhelp noch gespeichert hat – '
                   'nicht der ganze Posteingang. Nach Ablauf der Aufbewahrungsfrist für Mailinhalte '
                   'findet die Suche nur noch Absender, Betreff und Zusammenfassung.</p>')


def analysis_section(mail_id: str, state: MailState, record: dict[str, Any]) -> str:
    """The stored analysis of one mail; removed content says so instead of showing old values."""
    stored_relevance = state.relevance.model_dump(mode="json") if state.relevance else {}
    stored_summary = state.summary.model_dump(mode="json") if state.summary else {}
    relevance = {} if record.get("removed") else record.get("relevance") or stored_relevance
    summary = {} if record.get("removed") else record.get("summary") or stored_summary
    text = " ".join(summary.get("sentences", []))
    if not text:
        text = ("Nicht erforderlich (irrelevant)." if relevance.get("decision") == "irrelevant"
                else "Nicht vorhanden, noch nicht erstellt oder nach Aufbewahrung entfernt.")
    human = state.relevance_dialog.decision if state.relevance_dialog else None
    topics = record.get("topics", {})
    names = [topics.get(identifier, identifier) for identifier in relevance.get("topic_ids", [])]
    body = f'<section class="card"><h2>Zusammenfassung</h2><p>{e(text)}</p>'
    body += f'<p>Fristen: {e("; ".join(summary.get("deadlines", [])))}</p><h2>Relevanz und Themen</h2>'
    body += (f'<p>Modellbewertung: {e(relevance.get("decision", "unbekannt"))} · '
             f'Quelle: {e(record.get("source", "unbekannt"))}</p>')
    body += (f'<p>{e(relevance.get("reason", "Keine Begründung mehr verfügbar"))}</p>'
             f'<p>Themen: {e(", ".join(names))}</p>')
    body += f'<p>Menschliche Entscheidung: {e(human or "keine")}</p><h2>Erkannte Aktionen</h2><ul>'
    body += "".join(f'<li><a href="/vorschlag/{mail_id}/{e(p.id)}">{e(p.title)}</a> · {e(p.status.value)}</li>'
                    for p in state.proposals)
    return body + f'</ul><a class="button" href="/verlauf?q={mail_id}">Verlauf dieser Mail</a></section>'


PATH_BADGES = {Outcome.DONE: "ok", Outcome.SKIPPED: "", Outcome.FAILED: "danger", Outcome.PENDING: "accent",
               Outcome.MISSING: "warn"}


def _path_step(step: Step, topics: dict[str, str], tag: str = "li") -> str:
    badge = f'<span class="badge {PATH_BADGES[step.outcome]}">{OUTCOME_LABELS[step.outcome]}</span>'
    body = (f'<{tag} class="path-step outcome-{step.outcome.value}"><p class="path-head"><strong>{e(step.title)}'
            f'</strong> {badge}</p><p>{e(step.text)}</p>')
    if step.topics:
        body += f'<p>Themen: {e(", ".join(topics.get(topic, topic) for topic in step.topics))}</p>'
    if step.model_reason:
        body += (f'<p class="model-reason"><span class="meta">Modellbewertung, keine geprüfte Tatsache:</span> '
                 f'„{e(step.model_reason)}“</p>')
    if step.notes:
        body += '<ul class="path-notes">' + "".join(f"<li>{e(note)}</li>" for note in step.notes) + "</ul>"
    return body + f"</{tag}>"


def _hints(hints: tuple[Hint, ...]) -> str:
    """5.1.4: possible contradictions with their evidence; never a claim of a missed action."""
    if not hints:
        return ""
    items = "".join(f'<li class="hint-{hint.severity}"><span class="badge {hint.severity}">'
                    f'{"Prüfen" if hint.severity == "warn" else "Hinweis"}</span> {e(hint.text)} '
                    f'<span class="meta">Beleg: {e(hint.evidence)}</span></li>' for hint in hints)
    return f'<h3>Prüfhinweise</h3><ul class="path-hints">{items}</ul>'


def processing_path_section(explanation: Explanation, topics: dict[str, str], hints: tuple[Hint, ...] = ()) -> str:
    """5.1.1: how this mail was actually processed, step by step, from stored results only."""
    steps = "".join(_path_step(step, topics) for step in explanation.steps)
    return ('<section class="card processing-path" aria-labelledby="verarbeitung-titel">'
            '<h2 id="verarbeitung-titel">So wurde diese Mail verarbeitet</h2>'
            f'<p class="meta">Analyserunde {explanation.analysis_round} · aus gespeicherten Ergebnissen, '
            'ohne erneute Modellabfrage</p>'
            f'<ol class="path-steps">{steps}</ol>'
            + _path_step(explanation.result, topics, tag="div").replace(
                'class="path-step ', 'class="path-step path-result ', 1)
            + _hints(hints) + '</section>')


def event_text(row: dict[str, Any], zone: str) -> str:
    """6.2.3: "14.11.2026, 07:12 Uhr · Verworfen · Weboberfläche" – never ISO times or internal values."""
    parts = [format_datetime_local(datetime.fromisoformat(row["at"]), zone)]
    if row["kind"] not in ("state", "legacy") and label(EVENTS, row["kind"]) != label(STATUSES, row["status"]):
        parts.append(label(EVENTS, row["kind"]))
    parts += [label(STATUSES, row["status"]), label(SOURCES, row["source"])]
    return " · ".join(parts)


def revisions_list(mail_id: str, proposal_id: str, rows: list[dict[str, Any]], zone: str) -> str:
    if not rows:
        return '<p class="meta">Noch keine Revisionen erfasst.</p>'
    items = "".join(
        f'<li><a href="/vorschlag/{mail_id}/{e(proposal_id)}/version/{e(row["version"])}">'
        f'Version {e(row["version"])}</a> · {e(event_text(row, zone))}</li>'
        for row in rows)
    return f'<ul class="archive-list">{items}</ul>'


def history_page(query: ArchiveQuery, rows: list[dict[str, Any]], total: int, params: dict[str, Any],
                 zone: str) -> str:
    body = (page_head("Verlauf", "Einblicke", "Was mit Vorschlägen und Mails geschehen ist.")
            + chips("/verlauf", query.filter) + '<form method="get" class="stack">'
            + field("q", "Betreff, Absender oder Mail-ID", query.q))
    body += (field("status", "Vorschlagsstatus", query.status or "") + field("kind", "Ereignisart", query.kind)
             + field("proposal_kind", "Aufgabe (task) oder Termin (event)", query.proposal_kind)
             + field("since", "Von", query.since or "") + field("until", "Bis", query.until or ""))
    body += ('<button class="button">Filtern</button></form>'
             f'<p>{count_text(total, "Ereignis", "Ereignisse")} · Seite {query.page}</p><ul class="archive-list">')
    for row in rows:
        link = (f'/vorschlag/{row["mail_id"]}/{row["proposal_id"]}/version/{row["version"]}'
                if row["proposal_id"] else f'/mail/{row["mail_id"]}')
        version = f' · Version {e(row["version"])}' if row["version"] else ""
        body += (f'<li class="card"><a href="{e(link)}">{e(row["title"])}</a>'
                 f'<p>{e(event_text(row, zone))}{version}</p></li>')
    body += '</ul>'
    if query.page > 1:
        params["page"] = query.page - 1
        body += f'<a class="button" href="/verlauf?{e(urlencode(params))}">Vorherige Seite</a>'
    if query.page * query.size < total:
        params["page"] = query.page + 1
        body += f'<a class="button" href="/verlauf?{e(urlencode(params))}">Weitere Ereignisse</a>'
    return body


def version_diff(previous: Proposal | None, current: Proposal) -> str:
    """Changed fields against the stored predecessor; a historical version is read only."""
    diff = '<section class="card"><h2>Änderungen gegenüber vorheriger Version</h2>'
    if previous is None:
        diff += '<p>Vorherige Version nicht vorhanden.</p>'
    else:
        before, after = previous.model_dump(mode="json"), current.model_dump(mode="json")
        diff += '<dl>' + ''.join(f'<dt>{e(key)}</dt><dd>{e(before[key])} → {e(after[key])}</dd>'
                                for key in VERSION_FIELDS if before[key] != after[key]) + '</dl>'
    return diff + '</section><p>Historische Version – ausschließlich lesend.</p>'
