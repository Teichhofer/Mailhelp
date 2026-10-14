"""Duration provenance, partial facts, explicit durations and UTC elapsed time."""
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from web_scenario import proposal

from mailhelp.action_normalization import MailDateContext
from mailhelp.config import EventDefaultsSettings
from mailhelp.domain.extraction import ExtractedEvent
from mailhelp.event_defaults import meeting_mode, normalized_event, reapply_defaults
from mailhelp.external.ical import calendar_file
from mailhelp.review.cards import event_time
from mailhelp.review.editing import ProposalEditPatch, edit_proposal


def extracted(**changes):
    return ExtractedEvent.model_validate({"title": "Videokonferenz", "evidence": "Online am 20.11.2030 um 14 Uhr",
        "description": "Synthetische Sitzung", "responsibility": "user", "certainty": "certain",
        "classification": "new", "date_text": "2030-11-20", "time_text": "14:00 Uhr",
        "time_requirement": "timed", **changes})


def context():
    return MailDateContext(date_context_status="valid", date_header_parsed="2030-11-18T09:00:00+00:00",
                          imap_received_at="2030-11-18T09:00:00+00:00", user_timezone="Europe/Berlin")


@pytest.mark.parametrize("title,evidence,location,expected", [
    ("Besprechung", "Synthetisch", None, "unknown"),
    ("Skype-Termin", "Synthetisch", None, "video"),
    ("Präsenztermin", "Treffen vor Ort", "Raum 3", "in_person"),
    ("Besprechung", "Online und vor Ort", "Raum 3", "hybrid"),
])
def test_participation_mode_requires_explicit_evidence(title, evidence, location, expected):
    assert meeting_mode(extracted(title=title, evidence=evidence, location=location, description=None)) == expected


@pytest.mark.parametrize("mode,duration", [("video", 60), ("in_person", 180)])
def test_defaults_supply_missing_end_and_are_visible(mode, duration):
    title = "Videokonferenz" if mode == "video" else "Präsenztermin"
    event = extracted(title=title, evidence="Synthetischer Termin", description=None)
    result, actual, origin, applied = normalized_event(event, context(), EventDefaultsSettings())
    assert result.resolved and actual == mode and origin == "standard" and applied == duration
    assert result.value.end - result.value.start == timedelta(minutes=duration)
    item = proposal(1, "default", kind="event", title=title, start=result.value.start, end=result.value.end,
                    meeting_mode=mode, end_origin=origin, default_duration_minutes=applied)
    assert "angenommen" in event_time(item, "Europe/Berlin")
    assert str(duration) in event_time(item, "Europe/Berlin")
    assert f"Standarddauer {duration} Minuten" in calendar_file(item, "key").decode()


@pytest.mark.parametrize("changes,origin,applied", [
    ({"end_time_text": "15:30 Uhr"}, "mail_end", None),
    ({"duration_minutes": 90}, "mail_duration", None),
    ({"duration_minutes": 90, "duration_is_upper_bound": True}, "unknown", None),
    ({"time_text": None, "time_requirement": "required_unknown"}, "unknown", None),
    ({"title": "Besprechung", "evidence": "Unklar", "description": None}, "unknown", None),
])
def test_explicit_information_and_uncertainty_take_precedence(changes, origin, applied):
    result, _, found_origin, found_applied = normalized_event(extracted(**changes), context(), EventDefaultsSettings())
    assert found_origin == origin and found_applied == applied
    if changes.get("duration_minutes") == 90 and not changes.get("duration_is_upper_bound"):
        assert result.value.end - result.value.start == timedelta(minutes=90)


def test_legacy_proposals_only_receive_defaults_by_explicit_local_revision():
    start = datetime(2030, 11, 20, 14, tzinfo=UTC)
    item = proposal(1, "legacy", kind="event", title="Skype-Termin", known_temporal_facts={"start": start},
                    open_questions=["Wann endet der Termin?"], end=None)
    revised = reapply_defaults(item, EventDefaultsSettings(video_duration_minutes=75))
    assert revised.version == 2 and revised.start == start and revised.end == start + timedelta(minutes=75)
    assert revised.default_duration_minutes == 75 and revised.end_origin == "standard"
    assert item.version == 1 and item.end is None
    assert reapply_defaults(revised, EventDefaultsSettings(video_duration_minutes=75)) == revised
    assert reapply_defaults(revised, EventDefaultsSettings()).version == 3
    assert reapply_defaults(proposal(1, "task"), EventDefaultsSettings()).kind == "task"
    ambiguous = item.model_copy(update={"title": "Besprechung"})
    assert reapply_defaults(ambiguous, EventDefaultsSettings()) == ambiguous
    hybrid = item.model_copy(update={"meeting_mode": "hybrid"})
    assert reapply_defaults(hybrid, EventDefaultsSettings()) == hybrid
    bounded = item.model_copy(update={"duration_minutes": 60})
    assert reapply_defaults(bounded, EventDefaultsSettings()) == bounded


@pytest.mark.parametrize("date,time,end", [
    ("2030-03-31", "01:30 Uhr", "2030-03-31T03:30:00+02:00"),
    ("2030-10-27", "01:30 Uhr", "2030-10-27T02:30:00+02:00"),
    ("2030-11-20", "23:30 Uhr", "2030-11-21T00:30:00+01:00"),
])
def test_default_duration_measures_elapsed_minutes_across_dst_and_midnight(date, time, end):
    result, _, _, _ = normalized_event(extracted(date_text=date, time_text=time), context(), EventDefaultsSettings())
    assert result.value.end.isoformat() == end
    assert result.value.end.astimezone(UTC) - result.value.start.astimezone(UTC) == timedelta(hours=1)


def test_manual_end_replaces_provenance_and_remains_protected():
    item = proposal(1, "manual", kind="event", start="2030-11-20T14:00:00+01:00",
        end="2030-11-20T15:00:00+01:00", meeting_mode="video", end_origin="standard", default_duration_minutes=60)
    revised = edit_proposal(item, ProposalEditPatch(end="2030-11-20T16:00:00+01:00"), "Europe/Berlin", {item.target})
    assert revised.end_origin == "manual" and revised.default_duration_minutes is None
    assert "end" in revised.protected_fields
    with pytest.raises(ValidationError):
        item.model_validate({**item.model_dump(), "end_origin": "mail_end"})
    with pytest.raises(ValidationError):
        item.model_validate({**item.model_dump(), "merge_review_required": True})


def test_video_link_is_evidence_even_when_the_title_is_generic():
    result, mode, origin, duration = normalized_event(extracted(title="Austausch", description=None,
        evidence="Sitzung am 20.11.2030 um 14 Uhr", video_link="https://video.example.test/meeting"),
        context(), EventDefaultsSettings())
    assert result.resolved and mode == "video" and origin == "standard" and duration == 60


def test_google_calendar_description_records_the_actual_assumption():
    from mailhelp.integrations import HttpWriter
    result, _, _, _ = normalized_event(extracted(), context(), EventDefaultsSettings())
    item = proposal(1, "default", kind="event", start=result.value.start, end=result.value.end,
                    end_origin="standard", default_duration_minutes=60)
    writer = HttpWriter("google_calendar", "synthetic-token", item.target, calendar_timezone="Europe/Berlin")
    try:
        body = writer._calendar_event_body(item, "synthetic-key")
        assert "Standarddauer 60 Minuten" in body["description"]
    finally:
        writer.close()


def test_regression_manual_day_can_receive_a_confirmed_start_without_losing_protection():
    from mailhelp.domain.proposal_sources import ProposalSource
    from mailhelp.proposal_merge import merge_facts
    start = datetime(2030, 11, 20, 14, tzinfo=UTC)
    old = proposal(80, "day", kind="event", title="Videokonferenz", known_temporal_facts={"date": start.date()},
        protected_fields=["known_temporal_facts"], certainty="certain",
        open_questions=["Welches konkrete Datum?", "Wann beginnt der Termin?", "Wann endet der Termin?"],
        sources=[ProposalSource(mail_id="a" * 24, proposal_id="day", sent_at=start - timedelta(days=2))])
    incoming = proposal(81, "start", kind="event", title=old.title,
        known_temporal_facts={"start": start}, open_questions=["Wann endet der Termin?"],
        sources=[ProposalSource(mail_id="b" * 24, proposal_id="start", sent_at=start - timedelta(days=1))])
    merged = merge_facts(old, incoming)
    assert merged.known_temporal_facts.date == old.known_temporal_facts.date
    assert merged.known_temporal_facts.start == start
    revised = reapply_defaults(merged, EventDefaultsSettings())
    assert revised.start == start and revised.end == start + timedelta(hours=1)
    assert revised.status == "pending_confirmation" and "start" in revised.protected_fields
