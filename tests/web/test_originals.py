"""Original documents: allow-list, limits, integrity and a download-only route (Planung 2.3, 6)."""
import pytest
from shared_vision import mail
from shared_web_actions import MAIL1
from shared_web_details import with_mail

from mailhelp.attachments import AttachmentCache, download_name, original_type
from mailhelp.config import OriginalAttachmentSettings
from mailhelp.storage import JsonStore

PDF = b"%PDF-1.7 synthetisch"
DOCX = b"PK\x03\x04 synthetisches docx"
OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1 doc"
KEEP = OriginalAttachmentSettings()


@pytest.mark.parametrize(("name", "data", "expected"), [
    ("Rechnung.PDF", PDF, "application/pdf"),
    ("brief.docx", DOCX, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ("brief.docx", PDF, None),
    ("alt.doc", OLE, "application/msword"), ("tabelle.xls", OLE, "application/vnd.ms-excel"),
    ("folien.ppt", OLE, "application/vnd.ms-powerpoint"), ("t.rtf", b"{\\rtf1 x}", "application/rtf"),
    ("liste.csv", b"a;b", "text/csv; charset=utf-8"), ("notiz.txt", b"Text", "text/plain; charset=utf-8"),
    ("termin.ics", b"BEGIN:VCALENDAR", "text/calendar; charset=utf-8"), ("binär.txt", b"a\x00b", None),
    ("foto.jpg", b"\xff\xd8\xff\xe0", "image/jpeg"), ("foto.jpeg", b"\xff\xd8\xff\xe0", "image/jpeg"),
    ("bild.png", b"\x89PNG\r\n\x1a\nxx", "image/png"), ("anim.gif", b"GIF89a", "image/gif"),
    ("bild.webp", b"RIFF1234WEBPVP8", "image/webp"), ("bild.heic", b"0000ftypheic", "image/heic"),
    ("bild.heic", b"0000ftypavif", None), ("tarnung.pdf", b"MZ\x90\x00", None),
    ("programm.exe", b"MZ\x90\x00", None), ("seite.html", b"<html>", None), ("bild.svg", b"<svg/>", None),
    ("ohne-endung", PDF, None), ("leer.pdf", b"", None)])
def test_only_allow_listed_types_with_matching_signature(name, data, expected):
    assert original_type(name, data) == expected


def test_office_and_opendocument_types():
    for extension in ("xlsx", "pptx", "odt", "ods", "odp"):
        assert original_type(f"datei.{extension}", DOCX) is not None
        assert original_type(f"datei.{extension}", PDF) is None


@pytest.mark.parametrize(("name", "expected"), [
    ("Rechnung März.pdf", ("Rechnung März.pdf", "Rechnung_Marz.pdf")),
    ("C:\\Users\\x\\böse.pdf", ("böse.pdf", "bose.pdf")), ("../../etc/passwd", ("passwd", "passwd")),
    ('a"b;c\r\n.pdf', ("abc.pdf", "abc.pdf")), ("...", ("anhang-3", "anhang-3")),
    ("日本.pdf", ("日本.pdf", "pdf"))])
def test_download_names_are_safe(name, expected):
    assert download_name(name, 3) == expected


def raw_mail():
    return mail(("rechnung.pdf", "application", "pdf", PDF), ("setup.exe", "application", "octet-stream", b"MZ"),
                ("brief.docx", "application", "octet-stream", DOCX))


def test_originals_are_stored_with_a_manifest_and_checked_on_read(tmp_path):
    store = JsonStore(tmp_path)
    cache = AttachmentCache(store)
    entries = [{}, {}, {}]
    cache.prepare(MAIL1, raw_mail(), entries, KEEP)
    assert entries == [{}, {}, {}]  # the prepared mail for the analysis stays unchanged
    stored = cache.originals(MAIL1)
    assert sorted(stored) == [0, 2] and stored[0].filename == "rechnung.pdf" and stored[0].size_bytes == len(PDF)
    original, data = cache.original(MAIL1, 0)
    assert data == PDF and original.content_type == "application/pdf"
    assert cache.original(MAIL1, 1) is None and cache.original(MAIL1, 9) is None
    # A changed file on disk is never served.
    (cache.directory(MAIL1) / "original-2.bin").write_bytes(DOCX + b"!")
    assert cache.original(MAIL1, 2) is None
    (cache.directory(MAIL1) / "original-2.bin").unlink()
    assert cache.original(MAIL1, 2) is None
    (cache.directory(MAIL1) / "originals.json").write_text("{kaputt", encoding="utf-8")
    assert cache.originals(MAIL1) == {}
    cache.remove(MAIL1)
    assert cache.originals(MAIL1) == {}


def test_limits_and_switch(tmp_path):
    store = JsonStore(tmp_path)
    cache = AttachmentCache(store)
    cache.prepare(MAIL1, raw_mail(), [{}, {}, {}], OriginalAttachmentSettings(store_originals=False))
    assert cache.originals(MAIL1) == {}
    cache.prepare(MAIL1, raw_mail(), [{}, {}, {}])
    assert cache.originals(MAIL1) == {}
    big = PDF + b"x" * 2000
    many = mail(("a.pdf", "application", "pdf", big), ("b.pdf", "application", "pdf", big),
                ("c.pdf", "application", "pdf", PDF + b"y" * 3000))
    cache.prepare(MAIL1, many, [{}, {}, {}], OriginalAttachmentSettings(max_original_bytes=2500,
                                                                         max_total_bytes=4100))
    assert sorted(cache.originals(MAIL1)) == [0, 1]


def test_download_route_headers_retention_and_session(web):
    entries = [{"filename": "rechnung.pdf", "text": "Betrag"}, {"filename": "setup.exe"},
               {"filename": "brief.docx"}]
    AttachmentCache(web.store).prepare(MAIL1, raw_mail(), entries, KEEP)
    with_mail(web.store, 1, extracted_attachments=entries)
    page = web.browser.request("GET", f"/mail/{MAIL1}").body.decode()
    assert page.count("Original herunterladen") == 2 and f'href="/mail/{MAIL1}/original/0" download' in page
    response = web.browser.request("GET", f"/mail/{MAIL1}/original/0")
    headers = dict(response.all_headers())
    assert response.status == 200 and response.body == PDF and response.content_type == "application/pdf"
    assert headers["Content-Disposition"] == (
        "attachment; filename=\"rechnung.pdf\"; filename*=UTF-8''rechnung.pdf")
    assert headers["Content-Security-Policy"] == "default-src 'none'; sandbox"
    assert headers["X-Content-Type-Options"] == "nosniff" and headers["Cache-Control"] == "private, no-store"
    assert [fields for (_, _, event), fields in web.logger.events if event == "attachment_downloaded"] == [
        {"mail_id": MAIL1, "index": 0, "size_bytes": len(PDF)}]
    assert web.browser.request("GET", f"/mail/{MAIL1}/original/1").status == 404
    assert web.browser.request("GET", f"/mail/{'f' * 24}/original/0").status == 404
    web.auth.revoke_all()
    assert web.browser.request("GET", f"/mail/{MAIL1}/original/0").status == 303


def test_no_download_after_retention_removed_the_text(web):
    entries = [{"filename": "rechnung.pdf"}]
    AttachmentCache(web.store).prepare(MAIL1, mail(("rechnung.pdf", "application", "pdf", PDF)), entries, KEEP)
    with_mail(web.store, 1, extracted_attachments=entries)
    state = web.store.load("mail-" + MAIL1)
    state["mail"] = None
    web.store.save("mail-" + MAIL1, state)
    assert web.browser.request("GET", f"/mail/{MAIL1}/original/0").status == 404


def test_file_sizes_are_readable():
    from mailhelp.web.review_pages import _size
    assert (_size(10), _size(2048), _size(3 * 1_048_576 + 104_858)) == ("1 KB", "2 KB", "3,1 MB")
