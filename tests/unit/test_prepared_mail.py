"""Typed read view of the prepared mail (Planung 2.1, A3)."""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from mailhelp.domain.prepared import ImagePreview, MailHeaders, PreparedAttachment, PreparedMail
from mailhelp.mime import prepare

RAW = (b"From: Schule <info@schule.test>\r\nSubject: Ausflug\r\nDate: Mon, 12 Oct 2026 08:00:00 +0200\r\n"
       b"Message-ID: <a@schule.test>\r\n\r\nBitte unterschreiben.")


def test_reads_what_mime_prepare_stores_without_changing_it():
    stored = prepare(RAW, 1_000_000, None, "Europe/Berlin")
    before = json.dumps(stored, ensure_ascii=False)
    mail = PreparedMail.model_validate(stored)
    assert (mail.headers.sender, mail.headers.subject, mail.headers.message_id) == (
        "Schule <info@schule.test>", "Ausflug", "<a@schule.test>")
    assert mail.text == "Bitte unterschreiben." and mail.received == "2026-10-12T08:00:00+02:00"
    # Reading never touches the stored dict, which is also the language-model payload.
    assert json.dumps(stored, ensure_ascii=False) == before


def test_missing_fields_of_old_states_read_as_neutral_defaults():
    mail = PreparedMail.model_validate({"headers": {"from": "a@test"}, "imap_received_at": "2026-01-01T00:00:00+00:00"})
    assert mail.headers.reply_to == "" and mail.extracted_attachments == [] and mail.calendar_events == []
    assert mail.received == "2026-01-01T00:00:00+00:00" and mail.date_context_status == "missing"
    assert PreparedMail.model_validate({}).received is None
    # Unknown fields of other releases stay readable.
    assert PreparedMail.model_validate({"future": 1}).model_extra == {"future": 1}


def test_damaged_optional_values_read_as_absent():
    mail = PreparedMail.model_validate({"headers": "kaputt", "text": 7, "metadata": [],
                                        "extracted_attachments": [{"filename": "a.png", "preview": {"index": "x"}}]})
    assert mail.headers == MailHeaders() and mail.text is None and mail.metadata == {}
    # A preview without a usable index is no preview, the attachment itself remains.
    assert mail.extracted_attachments[0].filename == "a.png" and mail.extracted_attachments[0].preview is None
    with pytest.raises(ValidationError):
        ImagePreview.model_validate({"index": "x"})


def test_only_successfully_extracted_text_is_usable():
    assert PreparedAttachment(text="  Inhalt ").usable_text == "Inhalt"
    assert PreparedAttachment(text="Teil", extraction_status="error").usable_text == ""
    preview = PreparedAttachment.model_validate({"preview": {"index": 2, "size_bytes": 900}}).preview
    assert (preview.index, preview.width, preview.height) == (2, None, None)
