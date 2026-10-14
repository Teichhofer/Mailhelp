"""Unit-Tests für den DuplicatePreCheckService in Mailhelp 1.3."""
from datetime import UTC, date, datetime

import httpx

from mailhelp.domain.proposal import (
    DuplicateSource,
    Proposal,
    ProposalCertainty,
    ProposalClassification,
    ProposalKind,
    ProposalResponsibility,
    ProposalStatus,
)
from mailhelp.integrations import HttpWriter
from mailhelp.persistence.ledger import ActionLedgerEntry, ActionLedgerPort
from mailhelp.precheck import DuplicatePreCheckService


class DummyLedger(ActionLedgerPort):
    def __init__(self, entries=None, raise_exc=False):
        self.entries = entries or []
        self.raise_exc = raise_exc

    def record_success(self, proposal, external_id, external_link, execution_time_seconds=0.0):
        pass

    def record_simulated(self, proposal, execution_time_seconds=0.0):
        pass

    def book_created(self, proposal):
        pass

    def prior_actions(self, proposal):
        if self.raise_exc:
            raise RuntimeError("Ledger DB failure")
        return self.entries


def make_event_proposal(
    proposal_id="p1",
    title="Projektmeeting",
    start=datetime(2026, 10, 15, 10, 0, tzinfo=UTC),
    end=datetime(2026, 10, 15, 11, 0, tzinfo=UTC),
    all_day=False,
    classification=ProposalClassification.NEW,
    status=ProposalStatus.PENDING_CONFIRMATION,
    open_questions=None,
):
    return Proposal(
        schema_version=2,
        id=proposal_id,
        version=1,
        kind=ProposalKind.EVENT,
        responsibility=ProposalResponsibility.USER,
        certainty=ProposalCertainty.CERTAIN,
        classification=classification,
        title=title,
        description="Besprechung",
        evidence="im Text",
        source_mail_id="a" * 24,
        open_questions=open_questions or [],
        target="primary",
        status=status,
        start=start,
        end=end,
        all_day=all_day,
    )


def make_task_proposal(proposal_id="p2", title="Bericht schreiben"):
    return Proposal(
        schema_version=2,
        id=proposal_id,
        version=1,
        kind=ProposalKind.TASK,
        responsibility=ProposalResponsibility.USER,
        certainty=ProposalCertainty.CERTAIN,
        classification=ProposalClassification.NEW,
        title=title,
        description="Quartalsbericht",
        evidence="im Text",
        source_mail_id="b" * 24,
        open_questions=[],
        target="inbox",
        status=ProposalStatus.PENDING_CONFIRMATION,
    )


def test_precheck_empty_and_passthrough():
    service = DuplicatePreCheckService()
    prop = make_event_proposal()
    res = service.check_proposal(prop)
    assert res == prop


def test_precheck_ledger_match():
    entry = ActionLedgerEntry(
        action_key="a" * 64,
        action_key_version=2,
        mail_id="b" * 24,
        proposal_id="p1",
        proposal_version=1,
        kind=ProposalKind.EVENT,
        title="Projektmeeting",
        target="primary",
        external_id="ext-123",
        external_link="https://calendar.google.com/event?id=ext-123",
        created_at=datetime(2026, 10, 10, 8, 0, tzinfo=UTC),
    )
    ledger = DummyLedger(entries=[entry])
    service = DuplicatePreCheckService(ledger=ledger)
    prop = make_event_proposal()
    res = service.check_proposal(prop)
    assert res.status == ProposalStatus.ALREADY_EXISTS
    assert res.duplicate_match is not None
    assert res.duplicate_match.source == DuplicateSource.ACTION_LEDGER
    assert res.duplicate_match.external_id == "ext-123"
    assert res.duplicate_match.external_link == "https://calendar.google.com/event?id=ext-123"
    assert "Bereits erfolgreich über Mailhelp angelegt" in res.duplicate_match.details


def test_precheck_ledger_exception_resilience():
    ledger = DummyLedger(raise_exc=True)
    service = DuplicatePreCheckService(ledger=ledger)
    prop = make_event_proposal()
    # Does not crash, continues
    res = service.check_proposal(prop)
    assert res.status == ProposalStatus.NEEDS_CLARIFICATION
    assert res.duplicate_check_failed and not res.is_creatable


def test_precheck_calendar_exact_duplicate():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "items": [
                {
                    "id": "cal-evt-1",
                    "summary": "Projektmeeting",
                    "htmlLink": "https://calendar.google.com/event?id=cal-evt-1",
                    "start": {"dateTime": "2026-10-15T10:00:00Z"},
                    "end": {"dateTime": "2026-10-15T11:00:00Z"},
                }
            ]
        })

    writer = HttpWriter(
        service="google_calendar",
        token="tok",
        target="primary",
        calendar_timezone="UTC",
        transport=httpx.MockTransport(handler),
    )
    service = DuplicatePreCheckService(writer=writer)
    prop = make_event_proposal()
    res = service.check_proposal(prop)
    assert res.status == ProposalStatus.ALREADY_EXISTS
    assert res.duplicate_match is not None
    assert res.duplicate_match.source == DuplicateSource.GOOGLE_CALENDAR
    assert res.duplicate_match.external_id == "cal-evt-1"
    assert res.duplicate_match.external_link == "https://calendar.google.com/event?id=cal-evt-1"
    assert res.duplicate_match.details == "Bereits im Kalender eingetragen (Google Kalender)"


def test_precheck_calendar_reschedule_detected():
    # Existing event is at 14:00, proposal wants 10:00
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "items": [
                {
                    "id": "cal-evt-1",
                    "summary": "Projektmeeting",
                    "start": {"dateTime": "2026-10-15T14:00:00Z"},
                    "end": {"dateTime": "2026-10-15T15:00:00Z"},
                }
            ]
        })

    writer = HttpWriter(
        service="google_calendar",
        token="tok",
        target="primary",
        calendar_timezone="UTC",
        transport=httpx.MockTransport(handler),
    )
    service = DuplicatePreCheckService(writer=writer)
    prop = make_event_proposal()
    res = service.check_proposal(prop)
    # Stays PENDING_CONFIRMATION, but has target_event_id and time_changes!
    assert res.status == ProposalStatus.PENDING_CONFIRMATION
    assert res.target_event_id == "cal-evt-1"
    assert len(res.time_changes) > 0
    assert any("Beginn" in c for c in res.time_changes)
    assert not res.is_cancellation


def test_precheck_calendar_cancellation():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "items": [
                {
                    "id": "cal-evt-1",
                    "summary": "Projektmeeting",
                    "start": {"dateTime": "2026-10-15T10:00:00Z"},
                    "end": {"dateTime": "2026-10-15T11:00:00Z"},
                }
            ]
        })

    writer = HttpWriter(
        service="google_calendar",
        token="tok",
        target="primary",
        calendar_timezone="UTC",
        transport=httpx.MockTransport(handler),
    )
    service = DuplicatePreCheckService(writer=writer)
    prop = make_event_proposal(
        classification=ProposalClassification.CANCELLATION,
        status=ProposalStatus.NEEDS_CLARIFICATION,
        open_questions=["Welcher bestehende Eintrag soll storniert werden?"],
    )
    res = service.check_proposal(prop)
    assert res.target_event_id == "cal-evt-1"
    assert res.is_cancellation is True


def test_precheck_calendar_matcher_branch():
    class DummyDecision:
        def __init__(self, same_event):
            self.same_event = same_event

    def matcher(proposal, existing):
        return ("call-1", DummyDecision(False))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "items": [
                {
                    "id": "cal-evt-1",
                    "summary": "Projektmeeting",
                    "start": {"dateTime": "2026-10-15T10:00:00Z"},
                    "end": {"dateTime": "2026-10-15T11:00:00Z"},
                }
            ]
        })

    writer = HttpWriter(
        service="google_calendar",
        token="tok",
        target="primary",
        calendar_timezone="UTC",
        calendar_matcher=matcher,
        transport=httpx.MockTransport(handler),
    )
    service = DuplicatePreCheckService(writer=writer)
    prop = make_event_proposal()
    res = service.check_proposal(prop)
    # Matcher returned False -> no match
    assert res.status == ProposalStatus.PENDING_CONFIRMATION
    assert res.target_event_id is None


def test_precheck_calendar_exception_resilience():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Network down")

    writer = HttpWriter(
        service="google_calendar",
        token="tok",
        target="primary",
        calendar_timezone="UTC",
        transport=httpx.MockTransport(handler),
    )
    service = DuplicatePreCheckService(writer=writer)
    prop = make_event_proposal()
    res = service.check_proposal(prop)
    assert res.status == ProposalStatus.NEEDS_CLARIFICATION
    assert res.duplicate_check_failed and not res.is_creatable


def test_precheck_calendar_date_only_branch():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "items": [
                {
                    "id": "cal-evt-1",
                    "summary": "Ganztägig",
                    "start": {"date": "2026-10-15"},
                    "end": {"date": "2026-10-16"},
                }
            ]
        })

    writer = HttpWriter(
        service="google_calendar",
        token="tok",
        target="primary",
        calendar_timezone="UTC",
        transport=httpx.MockTransport(handler),
    )
    service = DuplicatePreCheckService(writer=writer)
    prop = make_event_proposal(
        title="Ganztägig",
        start=date(2026, 10, 15),
        end=date(2026, 10, 16),
        all_day=True,
    )
    res = service.check_proposal(prop)
    assert res.status == ProposalStatus.ALREADY_EXISTS


def test_precheck_todoist_match_and_exception():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "results": [
                {
                    "id": 12345,
                    "content": "Bericht schreiben",
                    "url": "https://todoist.com/showTask?id=12345",
                }
            ],
            "next_cursor": None,
        })

    writer = HttpWriter(
        service="todoist",
        token="tok",
        target="inbox",
        transport=httpx.MockTransport(handler),
    )
    service = DuplicatePreCheckService(writer=writer)
    prop = make_task_proposal()
    res = service.check_proposal(prop)
    assert res.status == ProposalStatus.ALREADY_EXISTS
    assert res.duplicate_match is not None
    assert res.duplicate_match.source == DuplicateSource.TODOIST
    assert res.duplicate_match.external_id == "12345"
    assert res.duplicate_match.external_link == "https://todoist.com/showTask?id=12345"
    assert res.duplicate_match.details == "Bereits als Aufgabe vorhanden (Todoist)"

    # Todoist error resilience
    err_writer = HttpWriter(
        service="todoist",
        token="tok",
        target="inbox",
        transport=httpx.MockTransport(lambda _r: httpx.Response(500, json={})),
    )
    # when fetch_active_tasks returns empty list on 500 error
    service_err = DuplicatePreCheckService(writer=err_writer)
    res2 = service_err.check_proposal(prop)
    assert res2.status == ProposalStatus.NEEDS_CLARIFICATION
    assert res2.duplicate_check_failed and not res2.is_creatable


def test_precheck_writers_dict_multi_service():
    def cal_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": []})

    def todo_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "results": [{"id": 99, "content": "Bericht schreiben"}],
            "next_cursor": None,
        })

    cal_writer = HttpWriter(
        service="google_calendar",
        token="tok",
        target="primary",
        calendar_timezone="UTC",
        transport=httpx.MockTransport(cal_handler),
    )
    todo_writer = HttpWriter(
        service="todoist",
        token="tok",
        target="inbox",
        transport=httpx.MockTransport(todo_handler),
    )

    service = DuplicatePreCheckService(writers={"google_calendar": cal_writer, "todoist": todo_writer})

    # Event has no match -> returns event
    event_res = service.check_proposal(make_event_proposal())
    assert event_res.status == ProposalStatus.PENDING_CONFIRMATION

    # Task matches Todoist -> returns ALREADY_EXISTS
    task_res = service.check_proposal(make_task_proposal())
    assert task_res.status == ProposalStatus.ALREADY_EXISTS


def test_precheck_ledger_empty_priors():
    ledger = DummyLedger(entries=[])
    service = DuplicatePreCheckService(ledger=ledger)
    prop = make_event_proposal()
    res = service.check_proposal(prop)
    assert res.status == ProposalStatus.PENDING_CONFIRMATION


def test_precheck_calendar_check_internal_exception(monkeypatch):
    writer = HttpWriter("google_calendar", "tok", "primary", calendar_timezone="UTC", transport=httpx.MockTransport(lambda _r: httpx.Response(200, json={"items": []})))
    service = DuplicatePreCheckService(writer=writer)
    monkeypatch.setattr(service, "_check_calendar", lambda _p, _w: (_ for _ in ()).throw(RuntimeError("cal boom")))
    prop = make_event_proposal()
    res = service.check_proposal(prop)
    assert res.status == ProposalStatus.NEEDS_CLARIFICATION
    assert res.duplicate_check_failed and not res.is_creatable


def test_precheck_todoist_check_internal_exception(monkeypatch):
    writer = HttpWriter("todoist", "tok", "inbox", transport=httpx.MockTransport(lambda _r: httpx.Response(200, json={"results": [], "next_cursor": None})))
    service = DuplicatePreCheckService(writer=writer)
    monkeypatch.setattr(service, "_check_todoist", lambda _p, _w: (_ for _ in ()).throw(RuntimeError("todo boom")))
    prop = make_task_proposal()
    res = service.check_proposal(prop)
    assert res.status == ProposalStatus.NEEDS_CLARIFICATION
    assert res.duplicate_check_failed and not res.is_creatable


def test_precheck_todoist_tasks_no_match():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "results": [
                {"id": 1, "content": "Andere Aufgabe"},
                {"id": 2, "content": "Noch eine Aufgabe"},
            ],
            "next_cursor": None,
        })

    writer = HttpWriter("todoist", "tok", "inbox", transport=httpx.MockTransport(handler))
    service = DuplicatePreCheckService(writer=writer)
    prop = make_task_proposal(title="Bericht schreiben")
    res = service.check_proposal(prop)
    assert res.status == ProposalStatus.PENDING_CONFIRMATION
