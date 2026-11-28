"""8.9.3 (Planung 8.9 AP3): the weekday of the source survives a shortened extraction.

Regression of audit case 45: the mail says "Dienstag, den 19.11.2026" (a Thursday); the model returned only
"19.11.2026" with certainty "certain", and Mailhelp asked only for the missing end time and kept the 19th as a
known date. "Dienstag, den 19.11.2026" itself was an unsupported format. Synthetic data only.
"""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from mailhelp.config import TargetSettings
from mailhelp.domain.extraction import ExtractedEvent, ExtractedTask
from mailhelp.domain.proposal import Proposal, ProposalRevisionDelta, apply_proposal_revision
from mailhelp.domain.revision_errors import ContradictoryRevision
from mailhelp.domain.temporal import WEEKDAY_MISMATCH_QUESTION
from mailhelp.processing.analysis import validate_revision_successor
from mailhelp.proposals.action_normalization import (
    MailDateContext,
    NormalizationReason,
    normalize_event,
    normalize_task_due,
)
from mailhelp.proposals.proposal_builder import ProposalBuilder
from mailhelp.text.source_dates import current_part, date_source, weekday_conflict

MAIL = "Hallo Alex,\n\nlass uns am Dienstag, den 19.11.2026 um 10:00 Uhr kurz abstimmen.\n\nGruß"


def context(source: str = MAIL) -> MailDateContext:
    return MailDateContext(date_context_status="valid", date_header_parsed="2026-11-12T09:00:00+01:00",
                           imap_received_at="2026-11-12T09:01:00+01:00", user_timezone="Europe/Berlin",
                           source_text=date_source(source, []))


def event(date_text: str = "19.11.2026", **changes) -> ExtractedEvent:
    values = {"title": "Abstimmung", "description": None, "evidence": "am Dienstag, den 19.11.2026 um 10:00 Uhr",
              "date_text": date_text, "time_text": "10:00", "end_time_text": None, "location": None,
              "video_link": None, "responsibility": "user", "certainty": "certain", "classification": "new",
              "time_requirement": "timed"}
    return ExtractedEvent.model_validate({**values, **changes})


def test_regression_the_shortened_date_keeps_the_contradicting_weekday_of_the_source():
    result = normalize_event(event(), context())
    assert result.reason == NormalizationReason.INVALID_DATE  # until 8.9.2: missing_end_time
    assert result.question == "Wochentag und Kalenderdatum widersprechen sich."
    assert result.known_date is None and result.temporal_fact.raw_text == "Dienstag, den 19.11.2026"
    assert result.temporal_fact.normalized_date is None
    assert result.known_start_time is not None  # the explicit clock stays a known fact


def test_regression_the_full_wording_with_den_is_a_supported_date():
    result = normalize_event(event("Dienstag, den 19.11.2026"), context(""))
    assert result.reason == NormalizationReason.INVALID_DATE  # until 8.9.2: unsupported_date_format
    right = normalize_event(event("Donnerstag, den 19.11.2026", end_time_text="11:00"), context(""))
    assert right.resolved and right.value.start.date() == date(2026, 11, 19)


@pytest.mark.parametrize(("source", "conflict"), [
    ("Treffen am Donnerstag, 19.11.2026 um 10 Uhr.", None),                       # the right weekday
    ("Treffen am 19.11.2026 um 10 Uhr.", None),                                    # no weekday at all
    ("Di 17.11.2026 Raum A\nDo 19.11.2026 Raum B", None),                         # another row of a table
    ("Neu: 19.11.2026.\n\n--- Ursprüngliche Nachricht ---\nDienstag, 19.11.2026?", None),  # only the old quote
    ("Neu: 19.11.2026.\n\nAm 10.11.2026 schrieb Kim:\nDienstag, 19.11.2026?", None),
    ("Neu: 19.11.2026.\n> Dienstag, 19.11.2026", None),
    ("Wir sehen uns Dienstag, 19. November.", "Dienstag, 19. November"),          # month name, no year
    ("Mo, 19.11. Treffen", "Mo, 19.11."),                                          # abbreviation, no year
    ("Do 19.11.2026 und Di 19.11.2026", "Di 19.11.2026"),                         # two passages disagree
    ("Montag, 31.02.2027 oder Donnerstag, 19.11.2026", None)])                      # an impossible day is skipped
def test_only_the_current_part_and_the_same_day_count(source, conflict):
    assert weekday_conflict(date(2026, 11, 19), current_part(source)) == conflict


def test_several_events_with_their_own_weekdays_and_ranges():
    source = "Termine: Dienstag, 17.11.2026 und Donnerstag, 19.11.2026, jeweils 10:00 bis 11:00 Uhr."
    for day in ("17.11.2026", "19.11.2026"):
        assert normalize_event(event(day, end_time_text="11:00"), context(source)).resolved
    wrong = "Klausur von Montag, 16.11.2026 bis Mittwoch, 19.11.2026"
    span = event("16.11.2026 bis 19.11.2026", time_text=None, time_requirement="all_day")
    result = normalize_event(span, context(wrong))
    assert result.reason == NormalizationReason.INVALID_DATE and result.temporal_fact.raw_text == "Mittwoch, 19.11.2026"
    across = "Vom Donnerstag, 31.12.2026 bis Freitag, 01.01.2027 geschlossen."
    assert normalize_event(event("31.12.2026 bis 01.01.2027", time_text=None, time_requirement="all_day"),
                           context(across)).resolved


def test_a_deadline_with_a_contradicting_weekday_needs_a_reply():
    task = ExtractedTask.model_validate({"title": "Bericht senden", "description": "", "evidence": "bis Montag, 19.11.2026",
                                         "responsibility": "user", "certainty": "certain", "classification": "new",
                                         "due_text": "19.11.2026"})
    result = normalize_task_due(task, context("Bitte den Bericht bis Montag, 19.11.2026 senden."))
    assert result.reason == NormalizationReason.INVALID_DATE and result.temporal_fact.raw_text == "Montag, 19.11.2026"
    assert normalize_task_due(task, context("Bitte den Bericht bis 19.11.2026 senden.")).resolved


def built(source: str = MAIL, **changes):
    targets = TargetSettings.model_validate({"todoist_project": "synthetic-todoist",
                                             "google_calendar": "synthetic-calendar"})
    return ProposalBuilder("m" * 24, targets, context(source)).build([], [event(**changes)])[0]


def test_regression_the_proposal_asks_for_the_date_first_and_keeps_it_over_a_restart():
    proposal = built()
    assert proposal.open_questions[0] == WEEKDAY_MISMATCH_QUESTION and proposal.start is None
    assert "Wann endet der Termin?" not in proposal.open_questions  # until 8.9.2 the only question
    assert proposal.temporal_fact.raw_text == "Dienstag, den 19.11.2026"
    restarted = Proposal.model_validate_json(proposal.model_dump_json())
    assert restarted == proposal and built() == proposal  # processing the mail again asks the same


def test_an_end_time_alone_does_not_settle_the_weekday_but_a_corrected_day_does():
    zone = ZoneInfo("Europe/Berlin")
    end = {"end": datetime(2026, 11, 19, 11, tzinfo=zone)}
    # With the known clock of the source an end alone is no valid revision at all; the question stays.
    proposal = built()
    with pytest.raises(ValueError, match="Zeitfakten"):
        apply_proposal_revision(proposal, ProposalRevisionDelta(answered_question=WEEKDAY_MISMATCH_QUESTION,
                                                                changes=end))
    # Without a known clock the end is taken, but it does not answer the weekday (until 8.9.2 it did).
    untimed = built(time_text=None, time_requirement="required_unknown")
    end_only = apply_proposal_revision(untimed, ProposalRevisionDelta(answered_question=WEEKDAY_MISMATCH_QUESTION,
                                                                      changes=end))
    assert WEEKDAY_MISMATCH_QUESTION in end_only.open_questions and end_only.status == "needs_clarification"
    assert end_only.end == end["end"]
    corrected = apply_proposal_revision(untimed, ProposalRevisionDelta(
        answered_question=WEEKDAY_MISMATCH_QUESTION,
        changes={"start": datetime(2026, 11, 17, 10, tzinfo=zone), "end": datetime(2026, 11, 17, 11, tzinfo=zone)}))
    assert WEEKDAY_MISMATCH_QUESTION not in corrected.open_questions and corrected.start.day == 17
    # A revision built on the outdated version is refused.
    with pytest.raises(ContradictoryRevision, match="Vorschlagsversion"):
        validate_revision_successor(end_only, corrected.model_dump())


def test_attachments_count_and_a_missing_source_changes_nothing():
    assert "Dienstag, 19.11.2026" in date_source("Siehe Anhang.", ["Plan: Dienstag, 19.11.2026, 10 Uhr"])
    old = MailDateContext(date_context_status="valid", date_header_parsed="2026-11-12T09:00:00+01:00",
                          imap_received_at="2026-11-12T09:01:00+01:00", user_timezone="Europe/Berlin")
    assert old.source_text == "" and normalize_event(event(), old).reason == NormalizationReason.MISSING_END_TIME
