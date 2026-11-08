"""4.7, step 18.1: Message-ID cleaning and the message:// link."""
import pytest

from mailhelp.domain.deep_links import clean_message_id, message_uri


@pytest.mark.parametrize(("raw", "expected"), [
    ("<abc.123@mail.example.test>", "abc.123@mail.example.test"),
    ("  <abc@example.test>  ", "abc@example.test"),
    ("<a@b.test> (Kommentar) <zweite@b.test>", "a@b.test"),          # the first one counts
    ("abc@example.test", "abc@example.test"),                          # bare form
    ("<CAF+x/y=z&q?%#@mail.gmail.test>", "CAF+x/y=z&q?%#@mail.gmail.test"),
])
def test_a_message_id_is_reduced_to_its_value(raw, expected):
    assert clean_message_id(raw) == expected


@pytest.mark.parametrize("raw", [
    None, "", "   ", "<>", "<ohne-at>", "<zwei@@at>", "<@host>", "<id@>", "ohne at", "mit leer@zeichen x",
    "<a b@host>", "<" + "x" * 899 + "@h>",                              # too long
    "<id@hostä>",                                                  # not ASCII
])
def test_no_link_without_a_usable_message_id(raw):
    assert clean_message_id(raw) is None


def test_the_apple_mail_link_encodes_everything_but_the_at_sign():
    assert message_uri("abc.123@mail.example.test") == "message://%3Cabc.123@mail.example.test%3E"
    link = message_uri("CAF+x/y=z&q?%#\"'@host")
    assert link == "message://%3CCAF%2Bx%2Fy%3Dz%26q%3F%25%23%22%27@host%3E"
    assert not set(link.removeprefix("message://")) & set(" <>\"'?#&")
