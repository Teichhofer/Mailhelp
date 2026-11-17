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

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from enum import StrEnum

from .en import EN


class Locale(StrEnum):
    DE = "de"
    EN = "en"


LOCALE: ContextVar[Locale] = ContextVar("mailhelp_locale", default=Locale.DE)
COOKIE = "mailhelp_lang"


def current() -> Locale:
    return LOCALE.get()


def tr(text: str, **params: object) -> str:
    """*text* in the active language; placeholders are filled after the lookup."""
    translated = EN.get(text, text) if LOCALE.get() == Locale.EN else text
    return translated.format(**params) if params else translated


@contextmanager
def use_locale(locale: Locale) -> Iterator[None]:
    token = LOCALE.set(locale)
    try:
        yield
    finally:
        LOCALE.reset(token)


def parse(value: str | None) -> Locale | None:
    """``de``/``en`` (also ``en-GB`` and the like) as a supported language, else ``None``."""
    primary = (value or "").strip().split("-")[0].casefold()
    return Locale(primary) if primary in {Locale.DE, Locale.EN} else None


def negotiate(cookie: str | None, accept_language: str | None, default: Locale) -> Locale:
    """The chosen language (cookie), else the browser's first supported one, else the configured one."""
    chosen = parse(cookie)
    if chosen is not None:
        return chosen
    for part in (accept_language or "").split(","):
        found = parse(part.split(";")[0])
        if found is not None:
            return found
    return default


__all__ = ["COOKIE", "LOCALE", "Locale", "current", "negotiate", "parse", "tr", "use_locale"]
