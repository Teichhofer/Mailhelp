"""5.1 (R5): deterministic consistency hints from a mail's stored results.

A hint describes a possible contradiction and names its evidence; it never claims
that an action was missed, and it never starts a paid re-analysis. A date or a
deadline alone is no task. Hints are computed from the stored state, so the same
state always yields the same hints and none is created twice.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from ..domain.mail import MailState
from ..domain.proposal import ProposalCertainty, ProposalKind
from .explanation import conflict_note

# Words that tie an organisational duty (registration, reply) to an appointment.
REGISTRATION = re.compile(r"anmeld|rückmeld|zurückmeld|zusag|absag|teilnahme", re.IGNORECASE)


class Rule(StrEnum):
    COUNT_CONFLICT = "count_conflict"
    POSSIBLE_OMISSION = "possible_omission"
    UNASSIGNED_DUTY = "unassigned_duty"
    CONTRADICTION = "contradiction"
    INCOMPLETE = "incomplete"


@dataclass(frozen=True)
class Hint:
    rule: Rule
    severity: str  # "info" or "warn"
    text: str
    evidence: str
    analysis_round: int


def _due_day(value: date | datetime) -> date:
    return value.date() if isinstance(value, datetime) else value


def _incomplete(state: MailState) -> list[tuple[str, str]]:
    found = []
    if state.error is not None:
        found.append(("Die Auswertung brach mit einem Fehler ab; ihr Ergebnis ist unvollständig.",
                      "Gespeicherter Verarbeitungsfehler"))
    mail = state.prepared
    if mail is None:
        return found
    if mail.metadata.get("text_shortened"):
        found.append(("Der Mailtext wurde wegen der Größengrenze gekürzt.", "Mailtext"))
    omitted = mail.metadata.get("attachments_omitted") or 0
    if omitted:
        found.append((f"{omitted} Anhänge wurden wegen der Grenze nicht gelesen.", "Anhänge"))
    for attachment in mail.extracted_attachments:
        if attachment.extraction_status != "success":
            found.append(("Ein Anhang konnte nicht gelesen werden.", f"Anhang „{attachment.filename}“"))
    return found


def hints(state: MailState) -> tuple[Hint, ...]:
    """The consistency hints of *state*, each once, in rule order."""
    found: dict[tuple[Rule, str, str], Hint] = {}

    def add(rule: Rule, severity: str, text: str, evidence: str) -> None:
        found.setdefault((rule, text, evidence), Hint(rule, severity, text, evidence, state.analysis_round))

    for conflict in state.extraction_count_conflicts:
        add(Rule.COUNT_CONFLICT, "warn", conflict_note(conflict), "Router und Extraktion")
    proposals = [item for item in state.proposals if item.status != "merged"]
    tasks = [item for item in proposals if item.kind == ProposalKind.TASK]
    events = [item for item in proposals if item.kind == ProposalKind.EVENT]
    relevant = state.relevance is not None and state.relevance.decision == "relevant"
    deadlines = state.summary.deadlines if state.summary is not None else []
    if relevant and deadlines and not tasks:
        add(Rule.POSSIBLE_OMISSION, "info",
            "Die Zusammenfassung nennt eine Frist, zu der es keinen Aufgabenvorschlag gibt. Bitte prüfen, ob ein "
            "eigener Auftrag dahintersteht; eine Frist allein ist keine Aufgabe.",
            "Zusammenfassung: " + "; ".join(deadlines))
    for event in events:
        if not tasks and REGISTRATION.search(" ".join((event.title, event.description, event.evidence))):
            add(Rule.UNASSIGNED_DUTY, "info",
                "Zum Termin wird eine Anmeldung oder Rückmeldung erwähnt, für die es keine eigene Aufgabe gibt.",
                f"Termin „{event.title}“")
    received = state.prepared.received if state.prepared is not None else None
    for item in proposals:
        if item.certainty == ProposalCertainty.CONTRADICTORY:
            add(Rule.CONTRADICTION, "warn", "Die Mail enthält widersprüchliche Angaben zu diesem Vorschlag.",
                f"Vorschlag „{item.title}“")
        if item.kind == ProposalKind.TASK and item.due is not None and received is not None:
            if _due_day(item.due) < datetime.fromisoformat(received).date():
                add(Rule.CONTRADICTION, "warn", "Die Frist liegt vor dem Eingang der Mail.",
                    f"Vorschlag „{item.title}“")
    for text, evidence in _incomplete(state):
        add(Rule.INCOMPLETE, "warn", text, evidence)
    order = list(Rule)
    return tuple(sorted(found.values(), key=lambda hint: order.index(hint.rule)))
