"""Proposal decision state transitions, separate from update routing."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from ..domain.proposal import invalidate_creation_permissions
from ..models import ActionLedgerEntry, Proposal, ProposalKind, ProposalStatus, TelegramDialogState
from ..review.errors import AnswerRequired, StaleCommand
from ..review.results import ResultStatus
from ..storage import JsonStore
from .callbacks import Decision, DecisionAction, apply_decision
from .client import TelegramTransport
from .formatting import clarification_prompt
from .ledger import ActionLedgerPort
from .persistence import ProposalRepository
from .writes import ProposalPersistence, WriteExecution

if TYPE_CHECKING:
    from ..precheck import DuplicatePreCheckService


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
        configured_timezone: str = "UTC",
    ):
        self.store, self.repository, self.persistence = store, repository, persistence
        self.ledger, self.writes, self.telegram = ledger, writes, telegram
        self.allowed_user, self.allowed_chat = allowed_user, allowed_chat
        self.configured_timezone = configured_timezone
        self.precheck: DuplicatePreCheckService | None = None
        self.profile_available: Callable[[Proposal], bool] = lambda proposal: True

    def decide(self, decision: Decision, user_id: int, chat_id: int) -> str:
        """Apply the decision and return the confirmation text ("" if none)."""
        return self.decide_with_status(decision, user_id, chat_id)[1]

    def decide_with_status(self, decision: Decision, user_id: int, chat_id: int,
                           write_authorizer: Callable[[], bool] | None = None) -> tuple[ResultStatus, str]:
        """Apply the decision; stale or premature decisions raise a ReviewError."""
        if (user_id, chat_id) != (self.allowed_user, self.allowed_chat):
            raise PermissionError("Nicht autorisierte Telegram-Anfrage")
        from ..proposal_reconciliation import ProposalReconciliationService
        ProposalReconciliationService(self.store).recover()
        proposal = self._open_proposal(decision)
        if decision.action == DecisionAction.EDIT:
            return self._start_edit(proposal)
        if (
            decision.action
            in {DecisionAction.CONFIRM, DecisionAction.CONFIRM_DUPLICATE}
            and proposal.status != ProposalStatus.PENDING_CONFIRMATION
        ):
            raise AnswerRequired("Zuerst müssen die offenen Fragen beantwortet werden")
        confirming = decision.action in {
            DecisionAction.CONFIRM,
            DecisionAction.CONFIRM_DUPLICATE,
        }
        if confirming and not self.profile_available(proposal):
            raise AnswerRequired("Zielprofil nicht mehr konfiguriert oder nicht verfügbar")
        if confirming:
            candidates = ProposalReconciliationService(self.store).confirmation_candidates(proposal)
            if candidates:
                revised = proposal.model_copy(update={"version": proposal.version + 1,
                    "status": ProposalStatus.NEEDS_CLARIFICATION, "matching_candidates": candidates,
                    "explicit_duplicate_create_confirmed_version": None,
                    "open_questions": ["Zuordnung zu bestehenden Entscheidungen prüfen; keine Neuanlage freigegeben."]})
                revised = invalidate_creation_permissions(revised)
                self.persistence.persist(revised)
                raise StaleCommand("Offene Entscheidungen haben sich geändert; neue Version prüfen")
        if confirming and self.precheck is not None:
            checked = self.precheck.check_proposal(proposal)
            fields = ("status", "duplicate_check_failed", "target_event_id", "time_changes", "is_cancellation")
            if any(getattr(checked, field) != getattr(proposal, field) for field in fields):
                checked = checked.model_copy(update={"version": proposal.version + 1,
                    "explicit_duplicate_create_confirmed_version": None})
                checked = invalidate_creation_permissions(checked)
                self.persistence.persist(checked)
                raise StaleCommand("Dublettenprüfung hat den Vorschlag geändert; neue Version prüfen")
        duplicates = self.ledger.prior_actions(proposal) if confirming else []
        if decision.action == DecisionAction.CONFIRM and duplicates:
            self._ask_about_duplicate(decision, duplicates[-1])
            return (ResultStatus.NEEDS_DUPLICATE_CONFIRMATION,
                    "✅ Doppelanlage-Prüfung wurde entgegengenommen.")
        if decision.action == DecisionAction.CONFIRM_DUPLICATE and not duplicates:
            raise StaleCommand("Die Doppelanlage-Bestätigung ist veraltet")
        if confirming and write_authorizer is not None and not write_authorizer():
            raise StaleCommand("Websitzung vor Ausführung ungültig geworden")
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
        if decision.action == DecisionAction.CONFIRM_DUPLICATE:
            changed = changed.model_copy(update={
                "explicit_duplicate_create_confirmed_version": changed.version,
            })
        self.persistence.persist(changed)
        if changed.status == ProposalStatus.CONFIRMED:
            return self._write(changed)
        return ResultStatus.DONE, "✅ Vorschlag wurde verworfen."

    def _open_proposal(self, decision: Decision) -> Proposal:
        """The exact proposal version the button belongs to, while it still awaits a decision."""
        proposal = self.repository.load_current(decision.mail_id, decision.proposal_id)
        if proposal is None:
            raise StaleCommand("Vorschlag wurde nicht gefunden")
        if (proposal.source_mail_id, proposal.id, proposal.version) != (
            decision.mail_id,
            decision.proposal_id,
            decision.version,
        ) or proposal.status not in {
            ProposalStatus.PENDING_CONFIRMATION,
            ProposalStatus.NEEDS_CLARIFICATION,
        }:
            raise StaleCommand("Diese Schaltfläche ist veraltet")
        return proposal

    def _start_edit(self, proposal: Proposal) -> tuple[ResultStatus, str]:
        """Open the clarification dialog; repeating it while it waits sends nothing new."""
        active = TelegramDialogState.model_validate(
            self.store.load("telegram-dialog", TelegramDialogState().model_dump()))
        if (
            (active.mail_id, active.proposal_id, active.version)
            == (proposal.source_mail_id, proposal.id, proposal.version)
            and proposal.status == ProposalStatus.NEEDS_CLARIFICATION
            and active.question is None
            and not active.retry_required
        ):
            return (ResultStatus.DONE,
                    "✏️ Änderungsmodus läuft bereits – bitte die Rückfrage oben beantworten.")
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
        prompt = clarification_prompt(proposal, self.configured_timezone)
        self.telegram.send(self.allowed_chat, prompt)
        # The question itself is the confirmation; no second message.
        return ResultStatus.DONE, ""

    def _ask_about_duplicate(self, decision: Decision, previous: ActionLedgerEntry) -> None:
        """An action like this was created before: ask before doing it twice."""
        source = self.repository.load_mail(previous.mail_id)
        headers = source.display_headers if source is not None else None
        source_text = (f"Absender: {headers.sender}\nBetreff: {headers.subject}"
                       if headers is not None else "Quellangaben nicht mehr verfügbar.")
        duplicate = decision.model_copy(
            update={"action": DecisionAction.CONFIRM_DUPLICATE}
        )
        reject = decision.model_copy(update={"action": DecisionAction.REJECT})
        self.telegram.send(
            self.allowed_chat,
            "\n".join(
                [
                    f"Bereits angelegt: {'Aufgabe' if previous.kind == ProposalKind.TASK else 'Termin'} "
                    f"„{previous.title}“.",
                    f"Frühere Quelle (Version {previous.proposal_version}):\n{source_text}",
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

    def _write(self, changed: Proposal) -> tuple[ResultStatus, str]:
        """Execute the confirmed write and translate its outcome."""
        result = self.writes.execute(changed)
        if result.status in {ProposalStatus.CREATED, ProposalStatus.SIMULATED}:
            # The write result message already reports the outcome.
            return ResultStatus.WRITTEN, ""
        if result.status == ProposalStatus.UNCERTAIN:
            return (ResultStatus.WRITE_UNCERTAIN,
                    "⚠️ Vorschlag bestätigt; externe Anlage ist noch unklar.")
        if result.status == ProposalStatus.FAILED:
            return (ResultStatus.WRITE_FAILED,
                    "❌ Vorschlag bestätigt; externe Anlage fehlgeschlagen.")
        return (ResultStatus.NOT_WRITTEN,
                "⚠️ Vorschlag intern bestätigt; keine externe Anlage ausgeführt.")

__all__ = ["ProposalDecisionService"]
