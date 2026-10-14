"""Bind profile labels and deliberate target changes to current trusted configuration."""

import hashlib
import json

from .external.contracts import TargetWriter
from .external.providers import CALENDAR_LABELS, TASK_LABELS
from .external.roles import provider_key, writer_for
from .mailbox_settings import profile_label, target_profiles
from .models import Proposal, ProposalStatus, invalidate_creation_permissions, required_revision_questions
from .target_profiles import UnavailableWriter


def available(settings, writers, proposal):
    if not settings.target_profiles and proposal.target_profile == 1:
        return True
    writer = writer_for(writers, proposal)
    target = target_profiles(settings).get(proposal.target_profile)
    if writer is None or target is None or isinstance(writer, UnavailableWriter):
        return False
    configured = target.task_target if proposal.kind == "task" else target.calendar_target
    return proposal.target == configured and (
        not isinstance(writer, TargetWriter)
        or proposal.target == writer.target
        and (not proposal.target_provider or proposal.target_provider == provider_key(writer))
    )


def label(settings, proposal):
    if not settings.target_profiles and proposal.target_profile == 1:
        return ""
    name = profile_label(settings, proposal.target_profile)
    target = target_profiles(settings).get(proposal.target_profile)
    if target is None:
        return name
    provider = (TASK_LABELS[target.task_provider] if proposal.kind == "task"
                else CALENDAR_LABELS[target.calendar_provider])
    return f"{provider} · {name}"


def policy_hash(settings):
    return hashlib.sha256(
        json.dumps(
            {number: target.model_dump(mode="json") for number, target in target_profiles(settings).items()},
            sort_keys=True,
        ).encode()
    ).hexdigest()


def choices(settings, proposal):
    if (
        proposal.status not in {"pending_confirmation", "needs_clarification"}
        or proposal.pending_sources
        or proposal.matching_candidates
    ):
        return []
    digest = policy_hash(settings)
    result = []
    for number, target in target_profiles(settings).items():
        value = target.task_target if proposal.kind == "task" else target.calendar_target
        provider = target.task_provider if proposal.kind == "task" else target.calendar_provider
        if (number, value, provider) != (proposal.target_profile, proposal.target, proposal.target_provider):
            result.append((number, profile_label(settings, number), digest))
    return result


def retarget(settings, proposal, number, digest):
    if not any(candidate == number and bound == digest for candidate, _, bound in choices(settings, proposal)):
        raise ValueError("Zielwahl inzwischen geändert oder Vorschlag nicht umstellbar")
    target = target_profiles(settings)[number]
    changed = proposal.model_copy(
        update={
            "version": proposal.version + 1,
            "target_profile": number,
            "target": target.task_target if proposal.kind == "task" else target.calendar_target,
            "target_provider": target.task_provider if proposal.kind == "task" else target.calendar_provider,
            "target_event_id": None,
            "duplicate_match": None,
            "time_changes": [],
            "is_cancellation": False,
            "duplicate_check_failed": False,
            "external_id": None,
            "external_link": None,
        }
    )
    changed = invalidate_creation_permissions(changed)
    questions = required_revision_questions(changed)
    changed = changed.model_copy(
        update={
            "open_questions": questions,
            "status": ProposalStatus.NEEDS_CLARIFICATION if questions else ProposalStatus.PENDING_CONFIRMATION,
        }
    )
    return Proposal.model_validate(changed.model_dump())


def summary(settings, writers):
    if not settings.target_profiles:
        return ""
    lines = []
    for number in target_profiles(settings):
        slot = "google_calendar" if number == 1 else f"google_calendar:{number}"
        writer = writers.get(slot)
        state = "nicht verfügbar" if writer is None or isinstance(writer, UnavailableWriter) else "konfiguriert"
        lines.append(f"Zielprofil {number} ({profile_label(settings, number)}): {state}")
    return "\n".join(lines)
