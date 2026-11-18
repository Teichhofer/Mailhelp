"""Encrypted secrets of the central OAuth service (Planung 8.0, section 3; decision of 18.11.2026).

Refresh tokens, PKCE verifiers and the client secret are encrypted with Fernet (AES-CBC with
HMAC from the ``cryptography`` package). The key file lies outside the state directory, so a
backup of the data alone never decrypts a token. The key file may hold several keys, one per
line: the first encrypts, all decrypt, and :meth:`SecretStore.rotate` re-encrypts with the first.
"""
from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

_NAME = "secrets.json"
# File modes are enforced where the system has them (the Linux server); Windows has no group/other bits.
POSIX = os.name != "nt"


class SecretStoreError(RuntimeError):
    """The store cannot be used safely; the message never contains a secret."""


def create_key(path: Path) -> None:
    """A new key file readable only by its owner; an existing file is never overwritten."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="ascii") as stream:
        stream.write(Fernet.generate_key().decode("ascii") + "\n")


def add_key(path: Path) -> None:
    """Put a new primary key in front; the old ones keep decrypting until :meth:`rotate` ran."""
    keys = path.read_text(encoding="ascii").split()
    _write(path, "\n".join([Fernet.generate_key().decode("ascii"), *keys]) + "\n")


def _write(path: Path, text: str) -> None:
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
        if POSIX:
            os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


class SecretStore:
    def __init__(self, directory: Path, key_file: Path) -> None:
        directory, key_file = directory.resolve(), key_file.resolve()
        if key_file.is_relative_to(directory):
            raise SecretStoreError("Der Schlüssel darf nicht im Zustandsverzeichnis liegen")
        if not key_file.is_file():
            raise SecretStoreError("Schlüsseldatei fehlt")
        if POSIX and stat.S_IMODE(key_file.stat().st_mode) & 0o077:
            raise SecretStoreError("Schlüsseldatei ist für andere lesbar")
        try:
            self._fernet = MultiFernet([Fernet(line.encode("ascii"))
                                        for line in key_file.read_text(encoding="ascii").split()])
        except (ValueError, UnicodeError):
            raise SecretStoreError("Schlüsseldatei ist ungültig") from None
        self.path = directory / _NAME
        directory.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("schema_version") != 1 or not isinstance(data.get("secrets"), dict):
                raise ValueError("schema")
            return {str(name): str(value) for name, value in data["secrets"].items()}
        except (ValueError, AttributeError):
            raise SecretStoreError("Geheimnisdatei ist beschädigt") from None

    def _save(self, secrets: dict[str, str]) -> None:
        _write(self.path, json.dumps({"schema_version": 1, "secrets": dict(sorted(secrets.items()))}, indent=1)
               + "\n")

    def put(self, name: str, value: str) -> None:
        secrets = self._load()
        secrets[name] = self._fernet.encrypt(value.encode("utf-8")).decode("ascii")
        self._save(secrets)

    def get(self, name: str) -> str | None:
        token = self._load().get(name)
        if token is None:
            return None
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except InvalidToken:
            raise SecretStoreError("Geheimnis lässt sich mit keinem Schlüssel entschlüsseln") from None

    def delete(self, name: str) -> bool:
        secrets = self._load()
        if secrets.pop(name, None) is None:
            return False
        self._save(secrets)
        return True

    def names(self) -> list[str]:
        return sorted(self._load())

    def rotate(self) -> int:
        """Re-encrypt every secret with the primary key; returns how many were rewritten."""
        secrets = self._load()
        try:
            rotated = {name: self._fernet.rotate(token.encode("ascii")).decode("ascii")
                       for name, token in secrets.items()}
        except InvalidToken:
            raise SecretStoreError("Geheimnis lässt sich mit keinem Schlüssel entschlüsseln") from None
        self._save(rotated)
        return len(rotated)


__all__ = ["SecretStore", "SecretStoreError", "add_key", "create_key"]
