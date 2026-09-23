from datetime import date, datetime, timedelta

import pytest

from mailhelp.action_normalization import (
    MailDateContext,
    NormalizationReason,
    TemporalValue,
    normalize_event,
    normalize_task_due,
)
from mailhelp.models import ExtractedEvent, ExtractedTask


def context(**changes):
    values = {
        "date_context_status": "valid",
        "date_header_parsed": "2026-09-18T12:00:00+02:00",
        "imap_received_at": "2026-09-18T10:01:00+00:00",
        "user_timezone": "Europe/Berlin",
    }
    values.update(changes)
    return MailDateContext(**values)


def event(**changes):
    values = {
        "title": "Sitzung", "description": None, "evidence": "synthetischer Beleg",
        "date_text": "22.09.2026", "time_text": None, "end_time_text": None,
        "time_requirement": "all_day",
        "location": None, "video_link": None, "responsibility": "user",
        "certainty": "certain", "classification": "new",
    }
    values.update(changes)
    return ExtractedEvent(**values)


def task(**changes):
    values = {"title": "Aufgabe", "description": "", "evidence": "Beleg",
              "responsibility": "user", "certainty": "certain", "classification": "new",
              "due_text": "2026-09-22"}
    values.update(changes)
    return ExtractedTask(**values)


def test_gemeinderat_is_one_exclusive_all_day_interval_and_responsibility_stays_separate():
    result = normalize_event(event(responsibility="unclear"), context())
    assert result.value == TemporalValue(date(2026, 9, 22), date(2026, 9, 23), True)
    assert result.reason is None and result.raw_value == "22.09.2026" and result.question is None
    assert result.resolved is True
    assert result.confirmation_ready is False
    assert normalize_event(event(), context()).confirmation_ready is True


@pytest.mark.parametrize(("raw", "expected_start", "expected_end"), [
    ("2024-02-29", date(2024, 2, 29), date(2024, 3, 1)),
    ("31.12.2026", date(2026, 12, 31), date(2027, 1, 1)),
])
def test_supported_dates_cover_leap_year_and_year_boundary(raw, expected_start, expected_end):
    result = normalize_event(event(date_text=raw), context())
    assert result.value == TemporalValue(expected_start, expected_end, True)


@pytest.mark.parametrize("raw", [
    "23.09.2026",
    "Mi, 23.09.2026",
    "Mittwoch, 23.09.2026",
    "Mi 23.09.2026",
    "Mittwoch 23.09.2026",
])
def test_numeric_german_date_accepts_matching_optional_weekday(raw):
    result = normalize_event(event(date_text=raw), context())
    assert result.value == TemporalValue(date(2026, 9, 23), date(2026, 9, 24), True)
    assert result.temporal_fact.model_dump(mode="json") == {
        "raw_text": raw,
        "normalized_date": "2026-09-23",
        "year_source": "explicit_mail",
        "status": "resolved",
    }


@pytest.mark.parametrize("raw", ["Di, 23.09.2026", "Mittwoch, 31.09.2026"])
def test_numeric_german_date_rejects_conflicting_weekday_and_invalid_calendar_date(raw):
    result = normalize_event(event(date_text=raw), context())
    assert result.value is None
    assert result.reason == NormalizationReason.INVALID_DATE
    assert result.raw_value == raw


@pytest.mark.parametrize(("raw", "reason"), [
    (None, NormalizationReason.MISSING_DATE),
    ("nächsten Freitag", NormalizationReason.UNSUPPORTED_DATE),
    ("2023-02-29", NormalizationReason.INVALID_DATE),
    ("31.04.2026", NormalizationReason.INVALID_DATE),
])
def test_missing_relative_and_invalid_dates_have_stable_reasons(raw, reason):
    result = normalize_event(event(date_text=raw), context())
    assert result.value is None and result.reason == reason and result.question
    assert result.raw_value == raw and not result.resolved and not result.confirmation_ready


@pytest.mark.parametrize(("changes", "reason"), [
    ({"time_text": "10:00"}, NormalizationReason.MISSING_END_TIME),
    ({"end_time_text": "11:00"}, NormalizationReason.MISSING_TIME),
    ({"time_text": "10 Uhr", "end_time_text": "11:00"}, NormalizationReason.UNSUPPORTED_TIME),
    ({"time_text": "25:00", "end_time_text": "11:00"}, NormalizationReason.INVALID_TIME),
    ({"time_text": "10:00", "end_time_text": "11 Uhr"}, NormalizationReason.UNSUPPORTED_TIME),
    ({"time_text": "10:00", "end_time_text": "25:00"}, NormalizationReason.INVALID_TIME),
    ({"time_text": "11:00", "end_time_text": "10:00"}, NormalizationReason.END_NOT_AFTER_START),
])
def test_incomplete_invalid_and_reversed_times_are_not_invented(changes, reason):
    result = normalize_event(event(time_requirement="timed", **changes), context())
    assert result.reason == reason and result.value is None and result.question


def test_unambiguous_clock_times_use_configured_zone_and_seconds_are_supported():
    result = normalize_event(event(date_text="2026-07-01", time_text="10:15:30",
                                   end_time_text="11:16:31", time_requirement="timed"), context())
    assert isinstance(result.value, TemporalValue)
    assert result.value.start == datetime.fromisoformat("2026-07-01T10:15:30+02:00")
    assert result.value.end == datetime.fromisoformat("2026-07-01T11:16:31+02:00")
    assert result.value.all_day is False


def test_all_day_rejects_clock_evidence_and_timed_context_is_validated():
    conflict = normalize_event(event(time_text="10:00"), context())
    assert conflict.reason == NormalizationReason.INVALID_TIME
    invalid_context = normalize_event(event(time_requirement="timed", time_text="10:00"),
                                      context(date_context_status="invalid"))
    assert invalid_context.reason == NormalizationReason.INVALID_CONTEXT


@pytest.mark.parametrize(("day", "clock", "reason"), [
    ("2026-03-29", "02:30", NormalizationReason.NONEXISTENT_LOCAL_TIME),
    ("2026-10-25", "02:30", NormalizationReason.AMBIGUOUS_LOCAL_TIME),
])
def test_dst_transition_times_require_clarification(day, clock, reason):
    result = normalize_event(event(date_text=day, time_text=clock, end_time_text="04:00",
                                   time_requirement="timed"), context())
    assert result.reason == reason


def test_dst_problem_in_end_time_is_also_detected():
    result = normalize_event(event(date_text="2026-10-25", time_text="01:30", end_time_text="02:30",
                                   time_requirement="timed"), context())
    assert result.reason == NormalizationReason.AMBIGUOUS_LOCAL_TIME


@pytest.mark.parametrize(("changes", "reason"), [
    ({"date_context_status": "missing"}, NormalizationReason.INVALID_CONTEXT),
    ({"date_context_status": "conflicting"}, NormalizationReason.CONFLICTING_CONTEXT),
    ({"date_header_parsed": None}, NormalizationReason.INVALID_CONTEXT),
    ({"date_header_parsed": "not-iso"}, NormalizationReason.INVALID_CONTEXT),
    ({"date_header_parsed": "2026-09-18T12:00:00"}, NormalizationReason.INVALID_CONTEXT),
    ({"imap_received_at": None}, NormalizationReason.INVALID_CONTEXT),
    ({"imap_received_at": "invalid"}, NormalizationReason.INVALID_CONTEXT),
    ({"imap_received_at": "2026-09-18T10:00:00"}, NormalizationReason.INVALID_CONTEXT),
    ({"imap_received_at": "2026-10-18T10:00:00+00:00"}, NormalizationReason.CONFLICTING_CONTEXT),
    ({"user_timezone": None}, NormalizationReason.MISSING_TIMEZONE),
    ({"user_timezone": "Not/AZone"}, NormalizationReason.UNKNOWN_TIMEZONE),
    ({"user_timezone": "\0"}, NormalizationReason.UNKNOWN_TIMEZONE),
])
def test_bad_or_contradictory_context_has_a_specific_result(changes, reason):
    result = normalize_event(event(), context(**changes))
    assert result.reason == reason and result.value is None


def test_task_due_supports_date_only_and_retains_unresolved_raw_input():
    resolved = normalize_task_due(task(), context())
    assert resolved.value == date(2026, 9, 22) and resolved.confirmation_ready
    missing = normalize_task_due(task(due_text=None), context())
    relative = normalize_task_due(task(due_text="morgen"), context())
    assert missing.reason == NormalizationReason.MISSING_DATE
    assert relative.reason == NormalizationReason.UNSUPPORTED_DATE and relative.raw_value == "morgen"


def test_task_due_checks_mail_context_and_does_not_override_responsibility():
    invalid = normalize_task_due(task(), context(date_context_status="invalid"))
    unclear = normalize_task_due(task(responsibility="unclear"), context())
    assert invalid.reason == NormalizationReason.INVALID_CONTEXT
    assert unclear.value == date(2026, 9, 22) and not unclear.confirmation_ready


def test_yearless_german_date_uses_only_validated_context_and_records_source():
    result = normalize_event(event(date_text="21. Oktober"), context())
    assert result.value == TemporalValue(date(2026, 10, 21), date(2026, 10, 22), True)
    assert result.temporal_fact.model_dump(mode="json") == {
        "raw_text": "21. Oktober", "normalized_date": "2026-10-21",
        "year_source": "mail_context", "status": "resolved",
    }


def test_yearless_date_rolls_forward_but_conflict_and_unknown_context_never_guess():
    rollover = normalize_event(event(date_text="2. Januar"), context(
        date_header_parsed="2026-12-30T12:00:00+01:00",
        imap_received_at="2026-12-30T11:01:00+00:00"))
    assert rollover.value.start == date(2027, 1, 2)
    conflicting = normalize_event(event(date_text="21. Oktober",
        evidence="21. Oktober 2026; an anderer Stelle 2027"), context())
    assert conflicting.reason == NormalizationReason.CONFLICTING_CONTEXT
    assert conflicting.temporal_fact.status == "conflicting"
    unknown = normalize_event(event(date_text="21. Oktober"), context(date_context_status="missing"))
    assert unknown.value is None and unknown.temporal_fact.status == "unresolved"


def test_explicit_four_digit_year_wins_over_context_year():
    result = normalize_event(event(date_text="2028-10-21",
                                   evidence="Termin am 21. Oktober 2028"), context())
    assert result.value.start == date(2028, 10, 21)
    assert result.temporal_fact.year_source == "explicit_mail"


def test_invalid_yearless_day_and_conflicting_explicit_years_are_rejected():
    invalid = normalize_event(event(date_text="31. Februar"), context())
    assert invalid.reason == NormalizationReason.INVALID_DATE
    conflict = normalize_event(event(date_text="21.10.2026",
                                     evidence="2026 widerspricht 2027"), context())
    assert conflict.reason == NormalizationReason.CONFLICTING_CONTEXT

@pytest.mark.parametrize("raw", ["Freitag, den 9. Oktober 2026", "9. Oktober 2026"])
def test_german_named_date_with_year_and_optional_weekday_is_supported(raw):
    result = normalize_event(event(date_text=raw, time_text="19:00 Uhr",
                                   end_time_text=None, time_requirement="timed"), context())
    assert result.reason == NormalizationReason.MISSING_END_TIME
    assert result.known_date == date(2026, 10, 9)
    assert result.known_start == datetime.fromisoformat("2026-10-09T19:00:00+02:00")
    assert result.raw_value == "19:00 Uhr"
    assert result.question == "Wann endet der Termin?"


def test_german_named_date_rejects_invalid_day_and_conflicting_weekday():
    invalid = normalize_event(event(date_text="31. Februar 2026"), context())
    conflict = normalize_event(event(date_text="Donnerstag, den 9. Oktober 2026"), context())
    assert invalid.reason == NormalizationReason.INVALID_DATE
    assert conflict.reason == NormalizationReason.INVALID_DATE

@pytest.mark.parametrize("raw", ["Freitag, den 9. Oktober 2026", "9. Oktober 2026"])
def test_german_named_date_with_year_and_optional_weekday_is_supported(raw):
    result = normalize_event(event(date_text=raw, time_text="19:00 Uhr",
                                   end_time_text=None, time_requirement="timed"), context())
    assert result.reason == NormalizationReason.MISSING_END_TIME
    assert result.known_date == date(2026, 10, 9)
    assert result.known_start == datetime.fromisoformat("2026-10-09T19:00:00+02:00")
    assert result.raw_value == "19:00 Uhr"
    assert result.question == "Wann endet der Termin?"


def test_german_named_date_rejects_invalid_day_and_conflicting_weekday():
    invalid = normalize_event(event(date_text="31. Februar 2026"), context())
    conflict = normalize_event(event(date_text="Donnerstag, den 9. Oktober 2026"), context())
    assert invalid.reason == NormalizationReason.INVALID_DATE
    assert conflict.reason == NormalizationReason.INVALID_DATE
