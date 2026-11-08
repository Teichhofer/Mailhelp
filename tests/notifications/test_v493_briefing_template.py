"""The briefing template contains only safe navigation, never action/approval forms."""
from datetime import UTC, datetime
from html.parser import HTMLParser

import pytest

from mailhelp.notifications.briefing_aggregate import BriefingContent, BriefingItem, BriefingSummary
from mailhelp.notifications.briefing_template import render_briefing

NOW = datetime(2026, 11, 8, 6, tzinfo=UTC)


class Links(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.urls, self.bad = [], []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "form", "img", "iframe"}:
            self.bad.append(tag)
        self.urls.extend(value for key, value in attrs if key == "href")


def test_html_and_text_include_dates_tasks_questions_summaries_and_safe_links():
    entry = BriefingItem("a" * 24, "p_one", 3, '<script>alert("x")</script>', "09.11.2026, 09:00 Uhr",
                         "Klärung nötig", ("Uhrzeit bestätigen?",))
    relevance = BriefingItem("b" * 24, None, 1, "Relevanz?", "", "Relevanz klären")
    summary = BriefingSummary("c" * 24, "Unterlagen & Frist", "Inhalt <b>untrusted</b>", ("10.11.2026",))
    content = BriefingContent(NOW, NOW, (entry,), (entry,), (relevance,), (summary,), 7, 4, 1)
    result = render_briefing(content, "07:00", "Europe/Berlin", "https://mailhelp.example.test/")
    assert result["subject"] == "[Mailhelp Briefing 07:00] 1 Termine, 1 Aufgaben"
    for part in ("07:00 Uhr", "10.11.2026", "7 Mails", "4 als irrelevant", "Version 3", "beschädigt"):
        assert part in result["text"] and part in result["html"]
    assert "&lt;script&gt;" in result["html"] and "<b>untrusted</b>" not in result["html"]
    links = Links(result["html"])
    assert not links.bad and all(url.startswith("https://mailhelp.example.test/") for url in links.urls)
    assert any("/vorschlag/" in url for url in links.urls) and any("/mail/" in url for url in links.urls)
    assert not any("/aktion" in url or "csrf" in url or "code=" in url for url in links.urls)


def test_empty_digest_and_large_lists_remain_bounded_and_report_overflow():
    assert "Alles ruhig" in render_briefing(BriefingContent(NOW, NOW), "07:00", "UTC", "http://localhost:8765")["text"]
    entry = BriefingItem("a", "p", 1, "Offen", "", "Bestätigen")
    summary = BriefingSummary("a", "Betreff", "Text", ())
    result = render_briefing(BriefingContent(NOW, NOW, tasks=(entry,) * 51, summaries=(summary,) * 51),
                             "13:00", "UTC", "https://host.test")
    for key in ("html", "text"):
        assert "1 weitere Einträge" in result[key] and "1 weitere Zusammenfassungen" in result[key]


@pytest.mark.parametrize("base", ["javascript:alert(1)", "https://user:secret@host.test", "https://host.test/path",
                                  "https://host.test/?key=secret", "https://host.test/#fragment", "https://bad host.test",
                                  "http:///", "https://host.test/\n"])
def test_invalid_or_credential_bearing_base_urls_are_rejected(base):
    with pytest.raises(ValueError, match="Basisadresse"):
        render_briefing(BriefingContent(NOW, NOW), "07:00", "UTC", base)


def test_even_untrusted_identifier_characters_cannot_change_the_link_destination():
    entry = BriefingItem('../?x="y"', "p/name", 1, "Text", "", "")
    html = render_briefing(BriefingContent(NOW, NOW, tasks=(entry,)), "18:00", "UTC", "https://host.test")["html"]
    assert "%2F%3Fx%3D%22y%22/p%2Fname" in html and not Links(html).bad
