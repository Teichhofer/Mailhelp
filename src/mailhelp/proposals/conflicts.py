"""Readable field conflicts of merged sources and their one-click resolution (5.9.2).

A conflict keeps the typed competing values, so choosing one of them can apply it. Labels and
texts are derived when shown; the stored question is the identity in ``open_questions``.
Choosing a variant only revises the proposal: it never authorizes an external write.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ..domain.proposal import (
    ConflictVariant,
    FieldConflict,
    KnownTemporalFacts,
    Proposal,
    ProposalStatus,
    required_revision_questions,
)
from ..domain.proposal_sources import ProposalReference

VARIANT_IDS = ("a", "b", "c")
# Grammatical forms: name, "bei/beim ...", "Welche/r ...".
_LABELS = {
    "interval": ("Zeitraum", "beim Zeitraum", "Welcher Zeitraum"),
    "start": ("Beginn", "beim Beginn", "Welcher Beginn"),
    "end": ("Endzeit", "bei der Endzeit", "Welche Endzeit"),
    "due": ("Fälligkeit", "bei der Fälligkeit", "Welche Fälligkeit"),
    "location": ("Ort", "beim Ort", "Welcher Ort"),
    "video_link": ("Videolink", "beim Videolink", "Welcher Videolink"),
}
BUTTON_LIMIT = 40


class ConflictChoiceError(ValueError):
    """The chosen variant no longer belongs to the current proposal version."""


def _local(value: datetime, zone: ZoneInfo | None) -> datetime:
    return value.astimezone(zone) if zone is not None else value


def aspect(conflict: FieldConflict) -> str:
    """An interval in which only the end (or only the start) differs is named after it."""
    if conflict.field != "interval":
        return conflict.field
    starts = {variant.start for variant in conflict.variants}
    ends = {variant.end for variant in conflict.variants}
    if len(starts) == 1:
        return "end"
    if len(ends) == 1:
        return "start"
    return "interval"


def label(conflict: FieldConflict) -> str:
    return _LABELS[aspect(conflict)][0]


def _day(value: date | datetime | None, zone: ZoneInfo | None) -> date | None:
    if isinstance(value, datetime):
        return _local(value, zone).date()
    return value


def _same_day(conflict: FieldConflict, zone: ZoneInfo | None) -> bool:
    days = {_day(value, zone) for variant in conflict.variants
            for value in (variant.start, variant.end, variant.due) if value is not None}
    return len(days) == 1


def _moment(value: date | datetime, zone: ZoneInfo | None, with_day: bool) -> str:
    if not isinstance(value, datetime):
        return f"{value:%d.%m.%Y}"
    local = _local(value, zone)
    return f"{local:%d.%m.%Y, %H:%M} Uhr" if with_day else f"{local:%H:%M} Uhr"


def _interval(variant: ConflictVariant, zone: ZoneInfo | None, with_day: bool) -> str:
    start, end = variant.start, variant.end
    if start is None:
        return "ohne Beginn"
    if not isinstance(start, datetime):
        last = end - timedelta(days=1) if isinstance(end, date) and not isinstance(end, datetime) else None
        if last is not None and last != start:
            return f"{start:%d.%m.%Y} – {last:%d.%m.%Y}, ganztägig"
        return f"{start:%d.%m.%Y}, ganztägig"
    if not isinstance(end, datetime):
        return _moment(start, zone, with_day) + " (Ende offen)"
    local_start, local_end = _local(start, zone), _local(end, zone)
    if local_start.date() == local_end.date():
        text = (f"{local_start:%d.%m.%Y, %H:%M}–{local_end:%H:%M} Uhr" if with_day
                else f"{local_start:%H:%M}–{local_end:%H:%M} Uhr")
    else:
        text = f"{local_start:%d.%m.%Y, %H:%M} Uhr – {local_end:%d.%m.%Y, %H:%M} Uhr"
    return text + (" (Dauer wie bisher)" if variant.derived_end else "")


def value_text(conflict: FieldConflict, variant: ConflictVariant, zone: ZoneInfo | None = None) -> str:
    """The value of one variant as shown in texts; dates are left out when all share one day."""
    with_day = not _same_day(conflict, zone)
    if conflict.field == "interval":
        part = aspect(conflict)
        if part == "end" and isinstance(variant.end, datetime):
            return _moment(variant.end, zone, with_day)
        if part == "start" and isinstance(variant.start, datetime) and not variant.derived_end:
            return _moment(variant.start, zone, with_day)
        return _interval(variant, zone, with_day)
    if conflict.field == "due":
        return _moment(variant.due, zone, True) if variant.due is not None else "keine"
    return f"„{variant.text}“" if variant.text else "keine Angabe"


def button_text(conflict: FieldConflict, variant: ConflictVariant, zone: ZoneInfo | None = None) -> str:
    """A short value for a button; links show their host only."""
    if conflict.field == "video_link" and variant.text:
        text = variant.text.split("://", 1)[-1].split("/", 1)[0]
    elif conflict.field == "location" and variant.text:
        text = variant.text
    else:
        text = value_text(conflict, variant, zone)
    text = " ".join(text.split())
    return text if len(text) <= BUTTON_LIMIT else text[:BUTTON_LIMIT - 1] + "…"


def origin_text(variant: ConflictVariant, sources: list[Any]) -> str:
    """bisher, von dir festgelegt or the source mail of a variant."""
    if variant.origin == "manual":
        return "von dir festgelegt"
    if variant.origin == "current":
        return "bisher"
    source = next((item for item in sources if variant.source is not None
                   and (item.mail_id, item.proposal_id) == (variant.source.mail_id, variant.source.proposal_id)), None)
    subject = f" „{source.subject}“" if source is not None and source.subject else ""
    when = f" vom {source.sent_at:%d.%m.}" if source is not None and source.sent_at is not None else ""
    return f"laut Mail{subject}{when}" if subject or when else "laut neuer Mail"


def question(conflict: FieldConflict, sources: list[Any], zone: ZoneInfo | None = None) -> str:
    """"Widerspruch bei der Endzeit: bisher 16:30 Uhr, laut Mail … 19:30 Uhr. Welche Endzeit soll gelten?\""""
    _, case, which = _LABELS[aspect(conflict)]
    parts = ", ".join(f"{origin_text(variant, sources)} {value_text(conflict, variant, zone)}"
                      for variant in conflict.variants)
    return f"Widerspruch {case}: {parts}. {which} soll gelten?"


def several_values_question(field: str) -> str:
    return f"Mehrere widersprüchliche Angaben {_LABELS[field][1]}: bitte den Vorschlag bearbeiten."


def temporal_facts_question(old: KnownTemporalFacts | None, new: KnownTemporalFacts) -> str:
    """Contradicting partial time facts have no buttons, but both values are named."""
    shown = _facts(old) if old is not None else "keine Angabe"
    return (f"Widerspruch bei den Zeitangaben: bisher {shown}, laut neuer Mail {_facts(new)}. "
            "Bitte den Termin bearbeiten.")


def _facts(facts: KnownTemporalFacts) -> str:
    if facts.start is not None:
        return _moment(facts.start, None, True)
    return ", ".join(part for part in (f"{facts.date:%d.%m.%Y}" if facts.date else "",
                                       f"{facts.start_time:%H:%M} Uhr" if facts.start_time else "") if part)


_TIMING = {"all_day": "Ganztägige und zeitgebundene Angaben widersprechen sich",
           "manual_day": "Widerspruch zum von dir festgelegten Datum oder Beginn"}


def timing_question(kind: str, previous: Proposal, incoming: Proposal) -> str:
    """All-day against timed, or against a day the user fixed: named with both times, edited by hand."""
    def show(proposal: Proposal) -> str:
        facts = proposal.known_temporal_facts
        if proposal.start is None and facts is not None:
            return _facts(facts)
        variant = ConflictVariant(id="a", origin="current", start=proposal.start, end=proposal.end)
        return _interval(variant, None, True)
    return f"{_TIMING[kind]}: bisher {show(previous)}, laut neuer Mail {show(incoming)}. Bitte den Termin bearbeiten."


def _value(variant: ConflictVariant, field: str) -> Any:
    if field == "interval":
        return variant.start, variant.end
    return variant.due if field == "due" else variant.text


def build_variant(field: str, values: dict[str, Any], origin: str, source: ProposalReference | None,
                  ident: str, derived_end: bool = False) -> ConflictVariant:
    if field == "interval":
        payload: dict[str, Any] = {"start": values["start"], "end": values["end"], "derived_end": derived_end}
    elif field == "due":
        payload = {"due": values["due"]}
    else:
        payload = {"text": None if values[field] is None else str(values[field])}
    return ConflictVariant(id=ident, origin=origin, source=source, **payload)


def extend(existing: FieldConflict | None, field: str, current: ConflictVariant, incoming: ConflictVariant,
           ident: str, sources: list[Any]) -> tuple[FieldConflict | None, str]:
    """A new conflict, an existing one with a further value, or None for more than three values."""
    if existing is None:
        conflict = FieldConflict(id=ident, field=field, question="-",
                                 variants=[current, incoming.model_copy(update={"id": "b"})])
    elif any(_value(variant, field) == _value(incoming, field) for variant in existing.variants):
        return existing, existing.question
    elif len(existing.variants) == len(VARIANT_IDS):
        return None, several_values_question(field)
    else:
        variants = [*existing.variants, incoming.model_copy(update={"id": VARIANT_IDS[len(existing.variants)]})]
        conflict = existing.model_copy(update={"variants": variants})
    return conflict.model_copy(update={"question": question(conflict, sources)}), ""


def choose(proposal: Proposal, conflict_id: str, variant_id: str) -> Proposal:
    """Apply one variant as a new version; the decision is the user's, so the field becomes protected."""
    if proposal.status not in {ProposalStatus.PENDING_CONFIRMATION, ProposalStatus.NEEDS_CLARIFICATION}:
        raise ConflictChoiceError("Nur offene Vorschläge können geändert werden")
    conflict = next((item for item in proposal.field_conflicts if item.id == conflict_id), None)
    variant = next((item for item in conflict.variants if item.id == variant_id), None) if conflict else None
    if conflict is None or variant is None:
        raise ConflictChoiceError("Der Widerspruch ist nicht mehr offen")
    changes: dict[str, Any]
    if conflict.field == "interval":
        changes = {"start": variant.start, "end": variant.end, "known_temporal_facts": None,
                   "temporal_fact": None, "duration_minutes": None, "duration_is_upper_bound": False,
                   "end_origin": "manual", "default_duration_minutes": None}
        fields = ["start", "end"]
    elif conflict.field == "due":
        changes, fields = {"due": variant.due}, ["due"]
    else:
        changes, fields = {conflict.field: variant.text}, [conflict.field]
    remaining = [item for item in proposal.open_questions if item != conflict.question]
    candidate = proposal.model_copy(update={**changes, "open_questions": remaining})
    for item in required_revision_questions(candidate):
        if item not in remaining:
            remaining.append(item)
    changes.update(
        version=proposal.version + 1, open_questions=remaining,
        field_conflicts=[item for item in proposal.field_conflicts if item.id != conflict_id],
        protected_fields=list(dict.fromkeys([*proposal.protected_fields, *fields])),
        explicit_create_fallback_confirmed=False, explicit_non_binding_create_confirmed=False,
        explicit_duplicate_create_confirmed_version=None, confirmed_web_actor=None,
        status=ProposalStatus.NEEDS_CLARIFICATION if remaining else ProposalStatus.PENDING_CONFIRMATION)
    try:
        return Proposal.model_validate(proposal.model_copy(update=changes).model_dump())
    except ValueError as exc:
        raise ConflictChoiceError("Diese Auswahl ergibt keinen gültigen Vorschlag; bitte bearbeiten") from exc


__all__ = ["BUTTON_LIMIT", "ConflictChoiceError", "aspect", "build_variant", "button_text", "choose",
           "extend", "label", "origin_text", "question", "several_values_question",
           "temporal_facts_question", "timing_question", "value_text"]
