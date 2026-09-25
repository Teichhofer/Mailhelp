"""Confirmed external-write execution and restart recovery."""

from __future__ import annotations

from typing import Protocol


from ..integrations import ExternalWriter, execute_confirmed, proposal_is_writable
from ..models import Proposal, ProposalKind, ProposalStatus
from ..storage import JsonStore

from .client import TelegramTransport
from .ledger import ActionLedgerPort


class ProposalPersistence(Protocol):
    def persist(self, proposal: Proposal) -> None: ...
    def send_proposal(self, proposal: Proposal) -> None: ...


class WriteExecution(Protocol):
    def execute(self, proposal: Proposal) -> None: ...
    def resume(self) -> None: ...


class ConfirmedWriteExecutor:
    """Execute and recover writes using only explicit infrastructure ports."""

    def __init__(
        self,
        store: JsonStore,
        writers: dict[str, ExternalWriter],
        persistence: ProposalPersistence,
        telegram: TelegramTransport,
        chat_id: int,
        test_mode: bool,
        ledger: ActionLedgerPort,
    ):
        self.store, self.writers, self.persistence = store, writers, persistence
        self.telegram, self.chat_id, self.test_mode, self.ledger = (
            telegram,
            chat_id,
            test_mode,
            ledger,
        )

    def writer_for(self, proposal: Proposal) -> ExternalWriter | None:
        return self.writers.get(
            "todoist" if proposal.kind == ProposalKind.TASK else "google_calendar"
        )

    def execute(self, proposal: Proposal) -> None:
        if not proposal_is_writable(proposal):
            return
        if proposal.status == ProposalStatus.SIMULATED and proposal.simulation_notified:
            return
        writer = self.writer_for(proposal)
        if writer is None:
            return
        changed, result = execute_confirmed(
            proposal, writer, self.persistence.persist, self.test_mode
        )
        if result.get("simulation"):
            kind = "Aufgabe" if proposal.kind == ProposalKind.TASK else "Kalendertermin"
            text = (
                f"Testmodus: {kind} „{proposal.title}“ wurde bestätigt, "
                "aber extern nicht angelegt (nur simuliert)."
            )
        elif result.get("operation") == "duplicate_updated":
            text = (
                f"Bereits vorhandener gleicher Termin „{proposal.title}“ wurde erkannt; "
                "fehlende Informationen wurden ergänzt. Kein neuer Termin wurde angelegt."
            )
        elif result.get("operation") == "duplicate_skipped":
            text = (
                f"Bereits vorhandener gleicher Termin „{proposal.title}“ wurde erkannt. "
                "Kein neuer Termin wurde angelegt."
            )
        elif changed.status == ProposalStatus.CREATED:
            details = f" (ID: {changed.external_id})" if changed.external_id else ""
            link = f" {changed.external_link}" if changed.external_link else ""
            kind = "Aufgabe" if proposal.kind == ProposalKind.TASK else "Kalendertermin"
            text = (
                f"Erstellt: {kind} extern angelegt „{proposal.title}“{details}.{link}"
            )
        elif changed.status == ProposalStatus.UNCERTAIN:
            if changed.uncertain_notified:
                return
            text = f"Unklarer Schreiberfolg bei „{proposal.title}“; wird weiter abgeglichen und nicht automatisch wiederholt."
        else:
            text = f"Erstellen von „{proposal.title}“ fehlgeschlagen."
        self.telegram.send(self.chat_id, text)
        if changed.status == ProposalStatus.UNCERTAIN:
            self.persistence.persist(
                changed.model_copy(update={"uncertain_notified": True})
            )
        elif changed.status == ProposalStatus.SIMULATED:
            self.persistence.persist(
                changed.model_copy(update={"simulation_notified": True})
            )

    def resume(self) -> None:
        names = getattr(self.store, "names", None)
        if names is None:
            return
        for name in names("proposal-"):
            if "-v" in name:
                continue
            proposal = self.store.load_model(name, Proposal)
            assert isinstance(proposal, Proposal)
            # Also repairs a crash after the authoritative proposal file was
            # replaced but before its embedding MailState was replaced.
            self.persistence.persist(proposal)
            if proposal.status in {
                ProposalStatus.CONFIRMED,
                ProposalStatus.WRITING,
                ProposalStatus.UNCERTAIN,
                ProposalStatus.SIMULATED,
            }:
                self.execute(proposal)
