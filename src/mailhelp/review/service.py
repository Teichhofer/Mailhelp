"""Execute review commands without knowledge of the channel they came from.

The state transitions themselves stay in the existing services
(``ProposalDecisionService``, ``ProposalRevisionProcessor`` and the relevance
dialog).  The review service checks authorization and the referenced version,
translates the command for those services and returns a typed result.  It runs
in the serialized operator thread; commits also compare the authoritative state.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from .. import state_names
from ..config.configuration import AdminCommand, ConfigurationService
from ..domain.mail import MailState
from ..domain.processing import AnswerStatus, ProposalClarificationState, TelegramDialogState
from ..domain.proposal import (
    RECONCILIATION_HINT,
    ActionLedger,
    Proposal,
    ProposalStatus,
    invalidate_creation_permissions,
    reconciliation_only,
    required_revision_questions,
)
from ..domain.verification import OPERATIONS, WriteVerification, operation_id
from ..notifications.notification_context import web_reply
from ..persistence.archive import record_event, record_recheck, record_relevance
from ..persistence.revision_origin import ORIGIN
from ..persistence.storage import JsonStore
from ..processing.mail_recheck import RecheckOutcome
from ..proposals.conflicts import ConflictChoiceError, button_text, choose, label
from ..proposals.profile_binding import retarget
from ..proposals.proposal_reconciliation import ProposalReconciliationService
from . import command_reconciliation, removal
from .commands import CommandKind, CommandSource, ReviewCommand
from .editing import edit_proposal
from .errors import AnswerRequired, ReviewBusy, ReviewError, StaleCommand
from .processing_actions import apply
from .reject_reasons import REJECT_REASONS
from .results import ResultStatus, ReviewResult
from .series import SeriesService
from .verification_texts import VERIFYING_MESSAGE

if TYPE_CHECKING:
    from ..external.contracts import TargetWriter

_OPEN = {ProposalStatus.PENDING_CONFIRMATION, ProposalStatus.NEEDS_CLARIFICATION}
_DIALOG = "telegram-dialog"
_RECHECK_REFUSED = {
    RecheckOutcome.NOT_FOUND: "Diese Mail ist nicht (mehr) vorhanden.",
    RecheckOutcome.NOT_IRRELEVANT: "Diese Mail ist nicht als irrelevant aussortiert.",
    RecheckOutcome.STALE: "Diese Mail wird bereits erneut geprüft oder wurde inzwischen geändert.",
    RecheckOutcome.ALREADY_PENDING: "Diese Mail wird noch verarbeitet.",
}

# Shown in the web; Telegram keeps its own confirmation texts.
_DONE_MESSAGES = {
    CommandKind.REJECT: "Vorschlag verworfen.",
    CommandKind.REMOVE_CREATED: "Eintrag entfernt und geprüft.",
    CommandKind.ALREADY_DONE: "Als schon erledigt erfasst (Aufgabe bleibt als relevant vermerkt)",
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
    CommandKind.ALREADY_DONE: "already_done",
    CommandKind.START_CLARIFICATION: "edit",
}


class ReviewService:
    """Authorize, check and apply one review command at a time."""

    def __init__(self, controller: Any,
                 web_authorizer: Callable[[str], bool] | None = None) -> None:
        self.controller = controller
        # Confirms that a web session is still valid when the command runs,
        # so a session revoked after submitting cannot act any more.
        self.web_authorizer = web_authorizer
        self.configuration: ConfigurationService | None = None
        self.completed: Callable[[ReviewCommand | AdminCommand, ReviewResult], None] | None = None
        # Resets a mail filed as irrelevant for a fresh analysis: (mail id, analysis round).
        self.recheck: Callable[[str, int], RecheckOutcome] | None = None

    def execute(self, command: ReviewCommand | AdminCommand, *, raise_errors: bool = False) -> ReviewResult:
        origin = ORIGIN.set(command.source.value)
        token = web_reply.set(command.source == CommandSource.WEB)
        try:
            result = self._execute_command(command, raise_errors=raise_errors)
            if self.completed is not None:
                self.completed(command, result)
            return result
        finally:
            ORIGIN.reset(origin)
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
            status = _error_status(exc)
            # Field names and error types only; values may contain mail content.
            self.controller.logger.event(
                "WARNING", "review", "command_refused", kind=command.kind.value,
                source=command.source.value, status=status.value, error_class=type(exc).__name__,
                fields=_invalid_fields(exc))
            return ReviewResult(status=status, message=_error_message(exc))

    def _record(self, command: ReviewCommand) -> None:
        if command.kind in {CommandKind.RETRY_MAIL, CommandKind.FILE_MAIL}:
            apply(self.controller.store, command)
            return
        if command.kind in {CommandKind.SERIES_ANSWER, CommandKind.SERIES_CONFIRM}:
            return
        learning = getattr(self.controller, "learning", None)
        if command.kind == CommandKind.RECHECK_MAIL:
            record_recheck(self.controller.store, command.mail_id, command.version, command.source.value,
                           command.idempotency_key)
            return
        if command.kind == CommandKind.REJECT_REASON:
            if learning is not None and command.reason is not None and command.proposal_id is not None:
                learning.reject_reason(command.mail_id, command.proposal_id, command.version, command.reason)
            return
        if command.kind == CommandKind.REMOVE_CREATED:
            if learning is not None and command.proposal_id is not None:
                learning.proposal_decision(command.mail_id, command.proposal_id, command.version, "remove",
                                           command.source.value, command.idempotency_key)
            return
        if command.proposal_id is None:
            state = self.controller.store.load_model(state_names.mail(command.mail_id), MailState)
            if state is not None:
                record_relevance(self.controller.store, state, command.source.value, command.idempotency_key)
            if learning is not None:
                learning.relevance_decision(command.mail_id, command.source.value, command.idempotency_key)
            return
        current = self.controller.repository.load_current(command.mail_id, command.proposal_id)
        if current is not None:
            record_event(self.controller.store, current, command.kind.value, command.source.value,
                         command.idempotency_key)
        if learning is not None:
            learning.proposal_decision(command.mail_id, command.proposal_id, command.version, command.kind.value,
                                       command.source.value, command.idempotency_key, command.text)

    def reconcile(self, command: ReviewCommand | AdminCommand) -> ReviewResult:
        return command_reconciliation.reconcile(self, command)

    def resume_admitted(self, command: ReviewCommand | AdminCommand) -> ReviewResult:
        return command_reconciliation.resume_admitted(self, command)

    def _took_effect(self, command: ReviewCommand) -> bool:
        return command_reconciliation._took_effect(self, command)

    def _authorized(self, command: ReviewCommand) -> bool:
        if command.source == CommandSource.TELEGRAM:
            return command.actor == (
                f"telegram:{self.controller.user_id}:{self.controller.chat_id}")
        return (command.actor.startswith("web:") and self.web_authorizer is not None
                and self.web_authorizer(command.actor))

    def _execute(self, command: ReviewCommand) -> ReviewResult:
        if command.kind in {CommandKind.SERIES_ANSWER, CommandKind.SERIES_CONFIRM}:
            return SeriesService(self).execute(command)
        ProposalReconciliationService(self.controller.store).recover()
        if command.kind == CommandKind.VERIFY_ENTRY:
            return self._verify_entry(command)
        if command.kind == CommandKind.RECHECK:
            previous = self._target(command)
            precheck = self.controller.decision_service.precheck
            if precheck is None:
                raise ValueError("Dublettenprüfung nicht verfügbar")
            result = precheck.check_proposal(previous.model_copy(update={"duplicate_check_failed": False,
                "open_questions": [q for q in previous.open_questions
                    if q != "Dublettenprüfung nicht verfügbar; vor einer Anlage erneut prüfen."]}))
            with self.controller.store.locked():
                if self._target(command) != previous:
                    raise StaleCommand("Vorschlag inzwischen geändert")
                questions = required_revision_questions(result)
                status = (result.status if result.status == ProposalStatus.ALREADY_EXISTS else
                          ProposalStatus.NEEDS_CLARIFICATION if questions else ProposalStatus.PENDING_CONFIRMATION)
                result = result.model_copy(update={"version": previous.version + 1,
                    "open_questions": list(dict.fromkeys([*result.open_questions, *questions])), "status": status})
                result = invalidate_creation_permissions(result)
                self.controller.persist(result)
            return ReviewResult(status=ResultStatus.DONE, message="Erneut geprüft; separat bestätigen.")
        if command.kind == CommandKind.RETARGET:
            previous = self._target(command)
            cfg = getattr(self.controller.relevance_handler, "mailbox_settings", None)
            if cfg is None:
                raise ValueError("Zielprofile nicht verfügbar")
            # The command validator requires both values for a retarget.
            assert command.target_profile is not None and command.proposal_hash is not None
            changed = retarget(cfg, previous, command.target_profile, command.proposal_hash)
            self._commit(previous, changed)
            self.controller.send_proposal(changed)
            return ReviewResult(status=ResultStatus.DONE, message="Ziel umgestellt; neue Version separat bestätigen.")
        if command.kind in {CommandKind.MERGE, CommandKind.SEPARATE, CommandKind.RESTORE, CommandKind.DEFAULTS}:
            return self._reconcile_proposal(command)
        if command.kind == CommandKind.EDIT:
            assert command.patch is not None  # ReviewCommand requires a patch for EDIT
            previous = self._target(command)
            targets = {previous.target}
            handler = self.controller.relevance_handler
            configured = getattr(handler, "targets", None)
            if configured is not None:
                targets.add(configured.task_target if previous.kind.value == "task" else configured.calendar_target)
            revised = edit_proposal(previous, command.patch, self.controller.configured_timezone, targets)
            self._commit(previous, revised)
            record_event(self.controller.store, revised, "edit", command.source.value, command.idempotency_key)
            if revised.version != previous.version:
                self.controller.send_proposal(revised)
            return ReviewResult(status=ResultStatus.DONE, message="Neue Version gespeichert; bitte separat bestätigen.")
        handlers = {CommandKind.RETRY_MAIL: self._processing, CommandKind.FILE_MAIL: self._processing,
                    CommandKind.RELEVANCE: self._relevance, CommandKind.RECHECK_MAIL: self._recheck,
                    CommandKind.ANSWER: self._answer, CommandKind.CANCEL_CLARIFICATION: self._cancel,
                    CommandKind.CHOOSE_EVENT: self._choose_event, CommandKind.CHOOSE_VARIANT: self._choose_variant,
                    CommandKind.REJECT_REASON: self._reject_reason,
                    CommandKind.REMOVE_CREATED: self._remove_created}
        return handlers.get(command.kind, self._decide)(command)

    def _writer_for(self, proposal: Proposal) -> TargetWriter | None:
        return removal._writer_for(self, proposal)

    def _removal_window_minutes(self) -> int:
        return removal._removal_window_minutes(self)

    def _is_within_removal_window(self, proposal: Proposal) -> bool:
        return removal._is_within_removal_window(self, proposal)

    def _remove_created(self, command: ReviewCommand) -> ReviewResult:

        return removal._remove_created(self, command)

    def _reject_reason(self, command: ReviewCommand) -> ReviewResult:
        assert command.proposal_id is not None
        assert command.reason is not None
        if command.reason not in REJECT_REASONS:
            raise ValueError(f"Unbekannter Ablehnungsgrund: {command.reason}")
        with self.controller.store.locked():
            current = self.controller.repository.load_current(command.mail_id, command.proposal_id)
            if current is None or current.version != command.version:
                raise StaleCommand("Vorschlag inzwischen geändert oder nicht gefunden")
            if current.status != ProposalStatus.REJECTED:
                raise ValueError("Grund kann nur für verworfene Vorschläge angegeben werden.")
            updated = current.model_copy(update={"reject_reason": command.reason})
            self.controller.persist(updated)
        label = REJECT_REASONS[command.reason]
        return ReviewResult(status=ResultStatus.DONE, message=f"Grund gespeichert: {label}.")

    def _choose_variant(self, command: ReviewCommand) -> ReviewResult:
        """5.9.3: one value of a field conflict becomes a new version; it is not a confirmation."""

        previous = self._target(command)
        assert command.conflict_id is not None and command.variant is not None  # required by ReviewCommand
        try:
            chosen = choose(previous, command.conflict_id, command.variant)
        except ConflictChoiceError as exc:
            raise StaleCommand(str(exc)) from exc
        # choose() succeeded, so conflict and variant exist in the previous version.
        conflict = next(item for item in previous.field_conflicts if item.id == command.conflict_id)
        variant = next(item for item in conflict.variants if item.id == command.variant)
        self._commit(previous, chosen)
        self.controller.send_proposal(chosen)
        # 5.9.4: the receipt names the field and the value (plan 2.1.5), e.g. "Endzeit 20:30 Uhr übernommen".
        value = button_text(conflict, variant, ZoneInfo(self.controller.configured_timezone))
        verb = "übernommen" if variant.origin == "source" else "behalten"
        return ReviewResult(status=ResultStatus.DONE,
                            message=f"{label(conflict)} {value} {verb}; neue Version bitte separat bestätigen.")

    def _choose_event(self, command: ReviewCommand) -> ReviewResult:
        """Bind a change or cancellation to the calendar entry the user picked (4.6, 17.4)."""
        previous = self._target(command)
        precheck = self.controller.decision_service.precheck
        if precheck is None:
            raise ValueError("Kalenderabgleich nicht verfügbar")
        assert command.candidate is not None  # ReviewCommand requires it for CHOOSE_EVENT
        # The calendar is read outside the store lock; _commit checks the version again.
        chosen = precheck.choose_calendar_event(previous, command.candidate)
        chosen = invalidate_creation_permissions(chosen.model_copy(update={"version": previous.version + 1}))
        self._commit(previous, chosen)
        self.controller.send_proposal(chosen)
        return ReviewResult(status=ResultStatus.DONE, message="Kalendertermin zugeordnet; separat bestätigen.")

    def _commit(self, previous: Proposal, changed: Proposal) -> None:
        with self.controller.store.locked():
            current = self.controller.repository.load_current(previous.source_mail_id, previous.id)
            if current != previous:
                raise StaleCommand("Vorschlag inzwischen geändert oder entschieden")
            self.controller.persist(changed)

    def _reconcile_proposal(self, command: ReviewCommand) -> ReviewResult:

        return command_reconciliation._reconcile_proposal(self, command)

    def _decide(self, command: ReviewCommand) -> ReviewResult:
        # Late: against the layer direction, named in tests/unit/test_layers70.py.
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
            decision, self.controller.user_id, self.controller.chat_id,
            write_authorizer=lambda: self._authorized(command),
            web_actor=command.actor if command.source == CommandSource.WEB else None)
        if command.source == CommandSource.TELEGRAM:
            return ReviewResult(status=status, message=text)
        # 5.2: a written but not yet verified entry is not reported as created.
        message = (text if text == VERIFYING_MESSAGE else _STATUS_MESSAGES.get(status)) or _DONE_MESSAGES[command.kind]
        return ReviewResult(status=status, message=message)

    def _relevance(self, command: ReviewCommand) -> ReviewResult:
        # Late: against the layer direction, named in tests/unit/test_layers70.py.
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

    def _processing(self, command: ReviewCommand) -> ReviewResult:
        apply(self.controller.store, command)
        return ReviewResult(status=ResultStatus.DONE, message=(
            "Erneuter Versuch beim nächsten Abruf." if command.kind == CommandKind.RETRY_MAIL else
            "Mail als nicht verarbeitet abgelegt; sie bleibt im Archiv."))

    def _recheck(self, command: ReviewCommand) -> ReviewResult:
        if self.recheck is None:
            raise ReviewError("Erneute Prüfung ist in diesem Betrieb nicht verfügbar.")
        outcome = self.recheck(command.mail_id, command.version)
        if outcome is not RecheckOutcome.QUEUED:
            raise StaleCommand(_RECHECK_REFUSED[outcome])
        return ReviewResult(status=ResultStatus.DONE,
                            message="Die Mail wird beim nächsten Abruf mit den aktuellen Themen erneut geprüft.")

    def _target(self, command: ReviewCommand) -> Proposal:
        assert command.proposal_id is not None
        proposal: Proposal | None = self.controller.repository.load_current(command.mail_id, command.proposal_id)
        if proposal is None:
            raise StaleCommand("Vorschlag wurde nicht gefunden")
        if proposal.version != command.version or proposal.status not in _OPEN:
            raise StaleCommand("Der Vorschlag wurde inzwischen geändert oder entschieden")
        return proposal

    def _verify_entry(self, command: ReviewCommand) -> ReviewResult:
        """5.2: only a written, not verified entry of exactly this version is read again."""
        assert command.proposal_id is not None
        current = self.controller.repository.load_current(command.mail_id, command.proposal_id)
        if current is None or current.version != command.version or current.status != ProposalStatus.VERIFYING:
            raise StaleCommand("Der Vorschlag wurde inzwischen geändert oder entschieden")
        checks = getattr(self.controller.write_executor, "verification", None)
        if checks is None or not checks.restart(current):
            raise StaleCommand("Für diesen Eintrag läuft bereits eine Prüfung oder sie ist abgeschlossen")
        return ReviewResult(status=ResultStatus.DONE,
                            message="Erneute Prüfung gestartet – Mailhelp liest den Eintrag nur erneut.")

    def _pointer(self) -> TelegramDialogState:
        state = self.controller.store.load_model(_DIALOG, TelegramDialogState, TelegramDialogState())
        assert isinstance(state, TelegramDialogState)
        return state

    def _answer(self, command: ReviewCommand) -> ReviewResult:
        """Point the clarification at this version, then answer like Telegram free text."""
        proposal = self._target(command)
        if reconciliation_only(proposal):
            # 5.0.3: only the Vorschlagsabgleich resolves this; no text answer or LLM call.
            raise AnswerRequired(RECONCILIATION_HINT)
        pointer = self._pointer()
        target = (proposal.source_mail_id, proposal.id, proposal.version)
        if (pointer.mail_id, pointer.proposal_id, pointer.version) != target:
            if pointer.retry_required:
                raise ReviewBusy("Eine andere Antwort wird gerade verarbeitet; bitte gleich erneut senden.")
            if proposal.status == ProposalStatus.PENDING_CONFIRMATION:
                self._commit(proposal, proposal.model_copy(
                    update={"status": ProposalStatus.NEEDS_CLARIFICATION}))
            self.controller.store.save(_DIALOG, TelegramDialogState(
                mail_id=proposal.source_mail_id, proposal_id=proposal.id,
                version=proposal.version).model_dump(mode="json"))
        assert command.text is not None
        follow_up = self.controller.revisions.answer(command.text)
        # 5.0.3: report what the interpretation did instead of always "übernommen".
        state = self.controller.store.load_model(
            state_names.clarification(proposal.source_mail_id, proposal.id, proposal.version),
            ProposalClarificationState)
        if follow_up is not None:
            return ReviewResult(status=ResultStatus.NEEDS_ANSWER,
                                message=f"Antwort nicht übernommen – Rückfrage: {follow_up}"[:500])
        if not isinstance(state, ProposalClarificationState) or state.answer_status == AnswerStatus.INVALID:
            return ReviewResult(status=ResultStatus.NEEDS_ANSWER,
                                message="Antwort nicht übernommen; der Vorschlag ist unverändert.")
        if state.answer_status == AnswerStatus.PENDING:
            return ReviewResult(status=ResultStatus.DONE,
                                message="Antwort gespeichert – die Auswertung wird automatisch wiederholt.")
        return ReviewResult(status=ResultStatus.DONE, message=_DONE_MESSAGES[command.kind])

    def _cancel(self, command: ReviewCommand) -> ReviewResult:
        # Late: against the layer direction, named in tests/unit/test_layers70.py.
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


def _invalid_fields(exc: Exception) -> list[str]:
    """Names and error types of the fields a validation error names, without values."""
    if not isinstance(exc, ValidationError):
        return []
    return [f"{'.'.join(map(str, error['loc'])) or 'model'}:{error['type']}"
            for error in exc.errors(include_input=False, include_url=False)][:10]


def _error_message(exc: Exception) -> str:
    if isinstance(exc, ReviewError):
        return str(exc)
    return "Die Eingabe ist ungültig."


def proposal_creation_time(store: JsonStore, proposal: Proposal) -> datetime | None:
    if proposal.created_at is not None:
        return proposal.created_at
    ledger = store.load_model("action-ledger", ActionLedger)
    if isinstance(ledger, ActionLedger):
        for entry in ledger.entries:
            if (entry.mail_id, entry.proposal_id, entry.proposal_version) == (
                proposal.source_mail_id, proposal.id, proposal.version
            ):
                return entry.created_at
    for operation in OPERATIONS:
        rec = store.load_model(
            state_names.write_verification(
                operation_id(proposal.source_mail_id, proposal.id, proposal.version, operation)
            ),
            WriteVerification,
        )
        if rec is not None:
            if rec.receipt is not None:
                return rec.receipt.written_at
            return rec.created_at
    return None


__all__ = ["ReviewService", "proposal_creation_time"]
