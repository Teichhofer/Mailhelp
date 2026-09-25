"""Restart-safe Telegram delivery orchestration."""

from __future__ import annotations

from ..models import Proposal
from .client import TelegramTransport
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

    def deliver(self, proposal: Proposal) -> None:
        self.repository.save_revision(proposal)
        mail = self.repository.load_mail(proposal.source_mail_id)
        sender = mail.display_headers.sender if mail and mail.display_headers else "—"
        subject = mail.display_headers.subject if mail and mail.display_headers else "—"
        presentation = self.presenter.present(proposal, sender, subject)
        status = self.repository.notification_status(proposal)
        if status == "completed" or status == "sending":
            return
        # Legacy states without per-proposal notification records remain
        # deliverable, while tracked records cross the durable boundary first.
        if status == "pending" and not self.repository.mark_notification_sending(
            proposal
        ):
            return
        for part in presentation.parts[:-1]:
            self.telegram.send(self.chat_id, part)
        self.telegram.send(
            self.chat_id, presentation.parts[-1], presentation.reply_markup
        )
        if status == "pending":
            self.repository.mark_notification_completed(proposal)


__all__ = ["ProposalDeliveryService"]
