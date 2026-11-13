"""6.1.6: the wall time of every processing step is journaled, content-free, with the AI share and run time."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from mailhelp.config import Topic
from mailhelp.mailbox.imap import FetchedMail
from mailhelp.processing.mail_pipeline import ProcessingRun
from mailhelp.processing.orchestrator import Orchestrator, ProcessingOutcome
from mailhelp.processing.stage_timing import StageClock, part
from mailhelp.runtime.metrics import MetricsRecorder, MetricsSettings
from mailhelp.runtime.stage_metrics import TOTAL, StageJournal, StageRecord, journal_path
from mailhelp.storage import JsonStore
from tests.fakes.shared_services import AnalyzerStub, Notify

ACCOUNT = "c" * 24
RAW = (b"From: Amt <amt@example.test>\nSubject: Geheimer Betreff Vortrag\nMessage-ID: <v1@example.test>\n\n"
       b"Beginn 12.11.2026, 18:30 Uhr")
MAIL = FetchedMail("INBOX", 7, 41, RAW, ACCOUNT)


class MetricsLogger:
    """Forwards events to a real MetricsRecorder, as the application's logger does."""

    def __init__(self, metrics):
        self.metrics = metrics

    def event(self, level, component, event, **context):
        self.metrics.observe(event, context)

    def llm_event(self, event, **context):
        self.metrics.observe(event, context)


def process(tmp_path, analyzer, enabled=True):
    metrics = MetricsRecorder(tmp_path / "logs" / "metrics.jsonl", MetricsSettings(enabled=enabled))
    with JsonStore(tmp_path / "data") as store:
        run = Orchestrator(analyzer, store, Notify(), 1, [Topic(id="t", name="T", enabled=True, description="t")],
                           100_000, logger=MetricsLogger(metrics))
        result = run.process(MAIL)
    return metrics, result


def lines(metrics):
    path = journal_path(metrics.path)
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def test_regression_every_step_of_a_mail_has_a_duration_and_the_mail_a_run_time(tmp_path):
    """Regression 6.1: only AI calls were measured; parsing, attachments, proposal building, duplicate
    check, notifications and completion had no duration, the evaluation said "lokal · nicht gemessen"."""
    metrics, result = process(tmp_path, AnalyzerStub("relevant"))
    assert result.outcome is ProcessingOutcome.COMPLETED
    records = lines(metrics)
    stages = [item["stage"] for item in records]
    assert stages[0] == "preparation" and stages[-2:] == ["completion", TOTAL]
    assert {"relevance", "summary", "normalization", "proposal_building", "proposal_notification"} <= set(stages)
    assert len(stages) == len(set(stages))  # every step once
    steps, total = records[:-1], records[-1]
    assert all(item["outcome"] == "completed" and not item["resumed"] for item in steps)
    assert total["duration_ms"] == pytest.approx(sum(item["duration_ms"] for item in steps))
    assert total["waiting_ms"] >= 0 and set(steps[0]["parts"]) == {"zerlegen", "anhaenge"}
    text = journal_path(metrics.path).read_text(encoding="utf-8")
    assert "Geheimer Betreff" not in text and "amt@example.test" not in text  # content-free


def test_an_irrelevant_mail_and_a_failed_step(tmp_path):
    metrics, _ = process(tmp_path / "a", AnalyzerStub("irrelevant"))
    assert [item["stage"] for item in lines(metrics)] == ["preparation", "relevance", "completion", TOTAL]

    class Broken(AnalyzerStub):
        def summary(self, mail):
            raise RuntimeError("synthetic")
    metrics, result = process(tmp_path / "b", Broken("relevant"))
    records = lines(metrics)
    assert records[-1]["stage"] == "summary" and records[-1]["outcome"] == "failed"
    assert TOTAL not in [item["stage"] for item in records]


def test_a_mail_waiting_for_a_decision_is_deferred_and_resumed_later(tmp_path):
    metrics, result = process(tmp_path, AnalyzerStub("unclear"))
    assert result.outcome is ProcessingOutcome.WAITING
    assert lines(metrics)[-1]["outcome"] == "deferred"
    clock = StageClock(lambda record: None, "a" * 24, 1, True)
    clock.enter("relevance")
    clock.enter("relevance")  # the same step again changes nothing
    assert clock.current == "relevance" and clock.resumed


def test_switched_off_metrics_measure_nothing_and_a_write_failure_stops_nothing(tmp_path):
    metrics, result = process(tmp_path / "off", AnalyzerStub("relevant"), enabled=False)
    assert result.outcome is ProcessingOutcome.COMPLETED and lines(metrics) == []
    journal = StageJournal(tmp_path / "ordner", lambda: 90)
    (tmp_path / "ordner").mkdir()
    journal.write(StageRecord(id="a" * 32, run_id="r", mode="standard", stage="relevance",
                              started_at=datetime.now(UTC), duration_ms=1, outcome="completed"))
    assert journal.failures == 1


def test_ai_calls_of_the_same_mail_within_a_step_are_its_ai_share(tmp_path):
    metrics = MetricsRecorder(tmp_path / "metrics.jsonl", MetricsSettings())
    mail, other = "a" * 24, "b" * 24
    started = datetime.now(UTC).timestamp()
    for call, owner in (("c1", mail), ("c2", other)):
        metrics.observe("request_started", {"call_id": call, "model": "m", "stage": "relevance", "mail_id": owner})
        metrics.observe("response_received", {"call_id": call})
    metrics.observe("stage_finished", {"mail_id": mail, "stage": "relevance", "outcome": "completed",
                                       "started_wall": started - 0.01, "duration_ms": 60_000, "parts": {},
                                       "analysis_round": 1, "resumed": False, "final": False})
    (record,) = lines(metrics)
    own = [item for item in metrics.records()[0] if item["mail_id"] == mail]
    assert record["llm_ms"] == pytest.approx(own[0]["duration_ms"])


def test_the_run_time_leaves_out_waiting_between_passes(tmp_path):
    journal = StageJournal(tmp_path / "s.jsonl", lambda: 90)
    first = datetime.now(UTC) - timedelta(hours=8)
    base = dict(run_id="r", mode="standard", outcome="completed", mail_id="a" * 24)
    journal.write(StageRecord(id="1" * 32, stage="relevance", started_at=first, duration_ms=2000, llm_ms=1500,
                              **{**base, "outcome": "deferred"}))
    last = StageRecord(id="2" * 32, stage="completion", started_at=first + timedelta(hours=8), duration_ms=1000,
                       resumed=True, **base)
    journal.write(last)
    total = journal.total(last)
    assert total.duration_ms == 3000 and total.llm_ms == 1500
    assert total.waiting_ms == pytest.approx(8 * 3600 * 1000 - 2000, abs=1)


def test_damaged_lines_duplicates_and_the_retention_period(tmp_path):
    path = tmp_path / "s.jsonl"
    assert StageJournal(path, lambda: 90).records() == []  # nothing recorded yet
    old = StageRecord(id="1" * 32, run_id="r", mode="standard", stage="relevance", outcome="completed",
                      started_at=datetime.now(UTC) - timedelta(days=100), duration_ms=1)
    new = old.model_copy(update={"id": "2" * 32, "started_at": datetime.now(UTC)})
    path.write_text("\n".join([old.model_dump_json(), new.model_dump_json(), new.model_dump_json(), "kaputt"]) + "\n",
                    encoding="utf-8")
    journal = StageJournal(path, lambda: 90)
    assert [item["id"] for item in journal.records()] == ["2" * 32] and journal.damaged == 1
    assert journal.records() == journal.records()  # cached until the file changes


def test_parts_and_the_run_hook():
    emitted = []
    times = iter([0.0, 1.0, 3.0, 4.0])
    clock = StageClock(emitted.append, "a" * 24, 2, False, monotonic=lambda: next(times), wall=lambda: 100.0)
    clock.enter("preparation")
    with part(clock, "zerlegen"):
        pass
    clock.finish("completed", final=True)
    assert emitted == [{"mail_id": "a" * 24, "stage": "preparation", "outcome": "completed", "started_wall": 100.0,
                        "duration_ms": 4000.0, "parts": {"zerlegen": 2000.0}, "analysis_round": 2,
                        "resumed": False, "final": True}]
    clock.finish("completed")  # nothing running: nothing emitted
    assert len(emitted) == 1
    with part(None, "ohne Uhr"):
        pass
    run = ProcessingRun("mail-x", SimpleNamespace(), SimpleNamespace(value="preparation"), 0.0)
    run.timer = SimpleNamespace(enter=emitted.append)
    run.stage = SimpleNamespace(value="relevance")
    assert emitted[-1] == "relevance"
