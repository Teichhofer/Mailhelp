"""Read-only account inventory and rendering from configuration and observed contacts."""
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from ..config import Settings
from ..external.providers import CALENDAR_LABELS, TASK_LABELS
from ..formatting import format_datetime_local
from ..mailbox_settings import active_profiles, profile_label, target_profiles

CALENDAR_SERVICES = {"google": "google_calendar", "caldav": "caldav_calendar", "outlook": "outlook_calendar"}
TASK_SERVICES = {"todoist": "todoist", "caldav": "caldav_tasks", "microsoft_todo": "microsoft_todo",
                 "apple_reminders": "apple_reminders"}


@dataclass(frozen=True)
class AccountInfo:
    key: str
    label: str
    enabled: bool
    inactive: str = "deaktiviert"
    connection: str = ""
    pending_restart: bool = False


def configured_accounts(settings: Settings) -> tuple[AccountInfo, ...]:
    accounts = [AccountInfo(f"imap:{box.id}", f"IMAP {box.id} · {box.label}", box.enabled,
                            connection=repr((box.host, box.port, box.connection_mode, box.folders)))
                for box in settings.imap.configured_mailboxes()]
    accounts += [AccountInfo(f"iserv:{account.id}", f"IServ {account.id} · {account.label}", account.enabled,
                             connection=repr((account.server, account.mailbox, account.historical_start)))
                 for account in settings.iserv.accounts]
    active = active_profiles(settings)
    for number, target in target_profiles(settings).items():
        label = f"{profile_label(settings, number)} ({number})"
        accounts += [
            AccountInfo(f"{CALENDAR_SERVICES[target.calendar_provider]}:{number}",
                        f"Kalender · {label} · {CALENDAR_LABELS[target.calendar_provider]}", number in active,
                        "nicht verwendet", connection=target.model_dump_json(exclude={"id", "label"})),
            AccountInfo(f"{TASK_SERVICES[target.task_provider]}:{number}",
                        f"Aufgaben · {label} · {TASK_LABELS[target.task_provider]}", number in active,
                        "nicht verwendet", connection=target.model_dump_json(exclude={"id", "label"}))]
    accounts.append(AccountInfo("telegram", "Telegram", settings.telegram.enabled))
    return tuple(accounts)


def account_rows(accounts: tuple[AccountInfo, ...], runtime: dict, zone: ZoneInfo) -> list[tuple[str, str]]:
    rows = []
    for account in accounts:
        observed = runtime.get("accounts", {}).get(account.key, {})
        folder_failed = any(account.key == f'imap:{error["mailbox"]}' for error in runtime.get("imap_errors", []))
        if account.pending_restart:
            status = f"Neustart erforderlich ({'aktiv' if account.enabled else account.inactive})"
        elif not account.enabled:
            status = account.inactive
        elif folder_failed or observed.get("status") == "failed":
            status = "Fehler beim letzten Verbindungsversuch"
        elif observed.get("status") == "ready":
            when = format_datetime_local(datetime.fromisoformat(observed["checked_at"]), zone)
            status = "zuletzt erfolgreich " + when
        else:
            status = "noch nicht geprüft (seit Dienststart kein belegter Kontakt)"
        rows.append((account.label, status))
    return rows
