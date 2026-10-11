"""Multimodal OCR for image attachments and scanned PDFs (1.4).

Preparation is deterministic and needs no external binaries: Pillow decodes,
filters and scales images, pypdf exposes the embedded page images of scanned
PDFs.  Only the prepared JPEG reaches the vision model (step ``vision_ocr`` in
``prompts.yaml``).  Icons, tracking pixels and everything beyond
``vision.max_images_per_mail`` are never sent.  Text read from an image is as
untrusted as the mail itself.
"""
from __future__ import annotations

import base64
from collections.abc import Iterator
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
import io
from typing import Any, Protocol
import warnings

import pypdf
from PIL import Image, ImageOps

from .attachment_extractor import MAX_TEXT_CHARACTERS, _clean_text, _truncate_text
from .config import VisionSettings
from .domain.extraction import VisionExtractionResult
from .mime import attachment_parts
from .openrouter import RateLimitExceeded

IMAGE_TYPES = frozenset({"image/jpeg", "image/jpg", "image/pjpeg", "image/png", "image/webp"})
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
# The decoded format decides, not the untrusted header or file name.
IMAGE_FORMATS = frozenset({"JPEG", "PNG", "WEBP"})
# Smaller images are icons, logos or tracking pixels.
MIN_IMAGE_PIXELS = 150
MIN_IMAGE_BYTES = 10_240
# A PDF with less text despite this size is treated as a scan.
SCAN_MAX_CHARACTERS = 50
SCAN_MIN_BYTES = 50_000
# Decompression-bomb guard, checked before any pixel data is decoded.
MAX_SOURCE_PIXELS = 50_000_000
JPEG_QUALITY = 85


class DocumentReader(Protocol):
    def read_document(self, filename: str, content_type: str, images: list[str]) -> tuple[str, VisionExtractionResult]: ...


@dataclass(frozen=True)
class VisionJob:
    """One attachment to read; ``index`` is its position in ``extracted_attachments``."""

    index: int
    filename: str
    content_type: str
    images: tuple[str, ...]


@dataclass(frozen=True)
class VisionUpdate:
    """The new attachment entry plus content-free facts for the log."""

    index: int
    attachment: dict[str, Any]
    call_id: str | None = None
    error: str | None = None


def is_image(filename: str, content_type: str) -> bool:
    return content_type.lower() in IMAGE_TYPES or filename.lower().endswith(IMAGE_EXTENSIONS)


def is_scanned_pdf(attachment: dict[str, Any]) -> bool:
    """A PDF without a usable text layer although it is large enough for a scan."""
    name = str(attachment.get("filename", "")).lower()
    kind = str(attachment.get("content_type", "")).lower()
    return ((name.endswith(".pdf") or "pdf" in kind)
            and attachment.get("extraction_status") in {"success", "no_text_found"}
            and int(attachment.get("character_count", 0)) < SCAN_MAX_CHARACTERS
            and int(attachment.get("size_bytes", 0)) > SCAN_MIN_BYTES)


def _open(data: bytes) -> Image.Image | None:
    """Decode a JPEG, PNG or WebP image; ``None`` for anything unreadable."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(io.BytesIO(data))
            if image.format not in IMAGE_FORMATS or image.width * image.height > MAX_SOURCE_PIXELS:
                return None
            image.load()
            return image
    except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        return None


def _large_enough(image: Image.Image) -> bool:
    return image.width >= MIN_IMAGE_PIXELS and image.height >= MIN_IMAGE_PIXELS


def encode(image: Image.Image, max_edge: int) -> str:
    """Upright, flattened JPEG with at most ``max_edge`` pixels as a data URL."""
    image = ImageOps.exif_transpose(image)
    if image.mode in {"RGBA", "LA", "PA"} or "transparency" in image.info:
        rgba = image.convert("RGBA")
        flat = Image.new("RGB", rgba.size, "white")
        flat.paste(rgba, mask=rgba.getchannel("A"))
        image = flat
    else:
        image = image.convert("RGB")
    image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=JPEG_QUALITY, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def pdf_page_images(data: bytes, limit: int) -> list[Image.Image]:
    """The largest embedded image of each of the first pages of a scanned PDF."""
    try:
        pages = pypdf.PdfReader(io.BytesIO(data)).pages
        result: list[Image.Image] = []
        for page in pages:
            if len(result) >= limit:
                break
            candidates = []
            for embedded in page.images:
                try:
                    candidates.append(embedded.image)
                except Exception:
                    continue
            usable = [image for image in candidates if image is not None and _large_enough(image)
                      and image.width * image.height <= MAX_SOURCE_PIXELS]
            if usable:
                result.append(max(usable, key=lambda image: image.width * image.height))
        return result
    except Exception:
        return []


def plan(raw: bytes, attachments: list[dict[str, Any]],
         settings: VisionSettings) -> tuple[list[VisionJob], dict[int, str]]:
    """Return the OCR jobs and the skip reason per attachment, within the image limit."""
    parts = list(attachment_parts(BytesParser(policy=policy.default).parsebytes(raw)))
    if len(parts) != len(attachments):
        # The stored preparation does not belong to this message.
        return [], {}
    jobs: list[VisionJob] = []
    skipped: dict[int, str] = {}
    remaining = settings.max_images_per_mail
    for index, ((filename, content_type, payload), attachment) in enumerate(zip(parts, attachments)):
        image = is_image(filename, content_type)
        if attachment.get("vision") is not None or not (image or is_scanned_pdf(attachment)):
            continue
        if len(payload) > settings.max_image_bytes:
            skipped[index] = "skipped_oversized"
            continue
        if image and len(payload) < MIN_IMAGE_BYTES:
            skipped[index] = "skipped_small"
            continue
        if remaining == 0:
            skipped[index] = "skipped_limit"
            continue
        if image:
            decoded = _open(payload)
            if decoded is None:
                skipped[index] = "skipped_unreadable"
                continue
            if not _large_enough(decoded):
                skipped[index] = "skipped_small"
                continue
            images = [decoded]
        else:
            images = pdf_page_images(payload, remaining)
            if not images:
                skipped[index] = "skipped_unreadable"
                continue
        try:
            encoded = tuple(encode(item, settings.max_edge_pixels) for item in images)
        except (OSError, ValueError):
            skipped[index] = "skipped_unreadable"
            continue
        remaining -= len(encoded)
        jobs.append(VisionJob(index, filename, content_type, encoded))
    return jobs, skipped


class VisionExtractor:
    """Read the planned attachments one by one; a failure never stops the mail."""

    def __init__(self, reader: DocumentReader, settings: VisionSettings) -> None:
        self.reader, self.settings = reader, settings

    def extract(self, raw: bytes, attachments: list[dict[str, Any]]) -> Iterator[VisionUpdate]:
        jobs, skipped = plan(raw, attachments, self.settings)
        for index, reason in sorted(skipped.items()):
            yield VisionUpdate(index, {**attachments[index], "vision": reason})
        for job in jobs:
            attachment = attachments[job.index]
            try:
                call_id, result = self.reader.read_document(job.filename, job.content_type,
                                                            list(job.images))
            except RateLimitExceeded:
                # Deferred like every other LLM step; finished attachments are kept.
                raise
            except Exception as exc:
                yield VisionUpdate(job.index, {**attachment, "vision": "failed"},
                                   error=type(exc).__name__)
                continue
            text = _clean_text(result.text) if result.legible else ""
            if not text:
                yield VisionUpdate(job.index, {**attachment, "vision": "no_text"}, call_id)
                continue
            text, _ = _truncate_text(text, MAX_TEXT_CHARACTERS)
            yield VisionUpdate(job.index, {
                **attachment, "text": text, "extraction_status": "success",
                "character_count": len(text), "vision": "read"}, call_id)


__all__ = ["DocumentReader", "IMAGE_FORMATS", "IMAGE_TYPES", "MIN_IMAGE_BYTES", "MIN_IMAGE_PIXELS",
           "SCAN_MAX_CHARACTERS", "SCAN_MIN_BYTES", "VisionExtractor", "VisionJob", "VisionUpdate",
           "encode", "is_image", "is_scanned_pdf", "pdf_page_images", "plan"]
