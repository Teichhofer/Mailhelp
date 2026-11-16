"""Resumption of interrupted runs and processing of queued mails (7.0, R5)."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from .. import state_names
from ..domain.mail import MailState
from ..domain.processing import ProcessingError, ProcessingErrorCode, ProcessingStage
from ..domain.run import ImapCheckpoint, MailRunEntry, MailRunEntryStatus, MailRunState
from ..processing.orchestrator import ProcessingOutcome, ProcessingResult
from ..state_names import mail_state_names
from . import mailbox_run as mailbox_run_module

if TYPE_CHECKING:
    from .mailbox_run import MailboxRunService, MailboxSource, _Contexts, _MailBudget, _Run


def _process_queued(service: MailboxRunService, source: MailboxSource, run_name: str, queued: MailRunEntry,
                    waiting: set[str], budget: _MailBudget, contexts: _Contexts,
                    results: list[ProcessingResult]) -> bool:
    """Process one queue entry; ``False`` halts the batch."""
    # Reload before every transition: repeated invocations must observe
    # another worker/restart having completed this identity already.
    persisted = service.store.load_model(run_name, MailRunState)
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
    persisted.counters = service.run_counters(persisted.entries)
    service.store.save(run_name, persisted.model_dump(mode="json"))
    if budget.remaining is not None:
        budget.take()
    try:
        mail = source.reader.fetch_uid(
            current.folder, current.uid, current.uidvalidity
        )
        result = service.process_mail(mail)
    except TimeoutError:
        # A connection-level timeout is not a result for this mail.  Keep
        # the durable ``processing`` entry intact so a newly constructed
        # reader can resume the exact materialised queue after reconnect.
        raise
    except Exception as exc:
        service.logger.event(
            "ERROR", "orchestrator", "mail_failed",
            folder=current.folder, uid=current.uid, error=str(exc),
        )
        # Keep the entry at ``processing``.  Retrying this exact queue
        # position after a restart is safer than skipping it and
        # potentially repeating one shared outage for every later mail.
        service._mail_processing_halted = True
        return False
    results.append(result)
    if result.state.get("awaiting_relevance"):
        # Keep the durable processing entry incomplete while moving
        # on to independent mail behind the held relevance question.
        return True
    service._finish_entry(run_name, queued, current, result)
    if result.outcome is ProcessingOutcome.FAILED:
        # A failed result is terminal for this run but deliberately not
        # checkpointed, so its durable MailState remains eligible for a
        # later retry.  Continue with the next independent queue item.
        return True
    checkpoint_name, checkpoint, ranges = contexts[source.account_id, current.folder]
    ranges = service._complete_uid(checkpoint_name, checkpoint, ranges, current.uid, current.uidvalidity)
    contexts[source.account_id, current.folder] = (checkpoint_name, checkpoint, ranges)
    return True


def _finish_entry(service: MailboxRunService, run_name: str, queued: MailRunEntry, current: MailRunEntry,
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
        service.logger.event(
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
    persisted = service.store.load_model(run_name, MailRunState)
    assert persisted is not None
    current = next(entry for entry in persisted.entries if entry.key == queued.key)
    current.status = terminal_status
    current.analysis_terminal = terminal_analysis
    current.user_action_open = terminal_status is MailRunEntryStatus.WAITING_FOR_USER
    current.failure_code = failure_code
    persisted.counters = service.run_counters(persisted.entries)
    service.store.save(run_name, persisted.model_dump(mode="json"))


def complete_resumed_entry(
    service: MailboxRunService, state: MailState, result: ProcessingResult
) -> None:
    """Synchronize a separately resumed mail with its durable run queue."""
    if (result.outcome is ProcessingOutcome.FAILED
            or result.state.get("awaiting_relevance")):
        return
    run_name = state_names.mail_run(state.imap.account_id)
    run = service.store.load_model(run_name, MailRunState)
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
    run.counters = service.run_counters(run.entries)
    service.store.save(run_name, run.model_dump(mode="json"))

    checkpoint_name = mailbox_run_module._checkpoint_name(state.imap.account_id, state.imap.folder)
    checkpoint = service.store.load_model(
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
    service._complete_uid(checkpoint_name, checkpoint.model_dump(exclude={"schema_version"}),
                       ranges, state.imap.uid, state.imap.uidvalidity)


def resume_pending(service: MailboxRunService, budget: _MailBudget | None = None) -> list[ProcessingResult]:
    """Resume due durable mail states, independently of IMAP checkpoints."""
    results: list[ProcessingResult] = []
    budget = budget or mailbox_run_module._MailBudget(None)
    now = datetime.now(UTC)
    for name in mail_state_names(service.store):
        if service.stop_event.is_set() or budget.remaining == 0:
            break
        state = None
        try:
            state = service.store.load_model(name, MailState)
            if state is None or (state.steps.completion != "pending" and
                                 state.steps.action_detection != "failed"):
                continue
            if state.awaiting_relevance:
                continue
            # Late: against the layer direction, named in tests/unit/test_layers.py.
            from ..processing.retry import blocked
            fingerprint = state.config_fingerprint
            active = getattr(service.orchestrator, "fingerprint_for", lambda _, fp=fingerprint: fp)(
                state.imap.account_id)
            if blocked(state, active, now):
                continue
            if state.steps.completion == "completed" and state.missing_analysis_steps:
                missing = state.missing_analysis_steps
                state.steps.action_detection = "skipped"
                state.error = ProcessingError(code=ProcessingErrorCode.ANALYSIS_DATA_REMOVED,
                                              stage=ProcessingStage.ACTION_DETECTION,
                                              occurred_at=now, retryable=False)
                service.store.save(name, state.model_dump(mode="json"))
                service.logger.event("WARNING", "orchestrator", "resume_abandoned", mail_id=state.id,
                                  reason="analysis_data_removed", missing_steps=missing)
                continue
            source = service._source(state.imap.account_id)
            reader = source.reader if source is not None else service.resume_readers.get(state.imap.account_id)
            if reader is None:
                service._report_unavailable(state.imap.account_id)
                continue
            # 5.1.7: like processing itself, only an unfinished mail needs its configuration,
            # and it is the configuration of its own mailbox (3.2), not the global one.
            accepts = getattr(service.orchestrator, "accepts_configuration",
                              lambda fp, account=None: fp == service.orchestrator.config_fingerprint)
            if (state.steps.completion != "completed"
                    and not accepts(state.config_fingerprint, state.imap.account_id)):
                if budget.blocked_remaining == 0:
                    break
                budget.take_blocked()
                service.logger.event(
                    "WARNING", "orchestrator", "configuration_changed",
                    mail_id=state.id,
                )
                results.append(ProcessingResult(
                    ProcessingOutcome.WAITING, state.model_dump(mode="json")
                ))
                continue
            if budget.remaining is not None:
                budget.take()
            mail = reader.fetch_uid(state.imap.folder, state.imap.uid, state.imap.uidvalidity)
            result = service.process_mail(mail)
            results.append(result)
            service.complete_resumed_entry(state, result)
            if result.outcome is ProcessingOutcome.FAILED:
                service.logger.event("ERROR", "orchestrator", "resume_failed", state_name=name,
                                  error=result.state.get("error"))
                continue
        except Exception as exc:
            failure = getattr(service.orchestrator, "failure", None)
            if state is not None and failure is not None:
                failure(name, state, ProcessingErrorCode.INTERNAL_ERROR,
                        state.error.stage if state.error else ProcessingStage.PREPARATION,
                        "Wiederaufnahme fehlgeschlagen; bitte Verbindung und Konfiguration prüfen.")
            service.logger.event("ERROR", "orchestrator", "resume_failed", state_name=name, error=str(exc))
    return results


def _unfinished_run(service: MailboxRunService, source: MailboxSource, waiting: set[str]) -> _Run | None:
    """The stored queue of one mailbox while it still has runnable positions."""
    run_name = state_names.mail_run(source.account_id)
    run = service.store.load_model(run_name, MailRunState)
    if run is not None and any(
        entry.key not in waiting and entry.status in {MailRunEntryStatus.DISCOVERED, MailRunEntryStatus.QUEUED,
                                                     MailRunEntryStatus.PROCESSING}
        for entry in run.entries
    ):
        return source, run_name, run
    return None


def _waiting_identities(service: MailboxRunService) -> set[str]:
    """Waiting relevance is durable mail work, not a runnable queue position.

    It is excluded from discovery and budgets until an authorized answer arrives.
    """
    waiting = set()
    for name in mail_state_names(service.store):
        state = service.store.load_model(name, MailState)
        assert state is not None  # the name was just listed by the store
        if state.awaiting_relevance:
            identity = state.imap
            waiting.add(f"{identity.account_id}\0{identity.folder}\0{identity.uidvalidity}\0{identity.uid}")
    return waiting
