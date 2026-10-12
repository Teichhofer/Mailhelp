"""Activity reports (2.2): counting, reading, judging, restart, limits and user actions."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace as NS

import pytest
from activity_fakes import Mailbox, Model, activity_prompts, definition, raw_mail
from log_fakes import RecordingLogger
from test_application import settings as app_settings

from mailhelp.activity.llm import ActivityAnalyzer
from mailhelp.activity.models import ReportEvent, ReportStatus
from mailhelp.activity.runner import MAX_FAILURES, ActivityRunner, default_report_folders
from mailhelp.activity.scan import SHORTENED, full_text
from mailhelp.activity.service import ActivityService, ReportConflict, event_values
from mailhelp.activity.store import ActivityReportStore
from mailhelp.analysis import Analyzer
from mailhelp.domain.prepared import PreparedMail
from mailhelp.openrouter import RateLimitExceeded
from mailhelp.storage import JsonStore

JAN = datetime(2026, 1, 10, 9, 0, tzinfo=UTC)
RELEVANT = {"relevant": True, "confidence": "high", "reason": "Elternbeirat"}
IRRELEVANT = {"relevant": False, "confidence": "low", "reason": "Werbung"}


def events_answer(payload):
    """Dates proven by the mail; one quote is invented and must be dropped."""
    return {"events": [
        {"title": "Elternabend", "date": "2026-01-20", "start_time": "19:00", "end_time": "20:30",
         "location": "Raum\x0712", "evidence": "am 20. Januar um 19 Uhr"},
        {"title": "\x07", "date": "2028-05-01", "evidence": "Sommerfest  2028"},
        {"title": "Erfunden", "date": "2026-01-21", "evidence": "steht nicht in der Mail"},
        {"title": "Abgesagt", "date": "2026-01-27", "evidence": "Treffen fällt aus", "cancelled": True}]}


def mailbox():
    body = "Einladung: am 20. Januar um 19 Uhr. Sommerfest\n2028. Das Treffen fällt aus."
    inbox = [
        (1, JAN, raw_mail("Elternabend", body, message_id="<a@schule.test>")),
        (2, JAN, raw_mail("Angebot", "Rabatt", sender="Shop <news@shop.test>")),
        (3, JAN, raw_mail("Werbung", "Kaufen")),
        (4, JAN, raw_mail("Newsletter", "Infos", headers={"List-Unsubscribe": "<mailto:x@y.test>"})),
        (5, JAN, raw_mail("Sicherheit", "Bitte Konto bestätigen: https://bit.ly/x")),
        (6, JAN, raw_mail("Groß", "x" * 2000)),
        (7, datetime(2026, 2, 1, 0, 0, tzinfo=UTC), raw_mail("Später", "Februar")),
        (8, datetime(2025, 12, 31, 23, 0, tzinfo=UTC), raw_mail("Früher", "Dezember")),
    ]
    sent = [(1, JAN, raw_mail("Re: Elternabend", "Ich komme am 20. Januar um 19 Uhr", sender="Ich <ich@example.test>",
                              to="Shop <news@shop.test>")),
            (2, JAN, raw_mail("Zusage", "Gerne am 20. Januar um 19 Uhr", sender="Ich <ich@example.test>",
                              to="Schule <info@schule.test>"))]
    archive = [(9, JAN, raw_mail("Elternabend", "Kopie", message_id="<a@schule.test>"))]
    return Mailbox({"INBOX": ("inbox", inbox), "Gesendet": ("sent", sent), "Archiv": (None, archive),
                    "Papierkorb": ("trash", [])})


def relevance_answer(payload):
    return RELEVANT if payload["mail"]["subject"] in {"Elternabend", "Zusage"} else IRRELEVANT


@pytest.fixture
def setup(tmp_path):
    with JsonStore(tmp_path) as store:
        cfg = app_settings(tmp_path)
        model = Model(activity_relevance=relevance_answer, activity_events=events_answer)
        analyzer = Analyzer(model, activity_prompts(), provider_retries=0, json_repair_retries=0,
                            schema_repair_retries=0)
        service = ActivityService(ActivityReportStore(store), clock=lambda: JAN)
        box, log = mailbox(), RecordingLogger()
        runner = ActivityRunner(service, ActivityAnalyzer(analyzer, lambda: "Ich bin im Elternbeirat."),
                                box.connection, cfg, log, lambda: 60)
        yield NS(store=store, cfg=cfg, model=model, service=service, box=box, log=log, runner=runner)


def started(setup, **changes):
    report = setup.service.create(definition(**changes), ["news@shop.test"], [])
    assert setup.runner.tick()
    report = setup.service.store.load(report.id)
    return setup.service.act(report.id, report.version, "start-0001", "start")


def run_all(setup):
    while setup.runner.tick():
        pass


def test_counting_lists_the_period_from_metadata_only(setup):
    report = setup.service.create(definition(folders=["INBOX", "Fehlt"]), [], [])
    assert setup.runner.tick()
    report = setup.service.store.load(report.id)
    assert report.status == ReportStatus.READY and "Fehlt" in report.message
    assert [(item.folder, item.sent, item.uids) for item in report.folders] == [
        ("INBOX", False, [1, 2, 3, 4, 5, 6]), ("Gesendet", True, [1, 2])]
    assert report.counters.listed == 8 and not any(call[0] == "fetch" for call in setup.box.calls)
    # Without sent mail only the chosen folders are listed.
    other = setup.service.create(definition(include_sent=False), [], [])
    setup.runner.tick()
    assert [item.folder for item in setup.service.store.load(other.id).folders] == ["INBOX"]
    assert default_report_folders(setup.box.connection, ["INBOX", "Papierkorb", "Archiv"]) == ["INBOX", "Archiv"]


def test_a_report_reads_judges_and_extracts_only_proven_dates(setup):
    report = started(setup, folders=["INBOX", "Archiv"], skip_automated=True)
    run_all(setup)
    report = setup.service.store.load(report.id)
    assert report.status == ReportStatus.DONE and report.finished_at is not None
    mails = {mail.key: mail for mail in setup.service.store.mails(report.id)}
    by_subject = {(mail.folder, mail.subject): mail for mail in mails.values()}
    invite = by_subject[("INBOX", "Elternabend")]
    assert invite.relevant and invite.confidence == "high" and invite.events_extracted
    assert [(e.title, e.day, e.start_time, e.location, e.cancelled, e.out_of_range) for e in invite.events] == [
        ("Elternabend", date(2026, 1, 20), "19:00", "Raum 12", False, False),
        ("Termin", date(2028, 5, 1), None, None, False, True),
        ("Abgesagt", date(2026, 1, 27), None, None, True, False)]
    assert {key: mail.skipped for key, mail in by_subject.items()} == {
        ("INBOX", "Elternabend"): None, ("INBOX", "Angebot"): "sender", ("INBOX", "Werbung"): None,
        ("INBOX", "Newsletter"): "automated", ("INBOX", "Sicherheit"): "suspicious", ("INBOX", "Groß"): "size",
        ("Archiv", "Elternabend"): "duplicate", ("Gesendet", "Re: Elternabend"): "sender",
        ("Gesendet", "Zusage"): None}
    assert by_subject[("INBOX", "Groß")].sender == "Schule <info@schule.test>"
    assert by_subject[("Gesendet", "Zusage")].sender == "An: Schule <info@schule.test>"
    counters = report.counters
    assert (counters.read, counters.skipped_sender, counters.duplicates, counters.skipped_other) == (9, 2, 1, 3)
    assert (counters.evaluated, counters.relevant, counters.events) == (3, 2, 4)
    assert counters.llm_calls == 5 and len(setup.model.requests) == 5
    first = setup.model.requests[0][1]
    assert first["personal_info"] == "Ich bin im Elternbeirat." and first["report"]["title"] == "Elternbeirat"
    assert sum(event[0][2] == "event_evidence_missing" for event in setup.log.events) == 4
    assert not any(call[0] not in {"open", "discover", "fetch"} for call in setup.box.calls)


def test_a_restart_repeats_only_the_interrupted_call(setup):
    older = setup.service.create(definition(title="Älter"), [], [])
    setup.service.act(older.id, 1, "cancel-001", "cancel")
    report = started(setup)
    setup.model.answers["activity_events"] = RuntimeError("Abbruch")
    with pytest.raises(RuntimeError):
        setup.runner.tick()
    stored = setup.service.store.mails(report.id)
    assert len(stored) == 1 and stored[0].relevant and not stored[0].events_extracted
    # Restart: the reading report waits; continuing does not judge the mail again.
    restarted = ActivityRunner(setup.service, setup.runner.analyzer, setup.box.connection, setup.cfg,
                               setup.log, lambda: 60)
    restarted.recover()
    report = setup.service.store.load(report.id)
    assert report.status == ReportStatus.PAUSED and "Neustart" in report.message
    setup.service.act(report.id, report.version, "resume-001", "resume")
    setup.model.answers["activity_events"] = events_answer
    calls_before = [stage for stage, _ in setup.model.requests]
    restarted.tick()
    assert [stage for stage, _ in setup.model.requests][len(calls_before):][0] == "activity_events"
    assert setup.service.store.mails(report.id)[0].events_extracted


def test_limits_pause_and_mailbox_failures_end_in_a_failed_report(setup):
    setup.cfg.activity_report = setup.cfg.activity_report.model_copy(update={"max_mails": 1})
    report = started(setup)
    setup.runner.tick()
    report = setup.service.store.load(report.id)
    assert report.status == ReportStatus.PAUSED and "Höchstzahl von 1 Mails" in report.message
    setup.cfg.activity_report = setup.cfg.activity_report.model_copy(update={"max_mails": 100, "max_llm_calls": 2})
    setup.service.act(report.id, report.version, "resume-001", "resume")
    setup.runner.tick()
    assert "KI-Aufrufen" in setup.service.store.load(report.id).message
    setup.cfg.activity_report = setup.cfg.activity_report.model_copy(update={"max_llm_calls": 100})
    report = setup.service.store.load(report.id)
    setup.service.act(report.id, report.version, "resume-002", "resume")
    setup.box.fetch_errors = [OSError("weg")]
    setup.runner.tick()
    assert setup.service.store.load(report.id).status == ReportStatus.RUNNING
    setup.box.fetch_errors = [OSError("weg")] * MAX_FAILURES
    for _ in range(MAX_FAILURES):
        setup.runner.tick()
    report = setup.service.store.load(report.id)
    assert report.status == ReportStatus.FAILED and "OSError" in report.message


def test_the_report_uses_only_its_share_and_waits_for_the_shared_budget(setup, monkeypatch):
    clock = [0.0]
    waits = []
    def wait(seconds):
        waits.append(seconds)
        clock[0] += seconds
        return False
    runner = ActivityRunner(setup.service, setup.runner.analyzer, setup.box.connection, setup.cfg, setup.log,
                            lambda: 2, lambda: clock[0])
    monkeypatch.setattr(runner.stop_event, "wait", wait)
    runner._wait_for_budget()
    runner._wait_for_budget()  # 50 % of 2 per minute: the second call waits
    assert waits and sum(waits) >= 5
    attempts = []
    def limited():
        attempts.append(1)
        if len(attempts) == 1:
            raise RateLimitExceeded(0)
        return "ok"
    assert runner._call(limited) == "ok" and len(attempts) == 2
    runner.stop_event.is_set = lambda: True
    with pytest.raises(RateLimitExceeded):
        runner._call(lambda: (_ for _ in ()).throw(RateLimitExceeded(0)))


def test_user_corrections_and_dates_on_request(setup):
    report = started(setup)
    run_all(setup)
    service = setup.service
    report = service.store.load(report.id)
    other = next(mail for mail in service.store.mails(report.id) if mail.subject == "Werbung")
    report = service.set_relevance(report.id, report.version, "rel-00001", other.key, True)
    assert report.pending_extractions == [other.key]
    assert setup.runner.tick() and service.store.mail(report.id, other.key).events_extracted
    report = service.store.load(report.id)
    assert report.pending_extractions == [] and not setup.runner.tick()
    skipped = next(mail for mail in service.store.mails(report.id) if mail.skipped == "sender")
    with pytest.raises(ReportConflict, match="Übersprungene"):
        service.set_relevance(report.id, report.version, "rel-00002", skipped.key, True)
    invite = next(mail for mail in service.store.mails(report.id) if mail.subject == "Elternabend")
    values = event_values("Elternabend (verschoben)", "2026-01-22", "18:00", "", "")
    report = service.set_event(report.id, report.version, "evt-00001", invite.key, "e1", values)
    report = service.set_event(report.id, report.version, "evt-00002", invite.key, "e2", {"excluded": True})
    report = service.set_event(report.id, report.version, "evt-00003", invite.key, None,
                               event_values("Nachtreffen", "2026-01-30", "", "", "Café"))
    events = service.store.mail(report.id, invite.key).events
    assert [(e.id, e.title, e.edited, e.excluded, e.manual) for e in events] == [
        ("e1", "Elternabend (verschoben)", True, False, False), ("e2", "Termin", False, True, False),
        ("e3", "Abgesagt", False, False, False), ("e4", "Nachtreffen", False, False, True)]
    for args, message in (((invite.key, "e9", {"excluded": True}), "nicht gefunden"),
                          (("x", None, values), "nicht im Bericht")):
        with pytest.raises(ReportConflict, match=message):
            service.set_event(report.id, report.version, "evt-00009", *args)
    with pytest.raises(ValueError):
        event_values("Titel", "kein Datum", "", "", "")
    with pytest.raises(ValueError):
        event_values("Titel", "2026-01-01", "25:00", "", "")


def test_actions_check_status_version_and_replays(setup):
    service = setup.service
    report = service.create(definition(), [], [])
    with pytest.raises(ReportConflict, match="aktuellen Stand"):
        service.act(report.id, 1, "start-0001", "start")
    with pytest.raises(ReportConflict, match="laufender"):
        service.delete(report.id, 1)  # counting: still reading metadata
    setup.runner.tick()
    started_report = service.act(report.id, 1, "start-0001", "start")
    assert started_report.version == 2 and started_report.started_at == JAN
    assert service.act(report.id, 1, "start-0001", "start").version == 2  # replay
    for args, message in (((1, "start-0002", "start"), "inzwischen geändert"),
                          ((2, "start-0001", "pause"), "Idempotenzkonflikt"),
                          ((2, "bad", "pause"), "Idempotenzschlüssel"),
                          ((2, "start-0003", "explode"), "Unbekannte Aktion")):
        with pytest.raises(ReportConflict, match=message):
            service.act(report.id, *args)
    with pytest.raises(ReportConflict, match="nicht gefunden"):
        service.act("b" * 32, 1, "start-0004", "pause")
    paused = service.act(report.id, 2, "pause-0001", "pause")
    with pytest.raises(ReportConflict, match="inzwischen"):
        service.delete(report.id, 2)
    cancelled = service.act(report.id, paused.version, "cancel-001", "cancel")
    assert cancelled.status == ReportStatus.CANCELLED and cancelled.finished_at == JAN
    service.delete(report.id, cancelled.version)
    service.delete(report.id, cancelled.version)
    assert service.store.load(report.id) is None


def test_background_loop_and_vanishing_reports(setup, monkeypatch):
    report = started(setup)
    runner = setup.runner
    # The report is deleted while a mail is judged: nothing is written back.
    original = runner.analyzer.relevance
    def delete_meanwhile(*args):
        setup.store.delete("activity-report-" + report.id)
        return original(*args)
    monkeypatch.setattr(runner.analyzer, "relevance", delete_meanwhile)
    runner.tick()
    assert setup.service.store.load(report.id) is None and not runner.tick()
    # Counting a report that was cancelled meanwhile keeps the cancellation.
    counting = setup.service.create(definition(), [], [])
    def cancel_meanwhile():
        setup.service.act(counting.id, 1, "cancel-001", "cancel")
        return setup.box.connection()
    runner.open_reader = cancel_meanwhile
    runner.tick()
    assert setup.service.store.load(counting.id).status == ReportStatus.CANCELLED
    # A failing tick is logged and the loop goes on until it is stopped.
    def failing():
        runner.stop_event.set()
        raise ValueError("privat")
    runner.tick = failing
    runner.start()
    runner.stop()
    assert setup.log.events[-1] == (("ERROR", "activity", "background_failed"), {"error_class": "ValueError"})
    idle = ActivityRunner(setup.service, runner.analyzer, setup.box.connection, setup.cfg, setup.log)
    idle.stop_event.wait = lambda seconds: idle.stop_event.set()
    idle.run()
    idle.stop()
    # Work done: the next unit follows at once, without waiting.
    busy = ActivityRunner(setup.service, runner.analyzer, setup.box.connection, setup.cfg, setup.log)
    busy.stop_event.wait = lambda seconds: pytest.fail("no wait after work")
    busy.tick = lambda: (busy.stop_event.set(), True)[1]
    busy.run()


def test_full_text_includes_attachments_and_is_cut_with_a_marker():
    prepared = PreparedMail.model_validate({"text": "Mailtext", "extracted_attachments": [
        {"filename": "plan.pdf", "text": "Ablauf"}, {"filename": "leer.pdf", "text": " "}]})
    assert full_text(prepared, 1000) == "Mailtext\n\n--- Anhang: plan.pdf ---\nAblauf"
    cut = full_text(PreparedMail.model_validate({"text": "y" * 2000}), 1000)
    assert len(cut) == 1000 and cut.endswith(SHORTENED)


def test_an_unreadable_mail_and_a_requested_mail_without_text_are_skipped(setup, monkeypatch):
    report = started(setup)
    monkeypatch.setattr("mailhelp.activity.scan.prepare", lambda *a: (_ for _ in ()).throw(LookupError("cp")))
    setup.runner.tick()
    first = setup.service.store.mails(report.id)[0]
    assert first.skipped == "unreadable"
    first.skipped, first.text_removed = None, True
    setup.service.store.save_mail(report.id, first)
    current = setup.service.store.load(report.id)
    current.pending_extractions = [first.key, "fehlt"]
    setup.service.store.save(current)
    setup.runner.extract_requested(report.id)
    setup.runner.extract_requested(report.id)
    assert setup.service.store.load(report.id).pending_extractions == []
    assert not setup.service.store.mail(report.id, first.key).events_extracted


def test_period_end_is_exclusive_in_the_configured_zone(setup):
    setup.cfg.timezone = "Europe/Berlin"
    report = setup.service.create(definition(until=date(2026, 1, 31)), [], [])
    setup.runner.tick()
    # 2026-02-01 00:00 UTC is 01:00 in Berlin: outside; 2025-12-31 23:00 UTC is already January in Berlin.
    assert setup.service.store.load(report.id).folders[0].uids == [1, 2, 3, 4, 5, 6, 8]
    assert setup.box.calls[1][2] == datetime(2026, 1, 1, tzinfo=UTC) - timedelta(hours=1)


def test_remaining_paths_of_run_and_service(setup, monkeypatch):
    from mailhelp.activity import runner as runner_module
    from mailhelp.activity import service as service_module
    from mailhelp.activity.scan import _header
    # A batch ends after BATCH mails even if more are waiting.
    monkeypatch.setattr(runner_module, "BATCH", 1)
    report = started(setup)
    setup.runner.tick()
    assert setup.service.store.load(report.id).processed == 1
    # Paused exactly while the run finishes: the user's pause wins over "done".
    def pause_first(current):
        setup.service.act(current.id, current.version, "pause-0001", "pause")
        return "Grenze"
    monkeypatch.setattr(setup.runner, "_limit_reached", pause_first)
    setup.runner.tick()
    paused = setup.service.store.load(report.id)
    assert paused.status == ReportStatus.PAUSED and paused.message == ""
    # Only reading reports are paused by a restart.
    setup.runner.recover()
    assert setup.service.store.load(report.id).message == ""
    # Saying "not relevant" requests nothing; the operation log stays bounded.
    monkeypatch.setattr(service_module, "MAX_OPERATIONS", 1)
    mail = setup.service.store.mails(report.id)[0]
    paused = setup.service.set_relevance(report.id, paused.version, "rel-00001", mail.key, False)
    assert paused.pending_extractions == [] and list(paused.operations) == ["rel-00001"]
    mail.events = [ReportEvent(id=f"e{n}", title="T", day=date(2026, 1, 1)) for n in range(1, 51)]
    setup.service.store.save_mail(report.id, mail)
    with pytest.raises(ReportConflict, match="Zu viele"):
        setup.service.set_event(report.id, paused.version, "evt-00001", mail.key, None,
                                event_values("Neu", "2026-01-02", "", "", ""))
    # Undecodable headers read as empty instead of stopping the report.
    class Broken:
        def get(self, name, default=""):
            raise ValueError("kaputt")
    assert _header(Broken(), "Subject") == "" and _header({"Subject": " a\n  b "}, "Subject") == "a b"
