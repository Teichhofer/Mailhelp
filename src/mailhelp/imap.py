"""Schreibfreier IMAP-Adapter (BODY.PEEK verändert \\Seen nicht)."""
from __future__ import annotations
import imaplib
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class FetchedMail:
    folder: str
    uidvalidity: int
    uid: int
    raw: bytes


class ImapReader:
    def __init__(self, host: str, port: int, username: str, password: str, timeout: float = 30, factory: Callable[..., imaplib.IMAP4] = imaplib.IMAP4_SSL):
        self.connection = factory(host, port, timeout=timeout)
        self.last_uidvalidity: int | None = None
        try:
            self.connection.login(username, password)
        except BaseException:
            self.connection.logout()
            raise

    def fetch_since(self, folder: str, after_uid: int = 0, expected_uidvalidity: int | None = None) -> list[FetchedMail]:
        status, data = self.connection.select(folder, readonly=True)
        if status != "OK": raise RuntimeError(f"IMAP-Ordner nicht lesbar: {folder}")
        status, validity = self.connection.response("UIDVALIDITY")
        if status != "UIDVALIDITY" or not validity: raise RuntimeError("IMAP lieferte keine UIDVALIDITY")
        uidvalidity = int(validity[0]); self.last_uidvalidity = uidvalidity
        if expected_uidvalidity != uidvalidity:
            after_uid = 0
        status, matches = self.connection.uid("search", None, f"UID {after_uid + 1}:*")
        if status != "OK": raise RuntimeError("IMAP-Suche fehlgeschlagen")
        result = []
        for token in matches[0].split():
            uid = int(token); status, body = self.connection.uid("fetch", token, "(BODY.PEEK[])")
            if status != "OK" or not body or not isinstance(body[0], tuple): raise RuntimeError(f"IMAP-Abruf fehlgeschlagen: UID {uid}")
            result.append(FetchedMail(folder, uidvalidity, uid, body[0][1]))
        return result

    def close(self) -> None:
        self.connection.logout()
