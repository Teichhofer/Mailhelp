"""Durable, ordered Telegram outbox that shows one open decision at a time.

Mail processing produces notifications asynchronously.  Once a message with
decision buttons (a relevance question or any undecided proposal, with or
without open questions) has been shown, every later notification stays queued
until that decision is resolved.  Afterwards the queue is sent in order up to
and including the next decision.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Callable, Protocol

from ..domain.processing import (
    ProposalClarificationState,
    ProposalRevisionStatus,
    QuestionStatus,
    TelegramOutboxEntry,
    TelegramOutboxGate,
    TelegramOutboxState,
)
from ..models import Proposal, ProposalStatus, RelevanceDialog, RelevanceDialogStatus
from ..storage import JsonStore
from .client import TelegramTransport
from .persistence import ProposalRepository, clarification_name, proposal_name
from .revisions import EventLogger

OUTBOX_NAME = "telegram-outbox"
_OPEN = {ProposalStatus.PENDING_CONFIRMATION, ProposalStatus.NEEDS_CLARIFICATION}
# A proposal version in one of these delivery states has not been shown yet.
_UNSHOWN = {"pending", "queued"}


def revision_paused(store: JsonStore, proposal: Proposal) -> bool:
    """Return whether an answered revision waits for an operator, not the user."""
    clarification = store.load_model(
        clarification_name(proposal.source_mail_id, proposal.id, proposal.version),
        ProposalClarificationState,
    )
    return (
        isinstance(clarification, ProposalClarificationState)
        and clarification.question_status == QuestionStatus.ANSWERED
        and clarification.proposal_revision_status == ProposalRevisionStatus.PAUSED
    )


class RelevanceLookup(Protocol):
    def all(self) -> list[RelevanceDialog]: ...
    def open(self) -> list[RelevanceDialog]: ...


class TelegramOutbox:
    """Queue, hold, and send Telegram notifications in their creation order."""

    def __init__(
        self,
        store: JsonStore,
        telegram: TelegramTransport,
        chat_id: int,
        logger: EventLogger,
        repository: ProposalRepository,
        send_proposal: Callable[[Proposal], None],
        send_relevance: Callable[[RelevanceDialog, str, str], None],
        relevance: RelevanceLookup,
        enabled: bool = True,
    ):
        self.store, self.telegram, self.chat_id = store, telegram, chat_id
        self.logger, self.repository = logger, repository
        self.send_proposal, self.send_relevance = send_proposal, send_relevance
        self.relevance, self.enabled = relevance, enabled

    def load(self) -> TelegramOutboxState:
        state = self.store.load_model(
            OUTBOX_NAME, TelegramOutboxState, TelegramOutboxState()
        )
        assert isinstance(state, TelegramOutboxState)
        return state

    def _save(self, state: TelegramOutboxState) -> None:
        self.store.save(OUTBOX_NAME, state.model_dump(mode="json"))

    def queued_proposals(self) -> set[tuple[str, str, int]]:
        """Return proposal versions that the user has not been shown yet."""
        return {
            (entry.mail_id, entry.proposal_id, entry.version)
            for entry in self.load().entries
            if entry.kind == "proposal"
        }

    def queued_relevance(self) -> set[tuple[str, int]]:
        """Relevance questions not yet attempted must not pause other mail."""
        return {(entry.mail_id, entry.version) for entry in self.load().entries
                if entry.kind == "relevance" and entry.status == "queued"}

    @staticmethod
    def _uncertain_gate(entry: TelegramOutboxEntry) -> TelegramOutboxGate | None:
        """Preserve a possibly delivered question without resending it."""
        if entry.kind == "message":
            return None
        return TelegramOutboxGate(kind=entry.kind, mail_id=entry.mail_id,
                                  proposal_id=entry.proposal_id, version=entry.version)

    def held_count(self) -> int:
        return len(self.load().entries)

    def enqueue_proposal(self, proposal: Proposal) -> str:
        return self._enqueue(
            kind="proposal",
            mail_id=proposal.source_mail_id,
            proposal_id=proposal.id,
            version=proposal.version,
        )

    def enqueue_relevance(
        self, dialog: RelevanceDialog, sender: str, subject: str
    ) -> str:
        return self._enqueue(
            kind="relevance",
            mail_id=dialog.mail_id,
            version=dialog.version,
            sender=sender,
            subject=subject,
        )

    def enqueue_message(self, text: str) -> str:
        return self._enqueue(kind="message", text=text)

    def _enqueue(self, **reference: object) -> str:
        state = self.load()
        if reference["kind"] != "message":
            # Referenced items are idempotent: a repeated enqueue after a
            # restart must not show the same question twice.
            for entry in state.entries:
                if all(getattr(entry, key) == value for key, value in reference.items()
                       if key in {"kind", "mail_id", "proposal_id", "version"}):
                    return entry.id
        entry = TelegramOutboxEntry(
            id=uuid.uuid4().hex, created_at=datetime.now(timezone.utc), **reference
        )
        state.entries.append(entry)
        self._save(state)
        self.logger.event(
            "INFO", "telegram.outbox", "outbox_enqueued",
            entry_id=entry.id, kind=entry.kind, mail_id=entry.mail_id,
            queued=len(state.entries),
        )
        return entry.id

    def gate_open(self, gate: TelegramOutboxGate | None) -> bool:
        """Return whether *gate* still holds back the following messages.

        A proposal stays open across versions until it is decided: a complete
        revision after a clarification still awaits its confirmation.
        """
        if gate is None or not self.enabled:
            return False
        if gate.kind == "relevance":
            return any(
                (dialog.mail_id, dialog.version) == (gate.mail_id, gate.version)
                for dialog in self.relevance.open()
            )
        assert gate.proposal_id is not None
        current = self.repository.load_current(gate.mail_id, gate.proposal_id)
        return (
            current is not None
            and current.status in _OPEN
            and not revision_paused(self.store, current)
        )

    def shown_open_decisions(self) -> list[TelegramOutboxGate]:
        """Return every already shown, still open decision in mail order.

        Entries still waiting in the outbox do not count.  Relevance questions
        come first because they also pause the mail analysis.
        """
        queued_relevance = self.queued_relevance()
        decisions = [
            TelegramOutboxGate(kind="relevance", mail_id=dialog.mail_id,
                               version=dialog.version)
            for dialog in self.relevance.open()
            if (dialog.mail_id, dialog.version) not in queued_relevance
        ]
        queued = self.queued_proposals()
        ordered: list[tuple[tuple[int, int, str, str], TelegramOutboxGate]] = []
        for name in self.store.names("proposal-"):
            proposal = self.store.load_model(name, Proposal)
            if (not isinstance(proposal, Proposal)
                    or name != proposal_name(proposal.source_mail_id, proposal.id)
                    or proposal.status not in _OPEN
                    or revision_paused(self.store, proposal)
                    or (proposal.source_mail_id, proposal.id, proposal.version) in queued
                    or self.repository.notification_status(proposal) in _UNSHOWN):
                continue
            mail = self.repository.load_mail(proposal.source_mail_id)
            position = (
                (mail.imap.uid, [item.id for item in mail.proposals].index(proposal.id))
                if mail is not None and any(item.id == proposal.id for item in mail.proposals)
                else (0, 0)
            )
            ordered.append(((*position, proposal.source_mail_id, proposal.id),
                            TelegramOutboxGate(
                                kind="proposal", mail_id=proposal.source_mail_id,
                                proposal_id=proposal.id, version=proposal.version)))
        return decisions + [gate for _, gate in sorted(ordered, key=lambda pair: pair[0])]

    def current_decision(self) -> TelegramOutboxGate | None:
        """Return the decision that currently holds back later messages."""
        if not self.enabled:
            return None
        state = self.load()
        if self.gate_open(state.active):
            return state.active
        return next(iter(self.shown_open_decisions()), None)

    def _set_gate(self, state: TelegramOutboxState,
                  gate: TelegramOutboxGate | None) -> None:
        if gate == state.active:
            return
        previous, state.active = state.active, gate
        self._save(state)
        if previous is not None:
            self.logger.event("INFO", "telegram.outbox", "outbox_gate_released",
                              kind=previous.kind, mail_id=previous.mail_id)
        if gate is not None:
            self.logger.event("INFO", "telegram.outbox", "outbox_gate_set",
                              kind=gate.kind, mail_id=gate.mail_id)

    def flush(self, raise_for: str | None = None) -> None:
        """Send queued messages in order until a shown decision is still open.

        A failure while sending is an uncertain delivery: the entry is never
        sent automatically again.  It is re-raised only to the caller that
        enqueued it, so a provider error is never attributed to another mail.
        """
        state = self.load()
        for entry in [item for item in state.entries if item.status == "sending"]:
            # Interrupted between persisting and confirming the send.
            state.active = self._uncertain_gate(entry)
            state.entries.remove(entry)
            self._save(state)
            self.logger.event(
                "WARNING", "telegram.outbox", "outbox_delivery_uncertain",
                entry_id=entry.id, kind=entry.kind, mail_id=entry.mail_id,
            )
        while state.entries:
            gate = self.current_decision()
            self._set_gate(state, gate)
            if gate is not None:
                self.logger.event(
                    "DEBUG", "telegram.outbox", "outbox_held",
                    queued=len(state.entries), gate_kind=gate.kind,
                    gate_mail_id=gate.mail_id,
                )
                return
            entry = state.entries[0]
            entry.status = "sending"
            self._save(state)
            try:
                gate = self._dispatch(entry)
            except Exception as exc:
                state.active = self._uncertain_gate(entry)
                state.entries.pop(0)
                self._save(state)
                self.logger.event(
                    "ERROR", "telegram.outbox", "outbox_delivery_failed",
                    entry_id=entry.id, kind=entry.kind, mail_id=entry.mail_id,
                    error_class=type(exc).__name__,
                )
                if entry.id == raise_for:
                    raise
                return
            state.entries.pop(0)
            self._save(state)
            if gate is not None:
                self._set_gate(state, gate)

    def _dispatch(self, entry: TelegramOutboxEntry) -> TelegramOutboxGate | None:
        if entry.kind == "message":
            assert entry.text is not None
            self.telegram.send(self.chat_id, entry.text)
            self._sent(entry)
            return None
        assert entry.mail_id is not None and entry.version is not None
        if entry.kind == "relevance":
            stored = next(
                (item for item in self.relevance.all()
                 if (item.mail_id, item.version) == (entry.mail_id, entry.version)),
                None,
            )
            if stored is not None and stored.status != RelevanceDialogStatus.OPEN:
                # Answered by free text while it was still queued.
                self._skipped(entry)
                return None
            assert entry.sender is not None and entry.subject is not None
            self.send_relevance(
                RelevanceDialog(mail_id=entry.mail_id, version=entry.version),
                entry.sender, entry.subject,
            )
            self._sent(entry)
            return TelegramOutboxGate(
                kind="relevance", mail_id=entry.mail_id, version=entry.version
            )
        assert entry.proposal_id is not None
        proposal = self.repository.load_current(entry.mail_id, entry.proposal_id)
        if (
            proposal is None
            or proposal.version != entry.version
            or proposal.status not in _OPEN
        ):
            # Already decided or revised (e.g. through /offen) while queued.
            self._skipped(entry)
            return None
        status = self.repository.notification_status(proposal)
        if status in {"sending", "completed"}:
            self._skipped(entry)
            return None
        if status == "queued":
            self.repository.mark_queued_notification_sending(proposal)
        self.send_proposal(proposal)
        if status is not None:
            self.repository.mark_notification_completed(proposal)
        self._sent(entry)
        return TelegramOutboxGate(
            kind="proposal", mail_id=proposal.source_mail_id,
            proposal_id=proposal.id, version=proposal.version,
        )

    def _sent(self, entry: TelegramOutboxEntry) -> None:
        self.logger.event(
            "INFO", "telegram.outbox", "outbox_sent",
            entry_id=entry.id, kind=entry.kind, mail_id=entry.mail_id,
        )

    def _skipped(self, entry: TelegramOutboxEntry) -> None:
        self.logger.event(
            "INFO", "telegram.outbox", "outbox_skipped_obsolete",
            entry_id=entry.id, kind=entry.kind, mail_id=entry.mail_id,
        )


__all__ = ["OUTBOX_NAME", "TelegramOutbox", "revision_paused"]
