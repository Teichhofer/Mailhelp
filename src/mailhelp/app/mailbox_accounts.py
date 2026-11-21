"""Compose mailbox OAuth with the existing authenticated configuration transactions."""
from __future__ import annotations

from contextlib import closing
from typing import Any

from ..config import ImapCredentials, MailboxSettings, Settings
from ..config.configuration import file_hash
from ..config.env_file import file_hash as env_hash
from ..external.hosted_oauth import cached_client
from ..mailbox.imap import ImapReader, reader_arguments
from ..mailbox.mailbox_activation import ReconnectActivation
from ..web.mailbox_oauth_site import MailboxOAuthContext, MailboxOAuthSite


def probe(settings: Settings, mailbox: MailboxSettings, username: str) -> list[tuple[str, str | None]]:
    address, options = reader_arguments(mailbox, ImapCredentials(username=username, password=""), settings.hosted_auth)
    with closing(ImapReader(*address, settings.timeouts.imap.timeout_seconds, **options)) as reader:
        folders = reader.list_folders()
        reader.check_access([next((folder.name for folder in folders if folder.role == "inbox"), "INBOX")])
        return [(folder.name, folder.role) for folder in folders]


def attach_initial_mailbox(site: Any, setup: Any, store: Any) -> None:
    def settings() -> Settings:
        return Settings.model_validate(setup.state().config)

    def read(number: int) -> tuple[MailboxSettings, int, str]:
        state = setup.state()
        if number != 1 or state.status != "draft" or state.completed_step < 1:
            raise ValueError("initial_mailbox")
        mailbox = settings().imap.mailbox(number)
        assert mailbox is not None
        return mailbox, state.version, state.env_revision

    def save(actor: str, mailbox: MailboxSettings, username: str, version: int, key: str, revision: str) -> None:
        if read(mailbox.id)[2] != revision:
            raise ValueError("credentials_changed")
        setup.save(actor, {"step": "2", "version": str(version), "key": key, "IMAP_USERNAME": username,
            **{"imap." + field: str(getattr(mailbox, field)) for field in (
                "host", "port", "connection_mode", "primary_folder", "drafts_folder",
                "auth_method", "oauth_connection")}})

    MailboxOAuthSite(site, store, cached_client(lambda: settings().hosted_auth),
        MailboxOAuthContext(read, save, lambda mailbox, username: probe(settings(), mailbox, username)),
        "/einrichtung/start")


def attach_running_mailbox(app: Any, site: Any, saved: Any) -> None:
    runtime = site.setup_page.runtime
    directory = app.configuration.directory

    def read(number: int) -> tuple[MailboxSettings, int, str]:
        cfg = saved()
        state = runtime.setup.state()
        if state.kind != "settings" or any(key.startswith("imap") for key in state.patch):
            raise ValueError("mailbox_draft_pending")
        if not 1 <= number <= 99:
            raise ValueError("mailbox")
        mailbox = cfg.imap.mailbox(number)
        if mailbox is None:
            if len(cfg.imap.configured_mailboxes()) >= 10:
                raise ValueError("mailbox_limit")
            mailbox = MailboxSettings(id=number, host="imap.example.invalid", port=993, folders=["INBOX"])
        revision = file_hash(directory / "config.yaml") + ":" + env_hash(directory / ".env")
        return mailbox, state.version, revision

    def save(actor: str, mailbox: MailboxSettings, username: str, version: int, key: str, revision: str) -> None:
        config_revision, env_revision = revision.split(":")
        ReconnectActivation(runtime).activate(actor, version, key, config_revision, env_revision, mailbox, username, "")

    MailboxOAuthSite(site, app.store, cached_client(lambda: saved().hosted_auth),
        MailboxOAuthContext(read, save, lambda mailbox, username: probe(saved(), mailbox, username)),
        "/einstellungen/postfaecher")
