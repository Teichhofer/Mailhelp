"""Protect human-owned revision facts independently of the channel."""
from __future__ import annotations

from ..models import Proposal


def protect_revision(original: Proposal, revised: Proposal) -> Proposal:
    changed = [field for field in ("title", "description", "due", "start", "end", "known_temporal_facts",
                                   "location", "video_link", "classification", "responsibility", "certainty")
               if getattr(original, field) != getattr(revised, field)]
    protected = list(dict.fromkeys([*original.protected_fields, *changed]))
    revised = revised.model_copy(update={"protected_fields": protected})
    if "end" in changed:
        revised = revised.model_copy(update={"end_origin": "manual", "default_duration_minutes": None})
    return revised
