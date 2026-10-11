"""Deterministic, bounded human edits. Saving an edit never authorizes a write."""
from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field

from ..domain.proposal import _required_revision_questions
from ..models import Proposal, ProposalKind, ProposalStatus


class ProposalEditPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=4000)
    target: str | None = Field(default=None, min_length=1, max_length=500)
    due: str | None = Field(default=None, max_length=40)
    start: str | None = Field(default=None, max_length=40)
    end: str | None = Field(default=None, max_length=40)
    all_day: bool | None = None
    location: str | None = Field(default=None, max_length=1000)
    video_link: str | None = Field(default=None, max_length=2000)


def local_time(value: str | None, zone: str, date_only: bool = False):
    if not value:
        return None
    if len(value) == 10:
        return date.fromisoformat(value)
    if date_only:
        raise ValueError("Ganztägige Termine benötigen reine Datumswerte")
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is not None:
        return stamp
    tz = ZoneInfo(zone)
    candidates = {stamp.replace(tzinfo=tz, fold=fold).astimezone(timezone.utc)
                  for fold in (0, 1)
                  if stamp.replace(tzinfo=tz, fold=fold).astimezone(timezone.utc)
                  .astimezone(tz).replace(tzinfo=None) == stamp}
    if len(candidates) != 1:
        raise ValueError("Uhrzeit ist mehrdeutig oder existiert nicht; bitte eindeutigen UTC-Offset angeben")
    return candidates.pop().astimezone(tz)


def edit_proposal(previous: Proposal, patch: ProposalEditPatch, zone: str, targets: set[str]) -> Proposal:
    if previous.status not in {ProposalStatus.PENDING_CONFIRMATION, ProposalStatus.NEEDS_CLARIFICATION}:
        raise ValueError("Nur offene Vorschläge können bearbeitet werden")
    changes = patch.model_dump(exclude_unset=True)
    if "target" in changes and changes["target"] not in targets:
        raise ValueError("Unzulässiges Ziel")
    if previous.kind == ProposalKind.TASK and set(changes) & {"start", "end", "all_day", "location", "video_link"}:
        raise ValueError("Aufgaben haben keine Kalenderfelder")
    if previous.kind == ProposalKind.EVENT and "due" in changes:
        raise ValueError("Termine haben keine Aufgabenfrist")
    for field in {"due", "start", "end"} & changes.keys():
        changes[field] = local_time(changes[field], zone, bool(changes.get("all_day", previous.all_day)))
    if changes.get("video_link") and not changes["video_link"].startswith("https://"):
        raise ValueError("Videolinks benötigen HTTPS")
    for field in {"location", "video_link"} & changes.keys():
        changes[field] = changes[field] or None
    if changes.get("video_link"):
        changes["video_link"] = AnyHttpUrl(changes["video_link"])
    changes = {field: value for field, value in changes.items() if getattr(previous, field) != value}
    if not changes:
        return previous
    if {"due", "start", "end"} & changes.keys():
        changes.update(known_temporal_facts=None, temporal_fact=None, duration_minutes=None, duration_is_upper_bound=False)
    changes.update(explicit_create_fallback_confirmed=False, explicit_non_binding_create_confirmed=False)
    candidate = previous.model_copy(update=changes)
    questions = _required_revision_questions(candidate)
    # Preserve unresolved questions not replaced by the directly entered facts.
    temporal = {"Wann beginnt der Termin?", "Wann endet der Termin?"}
    questions = list(dict.fromkeys(questions + [q for q in previous.open_questions if q not in temporal]))
    changes.update(version=previous.version + 1, open_questions=questions,
                   explicit_duplicate_create_confirmed_version=None,
                   explicit_create_fallback_confirmed=False,
                   explicit_non_binding_create_confirmed=False,
                   status=ProposalStatus.NEEDS_CLARIFICATION if questions else ProposalStatus.PENDING_CONFIRMATION)
    return Proposal.model_validate(previous.model_copy(update=changes).model_dump())
