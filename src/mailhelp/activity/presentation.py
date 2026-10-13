"""Safe report filters, source highlighting and content-free refresh signals."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from html import escape
from urllib.parse import parse_qs

from .export import event_rows
from .models import ActivityReport, ReportEvent, ReportMail


@dataclass(frozen=True)
class ReportFilter:
    month: str = ""
    sender: str = ""
    uncertain: bool = False
    excluded: bool = False

    @classmethod
    def parse(cls, query: str) -> ReportFilter:
        values = parse_qs(query, max_num_fields=8)
        month = values.get("month", [""])[0]
        return cls(month if re.fullmatch(r"\d{4}-\d{2}", month) else "",
                   values.get("sender", [""])[0][:500], values.get("uncertain") == ["on"],
                   values.get("excluded") == ["on"])

    def rows(self, mails: list[ReportMail]) -> list[tuple[int, ReportEvent, ReportMail]]:
        return [(number, event, mail) for number, event, mail in event_rows(mails, self.excluded)
                if (not self.month or event.day.isoformat().startswith(self.month))
                and (not self.sender or self.sender.casefold() in mail.sender.casefold())
                and (not self.uncertain or mail.confidence == "low" and mail.user_relevant is None)]


def highlighted_text(mail: ReportMail) -> str:
    """Match whitespace-normalized verbatim quotes, escaping every untrusted part."""
    spans: list[tuple[int, int]] = []
    for event in mail.events:
        words = event.evidence.split()
        if words:
            pattern = r"\s+".join(re.escape(word) for word in words)
            spans.extend(match.span() for match in re.finditer(pattern, mail.text, re.IGNORECASE))
    parts: list[str] = []
    end = 0
    for start, finish in sorted(spans):
        if start < end:
            continue
        parts.extend((escape(mail.text[end:start]), "<mark>", escape(mail.text[start:finish]), "</mark>"))
        end = finish
    parts.append(escape(mail.text[end:]))
    return "".join(parts)


def fingerprint(report: ActivityReport, mails: list[ReportMail]) -> str:
    value = [report.model_dump(mode="json"), [mail.model_dump(mode="json") for mail in mails]]
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
