"""6.2.10: the evaluation – figures as tiles, an empty state, jump links and a foldable chart section."""
import secrets
from datetime import UTC, datetime, timedelta

from mailhelp.runtime.metrics import AttemptRecord
from tests.fakes.shared_web_actions import web  # noqa: F401  (fixture)
from tests.fakes.shared_web_v12 import configure


def call():
    started = datetime.now(UTC) - timedelta(minutes=5)
    return AttemptRecord.model_validate({
        "id": secrets.token_hex(16), "call_id": "c", "attempt": 1, "mode": "standard", "model": "m/x",
        "stage": "relevance", "provider": "openrouter", "started_at": started.isoformat(),
        "start": started.timestamp(), "end": started.timestamp() + 1, "duration_ms": 1000.0, "status": "success",
        "tokens": {}, "cost_usd": None, "power_watts": 0, "electricity_price": 0}).model_dump_json() + "\n"


def test_damaged_lines_alone_still_show_the_figures(web, tmp_path):
    _, metrics, *_ = configure(web, tmp_path)
    metrics.path.write_text("kaputt\n", encoding="utf-8")
    page = web.browser.request("GET", "/auswertung").body.decode()
    assert '<dl class="kpi-grid">' in page and "1 beschädigte Zeilen" in page
    assert "Einen längeren Zeitraum wählen" not in page


def test_measured_calls_get_tiles_jump_links_and_a_foldable_chart_section(web, tmp_path):
    _, metrics, *_ = configure(web, tmp_path)
    metrics.path.write_text(call(), encoding="utf-8")
    page = web.browser.request("GET", "/auswertung").body.decode()
    nav = page[page.index('<nav class="page-sections"'):page.index("</nav>", page.index('<nav class="page-sections"'))]
    for target in ("#kennzahlen", "#diagramme", "#pipeline-title", "#nach-modell"):
        assert f'href="{target}"' in nav and f'id="{target[1:]}"' in page
    assert '<details class="chart-section" id="diagramme" open data-fold-phone>' in page
    assert page.count('<div class="kpi-tile">') >= 8
