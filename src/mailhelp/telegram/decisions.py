"""Proposal decision state transitions, separate from update routing."""

from __future__ import annotations

from ..models import ProposalKind, ProposalStatus, TelegramDialogState
from ..storage import JsonStore
from .callbacks import Decision, DecisionAction, apply_decision
from .client import TelegramTransport
from .ledger import ActionLedgerPort
from .writes import ProposalPersistence, WriteExecution
from .persistence import ProposalRepository


class ProposalDecisionService:
    """Validate version-bound decisions and perform their state transitions."""

    def __init__(
        self,
        store: JsonStore,
        repository: ProposalRepository,
        persistence: ProposalPersistence,
        ledger: ActionLedgerPort,
        writes: WriteExecution,
        telegram: TelegramTransport,
        allowed_user: int,
        allowed_chat: int,
    ):
        self.store, self.repository, self.persistence = store, repository, persistence
        self.ledger, self.writes, self.telegram = ledger, writes, telegram
        self.allowed_user, self.allowed_chat = allowed_user, allowed_chat

    def decide(self, decision: Decision, user_id: int, chat_id: int) -> str:
        if (user_id, chat_id) != (self.allowed_user, self.allowed_chat):
            raise PermissionError("Nicht autorisierte Telegram-Anfrage")
        proposal = self.repository.load_current(decision.mail_id, decision.proposal_id)
        if proposal is None:
            raise ValueError("Vorschlag wurde nicht gefunden")
        if (proposal.source_mail_id, proposal.id, proposal.version) != (
            decision.mail_id,
            decision.proposal_id,
            decision.version,
        ) or proposal.status not in {
            ProposalStatus.PENDING_CONFIRMATION,
            ProposalStatus.NEEDS_CLARIFICATION,
        }:
            raise ValueError("Diese Schaltfläche ist veraltet")
        if decision.action == DecisionAction.EDIT:
            changed = proposal.model_copy(
                update={"status": ProposalStatus.NEEDS_CLARIFICATION}
            )
            self.persistence.persist(changed)
            self.store.save(
                "telegram-dialog",
                TelegramDialogState(
                    mail_id=proposal.source_mail_id,
                    proposal_id=proposal.id,
                    version=proposal.version,
                ).model_dump(),
            )
            prompt = (
                proposal.open_questions[0]
                if proposal.open_questions
                else "Welche Änderung soll übernommen werden?"
            )
            self.telegram.send(self.allowed_chat, prompt)
            return "✏️ Änderungsmodus gestartet."
        if (
            decision.action
            in {DecisionAction.CONFIRM, DecisionAction.CONFIRM_DUPLICATE}
            and proposal.status != ProposalStatus.PENDING_CONFIRMATION
        ):
            raise ValueError("Zuerst müssen die offenen Fragen beantwortet werden")
        confirming = decision.action in {
            DecisionAction.CONFIRM,
            DecisionAction.CONFIRM_DUPLICATE,
        }
        duplicates = self.ledger.prior_actions(proposal) if confirming else []
        if decision.action == DecisionAction.CONFIRM and duplicates:
            previous = duplicates[-1]
            duplicate = decision.model_copy(
                update={"action": DecisionAction.CONFIRM_DUPLICATE}
            )
            reject = decision.model_copy(update={"action": DecisionAction.REJECT})
            self.telegram.send(
                self.allowed_chat,
                "\n".join(
                    [
                        f"Bereits angelegt: {'Aufgabe' if previous.kind == ProposalKind.TASK else 'Termin'} „{previous.title}“.",
                        f"Frühere Quelle: Mail {previous.mail_id}, Vorschlag {previous.proposal_id}, Version {previous.proposal_version}.",
                        "Soll die Aktion wirklich ein zweites Mal angelegt bzw. versendet werden?",
                    ]
                ),
                {
                    "inline_keyboard": [
                        [
                            {
                                "text": "Erneut anlegen",
                                "callback_data": duplicate.encode(self.store),
                            },
                            {
                                "text": "Nicht erneut",
                                "callback_data": reject.encode(self.store),
                            },
                        ]
                    ]
                },
            )
            return "✅ Doppelanlage-Prüfung wurde entgegengenommen."
        if decision.action == DecisionAction.CONFIRM_DUPLICATE and not duplicates:
            raise ValueError("Die Doppelanlage-Bestätigung ist veraltet")
        changed = (
            proposal.model_copy(update={"status": ProposalStatus.REJECTED})
            if decision.action == DecisionAction.REJECT
            else apply_decision(
                proposal,
                decision.model_copy(update={"action": DecisionAction.CONFIRM}),
                user_id,
                chat_id,
                self.allowed_user,
                self.allowed_chat,
            )
        )
        self.persistence.persist(changed)
        if changed.status == ProposalStatus.CONFIRMED:
            self.writes.execute(changed)
            return "✅ Vorschlag wurde bestätigt."
        return "✅ Vorschlag wurde verworfen."


__all__ = ["ProposalDecisionService"]
