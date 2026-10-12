"""Unit-Tests für die Read-Only Query-Adapter und Caching in Mailhelp 1.3."""
from datetime import date, datetime, timezone
import httpx
import pytest

from mailhelp.integrations import HttpWriter, CalendarOverlapEvent, TodoistTaskResponse
from mailhelp.models import Proposal, ProposalKind, ProposalStatus, ProposalResponsibility, ProposalCertainty, ProposalClassification


def test_fetch_events_in_window_success_and_caching():
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        assert request.url.path.endswith("/calendars/primary/events")
        params = request.url.params
        if "pageToken" not in params:
            # Page 1 with nextPageToken
            return httpx.Response(200, json={
                "items": [
                    {
                        "id": "ev1",
                        "summary": "Meeting 1",
                        "start": {"dateTime": "2026-10-15T10:00:00Z"},
                        "end": {"dateTime": "2026-10-15T11:00:00Z"},
                    }
                ],
                "nextPageToken": "token2",
            })
        else:
            # Page 2
            return httpx.Response(200, json={
                "items": [
                    {
                        "id": "ev2",
                        "summary": "Meeting 2",
                        "start": {"dateTime": "2026-10-15T14:00:00Z"},
                        "end": {"dateTime": "2026-10-15T15:00:00Z"},
                    }
                ],
            })

    transport = httpx.MockTransport(handler)
    writer = HttpWriter(
        service="google_calendar",
        token="test-token",
        target="primary",
        calendar_timezone="UTC",
        transport=transport,
    )

    start = datetime(2026, 10, 15, 9, 0, tzinfo=timezone.utc)
    end = datetime(2026, 10, 15, 18, 0, tzinfo=timezone.utc)

    # First fetch: queries 2 pages
    events = writer.fetch_events_in_window(start, end)
    assert len(events) == 2
    assert events[0].id == "ev1"
    assert events[1].id == "ev2"
    assert request_count == 2

    # Second fetch with same window: served from cache!
    events_cached = writer.fetch_events_in_window(start, end)
    assert len(events_cached) == 2
    assert request_count == 2  # No additional network requests!

    # Date-only window also works
    events_date = writer.fetch_events_in_window(date(2026, 10, 15), date(2026, 10, 16))
    assert request_count == 4  # 2 more requests for different window key

    # Expired cache branch (time.time() - ts >= ttl)
    writer._cache_ttl = 0.0
    events_expired = writer.fetch_events_in_window(start, end)
    assert len(events_expired) == 2
    assert request_count == 6


def test_fetch_events_wrong_service_and_graceful_fallback():
    writer_todoist = HttpWriter(
        service="todoist",
        token="test-token",
        target="inbox",
    )
    # Non-calendar service returns empty list immediately
    assert writer_todoist.fetch_events_in_window(date(2026, 10, 1), date(2026, 10, 2)) == []

    # Network error or 500 error falls back to empty list gracefully without throwing
    error_transport = httpx.MockTransport(lambda _r: httpx.Response(500, json={"error": "server error"}))
    writer_error = HttpWriter(
        service="google_calendar",
        token="test-token",
        target="primary",
        calendar_timezone="UTC",
        transport=error_transport,
    )
    res = writer_error.fetch_events_in_window(date(2026, 10, 1), date(2026, 10, 2))
    assert res == []

    # Non-list items response also falls back
    bad_json_transport = httpx.MockTransport(lambda _r: httpx.Response(200, json={"items": "not a list"}))
    writer_bad = HttpWriter(
        service="google_calendar",
        token="test-token",
        target="primary",
        calendar_timezone="UTC",
        transport=bad_json_transport,
    )
    assert writer_bad.fetch_events_in_window(date(2026, 10, 1), date(2026, 10, 2)) == []


def test_fetch_active_tasks_success_and_caching():
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        assert request.url.path.endswith("/tasks")
        assert request.url.params.get("project_id") == "proj-1"
        cursor = request.url.params.get("cursor")
        if cursor is None:
            return httpx.Response(200, json={
                "results": [
                    {"id": "t1", "content": "Aufgabe 1", "description": "Desc 1"},
                ],
                "next_cursor": "c2",
            })
        else:
            return httpx.Response(200, json={
                "results": [
                    {"id": "t2", "content": "Aufgabe 2", "description": "Desc 2"},
                ],
                "next_cursor": None,
            })

    transport = httpx.MockTransport(handler)
    writer = HttpWriter(
        service="todoist",
        token="test-token",
        target="proj-1",
        transport=transport,
    )

    # First fetch: 2 pages
    tasks = writer.fetch_active_tasks()
    assert len(tasks) == 2
    assert tasks[0].id == "t1"
    assert tasks[1].id == "t2"
    assert request_count == 2

    # Second fetch: from cache
    tasks_cached = writer.fetch_active_tasks()
    assert len(tasks_cached) == 2
    assert request_count == 2


def test_fetch_active_tasks_wrong_service_and_fallback():
    writer_cal = HttpWriter(
        service="google_calendar",
        token="test-token",
        target="primary",
        calendar_timezone="UTC",
    )
    # Wrong service returns empty
    assert writer_cal.fetch_active_tasks() == []

    # Network / 500 error falls back
    error_transport = httpx.MockTransport(lambda _r: httpx.Response(502, text="bad gateway"))
    writer_error = HttpWriter(
        service="todoist",
        token="test-token",
        target="proj-1",
        transport=error_transport,
    )
    assert writer_error.fetch_active_tasks() == []
