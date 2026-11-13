"""The call list behind every figure of the evaluation page (5.9.11).

One read-only page with a preset per figure instead of nine detail pages. It shows only metadata
from the content-free metric journal; the subject of a mail comes from its stored state and is
escaped like everywhere else.
"""
from __future__ import annotations

import math
import statistics
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

from ..formatting import duration_text, format_datetime_local
from ..review.views import STAGE_LABELS
from .pages import e, notice

FILTER_KEYS = ("days", "mode", "model", "provider", "stage", "since", "until")
SORTS = {"time": "Zeit", "duration": "Dauer", "cost": "Kosten"}
# A value of its own for "alle": empty query values are dropped and could not override a preset.
STATUSES = {"alle": "alle", "success": "erfolgreich", "failed": "fehlgeschlagen"}
PAGE_SIZE = 100
ERROR_LABELS = {"timeout": "Zeitüberschreitung", "rate_limited": "Anfragelimit des Anbieters erreicht",
                "provider_error": "Fehler oder ungültige Antwort des Anbieters",
                "invalid_json": "Antwort war kein JSON",
                "schema_invalid": "Antwort passte nicht zum erwarteten Schema", "cancelled": "abgebrochen",
                "other": "sonstige Ursache", None: "Ursache nicht erfasst (vor 5.9)"}


@dataclass(frozen=True)
class Metric:
    title: str
    explanation: str
    sort: str
    status: str = "alle"


METRICS = {
    "calls": Metric("Aufrufe (einzelne Versuche)", "Jeder Versuch zählt einzeln, auch Wiederholungen.", "time"),
    "failed": Metric("Fehlgeschlagene Aufrufe", "Fehlgeschlagene Versuche, nach Ursache gezählt.", "time", "failed"),
    "cloud_costs": Metric("Gemeldete Cloudkosten", "Vom Anbieter gemeldete Kosten, teuerste Aufrufe zuerst.", "cost"),
    "unknown_cost": Metric("Cloudaufrufe ohne Kostenangabe", "Der Anbieter hat keine Nutzungsdaten gemeldet; "
                           "die Kosten sind unbekannt, nicht null.", "time"),
    "cloud_eur": Metric("Cloudkosten in Euro", "Die gemeldeten Kosten in US-Dollar, umgerechnet mit dem "
                        "eingestellten Kurs.", "cost"),
    "electricity": Metric("Geschätzte Stromkosten Ollama", "Belegte Serverzeit × Leistung × Strompreis; die "
                          "Serverzeit wird je Server mit zusammengeführten Überlappungen ermittelt.", "time"),
    "duration": Metric("Summierte Aufrufdauer", "Summe aller Versuche; keine Durchlaufzeit.", "duration"),
    "distribution": Metric("Dauer je Aufruf", "Verteilung der Dauer einzelner Versuche, längste zuerst.",
                           "duration"),
    "incomplete": Metric("Unvollständige Erfassung", "Beschädigte Zeilen konnten nicht gelesen werden; "
                         "Erfassungsfehler sind Aufrufe, deren Messwerte nicht geschrieben werden konnten. Details "
                         "stehen in den Protokollen (logs/mailhelp.jsonl).", "time"),
}


def _number(value: float, digits: int) -> str:
    return f"{value:,.{digits}f}".replace(",", " ").replace(".", ",").replace(" ", ".")


def filters(params: dict[str, Any]) -> dict[str, str]:
    """The active evaluation filters, carried over to links in both directions."""
    return {key: str(params[key]) for key in FILTER_KEYS if params.get(key) not in (None, "")}


def link(metric: str, params: dict[str, Any], **extra: str) -> str:
    return "/auswertung/aufrufe?" + urlencode({"metric": metric, **filters(params), **extra})


def metric_link(metric: str, value: str, label: str, params: dict[str, Any]) -> str:
    """A figure as a native link (works without JavaScript); *value* is already escaped markup."""
    return f'<a class="fact-link" href="{e(link(metric, params))}" aria-label="{e(label)}">{value} ›</a>'


def preset(metric: str, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if metric == "cloud_costs" or metric == "cloud_eur":
        return [row for row in records if row["cost_usd"] is not None]
    if metric == "unknown_cost":
        return [row for row in records if row["cost_usd"] is None and row["provider"] != "ollama"]
    if metric == "electricity":
        return [row for row in records if row["provider"] == "ollama"]
    if metric == "incomplete":
        return []
    return records


def ordered(records: list[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
    """Descending; calls without a reported cost come last when sorted by cost."""
    if sort == "duration":
        return sorted(records, key=lambda row: (-row["duration_ms"], row["started_at"]))
    if sort == "cost":
        return sorted(records, key=lambda row: (row["cost_usd"] is None, -Decimal(row["cost_usd"] or "0"),
                                                row["started_at"]))
    return sorted(records, key=lambda row: row["started_at"], reverse=True)


def _quantile(values: list[float], share: float) -> float:
    return values[max(0, math.ceil(len(values) * share) - 1)]


def _explanation(metric: str, rows: list[dict[str, Any]], report: dict[str, Any], settings: Any) -> str:
    """The box above the list: what the figure means, with the numbers that explain it."""
    body = f"<p>{e(METRICS[metric].explanation)}</p>"
    if metric == "failed":
        causes: dict[str | None, int] = {}
        for row in rows:
            causes[row.get("error_kind")] = causes.get(row.get("error_kind"), 0) + 1
        body += "<ul>" + "".join(f"<li>{e(ERROR_LABELS[kind])}: {count}</li>" for kind, count in
                                 sorted(causes.items(), key=lambda item: (-item[1], str(item[0])))) + "</ul>"
    if metric in {"cloud_costs", "cloud_eur"}:
        models: dict[str, Decimal] = {}
        for row in rows:
            models[row["model"]] = models.get(row["model"], Decimal(0)) + Decimal(row["cost_usd"])
        body += "<ul>" + "".join(f"<li>{e(model)}: {_number(float(usd), 4)} $</li>"
                                 for model, usd in sorted(models.items(), key=lambda item: -item[1])) + "</ul>"
    if metric == "cloud_eur":
        rate = settings.usd_per_eur
        body += (f"<p>EUR = USD ÷ {_number(rate, 4)}"
                 + (f" (Kurs vom {e(settings.exchange_rate_date)})" if settings.exchange_rate_date else "") + ".</p>"
                 if rate else "<p>Kein Wechselkurs hinterlegt.</p>")
    if metric == "electricity":
        body += (f"<p>Eingestellt: {_number(settings.ollama_power_watts, 0)} W, "
                 f"{_number(settings.electricity_eur_per_kwh, 2)} €/kWh.</p>")
    if metric == "distribution" and rows:
        values = sorted(row["duration_ms"] / 1000 for row in rows)
        figures = [("Mittel", statistics.mean(values)), ("Median", statistics.median(values)),
                   ("90 %", _quantile(values, .9)), ("95 %", _quantile(values, .95)), ("99 %", _quantile(values, .99)),
                   ("Maximum", values[-1])]
        body += "<p>" + " · ".join(f"{name} {e(duration_text(value, precise=True))}"
                                   for name, value in figures) + "</p>"
    if metric == "incomplete":
        body += (f"<p>{report['damaged']} beschädigte Zeilen, {report['capture_failures']} Erfassungsfehler. "
                 "Zu diesen Fällen gibt es keine Einzelaufrufe.</p>")
    return f'<section class="card calls-explanation">{body}</section>'


def _mail(row: dict[str, Any], subject: Callable[[str], str | None]) -> str:
    if row.get("test_mail_hash") or row["mode"] == "decision_test":
        return "Vergleichslauf"
    if not row.get("mail_id"):
        return "—"
    title = subject(row["mail_id"])
    if title is None:
        return "Mail nicht mehr gespeichert"
    return f'<a href="/mail/{e(row["mail_id"])}">{e(title)}</a>'


def _row(row: dict[str, Any], zone: str, subject: Callable[[str], str | None]) -> str:
    tokens = row.get("tokens") or {}
    pair = " / ".join(_number(tokens[key], 0) if tokens.get(key) is not None else "—"
                      for key in ("prompt_tokens", "completion_tokens"))
    if row["status"] == "success":
        status = '<span class="badge ok">Erfolg</span>'
    else:
        status = (f'<span class="badge warn">Fehler</span> '
                  f'<span class="meta">{e(ERROR_LABELS[row.get("error_kind")])}</span>')
    cost = "unbekannt" if row["cost_usd"] is None else f"{_number(float(row['cost_usd']), 4)} $"
    cells = [e(format_datetime_local(datetime.fromisoformat(row["started_at"]), zone)),
             e(STAGE_LABELS.get(row["stage"], row["stage"])),
             f'{e(row["model"])}<br><span class="meta">{e(row["provider"])}</span>', status,
             e(duration_text(row["duration_ms"] / 1000, precise=True)), pair, cost, _mail(row, subject)]
    return "<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>"


def _pages(metric: str, params: dict[str, Any], sort: str, status: str, page: int, total: int) -> str:
    count = max(1, math.ceil(total / PAGE_SIZE))
    parts = [f"{total} {'Aufruf' if total == 1 else 'Aufrufe'} · Seite {page} von {count}"]
    if page > 1:
        parts.append(f'<a href="{e(link(metric, params, sort=sort, status=status, page=str(page - 1)))}">'
                     "‹ Vorherige Seite</a>")
    if page < count:
        parts.append(f'<a href="{e(link(metric, params, sort=sort, status=status, page=str(page + 1)))}">'
                     "Nächste Seite ›</a>")
    return f'<p class="calls-pages">{" · ".join(parts)}</p>'


def describe(params: dict[str, Any], labels: dict[str, str]) -> str:
    """The active filter as readable text."""
    names = {"model": "Modell", "provider": "Anbieter", "stage": "Schritt", "since": "von", "until": "bis"}
    parts = [f"Zeitraum: {params['days']} {'Tag' if int(params['days']) == 1 else 'Tage'}",
             f"Erfassung: {labels.get(params['mode'], params['mode'])}"]
    parts += [f"{names[key]}: {STAGE_LABELS.get(params[key], params[key]) if key == 'stage' else params[key]}"
              for key in names if params.get(key)]
    return " · ".join(parts)


def calls_page(metric: str, params: dict[str, Any], sort: str, status: str | None, page: int, report: dict[str, Any],
               settings: Any, zone: str, subject: Callable[[str], str | None], labels: dict[str, str]) -> str:
    info = METRICS[metric]
    sort = sort or info.sort
    # Without an explicit choice the figure decides, e.g. only failed calls for "davon fehlgeschlagen".
    status = info.status if status is None else status
    rows = [row for row in preset(metric, report["records"]) if status == "alle" or row["status"] == status]
    rows = ordered(rows, sort)
    back = "/auswertung" + ("?" + urlencode(filters(params)) if filters(params) else "")
    form = ('<form method="get" class="filters calls-filters">'
            f'<input type="hidden" name="metric" value="{e(metric)}">'
            + "".join(f'<input type="hidden" name="{key}" value="{e(value)}">'
                      for key, value in filters(params).items())
            + '<label>Status<select name="status">'
            + "".join(f'<option value="{key}"{" selected" if key == status else ""}>{text}</option>'
                      for key, text in STATUSES.items())
            + '</select></label><label>Sortierung (absteigend)<select name="sort">'
            + "".join(f'<option value="{key}"{" selected" if key == sort else ""}>{text}</option>'
                      for key, text in SORTS.items())
            + '</select></label><button class="button">Anzeigen</button></form>')
    body = (f'<p><a href="{e(back)}">← Zurück zur Auswertung</a></p><h1>{e(info.title)}</h1>'
            f'<p class="meta">{e(describe(params, labels))}</p>'
            + _explanation(metric, rows, report, settings))
    if int(params["days"]) > settings.retention_days or (
            params.get("since") and (datetime.now().date() - datetime.fromisoformat(params["since"]).date()).days
            > settings.retention_days):
        body += notice(f"Einzelaufrufe liegen nur für die letzten {settings.retention_days} Tage vor; "
                       "die Summen der Auswertung enthalten ältere Tage.", "info")
    if metric == "incomplete":
        return body
    body += form
    if not rows:
        return body + '<p class="empty">Für diese Auswahl gibt es keine erfassten Aufrufe.</p>'
    page = min(page, max(1, math.ceil(len(rows) / PAGE_SIZE)))
    shown = rows[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
    pages = _pages(metric, params, sort, status, page, len(rows))
    table = ('<div class="table-scroll" tabindex="0" role="region" aria-label="Aufrufe"><table class="calls-table">'
             "<thead><tr>" + "".join(f'<th scope="col">{name}</th>' for name in (
                 "Zeit", "Schritt", "Modell / Anbieter", "Status", "Dauer", "Tokens (Eingabe / Ausgabe)", "Kosten",
                 "Mail"))
             + "</tr></thead><tbody>" + "".join(_row(row, zone, subject) for row in shown)
             + "</tbody></table></div>")
    return body + pages + table + pages


__all__ = ["METRICS", "calls_page", "metric_link"]
