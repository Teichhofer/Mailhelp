"""Confirmed external-write execution and restart recovery."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from .. import state_names
from ..domain.proposal import UNVERIFIED_LEGACY_ACTOR, Proposal, ProposalKind, ProposalStatus
from ..domain.verification import VerificationState, WriteVerification
from ..external.confirmed import execute_confirmed
from ..external.contracts import ExternalWriter, proposal_is_writable
from ..external.roles import writer_for
from ..external.verification import EntryReader
from ..i18n import de
from ..persistence.ledger import ActionLedgerPort
from ..persistence.storage import JsonStore
from ..processing.write_verification import WriteVerifications
from ..proposals.proposal_reconciliation import ProposalReconciliationService
from ..review.commands import CommandKind, CommandSource, ReviewCommand
from ..review.inbox import CommandInboxState, CommandStatus
from ..review.verification_texts import differences_text, reason_text
from ..runtime.diagnostics import error_code
from .callbacks import Decision, DecisionAction
from .client import TelegramTransport

_WRITE_STATES = {ProposalStatus.CONFIRMED, ProposalStatus.WRITING, ProposalStatus.UNCERTAIN,
                 ProposalStatus.SIMULATED, ProposalStatus.VERIFYING}


def _status(proposal: Proposal) -> ProposalStatus:
    return proposal.status


class ProposalPersistence(Protocol):
    def persist(self, proposal: Proposal) -> None: ...
    def send_proposal(self, proposal: Proposal) -> None: ...


class WriteExecution(Protocol):
    def execute(self, proposal: Proposal) -> Proposal: ...
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
        configured_timezone: str = "UTC",
        verification: WriteVerifications | None = None,
    ) -> None:
        self.store, self.writers, self.persistence = store, writers, persistence
        self.telegram, self.chat_id, self.test_mode, self.ledger = (
            telegram,
            chat_id,
            test_mode,
            ledger,
        )
        self.configured_timezone = configured_timezone
        # 5.2: a written entry is CREATED only after a fresh read proved it.
        self.verification = verification
        self._reported_target_mismatches: set[tuple[str, str, int]] = set()
        self._reported_authorization_failures: set[tuple[str, str, int]] = set()
        self._repaired = False
        self.web_authorizer: Callable[[str], bool] = lambda actor: False
        self.telegram_authorizer: Callable[[str], bool] = lambda actor: False

    def _event_time_details(self, proposal: Proposal) -> str:
        """Render the created event's start in the user's configured timezone."""
        start = proposal.start
        if isinstance(start, datetime):
            local_start = start.astimezone(ZoneInfo(self.configured_timezone))
            return f" · {local_start:%d.%m.%Y, %H:%M} Uhr"
        return de(" · {date}, ganztägig", date=f"{start:%d.%m.%Y}")

    def writer_for(self, proposal: Proposal) -> ExternalWriter | None:
        return writer_for(self.writers, proposal)

    def execute(self, proposal: Proposal) -> Proposal:
        if not proposal_is_writable(proposal):
            return proposal
        if proposal.status == ProposalStatus.SIMULATED and proposal.simulation_notified:
            return proposal
        writer = self.writer_for(proposal)
        if writer is None:
            return proposal
        try:
            changed, result = execute_confirmed(proposal, writer, self.persistence.persist, self.test_mode,
                                               authorize=lambda: self._authorized(proposal),
                                               verification=self.verification)
        except Exception as exc:
            return self._write_failed(proposal, exc)
        self._profile_health(proposal, "")
        if result.get("verifying"):
            return self._verify(proposal, changed, writer, result)
        if result.get("target_mismatch"):
            self._report_target_mismatch(proposal)
            return changed
        text = self._result_text(proposal, changed, result)
        if text is None:
            return changed
        if result.get("authorization_invalid"):
            reference = (proposal.source_mail_id, proposal.id, proposal.version)
            if reference in self._reported_authorization_failures:
                return changed
            self._reported_authorization_failures.add(reference)
        markup = self._remove_button(changed) if changed.status == ProposalStatus.CREATED and self._can_remove(changed, result) else None
        if markup is not None:
            self.telegram.send(self.chat_id, text, markup)
        else:
            self.telegram.send(self.chat_id, text)
        if changed.status == ProposalStatus.UNCERTAIN:
            self.persistence.persist(changed.model_copy(update={"uncertain_notified": True}))
        elif changed.status == ProposalStatus.SIMULATED:
            self.persistence.persist(changed.model_copy(update={"simulation_notified": True}))
        return changed

    def _verify(self, proposal: Proposal, changed: Proposal, writer: ExternalWriter,
                result: dict[str, Any]) -> Proposal:
        """One due read of a written entry; each final outcome is reported once (5.2)."""
        if self.verification is None or not isinstance(writer, EntryReader):
            return changed  # stays VERIFYING; nothing may write it again
        changed, record = self.verification.check(changed, writer, self.persistence.persist)
        if record is None or record.state in {VerificationState.PENDING, record.notified}:
            return changed
        if record.state != VerificationState.VERIFIED:
            self.telegram.send(self.chat_id, self._unverified_text(proposal, record), self._recheck_button(changed))
        elif changed.status == ProposalStatus.CREATED:
            msg = self._verified_text(proposal, changed, record, result)
            markup = self._remove_button(changed) if self._can_remove(changed, result) else None
            if markup is not None:
                self.telegram.send(self.chat_id, msg, markup)
            else:
                self.telegram.send(self.chat_id, msg)
        self.verification.mark_notified(record)
        return changed

    def _verified_text(self, proposal: Proposal, changed: Proposal, record: WriteVerification,
                       result: dict[str, Any]) -> str:
        """The success message of the verified operation; details only while the write result is known."""
        title, operation = proposal.title, record.operation
        assert record.receipt is not None
        if operation == "cancel" and record.receipt.result == "existing":
            return de("✅ Termin „{title}“ war im Kalender bereits abgesagt oder gelöscht (geprüft); nichts geändert.",
                      title=title)
        if operation == "cancel":
            return de("✅ Termin „{title}“ im Kalender abgesagt und geprüft.", title=title)
        if operation == "update":
            changes = "; ".join(result.get("time_changes") or proposal.time_changes) or de("bestätigte Angaben "
                                                                                           "übernommen")
            return (de("✅ Bestehender Termin „{title}“ geändert und geprüft: {changes}. Titel und Beschreibung "
                       "bleiben erhalten; die Änderung ist in der Beschreibung vermerkt.",
                       title=title, changes=changes))
        if operation == "append" and result.get("time_changes"):
            return (de("✅ Bestehender Termin „{title}“ aktualisiert und geprüft: {changes}. Die Änderung ist in der "
                       "Terminbeschreibung vermerkt.",
                       title=title, changes="; ".join(result["time_changes"])))
        if operation == "append":
            return (de("Bereits vorhandener gleicher Termin „{title}“ wurde erkannt; fehlende Informationen wurden "
                       "ergänzt und geprüft. Kein neuer Termin wurde angelegt.",
                       title=title))
        if operation == "duplicate":
            return (de("Bereits vorhandener gleicher Termin „{title}“ wurde erkannt und frisch geprüft. Kein neuer "
                       "Termin wurde angelegt.",
                       title=title))
        return self._created_text(proposal, changed, verified=True)

    def _recheck_button(self, proposal: Proposal) -> dict[str, Any]:
        """A version-bound, read-only "Erneut prüfen" for the authorized chat (5.2)."""
        token = Decision(mail_id=proposal.source_mail_id, proposal_id=proposal.id, version=proposal.version,
                         action=DecisionAction.VERIFY_ENTRY).encode(self.store)
        return {"inline_keyboard": [[{"text": de("Erneut prüfen"), "callback_data": token}]]}

    def _remove_button(self, proposal: Proposal) -> dict[str, Any]:
        token = Decision(mail_id=proposal.source_mail_id, proposal_id=proposal.id, version=proposal.version,
                         action=DecisionAction.REMOVE_ASK).encode(self.store)
        return {"inline_keyboard": [[{"text": de("Wieder entfernen"), "callback_data": token}]]}

    def _can_remove(self, proposal: Proposal, result: dict[str, Any]) -> bool:
        if self.test_mode or result.get("simulation"):
            return False
        if result.get("operation") == "calendar_file":
            return False
        if proposal.external_id is None:
            return False
        writer = self.writer_for(proposal)
        return writer is None or getattr(writer, "supports_remove", True)

    def _unverified_text(self, proposal: Proposal, record: WriteVerification) -> str:
        if record.state == VerificationState.MISMATCH:
            return (de("⚠️ Eintrag vorhanden, Angaben weichen ab: „{title}“ – {differences_text}. Mailhelp ändert den "
                       "Eintrag nicht automatisch und legt keinen neuen an.",
                       title=proposal.title,
                       differences_text=differences_text(record, ZoneInfo(self.configured_timezone))))
        return (de("⚠️ Eintragung noch nicht bestätigt: „{title}“ wurde gespeichert, aber {reason_text}. Mailhelp "
                   "legt den Eintrag nicht erneut an.",
                   title=proposal.title, reason_text=reason_text(record)))

    def _authorized(self, proposal: Proposal) -> bool:
        actor = proposal.confirmed_web_actor
        if actor == UNVERIFIED_LEGACY_ACTOR:
            return False
        if actor is not None and not self.web_authorizer(actor):
            return False
        with self.store.locked():
            current = self.store.load_model(state_names.proposal(proposal.source_mail_id, proposal.id), Proposal)
            return current == proposal

    def _bind_legacy_authorization(self, proposal: Proposal) -> Proposal:
        """Old records need a durable source receipt; absence never invents a session."""
        legacy = ("confirmed_web_actor" not in proposal.model_fields_set
                  or proposal.confirmed_web_actor == UNVERIFIED_LEGACY_ACTOR)
        if proposal.status != ProposalStatus.CONFIRMED or not legacy:
            return proposal
        inbox = self.store.load_model("command-inbox", CommandInboxState, CommandInboxState())
        for entry in inbox.entries:
            command = entry.command
            if (isinstance(command, ReviewCommand)
                    and command.kind in {CommandKind.CONFIRM, CommandKind.CONFIRM_DUPLICATE}
                    and entry.status in {CommandStatus.RUNNING, CommandStatus.DONE, CommandStatus.FAILED}
                    and (command.mail_id, command.proposal_id, command.version) ==
                        (proposal.source_mail_id, proposal.id, proposal.version)):
                actor: str | None = command.actor
                if command.source == CommandSource.TELEGRAM:
                    actor = None if self.telegram_authorizer(command.actor) else UNVERIFIED_LEGACY_ACTOR
                elif not command.actor.startswith("web:"):
                    actor = UNVERIFIED_LEGACY_ACTOR
                return Proposal.model_validate(proposal.model_copy(update={"confirmed_web_actor": actor}).model_dump())
        return proposal.model_copy(update={"confirmed_web_actor": UNVERIFIED_LEGACY_ACTOR})

    def _write_failed(self, proposal: Proposal, exc: Exception) -> Proposal:
        """With target profiles a failing profile is recorded and the stored version stays; else raise."""
        if not any(":" in name for name in self.writers):
            raise exc
        self._profile_health(proposal, error_code(exc))
        current = self.store.load_model(state_names.proposal(proposal.source_mail_id, proposal.id), Proposal)
        return current if current is not None else proposal

    def _report_target_mismatch(self, proposal: Proposal) -> None:
        """Once per version: the configured target no longer matches the confirmed one."""
        reference = (proposal.source_mail_id, proposal.id, proposal.version)
        if reference in self._reported_target_mismatches:
            return
        self.telegram.send(
            self.chat_id,
            de("Ziel geändert: „{title}“ bleibt gesperrt. Das konfigurierte Ziel stimmt nicht mit dem angezeigten "
               "Vorschlagsziel überein. Ursprüngliches Ziel wiederherstellen oder einen neuen Vorschlag für das neue "
               "Ziel ausdrücklich bestätigen.",
               title=proposal.title),
        )
        self._reported_target_mismatches.add(reference)

    def _result_text(self, proposal: Proposal, changed: Proposal, result: dict[str, Any]) -> str | None:
        """The message about the write; ``None`` when an unclear result was reported before."""
        operation = result.get("operation")
        if result.get("authorization_invalid"):
            return de("Anlage blockiert: Freigabe, Vorschlagsversion oder Websitzung ist nicht mehr gültig.")
        if operation == "calendar_file":
            return (de("📎 Kalenderdatei für „{title}“{event_time_details} bereitgestellt – Übernahme in den Kalender "
                       "nicht prüfbar.",
                       title=proposal.title, event_time_details=self._event_time_details(changed)))
        if result.get("simulation"):
            kind = "Aufgabe" if proposal.kind == ProposalKind.TASK else "Kalendertermin"
            return de("🧪 Testmodus: {kind} „{title}“ bestätigt, aber nicht angelegt (nur simuliert).",
                      kind=kind, title=proposal.title)
        if operation == "event_cancelled":
            return de("✅ Termin „{title}“ im Kalender abgesagt.", title=proposal.title)
        if operation == "already_cancelled":
            return de("✅ Termin „{title}“ war im Kalender bereits abgesagt oder gelöscht; nichts geändert.",
                      title=proposal.title)
        if operation == "event_changed":
            changes = "; ".join(result.get("time_changes") or []) or de("bestätigte Angaben übernommen")
            return (de("✅ Bestehender Termin „{title}“ geändert: {changes}. Titel und Beschreibung bleiben erhalten; "
                       "die Änderung ist in der Beschreibung vermerkt.",
                       title=proposal.title, changes=changes))
        if operation == "duplicate_updated" and result.get("time_changes"):
            return (de("✅ Bestehender Termin „{title}“ aktualisiert: {changes}. Die Änderung ist in der "
                       "Terminbeschreibung vermerkt.",
                       title=proposal.title, changes="; ".join(result["time_changes"])))
        if operation == "duplicate_updated":
            return (de("Bereits vorhandener gleicher Termin „{title}“ wurde erkannt; fehlende Informationen wurden "
                       "ergänzt. Kein neuer Termin wurde angelegt.",
                       title=proposal.title))
        if operation == "duplicate_skipped":
            return (de("Bereits vorhandener gleicher Termin „{title}“ wurde erkannt. Kein neuer Termin wurde angelegt.",
                       title=proposal.title))
        if changed.status == ProposalStatus.CREATED:
            return self._created_text(proposal, changed)
        if changed.status == ProposalStatus.UNCERTAIN:
            if changed.uncertain_notified:
                return None
            return (de("Unklarer Schreiberfolg bei „{title}“; wird weiter abgeglichen und nicht automatisch "
                       "wiederholt.",
                       title=proposal.title))
        return de("Erstellen von „{title}“ fehlgeschlagen.", title=proposal.title)

    def _created_text(self, proposal: Proposal, changed: Proposal, verified: bool = False) -> str:
        where = de("als Aufgabe") if proposal.kind == ProposalKind.TASK else de("im Kalender")
        details = self._event_time_details(changed) if proposal.kind == ProposalKind.EVENT else ""
        text = de("✅ Angelegt und geprüft {where}: „{title}“{details}" if verified
                  else "✅ Angelegt {where}: „{title}“{details}", where=where, title=proposal.title, details=details)
        if changed.external_link:
            text += f"\n{changed.external_link}"
        return text

    def _profile_health(self, proposal: Proposal, code: str) -> None:
        if not any(":" in name for name in self.writers):
            return
        name = f"{'tasks' if proposal.kind == ProposalKind.TASK else 'calendar'}:{proposal.target_profile}"
        with self.store.locked():
            health = self.store.load("service-health", {"schema_version": 1, "errors": {}, "version": 0})
            if health["errors"].get(name, "") == code:
                return
            if code:
                health["errors"][name] = code
            else:
                health["errors"].pop(name, None)
            health["version"] += 1
            self.store.save("service-health", health)

    def resume(self) -> None:
        """Run on every operator pass; only the first one repairs every proposal.

        Later passes execute only proposals in a write state. Rewriting all
        proposals on every pass kept the operator busy for seconds (4.4.1).
        """
        ProposalReconciliationService(self.store).recover()
        repair = not self._repaired
        for name, signature in self.store.scan(state_names.PROPOSAL_PREFIX).items():
            if "-v" in name:
                continue
            if not repair and self.store.cached(name, Proposal, _status, signature) not in _WRITE_STATES:
                continue
            proposal = self.store.load_model(name, Proposal)
            assert isinstance(proposal, Proposal)
            proposal = self._bind_legacy_authorization(proposal)
            # Also repairs a crash after the authoritative proposal file was
            # replaced but before its embedding MailState was replaced.
            self.persistence.persist(proposal)
            if proposal.status in _WRITE_STATES:
                self.execute(proposal)
        self._repaired = True
