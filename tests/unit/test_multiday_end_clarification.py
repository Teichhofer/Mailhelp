"""A missing end clock must retain the validated last calendar day."""
from datetime import date
from pathlib import Path

import pytest

from mailhelp.domain.proposal import KnownTemporalFacts, Proposal
from mailhelp.domain.revision_errors import ContradictoryRevision
from mailhelp.text.temporal_answers import deterministic_temporal_revision
from tests.fakes.shared_telegram_dialog import proposal


@pytest.mark.parametrize("answer, fact_date", [("12:30", None), ("10.01.2027 12:30", date(2027, 1, 7))])
def test_end_answer_uses_last_day_after_a_restart(answer, fact_date):
    question = "Wann endet der Termin am 10.01.2027?"
    item = proposal(
        kind="event", status="needs_clarification", open_questions=[question],
        known_temporal_facts={"date": "2027-01-07", "start": "2027-01-07T11:30:00+01:00",
                              "end_date": "2027-01-10"},
    )
    restored = Proposal.model_validate_json(item.model_dump_json())
    revised = deterministic_temporal_revision(restored, question, answer, "Europe/Berlin")
    assert revised.start.isoformat() == "2027-01-07T11:30:00+01:00"
    assert revised.end.isoformat() == "2027-01-10T12:30:00+01:00"
    assert (revised.temporal_fact.normalized_date if revised.temporal_fact else None) == fact_date
    assert revised.version == item.version + 1
    assert revised.open_questions == []


def test_normalization_retains_the_last_day_for_the_builder():
    from mailhelp.proposals.action_normalization import normalize_event
    from tests.fakes.shared_action_normalization import context, event

    result = normalize_event(event(date_text="7. bis 10. Januar", time_requirement="timed",
                                   time_text="11:30"), context())
    assert result.known_end_date == date(2027, 1, 10)


def test_builder_and_successive_answers_keep_both_days():
    from tests.fakes.proposal_builder_fakes import builder, event

    item = builder().build([], [event(date_text="7. bis 10. Januar", time_requirement="timed",
                                     evidence="Tagung", time_text=None, end_time_text="12:30")])[0]
    assert item.known_temporal_facts.end_date == date(2027, 1, 10)
    item = deterministic_temporal_revision(item, item.open_questions[0], "11:30", "Europe/Berlin")
    assert item.known_temporal_facts.end_date == date(2027, 1, 10)
    item = deterministic_temporal_revision(item, item.open_questions[0], "12:30", "Europe/Berlin")
    assert item.start.date() == date(2027, 1, 7)
    assert item.end.date() == date(2027, 1, 10)


def test_known_end_day_must_not_precede_the_known_start():
    with pytest.raises(ValueError, match="Enddatum"):
        KnownTemporalFacts(date=date(2027, 1, 10), end_date=date(2027, 1, 7))


def test_an_answer_cannot_move_the_validated_last_day():
    question = "Wann endet der Termin am 10.01.2027?"
    item = proposal(kind="event", status="needs_clarification", open_questions=[question],
                    known_temporal_facts={"date": "2027-01-07", "end_date": "2027-01-10",
                                          "start": "2027-01-07T11:30:00+01:00"})
    with pytest.raises(ContradictoryRevision):
        deterministic_temporal_revision(item, question, "12.01.2027 12:30", "Europe/Berlin")
    with pytest.raises(ContradictoryRevision):
        deterministic_temporal_revision(item, question, "11.01.2027 12:30", "Europe/Berlin")


def test_a_service_successor_must_preserve_the_last_day():
    from mailhelp.processing.analysis import validate_revision_successor

    question = "Wann endet der Termin am 10.01.2027?"
    item = proposal(kind="event", status="needs_clarification", open_questions=[question],
                    known_temporal_facts={"date": "2027-01-07", "end_date": "2027-01-10",
                                          "start": "2027-01-07T11:30:00+01:00"})
    revised = deterministic_temporal_revision(item, question, "12:30", "Europe/Berlin")
    assert validate_revision_successor(item, revised) == revised
    wrong = {**revised.model_dump(mode="json"), "end": "2027-01-08T12:30:00+01:00"}
    with pytest.raises(ContradictoryRevision, match="Enddatum"):
        validate_revision_successor(item, wrong)


def test_the_upgrade_state_and_older_files_remain_readable():
    folder = Path(__file__).parents[1] / "upgrade/states/7.4/incomplete"
    path, = folder.glob("proposal-*.json")
    item = Proposal.model_validate_json(path.read_text(encoding="utf-8"))
    assert item.known_temporal_facts.end_date == date(2027, 1, 10)
    older = item.model_dump(mode="json")
    del older["known_temporal_facts"]["end_date"]
    restored = Proposal.model_validate(older)
    assert restored.known_temporal_facts.end_date is None
    assert restored.known_temporal_facts.start == item.known_temporal_facts.start
