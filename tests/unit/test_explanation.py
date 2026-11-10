"""5.1 R1: the processing path of a mail, from stored state only, with distinct outcomes."""
from datetime import UTC, datetime

import pytest

from mailhelp.domain.duplicate import DuplicateDecision
from mailhelp.domain.extraction import (
    ActionRoute,
    EventExtraction,
    ExtractedEvent,
    ExtractedTask,
    ExtractionCountConflict,
    TaskExtraction,
)
from mailhelp.domain.mail import MailState
from mailhelp.domain.processing import ProcessingError, ProcessingErrorCode, ProcessingStage
from mailhelp.domain.relevance import Relevance, RelevanceDialog
from mailhelp.processing.perspective import SELF_NOTE_REASON
from mailhelp.review.explanation import ERROR_STEPS, ERROR_TEXTS, OUTCOME_LABELS, Outcome, explain
from tests.scenarios.web_scenario import mail_id, proposal

NOW = datetime(2026, 11, 9, 9, tzinfo=UTC)
MAIL = mail_id(5)
TASK = ExtractedTask(title="Antrag abgeben", description="", evidence="Bitte bis Freitag abgeben.",
                     responsibility="user", certainty="certain", classification="new")
EVENT = ExtractedEvent(title="Elternabend", evidence="Elternabend am 12.11.", time_requirement="all_day",
                       responsibility="user", certainty="certain", classification="new")
DONE_STEPS = dict(preparation="completed", relevance="completed", summary="completed",
                  action_detection="completed", action_router="completed", task_extraction="completed",
                  event_extraction="completed", normalization="completed", proposal_building="completed",
                  duplicate_precheck="completed", completion="completed")


def state(steps=None, **fields):
    return MailState(id=MAIL, config_fingerprint="f" * 64,
                     imap={"account_id": "0" * 24, "folder": "INBOX", "uidvalidity": 1, "uid": 5},
                     created_at=NOW, mail=fields.pop("mail", {"text": "synthetisch"}),
                     steps={**DONE_STEPS, **(steps or {})}, **fields)


def route(action_state, tasks=0, events=0, reason="Modell: Frist zur Abgabe genannt."):
    return ActionRoute(action_state=action_state, task_count=tasks, event_count=events, reason=reason)


def steps_of(explanation):
    return {step.key: step for step in explanation.steps}


def test_a_complete_task_mail_names_every_step_and_marks_model_reasons():
    item = state(relevance=Relevance(decision="relevant", topic_ids=["schule"], reason="Schulthema laut Modell"),
                 action_route=route("task", tasks=1), task_extraction=TaskExtraction(tasks=[TASK]),
                 event_extraction=EventExtraction(events=[]), analysis_round=2,
                 proposals=[proposal(5, "a"), proposal(5, "b", status="needs_clarification", open_questions=["?"])])
    explanation = explain(item)
    steps = steps_of(explanation)
    assert (explanation.mail_id, explanation.analysis_round, explanation.content_retained) == (MAIL, 2, True)
    assert [step.key for step in explanation.steps] == ["intake", "relevance", "decision", "extraction", "assessment"]
    assert steps["intake"].text == "Mail empfangen und gelesen." and steps["intake"].notes == ()
    assert steps["relevance"].text == "Als relevant eingestuft."
    # A stored model reason stays a model assessment, never part of the fixed text.
    assert steps["relevance"].model_reason == "Schulthema laut Modell"
    assert (steps["relevance"].notes, steps["relevance"].topics) == ((), ("schule",))
    assert steps["decision"].text == "Erkannt: 1 mögliche Aufgabe, kein Termin."
    assert steps["decision"].model_reason == "Modell: Frist zur Abgabe genannt."
    assert steps["extraction"].text == "1 Aufgabe und 0 Termine extrahiert."
    assert steps["assessment"].text == "1 × Klärung nötig, 1 × Wartet auf Bestätigung."
    assert explanation.result.text == ("1 Vorschlag wartet auf deine Bestätigung; "
                                       "1 Vorschlag braucht eine Klärung.")
    assert all(step.outcome == Outcome.DONE for step in explanation.steps)


@pytest.mark.parametrize(("action_state", "tasks", "events", "text"), [
    ("event", 0, 2, "Erkannt: 2 mögliche Termine, keine Aufgabe."),
    ("task_and_event", 2, 1, "Erkannt: 2 mögliche Aufgaben und 1 möglichen Termin."),
    ("unclear", 1, 0, "Unklar: 1 mögliche Aufgabe und 0 mögliche Termine zur Prüfung."),
])
def test_each_router_outcome_has_its_own_text(action_state, tasks, events, text):
    item = state(relevance=Relevance(decision="relevant", topic_ids=[], reason="x"),
                 action_route=route(action_state, tasks, events),
                 task_extraction=TaskExtraction(tasks=[]), event_extraction=EventExtraction(events=[EVENT]))
    assert steps_of(explain(item))["decision"].text == text


def test_no_action_is_reported_as_such_and_extraction_as_not_needed():
    item = state(steps=dict(task_extraction="skipped", event_extraction="skipped", proposal_building="completed"),
                 relevance=Relevance(decision="relevant", topic_ids=[], reason="x"), action_route=route("none"))
    explanation = explain(item)
    steps = steps_of(explanation)
    assert steps["decision"].text.startswith("Keine Aufgabe und kein Termin erkannt")
    assert (steps["extraction"].outcome, steps["extraction"].text) == (
        Outcome.SKIPPED, "Nicht nötig, weil keine Aktion erkannt wurde.")
    assert steps["assessment"].text == "Keine Vorschläge gebildet."
    assert (explanation.result.outcome, explanation.result.text) == (Outcome.DONE, "Keine Aktion erkannt.")


def test_an_irrelevant_mail_explains_the_skipped_analysis_and_rule_reasons_are_no_model_reasons():
    skipped = {key: "skipped" for key in ("summary", "action_detection", "action_router", "task_extraction",
                                          "event_extraction", "normalization", "proposal_building",
                                          "duplicate_precheck")}
    item = state(steps=skipped, relevance=Relevance(decision="irrelevant", topic_ids=[], reason="Absender-Vorfilter"))
    explanation = explain(item)
    steps = steps_of(explanation)
    assert steps["relevance"].text == ("Als irrelevant eingeordnet; die Aktionsanalyse wurde ausgelassen. "
                                       "Absender durch deine Ausschlussregel gefiltert.")
    assert steps["relevance"].model_reason is None
    assert steps["decision"].text == "Ausgelassen, weil die Mail als irrelevant gilt."
    assert (steps["extraction"].text, steps["assessment"].text) == ("Ausgelassen.", "Ausgelassen.")
    assert explanation.result.text == "Als irrelevant abgelegt; keine Aktion nötig."


def test_own_notes_and_forwardings_are_named():
    own = state(self_mail=True, user_note="Merken",
                relevance=Relevance(decision="relevant", topic_ids=[], reason=SELF_NOTE_REASON))
    assert steps_of(explain(own))["intake"].text == "Von dir selbst gesendet (eigene Notiz)."
    assert steps_of(explain(own))["relevance"].text == "Als relevant eingestuft. Eigene Notiz: immer relevant."
    forwarded = state(is_forwarding=True)
    assert steps_of(explain(forwarded))["intake"].text == "Weiterleitung mit eigener Notiz erkannt."
    unclear = state(relevance=Relevance(decision="unclear", topic_ids=[], reason="Modell unsicher"))
    assert steps_of(explain(unclear))["relevance"].text == "Relevanz unklar."


def test_retention_is_reported_as_missing_and_never_as_nothing_found():
    item = state(mail=None, relevance=None, action_route=None, task_extraction=None, event_extraction=None)
    explanation = explain(item)
    steps = steps_of(explanation)
    assert explanation.content_retained is False
    assert steps["intake"].notes == ("Der Mailinhalt wurde nach der Aufbewahrungsregel entfernt.",)
    for key in ("relevance", "decision", "extraction"):
        assert (steps[key].outcome, steps[key].text) == (Outcome.MISSING, "Das Ergebnis wird nicht mehr aufbewahrt.")
    assert (explanation.result.outcome, explanation.result.text) == (
        Outcome.MISSING, "Kein Vorschlag; die Gründe werden nicht mehr vollständig aufbewahrt.")


def test_a_relevance_question_and_unfinished_steps_are_pending():
    dialog = RelevanceDialog(mail_id=MAIL)
    waiting = state(steps=dict(relevance="pending", action_router="pending", task_extraction="pending",
                               proposal_building="pending"),
                    awaiting_relevance=True, relevance_dialog=dialog)
    explanation = explain(waiting)
    steps = steps_of(explanation)
    assert steps["relevance"].text == "Wartet auf deine Entscheidung, ob die Mail relevant ist."
    assert (steps["decision"].outcome, steps["extraction"].text, steps["assessment"].text) == (
        Outcome.PENDING, "Noch nicht extrahiert.", "Noch keine Vorschläge gebildet.")
    assert (explanation.result.outcome, explanation.result.text) == (Outcome.PENDING, "Die Verarbeitung läuft noch.")
    fresh = state(steps=dict(preparation="pending", relevance="pending"))
    assert steps_of(explain(fresh))["intake"].text == "Die Mail wird noch vorbereitet."
    assert steps_of(explain(fresh))["relevance"].text == "Noch nicht geprüft."


@pytest.mark.parametrize("stage", list(ProcessingStage))
def test_a_stored_error_appears_at_its_step_and_makes_the_result_incomplete(stage):
    error = ProcessingError(code=ProcessingErrorCode.INVALID_JSON, stage=stage, occurred_at=NOW, retryable=True)
    explanation = explain(state(error=error))
    failed = steps_of(explanation)[ERROR_STEPS[stage]]
    assert (failed.outcome, failed.text) == (
        Outcome.FAILED, "Die Modellantwort war kein gültiges JSON. Ein neuer Versuch folgt automatisch.")
    assert (explanation.result.outcome, explanation.result.text) == (
        Outcome.FAILED, "Die Auswertung ist wegen eines Fehlers unvollständig.")


def test_every_error_code_and_outcome_has_a_text():
    assert set(ERROR_TEXTS) == set(ProcessingErrorCode) and set(OUTCOME_LABELS) == set(Outcome)
    error = ProcessingError(code=ProcessingErrorCode.MIME_LIMIT_EXCEEDED, stage="preparation", occurred_at=NOW)
    assert steps_of(explain(state(error=error)))["intake"].text == "Die Mail überschreitet die Größen- oder Teilegrenze."


def test_failed_steps_without_a_stored_error_still_count_as_failed():
    explanation = explain(state(steps=dict(action_router="failed", task_extraction="failed",
                                           proposal_building="failed")))
    steps = steps_of(explanation)
    assert [steps[key].outcome for key in ("decision", "extraction", "assessment")] == [Outcome.FAILED] * 3
    assert explanation.result.outcome == Outcome.FAILED


def test_count_conflicts_and_ambiguous_duplicates_are_noted():
    conflicts = [ExtractionCountConflict(category="task", expected_count=2, actual_count=1,
                                         router_call_id="r", extractor_call_id="t"),
                 ExtractionCountConflict(category="event", expected_count=1, actual_count=0,
                                         router_call_id="r", extractor_call_id="e")]
    item = state(relevance=Relevance(decision="relevant", topic_ids=[], reason="x"),
                 action_route=route("task_and_event", 2, 1), task_extraction=TaskExtraction(tasks=[TASK]),
                 event_extraction=EventExtraction(events=[]), extraction_count_conflicts=conflicts,
                 duplicate=DuplicateDecision(outcome="ambiguous", reason="multiple_message_ids",
                                             previous_mail_id=mail_id(4)))
    steps = steps_of(explain(item))
    assert steps["extraction"].notes == ("Router erwartete 2 Aufgaben; 1 wurde extrahiert.",
                                         "Router erwartete 1 Termin; 0 wurden extrahiert.")
    assert steps["intake"].notes == ("Möglicherweise doppelt empfangen; Mailhelp hat sie vorsorglich einzeln geprüft.",)


def test_a_duplicate_is_not_evaluated_and_decided_proposals_are_named():
    skipped = {key: "skipped" for key in ("relevance", "summary", "action_detection", "action_router",
                                          "task_extraction", "event_extraction", "proposal_building")}
    duplicate = state(steps=skipped, duplicate=DuplicateDecision(outcome="duplicate", reason="same_message",
                                                                 previous_mail_id=mail_id(4)))
    explanation = explain(duplicate)
    assert steps_of(explanation)["intake"].text == "Doppelt empfangen; es gilt die zuerst verarbeitete Mail."
    assert steps_of(explanation)["relevance"].text == "Nicht geprüft."
    assert explanation.result.text == "Nicht ausgewertet, weil die Mail doppelt empfangen wurde."
    decided = state(relevance=Relevance(decision="relevant", topic_ids=[], reason="x"),
                    action_route=route("task", 1), task_extraction=TaskExtraction(tasks=[TASK]),
                    event_extraction=EventExtraction(events=[]), proposals=[proposal(5, "a", status="rejected")])
    assert explain(decided).result.text == "Alle Vorschläge dieser Mail sind entschieden."
    assert steps_of(explain(decided))["assessment"].text == "1 × Verworfen."


def test_a_lost_extraction_of_a_completed_step_is_missing():
    item = state(relevance=Relevance(decision="relevant", topic_ids=[], reason="x"), action_route=route("task", 1),
                 task_extraction=None, event_extraction=EventExtraction(events=[]))
    assert steps_of(explain(item))["extraction"].outcome == Outcome.MISSING
    events_only = state(steps=dict(task_extraction="skipped"),
                        relevance=Relevance(decision="relevant", topic_ids=[], reason="x"),
                        action_route=route("event", 0, 1), event_extraction=EventExtraction(events=[EVENT]))
    assert steps_of(explain(events_only))["extraction"].text == "0 Aufgaben und 1 Termin extrahiert."


def test_only_clarifications_or_only_confirmations_name_just_that():
    relevant = Relevance(decision="relevant", topic_ids=[], reason="x")
    def result(*items):
        return explain(state(relevance=relevant, action_route=route("task", 2),
                             task_extraction=TaskExtraction(tasks=[TASK, TASK]),
                             event_extraction=EventExtraction(events=[]), proposals=list(items))).result.text
    clarify = proposal(5, "b", status="needs_clarification", open_questions=["?"])
    assert result(clarify) == "1 Vorschlag braucht eine Klärung."
    assert result(proposal(5, "a"), proposal(5, "c")) == "2 Vorschläge warten auf deine Bestätigung."
