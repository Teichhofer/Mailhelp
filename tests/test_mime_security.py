from email.message import EmailMessage

import pytest

from mailhelp.mime import MimeLimitExceeded, MimeLimits, _clean, _decode, prepare


def limits(**changes):
    values = dict(max_mail_bytes=100_000, max_mime_parts=20, max_decoded_text_bytes=10_000,
                  max_html_characters=10_000, max_html_tags=100, max_html_depth=20,
                  max_llm_payload_bytes=10_000)
    values.update(changes)
    return MimeLimits(**values)


def mail_bytes(text="hello", subtype="plain", charset="utf-8"):
    message = EmailMessage(); message["From"] = "sender@example.test"; message["Subject"] = "subject"
    message.set_content(text, subtype=subtype, charset=charset)
    return message.as_bytes()


def assert_limit(raw, name, **change):
    with pytest.raises(MimeLimitExceeded, match=name) as caught: prepare(raw, limits(**change))
    assert caught.value.limit == name and "hello" not in str(caught.value)


def test_nested_alternative_prefers_plain_and_omits_non_text_parts():
    root = EmailMessage(); root["Subject"] = "=?utf-8?q?Gr=C3=BC=C3=9Fe?="; root.make_mixed()
    alternative = EmailMessage(); alternative.set_content("plain\nOn Someone wrote:\nsecret"); alternative.add_alternative("<p>html</p>", subtype="html")
    root.attach(alternative); root.add_attachment(b"binary", maintype="application", subtype="pdf", filename="doc.pdf")
    inline = EmailMessage(); inline.set_content(b"image", maintype="image", subtype="png"); root.attach(inline)
    result = prepare(root.as_bytes(), limits())
    assert result["text"] == "plain" and result["headers"]["subject"] == "Grüße"
    assert result["metadata"] == {"attachments_omitted": 2, "text_shortened": True}


def test_charset_bad_transfer_encoding_unicode_and_controls():
    raw = b"Content-Type: text/plain; charset=iso-8859-1\r\nContent-Transfer-Encoding: base64\r\n\r\nR3L832U=%%%"
    assert "Grüße" in prepare(raw, limits())["text"]
    assert _clean("Ａ\x00 B\u200b\tC\r\n\n\nD\ud800") == "A B C\n\nD"
    unknown = b"Content-Type: text/plain; charset=x-unknown\r\n\r\nhello\xff"
    assert prepare(unknown, limits())["text"].startswith("hello")
    assert prepare(b"Content-Type: text/plain\r\n\r\n", limits())["text"] == ""


def test_html_ignores_active_embedded_content_and_preserves_lines():
    html = ("<article><p>Hello<br>world</p><script>steal()<img src=x></script><style>hidden</style>"
            "<noscript>fallback</noscript><object>object<img src=x></object><embed>embed</embed>"
            "<iframe>x</iframe><svg>svg</svg><canvas>canvas</canvas><img src='https://invalid/x'></article>")
    assert prepare(mail_bytes(html, "html"), limits())["text"] == "Hello\nworld"


def test_signature_markers_and_unclosed_html_are_safe():
    assert prepare(mail_bytes("answer\nAm Montag schrieb Max:\nold"), limits())["text"] == "answer"
    assert prepare(mail_bytes("answer\n--\nsig"), limits())["metadata"]["text_shortened"] is True
    assert prepare(mail_bytes("</div><p>x", "html"), limits())["text"] == "x"


def test_every_size_and_complexity_limit():
    assert_limit(b"hello", "max_mail_bytes", max_mail_bytes=4)
    multipart = EmailMessage(); multipart.make_mixed()
    for value in ("a", "b"):
        part = EmailMessage(); part.set_content(value); multipart.attach(part)
    assert_limit(multipart.as_bytes(), "max_mime_parts", max_mime_parts=1)
    assert_limit(mail_bytes("hello"), "max_decoded_text_bytes", max_decoded_text_bytes=4)
    assert_limit(mail_bytes("<p>hello</p>", "html"), "max_html_characters", max_html_characters=5)
    assert_limit(mail_bytes("<b><i>x</i></b>", "html"), "max_html_tags", max_html_tags=1)
    assert_limit(mail_bytes("<b><i>x</i></b>", "html"), "max_html_depth", max_html_depth=1)
    assert_limit(mail_bytes("hello"), "max_llm_payload_bytes", max_llm_payload_bytes=5)


def test_html_self_closing_and_raw_string_payload_paths():
    assert prepare(mail_bytes("a<hr/><custom/>b", "html"), limits())["text"] == "ab"
    message = EmailMessage(); message.set_payload("direct")
    assert prepare(message.as_bytes(), limits())["text"] == "direct"
    class Undecodable:
        def __init__(self, value): self.value = value
        def get_payload(self, decode=False): return None if decode else self.value
    assert _decode(Undecodable("fallback")) == "fallback"
    assert _decode(Undecodable([])) == ""
