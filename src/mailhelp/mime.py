"""Sichere MIME-Aufbereitung ohne externe Ressourcen."""
from __future__ import annotations
from email.message import Message
from email.parser import BytesParser
from email import policy
from html.parser import HTMLParser
import re


class _TextHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(); self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _body(part: Message) -> str:
    value = part.get_content()
    if part.get_content_type() == "text/html":
        parser = _TextHTML(); parser.feed(value); return " ".join(parser.parts)
    return value


def prepare(raw: bytes, max_bytes: int) -> dict[str, object]:
    if len(raw) > max_bytes:
        raise ValueError(f"E-Mail ist größer als das konfigurierte Limit ({max_bytes} Bytes)")
    message = BytesParser(policy=policy.default).parsebytes(raw)
    attachments = 0; plain: list[str] = []; html: list[str] = []
    for part in message.walk():
        if part.is_multipart():
            continue
        if part.get_content_disposition() == "attachment":
            attachments += 1; continue
        if part.get_content_type() == "text/plain": plain.append(_body(part))
        elif part.get_content_type() == "text/html": html.append(_body(part))
    text = "\n".join(plain or html)
    text = re.split(r"\n(?:-- |On .+ wrote:|Am .+ schrieb .+:)", text, maxsplit=1)[0]
    text = re.sub(r"[ \t]+", " ", text).strip()
    return {"from": str(message.get("From", "")), "subject": str(message.get("Subject", "")), "date": str(message.get("Date", "")), "message_id": str(message.get("Message-ID", "")), "text": text, "attachments": attachments}

