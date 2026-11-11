"""5.5.6: the small, safe Markdown subset of help chat answers.

Model output is untrusted. Everything is escaped first; only these structures become markup:
paragraphs and line breaks, ``**bold**``, ``*italic*``, ```code```, numbered and bulleted
lists, headings (shown as a bold line) and fenced code blocks. Raw HTML, images and links never
become markup; a link shows its text only (verified sources are listed below every answer).
Underscores never format, so setting keys such as ``poll_interval_seconds`` stay intact.
"""
from __future__ import annotations

import html
import re

_CODE = re.compile(r"`([^`\n]+)`")
_LINK = re.compile(r"!?\[([^\]\n]*)\]\([^)\n]*\)")
_BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")
_ITALIC = re.compile(r"(?<![*\w])\*(?=[^\s*])([^*\n]*?[^\s*])\*(?![*\w])")
_ORDERED = re.compile(r"(\d{1,3})[.)]\s+(.*)")
_BULLET = re.compile(r"[-*•]\s+(.*)")
_HEADING = re.compile(r"#{1,6}\s+(.*?)\s*#*")
_RULE = re.compile(r"(?:-{3,}|\*{3,}|_{3,})")


def _inline(escaped: str) -> str:
    parts = _CODE.split(escaped)
    rendered = []
    for index, part in enumerate(parts):
        if index % 2:
            rendered.append(f"<code>{part}</code>")
            continue
        part = _LINK.sub(r"\1", part)
        part = _BOLD.sub(r"<strong>\1</strong>", part)
        rendered.append(_ITALIC.sub(r"<em>\1</em>", part))
    return "".join(rendered)


def render(text: str) -> str:
    """Safe HTML for an answer written in the Markdown subset; never raw markup from the text."""
    blocks: list[str] = []
    paragraph: list[str] = []
    items: list[str] = []
    kind, start = "", 1
    code: list[str] | None = None

    def close_paragraph() -> None:
        if paragraph:
            blocks.append("<p>" + "<br>".join(_inline(line) for line in paragraph) + "</p>")
            paragraph.clear()

    def close_list() -> None:
        nonlocal kind
        if items:
            opening = f'<ol start="{start}">' if kind == "ol" and start != 1 else f"<{kind}>"
            blocks.append(opening + "".join(f"<li>{item}</li>" for item in items) + f"</{kind}>")
            items.clear()
        kind = ""

    for line in html.escape(text.replace("\r\n", "\n")).split("\n"):
        stripped = line.strip()
        if code is not None:
            if stripped.startswith("```"):
                blocks.append("<pre><code>" + "\n".join(code) + "</code></pre>")
                code = None
            else:
                code.append(line)
            continue
        if stripped.startswith("```"):
            close_paragraph()
            close_list()
            code = []
            continue
        if not stripped or _RULE.fullmatch(stripped):
            close_paragraph()
            close_list()
            continue
        heading = _HEADING.fullmatch(stripped)
        ordered = _ORDERED.fullmatch(stripped)
        bullet = _BULLET.fullmatch(stripped)
        entry = ordered.group(2) if ordered else bullet.group(1) if bullet else None
        if heading:
            close_paragraph()
            close_list()
            blocks.append(f'<p class="help-md-heading"><strong>{_inline(heading.group(1))}</strong></p>')
        elif entry is not None:
            close_paragraph()
            wanted = "ol" if ordered else "ul"
            if kind != wanted:
                close_list()
                kind = wanted
                start = int(ordered.group(1)) if ordered else 1
            items.append(_inline(entry))
        elif items and line[:1].isspace():
            items[-1] += "<br>" + _inline(stripped)  # an indented continuation of the item above
        else:
            close_list()
            paragraph.append(stripped)
    if code is not None:
        blocks.append("<pre><code>" + "\n".join(code) + "</code></pre>")
    close_paragraph()
    close_list()
    return "".join(blocks)


def plain(text: str) -> str:
    """The answer without Markdown marks, for deriving and comparing short answers."""
    lines = []
    for line in text.replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if stripped.startswith("```") or _RULE.fullmatch(stripped):
            continue
        heading = _HEADING.fullmatch(stripped)
        bullet = _BULLET.fullmatch(stripped)
        lines.append(heading.group(1) if heading else bullet.group(1) if bullet else stripped)
    result = _LINK.sub(r"\1", "\n".join(lines))
    result = _BOLD.sub(r"\1", result)
    result = _ITALIC.sub(r"\1", result)
    return _CODE.sub(r"\1", result)
