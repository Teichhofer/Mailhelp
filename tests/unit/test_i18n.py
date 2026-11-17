"""7.5.1: the language core – lookup, fallback, negotiation, context and catalog completeness."""
from __future__ import annotations

import ast
import string
from pathlib import Path

import pytest

import mailhelp
from mailhelp.i18n import LOCALE, Locale, current, negotiate, parse, tr, use_locale
from mailhelp.i18n.en import EN
from mailhelp.web.labels import KINDS, STATUSES, label, status_badge

PACKAGE = Path(mailhelp.__file__).parent


def _literal_calls() -> set[str]:
    """Every German text passed literally to tr() in the package."""
    found: set[str] = set()
    for path in PACKAGE.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "tr"
                    and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                found.add(node.args[0].value)
    return found


def _placeholders(text: str) -> set[str]:
    return {name for _literal, name, _spec, _conversion in string.Formatter().parse(text) if name}


def test_every_literal_text_has_an_english_entry_with_the_same_placeholders():
    missing = sorted(text for text in _literal_calls() if text not in EN)
    assert missing == []
    assert [key for key, value in EN.items() if _placeholders(key) != _placeholders(value)] == []


def test_every_shown_label_has_an_english_entry():
    assert [value for value in {*STATUSES.values(), *KINDS.values()} if value not in EN] == []


def test_german_is_the_reference_and_english_falls_back_to_it():
    assert current() == Locale.DE and tr("Klärung nötig") == "Klärung nötig"
    with use_locale(Locale.EN):
        assert tr("Klärung nötig") == "Needs clarification" and current() == Locale.EN
        assert tr("Noch nicht übersetzt") == "Noch nicht übersetzt"
        assert tr("unbekannt ({value})", value="x") == "unknown (x)"
    assert tr("unbekannt ({value})", value="x") == "unbekannt (x)" and LOCALE.get() == Locale.DE


@pytest.mark.parametrize(("cookie", "accept", "default", "expected"), [
    ("en", "de-DE", Locale.DE, Locale.EN),
    ("fr", "fr-FR, en-GB;q=0.8", Locale.DE, Locale.EN),
    (None, "de-AT,de;q=0.9", Locale.EN, Locale.DE),
    (None, "fr, it", Locale.EN, Locale.EN),
    (None, None, Locale.DE, Locale.DE),
    ("", "", Locale.EN, Locale.EN),
])
def test_negotiation_takes_the_choice_then_the_browser_then_the_configuration(cookie, accept, default, expected):
    assert negotiate(cookie, accept, default) == expected


def test_parse_accepts_regional_variants_only_of_supported_languages():
    assert parse("EN-us") == Locale.EN and parse(" de ") == Locale.DE
    assert parse("fr") is None and parse(None) is None and parse("") is None


def test_labels_and_badges_follow_the_language():
    with use_locale(Locale.EN):
        assert label(KINDS, "event") == "Event" and label(STATUSES, "zzz") == "unknown (zzz)"
        assert ">Needs clarification<" in status_badge("needs_clarification")
    assert label(KINDS, "event") == "Termin"


def test_the_page_frame_and_navigation_switch_language():
    from mailhelp.web.pages import OPEN_DECISIONS, layout
    token = OPEN_DECISIONS.set(1)
    try:
        german = layout("Titel", "<p>x</p>", active="/abgleich")
        with use_locale(Locale.EN):
            english = layout("Titel", "<p>x</p>", active="/abgleich")
    finally:
        OPEN_DECISIONS.reset(token)
    assert '<html lang="de">' in german and 'href="/sprache?wert=en" lang="en"' in german and ">English<" in german
    assert '<html lang="en">' in english and 'href="/sprache?wert=de" lang="de"' in english and ">Deutsch<" in english
    assert "Skip to content" in english and 'aria-label="Main navigation"' in english and ">Workspace<" in english
    assert ">Review<" in english and "1 open decision" in english and ">More<" in english
    assert "Zum Inhalt springen" in german and "1 offene Entscheidung" in german
