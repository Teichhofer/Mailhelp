"""Event times from mails: clock formats, changed times of existing events, revision notes."""
from __future__ import annotations

from datetime import datetime, timezone
import json

import httpx
import pytest

from mailhelp.action_normalization import NormalizationReason, normalize_event
from mailhelp.integrations import HttpWriter
from mailhelp.models import CalendarDuplicateDecision
from mailhelp.storage import JsonStore
from mailhelp.telegram.formatting import revision_summary
from test_action_normalization import context, event as extracted
from test_telegram_dialog import Writer, callback, controller, proposal

NOW = datetime(2026, 10, 11, 14, 3, tzinfo=timezone.utc)


@pytest.mark.parametrize(("time_text", "end_text", "start", "end"), [
    # Regression: these forms caused an extra question and LLM call although the
    # mail contained every value (Skype-Termin, vlf-Austausch, Beiratssitzung).
    ("13.00 Uhr", "14.30 Uhr", "13:00", "14:30"),
    ("14:00", "ca. 15:30 Uhr", "14:00", "15:30"),
    ("gegen 9 Uhr", "etwa 10.15 Uhr", "09:00", "10:15"),
    ("um ca. 16.00 Uhr", "circa 17:00", "16:00", "17:00"),
    ("ungefähr 8:30", "ca 9 Uhr", "08:30", "09:00"),
])
def test_common_german_clock_forms_need_no_question(time_text, end_text, start, end):
    result = normalize_event(extracted(date_text="20.11.2026", time_text=time_text,
                                       end_time_text=end_text, time_requirement="timed"), context())
    assert result.reason is None and result.question is None
    assert f"{result.value.start:%H:%M}" == start and f"{result.value.end:%H:%M}" == end


@pytest.mark.parametrize("time_text", ["07.10", "13.00", "ca. 25.00 Uhr"])
def test_a_dot_without_uhr_or_an_invalid_clock_is_still_asked(time_text):
    result = normalize_event(extracted(date_text="20.11.2026", time_text=time_text,
                                       time_requirement="timed"), context())
    assert result.reason in {NormalizationReason.UNSUPPORTED_TIME, NormalizationReason.INVALID_TIME}


def calendar_writer(existing, missing_fields=(), seen=None):
    def handler(request):
        if seen is not None:
            seen.append(request)
        if request.method == "PATCH":
            return httpx.Response(200, json={"id": "old", "htmlLink": "https://calendar.test/old"})
        if "privateExtendedProperty" in request.url.params:
            return httpx.Response(200, json={"items": []})
        return httpx.Response(200, json={"items": [{"id": "old", "description": "Alt", **existing}]})
    return HttpWriter("google_calendar", "synthetic", "calendar", calendar_timezone="Europe/Berlin",
                      transport=httpx.MockTransport(handler), calendar_matcher=lambda *_: (
                          "call", CalendarDuplicateDecision(same_event=True, reason="same",
                                                            missing_fields=list(missing_fields))))


def timed_event(**changes):
    changes.setdefault("target", "calendar")
    return proposal(kind="event", start="2026-10-21T12:30:00+02:00",
                    end="2026-10-21T15:30:00+02:00", status="confirmed", **changes)


def test_same_event_with_another_end_is_updated_and_the_change_is_noted(monkeypatch):
    """Regression: a confirmed new end time was dropped as "already exists"."""
    monkeypatch.setattr("mailhelp.external.calendar._now", lambda zone: NOW)
    seen = []
    writer = calendar_writer({"start": {"dateTime": "2026-10-21T12:30:00+02:00"},
                              "end": {"dateTime": "2026-10-21T14:30:00+02:00"}}, seen=seen)
    try:
        result = writer.create(timed_event(version=5), "key")
    finally:
        writer.close()
    patch = next(request for request in seen if request.method == "PATCH")
    body = json.loads(patch.content)
    assert body["start"] == {"dateTime": "2026-10-21T12:30:00+02:00"}
    assert body["end"] == {"dateTime": "2026-10-21T15:30:00+02:00"}
    assert body["description"] == (
        "Alt\n\n[Mailhelp 11.10.2026 14:03] Zeit aktualisiert: Ende 21.10.2026 14:30 Uhr → "
        "21.10.2026 15:30 Uhr (bestätigte Vorschlagsversion 5).")
    assert result["operation"] == "duplicate_updated"
    assert result["time_changes"] == ["Ende 21.10.2026 14:30 Uhr → 21.10.2026 15:30 Uhr"]


def test_equal_instants_in_another_offset_and_unknown_times_are_not_changes(monkeypatch):
    monkeypatch.setattr("mailhelp.external.calendar._now", lambda zone: NOW)
    for existing in ({"start": {"dateTime": "2026-10-21T10:30:00Z"},
                      "end": {"dateTime": "2026-10-21T13:30:00Z"}},
                     {"start": {}, "end": {}}):
        seen = []
        writer = calendar_writer(existing, seen=seen)
        try:
            result = writer.create(timed_event(), "key")
        finally:
            writer.close()
        assert result["operation"] == "duplicate_skipped"
        assert [request.method for request in seen] == ["GET"]


def test_all_day_and_timed_changes_name_old_and_new_values(monkeypatch):
    monkeypatch.setattr("mailhelp.external.calendar._now", lambda zone: NOW)
    all_day = proposal(kind="event", all_day=True, start="2026-10-21", end="2026-10-22",
                       status="confirmed", target="calendar")
    writer = calendar_writer({"start": {"date": "2026-10-21"}, "end": {"date": "2026-10-24"}})
    try:
        assert writer.create(all_day, "key")["time_changes"] == ["Ende 23.10.2026 → 21.10.2026"]
    finally:
        writer.close()
    writer = calendar_writer({"start": {"date": "2026-10-21"}, "end": {"date": "2026-10-22"}},
                             missing_fields=["description"])
    try:
        changes = writer.create(timed_event(description="Neu"), "key")["time_changes"]
    finally:
        writer.close()
    assert changes == ["Beginn 21.10.2026 → 21.10.2026 12:30 Uhr",
                       "Ende 21.10.2026 → 21.10.2026 15:30 Uhr"]


def test_telegram_reports_the_updated_time(tmp_path):
    class Updating(Writer):
        def create(self, item, key):
            super().create(item, key)
            return {"id": "old", "operation": "duplicate_updated",
                    "time_changes": ["Ende 21.10.2026 14:30 Uhr → 21.10.2026 15:30 Uhr"]}

    item = proposal(kind="event", start="2026-10-21T12:30:00+02:00", end="2026-10-21T15:30:00+02:00")
    with JsonStore(tmp_path) as store:
        c, t, _ = controller(store, writers={"google_calendar": Updating()})
        c.send_proposal(item)
        t.updates = [callback(1, t.sent[-1][2]["inline_keyboard"][0][0]["callback_data"])]
        c.poll_once()
    assert t.sent[-1][1] == (
        "✅ Bestehender Termin „Aufgabe“ aktualisiert: Ende 21.10.2026 14:30 Uhr → "
        "21.10.2026 15:30 Uhr. Die Änderung ist in der Terminbeschreibung vermerkt.")


def test_new_questions_after_an_answer_are_shown_as_new_not_taken_over():
    """Regression: after a date answer the new time questions appeared under "Übernommen"."""
    before = proposal(kind="event", open_questions=["Welches Datum ist gemeint?"])
    after = proposal(kind="event", version=2, open_questions=[
        "Wann beginnt der Termin?", "Wann endet der Termin?"])
    assert revision_summary(before, after, "Europe/Berlin") == (
        "Übernommen.\nNeu offen:\n- Wann beginnt der Termin?\n- Wann endet der Termin?")


def test_change_notes_use_the_current_time_in_the_calendar_zone():
    from mailhelp.external.calendar import _now
    before = datetime.now(timezone.utc)
    noted = _now("Europe/Berlin")
    assert str(noted.tzinfo) == "Europe/Berlin" and noted >= before
    assert str(_now(None).tzinfo) == "UTC"
