"""Property-based tests for code that reads untrusted input (Planung 2.1, T6)."""
from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from datetime import time as clock_time
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from zoneinfo import ZoneInfo

import httpx
import pytest
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from mailhelp.domain.extraction import Summary
from mailhelp.domain.prepared import MailHeaders
from mailhelp.domain.revision_errors import ContradictoryRevision
from mailhelp.external.ical import _fold_ical_line, _ical_text
from mailhelp.german_dates import WEEKDAYS, explicit_years, weekday_contradicts
from mailhelp.llm.openrouter import OpenRouterClient, OpenRouterResponseError
from mailhelp.mailbox.mime import MimeLimitExceeded, MimeLimits, extract_display_headers, prepare
from mailhelp.notifications.drafts import message
from mailhelp.notifications.webpush import subscription
from mailhelp.processing.analysis import Analyzer, LlmSchemaValidationFailed
from mailhelp.processing.calendar_parser import _unescape_text, _unfold_ical
from mailhelp.proposals.action_normalization import _parse_date
from mailhelp.temporal_answers import _localize, parse_deterministic_temporal_answer
from tests.fakes.shared_quality_corpus import prompt_config

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


@pytest.mark.slow
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
@example("", "\x80@00\x80\x80\x80\x80\x80\x80\U00010000\U00010000\U00010000\U00010000\U00010000", "", "", "")
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


# Planung 4.1, Schritt 9.10: hostile MIME structures, calendar edge cases and LLM output.

CHARSETS = st.sampled_from(["utf-8", "iso-8859-1", "windows-1252", "utf-16", "utf-7", "x-unknown", ""])
ENCODINGS = st.sampled_from(["7bit", "8bit", "base64", "quoted-printable", "x-bogus", ""])
BOUNDARY = st.text(alphabet=st.characters(min_codepoint=33, max_codepoint=126), min_size=0, max_size=30)
SUBTYPES = {"plain": "text", "html": "text", "octet-stream": "application", "rfc822": "message",
            "mixed": "multipart"}


@st.composite
def hostile_multipart(draw):
    """A multipart mail with possibly mismatched boundaries, charsets and transfer encodings."""
    declared, used = draw(BOUNDARY), draw(st.one_of(st.none(), BOUNDARY))
    parts = []
    for _ in range(draw(st.integers(0, 4))):
        subtype = draw(st.sampled_from(sorted(SUBTYPES)))
        payload = draw(st.one_of(st.binary(max_size=300), st.text(max_size=300).map(str.encode)))
        headers = (f'Content-Type: {SUBTYPES[subtype]}/{subtype}; charset="{draw(CHARSETS)}"\r\n'
                   f"Content-Transfer-Encoding: {draw(ENCODINGS)}\r\n")
        if draw(st.booleans()):
            headers += f'Content-Disposition: attachment; filename="{draw(st.text(max_size=20))}"\r\n'
        parts.append(headers.encode("utf-8", "surrogatepass") + b"\r\n" + payload)
    separator = f"--{declared if used is None else used}".encode()
    closing = draw(st.sampled_from([b"--", b"", b"-"]))
    body = b"".join(separator + b"\r\n" + part + b"\r\n" for part in parts) + separator + closing + b"\r\n"
    head = ("From: Absender <a@example.test>\r\nSubject: Test\r\nMIME-Version: 1.0\r\n"
            f'Content-Type: multipart/mixed; boundary="{declared}"\r\n\r\n').encode()
    return head + body


@FAST
@given(hostile_multipart())
def test_hostile_multipart_structures_only_fail_with_the_documented_errors(raw):
    try:
        result = prepare(raw, 1_000_000, RECEIVED, "Europe/Berlin")
    except (MimeLimitExceeded, ValueError):
        return
    assert isinstance(result["text"], str)
    assert all(isinstance(item, dict) for item in result.get("extracted_attachments", []))


@given(st.dates(min_value=date(1900, 1, 1), max_value=date(2099, 12, 31)), st.sampled_from(sorted(WEEKDAYS)))
def test_a_weekday_contradicts_a_date_exactly_when_it_names_another_day(day, weekday):
    assert weekday_contradicts(day, weekday) is (day.weekday() != WEEKDAYS[weekday])
    assert not weekday_contradicts(day, None)


@given(st.dates(min_value=date(1900, 1, 1), max_value=date(2099, 12, 31)))
@example(date(2028, 2, 29))
def test_explicit_years_find_every_written_year_including_leap_days(day):
    assert explicit_years(f"Frist {day.day}.{day.month}.{day.year}, sonst 19.04") == {str(day.year)}


BERLIN = ZoneInfo("Europe/Berlin")


def utc_instants_showing(naive: datetime) -> set[datetime]:
    """Independent oracle: the UTC instants whose Berlin wall clock reads *naive*."""
    return {naive - offset for offset in (timedelta(hours=1), timedelta(hours=2))
            if (naive - offset).replace(tzinfo=UTC).astimezone(BERLIN).replace(tzinfo=None) == naive}


@given(st.dates(min_value=date(1980, 1, 1), max_value=date(2099, 12, 31)),
       st.times().map(lambda value: value.replace(second=0, microsecond=0)))
@example(date(2026, 3, 29), clock_time(2, 30))
@example(date(2026, 10, 25), clock_time(2, 30))
@example(date(2028, 2, 29), clock_time(23, 59))
def test_local_times_are_unique_or_refused_at_daylight_saving_changes(day, value):
    naive = datetime.combine(day, value)
    instants = utc_instants_showing(naive)
    if len(instants) != 1:
        with pytest.raises(ContradictoryRevision):
            _localize(value, day, BERLIN)
        return
    localized = _localize(value, day, BERLIN)
    assert localized.replace(tzinfo=None) == naive
    assert localized.astimezone(UTC).replace(tzinfo=None) == next(iter(instants))


VALID_JSON = st.recursive(st.none() | st.booleans() | st.integers() | st.text(max_size=20),
                          lambda inner: st.lists(inner, max_size=3)
                          | st.dictionaries(st.text(max_size=8), inner, max_size=3), max_leaves=8)


@st.composite
def model_content(draw):
    """What a model returns: JSON, truncated JSON, Markdown fences, prose or arbitrary text."""
    text = json.dumps(draw(VALID_JSON), ensure_ascii=draw(st.booleans()))
    form = draw(st.sampled_from(["json", "truncated", "fenced", "prose", "text"]))
    if form == "truncated":
        return text[:draw(st.integers(0, max(0, len(text) - 1)))]
    if form == "fenced":
        return f"```json\n{text}\n```"
    if form == "prose":
        return f"Hier ist das Ergebnis: {text}"
    return draw(st.text(max_size=60)) if form == "text" else text


def parsed_or_rejected(content: str):
    try:
        return json.loads(content) if content.strip() else OpenRouterResponseError
    except json.JSONDecodeError:
        return OpenRouterResponseError


@FAST
@given(model_content())
def test_the_client_returns_exactly_valid_json_and_rejects_everything_else(content):
    body = {"id": "synthetic", "choices": [{"message": {"content": content}}]}
    client = OpenRouterClient("synthetic-key", 1, 0, 10_000, httpx.MockTransport(
        lambda request: httpx.Response(200, json=body, request=request)))
    expected = parsed_or_rejected(content)
    try:
        if expected is OpenRouterResponseError:
            with pytest.raises(OpenRouterResponseError):
                client.complete("synthetic/model", {}, "system", {"mail": "x"})
        else:
            assert client.complete("synthetic/model", {}, "system", {"mail": "x"})[1] == expected
    finally:
        client.close()


class FixedAnswer:
    def __init__(self, value):
        self.value = value

    def complete(self, *args, **kwargs):
        return "synthetic", self.value


PROPERTY_MAIL = prepare(b"From: a@example.test\r\nSubject: Test\r\n\r\nBitte bis Freitag antworten.\r\n", 100_000)


@FAST
@given(st.one_of(VALID_JSON, st.fixed_dictionaries(
    {"sentences": st.lists(st.text(max_size=30), max_size=3), "deadlines": st.lists(st.text(max_size=12), max_size=2)})))
def test_analysis_accepts_only_answers_matching_the_stage_schema(value):
    analyzer = Analyzer(FixedAnswer(value), prompt_config(), validation_retries=0, provider_retries=0)
    try:
        expected = Summary.model_validate(value)
    except ValidationError:
        with pytest.raises(LlmSchemaValidationFailed):
            analyzer.summary(PROPERTY_MAIL)
    else:
        assert analyzer.summary(PROPERTY_MAIL)[1] == expected
