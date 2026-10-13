"""Trusted construction of proposals from schema-validated LLM facts."""
from __future__ import annotations

import hashlib
import json

from .action_normalization import MailDateContext, TemporalValue, normalize_event, normalize_task_due, recover_task_due
from .config import TargetSettings
from .domain.extraction import ParsedCalendarEvent
from .models import (
    ExtractedEvent,
    ExtractedTask,
    ExtractionCountConflict,
    KnownTemporalFacts,
    Proposal,
    ProposalClassification,
    ProposalResponsibility,
    ProposalStatus,
)

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
_DESCRIPTION_LIMIT = 4000


class ProposalBuilder:
    """The sole trust boundary for proposal identity, routing, and initial status."""

    def __init__(self, source_mail_id: str, targets: TargetSettings, context: MailDateContext,
                 source_sender: str = "—", source_subject: str = "—"):
        self.source_mail_id = source_mail_id
        self.targets = targets
        self.context = context
        self.source_sender = source_sender
        self.source_subject = source_subject

    def _description(self, value: str | None) -> str:
        """Add bounded, application-owned source details to every external description."""
        mail_date = self.context.date_header_parsed or self.context.imap_received_at or "—"
        reference = (f"Absender: {self.source_sender}\n"
                     f"Betreff: {self.source_subject}\n"
                     f"Mail-Datum: {mail_date}")
        separator = "\n\n" if value else ""
        available = _DESCRIPTION_LIMIT - len(separator) - len(reference)
        description = (value or "")[:max(0, available)]
        return f"{description}{separator}{reference}"

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

    def build(self, tasks: list[ExtractedTask], events: list[ExtractedEvent],
              count_conflicts: list[ExtractionCountConflict] | None = None,
              calendar_events: list[ParsedCalendarEvent | dict] | None = None) -> list[Proposal]:
        """Build deterministic proposals without changing the extracted cardinality."""
        used_ids: set[str] = set()
        conflicted = {item.category for item in count_conflicts or []}
        proposals, ics_summaries = self._calendar_proposals(calendar_events, used_ids)
        filtered_events = [e for e in events if e.title.strip().casefold() not in ics_summaries]
        entries: list[tuple[str, ExtractedTask | ExtractedEvent]] = [
            *(("task", item) for item in tasks), *(("event", item) for item in filtered_events)
        ]
        for position, (kind, item) in enumerate(entries):
            proposals.append(self._extracted_proposal(kind, item, position, conflicted, used_ids))
        return proposals

    def _calendar_proposals(self, calendar_events: list[ParsedCalendarEvent | dict] | None,
                            used_ids: set[str]) -> tuple[list[Proposal], set[str]]:
        """Complete proposals from calendar attachments and their titles."""
        proposals: list[Proposal] = []
        cal_items: list[ParsedCalendarEvent] = []
        ics_summaries: set[str] = set()
        if calendar_events:
            for item in calendar_events:
                cal = item if isinstance(item, ParsedCalendarEvent) else ParsedCalendarEvent.model_validate(item)
                cal_items.append(cal)
                ics_summaries.add(cal.summary.strip().casefold())

        for pos_offset, cal in enumerate(cal_items):
            evidence = "Aus Kalenderanhang übernommen"
            classification = (
                ProposalClassification.CANCELLATION
                if cal.status == "CANCELLED"
                else ProposalClassification.NEW
            )
            raw_id = hashlib.sha256(
                f"{self.source_mail_id}:cal:{cal.uid or cal.summary}".encode()
            ).hexdigest()[:24]
            cand_id = f"p_{raw_id}"
            if cand_id in used_ids:
                cand_id = f"p_{hashlib.sha256(f'{cand_id}:{pos_offset}'.encode()).hexdigest()[:24]}"
            used_ids.add(cand_id)
            proposals.append(Proposal(
                schema_version=2,
                id=cand_id,
                version=1,
                kind="event",
                responsibility=ProposalResponsibility.USER,
                certainty="certain",
                classification=classification,
                title=cal.summary,
                description=self._description(cal.description),
                evidence=evidence,
                source_mail_id=self.source_mail_id,
                open_questions=[],
                location=cal.location,
                video_link=str(cal.video_link) if cal.video_link else None,
                target=self.targets.google_calendar,
                status=ProposalStatus.PENDING_CONFIRMATION,
                start=cal.start,
                end=cal.end,
                all_day=cal.all_day,
                is_cancellation=cal.status == "CANCELLED",
            ))
        return proposals, ics_summaries

    def _extracted_proposal(self, kind: str, item: ExtractedTask | ExtractedEvent, position: int,
                            conflicted: set[str], used_ids: set[str]) -> Proposal:
        """One proposal from an extracted task or event, with its open questions."""
        # A deadline missing from due_text but unambiguous in the verbatim
        # evidence is recovered; the identity still uses the raw extraction.
        due_item = recover_task_due(item) if isinstance(item, ExtractedTask) else item
        temporal = (normalize_task_due(due_item, self.context)
                    if kind == "task" and due_item.due_text is not None
                    else normalize_event(item, self.context) if kind == "event" else None)
        question = temporal.question if temporal is not None else None
        questions = self._questions(item, question)
        if kind in conflicted:
            questions.append(
                f"Wie viele {'Aufgaben' if kind == 'task' else 'Termine'} enthält diese Mail tatsächlich?"
            )
        values: dict[str, object] = {}
        if temporal is not None and temporal.resolved:
            if kind == "task":
                values["due"] = temporal.value
            else:
                assert isinstance(temporal.value, TemporalValue)
                values.update(start=temporal.value.start, end=temporal.value.end,
                              all_day=temporal.value.all_day)
        elif kind == "event" and temporal is not None and (
                temporal.known_date is not None or temporal.known_start is not None or
                temporal.known_start_time is not None):
            values["known_temporal_facts"] = KnownTemporalFacts(
                date=temporal.known_date, start=temporal.known_start,
                start_time=temporal.known_start_time)
        if temporal is not None:
            values["temporal_fact"] = temporal.temporal_fact
        target = self.targets.todoist_project if kind == "task" else self.targets.google_calendar
        status = (ProposalStatus.PENDING_CONFIRMATION
                  if item.classification == "new" and item.responsibility == "user"
                  and item.certainty == "certain" and not questions
                  else ProposalStatus.NEEDS_CLARIFICATION)
        return Proposal(
            schema_version=2, id=self._identity(kind, item, position, used_ids), version=1,
            kind=kind, responsibility=item.responsibility, certainty=item.certainty,
            classification=item.classification, title=item.title,
            description=self._description(item.description), evidence=item.evidence,
            source_mail_id=self.source_mail_id, open_questions=questions,
            location=item.location if isinstance(item, ExtractedEvent) else None,
            video_link=item.video_link if isinstance(item, ExtractedEvent) else None,
            duration_minutes=(item.duration_minutes
                              if isinstance(item, ExtractedEvent) else None),
            duration_is_upper_bound=(item.duration_is_upper_bound
                                     if isinstance(item, ExtractedEvent) else False),
            target=target, status=status, external_id=None, external_link=None,
            uncertain_notified=False, simulation_notified=False, **values,
        )
