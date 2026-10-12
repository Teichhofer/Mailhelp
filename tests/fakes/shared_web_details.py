"""Shared synthetic fixtures and doubles; no test-module dependencies."""
from __future__ import annotations

from shared_web_actions import MAIL1, Web, web  # noqa: F401  (fixture)
from web_scenario import mail_id

from mailhelp.models import MailState


def with_mail(store, number, text="Hallo,\nbitte https://evil.test/x <b>klicken</b>.", **content):
    state = store.load_model(f"mail-{mail_id(number)}", MailState)
    mail = {"headers": {"from": "x", "subject": "y"}, "text": text,
            "date_header_parsed": "2026-10-06T10:41:14+00:00",
            "metadata": {"attachments_omitted": 2, "text_shortened": True}, **content}
    store.save(f"mail-{mail_id(number)}", state.model_copy(update={"mail": mail}).model_dump(mode="json"))
