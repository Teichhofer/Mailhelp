"""Unit-Tests für die neuen Domänenmodelle und Invarianten von Mailhelp 1.3."""
from datetime import date, datetime, timezone
import pytest
from pydantic import ValidationError

from mailhelp.domain.proposal import (
    DuplicateMatchInfo,
    DuplicateSource,
    Proposal,
    ProposalClassification,
    ProposalCertainty,
    ProposalKind,
    ProposalResponsibility,
    ProposalRevisionChanges,
    ProposalStatus,
    required_revision_questions,
)
from mailhelp.domain.extraction import ExtractedAttachment, ParsedCalendarEvent
from mailhelp.domain.processing import ProcessingStage, ProcessingSteps


def sample_event_proposal(**kwargs) -> Proposal:
    base = {
        "id": "prop-1",
        "version": 1,
        "kind": ProposalKind.EVENT,
        "responsibility": ProposalResponsibility.USER,
        "certainty": ProposalCertainty.CERTAIN,
        "classification": ProposalClassification.NEW,
        "title": "Projektbesprechung",
        "description": "Details zum Release",
        "evidence": "Termin am 12.10. um 10 Uhr",
        "source_mail_id": "a" * 24,
        "start": datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc),
        "end": datetime(2026, 10, 12, 11, 0, tzinfo=timezone.utc),
        "target": "primary",
        "status": ProposalStatus.PENDING_CONFIRMATION,
    }
    base.update(kwargs)
    return Proposal.model_validate(base)


def sample_task_proposal(**kwargs) -> Proposal:
    base = {
        "id": "prop-task-1",
        "version": 1,
        "kind": ProposalKind.TASK,
        "responsibility": ProposalResponsibility.USER,
        "certainty": ProposalCertainty.CERTAIN,
        "classification": ProposalClassification.NEW,
        "title": "Bericht schreiben",
        "evidence": "Bitte bis morgen erledigen",
        "source_mail_id": "b" * 24,
        "due": date(2026, 10, 15),
        "target": "inbox",
        "status": ProposalStatus.PENDING_CONFIRMATION,
    }
    base.update(kwargs)
    return Proposal.model_validate(base)


def test_duplicate_match_info_and_already_exists_status():
    match = DuplicateMatchInfo(
        source=DuplicateSource.GOOGLE_CALENDAR,
        external_id="cal-123",
        external_link="https://calendar.google.com/event?eid=123",
        matched_title="Projektbesprechung",
        matched_time=datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc),
        similarity_score=1.0,
        details="Exakte Übereinstimmung",
    )
    assert match.source == DuplicateSource.GOOGLE_CALENDAR
    assert match.external_id == "cal-123"

    prop = sample_event_proposal(
        status=ProposalStatus.ALREADY_EXISTS,
        duplicate_match=match,
    )
    assert prop.status == ProposalStatus.ALREADY_EXISTS
    assert prop.duplicate_match is not None
    assert prop.duplicate_match.matched_title == "Projektbesprechung"


def test_already_exists_rejects_missing_match_info():
    with pytest.raises(ValidationError, match="Duplikat-Informationen"):
        sample_event_proposal(
            status=ProposalStatus.ALREADY_EXISTS,
            duplicate_match=None,
        )


def test_already_exists_rejects_open_questions():
    match = DuplicateMatchInfo(
        source=DuplicateSource.ACTION_LEDGER,
        matched_title="Projektbesprechung",
    )
    with pytest.raises(ValidationError, match="offenen Fragen"):
        sample_event_proposal(
            status=ProposalStatus.ALREADY_EXISTS,
            duplicate_match=match,
            open_questions=["Wann endet der Termin?"],
        )


def test_update_proposal_fields_and_validation():
    # Updating an event is valid
    update_prop = sample_event_proposal(
        classification=ProposalClassification.CHANGE,
        target_event_id="existing-event-99",
        time_changes=["Beginn 10:00 → 14:00 Uhr"],
    )
    assert update_prop.is_creatable is True
    assert update_prop.target_event_id == "existing-event-99"
    assert update_prop.time_changes == ["Beginn 10:00 → 14:00 Uhr"]

    # Cancelling an event is valid
    cancel_prop = sample_event_proposal(
        classification=ProposalClassification.CANCELLATION,
        target_event_id="existing-event-99",
        is_cancellation=True,
    )
    assert cancel_prop.is_creatable is True
    assert cancel_prop.is_cancellation is True

    # Task cannot have target_event_id
    with pytest.raises(ValidationError, match="Nur Termine unterstützen"):
        sample_task_proposal(target_event_id="event-123")

    # Cancellation requires target_event_id
    with pytest.raises(ValidationError, match="Ziel-Event-ID"):
        sample_event_proposal(
            classification=ProposalClassification.CANCELLATION,
            is_cancellation=True,
            target_event_id=None,
            status=ProposalStatus.NEEDS_CLARIFICATION,
            open_questions=["Welcher bestehende Eintrag soll storniert werden?"],
        )


def test_required_revision_questions_with_target_event_id():
    # Without target_event_id, CHANGE asks for existing entry
    change_without_id = sample_event_proposal(
        classification=ProposalClassification.CHANGE,
        status=ProposalStatus.NEEDS_CLARIFICATION,
        open_questions=["Welcher bestehende Eintrag soll geändert werden?"],
        target_event_id=None,
    )
    questions = required_revision_questions(change_without_id)
    assert "Welcher bestehende Eintrag soll geändert werden?" in questions

    # With target_event_id, CHANGE does NOT ask
    change_with_id = sample_event_proposal(
        classification=ProposalClassification.CHANGE,
        target_event_id="event-1",
    )
    assert "Welcher bestehende Eintrag soll geändert werden?" not in required_revision_questions(change_with_id)

    # Without target_event_id, CANCELLATION asks
    cancel_without_id = sample_event_proposal(
        classification=ProposalClassification.CANCELLATION,
        status=ProposalStatus.NEEDS_CLARIFICATION,
        open_questions=["Welcher bestehende Eintrag soll storniert werden?"],
        target_event_id=None,
    )
    assert "Welcher bestehende Eintrag soll storniert werden?" in required_revision_questions(cancel_without_id)

    # With target_event_id, CANCELLATION does NOT ask
    cancel_with_id = sample_event_proposal(
        classification=ProposalClassification.CANCELLATION,
        target_event_id="event-1",
    )
    assert "Welcher bestehende Eintrag soll storniert werden?" not in required_revision_questions(cancel_with_id)


def test_proposal_revision_changes_with_update_fields():
    changes = ProposalRevisionChanges(
        target_event_id="cal-42",
        time_changes=["Beginn geändert"],
        is_cancellation=True,
    )
    assert changes.target_event_id == "cal-42"
    assert changes.time_changes == ["Beginn geändert"]
    assert changes.is_cancellation is True


def test_extracted_attachment_model():
    att = ExtractedAttachment(
        filename="Protokoll.pdf",
        content_type="application/pdf",
        size_bytes=1024,
        text="Beschluss vom 10. Oktober",
        extraction_status="success",
        character_count=25,
    )
    assert att.filename == "Protokoll.pdf"
    assert att.extraction_status == "success"
    assert att.character_count == 25


def test_parsed_calendar_event_model():
    cal_event = ParsedCalendarEvent(
        uid="uid-1234@example.org",
        sequence=2,
        summary="Treffen",
        description="Besprechung",
        start=datetime(2026, 10, 15, 14, 0, tzinfo=timezone.utc),
        end=datetime(2026, 10, 15, 15, 0, tzinfo=timezone.utc),
        all_day=False,
        location="Raum 1",
        status="CONFIRMED",
    )
    assert cal_event.uid == "uid-1234@example.org"
    assert cal_event.sequence == 2
    assert cal_event.summary == "Treffen"
    assert cal_event.status == "CONFIRMED"


def test_processing_steps_and_stages_duplicate_precheck():
    steps = ProcessingSteps()
    assert steps.duplicate_precheck == "pending"
    assert ProcessingStage.DUPLICATE_PRECHECK == "duplicate_precheck"
