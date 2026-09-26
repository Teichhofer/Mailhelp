"""Composition Root und kontrollierte Polling-Schleife des Dienstes."""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
import imaplib
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from typing import Iterator
from uuid import uuid4
from zoneinfo import ZoneInfo

from .analysis import Analyzer
from .config import PromptConfig, Secrets, Settings, Topic
from .imap import ImapReader, UIDValidityChanged
from .integrations import GoogleOAuthTokenProvider, HttpWriter
from .logging import JsonlLogger, NullLogger
from .models import (ImapCheckpoint, MailRunCounters, MailRunEntry,
                     MailRunEntryStatus, MailRunState, MailState, TelegramOffset)
from .openrouter import OpenRouterClient
from .orchestrator import Orchestrator, ProcessingOutcome, ProcessingResult
from .storage import JsonStore, mail_state_names
from .telegram import (TelegramChatNotFoundError, TelegramClient,
                       TelegramDialogController)
from .adapter import RetryPolicy
from .retention import RetentionService

_BLOCKED_STATE_SCAN_LIMIT = 1000
_TELEGRAM_ERROR_BACKOFF_SECONDS = 5.0


class _FailedAccessAdapter:
    """Expose an adapter construction failure to the aggregated access check."""

    def __init__(self, error: Exception):
        self.error = error

    def check_access(self, *_args: object) -> None:
        raise self.error


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
    def from_run(cls, run: MailRunState | None) -> "_RunSummary":
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

    def message(self, *, bounded: bool = False) -> str:
        lines = [
            ("Mailhelp-Lauf vollständig abgearbeitet."
             if self.run_complete else "Mailhelp-Lauf abgebrochen oder unvollständig."),
            f"Entdeckt: {self.discovered}",
            f"In Warteschlange: {self.queued}",
            f"Analysiert: {self.processed}",
            f"Relevant: {self.relevant}",
            f"Irrelevant: {self.irrelevant}",
            f"Warten auf Benutzer: {self.waiting_for_user}",
            f"Fehlgeschlagen: {self.failed}",
            f"Übersprungen: {self.skipped}",
        ]
        return "\n".join(lines)


@dataclass
class Application:
    settings: Settings
    store: JsonStore
    logger: JsonlLogger
    imap: ImapReader
    openrouter: OpenRouterClient
    analyzer: Analyzer
    telegram: TelegramClient
    todoist: HttpWriter
    calendar: HttpWriter
    orchestrator: Orchestrator
    stop_event: Event
    dialog: TelegramDialogController | None = None
    sender_store: JsonStore | None = None
    _wait_for_user: bool = False
    _mail_processing_halted: bool = False

    def check_access(self) -> dict[str, str | None]:
        """Check every external credential and target without processing mail."""
        def check_imap() -> None:
            imap_settings = self.settings.imap
            primary = getattr(imap_settings, "primary_folder", imap_settings.folders[0])
            self.imap.check_access([primary])
            for folder in (item for item in imap_settings.folders if item != primary):
                try:
                    self.imap.check_access([folder])
                except Exception as exc:
                    getattr(self, "logger", NullLogger()).event(
                        "WARNING", "imap", "optional_folder_failed",
                        folder=folder, error=exc,
                    )

        checks = (
            ("IMAP", check_imap),
            ("OpenRouter", self.openrouter.check_access),
            ("Telegram", lambda: Application._check_telegram_access(self)),
            ("Todoist", self.todoist.check_access),
            ("Google Kalender", self.calendar.check_access),
        )
        results: dict[str, str | None] = {}
        logger = getattr(self, "logger", NullLogger())
        for name, check in checks:
            logger.event("DEBUG", "access_check", "check_started", service=name)
            try:
                check()
            except Exception as exc:
                logger.event(
                    "ERROR", "access_check", "check_failed", service=name,
                    error=exc, stacktrace=traceback.format_exc(),
                )
                # Adapter diagnostics are already safe, service-specific user
                # messages.  Preserve them verbatim for the CLI rather than
                # replacing them with a generic access-check failure.
                message = str(exc)
                results[name] = message if message else type(exc).__name__
            else:
                results[name] = None
                logger.event("DEBUG", "access_check", "check_completed", service=name)
        return results

    def _check_telegram_access(self) -> None:
        """Validate the bot and visibly prove access to the configured chat."""
        self.telegram.check_access()
        now = datetime.now(ZoneInfo(self.settings.timezone))
        message = (
            f"Test – Datum: {now:%d.%m.%Y}, Uhrzeit: {now:%H:%M:%S} "
            f"({self.settings.timezone})"
        )
        try:
            self.telegram.send(self.settings.telegram.chat_id, message)
        except TelegramChatNotFoundError as exc:
            chats = self.telegram.started_chats(self.settings.telegram.user_id)
            configured = self.settings.telegram.chat_id
            if chats:
                found = ", ".join(str(chat_id) for chat_id in chats)
                raise TelegramChatNotFoundError(
                    f"{exc}. Für die konfigurierte telegram.user_id wurde /start "
                    f"in Chat {found} empfangen; konfiguriert ist telegram.chat_id "
                    f"{configured}. Bitte telegram.chat_id entsprechend korrigieren."
                ) from exc
            raise TelegramChatNotFoundError(
                f"{exc}. Von der konfigurierten telegram.user_id wurde kein /start "
                "bei diesem Bot empfangen. Bitte prüfen, ob /start an genau den Bot "
                "aus TELEGRAM_BOT_TOKEN gesendet wurde und telegram.user_id stimmt."
            ) from exc

    def stop(self) -> None:
        self.stop_event.set()
        self.orchestrator.stop()

    def _poll_imap(self, max_mails: int | None = None, *,
                   ignore_historical_start: bool = False) -> list[ProcessingResult]:
        """Resume durable work and process new mail, returning every outcome."""
        budget = _MailBudget(max_mails)
        results = self._resume_pending(budget)
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
            results.extend(self._poll_imap_global(
                budget, ignore_historical_start=ignore_historical_start
            ))
            return results
        for folder in self.settings.imap.folders:
            if self.stop_event.is_set() or budget.remaining == 0:
                break
            checkpoint_name = _checkpoint_name(self.imap.account_id, folder)
            checkpoint_model = self.store.load_model(checkpoint_name, ImapCheckpoint, ImapCheckpoint()) if hasattr(self.store, "load_model") else ImapCheckpoint.model_validate(self.store.load(checkpoint_name, {}))
            checkpoint = checkpoint_model.model_dump(exclude={"schema_version"})
            try:
                if checkpoint["start_uid"] is None:
                    if (self.settings.imap.historical_start is not None
                            and not ignore_historical_start):
                        start_uid = self.imap.determine_start_uid(folder, self.settings.imap.historical_start)
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
                try:
                    mails = self.imap.fetch_since(
                        folder, checkpoint["start_uid"], checkpoint.get("uidvalidity"),
                        budget.remaining, tuple(ranges),
                    )
                except UIDValidityChanged as changed:
                    self.logger.event(
                        "WARNING", "imap", "uidvalidity_changed",
                        account_id=self.imap.account_id, folder=folder,
                        previous_uidvalidity=changed.previous,
                        uidvalidity=changed.current,
                    )
                    if (self.settings.imap.historical_start is not None
                            and not ignore_historical_start):
                        start_uid = self.imap.determine_start_uid(
                            folder, self.settings.imap.historical_start
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
                    ranges = []
                    # Persist generation and its matching boundary atomically
                    # before message content from that generation is requested.
                    self.store.save(
                        checkpoint_name, ImapCheckpoint(**checkpoint).model_dump()
                    )
                    mails = self.imap.fetch_since(
                        folder, start_uid, changed.current, budget.remaining, ()
                    )
            except Exception as exc:
                primary = getattr(self.settings.imap, "primary_folder",
                                  self.settings.imap.folders[0])
                event = "poll_failed" if folder == primary else "optional_folder_failed"
                self.logger.event("ERROR", "imap", event, folder=folder, error=str(exc))
                continue
            for mail in mails:
                if self.stop_event.is_set() or budget.remaining == 0:
                    break
                if budget.remaining is not None:
                    budget.take()
                try:
                    result = self._process_mail(mail)
                except Exception as exc:
                    self.logger.event("ERROR", "orchestrator", "mail_failed", folder=folder, uid=mail.uid, error=str(exc))
                    continue
                results.append(result)
                if result.outcome is ProcessingOutcome.FAILED:
                    self.logger.event("ERROR", "orchestrator", "mail_failed",
                                      folder=folder, uid=mail.uid,
                                      error=result.state.get("error"))
                    self._mail_processing_halted = True
                    break
                # Every result reaching this point has a durable mail state.
                # Failed results are excluded above so their checkpoint remains
                # available for restart recovery.
                ranges = _add_uid(ranges, mail.uid)
                checkpoint["uid"] = max(checkpoint["uid"], mail.uid)
                checkpoint["uidvalidity"] = mail.uidvalidity
                checkpoint["completed_uid_ranges"] = ranges
                self.store.save(checkpoint_name, ImapCheckpoint(**checkpoint).model_dump())
            if not mails and self.imap.last_uidvalidity is not None:
                if checkpoint["uidvalidity"] is None:
                    checkpoint["uidvalidity"] = self.imap.last_uidvalidity
                self.store.save(checkpoint_name, ImapCheckpoint(**checkpoint).model_dump())
        return results

    def _poll_imap_global(self, budget: _MailBudget, *,
                          ignore_historical_start: bool = False) -> list[ProcessingResult]:
        """Process one mailbox-wide batch ordered by IMAP receive time."""
        run_name = f"mail-run-{self.imap.account_id}"
        active = (self.store.load_model(run_name, MailRunState)
                  if hasattr(self.store, "load_model") else None)
        active = active if active is not None and any(
            entry.status in {MailRunEntryStatus.DISCOVERED, MailRunEntryStatus.QUEUED,
                             MailRunEntryStatus.PROCESSING}
            for entry in active.entries
        ) else None
        contexts: dict[str, tuple[str, dict[str, object], list[tuple[int, int]]]] = {}
        candidates = []
        for folder in self.settings.imap.folders:
            if self.stop_event.is_set() or budget.remaining == 0:
                break
            checkpoint_name = _checkpoint_name(self.imap.account_id, folder)
            checkpoint_model = (self.store.load_model(
                checkpoint_name, ImapCheckpoint, ImapCheckpoint()
            ) if hasattr(self.store, "load_model") else ImapCheckpoint.model_validate(
                self.store.load(checkpoint_name, {})
            ))
            checkpoint = checkpoint_model.model_dump(exclude={"schema_version"})
            try:
                if checkpoint["start_uid"] is None:
                    if (self.settings.imap.historical_start is not None
                            and not ignore_historical_start):
                        start_uid = self.imap.determine_start_uid(
                            folder, self.settings.imap.historical_start
                        )
                        initial_uidvalidity = self.imap.last_uidvalidity
                    else:
                        start_uid = checkpoint["uid"]
                        initial_uidvalidity = checkpoint["uidvalidity"]
                    checkpoint_model = ImapCheckpoint(
                        uidvalidity=initial_uidvalidity, uid=start_uid, start_uid=start_uid
                    )
                    self.store.save(checkpoint_name, checkpoint_model.model_dump())
                    checkpoint = checkpoint_model.model_dump(exclude={"schema_version"})
                ranges = checkpoint["completed_uid_ranges"]
                if not ranges and checkpoint["uid"] > checkpoint["start_uid"]:
                    ranges = [(checkpoint["start_uid"] + 1, checkpoint["uid"])]
                if ignore_historical_start and checkpoint["start_uid"] != 0:
                    checkpoint["start_uid"] = 0
                    self.store.save(
                        checkpoint_name, ImapCheckpoint(**checkpoint).model_dump()
                    )
                if active is not None:
                    contexts[folder] = (checkpoint_name, checkpoint, ranges)
                    continue
                try:
                    discovered = self.imap.discover_since(
                        folder, checkpoint["start_uid"], checkpoint.get("uidvalidity"),
                        tuple(ranges),
                    )
                except UIDValidityChanged as changed:
                    self.logger.event(
                        "WARNING", "imap", "uidvalidity_changed",
                        account_id=self.imap.account_id, folder=folder,
                        previous_uidvalidity=changed.previous, uidvalidity=changed.current,
                    )
                    if (self.settings.imap.historical_start is not None
                            and not ignore_historical_start):
                        start_uid = self.imap.determine_start_uid(
                            folder, self.settings.imap.historical_start
                        )
                        if self.imap.last_uidvalidity != changed.current:
                            raise RuntimeError(
                                f"IMAP-UIDVALIDITY änderte sich während der Grenzermittlung: {folder}"
                            )
                    else:
                        start_uid = 0
                    checkpoint = ImapCheckpoint(
                        uidvalidity=changed.current, uid=start_uid, start_uid=start_uid
                    ).model_dump(exclude={"schema_version"})
                    ranges = []
                    self.store.save(
                        checkpoint_name, ImapCheckpoint(**checkpoint).model_dump()
                    )
                    discovered = self.imap.discover_since(
                        folder, start_uid, changed.current, ()
                    )
            except Exception as exc:
                primary = getattr(self.settings.imap, "primary_folder",
                                  self.settings.imap.folders[0])
                event = "poll_failed" if folder == primary else "optional_folder_failed"
                self.logger.event("ERROR", "imap", event, folder=folder, error=str(exc))
                continue
            contexts[folder] = (checkpoint_name, checkpoint, ranges)
            candidates.extend(discovered)
            if not discovered and self.imap.last_uidvalidity is not None:
                if checkpoint["uidvalidity"] is None:
                    checkpoint["uidvalidity"] = self.imap.last_uidvalidity
                self.store.save(
                    checkpoint_name, ImapCheckpoint(**checkpoint).model_dump()
                )

        candidates.sort(key=lambda item: item.received_at, reverse=True)
        limit = budget.remaining if budget.remaining is not None else self.settings.imap.batch_size
        if active is not None:
            run = active
        else:
            unique = {}
            for candidate in candidates:
                entry = MailRunEntry(
                    account_id=candidate.account_id, folder=candidate.folder,
                    uidvalidity=candidate.uidvalidity, uid=candidate.uid,
                    status=MailRunEntryStatus.QUEUED,
                )
                unique.setdefault(entry.key, entry)
                if len(unique) == limit:
                    break
            entries = list(unique.values())
            run = MailRunState(
                run_id=uuid4(), max_mails=budget.remaining,
                created_at=datetime.now(timezone.utc), entries=entries,
                counters=self._run_counters(entries),
            )
            # The complete, deduplicated identity list is durable before the
            # first BODY.PEEK or analyzer call is allowed to happen.
            self.store.save(run_name, run.model_dump(mode="json"))

        results: list[ProcessingResult] = []
        for queued in run.entries:
            if self.stop_event.is_set() or budget.remaining == 0:
                break
            # Reload before every transition: repeated invocations must observe
            # another worker/restart having completed this identity already.
            persisted = self.store.load_model(run_name, MailRunState)
            assert persisted is not None
            current = next(entry for entry in persisted.entries if entry.key == queued.key)
            if current.status not in {MailRunEntryStatus.DISCOVERED,
                                      MailRunEntryStatus.QUEUED,
                                      MailRunEntryStatus.PROCESSING}:
                continue
            current.status = MailRunEntryStatus.PROCESSING
            current.analysis_terminal = None
            current.user_action_open = False
            current.failure_code = None
            persisted.counters = self._run_counters(persisted.entries)
            self.store.save(run_name, persisted.model_dump(mode="json"))
            if budget.remaining is not None:
                budget.take()
            try:
                mail = self.imap.fetch_uid(
                    current.folder, current.uid, current.uidvalidity
                )
                result = self._process_mail(mail)
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
                break
            else:
                results.append(result)
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
                    self._mail_processing_halted = True
                    terminal_status = MailRunEntryStatus.FAILED
                    terminal_analysis = "failed"
                    failure_code = "processing_failed"
                else:
                    terminal_status = (MailRunEntryStatus.WAITING_FOR_USER
                                       if result.outcome is ProcessingOutcome.WAITING
                                       else MailRunEntryStatus.COMPLETED)
                    if result.state.get("duplicate") is not None:
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
            persisted.counters = self._run_counters(persisted.entries)
            self.store.save(run_name, persisted.model_dump(mode="json"))

            if result.outcome is ProcessingOutcome.FAILED:
                # A failed result is terminal for this run but deliberately not
                # checkpointed.  Do not fan a shared provider/configuration
                # problem out over the remaining queue in the same process.
                break

            checkpoint_name, checkpoint, ranges = contexts[current.folder]
            ranges = _add_uid(ranges, current.uid)
            checkpoint["uid"] = max(checkpoint["uid"], current.uid)
            checkpoint["uidvalidity"] = current.uidvalidity
            checkpoint["completed_uid_ranges"] = ranges
            contexts[current.folder] = (checkpoint_name, checkpoint, ranges)
            self.store.save(checkpoint_name, ImapCheckpoint(**checkpoint).model_dump())
            if self._processing_blocked():
                break
        return results

    @staticmethod
    def _run_counters(entries: list[MailRunEntry]) -> MailRunCounters:
        values = {status.value: 0 for status in MailRunEntryStatus}
        for entry in entries:
            values[entry.status.value] += 1
        return MailRunCounters(**values)

    def _resume_pending(self, budget: _MailBudget | None = None) -> list[ProcessingResult]:
        """Resume due durable mail states, independently of IMAP checkpoints."""
        results: list[ProcessingResult] = []
        if not hasattr(self.store, "names"):
            return results
        budget = budget or _MailBudget(None)
        now = datetime.now(timezone.utc)
        for name in mail_state_names(self.store):
            if self.stop_event.is_set() or budget.remaining == 0:
                break
            try:
                state = self.store.load_model(name, MailState)
                if state is None or (state.steps.completion != "pending" and
                                     state.steps.action_detection != "failed"):
                    continue
                if state.imap.account_id != self.imap.account_id:
                    continue
                if state.config_fingerprint != self.orchestrator.config_fingerprint:
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
                result = self._process_mail(mail)
                results.append(result)
                if self._processing_blocked():
                    break
                if result.outcome is ProcessingOutcome.FAILED:
                    self.logger.event("ERROR", "orchestrator", "resume_failed", state_name=name,
                                      error=result.state.get("error"))
                    self._mail_processing_halted = True
                    break
            except Exception as exc:
                self.logger.event("ERROR", "orchestrator", "resume_failed", state_name=name, error=str(exc))
        return results

    def _poll_telegram(self, timeout: int | None = None) -> bool:
        """Poll Telegram once and report whether the request completed normally."""
        if self.dialog is not None:
            try:
                self.dialog.poll_once(timeout=timeout)
            except Exception as exc:
                self.logger.event("ERROR", "telegram", "poll_failed", error=str(exc))
                return False
            return True
        state_model = self.store.load_model("telegram-offset", TelegramOffset, TelegramOffset()) if hasattr(self.store, "load_model") else TelegramOffset.model_validate(self.store.load("telegram-offset", {}))
        try:
            updates = self.telegram.poll(state_model.offset, timeout=timeout)
        except Exception as exc:
            self.logger.event("ERROR", "telegram", "poll_failed", error=str(exc))
            return False
        for update in updates:
            offset = int(update["update_id"]) + 1
            self.store.save("telegram-offset", TelegramOffset(offset=offset).model_dump())
            self.logger.event("INFO", "telegram", "update_received", update_id=update["update_id"])
        return True

    def _process_mail(self, mail: object) -> ProcessingResult:
        """Pause mail processing while Telegram needs a user decision."""
        while True:
            if (self._wait_for_user and self.dialog is not None
                    and self.dialog.awaiting_decision()
                    and not self._wait_for_telegram_decision()):
                return ProcessingResult(ProcessingOutcome.WAITING, {})
            result = self.orchestrator.process(mail)
            if (not self._wait_for_user or self.dialog is None
                    or not self.dialog.awaiting_decision()):
                return result
            resume_mail = result.outcome is ProcessingOutcome.WAITING
            if not self._wait_for_telegram_decision():
                return result
            if not resume_mail:
                return result
            # An unclear relevance answer interrupts analysis. Once Telegram
            # resolved it, resume this same mail before advancing the mailbox.

    def _processing_blocked(self) -> bool:
        """Distinguish a technical operator block from a user decision."""
        checker = getattr(self.dialog, "processing_blocked", None)
        return bool(checker and checker())

    def _wait_for_telegram_decision(self) -> bool:
        """Long-poll until every current user decision is resolved or stopped."""
        if self.dialog is None or not self.dialog.awaiting_decision():
            return False
        while (not self.stop_event.is_set()
               and self.dialog.awaiting_decision()):
            if not self._poll_telegram():
                self.stop_event.wait(min(
                    self.settings.poll_interval_seconds,
                    _TELEGRAM_ERROR_BACKOFF_SECONDS,
                ))
        return not self.stop_event.is_set()

    def run(self, max_mails: int | None = None, *,
            ignore_historical_start: bool = False) -> None:
        self._wait_for_user = True
        try:
            while not self.stop_event.is_set():
                try:
                    RetentionService(self.store, self.settings.retention, self.logger).run()
                except Exception:
                    # No state content is included in this operational event.
                    self.logger.event("ERROR", "retention", "cleanup_failed",
                                      processed_at=datetime.now(timezone.utc).isoformat(), failure_count=1)
                # Only an already open, durable decision may precede mailbox
                # work.  An unconditional Telegram long-poll here used to make
                # every fresh start look stuck for up to telegram_poll_seconds.
                if self.dialog is not None and self.dialog.awaiting_decision():
                    self._wait_for_telegram_decision()
                if not self.stop_event.is_set() and not self._processing_blocked():
                    if ignore_historical_start:
                        self._poll_imap(
                            max_mails, ignore_historical_start=True
                        )
                    else:
                        self._poll_imap(max_mails)
                if self.stop_event.is_set():
                    break
                if max_mails is not None:
                    break
                telegram_poll_succeeded = self._poll_telegram()
                if (not self.stop_event.is_set() and self.dialog is not None
                        and self.dialog.awaiting_decision()):
                    self._wait_for_telegram_decision()
                delay = (min(self.settings.poll_interval_seconds,
                             _TELEGRAM_ERROR_BACKOFF_SECONDS)
                         if not telegram_poll_succeeded
                         else self.settings.poll_interval_seconds)
                self.stop_event.wait(delay)
        finally:
            run_name = f"mail-run-{self.imap.account_id}"
            run = (self.store.load_model(run_name, MailRunState)
                   if hasattr(self.store, "load_model") else None)
            summary = _RunSummary.from_run(run)
            # A shutdown must not append a run summary behind unanswered
            # inline buttons.  The next start resumes that decision first.
            if self.dialog is not None and self.dialog.awaiting_decision():
                self.logger.event("INFO", "telegram", "run_summary_deferred")
                return
            try:
                self.telegram.send(
                    self.settings.telegram.chat_id,
                    summary.message(bounded=max_mails is not None),
                )
            except Exception as exc:
                self.logger.event("ERROR", "telegram", "run_summary_failed", error=str(exc))
            else:
                self.logger.event("INFO", "telegram", "run_summary_sent",
                                  discovered=summary.discovered, queued=summary.queued,
                                  processed=summary.processed, relevant=summary.relevant,
                                  irrelevant=summary.irrelevant,
                                  waiting_for_user=summary.waiting_for_user,
                                  failed=summary.failed, skipped=summary.skipped,
                                  run_complete=summary.run_complete)


def _safe_name(folder: str) -> str:
    return folder.encode("utf-8").hex()


def _checkpoint_name(account: str, folder: str) -> str:
    return f"imap-{account}-{_safe_name(folder)}"


def _state_directory(settings: Settings, base_directory: Path) -> Path:
    """Return the fully isolated state namespace for the selected mode."""
    root = settings.data_directory if settings.data_directory.is_absolute() else base_directory / settings.data_directory
    return root / ("test" if settings.test_mode else "production")


def build_logger(
    settings: Settings,
    secrets: Secrets,
    base_directory: Path = Path("."),
    *,
    access_diagnostics: bool = False,
    log_directory: Path | None = None,
) -> JsonlLogger:
    """Construct the configured logger with every known secret redacted."""
    log_dir = log_directory if log_directory is not None else settings.logging.directory
    if not log_dir.is_absolute():
        log_dir = base_directory / log_dir
    known_secrets = tuple(value.get_secret_value() for value in (
        secrets.imap_password, secrets.openrouter_api_key, secrets.telegram_bot_token,
        secrets.todoist_token, secrets.todoist_client_id, secrets.todoist_client_secret,
        secrets.google_oauth_client_id, secrets.google_oauth_client_secret,
        secrets.google_oauth_refresh_token,
    ) if value is not None)
    log = settings.logging
    return JsonlLogger(
        log_dir, log.llm.include_requests, log.llm.include_responses,
        "DEBUG" if access_diagnostics else log.file.level,
        {} if access_diagnostics else log.modules,
        known_secrets,
        file_enabled=access_diagnostics or log.file.enabled, file_name=log.file.filename,
        file_format=log.file.format, file_max_bytes=log.file.max_bytes,
        file_backup_count=log.file.backup_count, file_retention_days=log.file.retention_days,
        console_enabled=access_diagnostics or log.console.enabled,
        console_level="DEBUG" if access_diagnostics else log.console.level,
        console_format=log.console.format,
        llm_enabled=log.llm.enabled, llm_level=log.llm.level,
        llm_name=log.llm.filename, llm_format=log.llm.format,
        llm_max_bytes=log.llm.max_bytes, llm_backup_count=log.llm.backup_count,
        llm_retention_days=log.llm.retention_days,
        telegram_enabled=log.telegram.enabled,
        telegram_level=log.telegram.level,
        telegram_name=log.telegram.filename,
        telegram_format=log.telegram.format,
        telegram_max_bytes=log.telegram.max_bytes,
        telegram_backup_count=log.telegram.backup_count,
        telegram_retention_days=log.telegram.retention_days,
    )


@contextmanager
def build_application(
    settings: Settings,
    secrets: Secrets,
    topics: list[Topic],
    prompts: PromptConfig,
    fingerprint: str,
    base_directory: Path = Path("."),
    *,
    access_diagnostics: bool = False,
    logger: JsonlLogger | None = None,
) -> Iterator[Application]:
    """Construct adapters and close every successfully constructed resource."""
    with ExitStack() as stack:
        data = _state_directory(settings, base_directory)
        store = stack.enter_context(JsonStore(data))
        sender_store = JsonStore(base_directory)
        if logger is None or access_diagnostics:
            logger = build_logger(
                settings, secrets, base_directory,
                access_diagnostics=access_diagnostics,
            )
        stop_event = Event()
        def policy(name: str) -> RetryPolicy:
            item = getattr(settings.timeouts, name)
            return RetryPolicy(item.retries, item.initial_backoff_seconds, item.max_backoff_seconds, stop_event.wait)
        imap_cfg = settings.timeouts.imap
        factory = imaplib.IMAP4_SSL if settings.imap.connection_mode == "ssl" else imaplib.IMAP4
        try:
            imap = ImapReader(settings.imap.host, settings.imap.port, secrets.imap_username, secrets.imap_password.get_secret_value(), imap_cfg.timeout_seconds, factory=factory, policy=policy("imap"), logger=logger, starttls=settings.imap.connection_mode == "starttls", batch_size=settings.imap.batch_size)
        except Exception as exc:
            if not access_diagnostics:
                raise
            # IMAP connects and authenticates in its constructor, unlike the
            # HTTP adapters. Preserve that failure as one diagnostic result so
            # constructing the application cannot prevent the other checks.
            imap = _FailedAccessAdapter(exc)
        else:
            stack.callback(imap.close)
        llm_cfg = settings.timeouts.openrouter
        openrouter = OpenRouterClient(secrets.openrouter_api_key.get_secret_value(), llm_cfg.timeout_seconds, llm_cfg.retries, settings.limits.llm_calls_per_minute, initial_backoff=llm_cfg.initial_backoff_seconds, max_backoff=llm_cfg.max_backoff_seconds, load_calls=lambda: store.load("llm-budget", {}).get("calls", []), save_calls=lambda calls: store.save("llm-budget", {"calls": calls}), logger=logger)
        stack.callback(openrouter.close)
        telegram = TelegramClient(secrets.telegram_bot_token.get_secret_value(), settings.timeouts.telegram.timeout_seconds, poll_timeout=settings.timeouts.telegram_poll_seconds, policy=policy("telegram"), logger=logger)
        stack.callback(telegram.close)
        todoist = HttpWriter("todoist", secrets.todoist_token.get_secret_value(), settings.targets.todoist_project, settings.timeouts.todoist.timeout_seconds, policy=policy("todoist"), logger=logger)
        stack.callback(todoist.close)
        google_cfg = settings.timeouts.google_calendar
        oauth = GoogleOAuthTokenProvider(
            secrets.google_oauth_client_id.get_secret_value(),
            secrets.google_oauth_client_secret.get_secret_value(),
            secrets.google_oauth_refresh_token.get_secret_value(),
            google_cfg.timeout_seconds,
            logger=logger,
        )
        stack.callback(oauth.close)
        analyzer = Analyzer(
            openrouter, prompts,
            provider_retries=settings.retries.provider_retry,
            json_repair_retries=settings.retries.json_repair,
            schema_repair_retries=settings.retries.schema_repair,
        )
        calendar = HttpWriter(
            "google_calendar", oauth, settings.targets.google_calendar,
            google_cfg.timeout_seconds, policy=policy("google_calendar"), logger=logger,
            calendar_timezone=settings.timezone,
            calendar_matcher=analyzer.calendar_duplicate,
        )
        stack.callback(calendar.close)
        dialog = TelegramDialogController(
            store, telegram, settings.telegram.user_id, settings.telegram.chat_id, logger,
            {"todoist": todoist, "google_calendar": calendar}, settings.test_mode,
            settings.timezone,
            analyzer,
            interpretation_attempts=settings.retries.interpretation_attempts,
            interpretation_backoff_seconds=settings.retries.interpretation_backoff_seconds,
            revision_attempts=settings.retries.revision_attempts,
            revision_backoff_seconds=settings.retries.revision_backoff_seconds,
        )
        orchestrator = Orchestrator(analyzer, store, dialog, settings.telegram.chat_id, topics, settings.limits.max_mail_bytes, logger, mime_limits=settings.limits, config_fingerprint=fingerprint, targets=settings.targets, user_timezone=settings.timezone, sender_store=sender_store)
        dialog.relevance_handler = orchestrator
        orchestrator.stop_event = stop_event
        yield Application(settings, store, logger, imap, openrouter, analyzer, telegram, todoist, calendar, orchestrator, stop_event, dialog, sender_store)
