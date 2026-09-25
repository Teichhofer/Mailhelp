"""Atomare, menschenlesbare JSON-Ablage mit Einzelinstanz-Sperre."""
from __future__ import annotations
import errno
import json, os
import re
from pathlib import Path
from typing import Any
from pydantic import BaseModel, ValidationError

from .persistence.migrations import migrate_document


class CorruptState(RuntimeError): pass
class AlreadyRunning(RuntimeError): pass


def mail_state_names(store: "JsonStore") -> list[str]:
    """Return only per-mail state names, excluding the ``mail-run-*`` queue."""
    return [name for name in store.names("mail-")
            if not name.startswith("mail-run-")]


class JsonStore:
    def __init__(self, directory: Path): self.directory, self.lock = directory, None

    def __enter__(self) -> "JsonStore":
        self.directory.mkdir(parents=True, exist_ok=True); path = self.directory / ".lock"
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            self._acquire_lock(descriptor)
        except OSError as exc:
            os.close(descriptor)
            if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise AlreadyRunning(f"Datenverzeichnis wird bereits verwendet: {self.directory}") from exc
            raise
        self.lock = descriptor
        # This is diagnostic information only.  The kernel-held lock above, not
        # the PID stored here, determines whether another instance is running.
        try:
            metadata = json.dumps({"pid": os.getpid()}).encode("ascii")
            os.lseek(descriptor, 0, os.SEEK_SET)
            os.write(descriptor, metadata)
            os.ftruncate(descriptor, len(metadata))
            os.fsync(descriptor)
        except BaseException:
            os.close(descriptor)
            self.lock = None
            raise
        return self

    def __exit__(self, *_: object) -> None:
        if self.lock is not None:
            os.close(self.lock)
            self.lock = None

    @staticmethod
    def _acquire_lock(descriptor: int) -> None:
        """Acquire a process-bound, non-blocking lock on an open lock file."""
        if os.name == "nt":
            import msvcrt

            # Windows byte-range locks require a byte to exist in the file.
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\0")
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def load(self, name: str, default: Any = None) -> Any:
        self._validate_name(name)
        path = self.directory / f"{name}.json"
        if not path.exists(): return default
        try:
            with path.open(encoding="utf-8") as stream: return json.load(stream)
        except (OSError, json.JSONDecodeError) as exc:
            quarantine = path.with_suffix(".corrupt"); os.replace(path, quarantine)
            raise CorruptState(f"Beschädigter Zustand isoliert: {quarantine.name}") from exc

    def load_model(self, name: str, model: type[BaseModel], default: BaseModel | None = None) -> BaseModel | None:
        """Load and validate a state object, quarantining invalid schemas too."""
        value = self.load(name, None)
        if value is None:
            return default
        migrated = migrate_document(model.__name__, value)
        try:
            result = model.model_validate(value)
        except ValidationError as exc:
            path = self.directory / f"{name}.json"
            quarantine = path.with_suffix(".invalid")
            os.replace(path, quarantine)
            locations = [".".join(str(part) for part in error["loc"]) or "<root>" for error in exc.errors(include_input=False)]
            raise CorruptState(f"Schemawidriger Zustand isoliert: {quarantine.name}; Schlüsselpfad: {', '.join(locations)}") from exc
        if migrated:
            self.save(name, result.model_dump(mode="json"))
        return result

    def save(self, name: str, value: Any) -> None:
        self._validate_name(name)
        path = self.directory / f"{name}.json"; temporary = path.with_suffix(".tmp")
        self.directory.mkdir(parents=True, exist_ok=True)
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True); stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
        # Make the directory entry durable as well as the file contents.
        if os.name != "nt":
            descriptor = os.open(self.directory, os.O_RDONLY)
            try: os.fsync(descriptor)
            finally: os.close(descriptor)

    def names(self, prefix: str = "") -> list[str]:
        """Return stable state names without exposing temporary/corrupt files."""
        return sorted(path.stem for path in self.directory.glob(f"{prefix}*.json") if path.is_file())

    @staticmethod
    def _validate_name(name: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            raise ValueError("Ungültiger Zustandsname")
