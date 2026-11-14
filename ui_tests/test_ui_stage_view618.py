"""6.1.8: step times, run time and the slowest runs in a real browser on every device."""
from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from playwright.sync_api import expect

from checks import audit, open_charts
from conftest import sign_in
from mailhelp.runtime.stage_metrics import StageRecord
from tests.scenarios.web_scenario import mail_id


def step(stage, duration, minutes, mail=1, **changes):
    return StageRecord(**{"id": secrets.token_hex(16), "run_id": "r", "mode": "standard", "stage": stage,
                          "outcome": "completed", "started_at": datetime.now(UTC) - timedelta(minutes=minutes),
                          "duration_ms": duration, "mail_id": mail_id(mail), **changes})


def journal(mailhelp):
    stages = mailhelp.site.archive.metrics.stages
    for index in range(12):
        minutes = 30 + index * 60
        parts = {"zerlegen": 100.0, "bilderkennung": 900.0}
        for record in (step("preparation", 300 + index * 20, minutes, parts=parts),
                       step("relevance", 2000 + index * 100, minutes, llm_ms=1900.0),
                       step("event_extraction", 4000 + index * 300, minutes, llm_ms=3900.0),
                       step("completion", 20, minutes),
                       step("total", 6400 + index * 420, minutes, waiting_ms=1000.0 * index)):
            stages.write(record)


def test_stage618_evaluation_shows_step_times_on_every_screen(page, mailhelp):
    journal(mailhelp)
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/auswertung?days=7")
    open_charts(page)
    expect(page.locator("#chart-wall-title")).to_have_text("Zeit je Verarbeitungsschritt")
    expect(page.locator("#chart-runs-title")).to_have_text("Durchlaufzeit je Mail")
    plan = page.locator("ol.pipeline")
    expect(plan.locator(".is-bottleneck")).to_contain_text("Terminerkennung")
    expect(plan.get_by_text("davon KI", exact=False).first).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert audit(page, "stage618-evaluation-" + page.device, page.mobile) == []
    page.get_by_role("link", name="Langsamste Durchläufe anzeigen", exact=True).click()
    expect(page.get_by_role("heading", name="Durchlaufzeit je Mail", exact=True)).to_be_visible()
    expect(page.locator(".calls-table tbody tr")).to_have_count(12)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert audit(page, "stage618-runs-" + page.device, page.mobile) == []
    assert page.errors == []


def test_stage618_the_slowest_runs_of_a_step_without_javascript(page, mailhelp):
    journal(mailhelp)
    page.cdp.send("Emulation.setScriptExecutionDisabled", {"value": True})
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/auswertung?days=7")
    page.locator(".stage-links").get_by_role("link", name="Terminerkennung", exact=True).click()
    expect(page.get_by_role("heading", name="Schritt „Terminerkennung“", exact=True)).to_be_visible()
    first = page.locator(".calls-table tbody tr").first
    expect(first).to_contain_text("7,30 s")  # the slowest first
    page.get_by_role("link", name="Zeit", exact=True).click()
    expect(page.locator(".calls-table tbody tr").first).to_contain_text("4,00 s")
