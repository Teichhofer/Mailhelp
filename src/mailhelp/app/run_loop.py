"""The main loop: poll mailboxes and Telegram, process mails, wait between cycles (7.0, R5)."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from .. import state_names
from ..domain.run import MailRunState, TelegramOffset
from ..external.contracts import OAuthTokenError
from ..logging import NullLogger, log_and_continue
from ..mailbox.mailbox_run import _RunSummary
from ..processing.orchestrator import ProcessingOutcome, ProcessingResult
from ..telegram.commands import STARTUP
from . import application as application_module

if TYPE_CHECKING:
    from ..mailbox.imap import FetchedMail
    from .application import Application


def _idle(app: Application, delay: float) -> None:
    """Wait for the next mail cycle while handling Telegram input as it arrives."""
    getattr(app, "logger", NullLogger()).event("DEBUG", "application", "idle_started", delay_seconds=delay)
    # The operator thread handles input; otherwise this loop does between cycles.
    if app.services.receiver is None or app.services.operator is not None:
        app.stop_event.wait(delay)
        return
    deadline = time.monotonic() + delay
    while not app.stop_event.is_set():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        if app.services.receiver.inbox.wait(remaining):
            app._poll_telegram(timeout=0)


def _poll_imap(app: Application, max_mails: int | None = None, *,
               ignore_historical_start: bool = False) -> list[ProcessingResult]:
    return app.mailbox.poll(max_mails, ignore_historical_start=ignore_historical_start)


def _poll_telegram(app: Application, timeout: int | None = None) -> bool:
    """Poll Telegram once and report whether the request completed normally.

    With a receiver thread, wait up to *timeout* (default: the Telegram
    long-poll time) for its inbox and then process what arrived.
    """
    if app.services.receiver is not None:
        app.services.receiver.inbox.wait(app.settings.timeouts.telegram_poll_seconds
                                  if timeout is None else timeout)
    if app.dialog is not None:
        try:
            app.dialog.poll_once(timeout=timeout)
        except OAuthTokenError as exc:
            app._stop_after_fatal_oauth_error(exc)
            return False
        except Exception as exc:
            app.logger.event("ERROR", "telegram", "poll_failed", error=str(exc))
            return False
        return True
    state_model = app.store.load_model("telegram-offset", TelegramOffset, TelegramOffset())
    try:
        updates = app.telegram.poll(state_model.offset, timeout=timeout)
    except Exception as exc:
        app.logger.event("ERROR", "telegram", "poll_failed", error=str(exc))
        return False
    for update in updates:
        offset = int(update["update_id"]) + 1
        app.store.save("telegram-offset", TelegramOffset(offset=offset).model_dump())
        app.logger.event("INFO", "telegram", "update_received", update_id=update["update_id"])
    return True


def _stop_after_fatal_oauth_error(app: Application, exc: OAuthTokenError) -> None:
    """Stop permanently after Google rejected the configured OAuth grant."""
    app._fatal_error = str(exc)
    app.logger.event(
        "CRITICAL", "application", "fatal_google_oauth_error",
        error=app._fatal_error,
    )
    try:
        app.telegram.send(
            app.settings.telegram.chat_id,
            "Mailhelp wird beendet: Die Google-OAuth-Anmeldung wurde "
            "abgelehnt. Bitte Google-Zugangsdaten erneuern, danach "
            "'mailhelp --check-access' ausführen und Mailhelp neu starten.",
        )
    except Exception as notification_error:
        app.logger.event(
            "ERROR", "telegram", "fatal_error_notification_failed",
            error=str(notification_error),
        )
    app.stop_event.set()


def _process_mail(app: Application, mail: FetchedMail) -> ProcessingResult:
    """Wait only for relevance; proposals are independent of mail analysis."""
    if app.services.receiver is not None:
        # Button presses received during the previous mail come first.
        app._poll_telegram(timeout=0)
    while True:
        if (app._wait_for_user and app.dialog is not None
                and app.dialog.awaiting_relevance_decision()
                and not app._wait_for_telegram_decision()):
            return ProcessingResult(ProcessingOutcome.WAITING, {})
        result = app.orchestrator.process(mail)
        if (not app._wait_for_user or app.dialog is None
                or not app.dialog.awaiting_relevance_decision()):
            return result
        resume_mail = result.outcome is ProcessingOutcome.WAITING
        if not app._wait_for_telegram_decision():
            return result
        if not resume_mail:
            return result


def _wait_for_telegram_decision(app: Application) -> bool:
    """Long-poll until the blocking relevance decision is resolved or stopped."""
    if app.dialog is None or not app.dialog.awaiting_relevance_decision():
        return False
    operator = app.services.operator
    while not app.stop_event.is_set():
        if operator is not None:
            # Cleared before checking: a decision served after this sets it again.
            operator.served.clear()
        if not app.dialog.awaiting_relevance_decision():
            break
        if operator is not None:
            operator.served.wait(app.settings.poll_interval_seconds)
        elif not app._poll_telegram():
            app.stop_event.wait(min(
                app.settings.poll_interval_seconds,
                application_module._TELEGRAM_ERROR_BACKOFF_SECONDS,
            ))
    return not app.stop_event.is_set()


def run(app: Application, max_mails: int | None = None, *,
        ignore_historical_start: bool = False) -> str | None:
    app._wait_for_user = True
    app._announce_start()
    app._start_receiver()
    app._start_web()
    app._start_operator()
    current = app
    try:
        while not app.stop_event.is_set():
            if app.reload is not None:
                app.reload.advance()
                current = app.reload.current
            if not current._cycle(max_mails, ignore_historical_start):
                break
    finally:
        current._finish(max_mails)
        if app.reload is not None:
            app.reload.close()
    return current._fatal_error


def _announce_start(app: Application) -> None:
    """Greeting, open decisions and held messages; no failure blocks the start."""
    if app.notifications is not None:
        return
    try:
        app.telegram.send(app.settings.telegram.chat_id, STARTUP)
    except Exception as exc:
        # A failed greeting must not block recovery or disclose provider data.
        log_and_continue(app.logger, "telegram", "startup_help_failed", exc)
    else:
        app.logger.event("INFO", "telegram", "startup_help_sent")
    try:
        if app.dialog is not None and app.dialog.awaiting_decision():
            app.dialog.show_open_decisions()
    except Exception as exc:
        log_and_continue(app.logger, "telegram", "startup_decisions_failed", exc)
    try:
        if app.dialog is not None:
            # Held messages whose question was resolved before a restart.
            app.dialog.flush_outbox()
    except Exception as exc:
        log_and_continue(app.logger, "telegram", "startup_outbox_failed", exc)


def _cycle(app: Application, max_mails: int | None, ignore_historical_start: bool) -> bool:
    """One pass: maintenance, mail, Telegram input and idle time; ``False`` ends the run."""
    app._apply_requested_configuration()
    for runtime in (app.mailbox_runtime, app.iserv_runtime):
        if runtime is not None:
            runtime.apply_pending()
    app._maintain()
    # Only an already open, durable relevance decision precedes mailbox
    # work.  An unconditional Telegram long-poll here used to make
    # every fresh start look stuck for up to telegram_poll_seconds.
    if app.dialog is not None and app.dialog.awaiting_relevance_decision():
        app._wait_for_telegram_decision()
    # A paused proposal revision is isolated to its source mail.
    # It must never prevent independent queued mail from being
    # analysed; the durable clarification remains available for an
    # operator retry without acting as a global circuit breaker.
    if not app.stop_event.is_set():
        if ignore_historical_start:
            app._poll_imap(
                max_mails, ignore_historical_start=True
            )
        else:
            app._poll_imap(max_mails)
    if not app.stop_event.is_set() and app.iserv is not None:
        app.iserv.poll(max_mails)
    if app.stop_event.is_set():
        return False
    if max_mails is not None:
        return False
    # The receiver already waited for input; only process what arrived.
    if app.services.operator is not None:
        telegram_poll_succeeded = True
    elif app.services.receiver is not None:
        telegram_poll_succeeded = app._poll_telegram(timeout=0)
    else:
        telegram_poll_succeeded = app._poll_telegram()
    if (not app.stop_event.is_set() and app.dialog is not None
            and app.dialog.awaiting_relevance_decision()):
        app._wait_for_telegram_decision()
    delay = (min(app.settings.poll_interval_seconds,
                 application_module._TELEGRAM_ERROR_BACKOFF_SECONDS)
             if not telegram_poll_succeeded
             else app.settings.poll_interval_seconds)
    app._idle(delay)
    return True


def _finish(app: Application, max_mails: int | None) -> None:
    """Stop the helpers and report the run, unless a relevance question still blocks it."""
    app.services.stop_operator()
    app.services.stop_web()
    app.services.stop_receiver()
    if app.lifecycle is not None:
        app.lifecycle.finished()
    runs = [app.store.load_model(state_names.mail_run(source.account_id), MailRunState)
            for source in app.sources]
    summary = _RunSummary.from_runs(runs)
    # Relevance still blocks analysis. Proposal buttons remain usable
    # independently of the run summary and of subsequent mail runs.
    if app.dialog is not None and app.dialog.awaiting_relevance_decision():
        app.logger.event("INFO", "telegram", "run_summary_deferred")
    elif summary.empty:
        app.logger.event("INFO", "telegram", "run_summary_skipped", reason="no_mail")
    else:
        try:
            app.telegram.send(
                app.settings.telegram.chat_id,
                summary.message(bounded=max_mails is not None) + app._mailbox_lines(runs),
            )
        except Exception as exc:
            app.logger.event("ERROR", "telegram", "run_summary_failed", error=str(exc))
        else:
            app.logger.event("INFO", "telegram", "run_summary_sent",
                              discovered=summary.discovered, queued=summary.queued,
                              processed=summary.processed, relevant=summary.relevant,
                              irrelevant=summary.irrelevant,
                              waiting_for_user=summary.waiting_for_user,
                              failed=summary.failed, skipped=summary.skipped,
                              run_complete=summary.run_complete)


def _mailbox_lines(app: Application, runs: list[MailRunState | None]) -> str:
    """With several mailboxes, one line per mailbox that took part in the run."""
    if len(app.sources) < 2:
        return ""
    lines = [f"\n{source.mailbox.label}: {_RunSummary.from_run(run).processed} von "
             f"{len(run.entries)} Mails geprüft"
             for source, run in zip(app.sources, runs, strict=True) if run is not None and run.entries]
    return "".join(lines)
