"""Private raster previews and original documents, independent of OCR and external services.

Originals (2.3) are kept only for an allow-list of document and image types,
checked by file extension *and* content signature.  Their metadata lives in a
separate manifest, so the prepared mail that the analysis sends stays unchanged.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import shutil
import unicodedata
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Any

from PIL import Image

from .config import OriginalAttachmentSettings
from .mime import attachment_parts
from .storage import StateStore, atomic_replace
from .vision import encode, is_image, open_image

ZIP, OLE = b"PK\x03\x04", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _text(data: bytes) -> bool:
    return b"\x00" not in data[:65536]


def _heic(data: bytes) -> bool:
    return data[4:8] == b"ftyp" and data[8:12] in {b"heic", b"heix", b"mif1", b"msf1"}


# Extension → (served content type, signature check).  Anything else is never stored.
ORIGINAL_TYPES: dict[str, tuple[str, Any]] = {
    "pdf": ("application/pdf", lambda data: data.startswith(b"%PDF-")),
    "doc": ("application/msword", lambda data: data.startswith(OLE)),
    "xls": ("application/vnd.ms-excel", lambda data: data.startswith(OLE)),
    "ppt": ("application/vnd.ms-powerpoint", lambda data: data.startswith(OLE)),
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document",
             lambda data: data.startswith(ZIP)),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", lambda data: data.startswith(ZIP)),
    "pptx": ("application/vnd.openxmlformats-officedocument.presentationml.presentation",
             lambda data: data.startswith(ZIP)),
    "odt": ("application/vnd.oasis.opendocument.text", lambda data: data.startswith(ZIP)),
    "ods": ("application/vnd.oasis.opendocument.spreadsheet", lambda data: data.startswith(ZIP)),
    "odp": ("application/vnd.oasis.opendocument.presentation", lambda data: data.startswith(ZIP)),
    "rtf": ("application/rtf", lambda data: data.startswith(b"{\\rtf")),
    "txt": ("text/plain; charset=utf-8", _text),
    "csv": ("text/csv; charset=utf-8", _text),
    "ics": ("text/calendar; charset=utf-8", _text),
    "jpg": ("image/jpeg", lambda data: data.startswith(b"\xff\xd8\xff")),
    "jpeg": ("image/jpeg", lambda data: data.startswith(b"\xff\xd8\xff")),
    "png": ("image/png", lambda data: data.startswith(b"\x89PNG\r\n\x1a\n")),
    "gif": ("image/gif", lambda data: data.startswith(b"GIF8")),
    "webp": ("image/webp", lambda data: data[:4] == b"RIFF" and data[8:12] == b"WEBP"),
    "heic": ("image/heic", _heic),
}


def original_type(filename: str, data: bytes) -> str | None:
    """The served content type of an allowed original, or None."""
    extension = filename.rsplit(".", 1)[-1].casefold() if "." in filename else ""
    known = ORIGINAL_TYPES.get(extension)
    return known[0] if known is not None and data and known[1](data) else None


def download_name(filename: str, index: int) -> tuple[str, str]:
    """(UTF-8 name, ASCII fallback) without folders, control characters or quoting characters."""
    base = unicodedata.normalize("NFC", filename.replace("\\", "/").rsplit("/", 1)[-1])
    cleaned = "".join(char for char in base if unicodedata.category(char)[0] != "C"
                      and char not in '"*:<>?|;')[:150].strip(" .") or f"anhang-{index}"
    plain = unicodedata.normalize("NFKD", cleaned).encode("ascii", "ignore").decode()
    return cleaned, re.sub(r"[^A-Za-z0-9._-]+", "_", plain).strip("._") or f"anhang-{index}"


@dataclass(frozen=True)
class OriginalFile:
    index: int
    filename: str
    content_type: str
    size_bytes: int
    sha256: str


class AttachmentCache:
    def __init__(self, store: StateStore) -> None:
        self.root = store.directory / "attachments"

    def directory(self, mail_id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{24}", mail_id):
            raise ValueError("Ungültige Mail-ID")
        path = self.root / mail_id
        if path.resolve().parent != self.root.resolve():
            raise ValueError("Ungültiger Anhangspfad")
        return path

    def prepare(self, mail_id: str, raw: bytes, attachments: list[dict[str, Any]],
                originals: OriginalAttachmentSettings | None = None) -> None:
        parts = list(attachment_parts(BytesParser(policy=policy.default).parsebytes(raw)))
        if len(parts) != len(attachments):
            return
        kept: dict[str, dict[str, Any]] = {}
        for index, ((name, kind, data), attachment) in enumerate(zip(parts, attachments, strict=False)):
            if originals is not None and originals.store_originals:
                self._keep_original(mail_id, index, name, data, originals, kept)
            self._preview(mail_id, index, name, kind, data, attachment)
        if kept:
            atomic_replace(self.directory(mail_id) / "originals.json",
                           json.dumps({"schema_version": 1, "files": kept}, ensure_ascii=False, indent=2) + "\n")

    def _preview(self, mail_id: str, index: int, name: str, kind: str, data: bytes,
                 attachment: dict[str, Any]) -> None:
        if not is_image(name, kind) or len(data) > 10_485_760:
            return
        image = open_image(data)
        if image is None:
            return
        encoded = base64.b64decode(encode(image, 1600).partition(",")[2])
        directory = self.directory(mail_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{index}.jpg"
        temporary = directory / f"{index}.tmp"
        temporary.write_bytes(encoded)
        temporary.replace(path)
        width, height = Image.open(io.BytesIO(encoded)).size
        attachment["preview"] = {"index": index, "size_bytes": len(encoded),
                                 "width": width, "height": height}

    def _keep_original(self, mail_id: str, index: int, name: str, data: bytes,
                       limits: OriginalAttachmentSettings, kept: dict[str, dict[str, Any]]) -> None:
        content_type = original_type(name, data)
        total = sum(item["size_bytes"] for item in kept.values()) + len(data)
        if content_type is None or len(data) > limits.max_original_bytes or total > limits.max_total_bytes:
            return
        directory = self.directory(mail_id)
        directory.mkdir(parents=True, exist_ok=True)
        temporary = directory / f"original-{index}.tmp"
        temporary.write_bytes(data)
        temporary.replace(directory / f"original-{index}.bin")
        kept[str(index)] = {"filename": name[:500], "content_type": content_type, "size_bytes": len(data),
                            "sha256": hashlib.sha256(data).hexdigest()}

    def originals(self, mail_id: str) -> dict[int, OriginalFile]:
        """Stored originals by attachment index; a damaged manifest reads as none."""
        path = self.directory(mail_id) / "originals.json"
        try:
            files = json.loads(path.read_text(encoding="utf-8"))["files"]
            return {int(key): OriginalFile(int(key), str(value["filename"]), str(value["content_type"]),
                                           int(value["size_bytes"]), str(value["sha256"]))
                    for key, value in files.items()}
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return {}

    def original(self, mail_id: str, index: int) -> tuple[OriginalFile, bytes] | None:
        """An original exactly as stored; a changed or replaced file is not served."""
        found = self.originals(mail_id).get(index)
        if found is None:
            return None
        path = self.directory(mail_id) / f"original-{index}.bin"
        if path.is_symlink() or not path.is_file():
            return None
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != found.sha256 or found.content_type != original_type(found.filename,
                                                                                                    data):
            return None
        return found, data

    def read(self, mail_id: str, index: int) -> bytes | None:
        if type(index) is not int or index < 0:
            return None
        directory = self.directory(mail_id)
        path = directory / f"{index}.jpg"
        if path.is_symlink() or not path.is_file():
            return None
        return path.read_bytes()

    def remove(self, mail_id: str) -> None:
        directory = self.directory(mail_id)
        if directory.exists():
            shutil.rmtree(directory)
