"""6.1.8: the evaluation shows the wall time of every step, the run time per mail and the slowest runs."""
import json
import re
import secrets
from datetime import UTC, datetime, timedelta

import pytest

from mailhelp.runtime.metrics import AttemptRecord
from mailhelp.runtime.stage_metrics import StageRecord
from mailhelp.web.pipeline import pipeline_plan, wall_ranking
from mailhelp.web.status_pages import _runtime_section
from tests.fakes.shared_web_actions import web  # noqa: F401  (fixture)
from tests.fakes.shared_web_v12 import configure
from tests.scenarios.web_scenario import mail_id

NOW = datetime.now(UTC)


def step(stage, duration, *, minutes=5, mail=1, llm=0.0, **changes):
    values = {"id": secrets.token_hex(16), "run_id": "r", "mode": "standard", "stage": stage, "outcome": "completed",
              "started_at": NOW - timedelta(minutes=minutes), "duration_ms": duration, "llm_ms": llm,
              "mail_id": mail_id(mail) if mail else None}
    return StageRecord(**{**values, **changes})


@pytest.fixture
def evaluation(web, tmp_path):
    _, metrics, *_ = configure(web, tmp_path)
    for record in (step("preparation", 400, parts={"zerlegen": 150.0, "anhaenge": 250.0}),
                   step("relevance", 2500, llm=2300), step("summary", 1500, llm=1400),
                   step("normalization", 20), step("completion", 30, outcome="completed"),
                   step("total", 4450, waiting_ms=3_600_000),
                   step("relevance", 9000, mail=99, minutes=60, llm=8800, resumed=True, outcome="deferred")):
        metrics.stages.write(record)
    return web, metrics


def page(web, path):
    response = web.browser.request("GET", path)
    return response.status, response.body.decode()


def test_regression_the_evaluation_shows_every_step_with_its_wall_time(evaluation):
    """Regression 6.1: only AI calls were shown; local steps read "lokal · nicht gemessen" and there was
    no run time per mail."""
    web, _ = evaluation
    status, html = page(web, "/auswertung?days=7")
    assert status == 200
    assert "<dt>Durchlaufzeit je Mail (Median / 95 % / Maximum)</dt>" in html
    assert 'href="/auswertung/schritte?days=7&amp;mode=production&amp;stage=total"' in html
    assert "<dt>Wartezeit auf Entscheidungen (Median)</dt><dd>1 Std.</dd>" in html
    assert "Zeit je Verarbeitungsschritt" in html and "Durchlaufzeit je Mail</span>" in html
    plan = html[html.index('<ol class="pipeline">'):html.index("</ol>", html.index('<ol class="pipeline">'))]
    assert "8. Normalisierung" in plan and "davon KI" in plan
    assert plan.count("lokal · nicht gemessen") == 8  # 13 steps, 5 measured
    bottleneck = re.search(r'<li class="pipeline-step is-bottleneck[^"]*">(.*?)</li>', plan).group(1)
    assert "Relevanzprüfung" in bottleneck  # largest wall time
    assert "Aufbereitung im Detail" in html and "Anhänge und Vorschauen" in html
    assert 'Langsamste Durchläufe: <a href="/auswertung/schritte?days=7&amp;mode=production&amp;stage=relevance">' \
        in html


def test_periods_without_step_data_look_as_before(web, tmp_path):
    _, metrics, *_ = configure(web, tmp_path)
    started = NOW - timedelta(minutes=5)
    call = AttemptRecord.model_validate({
        "id": secrets.token_hex(16), "call_id": "c", "attempt": 1, "mode": "standard", "model": "m/x",
        "stage": "relevance", "provider": "openrouter", "started_at": started.isoformat(),
        "start": started.timestamp(), "end": started.timestamp() + 1, "duration_ms": 1000.0, "status": "success",
        "tokens": {}, "cost_usd": None, "power_watts": 0, "electricity_price": 0})
    metrics.path.write_text(call.model_dump_json() + "\n", encoding="utf-8")
    html = page(web, "/auswertung?days=7")[1]
    assert "<dt>Durchlaufzeit je Mail" not in html and "Zeit je Verarbeitungsschritt" not in html
    assert "lokal · nicht gemessen" in html and "Gemessen werden nur KI-Aufrufe" in html


def test_the_slowest_runs_of_a_step_and_of_whole_mails(evaluation):
    web, _ = evaluation
    status, html = page(web, "/auswertung/schritte?days=7")
    assert status == 200 and "<h1>Durchlaufzeit je Mail</h1>" in html and "<th scope=\"col\">Wartezeit</th>" in html
    assert "1 Durchläufe · Seite 1 von 1" in html and f'<a href="/mail/{mail_id(1)}">' in html
    steps = page(web, "/auswertung/schritte?days=7&stage=relevance")[1]
    assert "<h1>Schritt „Relevanzprüfung“</h1>" in steps
    rows = re.findall(r"<tr><td>(.*?)</td></tr>", steps)
    assert "9,00 s" in rows[0] and "zurückgestellt · fortgesetzt" in rows[0]  # longest first
    assert "Mail nicht mehr gespeichert" in rows[0] and "abgeschlossen" in rows[1]
    by_time = re.findall(r"<tr><td>(.*?)</td></tr>", page(web, "/auswertung/schritte?days=7&stage=relevance&sort=time")[1])
    assert "2,50 s" in by_time[0]


@pytest.mark.parametrize("query", ["stage=unbekannt", "sort=name", "page=0", "page=x", "mode=x", "farbe=rot"])
def test_unknown_values_are_rejected(evaluation, query):
    web, _ = evaluation
    assert page(web, "/auswertung/schritte?" + query)[0] == 422


def test_paging_login_and_no_metrics(evaluation):
    from tests.fakes.shared_web_auth import Browser
    web, metrics = evaluation
    for index in range(205):
        metrics.stages.write(step("summary", 100 + index, mail=None))
    first = page(web, "/auswertung/schritte?days=7&stage=summary")[1]
    assert "206 Durchläufe · Seite 1 von 3" in first and "Nächste Seite" in first and "<td>—</td>" in first
    last = page(web, "/auswertung/schritte?days=7&stage=summary&page=9")[1]
    assert "Seite 3 von 3" in last and "Vorherige Seite" in last
    empty = page(web, "/auswertung/schritte?days=7&stage=duplicate_precheck")[1]
    assert "Für diese Auswahl gibt es keine gemessenen Durchläufe." in empty
    assert Browser(web.app).request("GET", "/auswertung/schritte").status in {302, 303}
    web.site.archive.metrics = None
    assert "Noch keine Metrikerfassung verfügbar." in page(web, "/auswertung/schritte")[1]


def test_pipeline_and_ranking_from_wall_times_alone():
    walls = {"relevance": {"count": 2, "sum_ms": 4000, "median_ms": 2000, "p95_ms": 3000, "max_ms": 3000,
                           "failed": 1, "llm_ms": 3500, "per_mail_median_ms": None},
             "completion": {"count": 2, "sum_ms": 20, "median_ms": 10, "p95_ms": 10, "max_ms": 10,
                            "failed": 0, "llm_ms": 0, "per_mail_median_ms": 10}}
    plan = pipeline_plan([], walls)
    assert "Dauer jedes Schritts mit dem Anteil der KI-Aufrufe." in plan and "davon KI 3,5 s" in plan
    ranking = wall_ranking(walls)
    assert "<td>Relevanzprüfung</td><td>99,5 %</td><td>4,0 s</td><td>2</td><td>2,0 s</td><td>3,0 s</td>" in ranking
    assert "Langsamste Durchläufe" not in ranking
    nothing = {**walls["completion"], "median_ms": None, "p95_ms": None, "max_ms": None}
    assert "<td>—</td><td>—</td><td>—</td>" in wall_ranking({"completion": nothing})


def test_the_status_page_names_the_usual_duration_of_the_running_step(evaluation):
    from types import SimpleNamespace
    from zoneinfo import ZoneInfo
    web, metrics = evaluation
    metrics.activity = {"stage": "relevance", "mail_id": None, "started": 0.0}
    runtime = metrics.runtime()
    assert runtime["usual_ms"] == pytest.approx(5750)
    info = SimpleNamespace(runtime={**runtime, "elapsed": 41}, services=())
    assert "<dt>Seit</dt><dd>41,0 s · üblich 5,8 s</dd>" in _runtime_section(info, ZoneInfo("Europe/Berlin"))
    info = SimpleNamespace(runtime={**runtime, "elapsed": 41, "usual_ms": None}, services=())
    assert "üblich" not in _runtime_section(info, ZoneInfo("Europe/Berlin"))
    assert json.dumps(runtime)  # serialisable for /api/stand


def test_a_run_time_without_waiting_shows_no_waiting_row():
    from mailhelp.web.archive_pages import _run_time_rows
    total = {"count": 1, "median_ms": 1000, "p95_ms": 1000, "max_ms": 1000}
    rows = _run_time_rows({"days": 7, "mode": "production"}, {"total": total, "waiting_median_ms": 0})
    assert [name for name, _ in rows] == ["Durchlaufzeit je Mail (Median / 95 % / Maximum)"]
    assert _run_time_rows({"days": 7}, None) == []
