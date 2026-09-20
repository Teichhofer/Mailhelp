"""Trusted construction of proposals from schema-validated LLM facts."""
from __future__ import annotations

import hashlib
import json

from .action_normalization import MailDateContext, TemporalValue, normalize_event, normalize_task_due
from .config import TargetSettings
from .models import (ExtractedEvent, ExtractedTask, Proposal, ProposalClassification,
                     KnownTemporalFacts, ProposalResponsibility, ProposalStatus)


_RESPONSIBILITY_QUESTION = "Ist die Nutzerin oder der Nutzer für diesen Eintrag zuständig?"
_CERTAINTY_QUESTIONS = {
    "uncertain": "Ist die extrahierte Information sicher belegt?",
    "contradictory": "Wie soll der Widerspruch in den Angaben aufgelöst werden?",
}
_CLASSIFICATION_QUESTIONS = {
    "non_binding": "Soll der nicht bindende Hinweis dennoch als neuer Eintrag angelegt werden?",
    "already_completed": "Der Eintrag ist bereits abgeschlossen und nicht direkt ausführbar.",
    "change": "Welcher bestehende Eintrag soll geändert werden?",
    "cancellation": "Welcher bestehende Eintrag soll storniert werden?",
    "recurring": "Wiederkehrende Einträge werden nicht automatisch angelegt.",
    "unsupported": "Diese Art von Eintrag wird nicht unterstützt.",
}


class ProposalBuilder:
    """The sole trust boundary for proposal identity, routing, and initial status."""

    def __init__(self, source_mail_id: str, targets: TargetSettings, context: MailDateContext):
        self.source_mail_id = source_mail_id
        self.targets = targets
        self.context = context

    @staticmethod
    def _questions(item: ExtractedTask | ExtractedEvent, temporal_question: str | None) -> list[str]:
        questions: list[str] = []
        if temporal_question:
            questions.append(temporal_question)
        if item.responsibility != "user":
            questions.append(_RESPONSIBILITY_QUESTION)
        certainty = _CERTAINTY_QUESTIONS.get(item.certainty)
        if certainty:
            questions.append(certainty)
        classification = _CLASSIFICATION_QUESTIONS.get(item.classification)
        if classification:
            questions.append(classification)
        return questions

    def _identity(self, kind: str, item: ExtractedTask | ExtractedEvent, position: int,
                  used: set[str]) -> str:
        facts = item.model_dump(mode="json")
        evidence = " ".join(item.evidence.split()).casefold()
        material = json.dumps({"mail": self.source_mail_id, "kind": kind,
                               "evidence": evidence, "facts": facts},
                              ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        base = "p_" + hashlib.sha256(material.encode()).hexdigest()[:24]
        candidate = base
        if candidate in used:
            candidate = "p_" + hashlib.sha256(f"{material}\0{position}".encode()).hexdigest()[:24]
        if candidate in used:
            raise ValueError("Vorschlags-ID-Kollision innerhalb einer Mail")
        used.add(candidate)
        return candidate

    def build(self, tasks: list[ExtractedTask], events: list[ExtractedEvent]) -> list[Proposal]:
        """Build deterministic proposals and discard byte-identical repeated facts."""
        proposals: list[Proposal] = []
        used_ids: set[str] = set()
        seen: set[tuple[str, str]] = set()
        entries: list[tuple[str, ExtractedTask | ExtractedEvent]] = [
            *(("task", item) for item in tasks), *(("event", item) for item in events)
        ]
        for position, (kind, item) in enumerate(entries):
            canonical = json.dumps(item.model_dump(mode="json"), ensure_ascii=False,
                                   sort_keys=True, separators=(",", ":"))
            duplicate_key = (kind, canonical)
            if duplicate_key in seen:
                continue
            seen.add(duplicate_key)
            temporal = (normalize_task_due(item, self.context) if kind == "task" and item.due_text is not None
                        else normalize_event(item, self.context) if kind == "event" else None)
            question = temporal.question if temporal is not None else None
            questions = self._questions(item, question)
            values: dict[str, object] = {}
            if temporal is not None and temporal.resolved:
                if kind == "task":
                    values["due"] = temporal.value
                else:
                    assert isinstance(temporal.value, TemporalValue)
                    values.update(start=temporal.value.start, end=temporal.value.end,
                                  all_day=temporal.value.all_day)
            elif kind == "event" and temporal is not None and (
                    temporal.known_date is not None or temporal.known_start is not None):
                values["known_temporal_facts"] = KnownTemporalFacts(
                    date=temporal.known_date, start=temporal.known_start)
            if temporal is not None:
                values["temporal_fact"] = temporal.temporal_fact
            target = self.targets.todoist_project if kind == "task" else self.targets.google_calendar
            status = (ProposalStatus.PENDING_CONFIRMATION
                      if item.classification == "new" and item.responsibility == "user"
                      and item.certainty == "certain" and not questions
                      else ProposalStatus.NEEDS_CLARIFICATION)
            proposals.append(Proposal(
                schema_version=2, id=self._identity(kind, item, position, used_ids), version=1,
                kind=kind, responsibility=item.responsibility, certainty=item.certainty,
                classification=item.classification, title=item.title,
                description=item.description or "", evidence=item.evidence,
                source_mail_id=self.source_mail_id, open_questions=questions,
                location=item.location if isinstance(item, ExtractedEvent) else None,
                video_link=item.video_link if isinstance(item, ExtractedEvent) else None,
                target=target, status=status, external_id=None, external_link=None,
                uncertain_notified=False, simulation_notified=False, **values,
            ))
        return proposals
