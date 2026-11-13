"""Charts of the evaluation page (3.3.9): server-side SVG from synthetic metric records."""
from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import pytest

from mailhelp.web.archive_pages import statistics_page
from mailhelp.web.charts import _number, _scale, bar_list, column_chart, count, statistics_charts

NOW = datetime(2026, 10, 15, 12, 30, tzinfo=UTC)


def record(hours_ago: float, *, status="success", cost="0.0012", seconds=2.5, stage="summary",
           model="openai/gpt-synthetic"):
    return {"started_at": (NOW - timedelta(hours=hours_ago)).isoformat(), "status": status, "cost_usd": cost,
            "duration_ms": seconds * 1000, "stage": stage, "model": model, "provider": "openrouter",
            "mode": "standard", "server": "openrouter.ai"}


@pytest.mark.parametrize(("maximum", "top"), [(0, 1), (0.03, 0.05), (1, 1), (7, 10), (120, 200), (250, 250),
                                              (3, 5)])
def test_value_axis_ends_at_a_round_number(maximum, top):
    assert _scale(maximum) == pytest.approx(top)


def test_columns_stack_their_series_and_keep_the_values_as_table():
    html = column_chart("c", "Aufrufe <je Tag>", "Beschreibung", ["14.10.", "15.10."],
                        [("ok", "chart-ok", [3, 0]), ("Fehler", "chart-failed", [1, 0])], count)
    assert html.count('<rect class="chart-ok"') == 1 and html.count('<rect class="chart-failed"') == 1
    assert 'role="img"' in html and "Aufrufe &lt;je Tag&gt;" in html and "<desc" in html
    assert "<tr><td>14.10.</td><td>3</td><td>1</td></tr>" in html
    assert "style=" not in html  # the CSP forbids inline styles
    empty = column_chart("e", "Leer", "Keine Werte", [], [("ok", "chart-ok", [])], count)
    assert "<rect" not in empty


def test_bars_sort_largest_first_and_sum_up_the_rest():
    items = [(f"Schritt {index}", float(index)) for index in range(1, 11)]
    items.append(("ein sehr langer Name eines Verarbeitungsschritts", 0.5))
    html = bar_list("b", "Dauer", "Summe", items, count)
    labels = re.findall(r"<tr><td>([^<]+)</td>", html)
    assert labels[:2] == ["Schritt 10", "Schritt 9"] and labels[-1] == "Weitere" and len(labels) == 8
    assert "<tr><td>Weitere</td><td>6</td></tr>" in html  # 3 + 2 + 1 + 0.5 beyond the seven largest
    short = bar_list("s", "Dauer", "Summe", [("ein sehr langer Name eines Verarbeitungsschritts", 1.0)], count)
    assert "ein sehr langer Name eines …" in short and "Verarbeitungsschritts: 1" in short


def test_last_day_is_shown_per_hour_and_older_records_are_left_out():
    html = statistics_charts([record(0.2), record(1, status="failed", cost=None), record(30)], 1, "Europe/Berlin", NOW)
    assert "KI-Aufrufe je Stunde" in html and "<td>14 Uhr</td><td>1</td><td>0</td>" in html
    assert "<td>13 Uhr</td><td>0</td><td>1</td>" in html
    assert html.count("<tr><td>") >= 24 + 24 + len(("< 1 s", "1–2 s"))


def test_period_is_shown_per_day_with_costs_durations_steps_and_models():
    records = [record(1, seconds=0.4), record(26, seconds=70, stage="relevance", model="ollama/local", cost=None),
               record(27, cost="0.01", seconds=12)]
    html = statistics_charts(records, 7, "UTC", NOW)
    assert html.count('<figure class="chart"') == 5 and html.count('<figure class="chart pipeline-figure"') == 1
    assert "<td>15.10.</td><td>1</td><td>0</td>" in html and "<td>14.10.</td><td>2</td><td>0</td>" in html
    # 5.9.9: durations per day with median, 95 % and maximum instead of fixed classes.
    assert "<tr><td>15.10.</td><td>1</td><td>0</td><td>0,4 s</td><td>0,4 s</td><td>0,4 s</td></tr>" in html
    assert "<tr><td>14.10.</td><td>2</td><td>0</td><td>41,0 s</td><td>1 Min. 10 s</td><td>1 Min. 10 s</td></tr>" in html
    assert "<tr><td>Relevanzprüfung</td><td>85,0 %</td><td>1 Min. 10 s</td><td>1</td><td>—</td></tr>" in html
    assert "<td>gpt-synthetic</td><td>0,0112 $</td>" in html
    without_costs = statistics_charts([record(1, cost=None)], 7, "UTC", NOW)
    assert without_costs.count('<figure class="chart"') == 4 and statistics_charts([], 7, "UTC", NOW) == ""


def test_evaluation_page_places_the_charts_before_the_groups():
    report = {"count": 1, "failed": 0, "usd": "0.0012", "unknown_cost": 0, "cloud_eur": None,
              "exchange_rate_date": None, "electricity_eur": "0", "seconds": 2.5, "mean": 2.5, "median": 2.5,
              "p95": 2.5, "damaged": 0, "capture_failures": 0, "records": [record(1)],
              "groups": [{"model": "openai/gpt-synthetic", "stage": "summary", "provider": "openrouter", "count": 1,
                          "failed": 0, "seconds": 2.5, "median": 2.5, "p95": 2.5, "usd": "0.0012"}]}
    page = statistics_page({"days": 30, "mode": "production"}, report, report["records"], "UTC", NOW)
    assert page.index("Verlauf und Verteilung") < page.index("Nach Modell und Schritt")
    assert statistics_page({"days": 30, "mode": "production"}, report, report["records"]).count("<figure") == 6


def test_regression_bars_keep_distinct_colours_without_the_stylesheet():
    """Regression: with an outdated stylesheet both series were drawn in the same (black) fill."""
    html = statistics_charts([record(1), record(2, status="failed")], 7, "UTC", NOW)
    fills = dict(re.findall(r'<rect class="(chart-[a-z]+)" fill="(#[0-9a-f]{6})"', html))
    assert fills["chart-ok"] != fills["chart-failed"] and fills["chart-cost"] not in {fills["chart-ok"], "#000000"}
    assert 'font-size="11"' in html and "<tspan" in html and 'fill="#a3262b" dx' in html


def test_interactive_chart_metadata_escapes_labels_and_preserves_no_script_values():
    html = column_chart("detail", 'Aufrufe "privat"', "Beschreibung", ['Tag "1" <script>'],
                        [("ok & mehr", "chart-ok", [2])], count)
    detail = 'Tag &quot;1&quot; &lt;script&gt;: ok &amp; mehr 2'
    assert f'data-chart-detail="{detail}"' in html and f'aria-label="{detail}"' in html
    assert 'tabindex="0" role="img"' in html and 'role="group"' in html
    assert 'aria-haspopup="dialog" hidden>Vergrößern</button>' in html
    assert "<script>" not in html and "<title>" + detail + "</title>" in html
    horizontal = bar_list("model", "Modellkosten", "Beschreibung", [('Modell "A" <img>', 1)], count)
    assert 'data-chart-detail="Modell &quot;A&quot; &lt;img&gt;: 1"' in horizontal
    assert "Werte als Tabelle" in horizontal and "style=" not in horizontal


def test_regression_long_call_durations_read_in_hours_with_the_exact_seconds():
    """Regression 5.9.1: the summed duration of a month read as an unwieldy "75.240,0 s"."""
    report = {"count": 1, "failed": 0, "usd": "0", "unknown_cost": 0, "cloud_eur": None,
              "exchange_rate_date": None, "electricity_eur": "0", "seconds": 75_240.0, "mean": 2.5, "median": 61.0,
              "p95": None, "damaged": 1, "capture_failures": 0, "records": [], "groups": []}
    page = statistics_page({"days": 30, "mode": "production"}, report, [], "UTC", NOW)
    assert ('<dt>Summierte Aufrufdauer</dt><dd><a class="fact-link" href="/auswertung/aufrufe?metric=duration&amp;'
            'days=30&amp;mode=production" aria-label="Längste Aufrufe anzeigen">20 Std. 54 Min. '
            '<span class="meta">(75.240 s)</span> ›</a></dd>') in page
    assert ">2,50 s / 1 Min. 1 s / — ›</a></dd>" in page and "75.240,0 s" not in page
    assert page.index("Summierte Aufrufdauer") < page.index("Unvollständige Erfassung")
    report["seconds"] = 59.9
    assert ">59,9 s ›</a></dd>" in statistics_page({"days": 30, "mode": "production"}, report, [], "UTC", NOW)


def test_v598_average_counts_from_the_first_recorded_day_and_gaps_count_as_zero():
    """Regression 5.9.8: without a reference line, rising costs were hard to judge."""
    # 30 days; first call 10 days ago, then a gap (days without calls cost nothing).
    records = [record(24 * 10, cost="0.07"), record(24 * 2, cost="0.04"), record(1, cost=None)]
    html = statistics_charts(records, 30, "UTC", NOW)
    average = 0.11 / 11  # days 10 … 0 ago, today included
    assert f"Ø {_number(average, 4)} $ je Tag" in html and 'stroke-dasharray="5 3"' in html
    assert '<line class="chart-average-line"' in html
    assert f"<tr><td>Durchschnitt (ab erstem erfassten Tag)</td><td>{_number(average, 4)} $</td><td></td></tr>" in html
    assert "<tr><td>Summe</td><td>0,1100 $</td><td></td></tr>" in html
    # The 7-day mean starts on the 7th recorded day: one value four days ago, none before.
    assert "<th>7-Tage-Mittel</th>" in html and '<path class="chart-cost-trend"' in html
    assert f"<tr><td>{(NOW - timedelta(days=4)):%d.%m.}</td><td>0,0000 $</td><td>{_number(0.07 / 7, 4)} $</td></tr>" in html
    assert f"<tr><td>{(NOW - timedelta(days=5)):%d.%m.}</td><td>0,0000 $</td><td>—</td></tr>" in html
    assert "— 7-Tage-Mittel" in html and "style=" not in html


def test_v598_short_periods_have_an_average_but_no_seven_day_mean():
    html = statistics_charts([record(0.2, cost="0.02")], 1, "UTC", NOW)
    assert "Ø 0,0200 $ je Stunde" in html and "7-Tage-Mittel" not in html
    assert "<tr><td>Durchschnitt (ab erster erfasster Stunde)</td><td>0,0200 $</td></tr>" in html
    week = statistics_charts([record(30, cost="0.02")], 7, "UTC", NOW)
    assert "chart-average-line" in week and "chart-cost-trend" not in week
    # Records outside the period leave no reference line at all.
    outside = statistics_charts([record(24 * 40)], 30, "UTC", NOW)
    assert "chart-average-line" not in outside and "<tr><td>Summe</td><td>0,0000 $</td></tr>" in outside


def test_v598_the_trend_line_is_interrupted_where_a_value_is_missing():
    html = column_chart("t", "Kosten", "Beschreibung", ["1", "2", "3", "4"], [("Kosten", "chart-cost", [1, 2, 3, 4])],
                        count, trend=("7-Tage-Mittel", [None, 2.0, None, 4.0]))
    path = re.search(r'<path class="chart-cost-trend"[^>]* d="([^"]+)"', html).group(1)
    assert path.count("M") == 2 and "L" not in path
    nothing = column_chart("n", "Kosten", "Beschreibung", ["1"], [("Kosten", "chart-cost", [1])], count,
                           trend=("7-Tage-Mittel", [None]))
    assert "<path" not in nothing and "<td>—</td>" in nothing


def test_v599_durations_are_points_on_a_log_axis_with_the_median_per_day():
    """Regression 5.9.9: fixed duration classes hid the time course and everything below one second."""
    records = [record(24 * 2 + index, seconds=value) for index, value in enumerate((0.05, 1.0, 3.0))]
    records += [record(24, seconds=2.0), record(1, seconds=250, status="failed", stage="relevance")]
    html = statistics_charts(records, 7, "UTC", NOW)
    chart = html[html.index('id="chart-durations-title"'):]
    chart = chart[:chart.index("</figure>")]
    # Labelled lines at 0.1 s … 1.000 s: the axis grows past 100 s to the next power of ten.
    assert [label for label in ("0,1 s", "1 s", "10 s", "100 s", "1.000 s") if f">{label}</text>" in chart] == [
        "0,1 s", "1 s", "10 s", "100 s", "1.000 s"]
    assert chart.count('<circle class="chart-dot"') == 4 and chart.count('<path class="chart-cross"') == 1
    assert "Relevanzprüfung · 4 Min. 10 s · gpt-synthetic · Fehler" in chart
    assert "· &lt; 0,1 s ·" in chart  # shorter calls sit on the 0,1 s line
    # Points are not tab stops; the table is the keyboard path.
    assert "<circle" in chart and not any("tabindex" in mark.split("</circle>")[0] for mark in chart.split("<circle")[1:])
    assert "Punkte für Details berühren oder mit der Maus zeigen; alle Werte in der Tabelle." in chart
    # The median line needs three calls: one day with 3 calls is a single point (one move, no line).
    trend = re.search(r'<path class="chart-trend-line"[^>]* d="([^"]+)"', chart).group(1)
    assert trend.count("M") == 1 and "L" not in trend
    assert "<tr><td>13.10.</td><td>3</td><td>0</td><td>1,0 s</td><td>3,0 s</td><td>3,0 s</td></tr>" in chart
    assert "<tr><td>12.10.</td><td>0</td><td>0</td><td>—</td><td>—</td><td>—</td></tr>" in chart
    assert "— Median je Tag" in chart and "Aufrufen dargestellt" not in chart
    assert "style=" not in chart


def test_v599_the_last_day_has_hours_and_a_short_slow_day_keeps_the_axis_at_100_s():
    hourly = statistics_charts([record(0.2, seconds=0.5)] * 3, 1, "UTC", NOW)
    assert "— Median je Stunde" in hourly and '<path class="chart-trend-line"' in hourly
    assert ">100 s</text>" in hourly and ">1.000 s</text>" not in hourly


def test_v599_more_than_3000_calls_are_thinned_deterministically_keeping_failures_and_slow_calls():
    from mailhelp.web.charts import thin
    records = [record(1 + index / 1000, seconds=1.0) for index in range(3001)]
    records[10] = record(1.01, seconds=1.0, status="failed")
    records[20] = record(1.02, seconds=500.0)
    shown = thin(records)
    assert len(shown) == 3000 and records[10] in shown and records[20] in shown
    assert thin(records) == shown and thin(records[:5]) == records[:5]
    html = statistics_charts(records, 7, "UTC", NOW)
    assert "3.000 von 3.001 Aufrufen dargestellt" in html
    many_failures = [record(1, seconds=1.0, status="failed")] * 4
    assert len(thin(many_failures, limit=3)) == 4  # every failure stays even above the limit
