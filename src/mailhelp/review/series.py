"""Durable, version-bound series operations on the serialized review thread."""
from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..config import EventDefaultsSettings
from ..domain.proposal import invalidate_creation_permissions
from ..models import Proposal, ProposalStatus
from ..proposals.event_defaults import reapply_defaults
from ..proposals.proposal_reconciliation import ProposalReconciliationService
from ..temporal_answers import deterministic_temporal_revision
from .commands import CommandKind, ReviewCommand, SeriesMember
from .errors import AnswerRequired, StaleCommand
from .results import ResultStatus, ReviewResult

if TYPE_CHECKING:
    from .service import ReviewService

OPEN = {ProposalStatus.PENDING_CONFIRMATION, ProposalStatus.NEEDS_CLARIFICATION}
SERIES_KINDS = {CommandKind.SERIES_ANSWER, CommandKind.SERIES_CONFIRM}


class SeriesReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    command: ReviewCommand
    originals: list[Proposal]
    revisions: list[Proposal] = Field(default_factory=list)
    completed: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    outcomes: dict[str, str] = Field(default_factory=dict)


def members(items: list[Proposal]) -> tuple[SeriesMember, ...]:
    return tuple(SeriesMember(proposal_id=item.id, version=item.version) for item in items)


class SeriesService:
    def __init__(self, review: ReviewService):
        self.review = review
        self.controller = review.controller
        self.store = self.controller.store

    def execute(self, command: ReviewCommand) -> ReviewResult:
        name = "series-receipt-" + hashlib.sha256(command.idempotency_key.encode()).hexdigest()
        with self.store.locked():
            receipt: SeriesReceipt | None = self.store.load_model(name, SeriesReceipt)
            fresh = receipt is None
            if receipt is None:
                receipt = self._prepare(command)
            elif receipt.command != command:
                raise ValueError("Serienschlüssel bereits für eine andere Entscheidung verwendet")
        if fresh:
            self._preflight(receipt)
            with self.store.locked():
                if any(self.controller.repository.load_current(item.source_mail_id, item.id) != item
                       for item in receipt.originals):
                    raise StaleCommand("Serie während der Vorprüfung geändert; Liste erneut prüfen")
                self.store.save(name, receipt.model_dump(mode="json"))
        for index, original in enumerate(receipt.originals):
            if original.id in receipt.completed:
                continue
            if not self.review._authorized(command):
                return ReviewResult(status=ResultStatus.UNAUTHORIZED,
                                    message="Sitzung abgelaufen; verbleibende Serientermine bleiben unverändert.")
            if command.kind == CommandKind.SERIES_ANSWER:
                self._revise(receipt, original, receipt.revisions[index])
            else:
                self._confirm(receipt, original)
            receipt.completed.append(original.id)
            self.store.save(name, receipt.model_dump(mode="json"))
        skipped = ", ".join(receipt.skipped)
        detail = f" Ausgelassen (geändert oder abgeschlossen): {skipped}." if skipped else ""
        action = "gespeichert; separat bestätigen" if command.kind == CommandKind.SERIES_ANSWER else "bearbeitet"
        problems = sum(value != ResultStatus.WRITTEN.value for value in receipt.outcomes.values())
        suffix = f" {problems} Ergebnis(se) separat prüfen; keine blinde Wiederholung." if problems else ""
        count = len(set(receipt.completed) - set(receipt.skipped))
        return ReviewResult(status=ResultStatus.DONE,
                            message=(f"{count} Serientermine {action}.{detail}{suffix}")[:500])

    def _preflight(self, receipt: SeriesReceipt) -> None:
        if receipt.command.kind != CommandKind.SERIES_CONFIRM:
            return
        service = self.controller.decision_service
        reconciliation = ProposalReconciliationService(self.store)
        fields = ("status", "duplicate_check_failed", "target_event_id", "time_changes", "is_cancellation")
        for item in receipt.originals:
            if not service.profile_available(item):
                raise AnswerRequired("Zielprofil nicht verfügbar; gesamte Serie bleibt unverändert")
            if reconciliation.confirmation_candidates(item):
                raise StaleCommand("Zuordnung geändert; gesamte Serie erneut prüfen")
            if service.ledger.prior_actions(item):
                raise AnswerRequired("Frühere Anlage gefunden; betroffenen Termin separat prüfen")
            if service.precheck is not None:
                checked = service.precheck.check_proposal(item)
                if any(getattr(checked, field) != getattr(item, field) for field in fields):
                    raise StaleCommand("Dublettenprüfung geändert; gesamte Serie erneut prüfen")

    def _prepare(self, command: ReviewCommand) -> SeriesReceipt:
        originals, skipped = [], []
        key = None
        for member in command.members:
            current = self.controller.repository.load_current(command.mail_id, member.proposal_id)
            valid = current is not None and current.version == member.version and current.status in OPEN
            if not valid:
                if command.kind == CommandKind.SERIES_CONFIRM:
                    raise StaleCommand("Serie geändert; gesamte angezeigte Liste neu prüfen und bestätigen")
                skipped.append(member.proposal_id)
                continue
            assert current is not None
            if current.kind != "event" or current.series_key is None or key is not None and current.series_key != key:
                raise ValueError("Die angezeigten Termine gehören nicht zu derselben Serie")
            key = current.series_key
            if command.kind == CommandKind.SERIES_CONFIRM and (
                    current.status != ProposalStatus.PENDING_CONFIRMATION or current.open_questions
                    or not current.is_creatable):
                raise AnswerRequired("Zuerst alle offenen Fragen der ausgewählten Termine klären")
            originals.append(current)
        receipt = SeriesReceipt(command=command, originals=originals, skipped=skipped)
        if command.kind == CommandKind.SERIES_ANSWER:
            receipt.revisions = [self._revision(item, command.text or "", command.endpoint) for item in originals]
        return receipt

    def _revision(self, original: Proposal, answer: str, endpoint: str) -> Proposal:
        question = "Wann endet der Termin?" if endpoint == "end" else "Wann beginnt der Termin?"
        candidate = deterministic_temporal_revision(original, question, answer, self.controller.configured_timezone)
        if candidate is None:
            raise AnswerRequired("Bitte eine eindeutige Uhrzeit oder ein Zeitintervall angeben")
        from ..proposals.revision_protection import protect_revision
        candidate = protect_revision(original, candidate)
        state = self.controller.repository.load_mail(original.source_mail_id)
        policy = state.proposal_policy if state is not None else None
        if self.review.configuration is not None:
            from ..mailbox.mailbox_settings import event_defaults_for
            handler = self.controller.relevance_handler
            defaults = event_defaults_for(self.review.configuration.active, self.store, original,
                                          getattr(handler, "mailbox_numbers", {}))
        else:
            defaults = EventDefaultsSettings.model_validate((policy or {}).get("event_defaults", {}))
        candidate = reapply_defaults(candidate, defaults)
        candidate = candidate.model_copy(update={"version": original.version + 1})
        candidate = invalidate_creation_permissions(candidate)
        return Proposal.model_validate(candidate.model_dump())

    def _revise(self, receipt: SeriesReceipt, original: Proposal, candidate: Proposal) -> None:
        with self.store.locked():
            current = self.controller.repository.load_current(original.source_mail_id, original.id)
            if current == candidate:
                return  # Interrupted after the durable revision but before its receipt.
            if current != original:
                receipt.skipped.append(original.id)
                return
            self.controller.persist(candidate)

    def _confirm(self, receipt: SeriesReceipt, original: Proposal) -> None:
        command = receipt.command
        child_key = f"{command.idempotency_key}:{original.id}:{original.version}"
        child = command.model_copy(update={"kind": CommandKind.CONFIRM, "proposal_id": original.id,
            "version": original.version, "members": (),
            "idempotency_key": hashlib.sha256(child_key.encode()).hexdigest()})
        current = self.controller.repository.load_current(original.source_mail_id, original.id)
        if current == original:
            result = self.review._decide(child)
            self.review._record(child)
        elif current is not None and current.version == original.version and current.status in {
                ProposalStatus.CONFIRMED, ProposalStatus.WRITING, ProposalStatus.UNCERTAIN}:
            # The existing writer reconciles ambiguous results before another create.
            status, message = self.controller.decision_service._write(current)
            result = ReviewResult(status=status, message=message)
        elif current is not None and current.version == original.version and current.status in {
                ProposalStatus.CREATED, ProposalStatus.SIMULATED}:
            result = ReviewResult(status=ResultStatus.WRITTEN, message="Bereits abgeschlossen.")
        else:
            raise StaleCommand("Serie während der Anlage geändert; verbleibende Termine neu prüfen und bestätigen.")
        receipt.outcomes[original.id] = result.status.value
