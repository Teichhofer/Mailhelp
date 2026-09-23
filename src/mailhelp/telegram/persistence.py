"""Named, crash-safe persistence operations for Telegram proposals."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from ..models import (
    MailState, Proposal, ProposalNotification, ProposalStatus,
    WriteAttemptReference,
)
from ..storage import JsonStore


def proposal_name(mail_id: str, proposal_id: str) -> str:
    return f"proposal-{mail_id}-{proposal_id}"


def proposal_version_name(mail_id: str, proposal_id: str, version: int) -> str:
    return f"proposal-{mail_id}-{proposal_id}-v{version}"


def clarification_name(mail_id: str, proposal_id: str, version: int) -> str:
    return f"clarification-{mail_id}-{proposal_id}-v{version}"


class ProposalPersistence(Protocol):
    """Port consumed by write and revision services."""

    def persist(self, proposal: Proposal) -> None: ...
    def send_proposal(self, proposal: Proposal) -> None: ...


class ProposalRepository:
    """Keep proposal snapshots, current records, and mail projections in sync.

    ``save_revision`` deliberately writes the immutable snapshot first, the
    authoritative current record second, and the denormalized mail projection
    last.  Repeating the operation after any interruption repairs the latter
    records without modifying an existing snapshot.
    """

    def __init__(self, store: JsonStore):
        self.store = store

    def load_current(self, mail_id: str, proposal_id: str) -> Proposal | None:
        value = self.store.load_model(proposal_name(mail_id, proposal_id), Proposal)
        return value if isinstance(value, Proposal) else None

    def load_version(self, mail_id: str, proposal_id: str,
                     version: int) -> Proposal | None:
        value = self.store.load_model(
            proposal_version_name(mail_id, proposal_id, version), Proposal)
        return value if isinstance(value, Proposal) else None

    def load_mail(self, mail_id: str) -> MailState | None:
        value = self.store.load_model(f"mail-{mail_id}", MailState)
        return value if isinstance(value, MailState) else None

    def save_revision(self, proposal: Proposal) -> None:
        value = proposal.model_dump(mode="json")
        version = proposal_version_name(
            proposal.source_mail_id, proposal.id, proposal.version)
        if self.store.load(version) is None:
            self.store.save(version, value)
        self.store.save(proposal_name(proposal.source_mail_id, proposal.id), value)
        state = self.load_mail(proposal.source_mail_id)
        if state is None:
            return
        proposals = [proposal if item.id == proposal.id else item
                     for item in state.proposals]
        notifications: list[ProposalNotification] = []
        for item in proposals:
            previous = next((entry for entry in state.proposal_notifications
                             if (entry.proposal_id, entry.proposal_version) ==
                             (item.id, item.version)), None)
            if previous is not None:
                notifications.append(previous)
            elif item.id == proposal.id and any(
                    old.id == proposal.id for old in state.proposals):
                notifications.append(ProposalNotification(
                    proposal_id=item.id, proposal_version=item.version))
        attempts = self._write_attempts(state, proposal)
        if (proposals, notifications, attempts) == (
                state.proposals, state.proposal_notifications,
                state.write_attempts):
            return
        changed = state.model_copy(update={
            "proposals": proposals,
            "proposal_notifications": notifications,
            "write_attempts": attempts,
            "updated_at": datetime.now(timezone.utc),
        })
        self.store.save(f"mail-{proposal.source_mail_id}",
                        changed.model_dump(mode="json"))

    def record_write_attempt(self, proposal: Proposal) -> None:
        """Add the stable write reference to the mail projection, once."""
        state = self.load_mail(proposal.source_mail_id)
        if state is None:
            return
        attempts = self._write_attempts(state, proposal, force=True)
        if attempts == state.write_attempts:
            return
        changed = state.model_copy(update={
            "write_attempts": attempts,
            "updated_at": datetime.now(timezone.utc),
        })
        self.store.save(f"mail-{proposal.source_mail_id}",
                        changed.model_dump(mode="json"))

    def mark_notification_sending(self, proposal: Proposal) -> bool:
        return self._mark_notification(proposal, "pending", "sending")

    def mark_notification_completed(self, proposal: Proposal) -> bool:
        return self._mark_notification(proposal, "sending", "completed")

    def notification_status(self, proposal: Proposal) -> str | None:
        state = self.load_mail(proposal.source_mail_id)
        if state is None:
            return None
        entry = next((item for item in state.proposal_notifications
                      if (item.proposal_id, item.proposal_version) ==
                      (proposal.id, proposal.version)), None)
        return entry.status if entry is not None else None

    def _mark_notification(self, proposal: Proposal, expected: str,
                           target: str) -> bool:
        state = self.load_mail(proposal.source_mail_id)
        if state is None:
            return False
        changed = False
        notifications = []
        for item in state.proposal_notifications:
            if ((item.proposal_id, item.proposal_version) ==
                    (proposal.id, proposal.version) and item.status == expected):
                item = item.model_copy(update={"status": target})
                changed = True
            notifications.append(item)
        if changed:
            updated = state.model_copy(update={
                "proposal_notifications": notifications,
                "updated_at": datetime.now(timezone.utc),
            })
            self.store.save(f"mail-{proposal.source_mail_id}",
                            updated.model_dump(mode="json"))
        return changed

    @staticmethod
    def _write_attempts(state: MailState, proposal: Proposal,
                        force: bool = False) -> list[WriteAttemptReference]:
        tracked = proposal.status in {
            ProposalStatus.WRITING, ProposalStatus.CREATED,
            ProposalStatus.FAILED, ProposalStatus.UNCERTAIN,
        }
        if not tracked and not force:
            return state.write_attempts
        service = ("todoist" if proposal.kind.value == "task"
                   else "google_calendar")
        reference = WriteAttemptReference(
            mail_id=proposal.source_mail_id, proposal_id=proposal.id,
            proposal_version=proposal.version, service=service,
            idempotency_key=(f"mailhelp:{proposal.source_mail_id}:"
                             f"{proposal.id}:v{proposal.version}"),
        )
        attempts = [item for item in state.write_attempts
                    if (item.proposal_id, item.proposal_version, item.service) !=
                    (reference.proposal_id, reference.proposal_version,
                     reference.service)]
        attempts.append(reference)
        return attempts


__all__ = [
    "ProposalPersistence", "ProposalRepository", "clarification_name",
    "proposal_name", "proposal_version_name",
]
