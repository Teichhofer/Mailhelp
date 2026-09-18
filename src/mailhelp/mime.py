"""Bounded, defensive MIME preparation without fetching external resources."""
from __future__ import annotations

from dataclasses import dataclass
from email import policy
from email.message import Message
from email.parser import BytesParser
from email.parser import BytesHeaderParser
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
import re
import unicodedata


@dataclass(frozen=True)
class MimeLimits:
    max_mail_bytes: int
    max_header_bytes: int = 64_000
    max_display_header_characters: int = 500
    max_mime_parts: int = 100
    max_decoded_text_bytes: int = 1_000_000
    max_html_characters: int = 1_000_000
    max_html_tags: int = 20_000
    max_html_depth: int = 100
    max_llm_payload_bytes: int = 500_000


class MimeLimitExceeded(ValueError):
    """A safe-to-display resource-limit failure (never contains mail content)."""

    def __init__(self, limit: str) -> None:
        self.limit = limit
        super().__init__(f"E-Mail-Verarbeitung abgebrochen: konfigurierte Grenze '{limit}' überschritten")


def extract_display_headers(raw: bytes, limits: int | MimeLimits | object) -> dict[str, str]:
    """Read only a complete, bounded header block for safe failure displays.

    This deliberately has no full-message fallback.  If the header/body separator
    is outside the inspected prefix, both values are unavailable.
    """
    configured = _limits(limits)
    prefix = raw[:configured.max_header_bytes + 1]
    matches = [(prefix.find(separator), separator) for separator in (b"\r\n\r\n", b"\n\n")]
    matches = [(position, separator) for position, separator in matches if position >= 0]
    if not matches:
        return {"from": "—", "subject": "—"}
    position, separator = min(matches, key=lambda item: item[0])
    end = position + len(separator)
    if end > configured.max_header_bytes:
        return {"from": "—", "subject": "—"}
    message = BytesHeaderParser(policy=policy.default).parsebytes(prefix[:end])

    def display(name: str) -> str:
        values = message.get_all(name, [])
        if len(values) != 1:
            return "—"
        value = _clean_display(str(values[0]))
        return value if value and len(value) <= configured.max_display_header_characters else "—"

    return {"from": display("From"), "subject": display("Subject")}


def _clean_display(value: str) -> str:
    """Normalize an untrusted header into one Telegram-safe display line."""
    value = unicodedata.normalize("NFKC", value)
    value = "".join(" " if char in "\r\n\t" else char for char in value)
    value = "".join(char for char in value if unicodedata.category(char) not in {"Cc", "Cf", "Cs"})
    return re.sub(r"\s+", " ", value).strip()


class _TextHTML(HTMLParser):
    _ignored = frozenset({"script", "style", "noscript", "object", "embed", "iframe", "svg", "canvas"})
    _breaks = frozenset({"address", "article", "br", "div", "footer", "h1", "h2", "h3", "h4", "h5", "h6", "header", "li", "p", "section", "tr"})
    _void = frozenset({"area", "base", "br", "col", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"})

    def __init__(self, limits: MimeLimits) -> None:
        super().__init__(convert_charrefs=True)
        self.limits, self.parts, self.depth, self.tags = limits, [], 0, 0
        self.ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        self.tags += 1
        self.depth += 1
        if self.tags > self.limits.max_html_tags:
            raise MimeLimitExceeded("max_html_tags")
        if self.depth > self.limits.max_html_depth:
            raise MimeLimitExceeded("max_html_depth")
        if self.ignored_depth or tag in self._ignored:
            self.ignored_depth += 1
        elif tag in self._breaks:
            self.parts.append("\n")
        if tag in self._void:
            if self.ignored_depth:
                self.ignored_depth -= 1
            self.depth -= 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in self._void:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if self.ignored_depth:
            self.ignored_depth -= 1
        elif tag in self._breaks:
            self.parts.append("\n")
        self.depth = max(0, self.depth - 1)

    def handle_data(self, data: str) -> None:
        if not self.ignored_depth:
            self.parts.append(data)


def _clean(value: str) -> str:
    value = unicodedata.normalize("NFKC", value.replace("\r\n", "\n").replace("\r", "\n"))
    value = "".join(char for char in value if char in "\n\t" or unicodedata.category(char) not in {"Cc", "Cf", "Cs"})
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in value.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _decode(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        raw = part.get_payload()
        return raw if isinstance(raw, str) else ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def _body(part: Message, limits: MimeLimits) -> str:
    value = _decode(part)
    if part.get_content_type() == "text/html":
        if len(value) > limits.max_html_characters:
            raise MimeLimitExceeded("max_html_characters")
        parser = _TextHTML(limits)
        parser.feed(value)
        parser.close()
        value = "".join(parser.parts)
    return _clean(value)


def _limits(value: int | MimeLimits | object) -> MimeLimits:
    if isinstance(value, int):
        return MimeLimits(value)
    return MimeLimits(**{name: getattr(value, name) for name in MimeLimits.__dataclass_fields__})


def _date_context(message: Message, received_at: datetime, user_timezone: str) -> dict[str, object]:
    """Keep the untrusted source value separate from a conservative interpretation."""
    original = _clean(str(message.get("Date", "")))
    parsed: datetime | None = None
    status = "missing"
    if original:
        try:
            candidate = parsedate_to_datetime(original)
        except (TypeError, ValueError, OverflowError):
            status = "invalid"
        else:
            if candidate.tzinfo is None or candidate.utcoffset() is None:
                status = "naive"
            else:
                parsed, status = candidate, "valid"
                if abs((candidate.astimezone(timezone.utc) - received_at.astimezone(timezone.utc)).total_seconds()) > 7 * 86400:
                    status = "conflicting"
    return {"date_header_original": original, "date_header_parsed": parsed.isoformat() if parsed else None,
            "imap_received_at": received_at.isoformat(), "user_timezone": user_timezone,
            "date_context_status": status}


def prepare(raw: bytes, limits: int | MimeLimits | object,
            received_at: datetime | None = None, user_timezone: str = "UTC") -> dict[str, object]:
    """Return distinct untrusted header/text fields plus non-sensitive preparation metadata."""
    configured = _limits(limits)
    if len(raw) > configured.max_mail_bytes:
        raise MimeLimitExceeded("max_mail_bytes")
    message = BytesParser(policy=policy.default).parsebytes(raw)
    received = received_at or datetime.min.replace(tzinfo=timezone.utc)
    if received.tzinfo is None or received.utcoffset() is None:
        raise ValueError("IMAP-Empfangszeitpunkt muss zeitzonenbehaftet sein")
    leaves = [part for part in message.walk() if not part.is_multipart()]
    if len(leaves) > configured.max_mime_parts:
        raise MimeLimitExceeded("max_mime_parts")
    attachments = 0
    decoded_bytes = 0
    plain: list[str] = []
    html: list[str] = []
    omitted_parts: set[int] = set()
    for part in message.walk():
        if id(part) in omitted_parts:
            continue
        # A filename is an attachment signal even when Content-Disposition is
        # missing or says ``inline``.  When the attachment is itself a MIME
        # message, exclude its complete subtree rather than accidentally
        # treating the enclosed text/plain part as the mail body.
        if part is not message and (
            part.get_content_disposition() == "attachment" or part.get_filename() is not None
        ):
            attachments += 1
            omitted_parts.update(id(descendant) for descendant in part.walk())

    for part in leaves:
        if id(part) in omitted_parts:
            continue
        content_type = part.get_content_type()
        if content_type not in {"text/plain", "text/html"}:
            attachments += 1
            continue
        body = _body(part, configured)
        decoded_bytes += len(body.encode("utf-8"))
        if decoded_bytes > configured.max_decoded_text_bytes:
            raise MimeLimitExceeded("max_decoded_text_bytes")
        (plain if content_type == "text/plain" else html).append(body)
    text = "\n".join(plain or html)
    shortened = bool(re.search(r"\n(?:-- ?$|On .+ wrote:$|Am .+ schrieb .+:$)", text, re.MULTILINE))
    text = re.split(r"\n(?:-- ?$|On .+ wrote:$|Am .+ schrieb .+:$)", text, maxsplit=1, flags=re.MULTILINE)[0].strip()
    result: dict[str, object] = {
        "headers": {name: _clean(str(message.get(source, ""))) for name, source in (
            ("from", "From"), ("subject", "Subject"), ("date", "Date"), ("message_id", "Message-ID"))},
        "text": text,
        "metadata": {"attachments_omitted": attachments, "text_shortened": shortened},
        **_date_context(message, received, user_timezone),
    }
    # Preserve all occurrences for conservative duplicate handling.  They are
    # untrusted input and are normalized only at the duplicate-index boundary.
    result["message_ids"] = [_clean(str(value)) for value in message.get_all("Message-ID", [])]
    if len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > configured.max_llm_payload_bytes:
        raise MimeLimitExceeded("max_llm_payload_bytes")
    return result
