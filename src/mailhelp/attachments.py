"""Private raster previews, independent of optional OCR and external services."""
from __future__ import annotations

import base64
import io
from email import policy
from email.parser import BytesParser
import re
import shutil

from PIL import Image

from .mime import attachment_parts
from .vision import open_image, encode, IMAGE_TYPES


class AttachmentCache:
    def __init__(self, store):
        self.root = store.directory / "attachments"

    def directory(self, mail_id):
        if not re.fullmatch(r"[a-f0-9]{24}", mail_id):
            raise ValueError("Ungültige Mail-ID")
        path = self.root / mail_id
        if path.resolve().parent != self.root.resolve():
            raise ValueError("Ungültiger Anhangspfad")
        return path

    def prepare(self, mail_id, raw, attachments):
        parts = list(attachment_parts(BytesParser(policy=policy.default).parsebytes(raw)))
        if len(parts) != len(attachments):
            return
        for index, ((_, kind, data), attachment) in enumerate(zip(parts, attachments)):
            if kind not in IMAGE_TYPES or len(data) > 10_485_760:
                continue
            image = open_image(data)
            if image is None:
                continue
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

    def read(self, mail_id, index):
        if type(index) is not int or index < 0:
            return None
        directory = self.directory(mail_id)
        path = directory / f"{index}.jpg"
        if path.is_symlink() or not path.is_file():
            return None
        return path.read_bytes()

    def remove(self, mail_id):
        directory = self.directory(mail_id)
        if directory.exists():
            shutil.rmtree(directory)
