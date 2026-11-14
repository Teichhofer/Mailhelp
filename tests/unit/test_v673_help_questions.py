"""Tests for typical help questions matching Bedienung.md sections (Planung 6.7, D3, 3.3).

Verifies D3:
- 10 typical user questions about daily workflows find their matching section in the help index
  without LLM calls.
"""
from __future__ import annotations

import pytest

from mailhelp.helpdocs import load


QUESTIONS: list[tuple[str, str]] = [
    (
        "Wie wische ich auf dem Smartphone, um einen Termin anzulegen oder zu verwerfen?",
        "bedienung/wischen-auf-dem-telefon",
    ),
    (
        "Was mache ich bei einem Widerspruch oder einer Rückfrage?",
        "bedienung/rueckfragen-und-widersprueche",
    ),
    (
        "Wie funktioniert der Vorschlagsabgleich?",
        "bedienung/vorschlagsabgleich",
    ),
    (
        "Kann ich einen versehentlich angelegten Termin wieder entfernen?",
        "bedienung/angelegte-eintraege-wieder-entfernen",
    ),
    (
        "Was bedeutet Eintragung noch nicht bestätigt nach dem Anlegen?",
        "bedienung/nach-dem-anlegen",
    ),
    (
        "Wo kann ich verarbeitete Mails nachlesen oder erneut analysieren?",
        "bedienung/mails-nachlesen-und-verlauf",
    ),
    (
        "Wie starte ich einen Lernlauf für Themen aus dem Postfach?",
        "bedienung/lernlauf-in-der-weboberflaeche-starten",
    ),
    (
        "Wie lernt Mailhelp Regeln aus meinen bisherigen Entscheidungen?",
        "bedienung/aus-entscheidungen-lernen",
    ),
    (
        "Wie kann ich die Annahmequote messen und verbessern?",
        "bedienung/annahmequote-messen-und-verbessern",
    ),
    (
        "Wie kann ich eine fehlgeschlagene Mail erneut versuchen oder ablegen?",
        "bedienung/fehlgeschlagene-mails",
    ),
]


@pytest.mark.parametrize(("question", "expected_section_id"), QUESTIONS)
def test_typical_questions_find_corresponding_section(question: str, expected_section_id: str) -> None:
    base = load()
    matched = [section.id for section in base.select(question)]
    assert expected_section_id in matched
    # It should even be the top result or in the first two results
    assert matched[0] == expected_section_id
