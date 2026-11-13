"""Atomic, bounded admission without any application mutex.

Immutable receipts are published with an exclusive hard link. Incoming files are
published with replace. A committed receipt also recovers a crash before the
incoming publication. Fixed capacity tickets remain occupied until execution starts.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import tempfile
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..configuration import AdminCommand
from .commands import ReviewCommand
from .inbox import (
    FINISHED,
    CommandConflict,
    CommandEntry,
    CommandInboxFull,
    CommandStatus,
    command_payload,
    entry_payload,
)
from .results import ResultStatus

SUCCESS = {ResultStatus.DONE, ResultStatus.WRITTEN}


class IncomingRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    key_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    ticket: str = Field(pattern=r"^[a-f0-9]{32}$")
    slot: int = Field(ge=0)
    entry: CommandEntry

    @model_validator(mode="after")
    def bound(self) -> IncomingRecord:
        digest = key_hash(self.entry.command.idempotency_key)
        if self.key_hash != digest or self.entry.id != digest[:32]:
            raise ValueError("Eingang und Idempotenzschlüssel passen nicht zusammen")
        if self.entry.received_at.utcoffset() is None or self.entry.command.source.value != "web":
            raise ValueError("Web-Eingang benötigt eine eindeutige Annahmezeit und Web-Quelle")
        return self


def key_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def requires_ack(entry: CommandEntry) -> bool:
    return entry.result is not None and entry.result.status not in SUCCESS and not entry.acknowledged


def read_file(path: Path) -> bytes | None:
    """6.1.5: web threads read receipts without the store lock while the main thread replaces them.

    On Windows opening a file at the moment it is replaced fails with PermissionError; like
    ``replace_file`` the read is retried a few times. A missing file is None.
    """
    for attempt in range(3):
        try:
            return path.read_bytes()
        except FileNotFoundError:
            return None
        except PermissionError:
            time.sleep(0.005 * (2 ** attempt))
    try:
        return path.read_bytes()  # The fourth and last attempt reports a persistent block.
    except FileNotFoundError:
        return None


def replace_file(source: Path, target: Path) -> None:
    """Windows readers/indexers can briefly prevent replacement; retries are bounded."""
    for attempt in range(3):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            time.sleep(0.005 * (2 ** attempt))
    os.replace(source, target)  # The fourth and last attempt reports a persistent block.


def atomic_json(path: Path, value: dict[str, Any], *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".admission-", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if exclusive:
            os.link(temporary, path)  # Compare-and-set: never overwrite an acknowledged intent.
        else:
            replace_file(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def record_payload(record: IncomingRecord) -> dict[str, Any]:
    value = record.model_dump(mode="json")
    value["entry"] = entry_payload(record.entry)
    return value


class IncomingCommands:
    def __init__(self, directory: Path, limit: Callable[[], int], clock: Callable[[], datetime]):
        self.directory, self.limit, self.clock = directory / "commands", limit, clock
        self.problems: list[str] = []
        self.legacy: dict[str, tuple[str, str, int]] = {}

    def _path(self, section: str, name: str) -> Path:
        return self.directory / section / f"{name}.json"

    def read(self, path: Path) -> IncomingRecord | None:
        value = read_file(path)
        if value is None:
            return None
        record = IncomingRecord.model_validate_json(value)
        if path.parent.name == "incoming" and path.stem != record.key_hash:
            raise ValueError("Falscher Name einer Eingabedatei")
        if path.parent.name == "receipts" and path.stem != record.entry.id:
            raise ValueError("Falscher Name einer Eingangsquittung")
        return record

    def receipt(self, entry_id: str) -> IncomingRecord | None:
        if not re.fullmatch(r"[a-f0-9]{32}", entry_id):
            return None
        return self.read(self._path("receipts", entry_id))

    def existing(self, command: ReviewCommand | AdminCommand) -> CommandEntry | None:
        record = self.receipt(key_hash(command.idempotency_key)[:32])
        if record is None:
            return None
        if command_payload(record.entry.command) != command_payload(command):
            raise CommandConflict("Idempotenzschlüssel gehört zu einem anderen Befehl")
        return self.decorate(record.entry)

    def _reserve(self, digest: str, ticket: str) -> int:
        staged = self.directory / "capacity" / f".ticket-{ticket}.tmp"
        atomic_json(staged, {"key_hash": digest, "ticket": ticket})
        try:
            for slot in range(self.limit()):
                try:
                    os.link(staged, self._path("capacity", str(slot)))
                    return slot
                except FileExistsError:
                    continue
            raise CommandInboxFull("Zu viele wartende Befehle")
        finally:
            staged.unlink(missing_ok=True)

    def release(self, record: IncomingRecord) -> None:
        self.release_ticket(record.key_hash, record.ticket, record.slot)

    def release_ticket(self, digest: str, ticket: str, slot: int) -> None:
        path = self._path("capacity", str(slot))
        try:
            value = json.loads(path.read_bytes())
        except FileNotFoundError:
            return
        if value == {"key_hash": digest, "ticket": ticket}:
            path.unlink(missing_ok=True)

    def accept(self, command: ReviewCommand | AdminCommand) -> tuple[CommandEntry, bool]:
        existing = self.existing(command)
        if existing is not None:
            return existing, False
        digest, ticket = key_hash(command.idempotency_key), secrets.token_hex(16)
        record = IncomingRecord(key_hash=digest, ticket=ticket, slot=0,
                                entry=CommandEntry(id=digest[:32], command=command, received_at=self.clock()))
        record.slot = self._reserve(digest, ticket)
        committed = False
        try:
            try:
                atomic_json(self._path("receipts", record.entry.id), record_payload(record), exclusive=True)
                committed = True
            except FileExistsError:
                existing = self.existing(command)
                assert existing is not None
                return existing, False
            try:
                atomic_json(self._path("incoming", digest), record_payload(record))
            except OSError:
                # The receipt already durably owns the intent. The operator also scans receipts.
                pass
            return record.entry, True
        finally:
            if not committed:
                self.release(record)

    def records(self, *, quarantine: bool = True) -> list[IncomingRecord]:
        result = []
        for path in sorted((self.directory / "receipts").glob("*.json")):
            if quarantine:
                record = self.checked(path)
            else:
                try:
                    record = self.read(path)
                except ValueError:
                    continue  # Only the operator isolates and reports damage.
            if record is not None:
                result.append(record)
        return sorted(result, key=lambda record: (record.entry.received_at, record.entry.id))

    def checked(self, path: Path) -> IncomingRecord | None:
        try:
            return self.read(path)
        except ValueError:
            self.isolate(path)
            return None

    def isolate(self, path: Path) -> None:
        name = f"{path.parent.name}-{path.stem}-{secrets.token_hex(8)}.invalid"
        destination = self.directory / "quarantine" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        replace_file(path, destination)
        self.problems.append("Beschädigte oder widersprüchliche Eingabedatei wurde isoliert; bitte prüfen lassen.")

    def repair(self) -> None:
        """A second durable copy recovers interrupted publication or damaged receipts."""
        for path in sorted((self.directory / "incoming").glob("*.json")):
            record = self.checked(path)
            if record is None:
                continue
            previous = self.checked(self._path("receipts", record.entry.id))
            if (previous is not None
                    and command_payload(previous.entry.command) != command_payload(record.entry.command)):
                self.isolate(path)
            elif previous is None:
                try:
                    atomic_json(self._path("receipts", record.entry.id), record_payload(record), exclusive=True)
                except FileExistsError:
                    pass  # Another producer has already committed the same identifier.

    def publish(self, entry: CommandEntry) -> None:
        record = self.receipt(entry.id)
        if record is None:
            legacy = self.legacy.pop(entry.id, None)
            if legacy is not None and entry.status != CommandStatus.QUEUED:
                self.release_ticket(*legacy)
            elif legacy is not None:
                self.legacy[entry.id] = legacy
            return
        if command_payload(record.entry.command) != command_payload(entry.command):
            raise CommandConflict("Quittung und übernommener Befehl widersprechen sich")
        record.entry = entry
        atomic_json(self._path("receipts", entry.id), record_payload(record))
        if entry.status != CommandStatus.QUEUED:
            self.release(record)

    def remove_incoming(self, record: IncomingRecord) -> None:
        self._path("incoming", record.key_hash).unlink(missing_ok=True)

    def forget(self, entry: CommandEntry) -> None:
        record = self.receipt(entry.id)
        if record is not None:
            self.remove_incoming(record)
            self.release(record)
            self._path("receipts", entry.id).unlink(missing_ok=True)
        self._path("acknowledged", entry.id).unlink(missing_ok=True)

    def decorate(self, entry: CommandEntry) -> CommandEntry:
        acknowledged = self._path("acknowledged", entry.id).is_file()
        return entry.model_copy(update={"acknowledged": True}) if acknowledged else entry

    def acknowledge(self, entry: CommandEntry, actor: str) -> None:
        atomic_json(self._path("acknowledged", entry.id),
                    {"id": entry.id, "actor": actor, "at": self.clock().isoformat()})

    def initialize(self, entries: list[CommandEntry]) -> None:
        """Before the web server starts, rebuild capacity after interrupted admission."""
        for section in ("capacity", "incoming", "receipts"):
            for pattern in (".admission-*.tmp", ".ticket-*.tmp"):
                for temporary in (self.directory / section).glob(pattern):
                    temporary.unlink()
        self.repair()
        records = self.records()
        queued = {entry.command.idempotency_key for entry in entries if entry.status == CommandStatus.QUEUED}
        queued.update(record.entry.command.idempotency_key for record in records
                      if record.entry.status == CommandStatus.QUEUED and not any(
                          entry.id == record.entry.id and entry.status in FINISHED | {CommandStatus.RUNNING}
                          for entry in entries))
        if len(queued) > self.limit():
            raise CommandInboxFull("Gespeicherter Eingang überschreitet die Kapazität")
        for path in (self.directory / "capacity").glob("*.json"):
            path.unlink()
        for key in sorted(queued):
            digest = key_hash(key)
            previous = next((record for record in records if record.key_hash == digest), None)
            ticket = previous.ticket if previous else secrets.token_hex(16)
            slot = self._reserve(digest, ticket)
            if previous is not None:
                previous.slot = slot
                atomic_json(self._path("receipts", previous.entry.id), record_payload(previous))
            else:
                entry = next(item for item in entries if item.command.idempotency_key == key)
                self.legacy[entry.id] = (digest, ticket, slot)

