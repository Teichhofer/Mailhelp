"""Mailboxes, folders and IServ accounts. (7.0: split from models.py)"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import (
    Field,
    field_validator,
    model_validator,
)

from .base import ConfigModel
from .notifications import NotificationOverrides
from .runtime_settings import MailboxRetention
from .target_settings import MailboxEventDefaults


def _default_primary_to_first_folder(value: object) -> object:
    # Backwards-compatible loading gives old configurations the same clear
    # semantics: their first source is required, all following ones optional.
    if isinstance(value, dict) and "primary_folder" not in value:
        folders = value.get("folders")
        if isinstance(folders, list) and folders:
            value = {**value, "primary_folder": folders[0]}
    return value

def _valid_historical_start(value: object) -> datetime | None:
    if isinstance(value, str):
        value = re.sub(r"^(\d{4}-\d{2}-\d{2})\s*T\s*", r"\1T", value.strip())
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("historical_start muss ISO 8601 entsprechen") from exc
    if value is not None and not isinstance(value, datetime):
        raise ValueError("historical_start muss ein Zeitpunkt oder null sein")
    if value is not None and value.tzinfo is None:
        raise ValueError("historical_start muss einen UTC-Offset enthalten")
    return value

def _valid_folders(folders: list[str] | None) -> list[str] | None:
    if folders is None:
        return None
    if any(not folder.strip() or "\x00" in folder for folder in folders):
        raise ValueError("Ordnernamen dürfen nicht leer sein oder NUL enthalten")
    if len(folders) != len(set(folders)):
        raise ValueError("Ordnernamen dürfen nicht doppelt vorkommen")
    return folders

ConnectionMode = Literal["ssl", "starttls", "plain"]

DraftsFolder = Annotated[str, Field(min_length=1, max_length=500, pattern=r"^[^\x00-\x1f\x7f]+$")]

class DraftSettings(ConfigModel):
    """Master switch and optional folder override; automatic writing remains opt-in."""

    enabled: bool = True
    folder: DraftsFolder | None = None

OwnAddress = Annotated[str, Field(min_length=3, max_length=254,
                                  pattern=r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$")]

# Fields of one mailbox; before 3.1 they were written directly below ``imap``.
MAILBOX_FIELDS = ("host", "port", "folders", "primary_folder", "connection_mode", "historical_start",
                  "drafts_folder")

MAX_MAILBOXES = 10

class MailboxSettings(ConfigModel):
    """One IMAP mailbox (3.1). ``id`` is stable and names its secrets ``IMAP_<id>_…``."""

    id: int = Field(ge=1, le=99)
    label: str = Field(default="Postfach", min_length=1, max_length=40, pattern=r"^[^\x00-\x1f\x7f]+$")
    enabled: bool = True
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(ge=1, le=65535)
    folders: list[str] = Field(min_length=1, max_length=100)
    primary_folder: str = "INBOX"
    connection_mode: ConnectionMode = "ssl"
    historical_start: datetime | None = None
    drafts_folder: DraftsFolder = "Drafts"
    target_profile: int = Field(default=1, ge=1, le=99)
    personal_info: str | None = Field(default=None, max_length=2000, pattern=r"^[^\x00-\x08\x0b-\x1f\x7f]*$")
    # 4.5: further own sender addresses (aliases); the IMAP user name already counts.
    own_addresses: list[OwnAddress] = Field(default_factory=list, max_length=20)
    # 4.7: which program the link to the original mail opens; "auto" follows the IMAP server.
    mail_client: Literal["auto", "apple_mail", "gmail_web", "outlook_web", "none"] = "auto"
    smart_reply: bool | None = None
    auto_draft: bool | None = None
    notifications: NotificationOverrides | None = None
    daily_briefing: bool = True
    activity_report_folder: DraftsFolder | None = None
    retention: MailboxRetention | None = None
    event_defaults: MailboxEventDefaults | None = None

    @model_validator(mode="before")
    @classmethod
    def default_primary_to_first_folder(cls, value: object) -> object:
        return _default_primary_to_first_folder(value)

    @field_validator("historical_start", mode="before")
    @classmethod
    def valid_historical_start(cls, value: object) -> datetime | None:
        return _valid_historical_start(value)

    @field_validator("folders")
    @classmethod
    def valid_folders(cls, folders: list[str]) -> list[str] | None:
        return _valid_folders(folders)

    @model_validator(mode="after")
    def primary_is_configured(self) -> MailboxSettings:
        """The primary inbox is required; every other configured folder is optional."""
        if self.primary_folder not in self.folders:
            raise ValueError("primary_folder muss in folders enthalten sein")
        return self

    @property
    def required_folders(self) -> tuple[str, ...]:
        return (self.primary_folder,)

    @property
    def optional_folders(self) -> tuple[str, ...]:
        return tuple(folder for folder in self.folders if folder != self.primary_folder)

    @property
    def secret_names(self) -> tuple[str, str]:
        return f"IMAP_{self.id}_USERNAME", f"IMAP_{self.id}_PASSWORD"

class ImapSettings(ConfigModel):
    """Shared fetch parameters and either ``mailboxes`` (3.1) or one mailbox in the format before 3.1.

    The former format keeps its exact field paths in error messages and its exact
    fingerprint; :meth:`configured_mailboxes` presents both formats uniformly.
    """

    batch_size: int = Field(default=25, ge=1, le=1000)
    global_newest_first: bool = False
    mailboxes: list[MailboxSettings] | None = Field(default=None, min_length=1)
    host: str | None = Field(default=None, min_length=1, max_length=253)
    port: int | None = Field(default=None, ge=1, le=65535)
    folders: list[str] | None = Field(default=None, min_length=1, max_length=100)
    primary_folder: str | None = None
    connection_mode: ConnectionMode | None = None
    historical_start: datetime | None = None
    drafts_folder: DraftsFolder | None = None

    @model_validator(mode="before")
    @classmethod
    def separate_formats(cls, value: object) -> object:
        # A dump of the former format carries ``mailboxes: null``; that is not the new format.
        if isinstance(value, dict) and value.get("mailboxes") is not None:
            mixed = [name for name in MAILBOX_FIELDS if value.get(name) is not None]
            if mixed:
                raise ValueError("imap.mailboxes und Postfachfelder direkt unter imap schließen sich aus: "
                                 + ", ".join(mixed))
            return value
        return _default_primary_to_first_folder(value)

    @field_validator("historical_start", mode="before")
    @classmethod
    def valid_historical_start(cls, value: object) -> datetime | None:
        return _valid_historical_start(value)

    @field_validator("folders")
    @classmethod
    def valid_folders(cls, folders: list[str] | None) -> list[str] | None:
        return _valid_folders(folders)

    @model_validator(mode="after")
    def complete_mailboxes(self) -> ImapSettings:
        if self.mailboxes is None:
            missing = [name for name in ("host", "port", "folders") if getattr(self, name) is None]
            if missing:
                raise ValueError("imap benötigt mailboxes oder " + ", ".join(missing))
            assert self.folders is not None
            if self.primary_folder not in self.folders:
                raise ValueError("primary_folder muss in folders enthalten sein")
            return self
        if len(self.mailboxes) > MAX_MAILBOXES:
            raise ValueError(f"höchstens {MAX_MAILBOXES} Postfächer werden unterstützt")
        ids = [mailbox.id for mailbox in self.mailboxes]
        if len(ids) != len(set(ids)):
            raise ValueError("Postfachnummern (id) dürfen nicht doppelt vorkommen")
        if not any(mailbox.enabled for mailbox in self.mailboxes):
            raise ValueError("mindestens ein Postfach muss aktiviert sein")
        return self

    @property
    def legacy_format(self) -> bool:
        return self.mailboxes is None

    def configured_mailboxes(self) -> list[MailboxSettings]:
        """Every configured mailbox in configuration order; the former format is mailbox 1."""
        if self.mailboxes is not None:
            return list(self.mailboxes)
        return [MailboxSettings.model_validate({
            "id": 1, **{name: getattr(self, name) for name in MAILBOX_FIELDS if getattr(self, name) is not None}})]

    def enabled_mailboxes(self) -> list[MailboxSettings]:
        return [mailbox for mailbox in self.configured_mailboxes() if mailbox.enabled]

    def mailbox(self, mailbox_id: int) -> MailboxSettings | None:
        return next((item for item in self.configured_mailboxes() if item.id == mailbox_id), None)

MAX_ISERV_ACCOUNTS = 10

class IServAccountSettings(ConfigModel):
    """An IServ parent account whose parent letters are processed as always relevant mail.

    ``id`` names its secrets ``ISERV_<id>_USERNAME``/``ISERV_<id>_PASSWORD``. The letters use the
    settings of IMAP mailbox ``mailbox`` (target profile, defaults).
    """

    id: int = Field(ge=1, le=MAX_ISERV_ACCOUNTS)
    label: str = Field(default="Elternbriefe", min_length=1, max_length=40, pattern=r"^[^\x00-\x1f\x7f]+$")
    enabled: bool = True
    server: str = Field(min_length=1, max_length=253)
    mailbox: int = Field(default=1, ge=1, le=99)
    # Older letters are not processed; without a value the mailbox's historical_start applies.
    historical_start: datetime | None = None

    @field_validator("server")
    @classmethod
    def valid_server(cls, value: str) -> str:
        """The school's HTTPS origin; a pasted link (path, query) or a bare host name is reduced to it."""
        text = value.strip()
        parts = urlsplit(text if "://" in text else "https://" + text)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
            raise ValueError("Die IServ-Adresse muss mit https:// beginnen und darf keine Zugangsdaten enthalten")
        return f"https://{parts.netloc.lower()}"

    @field_validator("historical_start", mode="before")
    @classmethod
    def valid_historical_start(cls, value: object) -> datetime | None:
        return _valid_historical_start(value)

    @property
    def secret_names(self) -> tuple[str, str]:
        return f"ISERV_{self.id}_USERNAME", f"ISERV_{self.id}_PASSWORD"

class IServSettings(ConfigModel):
    accounts: list[IServAccountSettings] = Field(default_factory=list, max_length=MAX_ISERV_ACCOUNTS)

    @field_validator("accounts")
    @classmethod
    def distinct_ids(cls, accounts: list[IServAccountSettings]) -> list[IServAccountSettings]:
        if len({account.id for account in accounts}) != len(accounts):
            raise ValueError("IServ-Konten brauchen verschiedene id")
        return accounts

    def enabled_accounts(self) -> list[IServAccountSettings]:
        return [account for account in self.accounts if account.enabled]
