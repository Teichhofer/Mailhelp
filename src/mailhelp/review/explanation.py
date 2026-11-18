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
from ..i18n import msg, tr
from ..processing.perspective import SELF_NOTE_REASON
from .views import STATUS_LABELS


class Outcome(StrEnum):
    DONE = "done"
    SKIPPED = "skipped"
    FAILED = "failed"
    PENDING = "pending"
    MISSING = "missing"


OUTCOME_LABELS = {
    Outcome.DONE: msg("Erledigt"),
    Outcome.SKIPPED: msg("Ausgelassen"),
    Outcome.FAILED: msg("Fehlgeschlagen"),
    Outcome.PENDING: msg("Ausstehend"),
    Outcome.MISSING: msg("Nicht mehr aufbewahrt"),
}

# Reasons Mailhelp sets itself by a rule; every other stored reason came from a model.
RULE_REASONS = {
    "Absender-Vorfilter": msg("Absender durch deine Ausschlussregel gefiltert."),
    "Eigenes Postfach-Briefing": msg("Eigener automatisch erzeugter Inhalt erkannt."),
    "IServ-Elternbrief: immer relevant": msg("IServ-Elternbrief: immer relevant."),
    "Kein relevantes Thema für dieses Postfach": msg("Für dieses Postfach ist kein Thema eingeschaltet."),
    "Großer Anhang: manuelle Prüfung nötig": msg("Großer Anhang: manuelle Prüfung nötig."),
    "Telegram-Entscheidung": msg("Von dir entschieden."),
    SELF_NOTE_REASON: msg("Eigene Notiz: immer relevant."),
}

# 7.7.2: reasons of prefilter rules name the rule after the prefix.
RULE_PREFIXES = ("Vorfilter: ", "VIP-Absender: ")

ERROR_TEXTS = {
    ProcessingErrorCode.ANALYSIS_DATA_REMOVED: msg(
        "Aktionserkennung nicht nachholbar – Analyse-Daten nach Aufbewahrung entfernt."
    ),
    ProcessingErrorCode.MIME_LIMIT_EXCEEDED: msg("Die Mail überschreitet die Größen- oder Teilegrenze."),
    ProcessingErrorCode.LLM_SCHEMA_VALIDATION_EXHAUSTED: msg("Das Modell lieferte wiederholt keine gültige Antwort."),
    ProcessingErrorCode.PROVIDER_RESPONSE_INVALID: msg("Der Modellanbieter lieferte eine unbrauchbare Antwort."),
    ProcessingErrorCode.INVALID_JSON: msg("Die Modellantwort war kein gültiges JSON."),
    ProcessingErrorCode.SCHEMA_VALIDATION_FAILED: msg("Die Modellantwort passte nicht zum erwarteten Format."),
    ProcessingErrorCode.PERMANENT_ADAPTER_ERROR: msg("Ein Dienst lehnte die Anfrage dauerhaft ab."),
    ProcessingErrorCode.LLM_RATE_LIMITED: msg("Das Abfragelimit des Modellanbieters war erreicht."),
    ProcessingErrorCode.INTERNAL_ERROR: msg("Interner Fehler bei der Verarbeitung."),
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
    return f"{count} {tr(one if count == 1 else many)}"


def _failed(key: str, title: str, error: ProcessingError) -> Step:
    retry = tr(" Ein neuer Versuch folgt automatisch.") if error.retryable else ""
    return Step(key, title, Outcome.FAILED, str(ERROR_TEXTS[error.code]) + retry)


def _error_for(state: MailState, key: str) -> ProcessingError | None:
    return state.error if state.error is not None and ERROR_STEPS.get(state.error.stage) == key else None


def _intake(state: MailState) -> Step:
    title = tr("Eingang und Vorfilter")
    if (error := _error_for(state, "intake")) is not None:
        return _failed("intake", title, error)
    if state.duplicate is not None and state.duplicate.outcome == "duplicate":
        return Step("intake", title, Outcome.SKIPPED, tr("Doppelt empfangen; es gilt die zuerst verarbeitete Mail."))
    if state.steps.preparation == "pending":
        return Step("intake", title, Outcome.PENDING, tr("Die Mail wird noch vorbereitet."))
    notes = []
    if state.duplicate is not None and state.duplicate.outcome == "ambiguous":
        notes.append(tr("Möglicherweise doppelt empfangen; Mailhelp hat sie vorsorglich einzeln geprüft."))
    if state.mail is None:
        notes.append(tr("Der Mailinhalt wurde nach der Aufbewahrungsregel entfernt."))
    text = (
        tr("Von dir selbst gesendet (eigene Notiz).")
        if state.self_mail
        else tr("Weiterleitung mit eigener Notiz erkannt.")
        if state.is_forwarding
        else tr("Mail empfangen und gelesen.")
    )
    return Step("intake", title, Outcome.DONE, text, notes=tuple(notes))


def _relevance(state: MailState) -> Step:
    title = tr("Relevanz")
    if (error := _error_for(state, "relevance")) is not None:
        return _failed("relevance", title, error)
    if state.steps.relevance == "skipped":
        return Step("relevance", title, Outcome.SKIPPED, tr("Nicht geprüft."))
    if state.steps.relevance == "pending":
        return Step(
            "relevance",
            title,
            Outcome.PENDING,
            tr("Wartet auf deine Entscheidung, ob die Mail relevant ist.")
            if state.awaiting_relevance
            else tr("Noch nicht geprüft."),
        )
    if state.relevance is None:
        return Step("relevance", title, Outcome.MISSING, "Das Ergebnis wird nicht mehr aufbewahrt.")
    relevance = state.relevance
    text = {
        "relevant": tr("Als relevant eingestuft."),
        "irrelevant": tr("Als irrelevant eingeordnet; die Aktionsanalyse wurde ausgelassen."),
        "unclear": tr("Relevanz unklar."),
    }[relevance.decision]
    topics = tuple(relevance.topic_ids)
    if relevance.reason in RULE_REASONS:
        return Step("relevance", title, Outcome.DONE, f"{text} {str(RULE_REASONS[relevance.reason])}", topics=topics)
    if relevance.reason.startswith(RULE_PREFIXES):
        # 7.7.2: decided by a named prefilter rule, without a model call.
        prefix = next(prefix for prefix in RULE_PREFIXES if relevance.reason.startswith(prefix))
        reason = tr(prefix) + relevance.reason[len(prefix) :]
        return Step(
            "relevance",
            title,
            Outcome.DONE,
            tr("{decision} {reason} – ohne KI-Aufruf.", decision=text, reason=reason),
            topics=topics,
        )
    return Step("relevance", title, Outcome.DONE, text, model_reason=relevance.reason, topics=topics)


def _irrelevant(state: MailState) -> bool:
    return state.relevance is not None and state.relevance.decision == "irrelevant"


def _decision(state: MailState) -> Step:
    title = tr("Aktionsentscheidung")
    if (error := _error_for(state, "decision")) is not None:
        return _failed("decision", title, error)
    step = state.steps.action_router
    if step == "skipped":
        return Step(
            "decision",
            title,
            Outcome.SKIPPED,
            tr("Ausgelassen, weil die Mail als irrelevant gilt.") if _irrelevant(state) else tr("Ausgelassen."),
        )
    if step == "failed":
        return Step("decision", title, Outcome.FAILED, tr("Die Aktionsentscheidung ist fehlgeschlagen."))
    if step == "pending":
        return Step("decision", title, Outcome.PENDING, tr("Noch nicht geprüft."))
    route = state.action_route
    if route is None:
        return Step("decision", title, Outcome.MISSING, tr("Das Ergebnis wird nicht mehr aufbewahrt."))
    tasks = _plural(route.task_count, tr("mögliche Aufgabe"), tr("mögliche Aufgaben"))
    events = _plural(route.event_count, tr("möglichen Termin"), tr("mögliche Termine"))
    text = {
        "none": tr("Keine Aufgabe und kein Termin erkannt; die Mail gilt als Information ohne Handlungsbedarf."),
        "task": tr("Erkannt: {p0}, kein Termin.", p0=tasks),
        "event": tr("Erkannt: {p0}, keine Aufgabe.", p0=events),
        "task_and_event": tr("Erkannt: {p0} und {p1}.", p0=tasks, p1=events),
        "unclear": tr("Unklar: {p0} und {p1} zur Prüfung.", p0=tasks, p1=events),
    }[route.action_state]
    return Step("decision", title, Outcome.DONE, text, model_reason=route.reason)


def _extraction(state: MailState) -> Step:
    title = tr("Extraktion")
    if (error := _error_for(state, "extraction")) is not None:
        return _failed("extraction", title, error)
    steps = (state.steps.task_extraction, state.steps.event_extraction)
    if "failed" in steps:
        return Step("extraction", title, Outcome.FAILED, tr("Die Extraktion ist fehlgeschlagen."))
    if "pending" in steps:
        return Step("extraction", title, Outcome.PENDING, tr("Noch nicht extrahiert."))
    if steps == ("skipped", "skipped"):
        none = state.action_route is not None and state.action_route.action_state == "none"
        return Step(
            "extraction",
            title,
            Outcome.SKIPPED,
            tr("Nicht nötig, weil keine Aktion erkannt wurde.") if none else tr("Ausgelassen."),
        )
    task_done, event_done = (step == "completed" for step in steps)
    if (task_done and state.task_extraction is None) or (event_done and state.event_extraction is None):
        return Step("extraction", title, Outcome.MISSING, tr("Das Ergebnis wird nicht mehr aufbewahrt."))
    tasks = len(state.task_extraction.tasks) if state.task_extraction is not None else 0
    events = len(state.event_extraction.events) if state.event_extraction is not None else 0
    text = tr(
        "{p0} und {p1} extrahiert.", p0=_plural(tasks, "Aufgabe", "Aufgaben"), p1=_plural(events, "Termin", "Termine")
    )
    notes = tuple(conflict_note(conflict) for conflict in state.extraction_count_conflicts)
    return Step("extraction", title, Outcome.DONE, text, notes=notes)


def conflict_note(conflict: ExtractionCountConflict) -> str:
    """A router count the extraction did not match, e.g. two expected tasks and one extracted."""
    names = ("Aufgabe", "Aufgaben") if conflict.category == "task" else ("Termin", "Termine")
    verb = tr("wurde") if conflict.actual_count == 1 else tr("wurden")
    return tr(
        "Router erwartete {expected}; {actual} {verb} extrahiert.",
        expected=_plural(conflict.expected_count, *names),
        actual=conflict.actual_count,
        verb=verb,
    )


def _assessment(state: MailState) -> Step:
    title = tr("Bewertung und Abgleich")
    if (error := _error_for(state, "assessment")) is not None:
        return _failed("assessment", title, error)
    if state.proposals:
        counts = Counter(proposal.status for proposal in state.proposals)
        parts = [tr("{p0} × {p1}", p0=count, p1=STATUS_LABELS[status]) for status, count in sorted(counts.items())]
        return Step("assessment", title, Outcome.DONE, ", ".join(parts) + ".")
    building = state.steps.proposal_building
    if building == "completed":
        return Step("assessment", title, Outcome.DONE, tr("Keine Vorschläge gebildet."))
    if building == "failed":
        return Step("assessment", title, Outcome.FAILED, tr("Die Vorschläge konnten nicht gebildet werden."))
    if building == "pending":
        return Step("assessment", title, Outcome.PENDING, tr("Noch keine Vorschläge gebildet."))
    return Step("assessment", title, Outcome.SKIPPED, tr("Ausgelassen."))


def _result(state: MailState, steps: tuple[Step, ...]) -> Step:
    title = tr("Ergebnis")
    if state.error is not None or any(step.outcome == Outcome.FAILED for step in steps):
        return Step("result", title, Outcome.FAILED, tr("Die Auswertung ist wegen eines Fehlers unvollständig."))
    if steps[0].outcome == Outcome.SKIPPED:
        return Step("result", title, Outcome.SKIPPED, tr("Nicht ausgewertet, weil die Mail doppelt empfangen wurde."))
    if any(step.outcome == Outcome.PENDING for step in steps):
        return Step("result", title, Outcome.PENDING, tr("Die Verarbeitung läuft noch."))
    open_ = Counter(proposal.status for proposal in state.proposals if proposal.status in OPEN)
    if open_:
        parts = []
        if confirm := open_[ProposalStatus.PENDING_CONFIRMATION]:
            parts.append(
                _plural(confirm, tr("Vorschlag wartet"), tr("Vorschläge warten")) + tr(" auf deine Bestätigung")
            )
        if clarify := open_[ProposalStatus.NEEDS_CLARIFICATION]:
            parts.append(_plural(clarify, tr("Vorschlag braucht"), tr("Vorschläge brauchen")) + tr(" eine Klärung"))
        return Step("result", title, Outcome.DONE, "; ".join(parts) + ".")
    if state.proposals:
        return Step("result", title, Outcome.DONE, tr("Alle Vorschläge dieser Mail sind entschieden."))
    if _irrelevant(state):
        return Step("result", title, Outcome.DONE, tr("Als irrelevant abgelegt; keine Aktion nötig."))
    if any(step.outcome == Outcome.MISSING for step in steps):
        return Step(
            "result", title, Outcome.MISSING, tr("Kein Vorschlag; die Gründe werden nicht mehr vollständig aufbewahrt.")
        )
    return Step("result", title, Outcome.DONE, tr("Keine Aktion erkannt."))


def explain(state: MailState) -> Explanation:
    """The stored processing path of one mail, step by step, with fixed texts."""
    steps = (_intake(state), _relevance(state), _decision(state), _extraction(state), _assessment(state))
    return Explanation(mail_id=state.id, analysis_round=state.analysis_round,
                       content_retained=state.mail is not None, steps=steps, result=_result(state, steps))
