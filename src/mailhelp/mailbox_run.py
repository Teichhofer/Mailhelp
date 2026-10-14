"""Mailbox run service: discovery, durable queue, checkpoints and recovery.

The service owns mailbox progress and the fatal processing latch. Mail analysis
is supplied as a callback so Telegram/Web lifecycle stays in Application.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Event
from typing import Literal
from uuid import uuid4

from . import state_names
from .config import MailboxSettings, Settings
from .imap import FetchedMail, ImapReader, UIDValidityChanged
from .logging import EventLogger
from .models import ImapCheckpoint, MailRunCounters, MailRunEntry, MailRunEntryStatus, MailRunState, MailState
from .orchestrator import Orchestrator, ProcessingOutcome, ProcessingResult
from .storage import JsonStore, mail_state_names

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


@dataclass
class MailboxRunService:
    settings: Settings
    store: JsonStore
    logger: EventLogger
    imap: ImapReader
    orchestrator: Orchestrator
    stop_event: Event
    process_mail: Callable[[FetchedMail], ProcessingResult]
    _mail_processing_halted: bool = False

    @property
    def mailbox(self) -> MailboxSettings:
        """The mailbox of ``imap``; 3.1 phase 1 processes exactly one enabled mailbox."""
        return self.settings.imap.enabled_mailboxes()[0]

    def poll(self, max_mails: int | None = None, *,
                   ignore_historical_start: bool = False) -> list[ProcessingResult]:
        """Resume durable work and process new mail, returning every outcome."""
        budget = _MailBudget(max_mails)
        results = self.resume_pending(budget)
        # A failed mail can indicate a shared provider or credential problem.  Do
        # not fan that same failure out over the rest of the mailbox.  The
        # in-memory latch is intentionally cleared only by a process restart,
        # after an operator had a chance to correct the external configuration.
        if self._mail_processing_halted:
            return results
        # Production readers expose metadata-only discovery.  Always build the
        # durable queue before fetching bodies; the fallback keeps deliberately
        # tiny legacy test adapters usable without weakening the real path.
        if hasattr(self.imap, "discover_since"):
            results.extend(self.poll_global(
                budget, ignore_historical_start=ignore_historical_start
            ))
            return results
        for folder in self.mailbox.folders:
            if self.stop_event.is_set() or budget.remaining == 0:
                break
            self._poll_folder_directly(folder, budget, ignore_historical_start, results)
        return results

    def _poll_folder_directly(self, folder: str, budget: _MailBudget, ignore_historical_start: bool,
                              results: list[ProcessingResult]) -> None:
        """Fetch and process one folder without a durable queue (readers without discovery)."""
        checkpoint_name = _checkpoint_name(self.imap.account_id, folder)
        try:
            checkpoint, ranges = self._start_checkpoint(folder, checkpoint_name, ignore_historical_start)
            try:
                mails = self.imap.fetch_since(
                    folder, checkpoint["start_uid"], checkpoint.get("uidvalidity"),
                    budget.remaining, tuple(ranges),
                )
            except UIDValidityChanged as changed:
                checkpoint, start_uid = self._restart_generation(
                    folder, checkpoint_name, changed, ignore_historical_start)
                ranges = []
                mails = self.imap.fetch_since(
                    folder, start_uid, changed.current, budget.remaining, ()
                )
        except Exception as exc:
            self._folder_failed(folder, exc)
            return
        for mail in mails:
            if self.stop_event.is_set() or budget.remaining == 0:
                break
            if budget.remaining is not None:
                budget.take()
            try:
                result = self.process_mail(mail)
            except Exception as exc:
                self.logger.event("ERROR", "orchestrator", "mail_failed", folder=folder, uid=mail.uid, error=str(exc))
                continue
            results.append(result)
            if result.outcome is ProcessingOutcome.FAILED:
                self.logger.event("ERROR", "orchestrator", "mail_failed",
                                  folder=folder, uid=mail.uid,
                                  error=result.state.get("error"))
                # This mail has a durable failure state.  Isolate its
                # terminal attempt from the batch and leave its UID out of
                # the checkpoint, but do not strand later messages.
                continue
            if result.state.get("awaiting_relevance"):
                # Only this mail is deferred; its UID is not complete yet.
                continue
            # Every result reaching this point has a durable mail state.
            # Failed results are excluded above so their checkpoint remains
            # available for restart recovery.
            ranges = self._complete_uid(checkpoint_name, checkpoint, ranges, mail.uid, mail.uidvalidity)
        if not mails:
            self._remember_generation(checkpoint_name, checkpoint)

    def _start_checkpoint(self, folder: str, checkpoint_name: str,
                          ignore_historical_start: bool) -> tuple[dict, list[tuple[int, int]]]:
        """Load the folder checkpoint, fixing its start boundary on first use."""
        checkpoint_model = self.store.load_model(checkpoint_name, ImapCheckpoint, ImapCheckpoint())
        checkpoint = checkpoint_model.model_dump(exclude={"schema_version"})
        if checkpoint["start_uid"] is None:
            if (self.mailbox.historical_start is not None
                    and not ignore_historical_start):
                start_uid = self.imap.determine_start_uid(folder, self.mailbox.historical_start)
                initial_uidvalidity = self.imap.last_uidvalidity
            else:
                start_uid = checkpoint["uid"]
                initial_uidvalidity = checkpoint["uidvalidity"]
            checkpoint_model = ImapCheckpoint(uidvalidity=initial_uidvalidity, uid=start_uid, start_uid=start_uid)
            self.store.save(checkpoint_name, checkpoint_model.model_dump())
            checkpoint = checkpoint_model.model_dump(exclude={"schema_version"})
        ranges = checkpoint["completed_uid_ranges"]
        # Checkpoints written before range tracking used one ascending
        # high-water mark.  Import that already completed prefix once.
        if not ranges and checkpoint["uid"] > checkpoint["start_uid"]:
            ranges = [(checkpoint["start_uid"] + 1, checkpoint["uid"])]
        if ignore_historical_start and checkpoint["start_uid"] != 0:
            checkpoint["start_uid"] = 0
            self.store.save(
                checkpoint_name, ImapCheckpoint(**checkpoint).model_dump()
            )
        return checkpoint, ranges

    def _restart_generation(self, folder: str, checkpoint_name: str, changed: UIDValidityChanged,
                            ignore_historical_start: bool) -> tuple[dict, int]:
        """A new UIDVALIDITY: persist the new generation and its boundary first."""
        self.logger.event(
            "WARNING", "imap", "uidvalidity_changed",
            account_id=self.imap.account_id, folder=folder,
            previous_uidvalidity=changed.previous,
            uidvalidity=changed.current,
        )
        if (self.mailbox.historical_start is not None
                and not ignore_historical_start):
            start_uid = self.imap.determine_start_uid(
                folder, self.mailbox.historical_start
            )
            # Guard against a second generation change while the
            # absolute boundary was being resolved.
            if self.imap.last_uidvalidity != changed.current:
                raise RuntimeError(
                    f"IMAP-UIDVALIDITY änderte sich während der Grenzermittlung: {folder}"
                )
        else:
            start_uid = 0
        checkpoint = ImapCheckpoint(
            uidvalidity=changed.current, uid=start_uid, start_uid=start_uid
        ).model_dump(exclude={"schema_version"})
        # Persist generation and its matching boundary atomically
        # before message content from that generation is requested.
        self.store.save(
            checkpoint_name, ImapCheckpoint(**checkpoint).model_dump()
        )
        return checkpoint, start_uid

    def _folder_failed(self, folder: str, exc: Exception) -> None:
        primary = self.mailbox.primary_folder
        event = "poll_failed" if folder == primary else "optional_folder_failed"
        self.logger.event("ERROR", "imap", event, folder=folder, error=str(exc))

    def _complete_uid(self, checkpoint_name: str, checkpoint: dict, ranges: list[tuple[int, int]],
                      uid: int, uidvalidity: int) -> list[tuple[int, int]]:
        """Record one finished UID in the folder checkpoint."""
        ranges = _add_uid(ranges, uid)
        checkpoint["uid"] = max(checkpoint["uid"], uid)
        checkpoint["uidvalidity"] = uidvalidity
        checkpoint["completed_uid_ranges"] = ranges
        self.store.save(checkpoint_name, ImapCheckpoint(**checkpoint).model_dump())
        return ranges

    def _remember_generation(self, checkpoint_name: str, checkpoint: dict) -> None:
        """An empty folder still records the UIDVALIDITY the server reported."""
        if self.imap.last_uidvalidity is not None:
            if checkpoint["uidvalidity"] is None:
                checkpoint["uidvalidity"] = self.imap.last_uidvalidity
            self.store.save(checkpoint_name, ImapCheckpoint(**checkpoint).model_dump())

    def poll_global(self, budget: _MailBudget, *,
                          ignore_historical_start: bool = False) -> list[ProcessingResult]:
        """Process one mailbox-wide batch ordered by IMAP receive time."""
        waiting = self._waiting_identities()
        run_name = state_names.mail_run(self.imap.account_id)
        active = self.store.load_model(run_name, MailRunState)
        active = active if active is not None and any(
            entry.key not in waiting and entry.status in {MailRunEntryStatus.DISCOVERED, MailRunEntryStatus.QUEUED,
                             MailRunEntryStatus.PROCESSING}
            for entry in active.entries
        ) else None
        contexts: dict[str, tuple[str, dict[str, object], list[tuple[int, int]]]] = {}
        candidates: list = []
        for folder in self.mailbox.folders:
            if self.stop_event.is_set() or budget.remaining == 0:
                break
            self._discover_folder(folder, active is not None, ignore_historical_start, contexts, candidates)
        run = active if active is not None else self._new_run(run_name, candidates, waiting, budget)
        results: list[ProcessingResult] = []
        for queued in run.entries:
            if self.stop_event.is_set() or budget.remaining == 0:
                break
            if not self._process_queued(run_name, queued, waiting, budget, contexts, results):
                break
        return results

    def _waiting_identities(self) -> set[str]:
        """Waiting relevance is durable mail work, not a runnable queue position.

        It is excluded from discovery and budgets until an authorized answer arrives.
        """
        waiting = set()
        for name in mail_state_names(self.store):
            state = self.store.load_model(name, MailState)
            assert state is not None  # the name was just listed by the store
            if state.awaiting_relevance:
                identity = state.imap
                waiting.add(f"{identity.account_id}\0{identity.folder}\0{identity.uidvalidity}\0{identity.uid}")
        return waiting

    def _discover_folder(self, folder: str, resuming: bool, ignore_historical_start: bool,
                         contexts: dict, candidates: list) -> None:
        """Prepare the folder checkpoint and, for a new batch, list its new mail."""
        checkpoint_name = _checkpoint_name(self.imap.account_id, folder)
        try:
            checkpoint, ranges = self._start_checkpoint(folder, checkpoint_name, ignore_historical_start)
            if resuming:
                contexts[folder] = (checkpoint_name, checkpoint, ranges)
                return
            try:
                discovered = self.imap.discover_since(
                    folder, checkpoint["start_uid"], checkpoint.get("uidvalidity"),
                    tuple(ranges),
                )
            except UIDValidityChanged as changed:
                checkpoint, start_uid = self._restart_generation(
                    folder, checkpoint_name, changed, ignore_historical_start)
                ranges = []
                discovered = self.imap.discover_since(
                    folder, start_uid, changed.current, ()
                )
        except Exception as exc:
            self._folder_failed(folder, exc)
            return
        contexts[folder] = (checkpoint_name, checkpoint, ranges)
        candidates.extend(discovered)
        if not discovered:
            self._remember_generation(checkpoint_name, checkpoint)

    def _new_run(self, run_name: str, candidates: list, waiting: set[str], budget: _MailBudget) -> MailRunState:
        """The newest candidates as a durable, deduplicated queue."""
        candidates.sort(key=lambda item: item.received_at, reverse=True)
        limit = budget.remaining if budget.remaining is not None else self.settings.imap.batch_size
        unique: dict[str, MailRunEntry] = {}
        for candidate in candidates:
            entry = MailRunEntry(
                account_id=candidate.account_id, folder=candidate.folder,
                uidvalidity=candidate.uidvalidity, uid=candidate.uid,
                status=MailRunEntryStatus.QUEUED,
            )
            if entry.key in waiting:
                continue
            unique.setdefault(entry.key, entry)
            if len(unique) == limit:
                break
        entries = list(unique.values())
        run = MailRunState(
            run_id=uuid4(), max_mails=budget.remaining,
            created_at=datetime.now(UTC), entries=entries,
            counters=self.run_counters(entries),
        )
        # The complete, deduplicated identity list is durable before the
        # first BODY.PEEK or analyzer call is allowed to happen.
        self.store.save(run_name, run.model_dump(mode="json"))
        return run

    def _process_queued(self, run_name: str, queued: MailRunEntry, waiting: set[str], budget: _MailBudget,
                        contexts: dict, results: list[ProcessingResult]) -> bool:
        """Process one queue entry; ``False`` halts the batch."""
        # Reload before every transition: repeated invocations must observe
        # another worker/restart having completed this identity already.
        persisted = self.store.load_model(run_name, MailRunState)
        assert persisted is not None
        current = next(entry for entry in persisted.entries if entry.key == queued.key)
        if current.key in waiting or current.status not in {MailRunEntryStatus.DISCOVERED,
                                  MailRunEntryStatus.QUEUED,
                                  MailRunEntryStatus.PROCESSING}:
            return True
        current.status = MailRunEntryStatus.PROCESSING
        current.analysis_terminal = None
        current.user_action_open = False
        current.failure_code = None
        persisted.counters = self.run_counters(persisted.entries)
        self.store.save(run_name, persisted.model_dump(mode="json"))
        if budget.remaining is not None:
            budget.take()
        try:
            mail = self.imap.fetch_uid(
                current.folder, current.uid, current.uidvalidity
            )
            result = self.process_mail(mail)
        except TimeoutError:
            # A connection-level timeout is not a result for this mail.  Keep
            # the durable ``processing`` entry intact so a newly constructed
            # reader can resume the exact materialised queue after reconnect.
            raise
        except Exception as exc:
            self.logger.event(
                "ERROR", "orchestrator", "mail_failed",
                folder=current.folder, uid=current.uid, error=str(exc),
            )
            # Keep the entry at ``processing``.  Retrying this exact queue
            # position after a restart is safer than skipping it and
            # potentially repeating one shared outage for every later mail.
            self._mail_processing_halted = True
            return False
        results.append(result)
        if result.state.get("awaiting_relevance"):
            # Keep the durable processing entry incomplete while moving
            # on to independent mail behind the held relevance question.
            return True
        self._finish_entry(run_name, queued, current, result)
        if result.outcome is ProcessingOutcome.FAILED:
            # A failed result is terminal for this run but deliberately not
            # checkpointed, so its durable MailState remains eligible for a
            # later retry.  Continue with the next independent queue item.
            return True
        checkpoint_name, checkpoint, ranges = contexts[current.folder]
        ranges = self._complete_uid(checkpoint_name, checkpoint, ranges, current.uid, current.uidvalidity)
        contexts[current.folder] = (checkpoint_name, checkpoint, ranges)
        return True

    def _finish_entry(self, run_name: str, queued: MailRunEntry, current: MailRunEntry,
                      result: ProcessingResult) -> None:
        """Persist the terminal queue status of one processed mail."""
        terminal_analysis: Literal["completed", "irrelevant", "duplicate", "failed", "skipped"]
        failure_code: Literal["imap_read_exhausted", "processing_failed"] | None
        if result.outcome is ProcessingOutcome.FAILED:
            # The mail state already contains the safe failure details.
            # Record the failed attempt in the durable run before
            # stopping.  Otherwise the summary misleadingly reports
            # zero analyzed/failed mails although the orchestrator
            # returned a terminal failure.  The missing checkpoint still
            # makes the mail eligible for recovery after a restart.
            self.logger.event(
                "ERROR", "orchestrator", "mail_failed",
                folder=current.folder, uid=current.uid,
                error=result.state.get("error"),
            )
            terminal_status = MailRunEntryStatus.FAILED
            terminal_analysis = "failed"
            failure_code = "processing_failed"
        else:
            terminal_status = (MailRunEntryStatus.WAITING_FOR_USER
                               if result.user_action_open
                               else MailRunEntryStatus.COMPLETED)
            if (result.state.get("duplicate") or {}).get("outcome") == "duplicate":
                terminal_analysis = "duplicate"
            elif (result.state.get("relevance") or {}).get("decision") == "irrelevant":
                terminal_analysis = "irrelevant"
            else:
                terminal_analysis = "completed"
            failure_code = None
        persisted = self.store.load_model(run_name, MailRunState)
        assert persisted is not None
        current = next(entry for entry in persisted.entries if entry.key == queued.key)
        current.status = terminal_status
        current.analysis_terminal = terminal_analysis
        current.user_action_open = terminal_status is MailRunEntryStatus.WAITING_FOR_USER
        current.failure_code = failure_code
        persisted.counters = self.run_counters(persisted.entries)
        self.store.save(run_name, persisted.model_dump(mode="json"))

    @staticmethod
    def run_counters(entries: list[MailRunEntry]) -> MailRunCounters:
        values = {status.value: 0 for status in MailRunEntryStatus}
        for entry in entries:
            values[entry.status.value] += 1
        return MailRunCounters(**values)


    def complete_resumed_entry(
        self, state: MailState, result: ProcessingResult
    ) -> None:
        """Synchronize a separately resumed mail with its durable run queue."""
        if (result.outcome is ProcessingOutcome.FAILED
                or result.state.get("awaiting_relevance")):
            return
        run_name = state_names.mail_run(self.imap.account_id)
        run = self.store.load_model(run_name, MailRunState)
        if run is None:
            return
        entry = next((candidate for candidate in run.entries if (
            candidate.account_id == state.imap.account_id
            and candidate.folder == state.imap.folder
            and candidate.uidvalidity == state.imap.uidvalidity
            and candidate.uid == state.imap.uid
        )), None)
        if entry is None or entry.analysis_terminal is not None:
            return

        entry.status = (MailRunEntryStatus.WAITING_FOR_USER
                        if result.user_action_open
                        else MailRunEntryStatus.COMPLETED)
        if (result.state.get("duplicate") or {}).get("outcome") == "duplicate":
            entry.analysis_terminal = "duplicate"
        elif (result.state.get("relevance") or {}).get("decision") == "irrelevant":
            entry.analysis_terminal = "irrelevant"
        else:
            entry.analysis_terminal = "completed"
        entry.user_action_open = entry.status is MailRunEntryStatus.WAITING_FOR_USER
        entry.failure_code = None
        run.counters = self.run_counters(run.entries)
        self.store.save(run_name, run.model_dump(mode="json"))

        checkpoint_name = _checkpoint_name(state.imap.account_id, state.imap.folder)
        checkpoint = self.store.load_model(
            checkpoint_name, ImapCheckpoint, ImapCheckpoint()
        )
        # A UID from an obsolete generation must never complete a position in
        # the current generation's checkpoint.
        if (checkpoint.uidvalidity is not None
                and checkpoint.uidvalidity != state.imap.uidvalidity):
            return
        ranges = checkpoint.completed_uid_ranges
        if (not ranges and checkpoint.start_uid is not None
                and checkpoint.uid > checkpoint.start_uid):
            ranges = [(checkpoint.start_uid + 1, checkpoint.uid)]
        checkpoint.uidvalidity = state.imap.uidvalidity
        checkpoint.uid = max(checkpoint.uid, state.imap.uid)
        checkpoint.completed_uid_ranges = _add_uid(ranges, state.imap.uid)
        self.store.save(checkpoint_name, checkpoint.model_dump())


    def resume_pending(self, budget: _MailBudget | None = None) -> list[ProcessingResult]:
        """Resume due durable mail states, independently of IMAP checkpoints."""
        results: list[ProcessingResult] = []
        budget = budget or _MailBudget(None)
        now = datetime.now(UTC)
        for name in mail_state_names(self.store):
            if self.stop_event.is_set() or budget.remaining == 0:
                break
            try:
                state = self.store.load_model(name, MailState)
                if state is None or (state.steps.completion != "pending" and
                                     state.steps.action_detection != "failed"):
                    continue
                if state.awaiting_relevance:
                    continue
                if state.imap.account_id != self.imap.account_id:
                    continue
                if not getattr(self.orchestrator, "accepts_configuration",
                               lambda fp: fp == self.orchestrator.config_fingerprint)(state.config_fingerprint):
                    if budget.blocked_remaining == 0:
                        break
                    budget.take_blocked()
                    self.logger.event(
                        "WARNING", "orchestrator", "configuration_changed",
                        mail_id=state.id,
                    )
                    results.append(ProcessingResult(
                        ProcessingOutcome.WAITING, state.model_dump(mode="json")
                    ))
                    continue
                if state.deferred_until is not None and state.deferred_until > now:
                    continue
                if budget.remaining is not None:
                    budget.take()
                mail = self.imap.fetch_uid(state.imap.folder, state.imap.uid, state.imap.uidvalidity)
                result = self.process_mail(mail)
                results.append(result)
                self.complete_resumed_entry(state, result)
                if result.outcome is ProcessingOutcome.FAILED:
                    self.logger.event("ERROR", "orchestrator", "resume_failed", state_name=name,
                                      error=result.state.get("error"))
                    continue
            except Exception as exc:
                self.logger.event("ERROR", "orchestrator", "resume_failed", state_name=name, error=str(exc))
        return results

