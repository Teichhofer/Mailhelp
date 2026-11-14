"""6.2.10: the evaluation – figure tiles, jump links, charts folded on phones and open on the desktop."""
from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime, timedelta

from playwright.sync_api import expect

from checks import audit
from conftest import sign_in


def journal(mailhelp):
    rows = []
    for index in range(12):
        started = datetime.now(UTC) - timedelta(minutes=10 + index * 60)
        rows.append({"id": secrets.token_hex(16), "call_id": f"c{index}", "attempt": 1, "mode": "standard",
                     "model": "openrouter/flash", "stage": "relevance", "provider": "openrouter",
                     "started_at": started.isoformat(), "start": started.timestamp(),
                     "end": started.timestamp() + 2, "duration_ms": 2000.0, "status": "success",
                     "tokens": {}, "cost_usd": "0.001", "power_watts": 300, "electricity_price": 0.3})
    mailhelp.site.archive.metrics.path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_evaluation6210_tiles_sections_and_folded_charts(page, mailhelp):
    journal(mailhelp)
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/auswertung?days=7")
    expect(page.locator(".kpi-tile")).to_have_count(8)
    charts = page.locator("details.chart-section")
    if page.mobile:
        expect(charts).not_to_have_attribute("open", "")  # the figures come first, charts on request
        page.locator("details.chart-section > summary").click()
    expect(charts).to_have_attribute("open", "")
    expect(page.locator("#chart-calls-title, .chart").first).to_be_visible()
    page.locator(".page-sections").get_by_role("link", name="Nach Modell und Schritt", exact=True).click()
    expect(page.locator("#nach-modell")).to_be_in_viewport()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert audit(page, "evaluation6210-" + page.device, page.mobile) == []
    assert page.errors == []


def test_evaluation6210_an_empty_period_is_one_sentence(page, mailhelp):
    if page.device != "desktop":
        return
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/auswertung?days=7")
    expect(page.get_by_text("Für diese Auswahl gibt es keine erfassten Aufrufe.", exact=False)).to_be_visible()
    expect(page.locator(".kpi-tile")).to_have_count(0)
