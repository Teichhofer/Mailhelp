"""Shared, restart-safe IMAP APPEND for reply and briefing drafts. No SMTP capability."""
from __future__ import annotations

import imaplib
from collections.abc import Callable
from typing import Any, cast

from .draft_folders import choose_drafts_folder, listed_folders
from .imap import mailbox_argument


class ImapDraftWriter:
    @staticmethod
    def folder(connection: imaplib.IMAP4, configured: str, record: dict[str, Any]) -> str | bytes:
        conn = cast(Any, connection)
        pinned = record.get("folder") if record.get("status") == "uncertain" else None
        preferred = pinned or configured
        folder = mailbox_argument(preferred)
        status, _ = conn.select(folder, readonly=True)
        if status != "OK":
            if pinned:
                raise ValueError("Bisheriger Entwurfsordner nicht verfügbar; Schreibresultat bleibt unklar")
            chosen = choose_drafts_folder(preferred, listed_folders(connection))
            if chosen is None or chosen == preferred:
                raise ValueError("Entwurfsordner nicht verfügbar")
            folder = mailbox_argument(chosen)
            status, _ = conn.select(folder, readonly=True)
            if status != "OK":
                raise ValueError("Entwurfsordner nicht verfügbar")
            preferred = chosen
        record["folder"] = preferred
        return folder

    def append(self, connection: imaplib.IMAP4, preferred: str, message_id: str, content: bytes,
               record: dict[str, Any], checkpoint: Callable[[], None], authorize: Callable[[], bool]) -> str:
        conn = cast(Any, connection)
        folder = self.folder(connection, preferred, record)
        status, matches = conn.uid("search", None, "HEADER", "Message-ID", message_id)
        if status != "OK":
            raise ValueError("Entwurfsabgleich nicht möglich")
        if any(matches):
            record.update(status="saved", error=None)
            return "saved"
        record.update(status="uncertain", error=None)
        checkpoint()  # Folder and Message-ID are durable before any possible write.
        if not authorize():
            record.update(status="editing", error="Automatische Entwurfsablage inzwischen ausgeschaltet.")
            return "editing"
        try:
            status, _ = conn.append(folder, r"(\Draft \Seen)", None, content)
        except (OSError, EOFError, imaplib.IMAP4.abort):
            return "uncertain"
        except imaplib.IMAP4.error:
            status = "BAD"
        if status == "OK":
            record["status"] = "saved"
        else:
            record.update(status="editing", error="Der Mailserver hat das Speichern abgelehnt.")
        return cast(str, record["status"])
