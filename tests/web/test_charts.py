"""Charts of the evaluation page (3.3.9): server-side SVG from synthetic metric records."""
from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import pytest

from mailhelp.web.archive_pages import statistics_page
from mailhelp.web.charts import _scale, bar_list, column_chart, count, statistics_charts

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
    assert html.count('<figure class="chart"') == 5
    assert "<td>15.10.</td><td>1</td><td>0</td>" in html and "<td>14.10.</td><td>2</td><td>0</td>" in html
    assert "<td>&lt; 1 s</td><td>1</td>" in html and "<td>&gt; 60 s</td><td>1</td>" in html
    assert "<td>relevance</td><td>70,0 s</td>" in html and "<td>gpt-synthetic</td><td>0,0112 $</td>" in html
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
    assert statistics_page({"days": 30, "mode": "production"}, report, report["records"]).count("<figure") == 5


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
