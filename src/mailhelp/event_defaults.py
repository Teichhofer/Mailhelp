"""Application-owned duration assumptions; raw mail extraction remains unchanged."""
import re
from dataclasses import replace
from datetime import UTC, timedelta

from .action_normalization import MailDateContext, NormalizationReason, TemporalValue, normalize_event
from .config import EventDefaultsSettings
from .domain.extraction import ExtractedEvent


def meeting_mode(event: ExtractedEvent) -> str:
    text = " ".join((event.title, event.description or "", event.evidence, event.location or "")).casefold()
    video = bool(event.video_link or re.search(
        r"\b(?:online|videokonferenz|videomeeting|skype|teams|zoom|webex|jitsi)\b", text))
    presence = bool(re.search(r"\b(?:präsenz(?:termin)?|vor ort|sitzungszimmer|sitzungssaal|raum|treffen in)\b", text))
    if video and presence:
        return "hybrid"
    if video:
        return "video"
    return "in_person" if presence else "unknown"


def normalized_event(event: ExtractedEvent, context: MailDateContext, defaults: EventDefaultsSettings | None):
    result = normalize_event(event, context)
    mode = meeting_mode(event)
    origin = ("mail_end" if event.end_time_text is not None else
              "mail_duration" if event.duration_minutes is not None and result.resolved else "unknown")
    applied = None
    if (defaults is not None and result.reason == NormalizationReason.MISSING_END_TIME
            and event.duration_minutes is None and mode in {"video", "in_person"}):
        start = result.known_start
        assert start is not None
        applied = (defaults.video_duration_minutes if mode == "video" else defaults.in_person_duration_minutes)
        end = (start.astimezone(UTC) + timedelta(minutes=applied)).astimezone(start.tzinfo)
        result = replace(result, value=TemporalValue(start, end, False), reason=None, question=None,
                         known_date=None, known_start=None)
        origin = "standard"
    return result, mode, origin, applied


def reapply_defaults(proposal, defaults: EventDefaultsSettings):
    from .domain.proposal import ProposalStatus, required_revision_questions
    start = proposal.start or (proposal.known_temporal_facts.start if proposal.known_temporal_facts else None)
    if (proposal.kind != "event" or proposal.end is not None and proposal.end_origin != "standard" or start is None or
            proposal.duration_minutes is not None or proposal.all_day):
        return proposal
    mode = proposal.meeting_mode
    if mode == "unknown":
        event = ExtractedEvent(title=proposal.title, description=proposal.description.split("\n\nAbsender:", 1)[0],
            evidence=proposal.evidence, responsibility=proposal.responsibility, certainty=proposal.certainty,
            classification=proposal.classification, location=proposal.location, video_link=proposal.video_link,
            time_requirement="timed")
        mode = meeting_mode(event)
    if mode not in {"video", "in_person"}:
        return proposal
    duration = defaults.video_duration_minutes if mode == "video" else defaults.in_person_duration_minutes
    end = (start.astimezone(UTC) + timedelta(minutes=duration)).astimezone(start.tzinfo)
    if proposal.end == end and proposal.default_duration_minutes == duration:
        return proposal
    candidate = proposal.model_copy(update={"start": start, "end": end, "known_temporal_facts": None,
        "meeting_mode": mode, "end_origin": "standard", "default_duration_minutes": duration,
        "version": proposal.version + 1, "explicit_create_fallback_confirmed": False,
        "explicit_non_binding_create_confirmed": False, "explicit_duplicate_create_confirmed_version": None})
    if "known_temporal_facts" in proposal.protected_fields:
        candidate = candidate.model_copy(update={"protected_fields": list(dict.fromkeys([
            *proposal.protected_fields, "start"]))})
    questions = [q for q in proposal.open_questions if q not in {"Wann beginnt der Termin?", "Wann endet der Termin?"}]
    questions = list(dict.fromkeys([*questions, *required_revision_questions(candidate)]))
    candidate = candidate.model_copy(update={"open_questions": questions,
        "status": ProposalStatus.NEEDS_CLARIFICATION if questions else ProposalStatus.PENDING_CONFIRMATION})
    return type(proposal).model_validate(candidate.model_dump())
