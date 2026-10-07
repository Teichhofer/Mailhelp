"""Restart-safe Telegram delivery orchestration."""

from __future__ import annotations

from ..models import Proposal
from .client import TelegramTransport
from .outbox import TelegramOutbox
from .persistence import ProposalRepository
from .presenter import ProposalPresenter


class ProposalDeliveryService:
    """Persist and deliver a proposal using an explicit delivery state machine."""

    def __init__(
        self,
        repository: ProposalRepository,
        presenter: ProposalPresenter,
        telegram: TelegramTransport,
        chat_id: int,
    ):
        self.repository = repository
        self.presenter = presenter
        self.telegram = telegram
        self.chat_id = chat_id
        self.outbox: TelegramOutbox | None = None

    def deliver(self, proposal: Proposal) -> None:
        """Send immediately; used for direct answers within a running dialog."""
        self.repository.save_revision(proposal)
        status = self.repository.notification_status(proposal)
        if status in {"completed", "sending", "queued"}:
            return
        # Legacy states without per-proposal notification records remain
        # deliverable, while tracked records cross the durable boundary first.
        if status == "pending" and not self.repository.mark_notification_sending(
            proposal
        ):
            return
        self.send_now(proposal)
        if status == "pending":
            self.repository.mark_notification_completed(proposal)

    def enqueue(self, proposal: Proposal) -> None:
        """Queue a new proposal behind a possibly open question, then flush."""
        if self.outbox is None:
            self.deliver(proposal)
            return
        self.repository.save_revision(proposal)
        status = self.repository.notification_status(proposal)
        if status in {"completed", "sending"}:
            return
        # The queue entry is written first; a crash before the status mark
        # leaves a pending record whose repeated enqueue is idempotent.
        entry_id = self.outbox.enqueue_proposal(proposal)
        if status == "pending":
            self.repository.mark_notification_queued(proposal)
        self.outbox.flush(raise_for=entry_id)

    def send_now(self, proposal: Proposal) -> None:
        """Render and send the proposal without changing delivery state."""
        mail = self.repository.load_mail(proposal.source_mail_id)
        sender = mail.display_headers.sender if mail and mail.display_headers else "—"
        subject = mail.display_headers.subject if mail and mail.display_headers else "—"
        previous = (self.repository.load_version(
            proposal.source_mail_id, proposal.id, proposal.version - 1)
            if proposal.version > 1 else None)
        presentation = self.presenter.present(proposal, sender, subject, previous)
        for part in presentation.parts[:-1]:
            self.telegram.send(self.chat_id, part)
        self.telegram.send(
            self.chat_id, presentation.parts[-1], presentation.reply_markup
        )


__all__ = ["ProposalDeliveryService"]
