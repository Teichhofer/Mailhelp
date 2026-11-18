"""Reconciliation of interrupted review commands after a restart (7.0, R5)."""
from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from .. import state_names
from ..config import EventDefaultsSettings
from ..config.configuration import AdminCommand
from ..domain.mail import MailState
from ..domain.processing import ProposalClarificationState
from ..domain.proposal import (
    Proposal,
    ProposalStatus,
)
from ..domain.relevance import RelevanceDialogStatus
from ..i18n import de
from ..mailbox.mailbox_settings import event_defaults_for
from ..proposals.event_defaults import reapply_defaults
from ..proposals.proposal_reconciliation import ProposalReconciliationService
from . import service as service_module
from .commands import CommandKind, ReviewCommand
from .errors import StaleCommand
from .results import ResultStatus, ReviewResult

if TYPE_CHECKING:
    from .service import ReviewService


def reconcile(service: ReviewService, command: ReviewCommand | AdminCommand) -> ReviewResult:
    """Result of a command interrupted by a restart, judged from the current state.

    The command is never executed again: if its effect is visible it
    counts as done, otherwise the user is asked to trigger it again.
    """
    if (isinstance(command, ReviewCommand)
            and command.kind in {CommandKind.SERIES_ANSWER, CommandKind.SERIES_CONFIRM}):
        return service.execute(command)
    if isinstance(command, AdminCommand):
        if service.configuration is None:
            return ReviewResult(status=ResultStatus.FAILED, message=de("Konfigurationsdienst nicht verfügbar."))
        return service.configuration.reconcile(command)
    ProposalReconciliationService(service.controller.store).recover()
    if service._took_effect(command):
        service._record(command)
        return ReviewResult(status=ResultStatus.DONE,
                            message=de("Nach einem Neustart abgeglichen; der aktuelle Stand wird angezeigt."))
    return ReviewResult(status=ResultStatus.FAILED,
                        message=de("Durch einen Neustart unterbrochen – bitte prüfen und erneut auslösen."))


def resume_admitted(service: ReviewService, command: ReviewCommand | AdminCommand) -> ReviewResult:
    """Resume a committed receipt if execution had not reached its durable effect."""
    if isinstance(command, AdminCommand):
        return service.reconcile(command)
    ProposalReconciliationService(service.controller.store).recover()
    if service._took_effect(command):
        return service.reconcile(command)
    # execute rechecks the original live session and authoritative version.
    # Confirmed/writing proposals have already taken effect and reach reconcile,
    # then ConfirmedWriteExecutor reconciles ambiguous writes before any retry.
    return service.execute(command)


def _took_effect(service: ReviewService, command: ReviewCommand) -> bool:
    store = service.controller.store
    if command.kind in {CommandKind.RETRY_MAIL, CommandKind.FILE_MAIL}:
        mail = store.load_model(state_names.mail(command.mail_id), MailState)
        return mail is not None and mail.processing_operation == command.idempotency_key
    if command.kind == CommandKind.RECHECK_MAIL:
        mail = store.load_model(state_names.mail(command.mail_id), MailState)
        return isinstance(mail, MailState) and mail.analysis_round > command.version
    if command.kind == CommandKind.RELEVANCE:
        mail = store.load_model(state_names.mail(command.mail_id), MailState)
        dialog = mail.relevance_dialog if isinstance(mail, MailState) else None
        return dialog is not None and dialog.status == RelevanceDialogStatus.DECIDED
    assert command.proposal_id is not None
    current: Proposal | None = service.controller.repository.load_current(command.mail_id, command.proposal_id)
    if current is None:
        return False
    if command.kind == CommandKind.ALREADY_DONE:
        return current.version == command.version and current.resolution == "already_done"
    if command.kind == CommandKind.REJECT_REASON:
        return current.version == command.version and current.reject_reason == command.reason
    if command.kind == CommandKind.REMOVE_CREATED:
        return _removed_effect(service, command, current)
    if command.kind == CommandKind.RESTORE:
        return True
    if (command.kind == CommandKind.RECHECK and current.status == ProposalStatus.ALREADY_EXISTS
            and current.video_link is not None):
        # 7.9: a re-evaluation of a closed duplicate took effect once its version moved on.
        return current.version != command.version
    if current.version != command.version or current.status not in service_module._OPEN:
        return True
    pointer = service._pointer()
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


def _reconcile_proposal(review: ReviewService, command: ReviewCommand) -> ReviewResult:
    service = ProposalReconciliationService(review.controller.store)
    with review.controller.store.locked():
        if command.kind == CommandKind.RESTORE:
            state = review.controller.repository.load_mail(command.mail_id)
            item = next((p for p in state.proposals if p.id == command.proposal_id), None) if state else None
            if item is None or item.version != command.version or item.source_mail_id != command.mail_id:
                raise StaleCommand(de("Mailbefund inzwischen geändert"))
            digest = hashlib.sha256(json.dumps(item.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()
            if digest != command.proposal_hash or review.controller.repository.load_current(command.mail_id, item.id):
                raise StaleCommand(de("Mailbefund inzwischen geändert oder wiederhergestellt"))
            # Preserve the original action key; a projection cannot prove
            # whether a confirmed request already reached the provider.
            if item.status == ProposalStatus.CONFIRMED:
                item = item.model_copy(update={"status": ProposalStatus.UNCERTAIN})
            review.controller.repository.save_revision(item)
            return ReviewResult(status=ResultStatus.DONE, message=de("Gespeicherten Befund wiederhergestellt."))
        assert command.proposal_id is not None  # ReviewCommand requires it for proposal kinds
        source = service.required(command.mail_id, command.proposal_id)
        if source.version != command.version:
            raise StaleCommand(de("Quellversion inzwischen geändert"))
        if command.kind == CommandKind.DEFAULTS:
            if source.status not in service_module._OPEN:
                raise StaleCommand(de("Vorschlag nicht mehr offen"))
            if review.configuration is not None:
                handler = review.controller.relevance_handler
                defaults = event_defaults_for(review.configuration.active, review.controller.store, source,
                                              getattr(handler, "mailbox_numbers", {}))
            else:
                defaults = EventDefaultsSettings()
            digest = hashlib.sha256(json.dumps(defaults.model_dump(), sort_keys=True).encode()).hexdigest()
            if digest != command.proposal_hash:
                raise StaleCommand(de("Standarddauer inzwischen geändert"))
            changed = reapply_defaults(source, defaults)
            review.controller.repository.save_revision(changed)
            notifications = [changed] if changed.version != source.version else []
        else:
            assert command.target_ref is not None
            target = service.required(command.target_ref.mail_id, command.target_ref.proposal_id)
            if target.version != command.target_version:
                raise StaleCommand(de("Zielversion inzwischen geändert"))
            changed = service.manual(source, target, separate=command.kind == CommandKind.SEPARATE)
            target_current = service.required(target.source_mail_id, target.id)
            notifications = [target_current] if target_current.status in service_module._OPEN else []
            if changed.status in service_module._OPEN:
                notifications.append(changed)
    for proposal in notifications:
        review.controller.send_proposal(proposal)
    return ReviewResult(status=ResultStatus.DONE, message=de("Vorschlagsversion gespeichert; separat bestätigen."))


def _removed_effect(service: ReviewService, command: ReviewCommand, current: Proposal) -> bool:
    if current.version == command.version and current.status == ProposalStatus.REMOVED:
        return True
    writer = service._writer_for(current)
    if writer is not None:
        found = writer.reconcile_remove(current, command.idempotency_key)
        if found is not None:
            removed = current.model_copy(update={"status": ProposalStatus.REMOVED})
            service.controller.persist(removed)
            return True
    return False
