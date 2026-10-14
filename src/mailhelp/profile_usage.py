"""Read-only references used to explain why a target profile cannot be removed."""

import re

from .models import Proposal


def profile_references(store, settings, number):
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
