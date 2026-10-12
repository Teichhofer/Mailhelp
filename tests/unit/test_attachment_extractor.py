"""Unit-Tests für die Dokumenten-Text-Extraktion (PDF, DOCX, TXT) und MIME-Integration."""
import io
import zipfile
from email.message import EmailMessage

import pypdf
import pytest

from mailhelp.attachment_extractor import (
    extract_attachment_text,
    clean_text,
    truncate_text,
    _TRUNCATION_MARKER,
    MAX_ATTACHMENT_BYTES,
)
from mailhelp.mime import prepare, MimeLimits


RAW_PDF_BYTES = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>endobj
4 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
5 0 obj<</Length 44>>stream
BT /F1 12 Tf 100 700 Td (Hallo Welt) Tj ET
endstream
endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000227 00000 n 
0000000294 00000 n 
trailer<</Size 6/Root 1 0 R>>
startxref
388
%%EOF"""


def make_encrypted_pdf() -> bytes:
    writer = pypdf.PdfWriter(clone_from=io.BytesIO(RAW_PDF_BYTES))
    writer.encrypt("topsecret")
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def make_blank_pdf() -> bytes:
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=100, height=100)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def make_docx(paragraphs: list[str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        body_parts = []
        for para in paragraphs:
            body_parts.append(f"<w:p><w:r><w:t>{para}</w:t></w:r></w:p>")
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f'<w:body>{"".join(body_parts)}</w:body>'
            '</w:document>'
        )
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


def test_clean_and_truncate_text():
    raw = "  Text   mit \t Tabs  \n\n\n\nund   vielen   Zeilen. \x00 "
    cleaned = clean_text(raw)
    assert cleaned == "Text mit Tabs\n\nund vielen Zeilen."

    short, truncated = truncate_text("12345", 10)
    assert short == "12345" and not truncated

    long_text, truncated = truncate_text("1234567890", 5)
    assert truncated is True
    assert long_text.startswith("12345")
    assert _TRUNCATION_MARKER in long_text


def test_extract_oversized_attachment():
    data = b"X" * 100
    res = extract_attachment_text("gross.pdf", "application/pdf", data, max_bytes=50)
    assert res.extraction_status == "skipped_oversized"
    assert res.text == ""
    assert res.character_count == 0


def test_extract_pdf():
    # Valid PDF with text
    res = extract_attachment_text("bericht.pdf", "application/pdf", RAW_PDF_BYTES)
    assert res.extraction_status == "success"
    assert "Hallo Welt" in res.text
    assert res.character_count > 0

    # Encrypted PDF
    enc = make_encrypted_pdf()
    res_enc = extract_attachment_text("sicher.pdf", "application/pdf", enc)
    assert res_enc.extraction_status == "encrypted"
    assert res_enc.text == ""

    # Blank PDF without text
    blank = make_blank_pdf()
    res_blank = extract_attachment_text("leer.pdf", "application/pdf", blank)
    assert res_blank.extraction_status == "no_text_found"

    # Truncated PDF
    res_trunc = extract_attachment_text("lang.pdf", "application/pdf", RAW_PDF_BYTES, max_chars=4)
    assert res_trunc.extraction_status == "success"
    assert _TRUNCATION_MARKER in res_trunc.text

    # Corrupted PDF
    res_err = extract_attachment_text("kaputt.pdf", "application/pdf", b"kein pdf content")
    assert res_err.extraction_status == "error"


def test_extract_docx():
    # Valid DOCX with text
    docx_bytes = make_docx(["Aufgabe 1: Angebot einholen", "Aufgabe 2: Vertrag prüfen"])
    res = extract_attachment_text("protokoll.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", docx_bytes)
    assert res.extraction_status == "success"
    assert "Aufgabe 1: Angebot einholen" in res.text
    assert "Aufgabe 2: Vertrag prüfen" in res.text

    # Empty DOCX
    empty_docx = make_docx([])
    res_empty = extract_attachment_text("leer.docx", "application/docx", empty_docx)
    assert res_empty.extraction_status == "no_text_found"

    # Truncated DOCX
    res_trunc = extract_attachment_text("lang.docx", "application/docx", docx_bytes, max_chars=10)
    assert res_trunc.extraction_status == "success"
    assert _TRUNCATION_MARKER in res_trunc.text

    # DOCX missing document.xml
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("other.xml", "<root/>")
    res_missing = extract_attachment_text("defekt.docx", "application/docx", buf.getvalue())
    assert res_missing.extraction_status == "error"

    # Corrupted ZIP
    res_corrupt = extract_attachment_text("kaputt.docx", "application/docx", b"kein zip archiv")
    assert res_corrupt.extraction_status == "error"


def test_extract_text_formats():
    # UTF-8 text
    txt_utf8 = "Rechnung Nr. 1234\nFällig am 30.11.2026".encode("utf-8")
    res = extract_attachment_text("info.txt", "text/plain", txt_utf8)
    assert res.extraction_status == "success"
    assert "Rechnung Nr. 1234" in res.text

    # Latin-1 text
    txt_latin1 = "Prüfung & Übergabe".encode("latin-1")
    res_lat = extract_attachment_text("notizen.md", "text/markdown", txt_latin1)
    assert res_lat.extraction_status == "success"
    assert "Prüfung & Übergabe" in res_lat.text

    # Empty text
    res_empty = extract_attachment_text("leer.txt", "text/plain", b"   \n\t  ")
    assert res_empty.extraction_status == "no_text_found"

    # Truncated text
    res_trunc = extract_attachment_text("lang.csv", "text/csv", txt_utf8, max_chars=8)
    assert res_trunc.extraction_status == "success"
    assert _TRUNCATION_MARKER in res_trunc.text


def test_extract_unsupported_format():
    res = extract_attachment_text("programm.exe", "application/octet-stream", b"binary code")
    assert res.extraction_status == "unsupported_format"
    assert res.text == ""


def test_mime_integration_with_calendar_and_pdf_attachments():
    msg = EmailMessage()
    msg["From"] = "vorstand@verein.de"
    msg["Subject"] = "Einladung und Protokoll"
    msg.set_content("Hallo zusammen, anbei die Unterlagen.")

    # Attach ICS calendar invitation
    ics_content = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:vorstand-2026@verein.de
DTSTART:20261105T180000Z
DTEND:20261105T193000Z
SUMMARY:Vorstandssitzung
LOCATION:Vereinsheim
END:VEVENT
END:VCALENDAR"""
    msg.add_attachment(ics_content.encode("utf-8"), maintype="text", subtype="calendar", filename="einladung.ics")

    # Attach PDF document
    msg.add_attachment(RAW_PDF_BYTES, maintype="application", subtype="pdf", filename="protokoll.pdf")

    limits = MimeLimits(max_mail_bytes=500_000, max_llm_payload_bytes=500_000)
    result = prepare(msg.as_bytes(), limits)

    assert result["text"] == "Hallo zusammen, anbei die Unterlagen."
    assert "calendar_events" in result
    assert len(result["calendar_events"]) == 1
    assert result["calendar_events"][0]["summary"] == "Vorstandssitzung"
    assert result["calendar_events"][0]["location"] == "Vereinsheim"

    assert "extracted_attachments" in result
    assert len(result["extracted_attachments"]) == 2

    # Verify ICS attachment info
    ics_att = next(a for a in result["extracted_attachments"] if a["filename"] == "einladung.ics")
    assert ics_att["extraction_status"] == "success"

    # Verify PDF text extraction
    pdf_att = next(a for a in result["extracted_attachments"] if a["filename"] == "protokoll.pdf")
    assert pdf_att["extraction_status"] == "success"
    assert "Hallo Welt" in pdf_att["text"]


def test_mime_integration_handles_corrupt_ics():
    msg = EmailMessage()
    msg["From"] = "sender@example.test"
    msg["Subject"] = "Test"
    msg.set_content("Text")
    # Corrupt ICS that raises during parse
    msg.add_attachment(b"X" * (1_500_000), maintype="text", subtype="calendar", filename="bad.ics")

    limits = MimeLimits(max_mail_bytes=2_000_000, max_llm_payload_bytes=500_000)
    result = prepare(msg.as_bytes(), limits)
    assert result["calendar_events"] == []
    assert len(result["extracted_attachments"]) == 1
    assert result["extracted_attachments"][0]["extraction_status"] == "error"


def test_docx_empty_paragraph_and_extract_text_error(monkeypatch):
    # DOCX with an empty paragraph
    docx_bytes = make_docx(["", "Text nach Leerzeile"])
    res = extract_attachment_text("leerzeile.docx", "application/docx", docx_bytes)
    assert res.extraction_status == "success"
    assert "Text nach Leerzeile" in res.text

    # extract_text unexpected error branch
    monkeypatch.setattr("mailhelp.attachment_extractor.clean_text", lambda _t: (_ for _ in ()).throw(RuntimeError("boom")))
    res_err = extract_attachment_text("boom.txt", "text/plain", b"irrelevant")
    assert res_err.extraction_status == "error"


def test_mime_attachment_none_payload():
    raw = (
        b"From: sender@example.test\r\n"
        b"Subject: Test\r\n"
        b"Content-Type: multipart/mixed; boundary=\"boundary123\"\r\n\r\n"
        b"--boundary123\r\n"
        b"Content-Type: text/plain\r\n\r\n"
        b"Body\r\n"
        b"--boundary123\r\n"
        b"Content-Type: application/pdf\r\n"
        b"Content-Disposition: attachment; filename=\"empty.pdf\"\r\n\r\n"
        b"--boundary123--\r\n"
    )
    res = prepare(raw, MimeLimits(100_000))
    assert len(res["extracted_attachments"]) == 1
    assert res["extracted_attachments"][0]["filename"] == "empty.pdf"
