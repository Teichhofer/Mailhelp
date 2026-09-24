from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from mailhelp.action_normalization import MailDateContext
from mailhelp.config import TargetSettings
from mailhelp.models import (ExtractedEvent, ExtractedTask, ExtractionCountConflict,
                             KnownTemporalFacts, Proposal, ProposalStatus, TemporalFact)
from mailhelp.proposal_builder import ProposalBuilder
from mailhelp.storage import JsonStore


def context(**changes):
    values = dict(date_context_status="valid", date_header_parsed="2026-09-18T10:00:00+02:00",
                  imap_received_at="2026-09-18T10:01:00+02:00", user_timezone="Europe/Berlin")
    values.update(changes)
    return MailDateContext(**values)


def task(**changes):
    values = dict(title="Antworten", description="", evidence="Bitte antworten",
                  responsibility="user", certainty="certain", classification="new", due_text=None)
    values.update(changes)
    return ExtractedTask(**values)


def event(**changes):
    values = dict(title="Gemeinderat", description=None, evidence="Gemeinderat am 22.09.2026",
                  date_text="22.09.2026", time_text=None, end_time_text=None, location=None,
                  time_requirement="all_day",
                  video_link=None, responsibility="user", certainty="certain", classification="new")
    values.update(changes)
    return ExtractedEvent(**values)


def builder(**changes):
    targets = TargetSettings(todoist_project="todoist-1", google_calendar="calendar-1")
    return ProposalBuilder("a" * 24, targets, context(**changes))


@pytest.mark.parametrize("responsibility", ["user", "other", "unclear"])
@pytest.mark.parametrize("certainty", ["certain", "uncertain", "contradictory"])
@pytest.mark.parametrize("classification", [
    "new", "non_binding", "already_completed", "change", "cancellation", "recurring", "unsupported",
])
def test_complete_status_rule_all_combinations(responsibility, certainty, classification):
    proposal = builder().build([task(responsibility=responsibility, certainty=certainty,
                                     classification=classification)], [])[0]
    ready = responsibility == "user" and certainty == "certain" and classification == "new"
    assert proposal.status == (ProposalStatus.PENDING_CONFIRMATION if ready
                               else ProposalStatus.NEEDS_CLARIFICATION)
    assert bool(proposal.open_questions) is not ready


def test_missing_event_time_and_gemeinderat_responsibility_are_explicit():
    missing = builder().build([], [event(time_text="10:00", end_time_text=None,
                                         time_requirement="timed")])[0]
    assert missing.start is None and missing.end is None
    assert missing.status == ProposalStatus.NEEDS_CLARIFICATION
    assert "Wann endet" in missing.open_questions[0]
    assert missing.known_temporal_facts.date == date(2026, 9, 22)
    assert missing.known_temporal_facts.start.isoformat() == "2026-09-22T10:00:00+02:00"

    council = builder().build([], [event(responsibility="unclear")])[0]
    assert (council.start, council.end, council.all_day) == (
        date(2026, 9, 22), date(2026, 9, 23), True)
    assert council.status == ProposalStatus.NEEDS_CLARIFICATION
    assert "zuständig" in council.open_questions[0]


def test_trusted_fields_targets_stable_ids_duplicates_and_restart():
    extracted = task(due_text="2026-09-30")
    first = builder().build([extracted, extracted], [])
    restarted = builder().build([extracted], [])
    assert len(first) == 2
    assert first[0] == restarted[0]
    proposal = first[0]
    assert proposal.model_dump(include={"schema_version", "version", "source_mail_id", "target",
                                        "external_id", "external_link", "uncertain_notified",
                                        "simulation_notified"}) == {
        "schema_version": 2, "version": 1, "source_mail_id": "a" * 24,
        "target": "todoist-1", "external_id": None, "external_link": None,
        "uncertain_notified": False, "simulation_notified": False,
    }
    assert proposal.id != ProposalBuilder("b" * 24, builder().targets, context()).build([extracted], [])[0].id
    assert builder().build([], [event()])[0].target == "calendar-1"


def test_unresolved_date():
    unresolved = builder().build([], [event(date_text="kommenden Dienstag")])[0]
    assert unresolved.status == ProposalStatus.NEEDS_CLARIFICATION and unresolved.start is None


def test_date_range_recovered_from_evidence_needs_no_date_question():
    proposal = builder().build([], [event(
        date_text=None, time_requirement="required_unknown",
        evidence="Das Seminar findet vom 5.- 6. November 2026 in Würzburg statt.",
        location="Würzburg",
    )])[0]
    assert (proposal.start, proposal.end, proposal.all_day) == (
        date(2026, 11, 5), date(2026, 11, 7), True)
    assert proposal.open_questions == []
    assert proposal.status == ProposalStatus.PENDING_CONFIRMATION


@pytest.mark.parametrize(("kind", "word"), [("task", "Aufgaben"), ("event", "Termine")])
def test_count_conflict_forces_a_concrete_clarification(kind, word):
    conflict = ExtractionCountConflict(category=kind, expected_count=2, actual_count=1,
                                       router_call_id="router", extractor_call_id="extractor")
    proposals = builder().build([task()] if kind == "task" else [],
                                [event()] if kind == "event" else [], [conflict])
    assert proposals[0].status == ProposalStatus.NEEDS_CLARIFICATION
    assert any(word in question for question in proposals[0].open_questions)


def test_structured_context_date_survives_proposal_boundary():
    proposal = builder().build([], [event(date_text="21. Oktober",
                                         evidence="Treffen am 21. Oktober")])[0]
    assert proposal.start == date(2026, 10, 21)
    assert proposal.temporal_fact.raw_text == "21. Oktober"
    assert proposal.temporal_fact.normalized_date == date(2026, 10, 21)
    assert proposal.temporal_fact.year_source == "mail_context"


def test_weekday_prefixed_numeric_date_builds_complete_timed_proposal_without_date_question():
    proposal = builder().build([], [event(
        date_text="Mi, 23.09.2026", time_text="09:00 Uhr", end_time_text="10:00 Uhr",
        time_requirement="timed", evidence="Treffen Mi, 23.09.2026 von 09:00 Uhr bis 10:00 Uhr",
    )])[0]
    assert proposal.start == datetime.fromisoformat("2026-09-23T09:00:00+02:00")
    assert proposal.end == datetime.fromisoformat("2026-09-23T10:00:00+02:00")
    assert proposal.status == ProposalStatus.PENDING_CONFIRMATION
    assert proposal.open_questions == []
    assert proposal.temporal_fact.raw_text == "Mi, 23.09.2026"
    assert proposal.temporal_fact.normalized_date == date(2026, 9, 23)
    assert proposal.temporal_fact.year_source == "explicit_mail"
    assert proposal.temporal_fact.status == "resolved"


def test_explicit_offset_instant_survives_proposal_persistence(tmp_path):
    proposal = builder(user_timezone="America/New_York").build([], [event(
        date_text="23.09.2026", time_text="09:00", end_time_text="10:00",
        timezone_offset_text="UTC+01:00", time_requirement="timed",
        evidence="23.09.2026, 09:00–10:00 (UTC+01:00)",
    )])[0]
    with JsonStore(tmp_path / "proposals") as store:
        store.save("offset-event", proposal.model_dump(mode="json"))
        restored = store.load_model("offset-event", Proposal)
    assert restored is not None
    assert restored.start.isoformat() == "2026-09-23T09:00:00+01:00"
    assert restored.end.isoformat() == "2026-09-23T10:00:00+01:00"
    assert restored.start.astimezone(timezone.utc).isoformat() == "2026-09-23T08:00:00+00:00"
    assert restored.end.astimezone(timezone.utc).isoformat() == "2026-09-23T09:00:00+00:00"


def test_temporal_fact_rejects_inconsistent_resolution_and_source():
    with pytest.raises(ValidationError, match="aufgelöster Zeitfakt"):
        TemporalFact(raw_text="21. Oktober", normalized_date="2026-10-21", status="unresolved")
    with pytest.raises(ValidationError, match="Jahresherkunft"):
        TemporalFact(raw_text="21. Oktober", year_source="mail_context", status="unresolved")


def test_date_without_time_is_conservative_and_retained():
    proposal = builder().build([], [event(time_requirement="required_unknown")])[0]
    assert proposal.start is None and proposal.end is None and proposal.all_day is False
    assert proposal.known_temporal_facts.date == date(2026, 9, 22)
    assert proposal.open_questions == ["Wann beginnt der Termin?"]


def test_proposal_validation_does_not_silently_correct_status():
    common = dict(id="p", version=1, kind="task", responsibility="unclear", certainty="certain",
                  classification="new", title="x", evidence="x", source_mail_id="a" * 24, target="p")
    with pytest.raises(ValidationError, match="vollständige neue"):
        Proposal(status="pending_confirmation", **common)


def test_known_temporal_facts_are_strict_and_event_only():
    with pytest.raises(ValidationError, match="Offset"):
        KnownTemporalFacts(start="2026-09-22T10:00:00")
    with pytest.raises(ValidationError, match="Mindestens"):
        KnownTemporalFacts()
    with pytest.raises(ValidationError, match="zusammenpassen"):
        KnownTemporalFacts(date="2026-09-22", start="2026-09-23T10:00:00+02:00")
    with pytest.raises(ValidationError, match="Nur Termine"):
        proposal = builder().build([task()], [])[0]
        Proposal.model_validate({**proposal.model_dump(),
                                 "known_temporal_facts": {"date": "2026-09-22"}})
    incomplete = builder().build([], [event(time_requirement="required_unknown")])[0]
    with pytest.raises(ValidationError, match="nicht mit Terminintervallen"):
        Proposal.model_validate({**incomplete.model_dump(),
                                 "start": "2026-09-22T10:00:00+02:00"})


def test_identity_collision_is_rehashed_and_a_second_collision_rejected(monkeypatch):
    class Digest:
        def __init__(self, value): self.value = value
        def hexdigest(self): return self.value * 64

    values = iter(["a", "a", "b"])
    monkeypatch.setattr("mailhelp.proposal_builder.hashlib.sha256", lambda _value: Digest(next(values)))
    proposals = builder().build([task(title="one"), task(title="two")], [])
    assert [item.id for item in proposals] == ["p_" + "a" * 24, "p_" + "b" * 24]

    monkeypatch.setattr("mailhelp.proposal_builder.hashlib.sha256", lambda _value: Digest("a"))
    with pytest.raises(ValueError, match="Kollision"):
        builder().build([task(title="one"), task(title="two")], [])
