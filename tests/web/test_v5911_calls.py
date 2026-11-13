"""5.9.11: every figure of the evaluation opens one read-only call list with a matching preset."""
from __future__ import annotations

import json
import re
import secrets
from datetime import UTC, datetime, timedelta

import pytest

from mailhelp.runtime.metrics import AttemptRecord, MetricsRecorder, MetricsSettings, error_kind
from tests.fakes.shared_web_actions import web  # noqa: F401  (fixture)
from tests.fakes.shared_web_v12 import configure
from tests.scenarios.web_scenario import mail_id


def row(minutes=10, **changes):
    started = datetime.now(UTC) - timedelta(minutes=minutes)
    item = {"id": secrets.token_hex(16), "call_id": "c", "attempt": 1, "mail_id": mail_id(1), "mode": "standard",
            "model": "openrouter/flash", "stage": "relevance", "provider": "openrouter",
            "started_at": started.isoformat(), "start": started.timestamp(), "end": started.timestamp() + 1,
            "duration_ms": 1400.0, "status": "success", "tokens": {"prompt_tokens": 1200, "completion_tokens": 30},
            "cost_usd": "0.0012", "power_watts": 300, "electricity_price": 0.3, **changes}
    return AttemptRecord.model_validate(item).model_dump(mode="json")


@pytest.fixture
def journal(web, tmp_path):
    _, metrics, *_ = configure(web, tmp_path)
    rows = [row(1), row(2, status="failed", error_kind="timeout", cost_usd=None, duration_ms=30_000.0),
            row(3, status="failed", cost_usd=None),  # written before 5.9: no cause
            row(4, mail_id=mail_id(99), cost_usd="0.5", model="openrouter/pro"),  # mail no longer stored
            row(5, mail_id=None, provider="ollama", cost_usd=None, model="ollama/local", mode="local"),
            row(6, mail_id=None, test_mail_hash="a" * 64)]
    metrics.path.write_text("".join(json.dumps(item) + "\n" for item in rows), encoding="utf-8")
    return web, metrics


def get(web, query):
    return web.browser.request("GET", "/auswertung/aufrufe?" + query)


def rows_of(html):
    return re.findall(r"<tr><td>(.*?)</td></tr>", html)


def test_regression_every_figure_of_the_evaluation_is_a_link_with_the_active_filter(journal):
    """Regression 5.9.11: the figures were plain text; behind "3 fehlgeschlagen" there was nothing to see."""
    web, _ = journal
    page = web.browser.request("GET", "/auswertung?days=7&model=openrouter/flash").body.decode()
    links = re.findall(r'<a class="fact-link" href="([^"]+)" aria-label="([^"]+)">', page)
    assert len(links) == 8
    assert ("/auswertung/aufrufe?metric=failed&amp;days=7&amp;mode=production&amp;model=openrouter%2Fflash",
            "2 fehlgeschlagene Aufrufe anzeigen") in links
    single = web.browser.request("GET", "/auswertung?model=openrouter/pro").body.decode()
    assert 'aria-label="1 Aufruf anzeigen"' in single and 'aria-label="0 fehlgeschlagene Aufrufe anzeigen"' in single


def test_the_failed_list_counts_causes_and_shows_them_per_call(journal):
    web, _ = journal
    html = get(web, "metric=failed").body.decode()
    assert "<h1>Fehlgeschlagene Aufrufe</h1>" in html and "Zeitraum: 30 Tage · Erfassung: Betrieb" in html
    assert "<li>Zeitüberschreitung: 1</li>" in html and "<li>Ursache nicht erfasst (vor 5.9): 1</li>" in html
    assert len(rows_of(html)) == 2 and html.count('<span class="badge warn">Fehler</span>') == 2
    assert '<option value="failed" selected>' in html and "2 Aufrufe · Seite 1 von 1" in html
    # Newest first by default; Relevanzprüfung in German; durations precise; unknown cost spelled out.
    assert html.index("Zeitüberschreitung</span>") < html.index("Ursache nicht erfasst (vor 5.9)</span>")
    assert "<td>Relevanzprüfung</td>" in html and "<td>30,00 s</td>" in html and "<td>unbekannt</td>" in html
    assert f'<a href="/mail/{mail_id(1)}">' in html and "1.200 / 30" in html
    # The explicit choice "alle" wins over the preset.
    assert len(rows_of(get(web, "metric=failed&status=alle").body.decode())) == 6


def test_cost_lists_sort_by_cost_and_name_the_mail_or_its_absence(journal):
    web, _ = journal
    html = get(web, "metric=cloud_costs").body.decode()
    cells = rows_of(html)
    assert len(cells) == 3 and "0,5000 $" in cells[0]
    assert "Mail nicht mehr gespeichert" in cells[0] and "Vergleichslauf" in html
    assert "<li>openrouter/pro: 0,5000 $</li>" in html
    eur = get(web, "metric=cloud_eur").body.decode()
    assert "EUR = USD ÷ 1,1000." in eur
    unknown = get(web, "metric=unknown_cost").body.decode()
    assert len(rows_of(unknown)) == 2 and "unbekannt, nicht null" in unknown
    local = get(web, "metric=electricity").body.decode()
    assert len(rows_of(local)) == 1 and "Eingestellt: 300 W, 0,30 €/kWh." in local and "<td>—</td>" in local
    longest = rows_of(get(web, "metric=duration").body.decode())
    assert "30,00 s" in longest[0]
    spread = get(web, "metric=distribution").body.decode()
    assert "Mittel " in spread and "99 % 30,00 s · Maximum 30,00 s" in spread
    by_time = rows_of(get(web, "metric=cloud_costs&sort=time").body.decode())
    assert "0,0012 $" in by_time[0]
    by_duration = get(web, "metric=calls&sort=duration&status=success").body.decode()
    assert len(rows_of(by_duration)) == 4


def test_incomplete_capture_explains_without_a_list_and_empty_lists_say_so(journal):
    web, metrics = journal
    metrics.failures = 2
    html = get(web, "metric=incomplete").body.decode()
    assert "0 beschädigte Zeilen, 2 Erfassungsfehler" in html and "<table" not in html
    empty = get(web, "metric=failed&model=unbekannt").body.decode()
    assert "Für diese Auswahl gibt es keine erfassten Aufrufe." in empty
    back = re.search(r'<a href="([^"]+)">← Zurück zur Auswertung</a>', empty).group(1)
    assert back == "/auswertung?days=30&amp;mode=production&amp;model=unbekannt"


def test_the_list_is_paged_by_100_and_older_periods_mention_the_retention(journal):
    web, metrics = journal
    many = [row(10 + index) for index in range(205)]
    metrics.path.write_text("".join(json.dumps(item) + "\n" for item in many), encoding="utf-8")
    first = get(web, "metric=calls").body.decode()
    assert len(rows_of(first)) == 100 and first.count("205 Aufrufe · Seite 1 von 3") == 2
    assert "page=2" in first and "Vorherige Seite" not in first
    last = get(web, "metric=calls&page=3").body.decode()
    assert len(rows_of(last)) == 5 and "Vorherige Seite" in last and "Nächste Seite" not in last
    assert len(rows_of(get(web, "metric=calls&page=99").body.decode())) == 5  # beyond the end: last page
    metrics.settings = MetricsSettings(retention_days=30)
    old = get(web, "metric=calls&days=90").body.decode()
    assert "Einzelaufrufe liegen nur für die letzten 30 Tage vor" in old
    since = (datetime.now(UTC) - timedelta(days=60)).date().isoformat()
    assert "Einzelaufrufe liegen nur" in get(web, f"metric=calls&since={since}").body.decode()
    assert "Einzelaufrufe liegen nur" not in get(web, "metric=calls&days=7").body.decode()


@pytest.mark.parametrize("query", ["metric=unbekannt", "metric=calls&sort=name", "metric=calls&status=offen",
                                   "metric=calls&page=0", "metric=calls&page=x", "metric=calls&mode=x",
                                   "metric=calls&farbe=rot", "metric=calls&days=0", "metric=calls&metric=failed"])
def test_unknown_values_are_rejected_with_422(journal, query):
    web, _ = journal
    assert get(web, query).status == 422


def test_the_list_needs_a_session_and_works_without_metrics(journal):
    from tests.fakes.shared_web_auth import Browser
    web, _ = journal
    stranger = Browser(web.app)
    assert stranger.request("GET", "/auswertung/aufrufe?metric=calls").status in {302, 303}
    web.site.archive.metrics = None
    assert "Noch keine Metrikerfassung verfügbar." in get(web, "metric=calls").body.decode()


def test_comparison_runs_use_their_own_journal(journal, tmp_path):
    web, metrics = journal
    comparison = MetricsRecorder(tmp_path / "comparison.jsonl", MetricsSettings(), mode="decision_test")
    comparison.path.write_text(json.dumps(row(1, mode="decision_test", mail_id=None)) + "\n", encoding="utf-8")
    metrics.comparison = comparison
    html = get(web, "metric=calls&mode=decision_test").body.decode()
    assert len(rows_of(html)) == 1 and "Vergleichslauf" in html and "Vergleichsläufe (Decision-Tests)" in html


@pytest.mark.parametrize(("event", "context", "kind"), [
    ("invalid_json", {}, "invalid_json"), ("provider_response_invalid", {}, "provider_error"),
    ("request_failed", {"status": 429}, "rate_limited"), ("request_failed", {"http_status": 503}, "provider_error"),
    ("request_failed", {"error": TimeoutError("x")}, "timeout"), ("request_failed", {"error": "read timed out"}, "timeout"),
    ("retry_failed", {"error_type": "CancelledError"}, "cancelled"),
    ("request_failed", {"error_type": "SchemaValidationError"}, "schema_invalid"),
    ("request_failed", {"error_type": "DecisionJSONError"}, "invalid_json"),
    ("request_failed", {"status": "error", "error": ValueError("geheim")}, "other"),
    ("request_failed", {"status": True}, "other"),
])
def test_error_kind_classifies_without_keeping_the_message(event, context, kind):
    assert error_kind(event, context) == kind


def test_failed_attempts_store_their_cause_and_old_rows_stay_valid(tmp_path):
    metrics = MetricsRecorder(tmp_path / "m.jsonl", MetricsSettings())
    metrics.observe("request_started", {"call_id": "a", "model": "m", "stage": "summary"})
    metrics.observe("request_failed", {"call_id": "a", "status": 429, "error": RuntimeError("Inhalt der Mail")})
    metrics.observe("request_started", {"call_id": "b", "model": "m", "stage": "summary"})
    metrics.observe("request_started", {"call_id": "b", "model": "m", "stage": "summary"})  # restarted
    metrics.observe("response_received", {"call_id": "b"})
    text = (tmp_path / "m.jsonl").read_text(encoding="utf-8")
    assert "Inhalt der Mail" not in text
    kinds = [json.loads(line).get("error_kind") for line in text.splitlines()]
    assert kinds == ["rate_limited", "cancelled", None]
    old = json.dumps({key: value for key, value in row(1).items() if key != "error_kind"})
    assert AttemptRecord.model_validate_json(old).error_kind is None
