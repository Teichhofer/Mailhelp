"""7.1 (D3): the packaged demo dataset – verified before every use and copied atomically per visitor.

The dataset is an immutable template: ``manifest.json`` names every original mail and every state file
with its SHA-256 digest. Loading checks schema, names and digests; a damaged or incomplete dataset is
refused with a readable message and never replaced by a real analysis.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from importlib.resources import files
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

DATASET = "standard-v1"
MAIL_COUNT = 30
_DIGEST = r"^[0-9a-f]{64}$"


class DemoDatasetError(ValueError):
    """The prepared dataset is missing, damaged or not the expected version."""


class DemoMailEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,80}$")
    message_id: str = Field(min_length=3, max_length=200)
    sha256: str = Field(pattern=_DIGEST)


class DemoManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    dataset: str
    schema_version: int
    reference_time: str
    timezone: str
    source_commit: str
    analysis_fingerprint: str
    model: str
    mails: list[DemoMailEntry]
    files: dict[str, str]

    @model_validator(mode="after")
    def complete_and_contained(self) -> DemoManifest:
        if self.dataset != DATASET or self.schema_version != 1:
            raise ValueError("unbekannte Version des Beispielbestands")
        if len(self.mails) != MAIL_COUNT or len({mail.message_id for mail in self.mails}) != MAIL_COUNT \
                or len({mail.name for mail in self.mails}) != MAIL_COUNT:
            raise ValueError(f"der Beispielbestand braucht genau {MAIL_COUNT} eindeutige Mails")
        for name, digest in self.files.items():
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or not name.endswith(".json") \
                    or not re.fullmatch(_DIGEST, digest):
                raise ValueError(f"unzulässiger Eintrag im Beispielbestand: {name}")
        return self


def packaged() -> Path:
    return Path(str(files("mailhelp").joinpath("defaults", "demo", DATASET)))


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(directory: Path) -> DemoManifest:
    """The manifest of *directory* after every listed file matched its digest."""
    try:
        manifest = DemoManifest.model_validate(json.loads((directory / "manifest.json").read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError, ValueError, ValidationError) as exc:
        raise DemoDatasetError(f"Der Beispielbestand in {directory} ist nicht lesbar oder unvollständig.") from exc
    expected = {f"mails/{mail.name}.eml": mail.sha256 for mail in manifest.mails}
    expected.update({f"state/{name}": digest for name, digest in manifest.files.items()})
    for name, digest in expected.items():
        path = directory / name
        if not path.is_file() or _digest(path) != digest:
            raise DemoDatasetError(f"Der Beispielbestand ist beschädigt: {name}")
    return manifest


def install(source: Path, target: Path) -> DemoManifest:
    """Copy the verified state files to the store directory *target*: complete or not there at all."""
    manifest = verify(source)
    if target.exists():
        raise DemoDatasetError(f"{target} ist bereits belegt.")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(f".{target.name}.{uuid.uuid4().hex}.neu")
    try:
        shutil.copytree(source / "state", staging)
        for name, digest in manifest.files.items():
            if _digest(staging / name) != digest:
                raise DemoDatasetError(f"Die Kopie des Beispielbestands ist beschädigt: {name}")
        os.replace(staging, target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return manifest
