"""Charts of the evaluation page as server-side SVG (3.3.9).

The content security policy allows neither inline scripts nor inline styles, so the charts are plain
SVG with presentation attributes and CSS classes; colours follow the light and dark theme of app.css.
Each chart carries a title and description for assistive technology and its values as a table.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from .pages import e

WIDTH, HEIGHT, LEFT, BOTTOM, TOP = 640, 220, 56, 28, 12
# Upper limits of the duration classes in seconds; the last class is open.
DURATION_CLASSES = ((1, "< 1 s"), (2, "1–2 s"), (5, "2–5 s"), (10, "5–10 s"), (30, "10–30 s"), (60, "30–60 s"),
                    (None, "> 60 s"))
MAX_BARS = 8
# Presentation attributes as fallback; class rules in app.css (light and dark theme) take precedence.
FILLS = {"chart-ok": "#176b4d", "chart-bar": "#176b4d", "chart-failed": "#a3262b", "chart-cost": "#7a5200"}
AXIS = 'fill="#526577" font-size="11"'
BAR_ROW = 28

Series = tuple[str, str, list[float]]


def _number(value: float, digits: int) -> str:
    return f"{value:,.{digits}f}".replace(",", " ").replace(".", ",").replace(" ", ".")


def _scale(maximum: float) -> float:
    """A round upper end of the value axis."""
    if maximum <= 0:
        return 1.0
    magnitude = 10.0 ** math.floor(math.log10(maximum))
    return next((magnitude * factor for factor in (1, 2, 2.5, 5) if magnitude * factor >= maximum), magnitude * 10)


def _figure(ident: str, title: str, description: str, svg: str, header: list[str], rows: list[list[str]],
            height: float = HEIGHT) -> str:
    table = ('<details><summary>Werte als Tabelle</summary><div class="table-scroll" tabindex="0" '
             f'role="region" aria-label="Wertetabelle: {e(title)}"><table><thead><tr>'
             + "".join(f"<th>{e(cell)}</th>" for cell in header) + "</tr></thead><tbody>"
             + "".join("<tr>" + "".join(f"<td>{e(cell)}</td>" for cell in row) + "</tr>" for row in rows)
             + "</tbody></table></div></details>")
    return (f'<figure class="chart" aria-labelledby="{ident}-title"><figcaption>'
            f'<span id="{ident}-title">{e(title)}</span><button type="button" class="button small chart-zoom" '
            f'aria-label="{e(title)} vergrößern" aria-haspopup="dialog" hidden>Vergrößern</button></figcaption>'
            f'<div class="chart-plot" tabindex="0" role="group" aria-label="Diagramm: {e(title)}">'
            f'<svg viewBox="0 0 {WIDTH} {height:.0f}" role="group" '
            f'aria-labelledby="{ident}-svg-title '
            f'{ident}-svg-desc" preserveAspectRatio="xMidYMid meet"><title id="{ident}-svg-title">{e(title)}</title>'
            f'<desc id="{ident}-svg-desc">{e(description)}</desc>{svg}</svg>'
            '<div class="chart-detail" tabindex="0" role="group" aria-label="Balkendetails">'
            '<p class="chart-hint" aria-hidden="true">'
            'Balken für Details berühren, mit der Maus zeigen oder per Tab fokussieren.</p>'
            f'<p class="chart-tooltip" role="tooltip" hidden></p></div></div>{table}</figure>')


def _point(detail: str) -> str:
    """Escaped details are readable with SVG titles, keyboard focus and the optional tooltip."""
    return f'data-chart-detail="{e(detail)}" tabindex="0" role="img" aria-label="{e(detail)}"'


def column_chart(ident: str, title: str, description: str, labels: list[str], series: list[Series],
                 fmt: Callable[[float], str]) -> str:
    """Stacked columns, one per label; the series are drawn bottom-up in their order."""
    totals = [sum(values[index] for _, _, values in series) for index in range(len(labels))]
    top = _scale(max(totals, default=0))
    plot_width, plot_height = WIDTH - LEFT - 8, HEIGHT - BOTTOM - TOP
    slot = plot_width / max(len(labels), 1)
    svg = ""
    for step in range(5):
        y = TOP + plot_height - plot_height * step / 4
        svg += (f'<line class="chart-grid" stroke="#dae3eb" x1="{LEFT}" x2="{WIDTH - 8}" y1="{y:.1f}" y2="{y:.1f}"/>'
                f'<text class="chart-axis" {AXIS} x="{LEFT - 6}" y="{y + 4:.1f}" text-anchor="end">'
                f'{e(fmt(top * step / 4))}'
                "</text>")
    every = max(1, round(len(labels) / 10))
    for index, label in enumerate(labels):
        x, base = LEFT + slot * index + slot * 0.15, float(TOP + plot_height)
        for name, css, values in series:
            height = plot_height * values[index] / top
            if height > 0:
                base -= height
                detail = f"{label}: {name} {fmt(values[index])}"
                svg += (f'<rect class="{css}" fill="{FILLS[css]}" x="{x:.1f}" y="{base:.1f}" width="{slot * 0.7:.1f}" '
                        f'height="{height:.1f}" {_point(detail)}><title>{e(detail)}</title></rect>')
        if index % every == 0:
            svg += (f'<text class="chart-axis" {AXIS} x="{x + slot * 0.35:.1f}" y="{HEIGHT - 8}" '
                    f'text-anchor="middle">{e(label)}</text>')
    legend = "".join(f'<tspan class="{css}-text" fill="{FILLS[css]}" dx="{12 if position else 0}">■ {e(name)}</tspan>'
                     for position, (name, css, _) in enumerate(series))
    svg += f'<text class="chart-legend" {AXIS} x="{WIDTH - 8}" y="{TOP + 2}" text-anchor="end">{legend}</text>'
    rows = [[label, *(fmt(values[index]) for _, _, values in series)] for index, label in enumerate(labels)]
    return _figure(ident, title, description, svg, ["", *(name for name, _, _ in series)], rows)


def bar_list(ident: str, title: str, description: str, items: list[tuple[str, float]],
             fmt: Callable[[float], str], css: str = "chart-bar") -> str:
    """Horizontal bars, largest first; further entries are summed up as "Weitere"."""
    items = sorted(items, key=lambda item: -item[1])
    if len(items) > MAX_BARS:
        items = [*items[:MAX_BARS - 1], ("Weitere", sum(value for _, value in items[MAX_BARS - 1:]))]
    top = _scale(max((value for _, value in items), default=0))
    # A fixed row height: few entries make a short chart instead of thick bars.
    row_height = BAR_ROW
    label_width, svg = 190, ""
    for index, (label, value) in enumerate(items):
        y = TOP + row_height * index
        width = (WIDTH - label_width - 90) * value / top
        short = label if len(label) <= 28 else label[:27] + "…"
        detail = f"{label}: {fmt(value)}"
        svg += (f'<text class="chart-axis" {AXIS} x="{label_width - 8}" y="{y + row_height * 0.62:.1f}" '
                f'text-anchor="end">{e(short)}</text>'
                f'<rect class="{css}" fill="{FILLS[css]}" x="{label_width}" y="{y + row_height * 0.18:.1f}" '
                f'width="{width:.1f}" '
                f'height="{row_height * 0.64:.1f}" {_point(detail)}><title>{e(detail)}</title></rect>'
                f'<text class="chart-axis" {AXIS} x="{label_width + width + 6:.1f}" y="{y + row_height * 0.62:.1f}">'
                f'{e(fmt(value))}</text>')
    return _figure(ident, title, description, svg, ["", title], [[label, fmt(value)] for label, value in items],
                   height=TOP + 4 + row_height * max(len(items), 1))


def _buckets(records: list[dict[str, Any]], days: int, zone: ZoneInfo, now: datetime
             ) -> tuple[list[str], Callable[[dict[str, Any]], int | None]]:
    """Hours of the last day, otherwise the calendar days of the period, in the configured zone."""
    local_now = now.astimezone(zone)
    if days == 1:
        start = local_now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=23)
        labels = [f"{(start + timedelta(hours=hour)):%H} Uhr" for hour in range(24)]

        def hour(record: dict[str, Any]) -> int | None:
            index = int((datetime.fromisoformat(record["started_at"]).astimezone(zone) - start).total_seconds() // 3600)
            return index if 0 <= index < 24 else None
        return labels, hour
    first = local_now.date() - timedelta(days=days - 1)
    labels = [f"{first + timedelta(days=offset):%d.%m.}" for offset in range(days)]

    def day(record: dict[str, Any]) -> int | None:
        index = (datetime.fromisoformat(record["started_at"]).astimezone(zone).date() - first).days
        return index if 0 <= index < days else None
    return labels, day


def count(value: float) -> str:
    return _number(value, 0)


def dollars(value: float) -> str:
    return _number(value, 4) + " $"


def seconds(value: float) -> str:
    return _number(value, 1) + " s"


def statistics_charts(records: list[dict[str, Any]], days: int, zone: str, now: datetime) -> str:
    """Calls, costs, durations and their distribution over steps and models of the selected records."""
    if not records:
        return ""
    tz = ZoneInfo(zone)
    labels, bucket = _buckets(records, days, tz, now)
    succeeded, failed, costs = [0.0] * len(labels), [0.0] * len(labels), [0.0] * len(labels)
    for record in records:
        index = bucket(record)
        if index is None:
            continue
        (succeeded if record["status"] == "success" else failed)[index] += 1
        costs[index] += float(Decimal(record["cost_usd"])) if record["cost_usd"] is not None else 0.0
    period = "Stunde" if days == 1 else "Tag"
    durations = [record["duration_ms"] / 1000 for record in records]
    classes = [0.0] * len(DURATION_CLASSES)
    for value in durations:
        classes[next(index for index, (limit, _) in enumerate(DURATION_CLASSES) if limit is None or value < limit)] += 1
    by_stage: dict[str, float] = {}
    by_model: dict[str, float] = {}
    for record in records:
        by_stage[record["stage"]] = by_stage.get(record["stage"], 0.0) + record["duration_ms"] / 1000
        if record["cost_usd"] is not None:
            model = record["model"].rsplit("/", 1)[-1]
            by_model[model] = by_model.get(model, 0.0) + float(Decimal(record["cost_usd"]))
    body = '<h2>Verlauf und Verteilung</h2><div class="chart-grid-layout">'
    body += column_chart("chart-calls", f"KI-Aufrufe je {period}",
                         f"Erfolgreiche und fehlgeschlagene Aufrufe je {period} im gewählten Zeitraum.", labels,
                         [("erfolgreich", "chart-ok", succeeded), ("fehlgeschlagen", "chart-failed", failed)], count)
    body += column_chart("chart-costs", f"Gemeldete Cloudkosten je {period}",
                         f"Vom Anbieter gemeldete Kosten in US-Dollar je {period}; Aufrufe ohne Angabe fehlen.",
                         labels, [("Kosten", "chart-cost", costs)], dollars)
    body += column_chart("chart-durations", "Verteilung der Aufrufdauer",
                         "Anzahl der Aufrufe je Dauerklasse.", [label for _, label in DURATION_CLASSES],
                         [("Aufrufe", "chart-bar", classes)], count)
    body += bar_list("chart-stages", "Summierte Dauer je Verarbeitungsschritt",
                     "Summe der Aufrufdauer je Schritt, größter zuerst.", list(by_stage.items()), seconds)
    if by_model:
        body += bar_list("chart-models", "Gemeldete Kosten je Modell",
                         "Summe der gemeldeten Kosten in US-Dollar je Modell, größtes zuerst.",
                         list(by_model.items()), dollars, css="chart-cost")
    return body + "</div>"


__all__ = ["DURATION_CLASSES", "bar_list", "column_chart", "statistics_charts"]
