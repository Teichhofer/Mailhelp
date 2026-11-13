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

from ..formatting import duration_text
from .pages import e

WIDTH, HEIGHT, LEFT, BOTTOM, TOP = 640, 220, 56, 28, 12
# 5.9.9: call durations as a logarithmic scatter plot; at most this many points are drawn.
MAX_POINTS = 3000
FLOOR = 0.1
MAX_BARS = 8
# Presentation attributes as fallback; class rules in app.css (light and dark theme) take precedence.
FILLS = {"chart-ok": "#176b4d", "chart-bar": "#176b4d", "chart-failed": "#a3262b", "chart-cost": "#7a5200",
         "chart-average": "#1d4ed8", "chart-trend": "#0f172a", "chart-dot": "#176b4d", "chart-cross": "#a3262b"}
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


HINT = "Balken für Details berühren, mit der Maus zeigen oder per Tab fokussieren."


def _figure(ident: str, title: str, description: str, svg: str, header: list[str], rows: list[list[str]],
            height: float = HEIGHT, hint: str = HINT, subtitle: str = "") -> str:
    table = ('<details><summary>Werte als Tabelle</summary><div class="table-scroll" tabindex="0" '
             f'role="region" aria-label="Wertetabelle: {e(title)}"><table><thead><tr>'
             + "".join(f"<th>{e(cell)}</th>" for cell in header) + "</tr></thead><tbody>"
             + "".join("<tr>" + "".join(f"<td>{e(cell)}</td>" for cell in row) + "</tr>" for row in rows)
             + "</tbody></table></div></details>")
    return (f'<figure class="chart" aria-labelledby="{ident}-title"><figcaption>'
            f'<span id="{ident}-title">{e(title)}</span><button type="button" class="button small chart-zoom" '
            f'aria-label="{e(title)} vergrößern" aria-haspopup="dialog" hidden>Vergrößern</button></figcaption>'
            + (f'<p class="meta chart-subtitle">{e(subtitle)}</p>' if subtitle else "") +
            f'<div class="chart-plot" tabindex="0" role="group" aria-label="Diagramm: {e(title)}">'
            f'<svg viewBox="0 0 {WIDTH} {height:.0f}" role="group" '
            f'aria-labelledby="{ident}-svg-title '
            f'{ident}-svg-desc" preserveAspectRatio="xMidYMid meet"><title id="{ident}-svg-title">{e(title)}</title>'
            f'<desc id="{ident}-svg-desc">{e(description)}</desc>{svg}</svg>'
            '<div class="chart-detail" tabindex="0" role="group" aria-label="Balkendetails">'
            f'<p class="chart-hint" aria-hidden="true">{e(hint)}</p>'
            f'<p class="chart-tooltip" role="tooltip" hidden></p></div></div>{table}</figure>')


def _point(detail: str) -> str:
    """Escaped details are readable with SVG titles, keyboard focus and the optional tooltip."""
    return f'data-chart-detail="{e(detail)}" tabindex="0" role="img" aria-label="{e(detail)}"'


def column_chart(ident: str, title: str, description: str, labels: list[str], series: list[Series],
                 fmt: Callable[[float], str], *, average: tuple[str, float] | None = None,
                 trend: tuple[str, list[float | None]] | None = None,
                 summary: list[list[str]] | None = None) -> str:
    """Stacked columns, one per label; the series are drawn bottom-up in their order.

    5.9.8: *average* is a dashed line with its value in the legend; *trend* a straight polyline
    through the column centres that is interrupted where a value is missing; *summary* rows
    follow the per-label rows of the value table.
    """
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

    def level(value: float) -> float:
        return TOP + plot_height - plot_height * value / top
    if average is not None:
        y = level(average[1])
        svg += (f'<line class="chart-average-line" stroke="{FILLS["chart-average"]}" stroke-width="1.5" '
                f'stroke-dasharray="5 3" x1="{LEFT}" x2="{WIDTH - 8}" y1="{y:.1f}" y2="{y:.1f}">'
                f'<title>{e(average[0])}</title></line>')
        legend += (f'<tspan class="chart-average-text" fill="{FILLS["chart-average"]}" dx="12">'
                   f'┄ {e(average[0])}</tspan>')
    if trend is not None:
        path, pen = "", False
        for index, value in enumerate(trend[1]):
            if value is None:
                pen = False
                continue
            path += f'{"L" if pen else "M"}{LEFT + slot * index + slot * 0.5:.1f} {level(value):.1f} '
            pen = True
        if path:
            svg += (f'<path class="chart-cost-trend" stroke="{FILLS["chart-trend"]}" stroke-width="2" fill="none" '
                    f'd="{path.strip()}"><title>{e(trend[0])}</title></path>')
        legend += f'<tspan class="chart-trend-text" fill="{FILLS["chart-trend"]}" dx="12">— {e(trend[0])}</tspan>'
    svg += f'<text class="chart-legend" {AXIS} x="{WIDTH - 8}" y="{TOP + 2}" text-anchor="end">{legend}</text>'
    rows = [[label, *(fmt(values[index]) for _, _, values in series)] for index, label in enumerate(labels)]
    header = ["", *(name for name, _, _ in series)]
    if trend is not None:
        header.append(trend[0])
        for row, value in zip(rows, trend[1], strict=True):
            row.append("—" if value is None else fmt(value))
    return _figure(ident, title, description, svg, header, rows + (summary or []))


def cost_lines(records: list[dict[str, Any]], costs: list[float], bucket: Callable[[dict[str, Any]], int | None],
               days: int) -> tuple[float | None, list[float | None] | None]:
    """5.9.8: average from the first period with a recorded call; 7-day mean from 14 days on.

    Calls without a reported cost count as zero, as in the columns; periods before the first
    recorded call would lower the average artificially and are left out.
    """
    used = [index for record in records if (index := bucket(record)) is not None]
    if not used:
        return None, None
    first = min(used)
    average = sum(costs[first:]) / (len(costs) - first)
    if days < 14:
        return average, None
    return average, [sum(costs[index - 6:index + 1]) / 7 if index - first >= 6 else None
                     for index in range(len(costs))]


def bar_list(ident: str, title: str, description: str, items: list[tuple[str, float]],
             fmt: Callable[[float], str], css: str = "chart-bar",
             table: tuple[list[str], list[list[str]]] | None = None) -> str:
    """Horizontal bars, largest first; further entries are summed up as "Weitere".

    *table* (5.9.10) replaces the default value table with own columns.
    """
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
    header, rows = table if table is not None else (["", title], [[label, fmt(value)] for label, value in items])
    return _figure(ident, title, description, svg, header, rows, height=TOP + 4 + row_height * max(len(items), 1))


def _quantile(values: list[float], share: float) -> float:
    """Nearest-rank quantile of a non-empty list."""
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(share * len(ordered)) - 1))]


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def thin(records: list[dict[str, Any]], limit: int = MAX_POINTS) -> list[dict[str, Any]]:
    """5.9.9: keep every failure and every call above the 95 % value, then a fixed stride of the rest.

    Deterministic (no randomness), so the same records always give the same picture.
    """
    if len(records) <= limit:
        return records
    p95 = _quantile([record["duration_ms"] for record in records], 0.95)
    kept = {index for index, record in enumerate(records)
            if record["status"] != "success" or record["duration_ms"] > p95}
    rest = [index for index in range(len(records)) if index not in kept]
    room = max(0, limit - len(kept))
    chosen = {rest[position * len(rest) // room] for position in range(room)} if room else set()
    return [record for index, record in enumerate(records) if index in kept or index in chosen]


def _seconds_text(value: float) -> str:
    return "< 0,1 s" if value < FLOOR else duration_text(value)


def _period_start(days: int, zone: ZoneInfo, now: datetime) -> tuple[datetime, timedelta]:
    local_now = now.astimezone(zone)
    if days == 1:
        return local_now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=23), timedelta(hours=24)
    first = local_now.date() - timedelta(days=days - 1)
    return datetime(first.year, first.month, first.day, tzinfo=zone), timedelta(days=days)


def _duration_grid(top: float, y_of: Callable[[float], float]) -> str:
    """Labelled lines at 0.1 s, 1 s, 10 s, …; fine unlabelled lines at 2 and 5 of each decade."""
    svg, exponent = "", -1
    while 10.0 ** exponent <= top * 1.0001:
        mark = 10.0 ** exponent
        y = y_of(mark)
        svg += (f'<line class="chart-grid" stroke="#dae3eb" x1="{LEFT}" x2="{WIDTH - 8}" y1="{y:.1f}" y2="{y:.1f}"/>'
                f'<text class="chart-axis" {AXIS} x="{LEFT - 6}" y="{y + 4:.1f}" text-anchor="end">'
                f'{e(_number(mark, 0) + " s" if mark >= 1 else "0,1 s")}</text>')
        for factor in (2, 5):
            if mark * factor < top:
                fine = y_of(mark * factor)
                svg += (f'<line class="chart-grid-fine" stroke="#eef2f6" x1="{LEFT}" x2="{WIDTH - 8}" '
                        f'y1="{fine:.1f}" y2="{fine:.1f}"/>')
        exponent += 1
    return svg


def _call_mark(record: dict[str, Any], x: float, y: float, zone: ZoneInfo) -> str:
    from ..review.views import STAGE_LABELS
    moment = datetime.fromisoformat(record["started_at"]).astimezone(zone)
    failed = record["status"] != "success"
    stage = STAGE_LABELS.get(record["stage"], record["stage"])
    detail = (f"{moment:%d.%m. %H:%M} · {stage} · {_seconds_text(record['duration_ms'] / 1000)} · "
              f"{record['model'].rsplit('/', 1)[-1]}" + (" · Fehler" if failed else ""))
    if failed:
        return (f'<path class="chart-cross" stroke="{FILLS["chart-cross"]}" stroke-width="1.6" '
                f'd="M{x - 3:.1f} {y - 3:.1f}L{x + 3:.1f} {y + 3:.1f}M{x - 3:.1f} {y + 3:.1f}L{x + 3:.1f} {y - 3:.1f}" '
                f'data-chart-detail="{e(detail)}"><title>{e(detail)}</title></path>')
    return (f'<circle class="chart-dot" fill="{FILLS["chart-dot"]}" fill-opacity="0.5" cx="{x:.1f}" '
            f'cy="{y:.1f}" r="2.5" data-chart-detail="{e(detail)}"><title>{e(detail)}</title></circle>')


def scatter_chart(ident: str, records: list[dict[str, Any]], days: int, zone: ZoneInfo, now: datetime) -> str:
    """5.9.9: every call at its exact time on a logarithmic duration axis, with the median per period.

    Points are not focusable (thousands of tab stops); the value table is the keyboard path.
    Failures are crosses, so they differ in shape and not only in colour.
    """
    labels, bucket = _buckets(records, days, zone, now)
    start, span = _period_start(days, zone, now)
    groups: list[list[dict[str, Any]]] = [[] for _ in labels]
    for record in records:
        index = bucket(record)
        if index is not None:
            groups[index].append(record)
    inside = [record for group in groups for record in group]
    shown = thin(inside)
    longest = max((record["duration_ms"] / 1000 for record in inside), default=FLOOR)
    top = max(100.0, 10.0 ** math.ceil(math.log10(max(longest, FLOOR))))
    plot_width, plot_height = WIDTH - LEFT - 8, HEIGHT - BOTTOM - TOP
    decades = math.log10(top) + 1

    def y_of(value: float) -> float:
        return TOP + plot_height * (1 - (math.log10(max(value, FLOOR)) + 1) / decades)
    svg = _duration_grid(top, y_of)
    every = max(1, round(len(labels) / 10))
    slot = plot_width / max(len(labels), 1)
    for index, label in enumerate(labels):
        if index % every == 0:
            svg += (f'<text class="chart-axis" {AXIS} x="{LEFT + slot * index + slot / 2:.1f}" y="{HEIGHT - 8}" '
                    f'text-anchor="middle">{e(label)}</text>')
    for record in shown:
        moment = datetime.fromisoformat(record["started_at"]).astimezone(zone)
        x = LEFT + plot_width * (moment - start).total_seconds() / span.total_seconds()
        svg += _call_mark(record, x, y_of(record["duration_ms"] / 1000), zone)
    path, pen = "", False
    for index, group in enumerate(groups):
        if len(group) < 3:
            pen = False
            continue
        median = _median([record["duration_ms"] / 1000 for record in group])
        path += f'{"L" if pen else "M"}{LEFT + slot * index + slot / 2:.1f} {y_of(median):.1f} '
        pen = True
    period = "Stunde" if days == 1 else "Tag"
    if path:
        svg += (f'<path class="chart-trend-line" stroke="{FILLS["chart-trend"]}" stroke-width="1.8" fill="none" '
                f'd="{path.strip()}"><title>Median je {period}</title></path>')
    svg += (f'<text class="chart-legend" {AXIS} x="{WIDTH - 8}" y="{TOP + 2}" text-anchor="end">'
            f'<tspan class="chart-ok-text" fill="{FILLS["chart-ok"]}">● erfolgreich</tspan>'
            f'<tspan class="chart-failed-text" fill="{FILLS["chart-failed"]}" dx="12">× fehlgeschlagen</tspan>'
            f'<tspan class="chart-trend-text" fill="{FILLS["chart-trend"]}" dx="12">— Median je {period}</tspan>'
            '</text>')
    rows = []
    for label, group in zip(labels, groups, strict=True):
        values = [record["duration_ms"] / 1000 for record in group]
        failures = sum(record["status"] != "success" for record in group)
        figures = ((_seconds_text(_median(values)), _seconds_text(_quantile(values, 0.95)),
                    _seconds_text(max(values))) if values else ("—", "—", "—"))
        rows.append([label, count(len(group)), count(failures), *figures])
    subtitle = (f"{count(len(shown))} von {count(len(inside))} Aufrufen dargestellt"
                if len(shown) < len(inside) else "")
    return _figure(ident, "Aufrufdauer", "Dauer jedes KI-Aufrufs zum genauen Zeitpunkt auf logarithmischer "
                   f"Achse mit dem Median je {period}.", svg,
                   ["", "Aufrufe", "Fehler", "Median", "95 %", "Maximum"], rows,
                   hint="Punkte für Details berühren oder mit der Maus zeigen; alle Werte in der Tabelle.",
                   subtitle=subtitle)


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
    by_model: dict[str, float] = {}
    for record in records:
        if record["cost_usd"] is not None:
            model = record["model"].rsplit("/", 1)[-1]
            by_model[model] = by_model.get(model, 0.0) + float(Decimal(record["cost_usd"]))
    body = '<h2>Verlauf und Verteilung</h2><div class="chart-grid-layout">'
    body += column_chart("chart-calls", f"KI-Aufrufe je {period}",
                         f"Erfolgreiche und fehlgeschlagene Aufrufe je {period} im gewählten Zeitraum.", labels,
                         [("erfolgreich", "chart-ok", succeeded), ("fehlgeschlagen", "chart-failed", failed)], count)
    average, trend = cost_lines(records, costs, bucket, days)
    summary = [["Summe", dollars(sum(costs))]]
    if average is not None:
        since = "erster erfasster Stunde" if days == 1 else "erstem erfassten Tag"
        summary.append([f"Durchschnitt (ab {since})", dollars(average)])
    if trend is not None:
        for row in summary:
            row.append("")
    body += column_chart("chart-costs", f"Gemeldete Cloudkosten je {period}",
                         f"Vom Anbieter gemeldete Kosten in US-Dollar je {period}; Aufrufe ohne Angabe fehlen.",
                         labels, [("Kosten", "chart-cost", costs)], dollars,
                         average=(f"Ø {dollars(average)} je {period}", average) if average is not None else None,
                         trend=("7-Tage-Mittel", trend) if trend is not None else None, summary=summary)
    body += scatter_chart("chart-durations", records, days, tz, now)
    from .pipeline import pipeline_plan, ranking, stage_times
    body += ranking(stage_times(records)) + pipeline_plan(records)
    if by_model:
        body += bar_list("chart-models", "Gemeldete Kosten je Modell",
                         "Summe der gemeldeten Kosten in US-Dollar je Modell, größtes zuerst.",
                         list(by_model.items()), dollars, css="chart-cost")
    return body + "</div>"


__all__ = ["bar_list", "column_chart", "scatter_chart", "statistics_charts", "thin"]
