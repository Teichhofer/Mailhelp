"""5.9.8–5.9.10: evaluation charts, pipeline plan and call list in a real browser."""
from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime, timedelta

from playwright.sync_api import expect

from checks import audit
from conftest import sign_in
from tests.scenarios.web_scenario import mail_id


def row(minutes, stage="relevance", status="success", seconds=1.4, mail=1, cost="0.0012", **extra):
    started = datetime.now(UTC) - timedelta(minutes=minutes)
    return {"id": secrets.token_hex(16), "call_id": f"c{minutes}", "attempt": 1, "mail_id": mail_id(mail),
            "mode": "standard", "model": "openrouter/flash", "stage": stage, "provider": "openrouter",
            "started_at": started.isoformat(), "start": started.timestamp(), "end": started.timestamp() + seconds,
            "duration_ms": seconds * 1000, "status": status, "tokens": {"prompt_tokens": 900, "completion_tokens": 20},
            "cost_usd": cost, "power_watts": 300, "electricity_price": 0.3, **extra}


def journal(mailhelp):
    rows = [row(10 + index * 90, seconds=0.5 + index % 7) for index in range(40)]
    rows += [row(15 + index * 200, stage="event_extraction", seconds=40 + index) for index in range(10)]
    rows += [row(30, status="failed", error_kind="timeout", cost=None, seconds=60)]
    mailhelp.site.archive.metrics.path.write_text("".join(json.dumps(item) + "\n" for item in rows),
                                                  encoding="utf-8")


def test_evaluation59_charts_and_pipeline_fit_every_screen(page, mailhelp):
    journal(mailhelp)
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/auswertung?days=7")
    expect(page.get_by_text("Ablauf der Mailverarbeitung", exact=True)).to_be_visible()
    plan = page.locator("ol.pipeline")
    expect(plan.locator(".is-bottleneck")).to_contain_text("⏱ größte Wartezeit")
    expect(plan.locator(".is-bottleneck")).to_contain_text("Terminerkennung")
    expect(plan.get_by_text("lokal · nicht gemessen").first).to_be_visible()
    # The plan runs left to right on wide screens and top to bottom on phones.
    first, second = plan.locator("> li").nth(0).bounding_box(), plan.locator("> li").nth(1).bounding_box()
    if page.device == "desktop":
        assert second["x"] > first["x"]
    else:
        assert second["y"] > first["y"]
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    durations = page.locator('figure:has(#chart-durations-title)')
    expect(durations.locator("circle.chart-dot").first).to_be_attached()
    expect(durations.locator("path.chart-cross")).to_have_count(1)
    assert durations.locator("circle[tabindex]").count() == 0
    assert audit(page, "evaluation59-" + page.device, page.mobile) == []
    assert page.errors == []


def test_evaluation59_a_figure_opens_its_call_list(page, mailhelp):
    journal(mailhelp)
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/auswertung?days=7")
    page.get_by_role("link", name="1 fehlgeschlagenen Aufruf anzeigen", exact=True).click()
    expect(page.get_by_role("heading", name="Fehlgeschlagene Aufrufe", exact=True)).to_be_visible()
    expect(page.locator(".calls-explanation")).to_contain_text("Zeitüberschreitung: 1")
    expect(page.locator(".calls-table tbody tr")).to_have_count(1)
    page.locator('select[name="status"]').select_option("alle")
    page.get_by_role("button", name="Anzeigen", exact=True).click()
    expect(page.locator(".calls-table tbody tr")).to_have_count(51)
    page.get_by_role("link", name="← Zurück zur Auswertung", exact=True).click()
    expect(page.get_by_role("heading", name="Auswertung", exact=True)).to_be_visible()
    assert page.url.endswith("/auswertung?days=7&mode=production")
    assert audit(page, "calls59-" + page.device, page.mobile) == []
    assert page.errors == []
