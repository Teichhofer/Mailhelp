"""Telegram answers about dates and times: deterministic revisions and clarifications."""
from __future__ import annotations

from datetime import date, time

import pytest

from mailhelp.domain.processing import (
    TelegramDialogState,
)
from mailhelp.domain.proposal import (
    Proposal,
    ProposalRevisionDelta,
    ProposalStatus,
    apply_proposal_revision,
)
from mailhelp.domain.revision_errors import ContradictoryRevision
from mailhelp.persistence.storage import JsonStore
from mailhelp.processing.analysis import (
    validate_revision_successor,
)
from mailhelp.telegram import (
    deterministic_classification_revision,
    deterministic_temporal_revision,
    format_proposal,
    normalize_deterministic_temporal_answer,
    parse_deterministic_temporal_answer,
)
from tests.fakes.shared_telegram_dialog import (
    OperationallyFailingRevisionService as OperationallyFailingRevisionService,
)
from tests.fakes.shared_telegram_dialog import (
    RevisionService,
    controller,
    proposal,
)


def test_telegram_date_only_successor_cannot_become_all_day():
    original = proposal(kind="event", status="needs_clarification",
                        open_questions=["Wann beginnt der Termin?"],
                        known_temporal_facts={"date": "2026-10-21"})
    candidate = {**original.model_dump(mode="json"), "version": 2,
                 "known_temporal_facts": None, "all_day": True,
                 "start": "2026-10-21", "end": "2026-10-22",
                 "open_questions": [], "status": "pending_confirmation"}
    with pytest.raises(ContradictoryRevision, match="Ganztagsevidenz"):
        validate_revision_successor(original, candidate)








def test_deterministic_start_revision_uses_validated_day_without_llm(tmp_path):
    class Normalized(RevisionService):
        def interpret_telegram_answer(self, item, question, answer):
            return "interpret", type("Interpretation", (), {
                "usable": True, "normalized_answer": "21.10.2026 um 12 Uhr",
                "reason": "eindeutig"})()
        def revise_proposal(self, item, question, answer):
            raise AssertionError("Für die eindeutige Zeit darf kein Revisions-LLM laufen")

    with JsonStore(tmp_path) as store:
        item = proposal(kind="event", status="needs_clarification",
                        open_questions=["Wann beginnt der Termin?"],
                        known_temporal_facts={"date": "2026-10-21"},
                        temporal_fact={"raw_text": "21.10.26",
                                       "normalized_date": "2026-10-21",
                                       "year_source": "telegram", "status": "resolved"})
        c, transport, log = controller(store, revision_service=Normalized())
        c.revisions.configured_timezone = "Europe/Berlin"
        c.persist(item)
        store.save("telegram-dialog", TelegramDialogState(
            mail_id=item.source_mail_id, proposal_id=item.id,
            version=1).model_dump(mode="json"))
        c.revisions.answer("21.10.26 12 Uhr")
        saved = store.load_model("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1", Proposal)
        assert saved.version == 2
        assert saved.known_temporal_facts.start.isoformat() == "2026-10-21T12:00:00+02:00"
        assert saved.open_questions == ["Wann endet der Termin?"]
        assert "verzögert" not in transport.sent[-1][1]
        applied = next(event for event in log.events
                       if event[0][2] == "proposal_revision_delta_applied")
        assert applied[1]["previous_version"] == 1
        assert applied[1]["new_version"] == 2


@pytest.mark.parametrize("answer", [
    "Neu anlegen",
    "Als neuen Termin anlegen",
    "Bitte stattdessen einen neuen Termin erstellen",
])
def test_change_without_existing_event_requires_explicit_create_fallback(tmp_path, answer):
    class NoLlm(RevisionService):
        def interpret_telegram_answer(self, item, question, authorized_answer):
            raise AssertionError("Eindeutige Ablehnung darf nicht zum Interpretations-LLM")

        def revise_proposal(self, item, question, normalized_answer):
            raise AssertionError("Eindeutige Ablehnung darf nicht zum Revisions-LLM")

    with JsonStore(tmp_path) as store:
        question = "Welcher bestehende Eintrag soll geändert werden?"
        item = proposal(
            kind="event", classification="change", status="needs_clarification",
            open_questions=[question], target="primary",
            start="2026-10-02T14:00:00+02:00",
            end="2026-10-02T15:00:00+02:00",
        )
        dialog, transport, log = controller(store, revision_service=NoLlm())
        dialog.persist(item)
        store.save("telegram-dialog", TelegramDialogState(
            mail_id=item.source_mail_id, proposal_id=item.id,
            version=item.version).model_dump(mode="json"))

        dialog.revisions.answer(answer)

        revised = store.load_model(
            "proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1", Proposal)
        assert revised.version == 2
        assert revised.classification.value == "change"
        assert revised.explicit_create_fallback_confirmed is True
        assert revised.status == ProposalStatus.PENDING_CONFIRMATION
        assert revised.open_questions == []
        assert "Einordnung: Änderung eines bestehenden Eintrags" in transport.sent[-1][1]
        assert any(event[0][2] == "answer_revision_completed" for event in log.events)
        clarification = store.load(
            "clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1")
        assert clarification["proposal_revision_status"] == "completed"
        assert clarification["revision_attempts"] == 0


@pytest.mark.parametrize("answer", [
    "Nichts",
    "Keinen",
    "Kein bestehender Termin",
    "Nichts soll geändert werden",
    "Es gibt keinen bestehenden Termin",
    "Alles ist korrekt",
    "Den Jour fixe vom letzten Freitag",
    "Vielleicht keinen",
    "Der bestehende Termin soll nicht geändert werden, sondern abgesagt werden",
])
def test_change_answer_is_only_reclassified_for_closed_unambiguous_phrases(answer):
    question = "Welcher bestehende Eintrag soll geändert werden?"
    item = proposal(classification="change", status="needs_clarification",
                    open_questions=[question])
    assert deterministic_classification_revision(item, question, answer) is None


def test_no_existing_event_rule_requires_change_question_and_classification():
    change = proposal(classification="change", status="needs_clarification",
                      open_questions=["Welche Änderung?"])
    assert deterministic_classification_revision(
        change, "Welche Änderung?", "Nichts") is None
    new = proposal(open_questions=["Welcher bestehende Eintrag soll geändert werden?"],
                   status="needs_clarification")
    assert deterministic_classification_revision(
        new, new.open_questions[0], "Nichts") is None


def test_deterministic_full_interval_bypasses_interpretation_and_is_idempotent(tmp_path):
    service = RevisionService()
    with JsonStore(tmp_path) as store:
        item = proposal(
            kind="event", status="needs_clarification",
            open_questions=["Wann beginnt der Termin?"],
            known_temporal_facts={"date": "2026-09-23"},
            temporal_fact={"raw_text": "23.09.2026", "normalized_date": "2026-09-23",
                           "year_source": "explicit_mail", "status": "resolved"},
        )
        c, _, _ = controller(store, revision_service=service)
        c.revisions.configured_timezone = "Europe/Berlin"
        c.persist(item)
        store.save("telegram-dialog", TelegramDialogState(
            mail_id=item.source_mail_id, proposal_id=item.id,
            version=item.version).model_dump(mode="json"))

        c.revisions.answer("23.09.2026 9:00 bis 10uhr")
        revised = store.load_model(
            "proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1", Proposal)

        assert service.calls == []
        assert revised.start.isoformat() == "2026-09-23T09:00:00+02:00"
        assert revised.end.isoformat() == "2026-09-23T10:00:00+02:00"
        assert revised.temporal_fact == item.temporal_fact
        assert revised.version == 2

        # Neither startup recovery nor replaying the now stale answer creates a
        # second successor or invokes the LLM.
        c.revisions.resume()
        c.revisions.answer("23.09.2026 9:00 bis 10uhr")
        repeated = store.load_model(
            "proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1", Proposal)
        assert repeated.version == 2
        assert service.calls == []


def test_deterministic_end_keeps_known_start_without_interpretation(tmp_path):
    service = RevisionService()
    with JsonStore(tmp_path) as store:
        item = proposal(
            kind="event", status="needs_clarification",
            open_questions=["Wann endet der Termin?"],
            known_temporal_facts={
                "date": "2026-09-23",
                "start": "2026-09-23T09:00:00+02:00",
            },
        )
        c, _, _ = controller(store, revision_service=service)
        c.revisions.configured_timezone = "Europe/Berlin"
        c.persist(item)
        store.save("telegram-dialog", TelegramDialogState(
            mail_id=item.source_mail_id, proposal_id=item.id,
            version=item.version).model_dump(mode="json"))

        c.revisions.answer("10 Uhr")
        revised = store.load_model(
            "proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1", Proposal)

        assert revised.start.isoformat() == "2026-09-23T09:00:00+02:00"
        assert revised.end.isoformat() == "2026-09-23T10:00:00+02:00"
        assert service.calls == []


def test_deterministic_contradictory_date_requests_concrete_confirmation(tmp_path):
    service = RevisionService()
    with JsonStore(tmp_path) as store:
        item = proposal(
            kind="event", status="needs_clarification",
            open_questions=["Wann beginnt der Termin?"],
            known_temporal_facts={"date": "2026-09-23"},
        )
        c, transport, _ = controller(store, revision_service=service)
        c.revisions.configured_timezone = "Europe/Berlin"
        c.persist(item)
        store.save("telegram-dialog", TelegramDialogState(
            mail_id=item.source_mail_id, proposal_id=item.id,
            version=item.version).model_dump(mode="json"))

        c.revisions.answer("2026-09-24 09 Uhr")

        assert service.calls == []
        assert "2026-09-23" in transport.sent[-1][1]
        assert "Bitte bestätige" in transport.sent[-1][1]
        state = store.load("clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1")
        assert state["interpretation_status"] == "completed"
        assert state["answer_status"] == "invalid"
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["version"] == 1


def test_mail_start_cannot_be_reinterpreted_as_end_and_gets_targeted_question(tmp_path):
    service = RevisionService()
    with JsonStore(tmp_path) as store:
        item = proposal(
            kind="event", status="needs_clarification",
            open_questions=["Wann endet der Termin?"],
            known_temporal_facts={
                "date": "2026-10-03", "start": "2026-10-03T10:00:00+02:00"},
        )
        c, transport, _ = controller(store, revision_service=service)
        c.revisions.configured_timezone = "Europe/Berlin"
        c.persist(item)
        store.save("telegram-dialog", TelegramDialogState(
            mail_id=item.source_mail_id, proposal_id=item.id,
            version=item.version).model_dump(mode="json"))

        c.revisions.answer("3.10.2026 10 Uhr")

        assert service.calls == []
        assert "10:00 Uhr ist bereits als Beginn belegt" in transport.sent[-1][1]
        state = store.load("clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1")
        assert (state["interpretation_status"], state["answer_status"]) == (
            "completed", "invalid")
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["version"] == 1


def test_ambiguous_local_clock_gets_concrete_temporal_clarification(tmp_path):
    with JsonStore(tmp_path) as store:
        item = proposal(
            kind="event", status="needs_clarification",
            open_questions=["Wann beginnt der Termin?"],
            known_temporal_facts={"date": "2026-10-25"},
        )
        c, transport, _ = controller(store, revision_service=RevisionService())
        c.revisions.configured_timezone = "Europe/Berlin"
        c.persist(item)
        store.save("telegram-dialog", TelegramDialogState(
            mail_id=item.source_mail_id, proposal_id=item.id,
            version=item.version).model_dump(mode="json"))

        c.revisions.answer("25.10.2026 2:30 Uhr")

        assert "Bitte bestätige Datum und Uhrzeit konkret" in transport.sent[-1][1]


def test_deterministic_date_only_and_context_requirements():
    date_question = proposal(
        kind="event", status="needs_clarification",
        open_questions=["Welches Datum hat der Termin?"],
        known_temporal_facts=None,
    )
    dated = deterministic_temporal_revision(
        date_question, date_question.open_questions[0], "2026-09-23", "UTC")
    assert dated.known_temporal_facts.date == date(2026, 9, 23)
    assert dated.start is None
    assert dated.end is None

    time_question = proposal(
        kind="event", status="needs_clarification",
        open_questions=["Wann beginnt der Termin?"],
        known_temporal_facts=None,
    )
    assert deterministic_temporal_revision(
        time_question, time_question.open_questions[0], "9 Uhr", "UTC") is None

    overnight = deterministic_temporal_revision(
        date_question, date_question.open_questions[0],
        "23.09.2026 23 Uhr bis 1 Uhr", "Europe/Berlin")
    assert overnight.end.date() == date(2026, 9, 24)
    assert overnight.end > overnight.start


def test_reported_date_time_answer_retains_start_fact_and_uses_duration():
    item = proposal(
        kind="event", status="needs_clarification", duration_minutes=30,
        open_questions=["Wann beginnt der Termin?"],
        temporal_fact={"raw_text": None, "normalized_date": None,
                       "year_source": "unknown", "status": "unresolved"},
    )
    revised = deterministic_temporal_revision(
        item, item.open_questions[0], "2026-09-25 11:00", "Europe/Berlin")
    assert revised.start.isoformat() == "2026-09-25T11:00:00+02:00"
    assert revised.end.isoformat() == "2026-09-25T11:30:00+02:00"
    assert revised.temporal_fact.normalized_date == date(2026, 9, 25)
    assert revised.temporal_fact.year_source == "telegram"
    assert revised.open_questions == []
    assert "🕒 25.09.2026, 11:00–11:30 Uhr" in format_proposal(revised, "Europe/Berlin")


def test_date_answer_combines_retained_mail_clock_without_assuming_upper_bound_end():
    item = proposal(
        kind="event", status="needs_clarification", duration_minutes=30,
        duration_is_upper_bound=True,
        open_questions=["Welches konkrete Datum ist mit „Samstag, 3. Oktober“ gemeint?"],
        known_temporal_facts={"start_time": "10:00:00"},
        temporal_fact={"raw_text": "Samstag, 3. Oktober", "normalized_date": None,
                       "year_source": "unknown", "status": "unresolved"},
    )

    revised = deterministic_temporal_revision(
        item, item.open_questions[0], "2026-10-03", "Europe/Berlin")

    assert revised.start is None and revised.end is None and not revised.all_day
    assert revised.known_temporal_facts.date == date(2026, 10, 3)
    assert revised.known_temporal_facts.start.isoformat() == "2026-10-03T10:00:00+02:00"
    assert revised.open_questions == ["Wann endet der Termin?"]
    assert "🕒 03.10.2026, 10:00 Uhr (höchstens 30 Min.)" in format_proposal(revised, "Europe/Berlin")


def test_today_is_resolved_from_explicit_context():
    parsed = parse_deterministic_temporal_answer(
        "Heute 11uhr", date(2026, 9, 25))
    assert parsed.date == date(2026, 9, 25)
    assert parsed.start == time(11, 0)
    assert parsed.end is None
    assert parse_deterministic_temporal_answer("Heute 11uhr") is None
    date_only = parse_deterministic_temporal_answer(
        "heute", date(2026, 9, 25))
    assert date_only.model_dump() == {
            "date": date(2026, 9, 25), "start": None, "end": None}
    assert normalize_deterministic_temporal_answer(date_only) == "2026-09-25"
    ranged = parse_deterministic_temporal_answer(
        "Heute 11:00 bis 12 Uhr", date(2026, 9, 25))
    assert ranged.start == time(11, 0)
    assert ranged.end == time(12, 0)
    assert normalize_deterministic_temporal_answer(parsed) == "2026-09-25 11:00"
    assert normalize_deterministic_temporal_answer(ranged) == (
        "2026-09-25 11:00 bis 12:00")
    time_only = parse_deterministic_temporal_answer("11 Uhr")
    assert normalize_deterministic_temporal_answer(time_only) == "11:00"


def test_formatting_shows_retained_incomplete_start_and_duration():
    item = proposal(
        kind="event", status="needs_clarification", duration_minutes=30,
        open_questions=["Wann endet der Termin?"],
        known_temporal_facts={
            "date": "2026-09-25", "start": "2026-09-25T11:00:00+02:00"})
    text = format_proposal(item, "Europe/Berlin")
    assert "🕒 25.09.2026, 11:00 Uhr (30 Min.)" in text


def test_temporal_date_delta_rejects_conflict_and_preserves_existing_storage():
    existing = proposal(
        kind="event", status="needs_clarification",
        open_questions=["Welches Datum hat der Termin?"],
        known_temporal_facts={"date": "2026-09-23"},
    )
    with pytest.raises(ValueError, match="temporal_date widerspricht"):
        apply_proposal_revision(existing, ProposalRevisionDelta(
            answered_question=existing.open_questions[0],
            changes={"temporal_date": "2026-09-24"},
        ))

    same = apply_proposal_revision(existing, ProposalRevisionDelta(
        answered_question=existing.open_questions[0],
        changes={"temporal_date": "2026-09-23"},
    ))
    assert same.known_temporal_facts == existing.known_temporal_facts


@pytest.mark.parametrize("normalized", [
    "09.10.2026, 17:30 Uhr",
    "2026-10-09 17:30",
    "2026-10-09T17:30 Uhr",
])
def test_deterministic_end_revision_accepts_normalized_time_formats(normalized):
    item = proposal(
        kind="event", status="needs_clarification",
        open_questions=["Wann endet der Termin?"],
        start="2026-10-09T16:00:00+02:00", end=None,
        temporal_fact={"raw_text": "09. Oktober 2026",
                       "normalized_date": "2026-10-09",
                       "year_source": "explicit_mail", "status": "resolved"},
    )

    revised = deterministic_temporal_revision(
        item, item.open_questions[0], normalized, "Europe/Berlin")

    assert revised is not None
    assert revised.end.isoformat() == "2026-10-09T17:30:00+02:00"
    assert revised.status == ProposalStatus.PENDING_CONFIRMATION


def test_short_year_end_turns_date_only_draft_into_timed_clarification():
    item = proposal(
        kind="event", status="needs_clarification", all_day=True,
        start="2026-10-02", end=None,
        open_questions=["Wann endet der Termin?"],
        temporal_fact={"raw_text": "2. Oktober 2026", "normalized_date": "2026-10-02",
                       "year_source": "explicit_mail", "status": "resolved"},
    )

    revised = deterministic_temporal_revision(
        item, item.open_questions[0], "2.10.26 15uhr", "Europe/Berlin")

    assert revised.start is None
    assert revised.end.isoformat() == "2026-10-02T15:00:00+02:00"
    assert not revised.all_day
    assert revised.open_questions == ["Wann beginnt der Termin?"]
    assert revised.status == ProposalStatus.NEEDS_CLARIFICATION
    assert parse_deterministic_temporal_answer("2.10.26 15uhr") is None
    assert parse_deterministic_temporal_answer(
        "2.10.27 15uhr", date(2026, 10, 2)
    ) is None


@pytest.mark.parametrize(("end", "expected_offset"), [
    ("09.10.2026 um 23:00 Uhr", "+02:00"),
    ("10.10.2026 um 01:00 Uhr", "+02:00"),
    ("29.03.2026 um 01:00 Uhr", "+01:00"),
    ("25.10.2026 um 01:00 Uhr", "+02:00"),
])
def test_deterministic_end_accepts_same_or_next_day_across_dst(end, expected_offset):
    start_day = "2026-03-28" if end.startswith("29.03") else (
        "2026-10-24" if end.startswith("25.10") else "2026-10-09")
    item = proposal(kind="event", status="needs_clarification",
                    open_questions=["Wann endet der Termin?"],
                    known_temporal_facts={
                        "date": start_day,
                        "start": f"{start_day}T22:00:00+01:00" if start_day.endswith("03-28")
                        else f"{start_day}T22:00:00+02:00"})
    revised = deterministic_temporal_revision(
        item, item.open_questions[0], end, "Europe/Berlin")
    assert revised.end.isoformat().endswith(expected_offset)
    assert revised.end > revised.start


@pytest.mark.parametrize("end", [
    "09.10.2026 um 22:00 Uhr",
    "09.10.2026 um 21:59 Uhr",
    "11.10.2026 um 01:00 Uhr",
])
def test_deterministic_end_rejects_nonpositive_or_too_distant_end(end):
    item = proposal(kind="event", status="needs_clarification",
                    open_questions=["Wann endet der Termin?"],
                    known_temporal_facts={
                        "date": "2026-10-09",
                        "start": "2026-10-09T22:00:00+02:00"})
    with pytest.raises((ContradictoryRevision, ValueError)):
        deterministic_temporal_revision(
            item, item.open_questions[0], end, "Europe/Berlin")


def test_deterministic_temporal_revision_rejects_wrong_day_and_dst_edges():
    item = proposal(kind="event", status="needs_clarification",
                    open_questions=["Wann beginnt der Termin?"],
                    known_temporal_facts={"date": "2026-10-21"})
    with pytest.raises(ContradictoryRevision, match="Termindatum"):
        deterministic_temporal_revision(
            item, item.open_questions[0], "21.10.2110 um 12 Uhr", "Europe/Berlin")
    assert deterministic_temporal_revision(
        proposal(open_questions=["Titel?"]), "Titel?", "21.10.2026 um 12 Uhr", "UTC") is None
    assert deterministic_temporal_revision(
        item, item.open_questions[0], "morgen mittag", "UTC") is None
    ambiguous = item.model_copy(update={
        "known_temporal_facts": item.known_temporal_facts.model_copy(
            update={"date": date(2026, 10, 25)})})
    with pytest.raises(ContradictoryRevision, match="Zeitumstellung"):
        deterministic_temporal_revision(
            ambiguous, ambiguous.open_questions[0], "25.10.2026 um 02:30 Uhr",
            "Europe/Berlin")
    nonexistent = item.model_copy(update={
        "known_temporal_facts": item.known_temporal_facts.model_copy(
            update={"date": date(2026, 3, 29)})})
    with pytest.raises(ContradictoryRevision, match="Zeitumstellung"):
        deterministic_temporal_revision(
            nonexistent, nonexistent.open_questions[0], "29.03.2026 um 02:30 Uhr",
            "Europe/Berlin")
