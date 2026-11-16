"""Polling of mailbox folders: checkpoints, generations and new runs (7.0, R5)."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from .. import state_names
from ..domain.run import ImapCheckpoint, MailRunEntry, MailRunEntryStatus, MailRunState
from ..processing.orchestrator import ProcessingOutcome, ProcessingResult
from . import mailbox_run as mailbox_run_module
from .imap import MailCandidate, UIDValidityChanged

if TYPE_CHECKING:
    from .mailbox_run import MailboxRunService, MailboxSource, _Contexts, _MailBudget, _Run


def poll(service: MailboxRunService, max_mails: int | None = None, *,
               ignore_historical_start: bool = False) -> list[ProcessingResult]:
    """Resume durable work and process new mail, returning every outcome."""
    service.record_folder_lists()
    budget = mailbox_run_module._MailBudget(max_mails)
    results = service.resume_pending(budget)
    # A failed mail can indicate a shared provider or credential problem.  Do
    # not fan that same failure out over the rest of the mailbox.  The
    # in-memory latch is intentionally cleared only by a process restart,
    # after an operator had a chance to correct the external configuration.
    if service._mail_processing_halted:
        return results
    # Production readers expose metadata-only discovery.  Always build the
    # durable queue before fetching bodies; the fallback keeps deliberately
    # tiny legacy test adapters usable without weakening the real path.
    if all(hasattr(source.reader, "discover_since") for source in service.sources):
        results.extend(service.poll_global(
            budget, ignore_historical_start=ignore_historical_start
        ))
        return results
    for source, folder in service._folders():
        if service.stop_event.is_set() or budget.remaining == 0:
            break
        service._poll_folder_directly(source, folder, budget, ignore_historical_start, results)
    return results


def _poll_folder_directly(service: MailboxRunService, source: MailboxSource, folder: str, budget: _MailBudget,
                          ignore_historical_start: bool, results: list[ProcessingResult]) -> None:
    """Fetch and process one folder without a durable queue (readers without discovery)."""
    checkpoint_name = mailbox_run_module._checkpoint_name(source.account_id, folder)
    try:
        checkpoint, ranges = service._start_checkpoint(source, folder, checkpoint_name, ignore_historical_start)
        try:
            mails = source.reader.fetch_since(
                folder, checkpoint["start_uid"], checkpoint.get("uidvalidity"),
                budget.remaining, tuple(ranges),
            )
        except UIDValidityChanged as changed:
            checkpoint, start_uid = service._restart_generation(
                source, folder, checkpoint_name, changed, ignore_historical_start)
            ranges = []
            mails = source.reader.fetch_since(
                folder, start_uid, changed.current, budget.remaining, ()
            )
    except Exception as exc:
        service._folder_failed(source, folder, exc)
        return
    for mail in mails:
        if service.stop_event.is_set() or budget.remaining == 0:
            break
        if budget.remaining is not None:
            budget.take()
        try:
            result = service.process_mail(mail)
        except Exception as exc:
            service.logger.event("ERROR", "orchestrator", "mail_failed", folder=folder, uid=mail.uid, error=str(exc))
            continue
        results.append(result)
        if result.outcome is ProcessingOutcome.FAILED:
            service.logger.event("ERROR", "orchestrator", "mail_failed",
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
        ranges = service._complete_uid(checkpoint_name, checkpoint, ranges, mail.uid, mail.uidvalidity)
    if not mails:
        service._remember_generation(source, checkpoint_name, checkpoint)


def _start_checkpoint(service: MailboxRunService, source: MailboxSource, folder: str, checkpoint_name: str,
                      ignore_historical_start: bool) -> tuple[dict[str, Any], list[tuple[int, int]]]:
    """Load the folder checkpoint, fixing its start boundary on first use."""
    checkpoint_model = service.store.load_model(checkpoint_name, ImapCheckpoint, ImapCheckpoint())
    checkpoint = checkpoint_model.model_dump(exclude={"schema_version"})
    if checkpoint["start_uid"] is None:
        if (source.mailbox.historical_start is not None
                and not ignore_historical_start):
            start_uid = source.reader.determine_start_uid(folder, source.mailbox.historical_start)
            initial_uidvalidity = source.reader.last_uidvalidity
        else:
            start_uid = checkpoint["uid"]
            initial_uidvalidity = checkpoint["uidvalidity"]
        checkpoint_model = ImapCheckpoint(uidvalidity=initial_uidvalidity, uid=start_uid, start_uid=start_uid)
        service.store.save(checkpoint_name, checkpoint_model.model_dump())
        checkpoint = checkpoint_model.model_dump(exclude={"schema_version"})
    ranges = checkpoint["completed_uid_ranges"]
    # Checkpoints written before range tracking used one ascending
    # high-water mark.  Import that already completed prefix once.
    if not ranges and checkpoint["uid"] > checkpoint["start_uid"]:
        ranges = [(checkpoint["start_uid"] + 1, checkpoint["uid"])]
    if ignore_historical_start and checkpoint["start_uid"] != 0:
        checkpoint["start_uid"] = 0
        service.store.save(
            checkpoint_name, ImapCheckpoint(**checkpoint).model_dump()
        )
    return checkpoint, ranges


def _restart_generation(service: MailboxRunService, source: MailboxSource, folder: str, checkpoint_name: str,
                        changed: UIDValidityChanged, ignore_historical_start: bool) -> tuple[dict[str, Any], int]:
    """A new UIDVALIDITY: persist the new generation and its boundary first."""
    service.logger.event(
        "WARNING", "imap", "uidvalidity_changed",
        account_id=source.account_id, folder=folder,
        previous_uidvalidity=changed.previous,
        uidvalidity=changed.current,
    )
    if (source.mailbox.historical_start is not None
            and not ignore_historical_start):
        start_uid = source.reader.determine_start_uid(
            folder, source.mailbox.historical_start
        )
        # Guard against a second generation change while the
        # absolute boundary was being resolved.
        if source.reader.last_uidvalidity != changed.current:
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
    service.store.save(
        checkpoint_name, ImapCheckpoint(**checkpoint).model_dump()
    )
    return checkpoint, start_uid


def poll_global(service: MailboxRunService, budget: _MailBudget, *,
                      ignore_historical_start: bool = False) -> list[ProcessingResult]:
    """Process one batch over every mailbox, selected by IMAP receive time.

    While any mailbox still has an unfinished queue, only those queues continue.
    Otherwise the newest new mail of all mailboxes forms one shared batch, which is
    stored as one durable queue per mailbox and processed mailbox by mailbox.
    """
    waiting = service._waiting_identities()
    active = [run for run in (service._unfinished_run(source, waiting) for source in service.sources)
              if run is not None]
    contexts: mailbox_run_module._Contexts = {}
    candidates: list[MailCandidate] = []
    for source, folder in service._folders():
        if service.stop_event.is_set() or budget.remaining == 0:
            break
        service._discover_folder(source, folder, bool(active), ignore_historical_start, contexts, candidates)
    runs = active or service._new_runs(candidates, waiting, budget)
    results: list[ProcessingResult] = []
    for source, run_name, run in runs:
        for queued in run.entries:
            if service.stop_event.is_set() or budget.remaining == 0:
                return results
            if not service._process_queued(source, run_name, queued, waiting, budget, contexts, results):
                return results
    return results


def _discover_folder(service: MailboxRunService, source: MailboxSource, folder: str, resuming: bool,
                     ignore_historical_start: bool, contexts: _Contexts, candidates: list[MailCandidate]) -> None:
    """Prepare the folder checkpoint and, for a new batch, list its new mail."""
    checkpoint_name = mailbox_run_module._checkpoint_name(source.account_id, folder)
    try:
        checkpoint, ranges = service._start_checkpoint(source, folder, checkpoint_name, ignore_historical_start)
        if resuming:
            contexts[source.account_id, folder] = (checkpoint_name, checkpoint, ranges)
            return
        try:
            discovered = source.reader.discover_since(
                folder, checkpoint["start_uid"], checkpoint.get("uidvalidity"),
                tuple(ranges),
            )
        except UIDValidityChanged as changed:
            checkpoint, start_uid = service._restart_generation(
                source, folder, checkpoint_name, changed, ignore_historical_start)
            ranges = []
            discovered = source.reader.discover_since(
                folder, start_uid, changed.current, ()
            )
    except Exception as exc:
        service._folder_failed(source, folder, exc)
        return
    contexts[source.account_id, folder] = (checkpoint_name, checkpoint, ranges)
    candidates.extend(discovered)
    if not discovered:
        service._remember_generation(source, checkpoint_name, checkpoint)


def _new_runs(service: MailboxRunService, candidates: list[MailCandidate], waiting: set[str],
              budget: _MailBudget) -> list[_Run]:
    """The newest candidates of all mailboxes as one durable, deduplicated queue per mailbox.

    Equal receive times keep the discovery order: mailbox, then folder configuration order.
    """
    candidates.sort(key=lambda item: item.received_at, reverse=True)
    limit = budget.remaining if budget.remaining is not None else service.settings.imap.batch_size
    unique: dict[str, MailRunEntry] = {}
    for candidate in candidates:
        if len(unique) == limit:
            break
        entry = MailRunEntry(
            account_id=candidate.account_id, folder=candidate.folder,
            uidvalidity=candidate.uidvalidity, uid=candidate.uid,
            status=MailRunEntryStatus.QUEUED,
        )
        if entry.key not in waiting:
            unique.setdefault(entry.key, entry)
    runs: list[mailbox_run_module._Run] = []
    for source in service.sources:
        entries = [entry for entry in unique.values() if entry.account_id == source.account_id]
        run = MailRunState(
            run_id=uuid4(), max_mails=budget.remaining,
            created_at=datetime.now(UTC), entries=entries,
            counters=service.run_counters(entries),
        )
        # The complete, deduplicated identity list is durable before the
        # first BODY.PEEK or analyzer call is allowed to happen.
        run_name = state_names.mail_run(source.account_id)
        service.store.save(run_name, run.model_dump(mode="json"))
        runs.append((source, run_name, run))
    return runs
