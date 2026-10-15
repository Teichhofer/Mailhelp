"""Read-only references used to explain why a target profile cannot be removed."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .models import Proposal

if TYPE_CHECKING:
    from .config import Settings
    from .storage import JsonStore


def profile_references(store: JsonStore, settings: Settings, number: int) -> list[str]:
    references = [
        f"Postfach {box.id} ({box.label})"
        for box in settings.imap.configured_mailboxes()
        if box.target_profile == number
    ]
    for name in store.names("proposal-"):
        if re.search(r"-v\d+$", name):
            continue
        proposal = store.peek_model(name, Proposal)
        if (
            proposal is not None
            and proposal.target_profile == number
            and (
                proposal.status in {"pending_confirmation", "needs_clarification", "confirmed", "writing", "uncertain"}
                or proposal.merge_review_required
            )
        ):
            references.append(f"Vorschlag {proposal.id} (Version {proposal.version})")
    return references
