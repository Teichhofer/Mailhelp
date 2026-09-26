from __future__ import annotations

from datetime import date, time
import httpx
import pytest
from unittest.mock import patch
from pydantic import ValidationError

from mailhelp.adapter import PermanentError, UncertainWriteError
from mailhelp.analysis import (Analyzer, ContradictoryRevision, LlmInvalidJson,
                               LlmProviderResponseInvalid,
                               LlmSchemaValidationFailed,
                               LlmTokenLimitExceeded, validate_revision_successor)
from mailhelp.models import (ActionLedger, ActionLedgerEntry, AnswerStatus, MailState, Proposal,
                             ProposalNotification,
                             ProposalClarificationState, ProposalRevisionDelta,
                             ProposalRevisionStatus, ProposalStatus,
                             QuestionStatus, RelevanceDialog, RelevanceDialogStatus,
                             TelegramDialogState, apply_proposal_revision)
from mailhelp.orchestrator import Orchestrator
from mailhelp.storage import JsonStore
from mailhelp.telegram import (
    Decision, DecisionAction,
    TelegramCallbackQuery,
    TelegramChatNotFoundError,
    TelegramClient,
    TelegramDialogController,
    TelegramMessage,
    TelegramUpdate,
    numbered_message_parts,
    format_proposal,
    deterministic_classification_revision,
    normalize_deterministic_temporal_answer,
    parse_deterministic_temporal_answer,
    deterministic_temporal_revision,
    validate_callback_data,
    validate_callback_markup,
)
from mailhelp.application import _state_directory
from mailhelp.config import OutputTokenRetry, Settings
from mailhelp.integrations import CalendarFileWriter
from mailhelp.openrouter import ProviderResponseInvalid
from test_core import prompt_config


def proposal(**changes):
    data = {"id": "p1", "version": 1, "kind": "task", "responsibility": "user", "certainty": "certain", "classification": "new", "title": "Aufgabe", "description": "Text", "evidence": "Beleg", "source_mail_id": "aaaaaaaaaaaaaaaaaaaaaaaa", "target": "inbox"}
    if "status" not in changes and (changes.get("open_questions") or changes.get("responsibility") not in {None, "user"}
                                    or changes.get("certainty") not in {None, "certain"}
                                    or changes.get("classification") not in {None, "new"}):
        data["status"] = "needs_clarification"
    data.update(changes)
    return Proposal.model_validate(data)


def message(update_id, text="Antwort", user=1, chat=2):
    return {"update_id": update_id, "message": {"message_id": update_id, "from": {"id": user}, "chat": {"id": chat}, "text": text}}


def callback(update_id, data, user=1, chat=2):
    return {"update_id": update_id, "callback_query": {"id": f"c{update_id}", "from": {"id": user, "is_bot": False, "first_name": "Ada"}, "chat_instance": "irrelevant", "message": {"message_id": 1, "from": {"id": 99, "is_bot": True, "first_name": "Mailhelp"}, "chat": {"id": chat, "type": "private"}, "date": 1_789_000_000, "text": "buttons", "reply_markup": {"inline_keyboard": []}}, "data": data}}


class Telegram:
    def __init__(self, updates=()):
        self.updates = list(updates); self.polls=[]; self.sent=[]; self.answered=[]; self.documents=[]; self.removed=[]
    def poll(self, offset, timeout=None): self.polls.append(offset); return self.updates
    def send(self, chat, text, reply_markup=None): self.sent.append((chat,text,reply_markup))
    def answer_callback(self, callback_id, text): self.answered.append((callback_id,text))
    def remove_inline_keyboard(self, chat_id, message_id): self.removed.append((chat_id,message_id))
    def send_document(self, chat_id, filename, content, caption=None):
        self.documents.append((chat_id, filename, content, caption))


class Logger:
    def __init__(self): self.events=[]
    def event(self, *args, **fields): self.events.append((args,fields))


class RevisionService:
    def __init__(self): self.calls=[]
    def interpret_telegram_answer(self, item, question, answer):
        self.calls.append(("interpret", item, question, answer))
        return "interpret-call", type("Interpretation", (), {
            "usable": True, "normalized_answer": answer, "reason": "passt"})()
    def clarify_telegram_answer(self, question, answer, reason, *, current_date=None):
        self.calls.append(("clarify", question, answer, reason, current_date))
        return "clarify-call", type("Clarification", (), {
            "message": f"Bitte konkreter beantworten: {question}"})()
    def revise_proposal(self, item, question, answer):
        self.calls.append((item,question,answer))
        remaining=item.open_questions[1:]
        return "revision-call", Proposal.model_validate({**item.model_dump(),
            "version":item.version+1, "description":answer,
            "open_questions":remaining,
            "status":"needs_clarification" if remaining else "pending_confirmation"})


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


class FailingRevisionService(RevisionService):
    def revise_proposal(self, item, question, answer): raise ValueError("contradiction")


class OperationallyFailingRevisionService(RevisionService):
    def revise_proposal(self, item, question, answer): raise RuntimeError("provider unavailable")


class UnusableAnswerService(RevisionService):
    def interpret_telegram_answer(self, item, question, answer):
        self.calls.append(("interpret", item, question, answer))
        return "interpret-call", type("Interpretation", (), {
            "usable": False, "normalized_answer": None, "reason": "Datum fehlt"})()


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
        assert "Einordnung: change" in transport.sent[-1][1]
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
    assert "Beginn: 2026-09-25T11:00:00+02:00" in format_proposal(
        revised, "Europe/Berlin")


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
    assert "Dauer: höchstens 30 Minuten" in format_proposal(revised, "Europe/Berlin")


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
    assert "Beginn: 2026-09-25T11:00:00+02:00" in text
    assert "Dauer: 30 Minuten" in text


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


def test_validation_failure_log_contains_safe_structured_details(tmp_path):
    with JsonStore(tmp_path) as store:
        c, _, log = controller(store)
        with pytest.raises(ValidationError) as caught:
            Proposal.model_validate({})
        c.revisions._log_revision_failure("a" * 24, "p1", 1, caught.value,
                                ProposalRevisionStatus.RETRY_REQUIRED)
        fields = log.events[-1][1]
        assert fields["validation_errors"][0]["location"] == ["id"]
        assert fields["validation_errors"][0]["type"] == "missing"
        assert "input" not in repr(fields["validation_errors"])


class InterpretationErrorService(RevisionService):
    def __init__(self, error):
        super().__init__(); self.error = error
    def interpret_telegram_answer(self, item, question, answer):
        raise self.error


def controller(store, updates=(), writers=None, test_mode=False, revision_service=None):
    transport=Telegram(updates); log=Logger()
    service=revision_service if revision_service is not None else RevisionService()
    return TelegramDialogController(store,transport,1,2,log,writers,test_mode,"UTC",service),transport,log


def test_write_attempt_references_are_linked_to_mail(tmp_path):
    mail_id="a"*24
    with JsonStore(tmp_path/"references") as store:
        state=MailState(id=mail_id,config_fingerprint="f"*64,
                        imap={"account_id":"0"*24,"folder":"INBOX","uidvalidity":1,"uid":1})
        store.save("mail-"+mail_id,state.model_dump(mode="json"))
        dialog,_,_=controller(store)
        task=proposal(source_mail_id=mail_id,status="writing")
        dialog.persist(task)
        dialog.persist(task)
        dialog.persist(proposal(id="event",kind="event",source_mail_id=mail_id,status="uncertain",
                                start="2026-01-01T10:00:00Z",end="2026-01-01T11:00:00Z"))
        loaded=store.load_model("mail-"+mail_id,MailState)
        assert [(item.proposal_id,item.service,item.idempotency_key) for item in loaded.write_attempts] == [
            ("p1","todoist",f"mailhelp:{mail_id}:p1:v1"),
            ("event","google_calendar",f"mailhelp:{mail_id}:event:v1"),
        ]


@pytest.mark.parametrize(("status", "has_attempt"), [
    (ProposalStatus.REJECTED, False),
    (ProposalStatus.CREATED, True),
    (ProposalStatus.SIMULATED, False),
    (ProposalStatus.FAILED, True),
    (ProposalStatus.UNCERTAIN, True),
])
def test_persist_synchronizes_every_terminal_result_with_mail_state(tmp_path, status, has_attempt):
    mail_id = "a" * 24
    original = proposal(source_mail_id=mail_id)
    state = MailState(
        id=mail_id, config_fingerprint="f" * 64,
        imap={"account_id":"0"*24,"folder":"INBOX","uidvalidity":1,"uid":1},
        proposals=[original], created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )
    changes = {"version": 2, "status": status}
    if status == ProposalStatus.CREATED:
        changes.update(external_id="external-1", external_link="https://example.test/item")
    current = original.model_copy(update=changes)
    with JsonStore(tmp_path / status.value) as store:
        store.save("mail-" + mail_id, state.model_dump(mode="json"))
        dialog,_,_=controller(store)
        dialog.persist(current)
        dialog.persist(current)
        loaded=store.load_model("mail-" + mail_id, MailState)
        assert loaded.proposals[0] == current
        assert loaded.updated_at > state.updated_at
        assert len(loaded.write_attempts) == int(has_attempt)
        if status == ProposalStatus.CREATED:
            assert loaded.proposals[0].external_id == "external-1"
            assert loaded.proposals[0].external_link == "https://example.test/item"


def test_persist_order_and_restart_repair_use_current_proposal(tmp_path):
    class RecordingStore(JsonStore):
        def __init__(self, directory): super().__init__(directory); self.saved=[]
        def save(self, name, value): self.saved.append(name); super().save(name, value)

    mail_id="a"*24
    initial=proposal(source_mail_id=mail_id)
    with RecordingStore(tmp_path) as store:
        state=MailState(id=mail_id,config_fingerprint="f"*64,
                        imap={"account_id":"0"*24,"folder":"INBOX","uidvalidity":1,"uid":1},
                        proposals=[initial])
        store.save("mail-"+mail_id,state.model_dump(mode="json")); store.saved.clear()
        created=initial.model_copy(update={"status":ProposalStatus.CREATED,
                                           "external_id":"external-1",
                                           "external_link":"https://example.test/item"})
        dialog,_,_=controller(store); dialog.persist(created)
        assert store.saved == [f"proposal-{mail_id}-p1-v1", f"proposal-{mail_id}-p1",
                               f"mail-{mail_id}", "action-ledger"]

        # Simulate a crash between the second and third writes by restoring a
        # stale embedding.  Startup repairs it from the current proposal file.
        store.save("mail-"+mail_id,state.model_dump(mode="json"))
        restarted,_,_=controller(store); restarted.poll_once()
        repaired=store.load_model("mail-"+mail_id,MailState).proposals[0]
        assert repaired.status == ProposalStatus.CREATED
        assert repaired.external_id == "external-1"
        assert repaired.external_link == "https://example.test/item"


def test_revision_replaces_notification_version_and_validates_mail_state(tmp_path):
    mail_id = "a" * 24
    original = proposal(source_mail_id=mail_id, status="needs_clarification",
                        open_questions=["Welches Datum?"])
    unrelated = proposal(id="p2", source_mail_id=mail_id)
    state = MailState(
        id=mail_id, config_fingerprint="f" * 64,
        imap={"account_id":"0"*24,"folder":"INBOX","uidvalidity":1,"uid":1},
        proposals=[unrelated, original],
        proposal_notifications=[ProposalNotification(
            proposal_id=original.id, proposal_version=1, status="completed")],
    )
    revised = proposal(source_mail_id=mail_id, version=2)
    with JsonStore(tmp_path) as store:
        store.save("mail-" + mail_id, state.model_dump(mode="json"))
        dialog, transport, _ = controller(store)

        dialog.persist(revised)

        saved = store.load_model("mail-" + mail_id, MailState)
        assert saved.proposals == [unrelated, revised]
        assert saved.proposal_notifications == [ProposalNotification(
            proposal_id=revised.id, proposal_version=2, status="pending")]
        dialog.send_proposal(revised)
        delivered = store.load_model("mail-" + mail_id, MailState)
        assert delivered.proposal_notifications[0].status == "completed"
        assert len(transport.sent) == 1


def test_restart_delivers_persisted_revision_before_marking_it_completed(tmp_path):
    mail_id = "a" * 24
    original = proposal(source_mail_id=mail_id, status="needs_clarification",
                        open_questions=["Welches Datum?"])
    state = MailState(
        id=mail_id, config_fingerprint="f" * 64,
        imap={"account_id":"0"*24,"folder":"INBOX","uidvalidity":1,"uid":1},
        proposals=[original],
        proposal_notifications=[ProposalNotification(
            proposal_id=original.id, proposal_version=1, status="completed")],
    )
    answered = ProposalClarificationState(
        mail_id=mail_id, proposal_id=original.id, version=1,
        question="Welches Datum?", question_status=QuestionStatus.ANSWERED,
        answer_status=AnswerStatus.VALID, normalized_answer="2026-10-21",
        proposal_revision_status=ProposalRevisionStatus.RETRY_REQUIRED)
    name = "clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1"
    with JsonStore(tmp_path) as store:
        store.save("mail-" + mail_id, state.model_dump(mode="json"))
        first, _, _ = controller(store)
        first.persist(proposal(source_mail_id=mail_id, version=2))
        store.save(name, answered.model_dump(mode="json"))

        restarted, transport, _ = controller(store)
        mail = store.load_model("mail-" + mail_id, MailState)
        mail.proposal_notifications[0].status = "sending"
        store.save("mail-" + mail_id, mail.model_dump(mode="json"))
        restarted.revisions._revise_answered(answered)
        assert not transport.sent
        assert store.load(name)["proposal_revision_status"] == "retry_required"
        mail.proposal_notifications[0].status = "pending"
        store.save("mail-" + mail_id, mail.model_dump(mode="json"))
        restarted.revisions._revise_answered(answered)

        assert len(transport.sent) == 1
        assert store.load_model("mail-" + mail_id, MailState).proposal_notifications[0].status == "completed"
        assert store.load(name)["proposal_revision_status"] == "completed"
        restarted.revisions._revise_answered(answered)
        assert len(transport.sent) == 1


def test_created_action_is_booked_and_duplicate_needs_second_confirmation(tmp_path):
    first_mail, second_mail = "a" * 24, "b" * 24
    with JsonStore(tmp_path) as store:
        writer = Writer()
        dialog, telegram, _ = controller(store, writers={"todoist": writer})
        already_created = proposal(source_mail_id=first_mail, status="created",
                                   external_id="old-external")
        dialog.persist(already_created)
        dialog.persist(already_created)  # bookkeeping is idempotent
        candidate = proposal(source_mail_id=second_mail)
        dialog.persist(candidate)

        normal = Decision(mail_id=second_mail, proposal_id="p1", version=1,
                          action=DecisionAction.CONFIRM)
        assert "Doppelanlage" in dialog._decide(normal)
        assert writer.created == 0
        assert "Bereits angelegt" in telegram.sent[-1][1]
        markup = telegram.sent[-1][2]
        repeat = Decision.parse(markup["inline_keyboard"][0][0]["callback_data"], store)
        assert repeat.action == DecisionAction.CONFIRM_DUPLICATE

        assert "bestätigt" in dialog._decide(repeat)
        assert writer.created == 1
        assert store.load("proposal-" + second_mail + "-p1")["status"] == "created"
        ledger = store.load_model("action-ledger", ActionLedger)
        assert len(ledger.entries) == 2
        assert {item.external_id for item in ledger.entries} == {"old-external", "external-1"}


def test_duplicate_override_is_rejected_when_ledger_no_longer_matches(tmp_path):
    with JsonStore(tmp_path) as store:
        dialog, telegram, _ = controller(store, writers={"todoist": Writer()})
        item = proposal()
        dialog.persist(item)
        decision = Decision(mail_id=item.source_mail_id, proposal_id=item.id, version=1,
                            action=DecisionAction.CONFIRM_DUPLICATE)
        with pytest.raises(ValueError, match="veraltet"):
            dialog._decide(decision)
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["status"] == "pending_confirmation"


def test_action_ledger_rejects_duplicate_proposal_version():
    entry = ActionLedgerEntry(action_key="0" * 64, mail_id="a" * 24, proposal_id="p1",
                              proposal_version=1, kind="task", title="Aufgabe", target="inbox")
    with pytest.raises(ValidationError, match="doppelt verbucht"):
        ActionLedger(entries=[entry, entry])


class Writer:
    def __init__(self, found=None, error=None): self.found=found; self.error=error; self.created=0; self.reconciled=0; self.versions=[]
    def reconcile(self,key): self.reconciled+=1; return self.found
    def create(self,p,key):
        self.created+=1; self.versions.append(p.version)
        if self.error: raise self.error
        return {"id":"external-1","url":"https://example.test/item"}


def test_direct_decision_persists_confirmation_before_write(tmp_path):
    events=[]
    class OrderedStore(JsonStore):
        def save(self, name, value):
            super().save(name, value)
            if name == "proposal-aaaaaaaaaaaaaaaaaaaaaaaa-event" and value["status"] == "confirmed":
                events.append("confirmation persisted")
    class SlowWriter(Writer):
        def create(self, item, key):
            assert events == ["confirmation persisted"]
            events.append("external write")
            return super().create(item, key)

    with OrderedStore(tmp_path) as store:
        transport=Telegram()
        dialog=TelegramDialogController(store,transport,1,2,Logger(),
                                        {"google_calendar":SlowWriter()},False,"UTC",
                                        RevisionService())
        item=proposal(id="event",kind="event",status="pending_confirmation",
                      start="2026-01-01T10:00:00Z",end="2026-01-01T11:00:00Z")
        dialog.persist(item)
        dialog._decide(Decision(mail_id=item.source_mail_id,
                       proposal_id=item.id,version=item.version,
                       action=DecisionAction.CONFIRM))

    assert events[:2] == ["confirmation persisted", "external write"]


def test_strict_schemas_and_decisions():
    parsed=Decision.parse("proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:3:confirm")
    assert parsed.encode()=="proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:3:confirm"
    for bad in ("x", "proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:x:confirm", "proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:٣:confirm", "proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:1:bad"):
        with pytest.raises((ValueError,ValidationError)): Decision.parse(bad)
    transport=TelegramMessage.model_validate({"message_id":1,"from":{"id":1,"first_name":"Ada","is_bot":False},"chat":{"id":2,"type":"private"},"date":1_789_000_000,"text":"x","unknown":True})
    assert transport.model_dump(by_alias=True)=={"message_id":1,"from":{"id":1},"chat":{"id":2},"text":"x"}
    callback_model=TelegramCallbackQuery.model_validate({**callback(1,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:1:confirm")["callback_query"],"unknown":1})
    assert "unknown" not in callback_model.model_dump() and callback_model.sender.id == 1
    with pytest.raises(ValidationError): Decision.model_validate({"proposal_id":"p1","version":1,"action":"confirm","unknown":True})
    with pytest.raises(ValidationError): TelegramUpdate(update_id=1)
    with pytest.raises(ValidationError): TelegramUpdate.model_validate({**message(1),"callback_query":callback(1,"x")["callback_query"]})


def test_durable_callback_tokens_bound_every_field_and_survive_restart(tmp_path):
    item = Decision(mail_id="a" * 24, proposal_id="Z_" * 16, version=123456789,
                    action=DecisionAction.CONFIRM)
    with JsonStore(tmp_path) as store:
        encoded = item.encode(store)
        assert len(encoded.encode("utf-8")) <= 64
        assert Decision.parse(encoded, store) == item
    with JsonStore(tmp_path) as restarted:
        assert Decision.parse(encoded, restarted) == item
        for bad in ("decision:" + "0" * 32, encoded[:-1] + "g", "decision:short"):
            with pytest.raises((ValueError, ValidationError)):
                Decision.parse(bad, restarted)
        with pytest.raises(ValueError, match="Unbekannter"):
            Decision.parse(encoded)


def test_callback_token_collision_and_invalid_persisted_record(tmp_path):
    item = Decision(mail_id="a" * 24, proposal_id="p1", version=12,
                    action=DecisionAction.EDIT)
    with JsonStore(tmp_path) as store:
        store.save("telegram-callback-" + "1" * 32, item.model_dump(mode="json"))
        with patch("mailhelp.telegram._core.secrets.token_hex", side_effect=["1" * 32, "2" * 32]):
            value = item.encode(store)
        assert value == "decision:" + "2" * 32
        for token, record in (("3" * 32, ["broken"]),
                              ("4" * 32, {"action": 1})):
            store.save("telegram-callback-" + token, record)
            with pytest.raises(ValueError, match="Callback-Datensatz"):
                Decision.parse("decision:" + token, store)


def test_callback_data_byte_validation_and_legacy_limit():
    validate_callback_markup(None)
    validate_callback_markup({"inline_keyboard": [[{"text": "URL"}]]})
    validate_callback_data("x" * 64)
    for value in ("", "x" * 65, "ü" * 33):
        with pytest.raises(ValueError, match="1 bis 64 UTF-8-Bytes"):
            validate_callback_data(value)
    with pytest.raises(ValueError, match="Zeichenkette"):
        validate_callback_markup({"inline_keyboard": [[{"callback_data": 1}]]})
    too_long_legacy = "proposal:" + "a" * 24 + ":" + "p" * 32 + ":12:confirm"
    with pytest.raises(ValueError, match="UTF-8-Bytes"):
        Decision.parse(too_long_legacy)


@pytest.mark.parametrize(("changes", "labels", "actions"), [
    ({}, ["Bestätigen", "Ändern", "Verwerfen"],
     [DecisionAction.CONFIRM, DecisionAction.EDIT, DecisionAction.REJECT]),
    ({"open_questions": ["Bitte klären"]}, ["Klären", "Verwerfen"],
     [DecisionAction.EDIT, DecisionAction.REJECT]),
    ({"classification": "unsupported"}, ["Manuell prüfen", "Verwerfen"],
     [DecisionAction.EDIT, DecisionAction.REJECT]),
    ({"kind": "event", "start": "2026-05-10T10:00:00+02:00", "end": "2026-05-10T11:00:00+02:00"},
     ["Anlegen", "Verwerfen"], [DecisionAction.CONFIRM, DecisionAction.REJECT]),
])
def test_all_proposal_buttons_use_short_exactly_bound_tokens(tmp_path, changes, labels, actions):
    item = proposal(id="P_" * 16, version=123456789, **changes)
    with JsonStore(tmp_path) as store:
        dialog, transport, _ = controller(store)
        dialog.send_proposal(item)
        buttons = transport.sent[-1][2]["inline_keyboard"][0]
        assert [button["text"] for button in buttons] == labels
        for button, action in zip(buttons, actions, strict=True):
            value = button["callback_data"]
            assert 1 <= len(value.encode("utf-8")) <= 64
            assert Decision.parse(value, store) == Decision(
                mail_id=item.source_mail_id, proposal_id=item.id,
                version=item.version, action=action)


def test_pending_event_pauses_until_anlegen_or_verwerfen(tmp_path):
    item = proposal(kind="event", start="2026-05-10T10:00:00+02:00",
                    end="2026-05-10T11:00:00+02:00")
    with JsonStore(tmp_path) as store:
        dialog, transport, _ = controller(store)
        dialog.send_proposal(item)

        assert dialog.awaiting_decision()
        buttons = transport.sent[-1][2]["inline_keyboard"][0]
        assert [button["text"] for button in buttons] == ["Anlegen", "Verwerfen"]

        transport.updates = [callback(1, buttons[1]["callback_data"])]
        dialog.poll_once()
        assert not dialog.awaiting_decision()


def test_awaiting_decision_ignores_version_snapshots_and_supports_legacy_store(tmp_path):
    with JsonStore(tmp_path) as store:
        dialog, _, _ = controller(store)
        item = proposal()
        store.save(dialog._version_name(item.source_mail_id, item.id, item.version),
                   item.model_dump(mode="json"))
        assert not dialog.awaiting_decision()

    class LegacyStore:
        pass

    dialog, _, _ = controller(LegacyStore())
    dialog._open_relevance_dialogs = lambda: []
    assert not dialog.awaiting_decision()
    dialog._open_relevance_dialogs = lambda: [object()]
    assert dialog.awaiting_decision()


def test_paused_answer_is_operator_block_not_open_user_decision(tmp_path):
    item = proposal(status="needs_clarification", open_questions=["Wann?"])
    state = ProposalClarificationState(
        mail_id=item.source_mail_id, proposal_id=item.id, version=item.version,
        question="Wann?", question_status=QuestionStatus.ANSWERED,
        answer_status=AnswerStatus.VALID, authorized_answer="Antwort",
        normalized_answer="Antwort",
        proposal_revision_status=ProposalRevisionStatus.PAUSED,
    )
    with JsonStore(tmp_path) as store:
        dialog, _, _ = controller(store)
        dialog.persist(item)
        store.save(
            "clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1",
            state.model_dump(mode="json"),
        )

        assert not dialog.awaiting_decision()
        assert dialog.processing_blocked()

    class LegacyStore:
        pass

    dialog, _, _ = controller(LegacyStore())
    assert not dialog.processing_blocked()


def test_numbered_parts():
    parts=numbered_message_parts("sender@example.test","Ein Betreff","x"*150,100)
    assert len(parts)>1 and all(
        f"[Absender: sender@example.test · Teil {i}/{len(parts)}]\nBetreff: Ein Betreff\n" in part
        for i,part in enumerate(parts,1))
    with pytest.raises(ValueError): numbered_message_parts("","p","x")
    with pytest.raises(ValueError): numbered_message_parts("m","","x")
    with pytest.raises(ValueError): numbered_message_parts("m","p","x",31)


@pytest.mark.parametrize(("item", "expected"), [
    (proposal(description="", due=None), ["Typ: Aufgabe", "Beschreibung: —", "Fälligkeit: —"]),
    (proposal(kind="event", start="2026-05-10T10:00:00+02:00", end="2026-05-10T11:00:00+02:00", location="Raum 1", video_link="https://video.example.test/abc"),
     ["Typ: Termin", "Beginn: 2026-05-10T10:00:00+02:00", "Ganztägig: Nein", "Konfigurierte Zeitzone: Europe/Berlin", "Ort: Raum 1", "Videolink: https://video.example.test/abc"]),
    (proposal(kind="event", all_day=True, start="2026-05-10", end="2026-05-11", location=None),
     ["Ende: 2026-05-11", "Ganztägig: Ja", "Ort: —", "Videolink: —"]),
])
def test_central_proposal_formatting_for_tasks_and_events(item, expected):
    text = format_proposal(item, "Europe/Berlin")
    assert all(value in text for value in expected)
    assert [line.split(":", 1)[0] for line in text.splitlines() if not line.startswith("-")] [:8] == [
        "Vorschlagsversion", "Typ", "Zuständigkeit", "Sicherheit", "Einordnung",
        "Extern anlegbar", "Titel", "Beschreibung",
    ]


def test_persist_before_buttons_and_authorized_flow(tmp_path):
    with JsonStore(tmp_path) as store:
        c,t,_=controller(store)
        p=proposal(title="t"*500, description="x"*4000)
        c.send_proposal(p)
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1")["version"]==1
        assert all("[Absender: — · Teil " in message for _, message, _ in t.sent)
        assert "Vorschlag p1" not in t.sent[-1][1] and "Ursprungsmail:" not in t.sent[-1][1]
        value=t.sent[-1][2]["inline_keyboard"][0][0]["callback_data"]
        assert len(t.sent)>=2 and value.startswith("decision:") and len(value.encode("utf-8")) <= 64
        assert Decision.parse(value, store) == Decision(mail_id="a"*24, proposal_id="p1", version=1, action=DecisionAction.CONFIRM)
        c.send(2,"ok")
        with pytest.raises(PermissionError): c.send(3,"x")

        t.updates=[callback(4,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:1:confirm")]
        c.poll_once()
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["status"]=="confirmed"
        assert "bestätigt" in t.sent[-1][1] and t.removed == [(2, 1)]
        # Duplicate update is ignored by the persisted offset after restart.
        c2,t2,_=controller(store,t.updates); c2.poll_once()
        assert t2.polls==[5] and not t2.answered
        # A replay with a fresh update id still cannot mutate the terminal state.
        t2.updates=[callback(5,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:1:reject")]; c2.poll_once()
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["status"]=="confirmed"
        assert "konnte nicht verarbeitet" in t2.sent[-1][1]


def test_test_mode_creates_calendar_file_and_sends_it_via_telegram(tmp_path):
    item = proposal(kind="event", start="2026-05-10T10:00:00+02:00",
                    end="2026-05-10T11:00:00+02:00", title="Planung")
    with JsonStore(tmp_path) as store:
        dialog, transport, _ = controller(store, test_mode=True)
        dialog.writers["google_calendar"] = CalendarFileWriter(transport, 2)
        dialog.send_proposal(item)
        callback_data = transport.sent[-1][2]["inline_keyboard"][0][0]["callback_data"]
        transport.updates = [callback(1, callback_data)]

        dialog.poll_once()

        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["status"] == "created"
        assert len(transport.documents) == 1
        chat_id, filename, content, caption = transport.documents[0]
        assert chat_id == 2 and filename.endswith(".ics")
        assert content.startswith(b"BEGIN:VCALENDAR\r\n")
        assert b"SUMMARY:Planung\r\n" in content
        assert "Planung" in caption
        assert any("Erstellt" in text for _, text, _ in transport.sent)
        assert transport.sent[-1][1] == "✅ Vorschlag wurde bestätigt."


def test_proposal_notification_uses_persisted_sender_and_subject(tmp_path):
    mail_id = "a" * 24
    with JsonStore(tmp_path) as store:
        state = MailState(
            id=mail_id, config_fingerprint="f" * 64,
            imap={"account_id": "0" * 24, "folder": "INBOX", "uidvalidity": 1, "uid": 1},
            display_headers={"sender": "Ada <ada@example.test>", "subject": "Besprechung"},
        )
        store.save("mail-" + mail_id, state.model_dump(mode="json"))
        dialog, transport, _ = controller(store)
        dialog.send_proposal(proposal(source_mail_id=mail_id))
        text = transport.sent[-1][1]
        assert text.startswith("[Absender: Ada <ada@example.test> · Teil 1/1]\nBetreff: Besprechung\n")
        assert mail_id not in text and "Vorschlag p1" not in text


def test_only_exactly_displayed_version_is_written(tmp_path):
    writer=Writer()
    with JsonStore(tmp_path) as store:
        c,t,_=controller(store, writers={"todoist":writer})
        c.send_proposal(proposal(version=1))
        c.send_proposal(proposal(version=2, title="Neue Fassung"))
        t.updates=[callback(1,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:1:confirm"),callback(2,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:2:confirm")]
        c.poll_once()
        assert any("konnte nicht verarbeitet" in text for _, text, _ in t.sent)
        assert writer.versions == [2]
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v2")["title"] == "Neue Fassung"


def test_deadline_clarification_blocks_every_external_request(tmp_path):
    writer=Writer()
    with JsonStore(tmp_path) as store:
        c,t,_=controller(store, writers={"todoist":writer})
        item=proposal(due="2026-10-01", status="needs_clarification",
                      open_questions=["Welcher Datumskontext soll verwendet werden?"])
        c.send_proposal(item)
        t.updates=[callback(1,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:1:confirm")]
        c.poll_once()
        assert writer.reconciled == 0 and writer.created == 0
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["status"] == "needs_clarification"


def test_identical_proposals_have_isolated_confirmation_and_external_results(tmp_path):
    common=dict(timezone="UTC",poll_interval_seconds=5,data_directory=tmp_path/"state",
                imap={"host":"h","port":993,"folders":["INBOX"]},telegram={"user_id":1,"chat_id":2},
                targets={"todoist_project":"p","google_calendar":"c"},limits={"max_mail_bytes":1024,"llm_calls_per_minute":2},
                retries={"provider_retry":0,"json_repair":0,"schema_repair":0},timeouts={**{name:{"timeout_seconds":30,"retries":0,"initial_backoff_seconds":0,"max_backoff_seconds":1} for name in ("imap","telegram","openrouter","todoist","google_calendar")},"telegram_poll_seconds":30},
                logging={"directory":str(tmp_path/"logs"),"console":{"enabled":False},"file":{"filename":"application.jsonl","max_bytes":10000,"backup_count":1,"retention_days":30},"llm":{"filename":"llm/requests.jsonl","max_bytes":10000,"backup_count":1,"retention_days":30}})
    test_settings=Settings(test_mode=True,**common)
    production_settings=Settings(test_mode=False,**common)
    with JsonStore(_state_directory(test_settings,tmp_path)) as test_store:
        test_dialog,_,_=controller(test_store,[callback(1,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:1:confirm")],{"todoist":Writer()},True)
        test_dialog.persist(proposal()); test_dialog.poll_once()
        assert test_store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["status"]=="simulated"
        assert test_store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1").get("external_id") is None
        assert test_store.load("telegram-offset")["offset"]==2

    writer=Writer()
    with JsonStore(_state_directory(production_settings,tmp_path)) as production_store:
        assert production_store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1") is None
        assert production_store.load("telegram-offset") is None
        production_dialog,_,_=controller(production_store,[callback(7,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:1:confirm")],{"todoist":writer})
        production_dialog.persist(proposal()); production_dialog.poll_once()
        assert production_store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["external_id"]=="external-1"
        assert production_store.load("telegram-offset")["offset"]==8
        assert writer.created==1

    with JsonStore(_state_directory(test_settings,tmp_path)) as test_store:
        assert test_store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["status"]=="simulated"
        assert test_store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1").get("external_id") is None
        assert test_store.load("telegram-offset")["offset"]==2


def test_same_llm_id_from_two_mails_survives_restart_and_writes_separately(tmp_path):
    first_mail, second_mail = "a" * 24, "b" * 24
    first_writer, second_writer = Writer(), Writer()
    with JsonStore(tmp_path) as store:
        c,t,_=controller(store, writers={"todoist":first_writer})
        c.persist(proposal(source_mail_id=first_mail))
        c.persist(proposal(source_mail_id=second_mail))
        assert store.load(f"proposal-{first_mail}-p1")["source_mail_id"] == first_mail
        assert store.load(f"proposal-{second_mail}-p1")["source_mail_id"] == second_mail
        t.updates=[callback(1,f"proposal:{first_mail}:p1:1:confirm")]
        c.poll_once()
        assert first_writer.created == 1

        restarted,t2,_=controller(store,[callback(2,f"proposal:{second_mail}:p1:1:confirm")],
                                  {"todoist":second_writer})
        restarted.poll_once()
        assert second_writer.created == 0
        repeat_message = next(message for message in t2.sent if message[2] is not None)
        repeat_data = repeat_message[2]["inline_keyboard"][0][0]["callback_data"]
        t2.updates = [callback(3, repeat_data)]
        restarted.poll_once()
        assert second_writer.created == 1
        assert store.load(f"proposal-{first_mail}-p1")["external_id"] == "external-1"
        assert store.load(f"proposal-{second_mail}-p1")["external_id"] == "external-1"

        # A fresh Telegram update cannot execute the already-created first proposal again.
        t2.updates=[callback(4,f"proposal:{first_mail}:p1:1:confirm")]
        restarted.poll_once()
        assert first_writer.created == 1 and second_writer.created == 1
        assert "konnte nicht verarbeitet" in t2.sent[-1][1]

def test_edit_question_answer_new_version_then_reject(tmp_path):
    with JsonStore(tmp_path) as store:
        c,t,_=controller(store)
        c.send_proposal(proposal(open_questions=["Wann?", "Wo?"]))
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["status"]=="needs_clarification"
        labels=[button["text"] for button in t.sent[-1][2]["inline_keyboard"][0]]
        assert labels == ["Klären", "Verwerfen"] and "Bestätigen" not in labels
        t.updates=[callback(1,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:1:confirm"), callback(2,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:1:edit")]
        c.poll_once()
        assert any("konnte nicht verarbeitet" in text for _, text, _ in t.sent)
        assert store.load("telegram-dialog")["proposal_id"]=="p1"
        t.updates=[message(3,"Morgen")]; c.poll_once()
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v2")["open_questions"]==["Wo?"]
        # Select edit and answer the remaining question, producing a confirmable v3.
        t.updates=[callback(4,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:2:edit"),message(5,"Berlin")]; c.poll_once()
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["version"]==3 and store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["status"]=="pending_confirmation"
        t.updates=[callback(6,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:3:reject")]; c.poll_once()
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["status"]=="rejected"
        assert "verworfen" in t.sent[-1][1]


def test_invalid_unauthorized_missing_and_stale_dialogs(tmp_path):
    with JsonStore(tmp_path) as store:
        bad=[{"not":"an update"}, {"update_id":1,"message":{"private":"do not log"}}, message(2,user=9), message(3,chat=9), callback(4,"bad"), callback(5,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:missing:1:confirm"), callback(6,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:1:confirm",user=9)]
        c,t,log=controller(store,bad); c.poll_once()
        assert store.load("telegram-offset")["offset"]==7
        assert any("syntaktisch" in item[1] for item in t.sent)
        assert any("Nicht autorisierte" in text for _,text,_ in t.sent)
        assert "private" not in repr(log.events)

        c.persist(proposal(version=2))
        store.save("telegram-dialog",{"mail_id":"a"*24,"proposal_id":"p1","version":1})
        t.updates=[message(7)]; c.poll_once(); assert "veraltet" in t.sent[-1][1]
        store.save("telegram-dialog",{"mail_id":"a"*24,"proposal_id":"gone","version":1})
        t.updates=[message(8)]; c.poll_once(); assert "nicht gefunden" in t.sent[-1][1]
        t.updates=[message(9)]; c.poll_once(); assert "Keine offene" in t.sent[-1][1]

        c.revisions.revision_service=FailingRevisionService()
        c.persist(proposal(version=2, description="x"*3995, status="needs_clarification"))
        store.save("telegram-dialog",{"mail_id":"a"*24,"proposal_id":"p1","version":2})
        t.updates=[message(10,"zu lang")]; c.poll_once()
        assert "gespeicherten Antwort" in t.sent[-1][1]
        assert store.load("telegram-dialog")["version"] is None
        saved = store.load("clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v2")
        assert saved["normalized_answer"] == "zu lang"
        assert saved["proposal_revision_status"] == "retry_required"


def test_unusable_answer_gets_llm_generated_concrete_follow_up(tmp_path):
    service = UnusableAnswerService()
    with JsonStore(tmp_path) as store:
        current = proposal(version=2, open_questions=["Welches Datum?"])
        c,t,log = controller(store, revision_service=service)
        c.persist(current)
        store.save("telegram-dialog", TelegramDialogState(
            mail_id=current.source_mail_id, proposal_id=current.id, version=2).model_dump())
        c.revisions.answer("irgendwann")
        assert t.sent[-1][1] == "Bitte konkreter beantworten: Welches Datum?"
        assert [call[0] for call in service.calls] == ["interpret", "clarify"]
        assert store.load("telegram-dialog")["version"] == 2
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["version"] == 2
        saved = store.load("clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v2")
        assert saved["answer_status"] == "invalid"
        assert saved["proposal_revision_status"] == "pending"
        event = next(entry for entry in log.events
                     if entry[0][2] == "answer_clarification_requested")
        assert event[1]["error_class"] == "IncompleteUserAnswer"


@pytest.mark.parametrize(("error", "error_class"), [
    (LlmTokenLimitExceeded("telegram_answer_interpretation", "output_token_limit"),
     "LlmTokenLimitExceeded"),
    (LlmInvalidJson("telegram_answer_interpretation"), "LlmInvalidJson"),
    (LlmSchemaValidationFailed("telegram_answer_interpretation"),
     "LlmSchemaValidationFailed"),
    (LlmProviderResponseInvalid("telegram_answer_interpretation", "provider_unavailable"),
     "LlmProviderResponseInvalid"),
    (httpx.ReadTimeout("timeout"), "ReadTimeout"),
])
def test_technical_answer_errors_are_consumed_without_reasking(
        tmp_path, error, error_class):
    with JsonStore(tmp_path) as store:
        item = proposal(open_questions=["Welches Datum?"])
        c, transport, log = controller(
            store, [message(4, "vertrauliche Antwort")],
            revision_service=InterpretationErrorService(error))
        c.persist(item)
        store.save("telegram-dialog", TelegramDialogState(
            mail_id=item.source_mail_id, proposal_id=item.id,
            version=1).model_dump(mode="json"))

        c.poll_once()

        expected_message = (
            "Technischer Abbruch: Das Modell hat sein Ausgabetokenlimit erreicht. "
            "Die sicher gespeicherte Antwort wird mit der Ausweichstrategie erneut bewertet."
            if isinstance(error, LlmTokenLimitExceeded) else
            "Die interne Verarbeitung ist verzögert. "
            "Die sicher gespeicherte Antwort wird erneut bewertet.")
        assert transport.sent[-1][1] == expected_message
        assert "Welches Datum?" not in transport.sent[-1][1]
        assert store.load("telegram-offset")["offset"] == 5
        assert store.load("telegram-dialog")["proposal_id"] == "p1"
        saved = store.load("clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1")
        assert saved["answer_status"] == "pending"
        assert saved["authorized_answer"] == "vertrauliche Antwort"
        assert saved["interpretation_status"] == "retry_required"
        assert saved["interpretation_attempts"] == 1
        assert saved["next_interpretation_at"] is not None
        event = next(entry for entry in log.events
                     if entry[0][2] == "answer_revision_failed")
        assert event[1]["error_class"] == error_class
        assert event[1]["proposal_reference"] == "aaaaaaaaaaaaaaaaaaaaaaaa:p1:v1"
        assert event[1]["revision_status"] == "retry_required"
        assert "vertrauliche Antwort" not in repr(log.events)


def test_contradictory_answer_is_domain_failure_not_incomplete(tmp_path):
    with JsonStore(tmp_path) as store:
        item = proposal(open_questions=["Welches Datum?"])
        c, transport, log = controller(
            store, [message(2, "Antwort")],
            revision_service=InterpretationErrorService(
                ContradictoryRevision("fachlicher Widerspruch")))
        c.persist(item)
        store.save("telegram-dialog", TelegramDialogState(
            mail_id=item.source_mail_id, proposal_id=item.id,
            version=1).model_dump(mode="json"))

        c.poll_once()

        assert "widerspricht" in transport.sent[-1][1]
        assert "Welches Datum?" not in transport.sent[-1][1]
        assert store.load("telegram-offset")["offset"] == 3
        saved = store.load("clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1")
        assert saved["answer_status"] == "pending"
        assert saved["authorized_answer"] == "Antwort"
        assert saved["interpretation_status"] == "retry_required"
        event = next(entry for entry in log.events
                     if entry[0][2] == "answer_revision_failed")
        assert event[1]["error_class"] == "ContradictoryRevision"


def test_interpretation_timeout_is_resumed_from_persisted_answer_after_restart(tmp_path):
    directory = tmp_path / "restart-interpretation"
    secret = "streng vertrauliche Terminantwort"
    with JsonStore(directory) as store:
        item = proposal(open_questions=["Welches Datum?"])
        c, _, log = controller(store, [message(4, secret)],
                               revision_service=InterpretationErrorService(
                                   httpx.ReadTimeout(secret)))
        c.persist(item)
        store.save("telegram-dialog", TelegramDialogState(
            mail_id=item.source_mail_id, proposal_id=item.id,
            version=1).model_dump(mode="json"))
        c.poll_once()
        name = "clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1"
        saved = store.load(name)
        assert saved["authorized_answer"] == secret
        assert secret not in repr(log.events)
        saved["next_interpretation_at"] = None
        store.save(name, saved)

    with JsonStore(directory) as store:
        service = RevisionService()
        c, _, log = controller(store, revision_service=service)
        c.poll_once()
        assert [call[3] for call in service.calls if call[0] == "interpret"] == [secret]
        saved = store.load("clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1")
        assert saved["interpretation_status"] == "completed"
        assert saved["proposal_revision_status"] == "completed"
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["version"] == 2
        assert secret not in repr(log.events)


def test_interpretation_retry_budget_pauses_without_deleting_answer(tmp_path):
    secret = "private Antwort"
    with JsonStore(tmp_path) as store:
        item = proposal(open_questions=["Datum?"])
        service = InterpretationErrorService(httpx.ReadTimeout(secret))
        c, transport, log = controller(store, [message(1, secret)],
                                       revision_service=service)
        c.revisions.interpretation_attempts = 2
        c.persist(item)
        store.save("telegram-dialog", TelegramDialogState(
            mail_id=item.source_mail_id, proposal_id=item.id,
            version=1).model_dump(mode="json"))
        c.poll_once()
        name = "clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1"
        pending = store.load(name)
        pending["next_interpretation_at"] = None
        store.save(name, pending)
        c.poll_once()
        paused = store.load(name)
        assert paused["interpretation_attempts"] == 2
        assert paused["interpretation_status"] == "paused"
        assert paused["next_interpretation_at"] is None
        assert paused["authorized_answer"] == secret
        calls = len(service.calls)
        c.poll_once()
        assert len(service.calls) == calls
        assert "pausiert" in transport.sent[-1][1]
        assert secret not in repr(log.events)


def test_token_limit_fallback_parameters_persist_and_pause_after_restart(tmp_path):
    class TruncatedCompleter:
        def __init__(self):
            self.requests = []

        def complete(self, model, parameters, system, payload, **metadata):
            self.requests.append((parameters, system, payload, metadata))
            raise ProviderResponseInvalid("output_token_limit")

    cfg = prompt_config()
    step = cfg.prompts["telegram_answer_interpretation"]
    step.parameters = {"temperature": 0.0, "max_tokens": 500}
    step.output_token_retry = OutputTokenRetry(
        system_prompt="Nur usable, normalized_answer und reason.",
        parameters={"max_tokens": 180})
    completer = TruncatedCompleter()
    service = Analyzer(completer, cfg, provider_retries=3)
    directory = tmp_path / "token-limit-restart"
    secret = "am ersten Oktober"

    with JsonStore(directory) as store:
        item = proposal(open_questions=["Welches Datum?"])
        c, _, _ = controller(store, [message(1, secret)], revision_service=service)
        c.revisions.interpretation_attempts = 2
        c.persist(item)
        store.save("telegram-dialog", TelegramDialogState(
            mail_id=item.source_mail_id, proposal_id=item.id,
            version=1).model_dump(mode="json"))
        c.poll_once()
        saved = store.load("clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1")
        assert saved["interpretation_status"] == "retry_required"
        assert saved["authorized_answer"] == secret
        saved["next_interpretation_at"] = None
        store.save("clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1", saved)

    with JsonStore(directory) as store:
        c, transport, _ = controller(store, revision_service=service)
        c.revisions.interpretation_attempts = 2
        c.poll_once()
        paused = store.load("clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1")
        assert paused["interpretation_status"] == "paused"
        assert paused["authorized_answer"] == secret
        assert paused["next_interpretation_at"] is None
        assert "pausiert" in transport.sent[-1][1]

    assert len(completer.requests) == 4
    assert [request[0]["max_tokens"] for request in completer.requests] == [
        500, 500, 500, 500]
    assert [request[1] for request in completer.requests[1::2]] == [
        step.output_token_retry.system_prompt, step.output_token_retry.system_prompt]


def test_duplicate_delivery_does_not_reinterpret_persisted_answer(tmp_path):
    with JsonStore(tmp_path) as store:
        item = proposal(open_questions=["Datum?"])
        service = InterpretationErrorService(httpx.ReadTimeout("timeout"))
        c, transport, _ = controller(store, [message(3, "erste Antwort")],
                                     revision_service=service)
        c.persist(item)
        store.save("telegram-dialog", TelegramDialogState(
            mail_id=item.source_mail_id, proposal_id=item.id,
            version=1).model_dump(mode="json"))
        c.poll_once()
        transport.updates = [message(3, "erste Antwort")]
        store.save("telegram-offset", {"schema_version": 1, "offset": 3})
        c.poll_once()
        assert store.load("clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1")[
            "interpretation_attempts"] == 1
        assert "bereits sicher gespeichert" in transport.sent[-1][1]


def test_failed_answer_persistence_does_not_advance_offset_or_log_answer(tmp_path):
    secret = "darf niemals im Fehler stehen"
    class FailingStore(JsonStore):
        fail = True
        def save(self, name, value):
            if self.fail and name.startswith("clarification-"):
                raise OSError("Zustand konnte nicht gespeichert werden")
            super().save(name, value)

    with FailingStore(tmp_path) as store:
        item = proposal(open_questions=["Datum?"])
        c, _, log = controller(store, [message(9, secret)])
        c.persist(item)
        store.save("telegram-dialog", TelegramDialogState(
            mail_id=item.source_mail_id, proposal_id=item.id,
            version=1).model_dump(mode="json"))
        with pytest.raises(OSError, match="Zustand konnte nicht gespeichert"):
            c.poll_once()
        assert store.load("telegram-offset") is None
        assert secret not in repr(log.events)
        store.fail = False
        c.poll_once()
        assert store.load("telegram-offset")["offset"] == 10


def test_revision_unavailable_preserves_dialog(tmp_path):
    with JsonStore(tmp_path) as store:
        transport=Telegram([message(1,"Neuer Titel")]); log=Logger()
        c=TelegramDialogController(store,transport,1,2,log)
        c.persist(proposal(status="needs_clarification"))
        store.save("telegram-dialog",{"mail_id":"a"*24,"proposal_id":"p1","version":1})
        c.poll_once()
        assert "nicht verfügbar" in transport.sent[-1][1]
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["version"]==1
        assert store.load("telegram-dialog")["proposal_id"]=="p1"


def test_operational_reply_failure_keeps_valid_answer_and_is_acknowledged(tmp_path):
    with JsonStore(tmp_path) as store:
        c,t,log=controller(store, [message(4, "Neuer Titel")],
                           revision_service=OperationallyFailingRevisionService())
        c.persist(proposal(status="needs_clarification"))
        store.save("telegram-dialog", {"mail_id":"a"*24,"proposal_id":"p1","version":1})
        c.poll_once()
        assert store.load("telegram-offset")["offset"] == 5
        assert store.load("telegram-dialog")["proposal_id"] is None
        saved = store.load("clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1")
        assert saved["normalized_answer"] == "Neuer Titel"
        assert saved["question_status"] == "answered"
        assert saved["answer_status"] == "valid"
        assert saved["proposal_revision_status"] == "retry_required"
        event = next(item for item in log.events if item[0][2] == "answer_revision_failed")
        assert event[1]["error_class"] == "TechnicalRevisionError"
        assert event[1]["revision_status"] == "retry_required"
        assert "provider unavailable" not in repr(event)


def test_answer_is_persisted_and_dialog_closed_before_revision(tmp_path):
    events = []
    class OrderedStore(JsonStore):
        def save(self, name, value):
            super().save(name, value)
            if name.startswith("clarification-"):
                events.append(("answer", value["normalized_answer"]))
            elif name == "telegram-dialog" and value["proposal_id"] is None:
                events.append(("dialog", None))
    class OrderedRevision(RevisionService):
        def revise_proposal(self, item, question, answer):
            assert events == [("answer", None), ("answer", "2026-10-21"),
                              ("dialog", None)]
            events.append(("revision", answer))
            return super().revise_proposal(item, question, answer)
        def interpret_telegram_answer(self, item, question, answer):
            return "interpret", type("Interpretation", (), {
                "usable": True, "normalized_answer": "2026-10-21", "reason": "ok"})()
    with OrderedStore(tmp_path) as store:
        item = proposal(open_questions=["Welches Datum?"])
        c,_,_=controller(store, revision_service=OrderedRevision())
        c.persist(item)
        store.save("telegram-dialog", TelegramDialogState(
            mail_id=item.source_mail_id, proposal_id=item.id, version=1).model_dump(mode="json"))
        events.clear()
        c.revisions.answer("am nächsten Mittwoch")
        assert events[:4] == [("answer", None), ("answer", "2026-10-21"),
                              ("dialog", None), ("revision", "2026-10-21")]
        assert store.load("clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1")["proposal_revision_status"] == "completed"


@pytest.mark.parametrize("error", [
    ValueError("schema"), RuntimeError("output_token_limit"),
    LlmInvalidJson("proposal_revision"),
])
def test_revision_failures_only_mark_revision_retry_required(tmp_path, error):
    class Failure(RevisionService):
        def revise_proposal(self, item, question, answer):
            raise error
    with JsonStore(tmp_path) as store:
        item=proposal(open_questions=["Welches Datum?"])
        c,_,_=controller(store, revision_service=Failure())
        c.persist(item)
        store.save("telegram-dialog", TelegramDialogState(
            mail_id=item.source_mail_id, proposal_id=item.id, version=1).model_dump(mode="json"))
        c.revisions.answer("2026-10-21")
        saved=store.load_model("clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1", ProposalClarificationState)
        assert (saved.question_status, saved.answer_status, saved.normalized_answer,
                saved.proposal_revision_status) == (
                    QuestionStatus.ANSWERED, AnswerStatus.VALID, "2026-10-21",
                    ProposalRevisionStatus.RETRY_REQUIRED)


def test_restart_retries_normalized_answer_and_ok_is_not_old_answer(tmp_path):
    class CrashAfterAnswer(JsonStore):
        crash = True
        def save(self, name, value):
            super().save(name, value)
            if self.crash and name == "telegram-dialog" and value["proposal_id"] is None:
                raise RuntimeError("simulated crash")
    directory=tmp_path/"restart"
    with CrashAfterAnswer(directory) as store:
        item=proposal(open_questions=["Welches Datum?"])
        c,_,_=controller(store)
        c.persist(item)
        store.save("telegram-dialog", TelegramDialogState(
            mail_id=item.source_mail_id, proposal_id=item.id, version=1).model_dump(mode="json"))
        with pytest.raises(RuntimeError, match="simulated crash"):
            c.revisions.answer("2026-10-21")
        assert store.load("clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1")["normalized_answer"] == "2026-10-21"
    with JsonStore(directory) as store:
        service=RevisionService()
        c,t,_=controller(store, [message(1, "Ok")], revision_service=service)
        c.poll_once()
        revision_calls=[call for call in service.calls if not isinstance(call[0], str)]
        assert revision_calls[0][2] == "2026-10-21"
        assert not any(call[0] == "interpret" and call[3] == "Ok" for call in service.calls)
        assert store.load("clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1")["normalized_answer"] == "2026-10-21"
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["version"] == 2
        assert "Keine offene" in t.sent[-1][1]


def test_clarification_schema_migration_and_validation(tmp_path):
    name="clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1"
    with JsonStore(tmp_path) as store:
        base={"schema_version":1, "mail_id":"a"*24, "proposal_id":"p1",
              "version":1, "question":"Welches Datum?"}
        store.save(name, {**base, "normalized_answer":"2026-10-21"})
        migrated=store.load_model(name, ProposalClarificationState)
        assert migrated.schema_version == 4 and migrated.answer_status == AnswerStatus.VALID
        assert store.load(name)["normalized_answer"] == "2026-10-21"
        store.save(name, base)
        open_state=store.load_model(name, ProposalClarificationState)
        assert open_state.question_status == QuestionStatus.OPEN
        assert open_state.answer_status == AnswerStatus.PENDING
    with pytest.raises(ValidationError, match="normalisierte Antwort"):
        ProposalClarificationState(mail_id="a"*24, proposal_id="p1", version=1,
                                   question="Datum?", normalized_answer="2026-10-21")
    with pytest.raises(ValidationError, match="offene Frage"):
        ProposalClarificationState(mail_id="a"*24, proposal_id="p1", version=1,
                                   question="Datum?", answer_status=AnswerStatus.INVALID,
                                   proposal_revision_status=ProposalRevisionStatus.RETRY_REQUIRED)
    with pytest.raises(ValidationError, match="UTC-Offset"):
        ProposalClarificationState(
            mail_id="a"*24, proposal_id="p1", version=1, question="Datum?",
            question_status="answered", answer_status="valid",
            normalized_answer="2026-10-21", proposal_revision_status="retry_required",
            next_revision_at="2026-09-22T12:00:00")
    with pytest.raises(ValidationError, match="Interpretationsversuche"):
        ProposalClarificationState(
            mail_id="a"*24, proposal_id="p1", version=1, question="Datum?",
            interpretation_attempts=1)
    with pytest.raises(ValidationError, match="Interpretationsstatus"):
        ProposalClarificationState(
            mail_id="a"*24, proposal_id="p1", version=1, question="Datum?",
            interpretation_status="retry_required")
    with pytest.raises(ValidationError, match="Interpretationszeitpunkt"):
        ProposalClarificationState(
            mail_id="a"*24, proposal_id="p1", version=1, question="Datum?",
            next_interpretation_at="2026-09-22T12:00:00+00:00")


def test_clarification_recovery_edge_paths(tmp_path):
    class InterpretationFailure(RevisionService):
        def interpret_telegram_answer(self, item, question, answer):
            raise LlmInvalidJson("telegram_answer_interpretation")
    with JsonStore(tmp_path) as store:
        item=proposal(open_questions=["Datum?"])
        c,t,_=controller(store, revision_service=InterpretationFailure())
        c.persist(item)
        dialog=TelegramDialogState(mail_id=item.source_mail_id, proposal_id=item.id, version=1)
        store.save("telegram-dialog", dialog.model_dump(mode="json"))
        c.revisions.answer("raw")
        assert "Verarbeitung ist verzögert" in t.sent[-1][1]

        # An invalid prior response is replaceable; it is not mistaken for a
        # still pending delivery.
        invalid = store.load("clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1")
        invalid.update(answer_status="invalid", interpretation_status="completed")
        store.save("clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1", invalid)
        c.revisions.revision_service = InterpretationFailure()
        c.revisions.answer("2026-10-21")

        answered=ProposalClarificationState(
            mail_id=item.source_mail_id, proposal_id=item.id, version=1,
            question="Datum?", question_status=QuestionStatus.ANSWERED,
            answer_status=AnswerStatus.VALID, normalized_answer="2026-10-21",
            proposal_revision_status=ProposalRevisionStatus.RETRY_REQUIRED)
        name="clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1"
        store.save(name, answered.model_dump(mode="json"))
        c.revisions.revision_service=RevisionService()
        c.revisions.answer("Ok")
        assert "bereits gespeichert" in t.sent[-1][1]

        # A successor published before a crash makes retry completion
        # idempotent and never invokes the LLM again.
        c.persist(proposal(version=2))
        c.revisions._revise_answered(answered)
        assert store.load(name)["proposal_revision_status"] == "completed"

        missing=answered.model_copy(update={"proposal_id":"missing"})
        c.revisions._revise_answered(missing)
        c.revisions._interpret_pending(answered.model_copy(update={
            "question_status": QuestionStatus.OPEN,
            "answer_status": AnswerStatus.PENDING,
            "normalized_answer": None,
            "proposal_revision_status": ProposalRevisionStatus.PENDING,
            "authorized_answer": "gespeichert",
        }))
        c.revisions.revision_service=None
        c.revisions._revise_answered(answered.model_copy(update={"version":2}))

        c.revisions.revision_service=RevisionService()
        original_handle = c._handle
        c._handle=lambda update: (_ for _ in ()).throw(RuntimeError("persistence"))
        t.updates=[message(7)]
        with pytest.raises(RuntimeError, match="persistence"):
            c.poll_once()

        c.revisions.revision_service = RevisionService()
        c._handle = original_handle
        c.poll_once()
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["version"] == 2
        assert store.load("telegram-dialog")["retry_required"] is False


def test_revision_resume_handles_stale_unavailable_and_repeated_failure(tmp_path):
    base={"mail_id":"a"*24,"proposal_id":"p1","version":1,
          "retry_required":True,"question":"Welche Änderung?",
          "normalized_answer":"Neu"}
    with JsonStore(tmp_path) as store:
        c,_,log=controller(store, revision_service=OperationallyFailingRevisionService())
        c.persist(proposal(status="needs_clarification"))
        store.save("telegram-dialog",base)
        c.poll_once()
        assert any(item[0][2] == "answer_revision_resume_failed" for item in log.events)

        c.revisions.revision_service=RevisionService()
        c.poll_once()
        assert store.load("telegram-dialog")["retry_required"] is False
        assert any(item[0][2] == "answer_revision_resumed" for item in log.events)

        c.revisions.revision_service=None
        store.save("telegram-dialog",{**base,"version":2})
        c.poll_once()
        assert store.load("telegram-dialog")["retry_required"] is True

        store.save("telegram-dialog",{**base,"version":3})
        c.poll_once()
        assert store.load("telegram-dialog")["retry_required"] is False
    with pytest.raises(Exception, match="Revisions-Retry"):
        TelegramDialogState(retry_required=True)


def test_unexpected_interpretation_failure_remains_unacknowledged(tmp_path):
    class Broken(RevisionService):
        def interpret_telegram_answer(self, item, question, answer):
            raise RuntimeError("temporary")
    with JsonStore(tmp_path) as store:
        c,_,_=controller(store,[message(8,"Antwort")],revision_service=Broken())
        c.persist(proposal(status="needs_clarification"))
        store.save("telegram-dialog",{"mail_id":"a"*24,"proposal_id":"p1","version":1})
        with pytest.raises(RuntimeError,match="temporary"):
            c.poll_once()


def test_unrelated_telegram_update_does_not_block_following_reply(tmp_path):
    unrelated = {"update_id": 1, "my_chat_member": {"private": "not logged"}}
    with JsonStore(tmp_path) as store:
        c,t,log=controller(store, [unrelated, message(2)])
        c.poll_once()
        assert store.load("telegram-offset")["offset"] == 3
        assert "Keine offene" in t.sent[-1][1]
        assert "private" not in repr(log.events)


def test_telegram_client_validation_and_callback():
    requests=[]
    def handler(request):
        requests.append(request)
        data={"ok":True,"result":[]} if request.url.path.endswith("getUpdates") else {"ok":True,"result":True}
        return httpx.Response(200,json=data,request=request)
    client=TelegramClient("secret",1,httpx.MockTransport(handler))
    assert client.poll(0)==[]
    client.send(2,"x",{"inline_keyboard":[]}); client.answer_callback("c","ok")
    client.remove_inline_keyboard(2, 7); client.close()
    assert len(requests)==4
    assert requests[-1].url.path.endswith("editMessageReplyMarkup")
    assert requests[-1].read() == b'{"chat_id":2,"message_id":7,"reply_markup":{"inline_keyboard":[]}}'
    assert requests[0].url.params["allowed_updates"] == '["message","callback_query"]'
    invalid=TelegramClient("secret",1,httpx.MockTransport(lambda r:httpx.Response(200,json={"ok":True,"result":{}},request=r)))
    with pytest.raises(ValueError): invalid.poll(0)
    invalid.close()


def test_expired_callback_acknowledgement_does_not_block_update_checkpoint(tmp_path):
    item = proposal()
    decision = Decision(mail_id=item.source_mail_id, proposal_id=item.id, version=1,
                        action=DecisionAction.REJECT)
    events = Logger()

    def handler(request):
        if request.url.path.endswith("getUpdates"):
            return httpx.Response(200, json={"ok": True, "result": [
                callback(7, decision.encode())
            ]}, request=request)
        if request.url.path.endswith("editMessageReplyMarkup") or request.url.path.endswith("sendMessage"):
            return httpx.Response(200, json={"ok": True, "result": True}, request=request)
        return httpx.Response(400, json={
            "ok": False,
            "error_code": 400,
            "description": (
                "Bad Request: query is too old and response timeout expired "
                "or query ID is invalid"
            ),
        }, request=request)

    client = TelegramClient("secret", 1, httpx.MockTransport(handler), logger=events)
    with JsonStore(tmp_path) as store:
        dialog = TelegramDialogController(store, client, 1, 2, events)
        dialog.persist(item)
        dialog.poll_once()
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["status"] == "rejected"
        assert store.load("telegram-offset")["offset"] == 8
        assert any(entry[0][2] == "callback_acknowledgement_expired"
                   for entry in events.events)
    client.close()


def test_only_exact_expired_callback_error_is_ignored():
    def rejected(request):
        return httpx.Response(400, json={
            "ok": False, "error_code": 400,
            "description": "Bad Request: query ID is invalid",
        }, request=request)

    client = TelegramClient("secret", 1, httpx.MockTransport(rejected))
    with pytest.raises(PermanentError, match="query ID is invalid"):
        client.answer_callback("c", "ok")
    client.close()


def test_started_chats_ignores_unrelated_update_kind():
    payload = {"ok": True, "result": [
        {"update_id": 1, "my_chat_member": {"status": "member"}},
        message(2, "/start", user=1, chat=7),
    ]}
    client = TelegramClient("secret", 1, httpx.MockTransport(
        lambda request: httpx.Response(200, json=payload, request=request)))
    assert client.started_chats(1) == [7]
    client.close()


def test_telegram_client_preserves_documented_api_error_description():
    def rejected(request):
        return httpx.Response(400,json={"ok":False,"error_code":400,"description":"Bad Request: chat not found"},request=request)
    client=TelegramClient("top-secret",1,httpx.MockTransport(rejected))
    with pytest.raises(PermanentError) as error:
        client.send(2,"x")
    assert str(error.value) == (
        "Permanente Adapterantwort: Telegram sendMessage: Chat nicht erreichbar. "
        "Bitte den Bot im Zielchat zuerst mit /start starten, die numerische "
        "telegram.chat_id prüfen und bei Gruppen sicherstellen, dass der Bot Mitglied ist"
    )
    assert "top-secret" not in str(error.value)
    client.close()


def test_telegram_client_finds_only_configured_users_start_chats():
    payload = {"ok": True, "result": [
        {"update_id": 1, "message": {"message_id": 1, "from": {"id": 42},
         "chat": {"id": 42}, "text": "/start"}},
        {"update_id": 2, "message": {"message_id": 2, "from": {"id": 42},
         "chat": {"id": -100}, "text": "/start@mailhelp_bot"}},
        {"update_id": 3, "message": {"message_id": 3, "from": {"id": 7},
         "chat": {"id": 7}, "text": "/start"}},
        {"update_id": 4, "message": {"message_id": 4, "from": {"id": 42},
         "chat": {"id": 42}, "text": "hello"}},
    ]}
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=payload, request=request)
    client = TelegramClient("secret", 1, httpx.MockTransport(handler))

    assert client.started_chats(42) == [-100, 42]
    assert seen[0].url.params["timeout"] == "0"
    assert seen[0].url.params["allowed_updates"] == '["message"]'
    client.close()


def test_telegram_started_chat_diagnostic_validates_api_response():
    for status, payload, error in (
        (200, {"wrong": True}, ValueError),
        (200, {"ok": False, "result": []}, ValueError),
        (400, {"ok": False, "description": "Bad Request: chat not found"},
         TelegramChatNotFoundError),
    ):
        client = TelegramClient(
            "secret", 1,
            httpx.MockTransport(lambda request, s=status, p=payload:
                                httpx.Response(s, json=p, request=request)),
        )
        with pytest.raises(error):
            client.started_chats(42)
        client.close()


def test_telegram_client_preserves_retryable_and_http_success_api_errors():
    responses=iter([
        (500,{"ok":False,"description":"Internal Server Error: try later"}),
        (200,{"ok":False,"error_code":400,"description":"Bad Request: message is too long"}),
        (200,{"ok":False,"error_code":400,"description":"Bad Request: chat not found"}),
    ])
    def rejected(request):
        status_code,payload=next(responses)
        return httpx.Response(status_code,json=payload,request=request)
    client=TelegramClient("secret",1,httpx.MockTransport(rejected))
    with pytest.raises(UncertainWriteError,match="Telegram sendMessage: Internal Server Error: try later"):
        client.send(2,"x")
    with pytest.raises(PermanentError,match="Telegram sendMessage: Bad Request: message is too long"):
        client.send(2,"x")
    with pytest.raises(PermanentError, match="Chat nicht erreichbar"):
        client.send(2,"x")
    client.close()


def test_telegram_error_description_boundary_rejects_unusable_fields():
    request=httpx.Request("POST","https://example.test")
    invalid_json=httpx.Response(400,content=b"not-json",request=request)
    list_json=httpx.Response(400,json=["description"],request=request)
    wrong_description=httpx.Response(400,json={"ok":False,"description":42},request=request)
    assert TelegramClient._description(invalid_json) is None
    assert TelegramClient._description(list_json) is None
    assert TelegramClient._description(wrong_description) is None
    with pytest.raises(httpx.HTTPStatusError) as error:
        TelegramClient._raise_for_status(wrong_description,"sendMessage")
    assert not hasattr(error.value,"safe_detail")
    TelegramClient._raise_api_error(invalid_json,"sendMessage")
    TelegramClient._raise_api_error(list_json,"sendMessage")
    TelegramClient._raise_api_error(wrong_description,"sendMessage")


def test_telegram_client_sends_calendar_document_and_validates_filename():
    requests=[]
    def handler(request):
        requests.append(request)
        return httpx.Response(200,json={"ok":True,"result":{"message_id":7}},request=request)
    client=TelegramClient("secret",1,httpx.MockTransport(handler))
    client.send_document(2,"termin.ics",b"BEGIN:VCALENDAR\r\n",caption="Import")
    client.send_document(2,"termin-ohne-text.ics",b"BEGIN:VCALENDAR\r\n")
    assert requests[0].url.path.endswith("/sendDocument")
    assert b'text/calendar' in requests[0].content and b'termin.ics' in requests[0].content
    with pytest.raises(ValueError,match="Dateiname"):
        client.send_document(2,"../termin.ics",b"x")
    with pytest.raises(ValueError,match="Dateiname"):
        client.send_document(2,"",b"x")
    client.close()


def test_confirmation_executes_and_reports_all_results(tmp_path):
    cases=[
        (Writer(),False,"created","Erstellt"),
        (Writer(error=httpx.ReadTimeout("timeout")),False,"uncertain","Unklarer"),
        (Writer(error=httpx.HTTPStatusError("bad",request=httpx.Request("POST","https://x"),response=httpx.Response(400))),False,"failed","fehlgeschlagen"),
        (Writer(),True,"simulated","Testmodus"),
    ]
    for index,(writer,test_mode,status,text) in enumerate(cases):
        with JsonStore(tmp_path/str(index)) as store:
            c,t,_=controller(store,[callback(1,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:1:confirm")],{"todoist":writer},test_mode)
            c.persist(proposal()); c.poll_once()
            saved=store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")
            assert saved["status"]==status
            assert any(text in message for _,message,_ in t.sent)
            if status=="created": assert saved["external_id"]=="external-1" and saved["external_link"]=="https://example.test/item"


def test_restart_reconciles_before_retry_and_duplicate_update_is_safe(tmp_path):
    with JsonStore(tmp_path) as store:
        first=Writer(error=httpx.ReadTimeout("timeout"))
        c,t,_=controller(store,[callback(1,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:1:confirm")],{"todoist":first})
        c.persist(proposal()); c.poll_once()
        assert first.created==1 and store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["status"]=="uncertain"
        recovered=Writer(found={"id":"external-existing","html_url":"https://example.test/existing"})
        restarted,t2,_=controller(store,[callback(1,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:1:confirm")],{"todoist":recovered})
        restarted.poll_once()
        assert recovered.reconciled==1 and recovered.created==0
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["external_id"]=="external-existing"
        assert t2.polls==[2]

    with JsonStore(tmp_path/"writing") as store:
        interrupted=Writer()
        c,t,_=controller(store,(),{"todoist":interrupted})
        c.persist(proposal(status="writing")); c.poll_once()
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["status"]=="uncertain"
        assert interrupted.reconciled == 1 and interrupted.created == 0

    class MinimalStore:
        def __init__(self): self.values={}
        def load(self,name,default=None): return self.values.get(name,default)
        def save(self,name,value): self.values[name]=value
        def load_model(self,name,model,default=None):
            value=self.load(name)
            return default if value is None else model.model_validate(value)
    minimal=MinimalStore(); c,_,_=controller(minimal); c.poll_once()


def test_uncertain_write_is_only_reconciled_across_restarts(tmp_path):
    with JsonStore(tmp_path) as store:
        failed=Writer(error=httpx.ConnectError("lost"))
        initial,telegram,_=controller(
            store,[callback(1,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:1:confirm")],{"todoist":failed})
        initial.persist(proposal()); initial.poll_once()
        assert failed.created == 1
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["status"] == "uncertain"
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["uncertain_notified"] is True
        assert len([text for _,text,_ in telegram.sent if "Unklarer" in text]) == 1

        unresolved=Writer()
        for _ in range(3):
            restarted,messages,_=controller(store,(),{"todoist":unresolved})
            restarted.poll_once()
            assert not messages.sent
        assert unresolved.reconciled == 3
        assert unresolved.created == 0
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["status"] == "uncertain"

        unresolved.found={"id":"eventual","url":"https://example.test/eventual"}
        recovered,messages,_=controller(store,(),{"todoist":unresolved})
        recovered.poll_once()
        assert unresolved.reconciled == 4
        assert unresolved.created == 0
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["status"] == "created"
        assert "Erstellt" in messages.sent[-1][1]


class RelevanceHandler:
    def __init__(self, store): self.store=store; self.resumed=[]
    def resolve_relevance(self, mail_id, version, decision, offset):
        state=self.store.load_model("mail-"+mail_id,MailState)
        dialog=state.relevance_dialog
        if dialog is None or dialog.version != version or dialog.status.value != "open":
            raise ValueError("Die Relevanzfrage ist veraltet oder bereits beantwortet")
        state.relevance_dialog=dialog.model_copy(update={"status":RelevanceDialogStatus.DECIDED,"decision":decision,"telegram_offset":offset})
        state.awaiting_relevance=False
        self.store.save("mail-"+mail_id,state.model_dump(mode="json")); return state
    def resume_mail(self,state): self.resumed.append(state.id)


def relevance_state(mail_id, version=1):
    return MailState(id=mail_id,config_fingerprint="0"*64,imap={"account_id":"0"*24,"folder":"INBOX","uidvalidity":1,"uid":1},awaiting_relevance=True,relevance_dialog=RelevanceDialog(mail_id=mail_id,version=version))


def test_relevance_dialog_authorization_stale_restart_and_duplicate(tmp_path):
    mail_id="a"*24
    with JsonStore(tmp_path) as store:
        store.save("mail-"+mail_id,relevance_state(mail_id).model_dump(mode="json"))
        updates=[callback(1,f"relevance:{mail_id}:1:relevant",user=9),callback(2,f"relevance:{mail_id}:2:relevant"),callback(3,f"relevance:{mail_id}:1:relevant")]
        c,t,_=controller(store,updates); handler=RelevanceHandler(store); c.relevance_handler=handler
        assert c.awaiting_relevance_decision()
        c.send_relevance(RelevanceDialog(mail_id=mail_id), "Alice <alice@example.test>", "Rechnung")
        visible=t.sent[-1][1]
        callbacks=t.sent[-1][2]["inline_keyboard"][0]
        assert visible == "Absender: Alice <alice@example.test>\nBetreff: Rechnung\nRelevanz bitte bestätigen:"
        assert mail_id not in visible
        assert [button["callback_data"] for button in callbacks] == [
            f"relevance:{mail_id}:1:relevant",
            f"relevance:{mail_id}:1:irrelevant",
        ]
        c.poll_once()
        assert not c.awaiting_relevance_decision()
        assert all(text == "Aktion wird verarbeitet …" for _, text in t.answered[:3])
        assert any("Nicht autorisierte" in text for _, text, _ in t.sent)
        assert any("konnte nicht verarbeitet" in text for _, text, _ in t.sent)
        assert handler.resumed==[mail_id] and store.load("mail-"+mail_id)["relevance_dialog"]["telegram_offset"]==4
        restarted,t2,_=controller(store,[callback(3,f"relevance:{mail_id}:1:irrelevant")]); restarted.relevance_handler=handler
        restarted.poll_once(); assert t2.polls==[4] and "bereits verarbeitet" in t2.answered[-1][1]
        t2.updates=[callback(4,f"relevance:{mail_id}:1:irrelevant")]; restarted.poll_once()
        assert "konnte nicht verarbeitet" in t2.sent[-1][1]


def test_relevance_dialog_displays_missing_headers_without_exposing_mail_id(tmp_path):
    mail_id="b"*24
    with JsonStore(tmp_path) as store:
        c,t,_=controller(store)
        c.send_relevance(RelevanceDialog(mail_id=mail_id,version=3), "—", "—")
        assert t.sent[-1][1] == "Absender: —\nBetreff: —\nRelevanz bitte bestätigen:"
        assert mail_id not in t.sent[-1][1]
        assert [button["callback_data"] for button in t.sent[-1][2]["inline_keyboard"][0]] == [
            f"relevance:{mail_id}:3:relevant",
            f"relevance:{mail_id}:3:irrelevant",
        ]


def test_relevance_free_text_requires_unique_open_dialog(tmp_path):
    ids=["a"*24,"b"*24]
    with JsonStore(tmp_path) as store:
        for mail_id in ids: store.save("mail-"+mail_id,relevance_state(mail_id).model_dump(mode="json"))
        c,t,_=controller(store,[message(1,"relevant")]); c.relevance_handler=RelevanceHandler(store); c.poll_once()
        assert "nicht eindeutig" in t.sent[-1][1]
        state=store.load_model("mail-"+ids[1],MailState); state.relevance_dialog=None; state.awaiting_relevance=False
        store.save("mail-"+ids[1],state.model_dump(mode="json"))
        t.updates=[message(2,"irrelevant")]; c.poll_once()
        assert store.load("mail-"+ids[0])["relevance_dialog"]["decision"]=="irrelevant"


def test_invalid_relevance_callbacks_and_unavailable_handler(tmp_path):
    mail_id="a"*24
    with JsonStore(tmp_path) as store:
        store.save("mail-"+mail_id,relevance_state(mail_id).model_dump(mode="json"))
        c,t,_=controller(store,[callback(1,"relevance:bad"),callback(2,f"relevance:{mail_id}:1:relevant"),message(3,"irrelevant")])
        c.poll_once()
        assert all(text == "Aktion wird verarbeitet …" for _, text in t.answered)
        assert any("syntaktisch" in text for _, text, _ in t.sent)
        assert "nicht verfügbar" in t.sent[-1][1]


def test_duplicate_free_text_is_visible_only_to_authorized_chat(tmp_path):
    mail_id="a"*24
    with JsonStore(tmp_path) as store:
        state=relevance_state(mail_id)
        state.relevance_dialog=state.relevance_dialog.model_copy(update={"status":RelevanceDialogStatus.DECIDED,"decision":"relevant","telegram_offset":3})
        state.awaiting_relevance=False
        store.save("mail-"+mail_id,state.model_dump(mode="json"))
        c,t,_=controller(store,[message(2,"relevant"),message(2,"relevant",user=9)])
        c.poll_once()
        assert t.polls==[3]
        assert [text for _,text,_ in t.sent]==["Diese Relevanzantwort wurde bereits verarbeitet."]

        # Even a replay is schema-validated before any raw Telegram fields are used.
        t.updates=[{"update_id":2,"message":{"private":"not trusted"}}]
        c.poll_once()
        assert [text for _,text,_ in t.sent]==["Diese Relevanzantwort wurde bereits verarbeitet."]

@pytest.mark.parametrize("classification", [
    "non_binding", "already_completed", "change", "cancellation", "recurring", "unsupported",
])
def test_non_creatable_classifications_stay_manual_after_telegram_interaction(tmp_path, classification):
    writer = Writer()
    with JsonStore(tmp_path / classification) as store:
        dialog, transport, _ = controller(store, writers={"todoist": writer})
        item = proposal(classification=classification)
        dialog.send_proposal(item)
        markup = transport.sent[-1][2]["inline_keyboard"]
        assert [button["text"] for button in markup[0]] == ["Manuell prüfen", "Verwerfen"]
        assert "Extern anlegbar: Nein – manuell prüfen" in transport.sent[-1][1]
        transport.updates = [callback(1, Decision(mail_id=item.source_mail_id, proposal_id=item.id,
                                                   version=item.version, action=DecisionAction.CONFIRM).encode())]
        dialog.poll_once()
        assert writer.created == 0 and writer.reconciled == 0
        assert transport.answered[-1][1] == "Aktion wird verarbeitet …"
        assert "konnte nicht verarbeitet" in transport.sent[-1][1]
        dialog.write_executor.execute(item.model_copy(update={"status": ProposalStatus.CONFIRMED}))
        assert writer.created == 0 and writer.reconciled == 0


@pytest.mark.parametrize(("changes", "expected_status"), [
    ({"responsibility": "other"}, ProposalStatus.NEEDS_CLARIFICATION),
    ({"responsibility": "unclear"}, ProposalStatus.NEEDS_CLARIFICATION),
    ({"certainty": "uncertain"}, ProposalStatus.NEEDS_CLARIFICATION),
    ({"certainty": "contradictory"}, ProposalStatus.NEEDS_CLARIFICATION),
])
def test_responsibility_and_uncertainty_are_not_writable(changes, expected_status):
    item = proposal(**changes)
    assert item.status == expected_status
    writer = Writer()
    with pytest.raises(ValueError, match="neue, sichere und eigene"):
        from mailhelp.integrations import execute_confirmed
        execute_confirmed(item.model_copy(update={"status": ProposalStatus.CONFIRMED}), writer, lambda _: None)
    assert writer.created == 0 and writer.reconciled == 0
    decision = Decision(mail_id=item.source_mail_id, proposal_id=item.id, version=item.version, action=DecisionAction.CONFIRM)
    if expected_status == ProposalStatus.PENDING_CONFIRMATION:
        with pytest.raises(ValueError, match="manuellen Prüfung"):
            from mailhelp.telegram import apply_decision
            apply_decision(item, decision, 1, 2, 1, 2)


def test_classification_fields_are_required_and_closed():
    raw = proposal().model_dump()
    for field in ("responsibility", "certainty", "classification"):
        missing = {**raw}
        missing.pop(field)
        with pytest.raises(ValidationError):
            Proposal.model_validate(missing)
    for field in ("responsibility", "certainty", "classification"):
        with pytest.raises(ValidationError):
            Proposal.model_validate({**raw, field: "invalid"})


def test_calendar_duplicate_outcomes_are_reported_without_claiming_creation(tmp_path):
    class DuplicateWriter(Writer):
        def __init__(self, operation):
            super().__init__(); self.operation=operation
        def create(self,p,key):
            self.created += 1
            return {"id":"existing", "operation":self.operation}
    for index,(operation,phrase) in enumerate([
        ("duplicate_updated","fehlende Informationen wurden ergänzt"),
        ("duplicate_skipped","Kein neuer Termin wurde angelegt"),
    ]):
        with JsonStore(tmp_path/str(index)) as store:
            item=proposal(kind="event",start="2026-05-10T10:00:00+00:00",
                          end="2026-05-10T11:00:00+00:00")
            decision=f"proposal:{item.source_mail_id}:{item.id}:1:confirm"
            dialog,telegram,_=controller(store,[callback(1,decision)],
                                          {"google_calendar":DuplicateWriter(operation)})
            dialog.persist(item); dialog.poll_once()
            assert any(phrase in text for _,text,_ in telegram.sent)
            assert not any(text.startswith("Erstellt:") for _,text,_ in telegram.sent)
