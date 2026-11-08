"""4.6, step 17.2: the date an event had before a change."""
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from mailhelp.models import CalendarCandidate, EventExtraction, Proposal
from mailhelp.proposals.action_normalization import resolve_day
from tests.fakes.proposal_builder_fakes import builder, context, event

MOVE = "Die Sitzung am 04.12.2026 wird auf den 11.12.2026 verschoben."


@pytest.mark.parametrize(("raw", "expected"), [
    ("04.12.2026", date(2026, 12, 4)),
    ("Freitag, 4. Dezember 2026", date(2026, 12, 4)),
    ("4. Dezember", date(2026, 12, 4)),         # year from the mail date (18.09.2026)
    ("31.02.2026", None),                        # invalid
    ("nächste Woche", None),                     # unsupported
    (None, None),
])
def test_an_earlier_date_text_resolves_like_an_event_date(raw, expected):
    assert resolve_day(raw, context()) == expected


def test_a_change_carries_the_resolved_earlier_day():
    (proposal,) = builder().build([], [event(classification="change", evidence=MOVE, date_text="11.12.2026",
                                             original_date_text="04.12.2026")])
    assert proposal.original_date == date(2026, 12, 4)
    assert proposal.start == date(2026, 12, 11)  # the new state stays the proposal's time


def test_without_or_with_an_unreadable_earlier_date_the_change_keeps_none():
    for raw in (None, "letzte Woche"):
        (proposal,) = builder().build([], [event(classification="change", evidence=MOVE, original_date_text=raw)])
        assert proposal.original_date is None


def test_only_a_change_uses_the_earlier_date():
    (proposal,) = builder().build([], [event(classification="cancellation", original_date_text="04.12.2026")])
    assert proposal.original_date is None


def test_an_extraction_without_the_new_field_keeps_its_proposal_id():
    """IDs from before 4.6 must stay stable (value computed with the 4.6.0 code)."""
    (proposal,) = builder().build([], [event(classification="change", evidence=MOVE, date_text="11.12.2026")])
    assert proposal.id == "p_0b010a9019e1149fabc92518"
    (with_date,) = builder().build([], [event(classification="change", evidence=MOVE, date_text="11.12.2026",
                                              original_date_text="04.12.2026")])
    assert with_date.id != proposal.id  # a different extraction is a different proposal


def test_old_extractions_without_the_field_still_validate():
    stored = {"schema_version": 1, "events": [event().model_dump(mode="json", exclude={"original_date_text"})]}
    assert EventExtraction.model_validate(stored).events[0].original_date_text is None


def proposal(**changes):
    values = dict(schema_version=3, id="p1", version=1, kind="event", responsibility="user", certainty="certain",
                  classification="change", title="Sitzung", evidence="x", source_mail_id="a" * 24, target="primary",
                  status="needs_clarification", open_questions=["Welcher bestehende Eintrag soll geändert werden?"])
    values.update(changes)
    return Proposal.model_validate(values)


def test_candidates_and_earlier_dates_belong_to_events_only():
    candidate = CalendarCandidate(event_id="e1", title="Sitzung", start=datetime(2026, 12, 4, 17, tzinfo=UTC),
                                  end=datetime(2026, 12, 4, 19, tzinfo=UTC))
    assert proposal(calendar_candidates=[candidate], original_date=date(2026, 12, 4)).calendar_candidates
    with pytest.raises(ValidationError, match="nur für Termine ohne gewähltes Ziel"):
        proposal(calendar_candidates=[candidate], target_event_id="e1")
    with pytest.raises(ValidationError, match="nur für Termine ohne gewähltes Ziel"):
        proposal(kind="task", calendar_candidates=[candidate])
    with pytest.raises(ValidationError, match="Nur Termine haben ein früheres Datum"):
        proposal(kind="task", original_date=date(2026, 12, 4))


def test_the_extraction_prompt_asks_for_the_earlier_date():
    prompts = yaml.safe_load(Path("prompts.yaml").read_text(encoding="utf-8"))["prompts"]
    text = " ".join(prompts["event_extraction"]["system_prompt"].split())
    assert "original_date_text ist das wörtliche frühere Datum aus der Mail" in text
    assert "date_text, time_text, end_time_text und location enthalten dann den NEUEN Stand" in text
    assert "ist classification \"cancellation\"" in text and "original_date_text null" in text
