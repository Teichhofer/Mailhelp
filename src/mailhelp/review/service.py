"""Execute review commands without knowledge of the channel they came from.

The state transitions themselves stay in the existing services
(``ProposalDecisionService``, ``ProposalRevisionProcessor`` and the relevance
dialog).  The review service checks authorization and the referenced version,
translates the command for those services and returns a typed result.  It runs
exclusively in the main thread.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from .. import state_names
from ..configuration import AdminCommand, ConfigurationService
from ..domain.processing import ProposalClarificationState
from ..models import MailState, Proposal, ProposalStatus, RelevanceDialogStatus, TelegramDialogState
from ..notification_context import web_reply
from .archive import record_event, record_relevance
from .commands import CommandKind, CommandSource, ReviewCommand
from .editing import edit_proposal
from .errors import AnswerRequired, ReviewBusy, ReviewError, StaleCommand
from .results import ResultStatus, ReviewResult

_OPEN = {ProposalStatus.PENDING_CONFIRMATION, ProposalStatus.NEEDS_CLARIFICATION}
_DIALOG = "telegram-dialog"

# Shown in the web; Telegram keeps its own confirmation texts.
_DONE_MESSAGES = {
    CommandKind.REJECT: "Vorschlag verworfen.",
    CommandKind.START_CLARIFICATION: "Bearbeitung gestartet – bitte die Rückfrage beantworten.",
    CommandKind.ANSWER: "Antwort übernommen – der Vorschlag wird aktualisiert.",
    CommandKind.CANCEL_CLARIFICATION: "Bearbeitung beendet; der Vorschlag ist unverändert.",
}
_STATUS_MESSAGES = {
    ResultStatus.WRITTEN: "Angelegt.",
    ResultStatus.NEEDS_DUPLICATE_CONFIRMATION:
        "Diese Aktion wurde bereits früher angelegt. Wirklich erneut anlegen?",
    ResultStatus.WRITE_UNCERTAIN: "Bestätigt; die externe Anlage ist noch unklar und wird abgeglichen.",
    ResultStatus.WRITE_FAILED: "Bestätigt; die externe Anlage ist fehlgeschlagen.",
    ResultStatus.NOT_WRITTEN: "Bestätigt; keine externe Anlage ausgeführt.",
}
_DECISION_ACTIONS = {
    CommandKind.CONFIRM: "confirm",
    CommandKind.CONFIRM_DUPLICATE: "confirm_duplicate",
    CommandKind.REJECT: "reject",
    CommandKind.START_CLARIFICATION: "edit",
}


class ReviewService:
    """Authorize, check and apply one review command at a time."""

    def __init__(self, controller: Any,
                 web_authorizer: Callable[[str], bool] | None = None):
        self.controller = controller
        # Confirms that a web session is still valid when the command runs,
        # so a session revoked after submitting cannot act any more.
        self.web_authorizer = web_authorizer
        self.configuration: ConfigurationService | None = None
        self.completed: Callable[[ReviewCommand | AdminCommand, ReviewResult], None] | None = None

    def execute(self, command: ReviewCommand | AdminCommand, *, raise_errors: bool = False) -> ReviewResult:
        token = web_reply.set(command.source == CommandSource.WEB)
        try:
            result = self._execute_command(command, raise_errors=raise_errors)
            if self.completed is not None:
                self.completed(command, result)
            return result
        finally:
            web_reply.reset(token)

    def _execute_command(self, command: ReviewCommand | AdminCommand, *, raise_errors: bool = False) -> ReviewResult:
        """Apply *command*; with *raise_errors*, a rejected command raises instead."""
        if isinstance(command, AdminCommand):
            if self.configuration is None:
                return ReviewResult(status=ResultStatus.INVALID, message="Konfigurationsdienst nicht verfügbar.")
            return self.configuration.execute(command)
        if not self._authorized(command):
            return ReviewResult(status=ResultStatus.UNAUTHORIZED, message="Nicht autorisiert.")
        try:
            result = self._execute(command)
            self._record(command)
            return result
        except (ReviewError, ValidationError, ValueError) as exc:
            if raise_errors:
                raise
            return ReviewResult(status=_error_status(exc), message=_error_message(exc))

    def _record(self, command: ReviewCommand) -> None:
        if command.proposal_id is None:
            state = self.controller.store.load_model(state_names.mail(command.mail_id), MailState)
            if state is not None:
                record_relevance(self.controller.store, state, command.source.value, command.idempotency_key)
            return
        current = self.controller.repository.load_current(command.mail_id, command.proposal_id)
        if current is not None:
            record_event(self.controller.store, current, command.kind.value, command.source.value,
                         command.idempotency_key)

    def reconcile(self, command: ReviewCommand | AdminCommand) -> ReviewResult:
        """Result of a command interrupted by a restart, judged from the current state.

        The command is never executed again: if its effect is visible it
        counts as done, otherwise the user is asked to trigger it again.
        """
        if isinstance(command, AdminCommand):
            if self.configuration is None:
                return ReviewResult(status=ResultStatus.FAILED, message="Konfigurationsdienst nicht verfügbar.")
            return self.configuration.reconcile(command)
        if self._took_effect(command):
            self._record(command)
            return ReviewResult(status=ResultStatus.DONE,
                                message="Nach einem Neustart abgeglichen; der aktuelle Stand wird angezeigt.")
        return ReviewResult(status=ResultStatus.FAILED,
                            message="Durch einen Neustart unterbrochen – bitte prüfen und erneut auslösen.")

    def _took_effect(self, command: ReviewCommand) -> bool:
        store = self.controller.store
        if command.kind == CommandKind.RELEVANCE:
            mail = store.load_model(state_names.mail(command.mail_id), MailState)
            dialog = mail.relevance_dialog if isinstance(mail, MailState) else None
            return dialog is not None and dialog.status == RelevanceDialogStatus.DECIDED
        assert command.proposal_id is not None
        current = self.controller.repository.load_current(command.mail_id, command.proposal_id)
        if current is None:
            return False
        if current.version != command.version or current.status not in _OPEN:
            return True
        pointer = self._pointer()
        on_target = (pointer.mail_id, pointer.proposal_id, pointer.version) == (
            command.mail_id, command.proposal_id, command.version)
        if command.kind == CommandKind.START_CLARIFICATION:
            return on_target
        if command.kind == CommandKind.CANCEL_CLARIFICATION:
            return not on_target
        if command.kind == CommandKind.ANSWER:
            answer = store.load_model(
                state_names.clarification(command.mail_id, command.proposal_id, command.version),
                ProposalClarificationState)
            return isinstance(answer, ProposalClarificationState) and answer.authorized_answer is not None
        return False

    def _authorized(self, command: ReviewCommand) -> bool:
        if command.source == CommandSource.TELEGRAM:
            return command.actor == (
                f"telegram:{self.controller.user_id}:{self.controller.chat_id}")
        return (command.actor.startswith("web:") and self.web_authorizer is not None
                and self.web_authorizer(command.actor))

    def _execute(self, command: ReviewCommand) -> ReviewResult:
        if command.kind == CommandKind.EDIT:
            assert command.patch is not None  # ReviewCommand requires a patch for EDIT
            previous = self._target(command)
            targets = {previous.target}
            handler = self.controller.relevance_handler
            configured = getattr(handler, "targets", None)
            if configured is not None:
                targets.add(configured.todoist_project if previous.kind.value == "task" else configured.google_calendar)
            revised = edit_proposal(previous, command.patch, self.controller.configured_timezone, targets)
            self.controller.persist(revised)
            record_event(self.controller.store, revised, "edit", command.source.value, command.idempotency_key)
            if revised.version != previous.version:
                self.controller.send_proposal(revised)
            return ReviewResult(status=ResultStatus.DONE, message="Neue Version gespeichert; bitte separat bestätigen.")
        if command.kind == CommandKind.RELEVANCE:
            return self._relevance(command)
        if command.kind == CommandKind.ANSWER:
            return self._answer(command)
        if command.kind == CommandKind.CANCEL_CLARIFICATION:
            return self._cancel(command)
        return self._decide(command)

    def _decide(self, command: ReviewCommand) -> ReviewResult:
        from ..telegram.callbacks import Decision, DecisionAction

        if command.source == CommandSource.WEB:
            # Named in web terms; Telegram's own check speaks of buttons.
            self._target(command)
        assert command.proposal_id is not None  # decisions always name a proposal
        decision = Decision(
            mail_id=command.mail_id, proposal_id=command.proposal_id,
            version=command.version,
            action=DecisionAction(_DECISION_ACTIONS[command.kind]),
        )
        status, text = self.controller.decision_service.decide_with_status(
            decision, self.controller.user_id, self.controller.chat_id)
        if command.source == CommandSource.TELEGRAM:
            return ReviewResult(status=status, message=text)
        message = _STATUS_MESSAGES.get(status) or _DONE_MESSAGES[command.kind]
        return ReviewResult(status=status, message=message)

    def _relevance(self, command: ReviewCommand) -> ReviewResult:
        from ..telegram.callbacks import RelevanceDecision

        assert command.decision is not None
        offset = command.replay_offset or max(self.controller.receive_offset(), 1)
        try:
            text = self.controller.decide_relevance(
                RelevanceDecision(mail_id=command.mail_id, version=command.version,
                                  decision=command.decision), offset)
        except ReviewError:
            raise
        except ValueError as exc:
            # The relevance dialog reports a stale or answered question this way.
            raise StaleCommand(str(exc)[:500]) from exc
        if command.source == CommandSource.TELEGRAM:
            return ReviewResult(status=ResultStatus.DONE, message=text or "")
        label = "relevant" if command.decision == "relevant" else "irrelevant"
        return ReviewResult(status=ResultStatus.DONE, message=f"Mail als {label} eingestuft.")

    def _target(self, command: ReviewCommand) -> Proposal:
        assert command.proposal_id is not None
        proposal = self.controller.repository.load_current(command.mail_id, command.proposal_id)
        if proposal is None:
            raise StaleCommand("Vorschlag wurde nicht gefunden")
        if proposal.version != command.version or proposal.status not in _OPEN:
            raise StaleCommand("Der Vorschlag wurde inzwischen geändert oder entschieden")
        return proposal

    def _pointer(self) -> TelegramDialogState:
        state = self.controller.store.load_model(_DIALOG, TelegramDialogState, TelegramDialogState())
        assert isinstance(state, TelegramDialogState)
        return state

    def _answer(self, command: ReviewCommand) -> ReviewResult:
        """Point the clarification at this version, then answer like Telegram free text."""
        proposal = self._target(command)
        pointer = self._pointer()
        target = (proposal.source_mail_id, proposal.id, proposal.version)
        if (pointer.mail_id, pointer.proposal_id, pointer.version) != target:
            if pointer.retry_required:
                raise ReviewBusy("Eine andere Antwort wird gerade verarbeitet; bitte gleich erneut senden.")
            if proposal.status == ProposalStatus.PENDING_CONFIRMATION:
                self.controller.persist(proposal.model_copy(
                    update={"status": ProposalStatus.NEEDS_CLARIFICATION}))
            self.controller.store.save(_DIALOG, TelegramDialogState(
                mail_id=proposal.source_mail_id, proposal_id=proposal.id,
                version=proposal.version).model_dump(mode="json"))
        assert command.text is not None
        self.controller.revisions.answer(command.text)
        return ReviewResult(status=ResultStatus.DONE, message=_DONE_MESSAGES[command.kind])

    def _cancel(self, command: ReviewCommand) -> ReviewResult:
        from ..telegram.commands import TelegramCommands

        proposal = self._target(command)
        pointer = self._pointer()
        if (pointer.mail_id, pointer.proposal_id, pointer.version) != (
                proposal.source_mail_id, proposal.id, proposal.version):
            raise StaleCommand("Für diesen Vorschlag läuft keine Bearbeitung")
        controller = self.controller
        TelegramCommands(controller.store, controller.repository, controller.presenter,
                         controller.telegram, controller.chat_id, controller.relevance,
                         controller.outbox).cancel()
        return ReviewResult(status=ResultStatus.DONE, message=_DONE_MESSAGES[command.kind])


def _error_status(exc: Exception) -> ResultStatus:
    if isinstance(exc, StaleCommand):
        return ResultStatus.STALE
    if isinstance(exc, AnswerRequired):
        return ResultStatus.NEEDS_ANSWER
    if isinstance(exc, ReviewBusy):
        return ResultStatus.BUSY
    return ResultStatus.INVALID


def _error_message(exc: Exception) -> str:
    if isinstance(exc, ReviewError):
        return str(exc)
    return "Die Eingabe ist ungültig."


__all__ = ["ReviewService"]
