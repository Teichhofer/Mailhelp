"""Removal of created entries within the removal window (7.0, R5)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from ..domain.proposal import (
    Proposal,
    ProposalStatus,
)
from ..external.contracts import EntryModifiedError
from ..external.roles import writer_for
from ..i18n import de
from ..llm.adapter import UncertainWriteError
from ..persistence.archive import record_event
from . import service as service_module
from .commands import ReviewCommand
from .errors import ReviewError, StaleCommand
from .results import ResultStatus, ReviewResult

if TYPE_CHECKING:
    from ..external.contracts import TargetWriter
    from .service import ReviewService


def _remove_created(service: ReviewService, command: ReviewCommand) -> ReviewResult:

    assert command.proposal_id is not None
    with service.controller.store.locked():
        current = service.controller.repository.load_current(command.mail_id, command.proposal_id)
        if current is None or current.version != command.version:
            raise StaleCommand(de("Vorschlag inzwischen geändert oder nicht gefunden"))
        if current.status == ProposalStatus.REMOVED:
            return ReviewResult(status=ResultStatus.DONE, message=de("Bereits entfernt."))
        if current.status == ProposalStatus.SIMULATED:
            raise ReviewError(de("Simulierte Vorschläge können nicht extern entfernt werden."))
        if current.status != ProposalStatus.CREATED:
            raise ReviewError(de("Nur angelegte Einträge können wieder entfernt werden."))
        if current.external_id is None:
            raise ReviewError(de("Keine externe ID vorhanden."))
        if not service._is_within_removal_window(current):
            raise ReviewError(
                de("Die Frist zum Entfernen des Eintrags ist abgelaufen (maximal 10 Minuten nach dem Anlegen).")
            )

        writer = _removing_writer(service, current)

        try:
            prepared = writer.prepare_remove(current, command.idempotency_key)
        except EntryModifiedError:
            return ReviewResult(
                status=ResultStatus.INVALID,
                message=de("Nicht entfernt – Eintrag wurde beim Anbieter geändert."),
            )

        if not prepared.requires_write:
            removed = current.model_copy(update={"status": ProposalStatus.REMOVED})
            service.controller.persist(removed)
            record_event(service.controller.store, removed, "remove", command.source.value, command.idempotency_key)
            return ReviewResult(status=ResultStatus.DONE, message=de("Bereits entfernt."))

        # Live authorization check at the write boundary
        if not service._authorized(command):
            return ReviewResult(status=ResultStatus.UNAUTHORIZED, message=de("Nicht autorisiert."))

        try:
            prepared.operation()
        except UncertainWriteError:
            rec = writer.reconcile_remove(current, command.idempotency_key)
            if rec is not None:
                removed = current.model_copy(update={"status": ProposalStatus.REMOVED})
                service.controller.persist(removed)
                record_event(service.controller.store, removed, "remove", command.source.value, command.idempotency_key)
                return ReviewResult(status=ResultStatus.DONE, message=de("Entfernt und geprüft."))
            return ReviewResult(
                status=ResultStatus.WRITE_UNCERTAIN,
                message=de("Entfernen noch nicht bestätigt; Abgleich läuft."),
            )
        except EntryModifiedError:
            return ReviewResult(
                status=ResultStatus.INVALID,
                message=de("Nicht entfernt – Eintrag wurde beim Anbieter geändert."),
            )
        except Exception:
            return ReviewResult(status=ResultStatus.FAILED, message=de("Entfernen fehlgeschlagen."))

        removed = current.model_copy(update={"status": ProposalStatus.REMOVED})
        service.controller.persist(removed)
        record_event(service.controller.store, removed, "remove", command.source.value, command.idempotency_key)
        return ReviewResult(status=ResultStatus.DONE, message=de("Entfernt und geprüft."))


def _removal_window_minutes(service: ReviewService) -> int:
    if service.configuration is not None:
        return service.configuration.active.targets.removal_window_minutes
    handler = getattr(service.controller, "relevance_handler", None)
    targets = getattr(handler, "targets", None)
    if targets is not None:
        return getattr(targets, "removal_window_minutes", 10)
    return 10


def _is_within_removal_window(service: ReviewService, proposal: Proposal) -> bool:
    created = service_module.proposal_creation_time(service.controller.store, proposal)
    if created is None:
        return True
    now = datetime.now(UTC)
    window = timedelta(minutes=service._removal_window_minutes())
    return now <= created + window


def _removing_writer(service: ReviewService, proposal: Proposal) -> TargetWriter:
    writer = service._writer_for(proposal)
    if writer is None:
        raise ReviewError(de("Kein Schreibdienst für diesen Vorschlag konfiguriert."))
    if not getattr(writer, "supports_remove", True):
        # 7.2: also a direct command must not reach an unprotected deletion.
        raise ReviewError(de("{label}: Einträge lassen sich in Mailhelp nicht wieder entfernen; "
                          "bitte direkt beim Anbieter bearbeiten.", label=writer.label))
    return writer


def _writer_for(service: ReviewService, proposal: Proposal) -> TargetWriter | None:
    write_executor = getattr(service.controller, "write_executor", None)
    if write_executor is not None:
        writer: TargetWriter | None = write_executor.writer_for(proposal)
        return writer
    writers = getattr(service.controller, "writers", None)
    if writers:
        return writer_for(writers, proposal)
    return None
