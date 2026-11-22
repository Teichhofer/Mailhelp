"""Tests for external removal write contract (Google Calendar and Todoist).

Checks D1 (6.6.1):
- Success: event cancelled, task deleted
- Already removed: no write performed
- Modified (E5): rejected with EntryModifiedError and differences
- Forbidden: 401 and 403 errors classified permanently
- Timeout before write: entry still exists
- Timeout after write: uncertain error, reconcile_remove verifies removal
- Idempotent repetition: no second write
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import httpx
import pytest

from mailhelp.domain.proposal import (
    Proposal,
    ProposalCertainty,
    ProposalClassification,
    ProposalKind,
    ProposalResponsibility,
    ProposalStatus,
)
from mailhelp.domain.verification import FieldDifference
from mailhelp.external.contracts import (
    AuthenticationError,
    CalendarAccessError,
    EntryModifiedError,
    TargetAccessError,
)
from mailhelp.external.http_writer import HttpWriter
from mailhelp.llm.adapter import UncertainWriteError
from tests.fakes.calendar_fakes import FakeGoogleCalendar, timed


def _build_event_proposal(external_id: str = "ev-1", target: str = "primary", **kwargs) -> Proposal:
    now = datetime(2026, 12, 1, 10, 0, tzinfo=UTC)
    data = {
        "id": "p1",
        "version": 1,
        "kind": ProposalKind.EVENT,
        "responsibility": ProposalResponsibility.USER,
        "certainty": ProposalCertainty.CERTAIN,
        "classification": ProposalClassification.NEW,
        "title": "Zahnarzttermin",
        "description": "Routinekontrolle",
        "evidence": "In der Mail",
        "source_mail_id": "a" * 24,
        "target": target,
        "start": now,
        "end": now + timedelta(hours=1),
        "status": ProposalStatus.CREATED,
        "external_id": external_id,
        "external_link": f"https://calendar.google.com/{external_id}",
    }
    data.update(kwargs)
    return Proposal.model_validate(data)


def _build_task_proposal(external_id: str = "task-1", target: str = "proj-1", **kwargs) -> Proposal:
    now = datetime(2026, 12, 1, 10, 0, tzinfo=UTC)
    data = {
        "id": "p2",
        "version": 1,
        "kind": ProposalKind.TASK,
        "responsibility": ProposalResponsibility.USER,
        "certainty": ProposalCertainty.CERTAIN,
        "classification": ProposalClassification.NEW,
        "title": "Steuererklärung abgeben",
        "description": "Belege sortieren",
        "evidence": "In der Mail",
        "source_mail_id": "b" * 24,
        "target": target,
        "due": now,
        "status": ProposalStatus.CREATED,
        "external_id": external_id,
        "external_link": f"https://todoist.com/{external_id}",
    }
    data.update(kwargs)
    return Proposal.model_validate(data)


# ---------------------------------------------------------------------------
# Google Calendar Removal Tests
# ---------------------------------------------------------------------------

def test_google_calendar_remove_success():
    start_str = "2026-12-01T10:00:00+00:00"
    end_str = "2026-12-01T11:00:00+00:00"
    ev = timed("ev-1", "Zahnarzttermin", start_str, end_str, description="Routinekontrolle", location=None)
    ev["reminders"] = {"useDefault": False, "overrides": [{"method": "popup", "minutes": 5}]}
    fake_cal = FakeGoogleCalendar(ev)
    writer = HttpWriter(service="google_calendar", token="tok", target="primary",
                        calendar_timezone="UTC", transport=httpx.MockTransport(fake_cal))
    proposal = _build_event_proposal(external_id="ev-1")

    prep = writer.prepare_remove(proposal, "key-rm-1")
    assert prep.requires_write is True
    assert prep.kind == "remove"

    result = writer.remove(proposal, "key-rm-1")
    assert result["operation"] == "removed"
    assert result["id"] == "ev-1"

    # Event in fake calendar is now cancelled
    assert fake_cal.events["ev-1"]["status"] == "cancelled"

    # Kontrollabruf / reconcile verifies it is removed
    assert writer.reconcile_remove(proposal, "key-rm-1") == {"id": "ev-1", "operation": "removed"}
    # Reconcile with missing external_id returns None
    prop_no_id = proposal.model_copy(update={"external_id": None})
    assert writer.reconcile_remove(prop_no_id, "key-rm-1") is None


def test_google_calendar_remove_already_cancelled_or_missing():
    # Missing event (404)
    fake_cal = FakeGoogleCalendar()
    writer = HttpWriter(service="google_calendar", token="tok", target="primary",
                        calendar_timezone="UTC", transport=httpx.MockTransport(fake_cal))
    proposal = _build_event_proposal(external_id="ev-missing")

    prep = writer.prepare_remove(proposal, "key-rm-2")
    assert prep.requires_write is False
    assert prep.kind == "remove"
    result = prep.operation()
    assert result["operation"] == "already_removed"
    assert result["id"] == "ev-missing"
    assert len(fake_cal.patches) == 0

    # Already cancelled event
    ev_cancelled = timed("ev-canc", "Termin", "2026-12-01T10:00:00+00:00", "2026-12-01T11:00:00+00:00",
                         status="cancelled")
    fake_cal2 = FakeGoogleCalendar(ev_cancelled)
    writer2 = HttpWriter(service="google_calendar", token="tok", target="primary",
                         calendar_timezone="UTC", transport=httpx.MockTransport(fake_cal2))
    proposal2 = _build_event_proposal(external_id="ev-canc")

    prep2 = writer2.prepare_remove(proposal2, "key-rm-3")
    assert prep2.requires_write is False
    result2 = prep2.operation()
    assert result2["operation"] == "already_removed"
    assert len(fake_cal2.patches) == 0


def test_google_calendar_remove_rejected_if_modified_e5():
    # Entry has modified summary
    start_str = "2026-12-01T10:00:00+00:00"
    end_str = "2026-12-01T11:00:00+00:00"
    ev = timed("ev-1", "Zahnarzttermin Geändert", start_str, end_str, description="Routinekontrolle")
    fake_cal = FakeGoogleCalendar(ev)
    writer = HttpWriter(service="google_calendar", token="tok", target="primary",
                        calendar_timezone="UTC", transport=httpx.MockTransport(fake_cal))
    proposal = _build_event_proposal(external_id="ev-1")

    with pytest.raises(EntryModifiedError) as exc_info:
        writer.prepare_remove(proposal, "key-rm-e5")

    err = exc_info.value
    assert "geändert" in str(err)
    assert "title" in err.differences
    assert err.link == "https://calendar.example.test/ev-1"
    assert len(fake_cal.patches) == 0


def test_google_calendar_remove_auth_and_access_errors():
    start_str = "2026-12-01T10:00:00+00:00"
    end_str = "2026-12-01T11:00:00+00:00"
    ev = timed("ev-1", "Zahnarzttermin", start_str, end_str)

    # 401 Unauthorized
    fake_cal = FakeGoogleCalendar(ev)
    fake_cal.fail[("GET", "get")] = httpx.Response(401, json={"error": {"message": "Invalid token"}})
    writer = HttpWriter(service="google_calendar", token="tok", target="primary",
                        calendar_timezone="UTC", transport=httpx.MockTransport(fake_cal))
    proposal = _build_event_proposal(external_id="ev-1")

    with pytest.raises(AuthenticationError):
        writer.prepare_remove(proposal, "key-rm-auth")

    # 403 Forbidden
    fake_cal2 = FakeGoogleCalendar(ev)
    fake_cal2.fail[("GET", "get")] = httpx.Response(403, json={"error": {"errors": [{"reason": "forbidden"}]}})
    writer2 = HttpWriter(service="google_calendar", token="tok", target="primary",
                         calendar_timezone="UTC", transport=httpx.MockTransport(fake_cal2))

    with pytest.raises(CalendarAccessError) as exc_info2:
        writer2.prepare_remove(proposal, "key-rm-forb")
    assert exc_info2.value.reason == "forbidden"


def test_google_calendar_remove_timeout_after_write():
    start_str = "2026-12-01T10:00:00+00:00"
    end_str = "2026-12-01T11:00:00+00:00"
    ev = timed("ev-1", "Zahnarzttermin", start_str, end_str, description="Routinekontrolle")
    ev["reminders"] = {"useDefault": False, "overrides": [{"method": "popup", "minutes": 5}]}
    fake_cal = FakeGoogleCalendar(ev)
    fake_cal.lose_patch_answer = True
    writer = HttpWriter(service="google_calendar", token="tok", target="primary",
                        calendar_timezone="UTC", transport=httpx.MockTransport(fake_cal))
    proposal = _build_event_proposal(external_id="ev-1")

    prep = writer.prepare_remove(proposal, "key-rm-timeout")
    with pytest.raises(UncertainWriteError):
        prep.operation()

    # Reconcile detects that the cancellation actually succeeded!
    rec = writer.reconcile_remove(proposal, "key-rm-timeout")
    assert rec == {"id": "ev-1", "operation": "removed"}


# ---------------------------------------------------------------------------
# Todoist Removal Tests
# ---------------------------------------------------------------------------

def test_todoist_remove_success():
    requests: list[httpx.Request] = []
    task_storage = {
        "task-1": {
            "id": "task-1",
            "content": "Steuererklärung abgeben",
            "description": f"Belege sortieren\n\n[mailhelp:{'b'*24}:p2:v1]",
            "project_id": "proj-1",
            "due": {"date": "2026-12-01T10:00:00+00:00"},
            "checked": False,
            "url": "https://todoist.example.test/task-1",
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if path == "/api/v1/user":
            return httpx.Response(200, json={"id": "u1"})
        if path == "/api/v1/projects/proj-1":
            return httpx.Response(200, json={"id": "proj-1"})
        if path == "/api/v1/tasks/task-1":
            if request.method == "GET":
                if "task-1" in task_storage:
                    return httpx.Response(200, json=task_storage["task-1"])
                return httpx.Response(404)
            if request.method == "DELETE":
                if "task-1" in task_storage:
                    del task_storage["task-1"]
                    return httpx.Response(204)
                return httpx.Response(404)
        if path.startswith("/api/v1/tasks/completed"):
            return httpx.Response(200, json={"items": [], "next_cursor": None})
        return httpx.Response(404)

    writer = HttpWriter(service="todoist", token="tok", target="proj-1",
                        transport=httpx.MockTransport(handler))
    proposal = _build_task_proposal(external_id="task-1")

    prep = writer.prepare_remove(proposal, "key-td-1")
    assert prep.requires_write is True
    assert prep.kind == "remove"

    result = writer.remove(proposal, "key-td-1")
    assert result == {"id": "task-1", "operation": "removed"}
    assert "task-1" not in task_storage

    # Subsequent reconcile verifies it's gone
    rec = writer.reconcile_remove(proposal, "key-td-1")
    assert rec == {"id": "task-1", "operation": "removed"}
    # Reconcile with missing external_id returns None
    prop_no_id = proposal.model_copy(update={"external_id": None})
    assert writer.reconcile_remove(prop_no_id, "key-td-1") is None

    # Test DELETE 404 response in _remove_todoist
    task_storage["task-404"] = {
        "id": "task-404",
        "content": "Steuererklärung abgeben",
        "description": f"Belege sortieren\n\n[mailhelp:{'b'*24}:p2:v1]",
        "project_id": "proj-1",
        "due": {"date": "2026-12-01T10:00:00+00:00"},
        "checked": False,
    }
    prop_404 = _build_task_proposal(external_id="task-404")
    prep_404 = writer.prepare_remove(prop_404, "key-404")
    # Delete from storage so DELETE /tasks/task-404 returns 404
    del task_storage["task-404"]
    res_404 = prep_404.operation()
    assert res_404 == {"id": "task-404", "operation": "already_removed"}


def test_todoist_remove_already_missing():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/projects/proj-1":
            return httpx.Response(200, json={"id": "proj-1"})
        if request.url.path.startswith("/api/v1/tasks/completed"):
            return httpx.Response(200, json={"items": [], "next_cursor": None})
        return httpx.Response(404)

    writer = HttpWriter(service="todoist", token="tok", target="proj-1",
                        transport=httpx.MockTransport(handler))
    proposal = _build_task_proposal(external_id="task-missing")

    prep = writer.prepare_remove(proposal, "key-td-2")
    assert prep.requires_write is False
    result = prep.operation()
    assert result == {"id": "task-missing", "operation": "already_removed"}


def test_todoist_remove_rejected_if_modified_e5():
    # 1. Content modified
    task_storage = {
        "task-1": {
            "id": "task-1",
            "content": "Steuererklärung GEÄNDERT",
            "description": f"Belege sortieren\n\n[mailhelp:{'b'*24}:p2:v1]",
            "project_id": "proj-1",
            "due": {"date": "2026-12-01T10:00:00+00:00"},
            "checked": False,
            "url": "https://todoist.example.test/task-1",
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/tasks/task-1" and request.method == "GET":
            return httpx.Response(200, json=task_storage["task-1"])
        return httpx.Response(200, json={})

    writer = HttpWriter(service="todoist", token="tok", target="proj-1",
                        transport=httpx.MockTransport(handler))
    proposal = _build_task_proposal(external_id="task-1")

    with pytest.raises(EntryModifiedError) as exc_info:
        writer.prepare_remove(proposal, "key-td-e5")
    assert "title" in exc_info.value.differences
    assert exc_info.value.link == "https://todoist.example.test/task-1"

    # 2. Already completed by user
    task_storage["task-1"]["content"] = "Steuererklärung abgeben"
    task_storage["task-1"]["checked"] = True

    with pytest.raises(EntryModifiedError) as exc_info2:
        writer.prepare_remove(proposal, "key-td-e5-completed")
    assert "completed" in exc_info2.value.differences


def test_todoist_remove_errors_and_edge_cases():
    proposal = _build_task_proposal(external_id="task-1")

    # Missing external ID
    prop_no_id = proposal.model_copy(update={"external_id": None})
    writer = HttpWriter(service="todoist", token="tok", target="proj-1",
                        transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    with pytest.raises(ValueError, match="keine externe ID"):
        writer.prepare_remove(prop_no_id, "key-no-id")

    # Target mismatch
    prop_wrong_target = proposal.model_copy(update={"target": "other-proj"})
    with pytest.raises(ValueError, match="weicht vom bestätigten"):
        writer.prepare_remove(prop_wrong_target, "key-mismatch")

    # 401 Unauthorized
    writer_401 = HttpWriter(service="todoist", token="tok", target="proj-1",
                            transport=httpx.MockTransport(lambda r: httpx.Response(401)))
    with pytest.raises(AuthenticationError):
        writer_401.prepare_remove(proposal, "key-401")

    # 403 Forbidden
    writer_403 = HttpWriter(service="todoist", token="tok", target="proj-1",
                            transport=httpx.MockTransport(lambda r: httpx.Response(403)))
    with pytest.raises(TargetAccessError) as exc_403:
        writer_403.prepare_remove(proposal, "key-403")
    assert exc_403.value.reason == "forbidden"


def test_todoist_remove_timeout_after_write():
    # DELETE succeeds on server, but client times out receiving response
    deleted = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal deleted
        if request.url.path == "/api/v1/tasks/task-1":
            if request.method == "GET":
                if deleted:
                    return httpx.Response(404)
                return httpx.Response(200, json={
                    "id": "task-1",
                    "content": "Steuererklärung abgeben",
                    "description": f"Belege sortieren\n\n[mailhelp:{'b'*24}:p2:v1]",
                    "project_id": "proj-1",
                    "due": {"date": "2026-12-01T10:00:00+00:00"},
                    "checked": False,
                })
            if request.method == "DELETE":
                deleted = True
                raise httpx.ReadTimeout("Timeout waiting for 204", request=request)
        if request.url.path == "/api/v1/projects/proj-1":
            return httpx.Response(200, json={"id": "proj-1"})
        if request.url.path.startswith("/api/v1/tasks/completed"):
            return httpx.Response(200, json={"items": [], "next_cursor": None})
        return httpx.Response(404)

    writer = HttpWriter(service="todoist", token="tok", target="proj-1",
                        transport=httpx.MockTransport(handler))
    proposal = _build_task_proposal(external_id="task-1")

    prep = writer.prepare_remove(proposal, "key-td-timeout")
    with pytest.raises(UncertainWriteError):
        prep.operation()

    # Reconcile checks: task is 404, so removal succeeded!
    rec = writer.reconcile_remove(proposal, "key-td-timeout")
    assert rec == {"id": "task-1", "operation": "removed"}


# ---------------------------------------------------------------------------
# VerifyingWriter & ProviderWriter Removal Tests
# ---------------------------------------------------------------------------

def test_verifying_writer_remove_lifecycle():
    from tests.fakes.verifying_writer import SimulatedProvider, VerifyingWriter

    provider = SimulatedProvider()
    writer = VerifyingWriter(provider, target="proj-1")
    proposal = _build_task_proposal(external_id="t1")

    # Initial write
    prep_write = writer.prepare(proposal, f"mailhelp:{'b'*24}:p2:v1")
    prep_write.operation()
    assert "t1" in provider.entries

    # 1. Modify entry -> E5 rejected
    provider.entries["t1"]["title"] = "Geänderter Titel"
    with pytest.raises(EntryModifiedError) as exc_info:
        writer.prepare_remove(proposal, "key-rm-vw")
    assert "title" in exc_info.value.differences

    # Restore title
    provider.entries["t1"]["title"] = proposal.title

    # 2. Already completed by user -> E5 rejected
    writer.script = [{"completed": True}]
    with pytest.raises(EntryModifiedError) as exc_comp:
        writer.prepare_remove(proposal, "key-rm-comp")
    assert "completed" in exc_comp.value.differences

    # 3. Successful removal
    writer.script = []
    prep_rm = writer.prepare_remove(proposal, "key-rm-ok")
    assert prep_rm.requires_write is True
    res = prep_rm.operation()
    assert res == {"id": "t1", "operation": "removed"}
    assert "t1" not in provider.entries

    # 4. Already removed call
    prep_already = writer.prepare_remove(proposal, "key-rm-again")
    assert prep_already.requires_write is False
    res_already = prep_already.operation()
    assert res_already == {"id": "t1", "operation": "already_removed"}

    # 5. Reconcile remove
    rec = writer.reconcile_remove(proposal, "key-rm-rec")
    assert rec == {"id": "t1", "operation": "removed"}

    # 6. Uncertain write on remove
    prop2 = _build_task_proposal(external_id="t2")
    writer.unclear_write = False
    writer.prepare(prop2, f"mailhelp:{'b'*24}:p2:v1").operation()
    assert "t2" in provider.entries
    writer.unclear_write = True
    prep_unc = writer.prepare_remove(prop2, "key-rm-unc")
    with pytest.raises(UncertainWriteError):
        prep_unc.operation()
    # Entry was deleted from provider before crash: reconcile verifies
    assert writer.reconcile_remove(prop2, "key-rm-unc") == {"id": "t2", "operation": "removed"}


def test_provider_writer_remove_delegation():
    from mailhelp.external.calendar import CalendarOperations
    from mailhelp.external.contracts import TargetWriter
    from mailhelp.external.provider import ProviderWriter

    # Default TargetWriter raises NotImplementedError
    class DummyWriter(TargetWriter):
        service, role, target, label = "dummy", "calendar", "cal-1", "Dummy"
        def check_access(self): pass
        def reconcile(self, key): return None
        def prepare(self, proposal, key): raise NotImplementedError
        def close(self): pass

    dummy = DummyWriter()
    prop = _build_event_proposal(external_id="ev-1", target="cal-1")
    with pytest.raises(NotImplementedError):
        dummy.prepare_remove(prop, "key-1")
    with pytest.raises(NotImplementedError):
        dummy.remove(prop, "key-1")
    assert dummy.reconcile_remove(prop, "key-1") is None

    # ProviderWriter without CalendarOperations
    class NonCalProvider(ProviderWriter):
        service, role, target, label = "tasks", "tasks", "t-1", "NonCal"
        def check_access(self): pass
        def reconcile(self, key): return None
        def _prepare(self, proposal, key): raise NotImplementedError
        def close(self): pass

    non_cal = NonCalProvider()
    non_cal.target = "t-1"
    prop_task = _build_task_proposal(external_id="task-1", target="t-1")

    # Missing external ID
    prop_no_id = prop_task.model_copy(update={"external_id": None})
    with pytest.raises(ValueError, match="keine externe ID"):
        non_cal.prepare_remove(prop_no_id, "key-1")

    # Target mismatch
    prop_wrong_target = prop_task.model_copy(update={"target": "t-2"})
    with pytest.raises(ValueError, match="weicht vom bestätigten"):
        non_cal.prepare_remove(prop_wrong_target, "key-1")

    # NotImplemented for tasks provider
    with pytest.raises(NotImplementedError, match="Entfernen wird nicht unterstützt"):
        non_cal.prepare_remove(prop_task, "key-1")
    assert non_cal.reconcile_remove(prop_task, "key-1") is None

    # ProviderWriter WITH CalendarOperations
    class CalProvider(ProviderWriter, CalendarOperations):
        service, role, target, label = "calendar", "calendar", "cal-1", "Cal"
        def check_access(self): pass
        def reconcile(self, key): return None
        def _prepare(self, proposal, key): raise NotImplementedError
        def close(self): pass

    cal_prov = CalProvider()
    cal_prov.target = "cal-1"
    cal_prov.existing_event = Mock(return_value=None)
    prep = cal_prov.prepare_remove(prop, "key-cal")
    assert prep.requires_write is False
    assert cal_prov.reconcile_remove(prop, "key-cal") == {"id": "ev-1", "operation": "removed"}
    cal_prov.existing_event.return_value = Mock()
    assert cal_prov.reconcile_remove(prop, "key-cal") is None
    # None external_id on reconcile_remove returns None
    assert cal_prov.reconcile_remove(prop_no_id, "key-cal") is None
    assert non_cal.reconcile_remove(prop_no_id, "key-cal") is None


