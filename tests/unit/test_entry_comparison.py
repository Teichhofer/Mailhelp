"""5.2: the deterministic comparison of expected and freshly read facts, and its display."""
from datetime import UTC, date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from mailhelp.domain.verification import (
    FieldDifference,
    VerificationState,
    WriteVerification,
    fingerprint,
    operation_id,
)
from mailhelp.external.verification import compare, event_facts, task_facts
from mailhelp.review.verification_texts import STATE_TEXTS, differences_text, reason_text, shown

BERLIN = ZoneInfo("Europe/Berlin")
TEN = datetime(2026, 11, 11, 10, tzinfo=BERLIN)
NOW = datetime(2026, 11, 10, 9, tzinfo=UTC)


def record(**fields):
    expected = {"title": "A"}
    data = dict(id=operation_id("a" * 24, "p", 1, "create"), mail_id="a" * 24, proposal_id="p", proposal_version=1,
                idempotency_key="k", operation="create",
                target={"profile": 1, "provider": "todoist", "account": "konto", "container": "Inbox"},
                receipt={"external_id": "1", "written_at": NOW, "result": "created"}, expected=expected,
                expected_fingerprint=fingerprint(expected), deadline_at=NOW, created_at=NOW, updated_at=NOW)
    data.update(fields)
    return WriteVerification.model_validate(data)


def test_the_same_instant_in_another_offset_is_equal():
    expected = task_facts("A", "", TEN, "Inbox")
    assert compare(expected, {**expected, "due": "2026-11-11T09:00:00Z"}) == {}
    assert compare(expected, {**expected, "due": "2026-11-11T09:00:00+00:00"}) == {}
    assert compare(expected, {**expected, "due": "2026-11-11T10:00:00"}) == {}  # floating wall time
    assert set(compare(expected, {**expected, "due": "2026-11-11T10:00:00Z"})) == {"due"}


@pytest.mark.parametrize("actual", ["2026-11-11", None, "kein Datum", "2026-11-11T11:00:00"])
def test_a_date_never_equals_a_time_and_a_missing_due_is_a_difference(actual):
    expected = task_facts("A", "", TEN, "Inbox")
    assert set(compare(expected, {**expected, "due": actual})) == {"due"}


def test_dates_compare_as_dates_and_missing_values_as_missing():
    expected = task_facts("A", "", date(2026, 11, 11), "Inbox")
    assert compare(expected, {**expected}) == {}
    assert set(compare(expected, {**expected, "due": "2026-11-12"})) == {"due"}
    undated = task_facts("A", "", None, "Inbox")
    assert compare(undated, {**undated}) == {}


def test_text_normalisation_is_limited_to_line_endings_and_surrounding_space():
    expected = event_facts("Elternabend", "Zeile 1\nZeile 2", date(2026, 11, 11), date(2026, 11, 12), True,
                           None, "kalender")
    actual = {**expected, "title": " Elternabend ", "description": "Zeile 1\r\nZeile 2\r", "location": ""}
    assert compare(expected, actual) == {}
    changed = {**expected, "title": "Elternabende", "all_day": False, "container": "anderer"}
    assert set(compare(expected, changed)) == {"title", "all_day", "container"}
    assert compare({"title": "x" * 600}, {"title": "y"})["title"].expected == "x" * 500


def test_values_are_shown_in_german_form():
    assert shown("2026-11-11", BERLIN) == "11.11.2026"
    assert shown("2026-11-11T09:00:00Z", BERLIN) == "11.11.2026 10:00 Uhr"
    assert shown("2026-11-11T09:00:00", BERLIN) == "11.11.2026 09:00 Uhr"
    assert (shown(None, BERLIN), shown("", BERLIN), shown("True", BERLIN), shown("Saal", BERLIN)) == (
        "–", "–", "ja", "Saal")
    assert shown(datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=1))).isoformat(), UTC) == \
        "31.12.2025 23:00 Uhr"


def test_differences_and_reasons_have_fixed_texts():
    item = record(state="mismatch", next_check_at=None,
                  differences={"due": FieldDifference(expected="2026-11-11", actual=None),
                               "custom": FieldDifference(expected="a", actual="b")})
    assert differences_text(item, BERLIN) == "custom: erwartet a, gefunden b; Fälligkeit: erwartet 11.11.2026, gefunden –"
    assert reason_text(record(state="unavailable", next_check_at=None, last_error="rate_limited")) == \
        "der Anbieter hat zu viele Anfragen gemeldet"
    assert reason_text(record(state="unavailable", next_check_at=None)) == "die Nachprüfung war nicht möglich"
    assert set(STATE_TEXTS) == set(VerificationState)
