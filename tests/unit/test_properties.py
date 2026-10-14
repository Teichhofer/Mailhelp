"""Property-based tests for code that reads untrusted input (Planung 2.1, T6)."""
from __future__ import annotations

from datetime import UTC, date, datetime
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser

import pytest
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from mailhelp.action_normalization import _parse_date
from mailhelp.calendar_parser import _unescape_text, _unfold_ical
from mailhelp.domain.prepared import MailHeaders
from mailhelp.drafts import message
from mailhelp.external.ical import _fold_ical_line, _ical_text
from mailhelp.mime import MimeLimitExceeded, MimeLimits, extract_display_headers, prepare
from mailhelp.telegram.temporal import parse_deterministic_temporal_answer
from mailhelp.webpush import subscription

RECEIVED = datetime(2026, 10, 12, 8, 0, tzinfo=UTC)
ANY_TEXT = st.text(alphabet=st.characters(codec="utf-8"), max_size=200)
FAST = settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])


def mail_bytes(subject: str, sender: str, body: str, subtype: str) -> bytes:
    mail = EmailMessage(policy=policy.SMTP)
    mail["Subject"], mail["From"] = subject, sender
    mail.set_content(body, subtype=subtype)
    return mail.as_bytes()


@FAST
@given(st.binary(max_size=4000))
def test_preparing_arbitrary_bytes_only_fails_with_the_documented_errors(raw):
    try:
        result = prepare(raw, 1_000_000, RECEIVED, "Europe/Berlin")
    except (MimeLimitExceeded, ValueError):
        return
    assert isinstance(result["text"], str) and isinstance(result["headers"], dict)
    extract_display_headers(raw, 1_000_000)


@FAST
@given(st.text(alphabet=st.characters(blacklist_categories=("Cs", "Cc")), max_size=80),
       st.emails(), ANY_TEXT, st.sampled_from(["plain", "html"]))
def test_prepared_mails_respect_the_payload_limit(subject, sender, body, subtype):
    raw = mail_bytes(subject, sender, body, subtype)
    try:
        prepare(raw, MimeLimits(max_mail_bytes=1_000_000, max_llm_payload_bytes=600), RECEIVED, "UTC")
    except MimeLimitExceeded as exceeded:
        assert exceeded.limit in {"max_llm_payload_bytes", "max_html_tags", "max_html_depth",
                                  "max_html_characters", "max_decoded_text_bytes"}


@FAST
@given(ANY_TEXT, ANY_TEXT, ANY_TEXT, ANY_TEXT, ANY_TEXT)
def test_reply_drafts_never_carry_injected_headers(sender, reply_to, subject, parent, references):
    headers = MailHeaders.model_validate({"from": sender, "reply_to": reply_to, "subject": subject,
                                          "message_id": parent, "references": references})
    try:
        data = message(headers, "me@example.test", "Text", "<new@example.test>")
    except ValueError:
        return
    parsed = BytesParser(policy=policy.default).parsebytes(data)
    assert {key.casefold() for key in parsed.keys()} <= {
        "from", "to", "subject", "in-reply-to", "references", "date", "message-id",
        "content-type", "content-transfer-encoding", "mime-version"}
    assert len(parsed.get_all("To")) == 1 and "\n" not in str(parsed["Subject"])


@FAST
@given(st.one_of(st.text(max_size=120), st.builds(
    "{}://{}{}/{}".format, st.sampled_from(["https", "http", "ftp"]),
    st.sampled_from(["fcm.googleapis.com", "evil.test", "web.push.apple.com.evil.test",
                     "x.notify.windows.com", "user:pw@fcm.googleapis.com", "fcm.googleapis.com#"]),
    st.sampled_from(["", ":443", ":8443"]), st.text(max_size=20))))
def test_push_subscriptions_only_reach_known_providers(endpoint):
    from urllib.parse import urlsplit
    value = {"endpoint": endpoint, "keys": {"p256dh": "A" * 87, "auth": "A" * 22}}
    try:
        subscription(value)
    except (ValueError, KeyError):
        return
    url = urlsplit(endpoint)
    assert url.scheme == "https" and url.port in (None, 443) and not url.username
    assert url.hostname in {"fcm.googleapis.com", "updates.push.services.mozilla.com", "web.push.apple.com"} or (
        url.hostname.endswith(".notify.windows.com"))


@FAST
@given(st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=200).map(str.strip))
@example("C:" + chr(92) + "new" + chr(92) + "Nordsee;Plan," + chr(92) + chr(92))
def test_calendar_text_survives_escaping_and_parsing(text):
    assert _unescape_text(_ical_text(text)) == text.replace("\r\n", "\n").replace("\r", "\n").strip()


@FAST
@given(st.text(alphabet=st.characters(blacklist_categories=("Cs", "Cc", "Zl", "Zp")), min_size=1,
               max_size=400).map(str.strip).filter(bool))
def test_folded_calendar_lines_unfold_to_the_original(line):
    folded = _fold_ical_line(line)
    assert all(len(part.encode("utf-8")) <= 75 for part in folded.split("\r\n"))
    assert _unfold_ical(folded) == [line]


@FAST
@given(st.dates(min_value=date(1900, 1, 1), max_value=date(2099, 12, 31)),
       st.sampled_from(["%d.%m.%Y", "%Y-%m-%d"]))
def test_explicit_dates_parse_back_to_the_same_day(day, layout):
    parsed = _parse_date(day.strftime(layout), "user")
    assert isinstance(parsed, tuple) and parsed[0] == day


@FAST
@given(ANY_TEXT, st.one_of(st.none(), st.dates()))
def test_free_answers_never_break_the_temporal_parser(answer, reference):
    parsed = parse_deterministic_temporal_answer(answer, reference)
    assert parsed is None or parsed.__class__.__name__ == "DeterministicTemporalAnswer"


@pytest.mark.parametrize("answer, reference", [("30", None), ("heute 25 Uhr", date(2026, 1, 10)),
                                               ("31.02.2026", None), ("2026-13-01", None)])
def test_impossible_times_and_dates_are_no_deterministic_answer(answer, reference):
    # Regression (found by the property test above): "30" was read as 30 o'clock and
    # raised ValueError instead of leaving the answer to the interpretation step.
    assert parse_deterministic_temporal_answer(answer, reference) is None
