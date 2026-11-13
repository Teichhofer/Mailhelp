"""6.1.7: step times are queried by period and folded into daily figures beyond the retention period."""
import json
from datetime import UTC, datetime, timedelta

import pytest

from mailhelp.runtime.metrics import MetricsRecorder, MetricsSettings
from mailhelp.runtime.stage_metrics import TOTAL, StageJournal, StageRecord, compact, median, quantile, report

NOW = datetime.now(UTC)


def line(identity, stage="relevance", days=0, duration=1000.0, mail="a" * 24, **changes):
    values = {"id": f"{identity:032x}", "run_id": "r", "mode": "standard", "stage": stage, "outcome": "completed",
              "started_at": NOW - timedelta(days=days), "duration_ms": duration, "mail_id": mail}
    return StageRecord(**{**values, **changes})


def journal(tmp_path, *records, retention=90):
    store = StageJournal(tmp_path / "metrics-stages.jsonl", lambda: retention)
    for record in records:
        store.write(record)
    return store


@pytest.mark.parametrize(("values", "middle", "high"), [([5.0], 5.0, 5.0), ([1.0, 3.0], 2.0, 3.0),
                                                         ([float(n) for n in range(1, 101)], 50.5, 95.0)])
def test_median_and_95_percent(values, middle, high):
    assert median(values) == middle and quantile(values, .95) == high


def test_the_report_groups_steps_and_run_times_with_filters(tmp_path):
    store = journal(tmp_path, line(1, duration=1000, llm_ms=800), line(2, duration=3000, mail="b" * 24),
                    line(3, stage="normalization", duration=10, parts={"x": 1.0}),
                    line(4, stage="summary", outcome="failed", duration=500),
                    line(5, stage=TOTAL, duration=4010, waiting_ms=60_000),
                    line(6, days=10), line(7, mode="decision_test"))
    result = report(store, days=7, mode="production")
    relevance = result["stages"]["relevance"]
    assert (relevance["count"], relevance["sum_ms"], relevance["median_ms"], relevance["max_ms"]) == (2, 4000, 2000, 3000)
    assert relevance["llm_ms"] == 800 and relevance["per_mail_median_ms"] == 2000
    assert result["stages"]["summary"]["failed"] == 1 and result["parts"] == {"x": 1.0}
    assert result["total"]["count"] == 1 and result["waiting_median_ms"] == 60_000
    assert report(store, days=30, mode="production")["stages"]["relevance"]["count"] == 3
    assert list(report(store, days=7, stage="summary")["stages"]) == ["summary"]
    today = NOW.date().isoformat()
    assert report(store, days=30, since=today, until=today)["stages"]["relevance"]["count"] == 3
    empty = report(journal(tmp_path / "leer"), days=7)
    assert empty["stages"] == {} and empty["total"]["median_ms"] is None and empty["waiting_median_ms"] is None
    no_mail = report(journal(tmp_path / "ohne", line(8, mail=None)), days=7)
    assert no_mail["stages"]["relevance"]["per_mail_median_ms"] is None


def test_lines_beyond_the_retention_are_folded_once_even_after_an_interrupted_fold(tmp_path):
    store = journal(tmp_path, line(1, days=100), line(2, days=100, duration=3000), line(3))
    compact(store)
    daily = json.loads(store.sibling("daily").read_text(encoding="utf-8"))
    (key,) = daily
    assert json.loads(key)[1:] == ["standard", "relevance"] and daily[key]["count"] == 2
    assert [item["id"] for item in store.records()] == [f"{3:032x}"]
    compact(store)  # nothing expired: unchanged
    assert json.loads(store.sibling("daily").read_text(encoding="utf-8")) == daily
    # A later fold of the same day adds to the figures.
    store.write(line(4, days=100, duration=500))
    compact(store)
    assert json.loads(store.sibling("daily").read_text(encoding="utf-8"))[key]["count"] == 3
    # A crash after writing the operation journal: the restart applies it instead of counting twice.
    operation = {"daily": {"x": {"count": 9}}, "retained": line(5).model_dump_json() + "\n"}
    store.sibling("compaction").write_text(json.dumps(operation), encoding="utf-8")
    restarted = StageJournal(store.path, lambda: 90)
    compact(restarted)
    assert json.loads(restarted.sibling("daily").read_text(encoding="utf-8")) == {"x": {"count": 9}}
    assert [item["id"] for item in restarted.records()] == [f"{5:032x}"]
    assert not restarted.sibling("compaction").exists()


def test_metrics_maintenance_also_folds_the_step_journal(tmp_path):
    metrics = MetricsRecorder(tmp_path / "metrics.jsonl", MetricsSettings(retention_days=1))
    metrics.stages.write(line(1, days=5))
    metrics.maintain()
    assert metrics.stages.records() == [] and metrics.stages.sibling("daily").exists()
