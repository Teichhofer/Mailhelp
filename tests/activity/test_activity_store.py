"""Activity reports (2.2): models, storage in blocks, deletion and retention."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError

from mailhelp.activity import store as store_module
from mailhelp.activity.models import ActivityReport, ReportDefinition, ReportEvent, ReportMail, ReportStatus
from mailhelp.activity.store import ActivityReportStore, mails_name, report_name
from mailhelp.fingerprints import config_fingerprint, legacy_fingerprints, legacy_policies, topic_policy
from mailhelp.retention import RetentionService
from mailhelp.storage import JsonStore

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)


def definition(**changes) -> ReportDefinition:
    values = dict(title="Elternbeirat 2025/26", topic="Termine und Aufgaben des Elternbeirats der Klasse 4b",
                  since=date(2025, 9, 1), until=date(2026, 7, 31), folders=["INBOX", "Sent"])
    return ReportDefinition(**(values | changes))


def mail(key: str, **changes) -> ReportMail:
    values = dict(key=key, folder="INBOX", uid=int(key.split(":")[-1]), received_at=NOW,
                  sender="Schule <info@schule.test>", subject="Elternabend", text="Volltext " + key)
    return ReportMail(**(values | changes))


def test_definitions_are_bounded_and_unambiguous():
    assert definition().include_sent and not definition().skip_automated
    for changes, message in (({"since": date(2026, 8, 1)}, "beginnt nach"),
                             ({"until": date(2028, 12, 31)}, "drei Jahre"),
                             ({"folders": ["INBOX", "INBOX"]}, "nur einmal"),
                             ({"topic": "kurz"}, "at least 10"),
                             ({"title": "Bericht\x07"}, "pattern")):
        with pytest.raises(ValidationError, match=message):
            definition(**changes)


def test_report_progress_relevance_override_and_range():
    report = ActivityReport(id="a" * 32, definition=definition(),
                            folders=[{"folder": "INBOX", "uids": [1, 2, 3], "done": 2},
                                     {"folder": "Sent", "sent": True, "uids": [9], "done": 1}])
    assert (report.total, report.processed, report.status) == (4, 3, ReportStatus.COUNTING)
    assert report.in_range(date(2025, 8, 2)) and not report.in_range(date(2025, 8, 1))
    assert report.in_range(date(2027, 7, 31)) and not report.in_range(date(2027, 8, 1))
    assert not mail("1:1").counts_as_relevant and mail("1:1", relevant=True).counts_as_relevant
    assert not mail("1:1", relevant=True, user_relevant=False).counts_as_relevant
    with pytest.raises(ValidationError):
        ReportEvent(id="x1", title="T", day=date(2026, 1, 1))
    with pytest.raises(ValidationError):
        ReportEvent(id="e1", title="T", day=date(2026, 1, 1), start_time="25:00")


def test_reports_and_mails_survive_restart_in_blocks(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "CHUNK", 2)
    with JsonStore(tmp_path) as store:
        reports = ActivityReportStore(store)
        older = reports.create(definition(title="Alt"), ["a@test"], ["test"])
        older.created_at = NOW - timedelta(days=1)
        reports.save(older)
        report = reports.create(definition(), [], [])
        for uid in (1, 2, 3):
            reports.save_mail(report.id, mail(f"7:{uid}"))
        reports.save_mail(report.id, mail("7:2", relevant=True))
        assert sorted(store.names(mails_name(report.id, 0)[:-1])) == [mails_name(report.id, 0), mails_name(report.id, 1)]
    with JsonStore(tmp_path) as store:
        reports = ActivityReportStore(store)
        assert [item.definition.title for item in reports.reports()] == ["Elternbeirat 2025/26", "Alt"]
        assert reports.load(older.id).blocked_addresses == ["a@test"]
        assert [item.key for item in reports.mails(report.id)] == ["7:1", "7:2", "7:3"]
        assert reports.mail(report.id, "7:2").relevant and reports.mail(report.id, "7:9") is None
        reports.delete(report.id)
        reports.delete(report.id)
        assert reports.load(report.id) is None and reports.mails(report.id) == []
        assert store.names("activity-") == [report_name(older.id)]
        assert reports.load("b" * 32) is None


def test_retention_removes_only_expired_full_texts(tmp_path):
    with JsonStore(tmp_path) as store:
        reports = ActivityReportStore(store)
        expired, recent, running = (reports.create(definition(title=title), [], []) for title in "ABC")
        for report, finished in ((expired, NOW - timedelta(days=400)), (recent, NOW - timedelta(days=10))):
            report.finished_at = finished
            reports.save(report)
        event = ReportEvent(id="e1", title="Elternabend", day=date(2025, 10, 7), evidence="am 7. Oktober")
        for report in (expired, recent, running):
            reports.save_mail(report.id, mail("7:1", events=[event]))
        assert reports.remove_expired_texts("unlimited", NOW) == 0
        assert reports.remove_expired_texts(365, NOW) == 1
        assert reports.remove_expired_texts(365, NOW) == 0  # already removed, not rewritten
        kept = reports.mail(expired.id, "7:1")
        assert (kept.text, kept.text_removed, kept.events[0].evidence) == ("", True, "")
        assert (kept.subject, kept.sender, kept.events[0].day) == ("Elternabend", "Schule <info@schule.test>",
                                                                   date(2025, 10, 7))
        assert reports.mail(recent.id, "7:1").text == "Volltext 7:1"
        assert reports.remove_expired_texts("disabled", NOW) == 1
        assert reports.mail(running.id, "7:1").text == "Volltext 7:1"


def test_retention_service_runs_the_activity_cleanup(tmp_path):
    from shared_application import Log, settings
    with JsonStore(tmp_path) as store:
        reports = ActivityReportStore(store)
        report = reports.create(definition(), [], [])
        report.finished_at = NOW - timedelta(days=2)
        reports.save(report)
        reports.save_mail(report.id, mail("7:1"))
        retention = settings(tmp_path).retention.model_copy(update={"activity_report_days": 1})
        log = Log()
        assert RetentionService(store, retention, log, clock=lambda: NOW).run().activity_scrubbed == 1
        assert log.events[-1][1]["activity_count"] == 1


def test_activity_settings_never_change_an_analysis_fingerprint(tmp_path):
    """The report and its prompts act outside the analysis; mails in progress must not wait."""
    from shared_application import settings
    from shared_core import prompt_config

    from mailhelp.config import PromptStep
    cfg, prompts = settings(tmp_path), prompt_config()
    before = (config_fingerprint(cfg, prompts, []), legacy_fingerprints(cfg, prompts, []),
              legacy_policies(cfg, prompts), topic_policy(cfg, prompts))
    cfg.activity_report = cfg.activity_report.model_copy(update={"enabled": True, "max_mails": 10})
    cfg.retention = cfg.retention.model_copy(update={"activity_report_days": 7})
    prompts.prompts["activity_relevance"] = PromptStep(system_prompt="Relevanz")
    prompts.prompts["activity_events"] = PromptStep(system_prompt="Termine")
    assert before == (config_fingerprint(cfg, prompts, []), legacy_fingerprints(cfg, prompts, []),
                      legacy_policies(cfg, prompts), topic_policy(cfg, prompts))
