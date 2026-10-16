"""Sichere Text-Extraktion aus Dokumenten-Anhängen (PDF, DOCX, TXT)."""
from __future__ import annotations

import io
import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile

import pypdf

from .domain.extraction import ExtractedAttachment

MAX_ATTACHMENT_BYTES = 5_000_000
MAX_TEXT_CHARACTERS = 20_000
_TRUNCATION_MARKER = "\n[... Text nach 20.000 Zeichen gekürzt ...]"


def clean_text(value: str) -> str:
    """Normalize extracted text and strip control characters except tabs and newlines."""
    normalized = unicodedata.normalize("NFKC", value.replace("\r\n", "\n").replace("\r", "\n"))
    cleaned = "".join(
        char for char in normalized
        if char in "\n\t" or unicodedata.category(char) not in {"Cc", "Cf", "Cs"}
    )
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in cleaned.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def truncate_text(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars].rstrip() + _TRUNCATION_MARKER, True


def extract_attachment_text(
    filename: str,
    content_type: str,
    data: bytes,
    max_bytes: int = MAX_ATTACHMENT_BYTES,
    max_chars: int = MAX_TEXT_CHARACTERS,
) -> ExtractedAttachment:
    """Extract bounded plain text from document attachments."""
    size_bytes = len(data)
    if size_bytes > max_bytes:
        return ExtractedAttachment(
            filename=filename[:500],
            content_type=content_type[:200],
            size_bytes=size_bytes,
            text="",
            extraction_status="skipped_oversized",
            character_count=0,
        )

    lower_name = filename.lower()
    lower_type = content_type.lower()

    is_pdf = lower_name.endswith(".pdf") or "pdf" in lower_type
    is_docx = lower_name.endswith(".docx") or "wordprocessingml" in lower_type
    is_text = (
        lower_name.endswith((".txt", ".md", ".csv", ".rtf"))
        or lower_type.startswith("text/")
        or lower_type in {"application/csv", "application/rtf"}
    )

    if is_pdf:
        return _extract_pdf(filename, content_type, data, size_bytes, max_chars)
    elif is_docx:
        return _extract_docx(filename, content_type, data, size_bytes, max_chars)
    elif is_text:
        return _extract_text(filename, content_type, data, size_bytes, max_chars)
    else:
        return ExtractedAttachment(
            filename=filename[:500],
            content_type=content_type[:200],
            size_bytes=size_bytes,
            text="",
            extraction_status="unsupported_format",
            character_count=0,
        )


def _extract_pdf(
    filename: str, content_type: str, data: bytes, size_bytes: int, max_chars: int
) -> ExtractedAttachment:
    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            return ExtractedAttachment(
                filename=filename[:500],
                content_type=content_type[:200],
                size_bytes=size_bytes,
                text="",
                extraction_status="encrypted",
                character_count=0,
            )

        extracted_pages: list[str] = []
        total_len = 0
        for page in reader.pages:
            page_text = page.extract_text() or ""
            if page_text:
                extracted_pages.append(page_text)
                total_len += len(page_text)
                if total_len > max_chars * 2:
                    break

        raw_text = "\n\n".join(extracted_pages)
        cleaned = clean_text(raw_text)
        if not cleaned:
            return ExtractedAttachment(
                filename=filename[:500],
                content_type=content_type[:200],
                size_bytes=size_bytes,
                text="",
                extraction_status="no_text_found",
                character_count=0,
            )

        truncated, _ = truncate_text(cleaned, max_chars)
        return ExtractedAttachment(
            filename=filename[:500],
            content_type=content_type[:200],
            size_bytes=size_bytes,
            text=truncated,
            extraction_status="success",
            character_count=len(truncated),
        )
    except Exception:
        return ExtractedAttachment(
            filename=filename[:500],
            content_type=content_type[:200],
            size_bytes=size_bytes,
            text="",
            extraction_status="error",
            character_count=0,
        )


def _extract_docx(
    filename: str, content_type: str, data: bytes, size_bytes: int, max_chars: int
) -> ExtractedAttachment:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if "word/document.xml" not in archive.namelist():
                return ExtractedAttachment(
                    filename=filename[:500],
                    content_type=content_type[:200],
                    size_bytes=size_bytes,
                    text="",
                    extraction_status="error",
                    character_count=0,
                )

            xml_data = archive.read("word/document.xml")
            root = ET.fromstring(xml_data)

            # Namespace for Word OpenXML
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            paragraphs: list[str] = []
            for p in root.iterfind(".//w:p", ns):
                texts = [node.text for node in p.iterfind(".//w:t", ns) if node.text]
                if texts:
                    paragraphs.append("".join(texts))

            raw_text = "\n".join(paragraphs)
            cleaned = clean_text(raw_text)
            if not cleaned:
                return ExtractedAttachment(
                    filename=filename[:500],
                    content_type=content_type[:200],
                    size_bytes=size_bytes,
                    text="",
                    extraction_status="no_text_found",
                    character_count=0,
                )

            truncated, _ = truncate_text(cleaned, max_chars)
            return ExtractedAttachment(
                filename=filename[:500],
                content_type=content_type[:200],
                size_bytes=size_bytes,
                text=truncated,
                extraction_status="success",
                character_count=len(truncated),
            )
    except Exception:
        return ExtractedAttachment(
            filename=filename[:500],
            content_type=content_type[:200],
            size_bytes=size_bytes,
            text="",
            extraction_status="error",
            character_count=0,
        )


def _extract_text(
    filename: str, content_type: str, data: bytes, size_bytes: int, max_chars: int
) -> ExtractedAttachment:
    try:
        try:
            raw_text = data.decode("utf-8")
        except UnicodeDecodeError:
            raw_text = data.decode("latin-1", errors="replace")

        cleaned = clean_text(raw_text)
        if not cleaned:
            return ExtractedAttachment(
                filename=filename[:500],
                content_type=content_type[:200],
                size_bytes=size_bytes,
                text="",
                extraction_status="no_text_found",
                character_count=0,
            )

        truncated, _ = truncate_text(cleaned, max_chars)
        return ExtractedAttachment(
            filename=filename[:500],
            content_type=content_type[:200],
            size_bytes=size_bytes,
            text=truncated,
            extraction_status="success",
            character_count=len(truncated),
        )
    except Exception:
        return ExtractedAttachment(
            filename=filename[:500],
            content_type=content_type[:200],
            size_bytes=size_bytes,
            text="",
            extraction_status="error",
            character_count=0,
        )

