"""Conservative duplicate detection before any LLM call."""
from __future__ import annotations

import hashlib
import json
import re
from typing import TYPE_CHECKING, Any

from . import state_names
from .models import (
    DuplicateDecision,
    DuplicateIndex,
    DuplicateIndexEntry,
    MailState,
)

if TYPE_CHECKING:
    from .orchestrator import Orchestrator


class DuplicateMailCheck:
    """Owned by the Orchestrator; reads its services through ``o``."""

    def __init__(self, owner: Orchestrator):
        self.o = owner

    @staticmethod
    def identity(mail: dict[str, Any]) -> tuple[list[str], str, int]:
        """Derive bounded identifiers and a one-way digest, never stored content.

        Works on the stored dict on purpose: the digest is kept in the
        duplicate index and must stay bit-identical across releases.
        """
        values = mail.get("message_ids", [mail["headers"].get("message_id", "")])
        normalized: list[str] = []
        for value in values:
            compact = re.sub(r"\s+", "", str(value)).casefold()
            if len(compact) <= 998 and re.fullmatch(r"<[^<>@\s]+@[^<>@\s]+>", compact) and compact not in normalized:
                normalized.append(compact)
        stable = {
            "from": str(mail["headers"].get("from", "")).casefold(),
            "subject": str(mail["headers"].get("subject", "")).casefold(),
            "date": str(mail["headers"].get("date", "")),
            "text": str(mail.get("text", "")),
        }
        digest = hashlib.sha256(json.dumps(stable, ensure_ascii=False, sort_keys=True,
                                           separators=(",", ":")).encode()).hexdigest()
        return normalized, digest, len(values)

    def check(self, name: str, state: MailState) -> bool:
        """Persist a conservative decision before any LLM call; return whether to skip."""
        assert state.mail is not None
        message_ids, fingerprint, message_id_headers = self.identity(state.mail)
        index = self.o.load_model("duplicate-index", DuplicateIndex, DuplicateIndex())
        assert isinstance(index, DuplicateIndex)
        # The index is the durable processed-mail marker.  Include an entry for
        # this technical identity when its MailState no longer exists (for
        # example after an operator cleanup); excluding it would incorrectly
        # turn the same stable mail id into a new message.  Entries of every
        # mailbox count (3.1): a mail sent to two configured mailboxes is one mail.
        candidates = index.entries
        others = [entry for entry in candidates if entry.mail_id != state.id]
        same_identity = next((entry for entry in candidates if entry.mail_id == state.id), None)
        matching_ids = [entry for entry in others if set(entry.message_ids) & set(message_ids)]
        matching_fingerprints = [entry for entry in others if entry.content_fingerprint == fingerprint]

        if state.duplicate is None:
            candidate: DuplicateIndexEntry | None = None
            reason = "no_match"
            outcome = "new"
            if (same_identity is not None
                    and same_identity.message_ids == message_ids
                    and same_identity.content_fingerprint == fingerprint):
                candidate = same_identity
                outcome, reason = "duplicate", "same_message"
            elif same_identity is not None:
                candidate = same_identity
                outcome = "ambiguous"
                reason = ("message_id_reused"
                          if set(same_identity.message_ids) & set(message_ids)
                          else "fingerprint_collision")
            elif message_id_headers != 1 or len(message_ids) != 1:
                candidate = next(iter(matching_ids or matching_fingerprints), None)
                if candidate is not None:
                    outcome = "ambiguous"
                reason = "multiple_message_ids" if message_id_headers > 1 else "missing_message_id"
            elif matching_ids:
                candidate = matching_ids[0]
                completed = []
                for entry in matching_ids:
                    previous = self.o.load_model(state_names.mail(entry.mail_id), MailState)
                    completed.append(isinstance(previous, MailState) and previous.steps.completion == "completed")
                if all(entry.content_fingerprint == fingerprint for entry in matching_ids) and all(completed):
                    outcome, reason = "duplicate", "same_message"
                elif not all(completed):
                    outcome, reason = "ambiguous", "candidate_incomplete"
                else:
                    outcome, reason = "ambiguous", "message_id_reused"
            elif matching_fingerprints:
                candidate = matching_fingerprints[0]
                outcome, reason = "ambiguous", "fingerprint_collision"
            state.duplicate = DuplicateDecision(outcome=outcome, reason=reason,
                                                previous_mail_id=candidate.mail_id if candidate else None)
            if outcome == "duplicate":
                state.steps.relevance = state.steps.summary = state.steps.action_detection = "skipped"
                state.steps.action_router = state.steps.task_extraction = state.steps.event_extraction = "skipped"
                state.steps.normalization = state.steps.proposal_building = "skipped"
                state.steps.summary_notification = state.steps.proposal_notification = "skipped"
                state.steps.completion = "completed"
            self.o.save(name, state)
            self.o.logger.event("INFO", "orchestrator", "duplicate_checked", mail_id=state.id,
                              outcome=outcome, reason=reason,
                              previous_mail_id=candidate.mail_id if candidate else None)

        entry = DuplicateIndexEntry(mail_id=state.id, imap=state.imap, message_ids=message_ids,
                                    content_fingerprint=fingerprint)
        index.entries = [item for item in index.entries if item.mail_id != state.id] + [entry]
        self.o.store.save("duplicate-index", index.model_dump(mode="json"))
        return state.duplicate.outcome == "duplicate"
