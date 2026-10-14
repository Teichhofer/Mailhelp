"""Non-destructive addition of source facts; every material change is versioned."""

from datetime import datetime
from typing import Any

from .domain.proposal import KnownTemporalFacts, Proposal, ProposalStatus, required_revision_questions
from .domain.proposal_sources import ProposalReference
from .proposal_matching import day

_TIME_QUESTIONS = ("Wann beginnt der Termin?", "Wann endet der Termin?",
                   "Welches konkrete Datum", "Ist die extrahierte Information sicher belegt?")


def merge_facts(previous: Proposal, incoming: Proposal, *, uncertain=False) -> Proposal:
    changes: dict[str, Any] = {"sources": list(previous.sources), "explicit_create_fallback_confirmed": False,
        "explicit_non_binding_create_confirmed": False, "explicit_duplicate_create_confirmed_version": None}
    if incoming.duplicate_check_failed:
        changes["duplicate_check_failed"] = True
    for source in incoming.sources:
        if source not in changes["sources"]:
            changes["sources"].append(source)
    questions = list(previous.open_questions)
    if uncertain:
        ref = ProposalReference(mail_id=incoming.source_mail_id, proposal_id=incoming.id)
        changes["pending_sources"] = list(dict.fromkeys(
            (item.mail_id, item.proposal_id) for item in [*previous.pending_sources, ref]))
        changes["pending_sources"] = [ProposalReference(mail_id=mail, proposal_id=proposal)
                                      for mail, proposal in changes["pending_sources"]]
        questions.append("Zuordnung der zusätzlichen Quelle prüfen.")
    else:
        latest_old = max((s.sent_at for s in previous.sources if s.sent_at is not None), default=None)
        latest_new = max((s.sent_at for s in incoming.sources if s.sent_at is not None), default=None)
        newer = latest_new is not None and (latest_old is None or latest_new > latest_old)
        known = previous.known_temporal_facts
        incoming_start = incoming.start or (
            incoming.known_temporal_facts.start if incoming.known_temporal_facts else None)
        protected_clock_changed = bool(known and isinstance(incoming_start, datetime) and (
            known.start is not None and known.start != incoming_start or
            known.start_time is not None and known.start_time != incoming_start.time()))
        if (newer and previous.classification == "non_binding" and incoming.classification == "new"
                and "classification" not in previous.protected_fields):
            changes["classification"] = incoming.classification
            questions = [q for q in questions if q !=
                "Soll der nicht bindende Hinweis dennoch als neuer Eintrag angelegt werden?"]
        for field in ("start", "end", "due", "location", "video_link", "known_temporal_facts"):
            old, new = getattr(previous, field), getattr(incoming, field)
            if new is None or new == old:
                continue
            if field in {"start", "end", "known_temporal_facts"} and previous.all_day != incoming.all_day:
                questions.append("Ganztägige und zeitgebundene Angaben aus den Quellen vergleichen.")
                continue
            if field in {"start", "end"} and "known_temporal_facts" in previous.protected_fields and (
                    day(previous) is not None and day(incoming) != day(previous) or protected_clock_changed):
                questions.append("Widerspruch zum manuell festgelegten Datum oder Beginn: Quellen vergleichen.")
                continue
            if field == "known_temporal_facts" and previous.start is not None:
                continue
            if (field == "known_temporal_facts" and old is not None and old.start is None and new.start is not None
                    and (old.date is None or old.date == new.start.date())
                    and (old.start_time is None or old.start_time == new.start.time())):
                changes[field] = KnownTemporalFacts(date=old.date or new.start.date(), start=new.start)
                continue
            if field in previous.protected_fields:
                questions.append(f"Widerspruch bei {field}: Angaben aus den Quellen vergleichen.")
            elif field == "start" and old is not None and incoming.end is None:
                questions.append("Abweichender Beginn ohne belegtes Ende: Quellen vergleichen.")
            elif old is None:
                changes[field] = new
            elif (
                    field == "end" and previous.end_origin == "standard" and incoming.end_origin != "standard"
                    and incoming.start == previous.start
                    or newer and incoming.classification == "change"):
                changes[field] = new
            elif newer or latest_new is None or latest_new == latest_old:
                questions.append(f"Widerspruch bei {field}: Angaben aus den Quellen vergleichen.")
        if changes.get("known_temporal_facts") is not None:
            changes["temporal_fact"] = incoming.temporal_fact
        if changes.get("start") is not None:
            changes["known_temporal_facts"] = None
            changes["temporal_fact"] = incoming.temporal_fact
        if "end" in changes:
            changes.update(end_origin=incoming.end_origin, default_duration_minutes=incoming.default_duration_minutes)
        if previous.meeting_mode == "unknown":
            changes["meeting_mode"] = incoming.meeting_mode
        if incoming.certainty == "certain" and newer:
            changes["certainty"] = incoming.certainty
        fragment = incoming.description.split("\n\nAbsender:", 1)[0].strip()
        if fragment and fragment not in previous.description:
            if "description" in previous.protected_fields:
                questions.append("Zusätzliche Beschreibung aus der neuen Quelle prüfen.")
            else:
                changes["description"] = (previous.description + "\n\nErgänzung: " + fragment)[:4000]
        candidate = previous.model_copy(update=changes)
        if candidate.start is not None and candidate.end is not None and candidate.end <= candidate.start:
            for field in ("start", "end", "known_temporal_facts", "temporal_fact",
                          "end_origin", "default_duration_minutes"):
                changes.pop(field, None)
            questions.append("Widersprüchliches Zeitintervall aus den Quellen prüfen.")
            candidate = previous.model_copy(update=changes)
        if (candidate.start is not None and candidate.end is not None and
                candidate.certainty == "certain"):
            questions = [q for q in questions if not q.startswith(_TIME_QUESTIONS)]
        elif (candidate.known_temporal_facts is not None and candidate.known_temporal_facts.start is not None
              and candidate.certainty == "certain"):
            questions = [q for q in questions if not q.startswith((_TIME_QUESTIONS[0], *_TIME_QUESTIONS[2:]))]
        questions.extend(required_revision_questions(candidate))
    changes["open_questions"] = list(dict.fromkeys(questions))
    changes["status"] = (ProposalStatus.NEEDS_CLARIFICATION if changes["open_questions"]
                         else ProposalStatus.PENDING_CONFIRMATION)
    if all(getattr(previous, name) == value for name, value in changes.items()):
        return previous
    changes.update(version=previous.version + 1, explicit_create_fallback_confirmed=False,
                   explicit_non_binding_create_confirmed=False, explicit_duplicate_create_confirmed_version=None,
                   uncertain_notified=False)
    return Proposal.model_validate(previous.model_copy(update=changes).model_dump())
