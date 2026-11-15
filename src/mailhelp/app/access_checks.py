"""Access checks of the running application: mail, Telegram and write targets (7.0, R5)."""
from __future__ import annotations

import traceback
from collections.abc import Callable
from datetime import datetime
from threading import Thread
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from ..external.contracts import TargetWriter
from ..logging import NullLogger
from ..mailbox.mailbox_run import MailboxSource
from ..mailbox.mailbox_settings import active_profiles, profile_label
from ..proposals.target_profiles import ProfileWriters, UnavailableWriter
from ..telegram import TelegramChatNotFoundError
from . import application as application_module

if TYPE_CHECKING:
    from .application import Application


def check_access(app: Application) -> dict[str, str | None]:
    """Check every external credential and target without processing mail."""
    def check_imap(source: MailboxSource) -> None:
        failures = []
        for folder in source.mailbox.folders:
            try:
                source.reader.check_access([folder])
            except Exception as exc:
                failures.append(f"{folder}: {str(exc) or type(exc).__name__}")
            else:
                getattr(app, "logger", NullLogger()).event(
                    "DEBUG", "access_check", "imap_folder_accessible", mailbox=source.mailbox.id, folder=folder)
        if failures:
            raise RuntimeError("IMAP: " + "; ".join(failures))

    several = len(app.sources) > 1
    checks: tuple[tuple[str, Callable[[], None]], ...] = (
        *((f"IMAP Postfach {source.mailbox.id} ({source.mailbox.label})" if several else "IMAP",
           lambda source=source: check_imap(source)) for source in app.sources),
        (app.openrouter.service_name, app.openrouter.check_access),
        ("Telegram", lambda: application_module.Application._check_telegram_access(app)),
        (getattr(app.todoist, "label", "Todoist"), app.todoist.check_access),
        (getattr(app.calendar, "label", "Google Kalender"), app.calendar.check_access),
    )
    iserv = getattr(app, "iserv", None)
    if iserv is not None:
        checks = (*checks, *((f"IServ {source.account.label}", source.reader.check_access)
                             for source in iserv.sources))
    profile_writers = getattr(app, "profile_writers", None)
    if isinstance(profile_writers, ProfileWriters):
        checks = (*checks[:-2], *((f"{role}:{number} ({profile_label(app.settings, number)})", writer.check_access)
            for number, pair in profile_writers.profiles.items() if number in active_profiles(app.settings)
            for role, writer in pair.slots.items()))
    results: dict[str, str | None] = {}
    logger = getattr(app, "logger", NullLogger())
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


def confirm_access_in_background(app: Application) -> Thread:
    """Run :meth:`confirm_access` beside the mail loop; a slow service never delays it."""
    thread = Thread(target=app.confirm_access, name="mailhelp-access-check", daemon=True)
    thread.start()
    return thread


def confirm_access(app: Application) -> None:
    """Read-only access check at service start, so the status page knows each service at once.

    Unlike :meth:`check_access` it sends no Telegram test message and leaves IMAP to the
    first mail cycle.  A failure is only logged; the service shows as unknown until a
    later contact succeeds.
    """
    checks: list[tuple[str, Any]] = [("llm", app.openrouter)]
    if app.settings.telegram.enabled:
        checks.append(("telegram", app.telegram))
    checks += [(writer.service, writer) for writer in app._active_writers()
               if not isinstance(writer, UnavailableWriter)]
    if app.iserv is not None:
        checks += [("iserv", source.reader) for source in app.iserv.sources]
    for service, client in checks:
        if app.stop_event.is_set():
            return
        context = ({"account": client.account.id} if service == "iserv"
                   else {"profile": getattr(client, "target_profile", 1)})
        try:
            # Looked up inside the guard: a client without a check counts as unconfirmed.
            client.check_access()
        except Exception as exc:
            app.logger.event("WARNING", service, "access_check_failed", error=exc, **context)
        else:
            app.logger.event("INFO", service, "access_confirmed", **context)


def _active_writers(app: Application) -> list[TargetWriter]:
    profile_writers = app.profile_writers
    if isinstance(profile_writers, ProfileWriters):
        active = active_profiles(app.settings)
        return [writer for number, pair in profile_writers.profiles.items() if number in active
                for writer in pair.slots.values()]
    return [app.todoist, app.calendar]


def _check_telegram_access(app: Application) -> None:
    """Validate the bot and visibly prove access to the configured chat."""
    app.telegram.check_access()
    now = datetime.now(ZoneInfo(app.settings.timezone))
    message = (
        f"Test – Datum: {now:%d.%m.%Y}, Uhrzeit: {now:%H:%M:%S} "
        f"({app.settings.timezone})"
    )
    try:
        app.telegram.send(app.settings.telegram.chat_id, message)
    except TelegramChatNotFoundError as exc:
        chats = app.telegram.started_chats(app.settings.telegram.user_id)
        configured = app.settings.telegram.chat_id
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
