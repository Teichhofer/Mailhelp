"""7.5: languages of the human interface – German (reference) and English.

The German text is the message id: ``tr("Klärung nötig")`` returns it unchanged in German and
the catalog entry in English. A missing entry falls back to German, so a page never shows a key
instead of text; the completeness test finds every literal ``tr()`` call without an English entry
and every entry whose placeholders differ. Model prompts, topics and extraction stay German
(Planung 7.5, Kernvorgabe): this module is only used where people read Mailhelp.

The active language lives in a context variable, set per web request or Telegram message, so
threads and requests never see each other's language.
"""
from __future__ import annotations

import re
import string
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from enum import StrEnum
from functools import cache
from types import MappingProxyType

from .en import EN


class Locale(StrEnum):
    DE = "de"
    EN = "en"


LOCALE: ContextVar[Locale] = ContextVar("mailhelp_locale", default=Locale.DE)
WORDING: ContextVar[Mapping[str, str]] = ContextVar("mailhelp_wording", default=MappingProxyType({}))
COOKIE = "mailhelp_lang"


def current() -> Locale:
    return LOCALE.get()


def tr(text: str, **params: object) -> str:
    """*text* in the active language; placeholders are filled after the lookup."""
    text = WORDING.get().get(text, text)
    translated = EN.get(text, text) if LOCALE.get() == Locale.EN else text
    return translated.format(**params) if params else translated


def heading(text: str) -> str:
    """*text* translated as a title: a count word like "Mails" becomes "Emails", not "emails"."""
    translated = tr(text)
    return translated[:1].upper() + translated[1:]


class Message(str):
    """An owned label: translate at rendering, retaining its German identity in tables and JSON.

    Plain strings from mails or users never get this marker. Labels can consequently remain in
    immutable module-level tables without capturing the language of the importing thread.
    """

    def __str__(self) -> str:
        return tr(super().__str__())

    def __format__(self, spec: str) -> str:
        return format(str(self), spec)

    def __add__(self, other: str) -> str:
        return str(self) + other

    def __radd__(self, other: str) -> str:
        return other + str(self)


def msg(text: str) -> str:
    return Message(text)


def de(text: str, **params: object) -> str:
    """7.5.4: a German text that is stored or sent on and translated where it is read (``stored``).

    Results of actions and Telegram messages are made in German whatever the language; the web page
    and the Telegram transport show them in their reader's language. Marking them lets the
    completeness test find texts without an English entry.
    """
    return text.format(**params) if params else text


@cache
def _templates() -> tuple[tuple[str, re.Pattern[str], str, bool], ...]:
    """Catalog entries with placeholders as patterns, the most specific (longest literal text) first."""
    found = []
    for german, english in EN.items():
        pattern, literal, names = "", "", set()
        for text, name, _spec, _conversion in string.Formatter().parse(german):
            pattern += re.escape(text)
            literal += text
            if name:
                pattern += f"(?P={name})" if name in names else f"(?P<{name}>.*?)"
                names.add(name)
        if names and literal.strip():
            prefix = next(iter(string.Formatter().parse(german)))[0]
            found.append((len(literal), prefix, re.compile(pattern, re.DOTALL), english, "\n" in german))
    found.sort(key=lambda item: -item[0])
    return tuple((prefix, pattern, english, lines) for _size, prefix, pattern, english, lines in found)


# "07.01.2027, 14:30 Uhr", "07.01.2027 14:30 Uhr", "07.01.2027" and "14:30 Uhr" as written by German formatting.
_GERMAN_TIME = re.compile(r"\b(?:(\d{2})\.(\d{2})\.(\d{4})(?:(,? )(\d{2}:\d{2}) Uhr)?|(\d{2}:\d{2}) Uhr)")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _english_time(match: re.Match[str]) -> str:
    day_, month, year, _separator, clock, alone = match.groups()
    if alone is not None:
        return alone
    if not 1 <= int(month) <= 12:
        return match.group(0)
    text = f"{_MONTHS[int(month) - 1]} {int(day_)}, {year}"
    return f"{text}, {clock}" if clock is not None else text


def _translate(text: str) -> str:
    if text in EN:
        return EN[text]
    several = "\n" in text
    for prefix, pattern, english, lines in _templates():
        # Text of several lines only matches an entry of several lines, never a short generic one.
        if (lines or not several) and text.startswith(prefix):
            match = pattern.fullmatch(text)
            if match:
                # A value is shorter than the text (the entry has text of its own), so this ends.
                return english.format(**{name: _translate(value) for name, value in match.groupdict().items()})
    if several:
        return "\n".join(_translate(line) for line in text.split("\n"))
    return _GERMAN_TIME.sub(_english_time, text)


def stored(text: str) -> str:
    """7.5.4: a German text made earlier (a stored result, a message built in the background).

    The text, else each of its lines, is looked up as a whole or matched against the entries with
    placeholders, whose values are translated the same way; German dates and times are rewritten.
    Anything unknown stays as it is, also English text.
    """
    text = WORDING.get().get(text, text)
    if LOCALE.get() != Locale.EN:
        return text
    return _translate(text)


@contextmanager
def use_locale(locale: Locale, *, wording: Mapping[str, str] | None = None) -> Iterator[None]:
    token = LOCALE.set(locale)
    words = WORDING.set(wording) if wording is not None else None
    try:
        yield
    finally:
        if words is not None:
            WORDING.reset(words)
        LOCALE.reset(token)


def parse(value: str | None) -> Locale | None:
    """``de``/``en`` (also ``en-GB`` and the like) as a supported language, else ``None``."""
    tag = (value or "").strip()
    if re.fullmatch(r"[a-z]{2,8}(?:-[a-z0-9]{1,8})*", tag, re.I) is None:
        return None
    primary = tag.split("-")[0].casefold()
    return Locale(primary) if primary in {Locale.DE, Locale.EN} else None


def negotiate(cookie: str | None, accept_language: str | None, default: Locale) -> Locale:
    """The chosen language (cookie), else the browser's first supported one, else the configured one."""
    chosen = parse(cookie)
    if chosen is not None:
        return chosen
    selected, quality = default, 0.0
    for part in (accept_language or "")[:8192].split(",")[:64]:
        match = re.fullmatch(
            r"\s*([a-z]{2,8}(?:-[a-z0-9]{1,8})*)\s*(?:;\s*q=(0(?:\.\d{0,3})?|1(?:\.0{0,3})?))?\s*",
            part, re.I)
        if match is None:
            continue
        found = parse(match[1])
        weight = float(match[2]) if match[2] is not None else 1.0
        if found is not None and weight > quality:
            selected, quality = found, weight
    return selected


__all__ = ["COOKIE", "LOCALE", "Locale", "Message", "current", "de", "heading", "msg", "negotiate", "parse", "stored",
           "tr", "use_locale"]
