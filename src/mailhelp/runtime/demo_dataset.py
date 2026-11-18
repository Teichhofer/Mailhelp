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
from datetime import datetime
from importlib.resources import files
from pathlib import Path, PurePosixPath
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ..domain.mail import MailState
from ..i18n import Locale

DATASET = "standard-v1"
DATASETS = {Locale.DE: DATASET, Locale.EN: "standard-en-v1"}
MAIL_COUNT = 30
# A prepared corpus contains processing results, never sessions, credentials or queued deliveries.
STATE_FILE = re.compile(
    r"(?:mail-[0-9a-f]{24}|analysis-[0-9a-f]{24}|history-[0-9a-f]{24}|"
    r"proposal-[0-9a-f]{24}-p_[0-9a-f]{24}(?:-v[1-9][0-9]*)?|"
    r"processing-topics-[0-9a-f]{64}|duplicate-index)\.json"
)
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
    locale: Locale = Locale.DE
    schema_version: int
    reference_time: str
    timezone: str
    source_commit: str
    analysis_fingerprint: str
    model: str
    mails: list[DemoMailEntry]
    files: dict[str, str]
    # The recorded results of the prepared answers (answers.json).
    answers: str = Field(pattern=_DIGEST)

    @model_validator(mode="after")
    def complete_and_contained(self) -> DemoManifest:
        if (
            self.dataset != DATASETS[self.locale]
            or self.schema_version not in {1, 2}
            or self.schema_version == 1
            and self.locale != Locale.DE
            or self.schema_version == 2
            and "locale" not in self.model_fields_set
        ):
            raise ValueError("unbekannte Version des Beispielbestands")
        if datetime.fromisoformat(self.reference_time).tzinfo is None or self.timezone != "Europe/Berlin":
            raise ValueError("ungültige Referenzzeit oder Zeitzone")
        ZoneInfo(self.timezone)
        if self.schema_version == 2 and (
            re.fullmatch(r"[0-9a-f]{7,40}", self.source_commit) is None
            or re.fullmatch(_DIGEST, self.analysis_fingerprint) is None
            or not self.model.strip()
        ):
            raise ValueError("unvollständige Erzeugungsmetadaten")
        if len(self.mails) != MAIL_COUNT or len({mail.message_id for mail in self.mails}) != MAIL_COUNT \
                or len({mail.name for mail in self.mails}) != MAIL_COUNT:
            raise ValueError(f"der Beispielbestand braucht genau {MAIL_COUNT} eindeutige Mails")
        if len({name.casefold() for name in self.files}) != len(self.files):
            raise ValueError("kollidierende Dateinamen im Beispielbestand")
        for name, digest in self.files.items():
            path = PurePosixPath(name)
            if (
                path.is_absolute()
                or ".." in path.parts
                or path.as_posix() != name
                or not re.fullmatch(r"[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_-]+)*\.json", name)
                or not re.fullmatch(_DIGEST, digest)
            ):
                raise ValueError(f"unzulässiger Eintrag im Beispielbestand: {name}")
        return self


def packaged(locale: Locale = Locale.DE) -> Path:
    return Path(str(files("mailhelp").joinpath("defaults", "demo", DATASETS[locale])))


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(directory: Path) -> DemoManifest:
    """The manifest of *directory* after every listed file matched its digest."""
    if directory.is_symlink() or directory.is_junction():
        raise DemoDatasetError("Der Beispielbestand enthält eine symbolische Verknüpfung.")
    try:
        manifest = DemoManifest.model_validate(json.loads((directory / "manifest.json").read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError, ValueError, ValidationError) as exc:
        raise DemoDatasetError(f"Der Beispielbestand in {directory} ist nicht lesbar oder unvollständig.") from exc
    expected = {f"mails/{mail.name}.eml": mail.sha256 for mail in manifest.mails}
    expected.update({f"state/{name}": digest for name, digest in manifest.files.items()})
    expected["answers.json"] = manifest.answers
    actual = set()
    for path in directory.rglob("*"):
        if path.is_symlink() or path.is_junction():
            raise DemoDatasetError("Der Beispielbestand enthält eine symbolische Verknüpfung.")
        if path.is_file():
            actual.add(path.relative_to(directory).as_posix())
    if directory.is_symlink() or actual - {*expected, "manifest.json"}:
        raise DemoDatasetError("Der Beispielbestand enthält unerwartete oder fehlende Dateien.")
    for name, digest in expected.items():
        path = directory / name
        if not path.is_file() or _digest(path) != digest:
            raise DemoDatasetError(f"Der Beispielbestand ist beschädigt: {name}")
    if manifest.schema_version == 2:
        _references(directory, manifest)
    return manifest


def _references(directory: Path, manifest: DemoManifest) -> None:
    """Check the graph as well as bytes: originals, states and proposal snapshots agree."""
    try:
        if any(STATE_FILE.fullmatch(name) is None for name in manifest.files):
            raise ValueError("unexpected runtime state")
        states = {
            name: MailState.model_validate_json((directory / "state" / name).read_bytes())
            for name in manifest.files
            if name.startswith("mail-")
        }
        if len(states) != MAIL_COUNT or {
            state.mail["headers"]["message_id"] for state in states.values() if state.mail is not None
        } != {mail.message_id for mail in manifest.mails}:
            raise ValueError("mail graph mismatch")
        snapshots = set()
        for filename, state in states.items():
            if f"mail-{state.id}.json" != filename:
                raise ValueError("mail identity mismatch")
            for proposal in state.proposals:
                if proposal.source_mail_id != state.id:
                    raise ValueError("foreign proposal")
                stem = f"proposal-{state.id}-{proposal.id}"
                for name in (f"{stem}.json", f"{stem}-v{proposal.version}.json"):
                    snapshots.add(name)
                    raw = json.loads((directory / "state" / name).read_text(encoding="utf-8"))
                    if raw != proposal.model_dump(mode="json"):
                        raise ValueError("proposal snapshot mismatch")
        if snapshots != {name for name in manifest.files if name.startswith("proposal-")}:
            raise ValueError("orphan proposal")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise DemoDatasetError("Der Beispielbestand enthält widersprüchliche Referenzen.") from exc


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
