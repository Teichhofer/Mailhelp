from datetime import date

import pytest
from pydantic import ValidationError

from mailhelp.action_normalization import MailDateContext
from mailhelp.config import TargetSettings
from mailhelp.models import ExtractedEvent, ExtractedTask, Proposal, ProposalStatus
from mailhelp.proposal_builder import ProposalBuilder


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
    missing = builder().build([], [event(time_text="10:00", end_time_text=None)])[0]
    assert missing.start is None and missing.end is None
    assert missing.status == ProposalStatus.NEEDS_CLARIFICATION
    assert "Wann endet" in missing.open_questions[0]

    council = builder().build([], [event(responsibility="unclear")])[0]
    assert (council.start, council.end, council.all_day) == (
        date(2026, 9, 22), date(2026, 9, 23), True)
    assert council.status == ProposalStatus.NEEDS_CLARIFICATION
    assert "zuständig" in council.open_questions[0]


def test_trusted_fields_targets_stable_ids_duplicates_and_restart():
    extracted = task(due_text="2026-09-30")
    first = builder().build([extracted, extracted], [])
    restarted = builder().build([extracted], [])
    assert len(first) == 1
    assert first == restarted
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


def test_proposal_validation_does_not_silently_correct_status():
    common = dict(id="p", version=1, kind="task", responsibility="unclear", certainty="certain",
                  classification="new", title="x", evidence="x", source_mail_id="a" * 24, target="p")
    with pytest.raises(ValidationError, match="vollständige neue"):
        Proposal(status="pending_confirmation", **common)


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
