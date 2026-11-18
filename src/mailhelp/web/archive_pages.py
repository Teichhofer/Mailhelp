"""HTML of the mail archive, the history and the cost evaluation; no routing, no state access."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, SupportsFloat, get_args
from urllib.parse import urlencode

from ..domain.mail import MailState
from ..domain.proposal import Proposal
from ..formatting import duration_text, format_datetime_local
from ..i18n import heading, msg, tr
from ..i18n.formatting import decimal
from ..review.cards import sender_name
from ..review.consistency import Hint
from ..review.error_reporting import error_summary
from ..review.explanation import OUTCOME_LABELS, Explanation, Outcome, Step
from ..review.queries import ArchiveQuery
from ..review.search import Hit
from ..review.views import STATUS_LABELS
from .actions import failure_forms, recheck_form
from .calls_page import filters, metric_link
from .charts import statistics_charts
from .filters import chips
from .forms import select
from .labels import EVENTS, KINDS, SOURCES, STATUSES, count_text, label, status_badge
from .pages import e, notice, page_head
from .rows import row
from .toolbar import date_field, search_field, toolbar

_STATISTICS_PAGE_TEXT_1 = msg(
    '<p class="meta">Kosten in USD stammen aus den Angaben des Anbieters; fehlt eine '
    "Angabe, ist sie unbekannt, nicht null. Stromkosten sind eine Schätzung aus der "
    "eingestellten Leistung und dem Strompreis (überlappende Aufrufe einmal gezählt); "
    "Leerlauf, Hardware und andere Serverlast sind nicht enthalten. Die summierte "
    "Aufrufdauer ist keine Durchlaufzeit; die Durchlaufzeit je Mail steht darüber (ab "
    "6.1.6 erfasst).</p>"
)

_STATISTICS_PAGE_TEXT_2 = msg(
    '<p class="empty">Für diese Auswahl gibt es keine erfassten Aufrufe. Einen längeren '
    "Zeitraum wählen oder die Filter zurücksetzen.</p>"
)

_MAIL_LIST_PAGE_TEXT_1 = msg(
    '<p class="meta">Gezeigt werden nur Mails, die Mailhelp noch gespeichert hat – nicht '
    "der ganze Posteingang. Nach Ablauf der Aufbewahrungsfrist für Mailinhalte findet die "
    "Suche nur noch Absender, Betreff und Zusammenfassung.</p>"
)

_MAIL_LIST_PAGE_TEXT_2 = msg(
    '<p class="meta" id="suche-hinweis">Alle Wörter müssen vorkommen; „genaue Wortfolge“ '
    "in Anführungszeichen. Groß-/Kleinschreibung und ä/ae, ö/oe, ü/ue, ß/ss sind "
    "gleichwertig.</p>"
)

MODE_LABELS = {
    "production": msg("Betrieb (Standard und Ollama)"),
    "standard": msg("Betrieb mit Standard-KI"),
    "local": msg("Betrieb mit Ollama"),
    "decision_test": msg("Vergleichsläufe (Decision-Tests)"),
}
PERIODS = ((1, msg("Heute (24 Std.)")), (7, msg("7 Tage")), (30, msg("30 Tage")), (90, msg("90 Tage")))
RELEVANCE_LABELS = {
    "relevant": msg("relevant"),
    "irrelevant": msg("irrelevant"),
    "unclear": msg("unklar"),
    "unknown": msg("nicht mehr bekannt"),
}
STATE_FILTERS = (
    ("", msg("alle")),
    ("waiting", msg("wartet auf dich")),
    ("failed", msg("mit Fehler")),
    ("completed", msg("abgeschlossen")),
    ("no_action", msg("ohne Vorschlag")),
)
SORTS = (("received", msg("Empfangszeit")), ("updated", msg("zuletzt bearbeitet")))
SEARCH_SCOPES = (
    ("all", msg("allem – auch Mailtext und Anhänge")),
    ("meta", msg("nur Absender, Betreff und Zusammenfassung")),
)
# Fields compared between two stored versions of a proposal.
VERSION_FIELDS = ('title', 'description', 'target', 'due', 'start', 'end', 'all_day', 'location', 'video_link',
                  'status', 'open_questions')


def _number(value: SupportsFloat | str, digits: int = 2) -> str:
    """German number format; callers show missing figures as "—" or "unbekannt"."""
    return decimal(float(value), digits)


def _money(value: SupportsFloat | str | None, currency: str) -> str:
    return msg("unbekannt") if value is None else f"{_number(value, 4)} {currency}"


def _calls(count: int, one: str, many: str) -> str:
    """Spoken link label, e.g. "1 fehlgeschlagenen Aufruf anzeigen" / "3 fehlgeschlagene Aufrufe anzeigen"."""
    return tr("{p0} {p1} anzeigen", p0=f"{count}", p1=f"{(one if count == 1 else many)}")


class _Html(str):
    """Markup that is already escaped."""


def _total_duration(seconds: float) -> str:
    """The readable sum; the exact seconds stay visible next to a larger unit (5.9.1)."""
    text = e(duration_text(seconds))
    return text if round(seconds, 1) < 60 else f'{text} <span class="meta">({_number(seconds, 0)} s)</span>'


def statistics_page(params: dict[str, Any], report: dict[str, Any], everything: list[dict[str, Any]], zone: str = "UTC",
                    now: datetime | None = None, steps: dict[str, Any] | None = None) -> str:
    """Costs and durations with readable labels and charts; unknown values are never shown as zero."""

    def choices(key: str) -> list[tuple[str, str]]:
        return [("", msg("alle"))] + [(value, value) for value in sorted({row[key] for row in everything})]

    narrowing = ("model", "provider", "stage", "since", "until")
    form = toolbar(
        "/auswertung",
        [
            select("days", msg("Zeitraum"), params["days"], list(PERIODS)),
            select("mode", "Erfassung", params["mode"], list(MODE_LABELS.items())),
        ],
        submit=msg("Auswerten"),
        active=sum(1 for key in narrowing if params.get(key)),
        reset="/auswertung" if any(params.get(key) for key in narrowing) else "",
        more=[
            select("model", msg("Modell"), params.get("model", ""), choices("model")),
            select("provider", msg("Anbieter"), params.get("provider", ""), choices("provider")),
            select("stage", "Verarbeitungsschritt", params.get("stage", ""), choices("stage")),
            date_field("since", msg("Von"), params.get("since")),
            date_field("until", msg("Bis"), params.get("until")),
        ],
    )
    rate = report["exchange_rate_date"]
    # 5.9.11: every figure opens the call list with a matching preset (a native link, no JavaScript).
    figures = _statistics_figures(report, rate)
    rows = [(name, _Html(metric_link(metric, value, label, params))) for name, metric, value, label in figures]
    rows += _run_time_rows(params, steps)
    head = page_head(
        msg("Auswertung"), msg("Einblicke"), tr("Kosten und Zeiten der KI-Aufrufe und Verarbeitungsschritte.")
    )
    measured = report["count"] or report["damaged"] or report["capture_failures"]
    if not measured and not (steps or {}).get("totals") and not (steps or {}).get("stages"):
        # 6.2.10: nothing measured – one sentence instead of a table full of zeros.
        return head + form + tr(_STATISTICS_PAGE_TEXT_2)
    # 6.2.10: every figure is a tile (label above the value); the pairs stay a definition list.
    tiles = "".join(f'<div class="kpi-tile"><dt>{e(k)}</dt><dd>{v if isinstance(v, _Html) else e(v)}</dd></div>'
                    for k, v in rows)
    body = (
        head
        + form
        + SECTIONS
        + tr('<h2 id="kennzahlen" class="visually-hidden">Kennzahlen</h2><dl class="kpi-grid">{p0}</dl>', p0=f"{tiles}")
        + tr(_STATISTICS_PAGE_TEXT_1)
    )
    link = "/auswertung/schritte?" + urlencode(filters(params))
    charts = statistics_charts(report["records"], params["days"], zone, now or datetime.now(UTC), steps, link)
    return body + charts + _statistics_groups(report["groups"])


# 6.2.10: jump links to the parts of a long page (about fourteen screen heights on a phone before).
SECTIONS = msg(
    '<nav class="page-sections" aria-label="Abschnitte der Auswertung"><a href="#kennzahlen">Kennzahlen</a>'
    '<a href="#diagramme">Diagramme</a><a href="#pipeline-title">Ablauf</a>'
    '<a href="#nach-modell">Nach Modell und Schritt</a></nav>'
)


def _run_time_rows(params: dict[str, Any], steps: dict[str, Any] | None) -> list[tuple[str, _Html]]:
    """6.1.8: run time per mail and the waiting for decisions; a link to the slowest runs."""
    total = (steps or {}).get("total") or {}
    if not total.get("count"):
        return []
    figures = " / ".join(duration_text(total[key] / 1000, precise=True) for key in ("median_ms", "p95_ms", "max_ms"))
    href = "/auswertung/schritte?" + urlencode({**filters(params), "stage": "total"})
    rows = [
        (
            msg("Durchlaufzeit je Mail (Median / 95 % / Maximum)"),
            _Html(
                tr(
                    ('<a class="fact-link" href="{p0}" aria-label="Langsamste Durchläufe anzeigen">{p1} ›</a>'),
                    p0=e(href),
                    p1=e(figures),
                )
            ),
        )
    ]
    waiting = (steps or {}).get("waiting_median_ms")
    if waiting:
        rows.append((msg("Wartezeit auf Entscheidungen (Median)"), _Html(e(duration_text(waiting / 1000)))))
    return rows


def _statistics_groups(groups: list[dict[str, Any]]) -> str:
    if not groups:
        return tr('<p class="empty">Für diese Auswahl gibt es keine erfassten Aufrufe.</p>')
    # Scrollable on phones, so it must be reachable by keyboard (axe scrollable-region-focusable).
    body = tr(
        '<h2 id="nach-modell">Nach Modell und Schritt</h2><div '
        'class="table-scroll" tabindex="0" role="region" aria-label="Nach '
        "Modell und "
        'Schritt"><table><thead><tr><th>Modell</th><th>Schritt</th><th>Anb'
        "ieter</th><th>Aufrufe</th><th>Fehler</th><th>Summe</th><th>Median"
        "</th><th>95 %</th><th>$Cent</th></tr></thead><tbody>"
    )
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
    return tr(
        ('<p class="search-hit"><span class="meta">Gefunden in {p0}:</span> {p1}<mark>{p2}</mark>{p3}</p>'),
        p0=e(hit.where),
        p1=e(hit.before),
        p2=e(hit.match),
        p3=e(hit.after),
    )


def _local_time(value: str | None, zone: str) -> str:
    if not value:
        return msg("Empfangszeit unbekannt")
    return format_datetime_local(datetime.fromisoformat(value), zone)


def _archive_filters(query: ArchiveQuery, topics: list[str], mailboxes: dict[str, tuple[int, str]]) -> str:

    status = "" if query.status is None else str(query.status)
    status_choices = [("", msg("alle"))] + [(item.value, label) for item, label in STATUS_LABELS.items()]
    filters = (
        select(
            "relevance",
            msg("Relevanz"),
            query.relevance,
            [("", msg("alle")), *((key, label) for key, label in RELEVANCE_LABELS.items())],
        )
        + select("topic", msg("Thema"), query.topic, [("", msg("alle")), *((topic, topic) for topic in topics)])
        + select("state", msg("Verarbeitung"), query.state, list(STATE_FILTERS))
        + select("status", msg("Vorschläge"), status, status_choices)
        + tr('<label>Von<input type="date" name="since" value="{p0}"></label>', p0=e(query.since or ""))
        + tr('<label>Bis<input type="date" name="until" value="{p0}"></label>', p0=e(query.until or ""))
        + select("sort", msg("Sortierung"), query.sort, list(SORTS))
    )
    if mailboxes:
        filters += select(
            "postfach",
            msg("Postfach"),
            "" if query.postfach is None else str(query.postfach),
            [("", msg("alle")), *((str(number), label) for number, label in sorted(mailboxes.values()))],
        )
    return filters


def _archive_row(item: dict[str, Any], zone: str, mailboxes: dict[str, tuple[int, str]], csrf: str = "") -> str:

    badges = [f'<span class="badge">{e(RELEVANCE_LABELS.get(item["relevance"], item["relevance"]))}</span>']
    if mailboxes:
        label = mailboxes.get(item["account"], (0, msg("Entferntes Postfach")))[1]
        badges.insert(0, f'<span class="badge">{e(label)}</span>')
    if item["waiting"]:
        badges.append(tr('<span class="badge warn">wartet auf dich</span>'))
    if item["failed"]:
        badges.append(tr('<span class="badge danger">Fehler</span>'))
    counts: dict[str, int] = {}
    for value in item["statuses"]:
        counts[value] = counts.get(value, 0) + 1
    badges += [status_badge(value, f"{count} × ") for value, count in sorted(counts.items())]
    summary = f'<p class="row-detail">{e(item["summary"])}</p>' if item["summary"] else ""
    recheck = (recheck_form(csrf, item["id"], item["recheck_round"], small=True)
               if csrf and item.get("recheck_round") is not None else "")
    return row(f'/mail/{item["id"]}', item["subject"],
               f'{sender_name(item["sender"])} · {_local_time(item["received"], zone)}', " ".join(badges),
               summary + _hit(item.get("hit")) + recheck + _failure(item, csrf))


def _failure(item: dict[str, Any], csrf: str) -> str:
    """7.3: cause, stage and attempts of a failed mail, with its actions and the report link."""
    if not item["failed"]:
        return ""
    if item["retry_pending"]:
        return tr(
            '<p class="row-detail">Erneuter Versuch angefordert; die Mail wird beim nächsten Abruf verarbeitet.</p>'
        )
    summary = error_summary(item["error_code"], item["error_stage"], item["error_attempts"])
    line = f'<p class="row-detail">{e(summary)}</p>'
    forms = failure_forms(csrf, item["id"], item["analysis_round"], retryable=item["retryable"], back_to_list=True)
    # Without JavaScript the link jumps to the report on the mail page; with it, a dialog opens.
    return line + forms + (f'<p><a class="button small" href="/mail/{e(item["id"])}#fehlerbericht" '
                           f'data-error-report>Details</a></p>')


def mail_list_page(query: ArchiveQuery, items: list[dict[str, Any]], total: int, damaged: int,
                   topics: list[str], zone: str, mailboxes: dict[str, tuple[int, str]] | None = None,
                   csrf: str = "", *, result: str = "") -> str:
    """Search and filters for stored mails; works without JavaScript."""
    mailboxes = mailboxes or {}
    active = sum(1 for value in (query.relevance, query.topic, query.state, query.status is not None, query.since,
                                 query.until, query.sort != "received", query.postfach) if value)
    body = (
        page_head(heading("Mails"), msg("Arbeitsbereich"), tr("Von Mailhelp gespeicherte Mails durchsuchen."))
        + chips("/mails", query.filter)
        + toolbar(
            "/mails",
            [
                search_field("q", msg("Suche"), query.q, hint_id='suche-hinweis'),
                select("scope", msg("Suchen in"), query.scope, list(SEARCH_SCOPES)),
            ],
            submit=msg("Suchen"),
            more=[_archive_filters(query, topics, mailboxes)],
            active=active,
            reset="/mails" if active or query.q or query.filter else "",
            hidden=_kept_filter(query),
            below=tr(_MAIL_LIST_PAGE_TEXT_2),
        )
    )
    body += result
    body += tr(
        '<p class="meta">{p0} · Seite {p1}</p>',
        p0=count_text(total, msg("gespeicherte Mail"), msg("gespeicherte Mails")),
        p1=query.page,
    )
    if not items:
        body += tr('<p class="empty">Keine gespeicherte Mail passt zu dieser Suche.</p>')
    body += f'<ul class="row-list">{"".join(_archive_row(item, zone, mailboxes, csrf) for item in items)}</ul>'
    pages = []
    for number, text in ((query.page - 1, msg("Vorherige Seite")), (query.page + 1, msg("Nächste Seite"))):
        if 1 <= number <= max(1, (total + query.size - 1) // query.size):
            parameters = query.model_dump(mode="json", exclude_none=True)
            parameters["page"] = number
            parameters = {k: v for k, v in parameters.items() if v not in ("", None)}
            pages.append(f'<a class="button" href="/mails?{e(urlencode(parameters))}">{text}</a>')
    if pages:
        body += f'<p class="actions">{" ".join(pages)}</p>'
    if damaged:
        body += notice(
            tr(("{p0} gespeicherte Datensätze sind beschädigt und werden nicht angezeigt."), p0=damaged), "warn"
        )
    return body + (tr(_MAIL_LIST_PAGE_TEXT_1))


def analysis_section(mail_id: str, state: MailState, record: dict[str, Any]) -> str:
    """The stored analysis of one mail; removed content says so instead of showing old values."""
    stored_relevance = state.relevance.model_dump(mode="json") if state.relevance else {}
    stored_summary = state.summary.model_dump(mode="json") if state.summary else {}
    relevance = {} if record.get("removed") else record.get("relevance") or stored_relevance
    summary = {} if record.get("removed") else record.get("summary") or stored_summary
    text = " ".join(summary.get("sentences", []))
    if not text:
        text = (
            msg("Nicht erforderlich (irrelevant).")
            if relevance.get("decision") == "irrelevant"
            else msg("Nicht vorhanden, noch nicht erstellt oder nach Aufbewahrung entfernt.")
        )
    human = state.relevance_dialog.decision if state.relevance_dialog else None
    topics = record.get("topics", {})
    names = [topics.get(identifier, identifier) for identifier in relevance.get("topic_ids", [])]
    body = tr('<section class="card"><h2>Zusammenfassung</h2><p>{p0}</p>', p0=f"{e(text)}")
    body += tr("<p>Fristen: {p0}</p><h2>Relevanz und Themen</h2>", p0=e("; ".join(summary.get("deadlines", []))))
    body += tr(
        "<p>Modellbewertung: {p0} · Quelle: {p1}</p>",
        p0=e(relevance.get("decision", msg("unbekannt"))),
        p1=e(record.get("source", msg("unbekannt"))),
    )
    body += tr(
        "<p>{p0}</p><p>Themen: {p1}</p>",
        p0=e(relevance.get("reason", msg("Keine Begründung mehr verfügbar"))),
        p1=e(", ".join(names)),
    )
    body += tr("<p>Menschliche Entscheidung: {p0}</p><h2>Erkannte Aktionen</h2><ul>", p0=e(human or msg("keine")))
    body += "".join(f'<li><a href="/vorschlag/{mail_id}/{e(p.id)}">{e(p.title)}</a> · {e(p.status.value)}</li>'
                    for p in state.proposals)
    return body + tr('</ul><a class="button" href="/verlauf?q={p0}">Verlauf dieser Mail</a></section>', p0=mail_id)


PATH_BADGES = {Outcome.DONE: "ok", Outcome.SKIPPED: "", Outcome.FAILED: "danger", Outcome.PENDING: "accent",
               Outcome.MISSING: "warn"}


def _path_step(step: Step, topics: dict[str, str], tag: str = "li") -> str:
    badge = f'<span class="badge {PATH_BADGES[step.outcome]}">{OUTCOME_LABELS[step.outcome]}</span>'
    body = (f'<{tag} class="path-step outcome-{step.outcome.value}"><p class="path-head"><strong>{e(step.title)}'
            f'</strong> {badge}</p><p>{e(step.text)}</p>')
    if step.topics:
        body += tr("<p>Themen: {p0}</p>", p0=e(", ".join(topics.get(topic, topic) for topic in step.topics)))
    if step.model_reason:
        body += tr(
            ('<p class="model-reason"><span class="meta">Modellbewertung, keine geprüfte Tatsache:</span> „{p0}“</p>'),
            p0=e(step.model_reason),
        )
    if step.notes:
        body += '<ul class="path-notes">' + "".join(f"<li>{e(note)}</li>" for note in step.notes) + "</ul>"
    return body + f"</{tag}>"


def _hints(hints: tuple[Hint, ...]) -> str:
    """5.1.4: possible contradictions with their evidence; never a claim of a missed action."""
    if not hints:
        return ""
    items = "".join(
        tr(
            (
                '<li class="hint-{p0}"><span class="badge {p1}">{p2}</span> {p3} '
                '<span class="meta">Beleg: {p4}</span></li>'
            ),
            p0=hint.severity,
            p1=hint.severity,
            p2=msg("Prüfen") if hint.severity == "warn" else msg("Hinweis"),
            p3=e(hint.text),
            p4=e(hint.evidence),
        )
        for hint in hints
    )
    return f'<h3>Prüfhinweise</h3><ul class="path-hints">{items}</ul>'


def processing_path_section(explanation: Explanation, topics: dict[str, str], hints: tuple[Hint, ...] = ()) -> str:
    """5.1.1: how this mail was actually processed, step by step, from stored results only."""
    steps = "".join(_path_step(step, topics) for step in explanation.steps)
    return (
        tr(
            (
                '<section class="card processing-path" '
                'aria-labelledby="verarbeitung-titel"><h2 '
                'id="verarbeitung-titel">So wurde diese Mail verarbeitet</h2><p '
                'class="meta">Analyserunde {p0} · aus gespeicherten Ergebnissen, '
                'ohne erneute Modellabfrage</p><ol class="path-steps">{p1}</ol>'
            ),
            p0=explanation.analysis_round,
            p1=steps,
        )
        + _path_step(explanation.result, topics, tag="div").replace(
            'class="path-step ', 'class="path-step path-result ', 1
        )
        + _hints(hints)
        + "</section>"
    )


HISTORY_STATUSES = [("", msg("alle")), *((key, msg(text)) for key, text in STATUSES.items() if key != "legacy")]
HISTORY_EVENTS = [
    ("", msg("alle")),
    *((key, msg(EVENTS[key])) for key in get_args(ArchiveQuery.model_fields["kind"].annotation) if key),
]


def _kept_filter(query: ArchiveQuery) -> str:
    """The quick filter chosen above the tool row stays selected when the form is sent."""
    return f'<input type="hidden" name="filter" value="{e(query.filter)}">' if query.filter else ""


def event_text(row: dict[str, Any], zone: str) -> str:
    """6.2.3: "14.11.2026, 07:12 Uhr · Verworfen · Weboberfläche" – never ISO times or internal values."""
    parts = [format_datetime_local(datetime.fromisoformat(row["at"]), zone)]
    if row["kind"] not in ("state", "legacy") and label(EVENTS, row["kind"]) != label(STATUSES, row["status"]):
        parts.append(label(EVENTS, row["kind"]))
    parts += [label(STATUSES, row["status"]), label(SOURCES, row["source"])]
    return " · ".join(parts)


def history_meta(entry: dict[str, Any], zone: str) -> str:
    """Time, what happened (when it says more than the status badge), who, and the version."""
    parts = [format_datetime_local(datetime.fromisoformat(entry["at"]), zone)]
    if entry["kind"] not in ("state", "legacy") and label(EVENTS, entry["kind"]) != label(STATUSES, entry["status"]):
        parts.append(label(EVENTS, entry["kind"]))
    parts.append(label(SOURCES, entry["source"]))
    if entry["version"]:
        parts.append(f'Version {entry["version"]}')
    return " · ".join(parts)


def revisions_list(mail_id: str, proposal_id: str, rows: list[dict[str, Any]], zone: str) -> str:
    if not rows:
        return tr('<p class="meta">Noch keine Revisionen erfasst.</p>')
    items = "".join(
        f'<li><a href="/vorschlag/{mail_id}/{e(proposal_id)}/version/{e(row["version"])}">'
        f'Version {e(row["version"])}</a> · {e(event_text(row, zone))}</li>'
        for row in rows)
    return f'<ul class="archive-list">{items}</ul>'


def history_page(query: ArchiveQuery, rows: list[dict[str, Any]], total: int, params: dict[str, Any],
                 zone: str) -> str:
    body = page_head(msg("Verlauf"), msg("Einblicke"), tr("Was mit Vorschlägen und Mails geschehen ist.")) + chips(
        "/verlauf", query.filter
    )
    more = sum(1 for value in (query.kind, query.since, query.until) if value)
    narrowed = more or query.q or query.status is not None or query.proposal_kind or query.filter
    body += toolbar(
        "/verlauf",
        [
            search_field("q", msg("Betreff, Absender oder Mail-ID"), query.q),
            select("status", "Status", "" if query.status is None else str(query.status), HISTORY_STATUSES),
            select("proposal_kind", msg("Art"), query.proposal_kind, [("", msg("alle")), *KINDS.items()]),
        ],
        submit=msg("Filtern"),
        active=more,
        reset="/verlauf" if narrowed else "",
        hidden=_kept_filter(query),
        more=[
            select("kind", msg("Ereignis"), query.kind, HISTORY_EVENTS),
            date_field("since", msg("Von"), query.since),
            date_field("until", msg("Bis"), query.until),
        ],
    )
    body += tr(
        '<p>{p0} · Seite {p1}</p><ul class="row-list">',
        p0=count_text(total, "Ereignis", msg("Ereignisse")),
        p1=query.page,
    )
    for entry in rows:
        link = (
            f"/vorschlag/{entry['mail_id']}/{entry['proposal_id']}/version/{entry['version']}"
            if entry["proposal_id"]
            else f"/mail/{entry['mail_id']}"
        )
        body += row(link, entry["title"], history_meta(entry, zone), status_badge(entry["status"]))
    body += '</ul>'
    if query.page > 1:
        params["page"] = query.page - 1
        body += tr('<a class="button" href="/verlauf?{p0}">Vorherige Seite</a>', p0=e(urlencode(params)))
    if query.page * query.size < total:
        params["page"] = query.page + 1
        body += tr('<a class="button" href="/verlauf?{p0}">Weitere Ereignisse</a>', p0=e(urlencode(params)))
    return body


def version_diff(previous: Proposal | None, current: Proposal) -> str:
    """Changed fields against the stored predecessor; a historical version is read only."""
    diff = tr('<section class="card"><h2>Änderungen gegenüber vorheriger Version</h2>')
    if previous is None:
        diff += tr("<p>Vorherige Version nicht vorhanden.</p>")
    else:
        before, after = previous.model_dump(mode="json"), current.model_dump(mode="json")
        diff += '<dl>' + ''.join(f'<dt>{e(key)}</dt><dd>{e(before[key])} → {e(after[key])}</dd>'
                                for key in VERSION_FIELDS if before[key] != after[key]) + '</dl>'
    return diff + tr("</section><p>Historische Version – ausschließlich lesend.</p>")


def _statistics_figures(report: dict[str, Any], rate: Any) -> list[tuple[str, str, str, str]]:
    figures: list[tuple[str, str, str, str]] = [
        (
            msg("Aufrufe (einzelne Versuche)"),
            "calls",
            e(report["count"]),
            _calls(report["count"], msg("Aufruf"), msg("Aufrufe")),
        ),
        (
            msg("davon fehlgeschlagen"),
            "failed",
            e(report["failed"]),
            _calls(report["failed"], msg("fehlgeschlagenen Aufruf"), msg("fehlgeschlagene Aufrufe")),
        ),
        (
            msg("Gemeldete Cloudkosten"),
            "cloud_costs",
            e(_money(report["usd"], "USD")),
            msg("Aufrufe mit Kostenangabe anzeigen"),
        ),
        (
            msg("Cloudaufrufe ohne Kostenangabe"),
            "unknown_cost",
            e(report["unknown_cost"]),
            _calls(report["unknown_cost"], msg("Cloudaufruf ohne Kostenangabe"), msg("Cloudaufrufe ohne Kostenangabe")),
        ),
        (
            msg("Cloudkosten in Euro"),
            "cloud_eur",
            e(
                _money(report["cloud_eur"], "EUR") + (tr(" (Wechselkurs vom {p0})", p0=f"{rate}") if rate else "")
                if report["cloud_eur"] is not None
                else msg("kein Wechselkurs hinterlegt")
            ),
            msg("Umrechnung und Aufrufe anzeigen"),
        ),
        (
            msg("Geschätzte Stromkosten Ollama"),
            "electricity",
            e(_money(report["electricity_eur"], "EUR")),
            msg("Ollama-Aufrufe und Berechnung anzeigen"),
        ),
        (msg("Summierte Aufrufdauer"), "duration", _total_duration(report["seconds"]), msg("Längste Aufrufe anzeigen")),
        (
            msg("Dauer je Aufruf (Mittel / Median / 95 %)"),
            "distribution",
            e(
                " / ".join(
                    duration_text(report[key], precise=True) if report[key] is not None else "—"
                    for key in ("mean", "median", "p95")
                )
            ),
            msg("Verteilung der Aufrufdauer anzeigen"),
        ),
    ]
    if report["damaged"] or report["capture_failures"]:
        figures.append(
            (
                "Unvollständige Erfassung",
                "incomplete",
                e(
                    tr(
                        "{p0} beschädigte Zeilen, {p1} Erfassungsfehler",
                        p0=report["damaged"],
                        p1=report["capture_failures"],
                    )
                ),
                msg("Bedeutung der unvollständigen Erfassung anzeigen"),
            )
        )
    return figures
