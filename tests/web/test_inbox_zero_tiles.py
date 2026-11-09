"""Planung 5.0, step 21.6 (5.0.10): today's results as tiles on the inbox zero card."""
import re
from datetime import UTC, datetime

from tests.scenarios.web_scenario import mail_id


def row(pid, status, kind):
    return {"mail_id": mail_id(1), "proposal_id": pid, "status": status, "proposal_kind": kind,
            "at": "2026-10-12T10:00:00+00:00", "version": 1, "source": "web", "kind": "decision", "title": "x"}


def tiles(html):
    return dict(re.findall(r'<div class="kpi[^"]*"><dt>([^<]+)</dt><dd>(\d+)</dd></div>', html))


def test_the_tiles_count_appointments_tasks_reconciliations_and_rejections(web, monkeypatch):
    site = web.site
    site.clock = lambda: datetime(2026, 10, 12, 12, tzinfo=UTC)
    rows = [row("a", "created", "event"), row("b", "created", "event"), row("c", "simulated", "task"),
            row("d", "already_exists", "task"), row("e", "rejected", "event"), row("f", "rejected", "task"),
            row("g", "rejected", "task")]
    monkeypatch.setattr(site.archive.queries, "history", lambda: rows)
    html = site.experience.inbox_zero()
    assert tiles(html) == {"📅 Termine": "2", "✅ Aufgaben": "1", "🔁 Abgleiche": "1", "🗑️ Verworfen": "3"}
    assert '<dl class="kpi-tiles" aria-label="Heute">' in html
    # Appointments and tasks carry their kind colour; the others stay neutral.
    assert '<div class="kpi kind-event"><dt>📅 Termine' in html and '<div class="kpi kind-task"><dt>✅' in html
    assert '<div class="kpi "><dt>🔁 Abgleiche' in html


def test_without_results_every_tile_shows_zero(web, monkeypatch):
    monkeypatch.setattr(web.site.archive.queries, "history", lambda: [])
    assert set(tiles(web.site.experience.inbox_zero()).values()) == {"0"}
