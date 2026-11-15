"""Mailbox run service: discovery, durable queue, checkpoints and recovery.

The service owns mailbox progress and the fatal processing latch. Mail analysis
is supplied as a callback so Telegram/Web lifecycle stays in Application.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import Event
from typing import Any

from .. import state_names
from ..config import MailboxSettings, Settings
from ..domain.mail import MailState
from ..domain.run import ImapCheckpoint, MailRunCounters, MailRunEntry, MailRunEntryStatus, MailRunState
from ..logging import EventLogger
from ..persistence.storage import JsonStore
from ..processing.orchestrator import Orchestrator, ProcessingResult
from . import run_polling, run_resume
from .imap import FetchedMail, ListedMailbox, MailCandidate, UIDValidityChanged

_BLOCKED_STATE_SCAN_LIMIT = 1000

def _add_uid(ranges: list[tuple[int, int]], uid: int) -> list[tuple[int, int]]:
    """Return normalized completed UID ranges after adding one UID."""
    result: list[tuple[int, int]] = []
    start = end = uid
    for current_start, current_end in ranges:
        if current_end + 1 < start:
            result.append((current_start, current_end))
        elif end + 1 < current_start:
            result.append((start, end))
            start, end = current_start, current_end
        else:
            start, end = min(start, current_start), max(end, current_end)
    result.append((start, end))
    return result


@dataclass
class _MailBudget:
    """Independent per-run budgets for actionable and blocked mail states."""

    remaining: int | None
    blocked_remaining: int | None = None

    def __post_init__(self) -> None:
        # A bounded run may report at most as many configuration-blocked states
        # as it can actually process.  Keeping this counter separate prevents a
        # stale backlog from starving newly arrived mail.
        if self.blocked_remaining is None:
            self.blocked_remaining = (self.remaining if self.remaining is not None
                                      else _BLOCKED_STATE_SCAN_LIMIT)

    def take(self) -> None:
        assert self.remaining is not None
        self.remaining -= 1

    def take_blocked(self) -> None:
        assert self.blocked_remaining is not None
        self.blocked_remaining -= 1


@dataclass
class _RunSummary:
    """Safe, persisted aggregate of the fixed mail batch."""

    discovered: int = 0
    queued: int = 0
    processed: int = 0
    relevant: int = 0
    irrelevant: int = 0
    waiting_for_user: int = 0
    failed: int = 0
    skipped: int = 0
    run_complete: bool = False

    @classmethod
    def from_runs(cls, runs: list[MailRunState | None]) -> _RunSummary:
        """One summary of the runs of every mailbox; without any run it is an interrupted empty run."""
        present = [cls.from_run(run) for run in runs if run is not None]
        if not present:
            return cls()
        total = cls(run_complete=all(item.run_complete for item in present))
        for item in present:
            for name in ("discovered", "queued", "processed", "relevant", "irrelevant", "waiting_for_user",
                         "failed", "skipped"):
                setattr(total, name, getattr(total, name) + getattr(item, name))
        return total

    @classmethod
    def from_run(cls, run: MailRunState | None) -> _RunSummary:
        """Build counters only from the durable snapshot, never attempt results."""
        if run is None:
            return cls()
        terminals = [entry.analysis_terminal for entry in run.entries
                     if entry.analysis_terminal is not None]
        return cls(
            discovered=len(run.entries),
            queued=run.counters.discovered + run.counters.queued,
            processed=len(terminals),
            relevant=sum(value == "completed" for value in terminals),
            irrelevant=sum(value == "irrelevant" for value in terminals),
            waiting_for_user=run.counters.waiting_for_user,
            failed=sum(value == "failed" for value in terminals),
            skipped=sum(value in {"duplicate", "skipped"} for value in terminals),
            run_complete=run.run_complete,
        )

    @property
    def empty(self) -> bool:
        """A completed run that found no mail is not worth a message."""
        return self.run_complete and self.discovered == 0

    def message(self, *, bounded: bool = False) -> str:
        """One compact line; zero counters are left out."""
        head = "✅ Lauf abgeschlossen" if self.run_complete else "⏸ Lauf unterbrochen"
        parts = [f"{self.processed} von {self.discovered} Mails geprüft"]
        for count, label in ((self.relevant, "relevant"), (self.irrelevant, "irrelevant"),
                             (self.waiting_for_user, "warten auf dich"),
                             (self.failed, "fehlgeschlagen"), (self.skipped, "übersprungen"),
                             (self.queued, "noch offen")):
            if count:
                parts.append(f"{count} {label}")
        return f"{head}: " + " · ".join(parts)


def _safe_name(folder: str) -> str:
    return folder.encode("utf-8").hex()


def _checkpoint_name(account: str, folder: str) -> str:
    return f"imap-{account}-{_safe_name(folder)}"


@dataclass(frozen=True)
class MailboxSource:
    """One configured mailbox and its reader (Planung 3.1)."""

    mailbox: MailboxSettings
    # An ImapReader, or the adapter that preserves its construction failure.
    reader: Any

    @property
    def account_id(self) -> str:
        account_id: str = self.reader.account_id
        return account_id


# The durable queue of one mailbox: its source, state name and snapshot.
_Run = tuple[MailboxSource, str, MailRunState]
# Per (account, folder): checkpoint name, checkpoint document and the UID ranges done in this run.
_Contexts = dict[tuple[str, str], tuple[str, dict[str, Any], list[tuple[int, int]]]]


@dataclass
class MailboxRunService:
    settings: Settings
    store: JsonStore
    logger: EventLogger
    sources: list[MailboxSource]
    orchestrator: Orchestrator
    stop_event: Event
    process_mail: Callable[[FetchedMail], ProcessingResult]
    _mail_processing_halted: bool = False
    _unavailable_reported: set[str] = field(default_factory=set)
    # Readers of further sources by account id (IServ, 3.3.7); unfinished letters resume through them.
    resume_readers: dict[str, Any] = field(default_factory=dict)
    # Accounts whose folder list was stored, or whose listing failure was reported, since this start.
    _folders_listed: set[str] = field(default_factory=set)
    _folder_list_failures: set[str] = field(default_factory=set)

    def _source(self, account: str) -> MailboxSource | None:
        return next((source for source in self.sources if source.account_id == account), None)

    def _folders(self) -> Iterator[tuple[MailboxSource, str]]:
        """Every configured folder, mailbox by mailbox in configuration order."""
        for source in self.sources:
            for folder in source.mailbox.folders:
                yield source, folder

    def poll(self, max_mails: int | None = None, *,
                   ignore_historical_start: bool = False) -> list[ProcessingResult]:
        return run_polling.poll(self, max_mails, ignore_historical_start=ignore_historical_start)

    def _poll_folder_directly(self, source: MailboxSource, folder: str, budget: _MailBudget,
                              ignore_historical_start: bool, results: list[ProcessingResult]) -> None:
        return run_polling._poll_folder_directly(self, source, folder, budget, ignore_historical_start, results)

    def _start_checkpoint(self, source: MailboxSource, folder: str, checkpoint_name: str,
                          ignore_historical_start: bool) -> tuple[dict[str, Any], list[tuple[int, int]]]:
        return run_polling._start_checkpoint(self, source, folder, checkpoint_name, ignore_historical_start)

    def _restart_generation(self, source: MailboxSource, folder: str, checkpoint_name: str,
                            changed: UIDValidityChanged, ignore_historical_start: bool) -> tuple[dict[str, Any], int]:
        return run_polling._restart_generation(self, source, folder, checkpoint_name, changed, ignore_historical_start)

    def record_folder_lists(self) -> None:
        """Store the folder list of every mailbox server once after each start.

        A failed listing is retried at the next poll but reported only once; it
        never delays or prevents fetching mail.
        """
        for source in self.sources:
            account = source.account_id
            if account in self._folders_listed or not hasattr(source.reader, "list_folders"):
                continue
            try:
                listed = source.reader.list_folders()
            except Exception as exc:
                if account not in self._folder_list_failures:
                    self._folder_list_failures.add(account)
                    self.logger.event("WARNING", "imap", "folder_list_failed", mailbox=source.mailbox.id,
                                      account_id=account, error=str(exc))
                continue
            self._folders_listed.add(account)
            self._save_folder_list(source, listed)

    def _save_folder_list(self, source: MailboxSource, listed: list[ListedMailbox]) -> None:
        configured = set(source.mailbox.folders)
        names = {folder.name for folder in listed}
        missing = sorted(configured - names)
        stored = self.store.load(state_names.MAILBOX_FOLDERS)
        current = {str(item.mailbox.id) for item in self.sources}
        # Entries of mailboxes that are no longer configured are dropped.
        mailboxes = {key: value for key, value in (stored.get("mailboxes") or {}).items() if key in current
                     } if isinstance(stored, dict) else {}
        mailboxes[str(source.mailbox.id)] = {
            "account_id": source.account_id, "label": source.mailbox.label,
            "listed_at": datetime.now(UTC).isoformat(),
            "folders": [{"name": folder.name, "role": folder.role, "flags": sorted(folder.flags),
                         "configured": folder.name in configured}
                        for folder in sorted(listed, key=lambda item: item.name)],
            "missing": missing,
        }
        self.store.save(state_names.MAILBOX_FOLDERS, {"schema_version": 1, "mailboxes": mailboxes})
        self.logger.event("INFO", "imap", "folders_listed", mailbox=source.mailbox.id, account_id=source.account_id,
                          count=len(listed), unconfigured_count=len(names - configured), missing=missing)

    def _folder_failed(self, source: MailboxSource, folder: str, exc: Exception) -> None:
        event = "poll_failed" if folder == source.mailbox.primary_folder else "optional_folder_failed"
        self.logger.event("ERROR", "imap", event, mailbox=source.mailbox.id, account_id=source.account_id,
                          folder=folder, error=str(exc))

    def _complete_uid(self, checkpoint_name: str, checkpoint: dict[str, Any], ranges: list[tuple[int, int]],
                      uid: int, uidvalidity: int) -> list[tuple[int, int]]:
        """Record one finished UID in the folder checkpoint."""
        # A durable queue created before boundary filtering may still contain
        # an excluded UID. Finish its entry without reopening the checkpoint.
        if uid <= (checkpoint["start_uid"] or 0):
            return ranges
        ranges = _add_uid(ranges, uid)
        checkpoint["uid"] = max(checkpoint["uid"], uid)
        checkpoint["uidvalidity"] = uidvalidity
        checkpoint["completed_uid_ranges"] = ranges
        self.store.save(checkpoint_name, ImapCheckpoint(**checkpoint).model_dump())
        return ranges

    def _remember_generation(self, source: MailboxSource, checkpoint_name: str, checkpoint: dict[str, Any]) -> None:
        """An empty folder still records the UIDVALIDITY the server reported."""
        if source.reader.last_uidvalidity is not None:
            if checkpoint["uidvalidity"] is None:
                checkpoint["uidvalidity"] = source.reader.last_uidvalidity
            self.store.save(checkpoint_name, ImapCheckpoint(**checkpoint).model_dump())

    def poll_global(self, budget: _MailBudget, *,
                          ignore_historical_start: bool = False) -> list[ProcessingResult]:
        return run_polling.poll_global(self, budget, ignore_historical_start=ignore_historical_start)

    def _unfinished_run(self, source: MailboxSource, waiting: set[str]) -> _Run | None:
        return run_resume._unfinished_run(self, source, waiting)

    def _waiting_identities(self) -> set[str]:
        return run_resume._waiting_identities(self)

    def _discover_folder(self, source: MailboxSource, folder: str, resuming: bool, ignore_historical_start: bool,
                         contexts: _Contexts, candidates: list[MailCandidate]) -> None:
        return run_polling._discover_folder(self, source, folder, resuming, ignore_historical_start, contexts, candidates)

    def _new_runs(self, candidates: list[MailCandidate], waiting: set[str], budget: _MailBudget) -> list[_Run]:
        return run_polling._new_runs(self, candidates, waiting, budget)

    def _process_queued(self, source: MailboxSource, run_name: str, queued: MailRunEntry, waiting: set[str],
                        budget: _MailBudget, contexts: _Contexts, results: list[ProcessingResult]) -> bool:
        return run_resume._process_queued(self, source, run_name, queued, waiting, budget, contexts, results)

    def _finish_entry(self, run_name: str, queued: MailRunEntry, current: MailRunEntry,
                      result: ProcessingResult) -> None:
        return run_resume._finish_entry(self, run_name, queued, current, result)

    @staticmethod
    def run_counters(entries: list[MailRunEntry]) -> MailRunCounters:
        values = {status.value: 0 for status in MailRunEntryStatus}
        for entry in entries:
            values[entry.status.value] += 1
        return MailRunCounters(**values)


    def complete_resumed_entry(
        self, state: MailState, result: ProcessingResult
    ) -> None:
        return run_resume.complete_resumed_entry(self, state, result)


    def resume_pending(self, budget: _MailBudget | None = None) -> list[ProcessingResult]:
        return run_resume.resume_pending(self, budget)

    def _report_unavailable(self, account: str) -> None:
        """Mail of a removed or disabled mailbox waits; reported once per process."""
        if account not in self._unavailable_reported:
            self._unavailable_reported.add(account)
            self.logger.event("WARNING", "imap", "mailbox_unavailable", account_id=account)
