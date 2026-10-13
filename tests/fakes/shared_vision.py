"""Shared synthetic fixtures and doubles; no test-module dependencies."""
from __future__ import annotations

import base64
import io
from email.message import EmailMessage

from PIL import Image

from mailhelp.config import VisionSettings
from mailhelp.mime import prepare


def noise(width=300, height=300, mode="RGB") -> Image.Image:
    return Image.effect_noise((width, height), 60).convert(mode)

def image_bytes(image: Image.Image, fmt="PNG", **options) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, fmt, **options)
    return buffer.getvalue()

def scanned_pdf(pages=2, size=(600, 800)) -> bytes:
    images = [noise(*size) for _ in range(pages)]
    buffer = io.BytesIO()
    images[0].save(buffer, "PDF", save_all=True, append_images=images[1:])
    return buffer.getvalue()

def mail(*attachments) -> bytes:
    message = EmailMessage()
    message["From"] = "Schule <info@schule.example>"
    message["Subject"] = "Aushang"
    message.set_content("Siehe Anhang.")
    for filename, maintype, subtype, data in attachments:
        message.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
    return message.as_bytes()

def prepared(raw: bytes) -> list[dict]:
    return prepare(raw, 50_000_000)["extracted_attachments"]

def decoded(url: str) -> Image.Image:
    header, data = url.split(",", 1)
    assert header == "data:image/jpeg;base64"
    return Image.open(io.BytesIO(base64.b64decode(data)))

SETTINGS = VisionSettings()

class Reader:
    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def read_document(self, filename, content_type, images):
        self.calls.append((filename, content_type, len(images)))
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return f"call-{len(self.calls)}", answer
