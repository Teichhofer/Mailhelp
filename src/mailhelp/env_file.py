"""Write single credentials into ``.env`` without touching any other line (3.3.11).

The file keeps the small, non-expanding ``KEY=VALUE`` format read by ``config.loader._dotenv``.
Values are never returned or logged; callers only learn whether a name is set.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .storage import atomic_replace

NAME = re.compile(r"[A-Z][A-Z0-9_]{0,63}")
MAX_VALUE = 4096
# Changing it would end every web session, including the one making the change.
PROTECTED = frozenset({"MAILHELP_WEB_SECRET"})


class EnvFileConflict(RuntimeError):
    """The file changed since the page was loaded."""


def file_hash(path: Path) -> str:
    """Hash of the current content; an absent file counts as empty."""
    return hashlib.sha256(path.read_bytes() if path.exists() else b"").hexdigest()


def validate(name: str, value: str) -> None:
    if not NAME.fullmatch(name) or name in PROTECTED:
        raise ValueError("Unzulässiger Name")
    if not value or len(value) > MAX_VALUE or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("Wert leer, zu lang oder mit Steuerzeichen")


def _encoded(value: str) -> str:
    """Quote only what the reader would otherwise strip or unquote."""
    unsafe = value != value.strip() or (len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'")
    return f'"{value}"' if unsafe else value


def set_value(path: Path, name: str, value: str, expected_hash: str) -> None:
    """Replace every assignment of *name*, or append one; comments and other lines stay as they are."""
    set_values(path, {name: value}, expected_hash)


def set_values(path: Path, values: dict[str, str], expected_hash: str) -> None:
    """Validate and replace a credential pair in one atomic file write."""
    if not values:
        raise ValueError("Keine Zugangsdaten angegeben")
    for name, value in values.items():
        validate(name, value)
    if file_hash(path) != expected_hash:
        raise EnvFileConflict(".env wurde inzwischen geändert")
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    for name, value in values.items():
        assignment = f"{name}={_encoded(value)}"
        pattern = re.compile(rf"\s*{name}\s*=")
        replaced = [assignment if pattern.match(line) else line for line in lines]
        if not any(pattern.match(line) for line in lines):
            replaced.append(assignment)
        lines = replaced
    atomic_replace(path, "\n".join(lines) + "\n")


__all__ = ["EnvFileConflict", "MAX_VALUE", "PROTECTED", "file_hash", "set_value", "set_values", "validate"]
