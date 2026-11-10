"""5.1 (R1): how a mail was actually processed, read from its stored state only.

The explanation uses stored outcomes and fixed texts. It never asks a model to
justify an earlier decision afterwards. A reason a model gave is shown as that
model's assessment, not as a fact about the mail. "Nothing found", "not
checked", "failed" and "no longer retained" are different outcomes: an empty
list alone is never reported as success.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum

from ..domain.extraction import ExtractionCountConflict
from ..domain.mail import MailState
from ..domain.processing import ProcessingError, ProcessingErrorCode, ProcessingStage
from ..domain.proposal import ProposalStatus
from ..processing.perspective import SELF_NOTE_REASON
from .views import STATUS_LABELS


class Outcome(StrEnum):
    DONE = "done"
    SKIPPED = "skipped"
    FAILED = "failed"
    PENDING = "pending"
    MISSING = "missing"


OUTCOME_LABELS = {
    Outcome.DONE: "Erledigt",
    Outcome.SKIPPED: "Ausgelassen",
    Outcome.FAILED: "Fehlgeschlagen",
    Outcome.PENDING: "Ausstehend",
    Outcome.MISSING: "Nicht mehr aufbewahrt",
}

# Reasons Mailhelp sets itself by a rule; every other stored reason came from a model.
RULE_REASONS = {
    "Absender-Vorfilter": "Absender durch deine Ausschlussregel gefiltert.",
    "Eigenes Postfach-Briefing": "Eigener automatisch erzeugter Inhalt erkannt.",
    "IServ-Elternbrief: immer relevant": "IServ-Elternbrief: immer relevant.",
    "Kein relevantes Thema für dieses Postfach": "Für dieses Postfach ist kein Thema eingeschaltet.",
    "Großer Anhang: manuelle Prüfung nötig": "Großer Anhang: manuelle Prüfung nötig.",
    "Telegram-Entscheidung": "Von dir entschieden.",
    SELF_NOTE_REASON: "Eigene Notiz: immer relevant.",
}

ERROR_TEXTS = {
    ProcessingErrorCode.MIME_LIMIT_EXCEEDED: "Die Mail überschreitet die Größen- oder Teilegrenze.",
    ProcessingErrorCode.LLM_SCHEMA_VALIDATION_EXHAUSTED: "Das Modell lieferte wiederholt keine gültige Antwort.",
    ProcessingErrorCode.PROVIDER_RESPONSE_INVALID: "Der Modellanbieter lieferte eine unbrauchbare Antwort.",
    ProcessingErrorCode.INVALID_JSON: "Die Modellantwort war kein gültiges JSON.",
    ProcessingErrorCode.SCHEMA_VALIDATION_FAILED: "Die Modellantwort passte nicht zum erwarteten Format.",
    ProcessingErrorCode.PERMANENT_ADAPTER_ERROR: "Ein Dienst lehnte die Anfrage dauerhaft ab.",
    ProcessingErrorCode.LLM_RATE_LIMITED: "Das Abfragelimit des Modellanbieters war erreicht.",
    ProcessingErrorCode.INTERNAL_ERROR: "Interner Fehler bei der Verarbeitung.",
}

# The stored error belongs to these explanation steps.
ERROR_STEPS = {
    ProcessingStage.PREPARATION: "intake",
    ProcessingStage.RELEVANCE: "relevance",
    ProcessingStage.SUMMARY: "relevance",
    ProcessingStage.SUMMARY_NOTIFICATION: "relevance",
    ProcessingStage.ACTION_DETECTION: "decision",
    ProcessingStage.ACTION_ROUTER: "decision",
    ProcessingStage.TASK_EXTRACTION: "extraction",
    ProcessingStage.EVENT_EXTRACTION: "extraction",
    ProcessingStage.NORMALIZATION: "assessment",
    ProcessingStage.PROPOSAL_BUILDING: "assessment",
    ProcessingStage.DUPLICATE_PRECHECK: "assessment",
    ProcessingStage.PROPOSAL_NOTIFICATION: "assessment",
    ProcessingStage.COMPLETION: "assessment",
}

OPEN = {ProposalStatus.PENDING_CONFIRMATION, ProposalStatus.NEEDS_CLARIFICATION}


@dataclass(frozen=True)
class Step:
    key: str
    title: str
    outcome: Outcome
    text: str
    # A reason a model gave, shown as its assessment; never a fact about the mail.
    model_reason: str | None = None
    notes: tuple[str, ...] = ()
    # Topic ids of the relevance step; the view shows their configured names (5.1.1).
    topics: tuple[str, ...] = ()


@dataclass(frozen=True)
class Explanation:
    mail_id: str
    analysis_round: int
    content_retained: bool
    steps: tuple[Step, ...]
    result: Step


def _plural(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


def _failed(key: str, title: str, error: ProcessingError) -> Step:
    retry = " Ein neuer Versuch folgt automatisch." if error.retryable else ""
    return Step(key, title, Outcome.FAILED, ERROR_TEXTS[error.code] + retry)


def _error_for(state: MailState, key: str) -> ProcessingError | None:
    return state.error if state.error is not None and ERROR_STEPS.get(state.error.stage) == key else None


def _intake(state: MailState) -> Step:
    title = "Eingang und Vorfilter"
    if (error := _error_for(state, "intake")) is not None:
        return _failed("intake", title, error)
    if state.duplicate is not None and state.duplicate.outcome == "duplicate":
        return Step("intake", title, Outcome.SKIPPED,
                    "Doppelt empfangen; es gilt die zuerst verarbeitete Mail.")
    if state.steps.preparation == "pending":
        return Step("intake", title, Outcome.PENDING, "Die Mail wird noch vorbereitet.")
    notes = []
    if state.duplicate is not None and state.duplicate.outcome == "ambiguous":
        notes.append("Möglicherweise doppelt empfangen; Mailhelp hat sie vorsorglich einzeln geprüft.")
    if state.mail is None:
        notes.append("Der Mailinhalt wurde nach der Aufbewahrungsregel entfernt.")
    text = ("Von dir selbst gesendet (eigene Notiz)." if state.self_mail
            else "Weiterleitung mit eigener Notiz erkannt." if state.is_forwarding
            else "Mail empfangen und gelesen.")
    return Step("intake", title, Outcome.DONE, text, notes=tuple(notes))


def _relevance(state: MailState) -> Step:
    title = "Relevanz"
    if (error := _error_for(state, "relevance")) is not None:
        return _failed("relevance", title, error)
    if state.steps.relevance == "skipped":
        return Step("relevance", title, Outcome.SKIPPED, "Nicht geprüft.")
    if state.steps.relevance == "pending":
        return Step("relevance", title, Outcome.PENDING,
                    "Wartet auf deine Entscheidung, ob die Mail relevant ist." if state.awaiting_relevance
                    else "Noch nicht geprüft.")
    if state.relevance is None:
        return Step("relevance", title, Outcome.MISSING, "Das Ergebnis wird nicht mehr aufbewahrt.")
    relevance = state.relevance
    text = {"relevant": "Als relevant eingestuft.",
            "irrelevant": "Als irrelevant eingeordnet; die Aktionsanalyse wurde ausgelassen.",
            "unclear": "Relevanz unklar."}[relevance.decision]
    topics = tuple(relevance.topic_ids)
    if relevance.reason in RULE_REASONS:
        return Step("relevance", title, Outcome.DONE, f"{text} {RULE_REASONS[relevance.reason]}", topics=topics)
    return Step("relevance", title, Outcome.DONE, text, model_reason=relevance.reason, topics=topics)


def _irrelevant(state: MailState) -> bool:
    return state.relevance is not None and state.relevance.decision == "irrelevant"


def _decision(state: MailState) -> Step:
    title = "Aktionsentscheidung"
    if (error := _error_for(state, "decision")) is not None:
        return _failed("decision", title, error)
    step = state.steps.action_router
    if step == "skipped":
        return Step("decision", title, Outcome.SKIPPED,
                    "Ausgelassen, weil die Mail als irrelevant gilt." if _irrelevant(state) else "Ausgelassen.")
    if step == "failed":
        return Step("decision", title, Outcome.FAILED, "Die Aktionsentscheidung ist fehlgeschlagen.")
    if step == "pending":
        return Step("decision", title, Outcome.PENDING, "Noch nicht geprüft.")
    route = state.action_route
    if route is None:
        return Step("decision", title, Outcome.MISSING, "Das Ergebnis wird nicht mehr aufbewahrt.")
    tasks = _plural(route.task_count, "mögliche Aufgabe", "mögliche Aufgaben")
    events = _plural(route.event_count, "möglichen Termin", "mögliche Termine")
    text = {"none": "Keine Aufgabe und kein Termin erkannt; die Mail gilt als Information ohne Handlungsbedarf.",
            "task": f"Erkannt: {tasks}, kein Termin.",
            "event": f"Erkannt: {events}, keine Aufgabe.",
            "task_and_event": f"Erkannt: {tasks} und {events}.",
            "unclear": f"Unklar: {tasks} und {events} zur Prüfung."}[route.action_state]
    return Step("decision", title, Outcome.DONE, text, model_reason=route.reason)


def _extraction(state: MailState) -> Step:
    title = "Extraktion"
    if (error := _error_for(state, "extraction")) is not None:
        return _failed("extraction", title, error)
    steps = (state.steps.task_extraction, state.steps.event_extraction)
    if "failed" in steps:
        return Step("extraction", title, Outcome.FAILED, "Die Extraktion ist fehlgeschlagen.")
    if "pending" in steps:
        return Step("extraction", title, Outcome.PENDING, "Noch nicht extrahiert.")
    if steps == ("skipped", "skipped"):
        none = state.action_route is not None and state.action_route.action_state == "none"
        return Step("extraction", title, Outcome.SKIPPED,
                    "Nicht nötig, weil keine Aktion erkannt wurde." if none else "Ausgelassen.")
    task_done, event_done = (step == "completed" for step in steps)
    if (task_done and state.task_extraction is None) or (event_done and state.event_extraction is None):
        return Step("extraction", title, Outcome.MISSING, "Das Ergebnis wird nicht mehr aufbewahrt.")
    tasks = len(state.task_extraction.tasks) if state.task_extraction is not None else 0
    events = len(state.event_extraction.events) if state.event_extraction is not None else 0
    text = (f"{_plural(tasks, 'Aufgabe', 'Aufgaben')} und "
            f"{_plural(events, 'Termin', 'Termine')} extrahiert.")
    notes = tuple(_conflict_note(conflict) for conflict in state.extraction_count_conflicts)
    return Step("extraction", title, Outcome.DONE, text, notes=notes)


def _conflict_note(conflict: ExtractionCountConflict) -> str:
    """A router count the extraction did not match, e.g. two expected tasks and one extracted."""
    names = ("Aufgabe", "Aufgaben") if conflict.category == "task" else ("Termin", "Termine")
    verb = "wurde" if conflict.actual_count == 1 else "wurden"
    return f"Router erwartete {_plural(conflict.expected_count, *names)}; {conflict.actual_count} {verb} extrahiert."


def _assessment(state: MailState) -> Step:
    title = "Bewertung und Abgleich"
    if (error := _error_for(state, "assessment")) is not None:
        return _failed("assessment", title, error)
    if state.proposals:
        counts = Counter(proposal.status for proposal in state.proposals)
        parts = [f"{count} × {STATUS_LABELS[status]}" for status, count in sorted(counts.items())]
        return Step("assessment", title, Outcome.DONE, ", ".join(parts) + ".")
    building = state.steps.proposal_building
    if building == "completed":
        return Step("assessment", title, Outcome.DONE, "Keine Vorschläge gebildet.")
    if building == "failed":
        return Step("assessment", title, Outcome.FAILED, "Die Vorschläge konnten nicht gebildet werden.")
    if building == "pending":
        return Step("assessment", title, Outcome.PENDING, "Noch keine Vorschläge gebildet.")
    return Step("assessment", title, Outcome.SKIPPED, "Ausgelassen.")


def _result(state: MailState, steps: tuple[Step, ...]) -> Step:
    title = "Ergebnis"
    if state.error is not None or any(step.outcome == Outcome.FAILED for step in steps):
        return Step("result", title, Outcome.FAILED, "Die Auswertung ist wegen eines Fehlers unvollständig.")
    if steps[0].outcome == Outcome.SKIPPED:
        return Step("result", title, Outcome.SKIPPED, "Nicht ausgewertet, weil die Mail doppelt empfangen wurde.")
    if any(step.outcome == Outcome.PENDING for step in steps):
        return Step("result", title, Outcome.PENDING, "Die Verarbeitung läuft noch.")
    open_ = Counter(proposal.status for proposal in state.proposals if proposal.status in OPEN)
    if open_:
        parts = []
        if confirm := open_[ProposalStatus.PENDING_CONFIRMATION]:
            parts.append(_plural(confirm, "Vorschlag wartet", "Vorschläge warten") + " auf deine Bestätigung")
        if clarify := open_[ProposalStatus.NEEDS_CLARIFICATION]:
            parts.append(_plural(clarify, "Vorschlag braucht", "Vorschläge brauchen") + " eine Klärung")
        return Step("result", title, Outcome.DONE, "; ".join(parts) + ".")
    if state.proposals:
        return Step("result", title, Outcome.DONE, "Alle Vorschläge dieser Mail sind entschieden.")
    if _irrelevant(state):
        return Step("result", title, Outcome.DONE, "Als irrelevant abgelegt; keine Aktion nötig.")
    if any(step.outcome == Outcome.MISSING for step in steps):
        return Step("result", title, Outcome.MISSING,
                    "Kein Vorschlag; die Gründe werden nicht mehr vollständig aufbewahrt.")
    return Step("result", title, Outcome.DONE, "Keine Aktion erkannt.")


def explain(state: MailState) -> Explanation:
    """The stored processing path of one mail, step by step, with fixed texts."""
    steps = (_intake(state), _relevance(state), _decision(state), _extraction(state), _assessment(state))
    return Explanation(mail_id=state.id, analysis_round=state.analysis_round,
                       content_retained=state.mail is not None, steps=steps, result=_result(state, steps))
