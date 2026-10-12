"""Vision OCR (1.4): deterministic preparation and the per-attachment extractor."""
from __future__ import annotations

import base64
import io
from email.message import EmailMessage

import pytest
from PIL import Image

from mailhelp import vision
from mailhelp.config import VisionSettings
from mailhelp.mime import prepare
from mailhelp.models import ExtractedAttachment, VisionExtractionResult
from mailhelp.openrouter import RateLimitExceeded


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


def test_image_and_scan_detection():
    assert vision.is_image("foto.JPG", "application/octet-stream")
    assert vision.is_image("scan", "image/webp")
    assert not vision.is_image("flyer.gif", "image/gif")
    scan = {"filename": "scan.pdf", "content_type": "application/pdf", "size_bytes": 60_000,
            "extraction_status": "no_text_found", "character_count": 0}
    assert vision.is_scanned_pdf(scan)
    assert vision.is_scanned_pdf({**scan, "filename": "x", "extraction_status": "success",
                                  "character_count": 49})
    assert not vision.is_scanned_pdf({**scan, "character_count": 50, "extraction_status": "success"})
    assert not vision.is_scanned_pdf({**scan, "size_bytes": 50_000})
    assert not vision.is_scanned_pdf({**scan, "extraction_status": "encrypted"})
    assert not vision.is_scanned_pdf({**scan, "filename": "a.docx", "content_type": "application/msword"})


def test_open_accepts_only_bounded_jpeg_png_and_webp(monkeypatch):
    for fmt in ("PNG", "JPEG", "WEBP"):
        assert vision.open_image(image_bytes(noise(), fmt)).size == (300, 300)
    assert vision.open_image(image_bytes(noise(), "GIF")) is None
    assert vision.open_image(b"kein Bild") is None
    monkeypatch.setattr(vision, "MAX_SOURCE_PIXELS", 300 * 300 - 1)
    assert vision.open_image(image_bytes(noise(), "PNG")) is None


def test_open_rejects_decompression_bombs(monkeypatch):
    # Pillow warns above MAX_IMAGE_PIXELS; the warning is treated as an error.
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100 * 100)
    assert vision.open_image(image_bytes(noise(), "PNG")) is None
    # Twice the limit is an error in Pillow itself.
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 10 * 10)
    assert vision.open_image(image_bytes(noise(), "PNG")) is None


def test_encode_scales_flattens_and_rotates():
    wide = decoded(vision.encode(noise(3200, 800), 1600))
    assert wide.size == (1600, 400) and wide.mode == "RGB"
    small = decoded(vision.encode(noise(400, 300, "L"), 1600))
    assert small.size == (400, 300)
    transparent = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    assert decoded(vision.encode(transparent, 1600)).getpixel((5, 5)) == (255, 255, 255)
    palette = Image.new("P", (200, 200), 0)
    palette.info["transparency"] = 0
    assert decoded(vision.encode(palette, 1600)).getpixel((5, 5)) == (255, 255, 255)
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90° clockwise when displayed
    rotated = Image.open(io.BytesIO(image_bytes(noise(400, 200), "JPEG", exif=exif)))
    assert decoded(vision.encode(rotated, 1600)).size == (200, 400)


def test_pdf_page_images_use_the_largest_usable_image_per_page(monkeypatch):
    pages = vision.pdf_page_images(scanned_pdf(3), 2)
    assert [page.size for page in pages] == [(600, 800), (600, 800)]
    assert vision.pdf_page_images(scanned_pdf(1, (100, 100)), 3) == []
    assert vision.pdf_page_images(b"%PDF-kaputt", 3) == []

    class Broken:
        @property
        def image(self):
            raise ValueError("Filter nicht unterstützt")

    class Empty:
        image = None

    class Huge:
        image = noise(400, 400)

    class Page:
        images = [Broken(), Empty(), Huge()]

    class Reader:
        def __init__(self, stream): self.pages = [Page()]

    monkeypatch.setattr(vision.pypdf, "PdfReader", Reader)
    assert [page.size for page in vision.pdf_page_images(b"", 3)] == [(400, 400)]
    monkeypatch.setattr(vision, "MAX_SOURCE_PIXELS", 100)
    assert vision.pdf_page_images(b"", 3) == []


def test_plan_filters_limits_and_reports_every_skipped_attachment():
    raw = mail(
        ("icon.png", "image", "png", image_bytes(noise(40, 40))),               # < 10 KB
        ("logo.png", "image", "png", image_bytes(noise(140, 400))),             # < 150 px
        ("kaputt.jpg", "image", "jpeg", b"x" * 20_000),
        ("bericht.pdf", "application", "pdf", b"%PDF-1.4 kein Scan"),
        ("foto.jpg", "image", "jpeg", image_bytes(noise(2000, 1000), "JPEG")),
        ("scan.pdf", "application", "pdf", scanned_pdf(3)),
        ("zu-viel.png", "image", "png", image_bytes(noise())),
        ("notiz.txt", "text", "plain", b"Kein Bild"),
    )
    jobs, skipped = vision.plan(raw, prepared(raw), SETTINGS)
    assert [(job.index, job.filename, len(job.images)) for job in jobs] == [
        (4, "foto.jpg", 1), (5, "scan.pdf", 2)]
    assert decoded(jobs[0].images[0]).size == (1600, 800)
    assert skipped == {0: "skipped_small", 1: "skipped_small", 2: "skipped_unreadable",
                       6: "skipped_limit"}


def test_plan_skips_oversized_handled_and_imageless_attachments(monkeypatch):
    raw = mail(("gross.png", "image", "png", image_bytes(noise())),
               ("leer.pdf", "application", "pdf", scanned_pdf(1, (100, 100)) + b" " * 60_000),
               ("erledigt.png", "image", "png", image_bytes(noise())))
    attachments = prepared(raw)
    attachments[2]["vision"] = "read"
    jobs, skipped = vision.plan(raw, attachments, VisionSettings(max_image_bytes=200_000))
    assert jobs == [] and skipped == {0: "skipped_oversized", 1: "skipped_unreadable"}
    # The stored preparation must belong to exactly this message.
    assert vision.plan(raw, attachments[:2], SETTINGS) == ([], {})

    def broken(image, edge):
        raise OSError("Kodierung fehlgeschlagen")

    monkeypatch.setattr(vision, "encode", broken)
    assert vision.plan(raw, prepared(raw), SETTINGS) == ([], {0: "skipped_unreadable",
                                                             1: "skipped_unreadable",
                                                             2: "skipped_unreadable"})


class Reader:
    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def read_document(self, filename, content_type, images):
        self.calls.append((filename, content_type, len(images)))
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return f"call-{len(self.calls)}", answer


def test_extractor_reads_each_job_and_never_fails_the_mail():
    raw = mail(("a.png", "image", "png", image_bytes(noise())),
               ("b.png", "image", "png", image_bytes(noise())),
               ("c.png", "image", "png", image_bytes(noise())),
               ("icon.png", "image", "png", image_bytes(noise(20, 20))))
    attachments = prepared(raw)
    reader = Reader(VisionExtractionResult(legible=True, text="Elternabend\x07 am 3. März  19 Uhr"),
                    VisionExtractionResult(legible=False),
                    ValueError("Anbieter nicht erreichbar"))
    updates = list(vision.VisionExtractor(reader, SETTINGS).extract(raw, attachments))
    assert [(u.index, u.attachment["vision"], u.call_id, u.error) for u in updates] == [
        (3, "skipped_small", None, None), (0, "read", "call-1", None),
        (1, "no_text", "call-2", None), (2, "failed", None, "ValueError")]
    read = ExtractedAttachment.model_validate(updates[1].attachment)
    assert read.text == "Elternabend am 3. März 19 Uhr" and read.extraction_status == "success"
    assert read.character_count == len(read.text)
    assert updates[2].attachment["extraction_status"] == "unsupported_format"
    assert reader.calls[0] == ("a.png", "image/png", 1)


def test_extractor_truncates_long_text_and_ignores_blank_answers():
    raw = mail(("a.png", "image", "png", image_bytes(noise())),
               ("b.png", "image", "png", image_bytes(noise())))
    reader = Reader(VisionExtractionResult(legible=True, text="x" * 20_000 + "y"),
                    VisionExtractionResult(legible=True, text=" \n "))
    first, second = vision.VisionExtractor(reader, SETTINGS).extract(raw, prepared(raw))
    assert first.attachment["text"].endswith("gekürzt ...]") and first.attachment["vision"] == "read"
    assert second.attachment["vision"] == "no_text"


def test_extractor_defers_on_the_llm_rate_limit():
    raw = mail(("a.png", "image", "png", image_bytes(noise())))
    updates = vision.VisionExtractor(Reader(RateLimitExceeded(0.0)), SETTINGS).extract(raw, prepared(raw))
    with pytest.raises(RateLimitExceeded):
        next(updates)


def test_vision_result_rejects_text_for_illegible_documents():
    with pytest.raises(ValueError):
        VisionExtractionResult(legible=False, text="erfunden")
    assert VisionExtractionResult(legible=False, text=" ").text == " "
