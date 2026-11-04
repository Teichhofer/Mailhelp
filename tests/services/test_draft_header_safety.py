"""A failed safe email serialization is a validation error, before any IMAP write."""
from email import errors
from email.message import EmailMessage

import pytest

from mailhelp.domain.prepared import MailHeaders
from mailhelp.notifications.drafts import message


def test_stdlib_header_write_failure_is_reported_as_invalid_input(monkeypatch):
    failure = getattr(errors, "HeaderWriteError", errors.MessageError)
    def invalid(self, *args, **kwargs):
        raise failure("Synthetic invalid folded header")
    monkeypatch.setattr(EmailMessage, "as_bytes", invalid)
    with pytest.raises(ValueError, match="Mailkopfzeilen"):
        message(MailHeaders(sender="source@example.test"), "me@example.test", "Synthetic", "<new@example.test>")
