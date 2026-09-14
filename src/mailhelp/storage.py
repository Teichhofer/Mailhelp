"""Atomare, menschenlesbare JSON-Ablage mit Einzelinstanz-Sperre."""
from __future__ import annotations
import json, os
import re
from pathlib import Path
from typing import Any


class CorruptState(RuntimeError): pass
class AlreadyRunning(RuntimeError): pass


class JsonStore:
    def __init__(self, directory: Path): self.directory, self.lock = directory, None

    def __enter__(self) -> "JsonStore":
        self.directory.mkdir(parents=True, exist_ok=True); path = self.directory / ".lock"
        try: self.lock = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc: raise AlreadyRunning(f"Datenverzeichnis wird bereits verwendet: {self.directory}") from exc
        os.write(self.lock, str(os.getpid()).encode()); return self

    def __exit__(self, *_: object) -> None:
        if self.lock is not None: os.close(self.lock); self.lock = None
        (self.directory / ".lock").unlink(missing_ok=True)

    def load(self, name: str, default: Any = None) -> Any:
        self._validate_name(name)
        path = self.directory / f"{name}.json"
        if not path.exists(): return default
        try:
            with path.open(encoding="utf-8") as stream: return json.load(stream)
        except (OSError, json.JSONDecodeError) as exc:
            quarantine = path.with_suffix(".corrupt"); os.replace(path, quarantine)
            raise CorruptState(f"Beschädigter Zustand isoliert: {quarantine.name}") from exc

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
