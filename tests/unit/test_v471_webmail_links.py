"""4.7, step 18.2: Gmail and Outlook web links and the choice by IMAP server."""
import pytest

from mailhelp.domain.deep_links import gmail_url, mail_link, outlook_url, resolve_client

ID = "CAF+x/y=z&q?#@mail.gmail.test"


def test_gmail_searches_exactly_the_message_id():
    assert gmail_url(ID) == ("https://mail.google.com/mail/u/0/#search/rfc822msgid%3A"
                             "CAF%2Bx%2Fy%3Dz%26q%3F%23%40mail.gmail.test")


def test_outlook_searches_the_message_id():
    assert outlook_url(ID) == "https://outlook.office.com/mail/search?q=CAF%2Bx%2Fy%3Dz%26q%3F%23%40mail.gmail.test"


@pytest.mark.parametrize(("configured", "host", "kind"), [
    ("auto", "imap.gmail.com", "gmail_web"),
    ("auto", " IMAP.GoogleMail.com. ", "gmail_web"),
    ("auto", "outlook.office365.com", "apple_mail"),    # Outlook web is never chosen automatically
    ("auto", "imap.example.test", "apple_mail"),
    ("auto", None, "apple_mail"),
    ("outlook_web", "imap.gmail.com", "outlook_web"),   # an explicit choice wins
    ("none", "imap.gmail.com", "none"),
])
def test_auto_follows_the_imap_server(configured, host, kind):
    assert resolve_client(configured, host) == kind


def test_a_link_needs_a_message_id_and_a_link_kind():
    assert mail_link("<abc@example.test>", "apple_mail") == "message://%3Cabc@example.test%3E"
    assert mail_link("<abc@example.test>", "gmail_web").startswith("https://mail.google.com/")
    assert mail_link("<abc@example.test>", "outlook_web").startswith("https://outlook.office.com/")
    assert mail_link("<abc@example.test>", "none") is None
    assert mail_link("", "gmail_web") is None and mail_link(None, "apple_mail") is None
