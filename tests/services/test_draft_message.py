"""4.8, step 19.2: a reply draft threads correctly and carries exactly one "Re:"."""
from email import policy
from email.parser import BytesParser

import pytest

from mailhelp.domain.prepared import MailHeaders
from mailhelp.notifications.drafts import message, reply_subject


@pytest.mark.parametrize(("subject", "expected"), [
    ("Angebot", "Re: Angebot"),
    ("AW: Angebot", "Re: Angebot"),                      # German Outlook
    ("Re: AW: RE: Angebot", "Re: Angebot"),              # several markers
    ("Antw: Frage", "Re: Frage"), ("SV: Fråga", "Re: Fråga"), ("Re[2]: Frage", "Re: Frage"),
    ("WG: Einladung", "Re: WG: Einladung"),              # a forward marker stays meaningful
    ("Rechnung: März", "Re: Rechnung: März"),            # a word, not a marker
])
def test_exactly_one_reply_marker(subject, expected):
    assert reply_subject(subject) == expected


def test_the_draft_answers_in_the_existing_thread():
    headers = MailHeaders.model_validate({
        "from": "Kundin <kundin@example.test>", "reply_to": "Büro <buero@example.test>", "subject": "AW: Angebot",
        "message_id": "<m2@example.test>", "references": "<m0@example.test> <m1@example.test>"})
    parsed = BytesParser(policy=policy.default).parsebytes(
        message(headers, "Ich <ich@example.test>", "Vielen Dank für Ihre Anfrage.\n\nGrüße", "<d1@draft.local>"))
    assert parsed["To"] == "buero@example.test"            # the reply address of the mail
    assert parsed["Subject"] == "Re: Angebot"
    assert parsed["In-Reply-To"] == "<m2@example.test>"
    assert parsed["References"] == "<m0@example.test> <m1@example.test> <m2@example.test>"
    assert parsed.get_content_charset() == "utf-8" and "Vielen Dank" in parsed.get_content()
