"""5.7.4 (S5): the help chat and the settings search find the new learning area and topic editing.

Deterministic counterpart of the real-model check: the help chat can only answer what its
section choice offers, so these questions must reach the released guide sections.
"""
import pytest

from mailhelp.helpdocs import load
from mailhelp.web.settings_search import search

RULES, EDIT = "bedienung/aus-entscheidungen-lernen", "web-einstellungen/thema-bearbeiten"


@pytest.mark.parametrize(("question", "expected"), [
    ("Wo finde ich das Regellernen?", RULES),
    ("Wie verbessere ich meine Themenregeln mit meinen Entscheidungen?", RULES),
    ("Was zeigt die Lernübersicht?", "bedienung/lernmodus-lernfunktion"),
    ("Wie bearbeite ich ein Thema?", EDIT),
    ("Warum muss ich eine Themenänderung erst prüfen?", EDIT),
    ("Wie suche ich in den Themen?", "web-einstellungen/themenuebersicht"),
])
def test_questions_about_learning_and_topics_reach_the_guide(question, expected):
    assert expected in [section.id for section in load().select(question)]


def test_the_guide_names_the_real_controls_of_57():
    base = load()
    text = " ".join(" ".join(section.text for section in base.sections
                             if section.id.startswith(("bedienung/", "web-einstellungen/"))).split())
    for label in ("Aus Entscheidungen lernen öffnen", "Änderung prüfen", "Änderung ausdrücklich speichern",
                  "Weiter bearbeiten", "Unveränderte Felder anzeigen", "Auszug anzeigen", "+ neu", "− entfernt",
                  "Ausstehende Themenänderungen", "Neu laden", "1. Postfach und Ordner", "3. Kosten und Budget"):
        assert label in text, label
    # The learning chapter now holds both functions; rule learning is no longer under "Weitere Seiten".
    rules = base.get(RULES)
    assert rules is not None and rules.path[:2] == ("Alltagsbedienung", "Lernmodus (Lernfunktion)")


@pytest.mark.parametrize(("query", "key"), [
    ("Regeln lernen", "page:regellernen"), ("Themenregeln", "page:regellernen"),
    ("Themen verbessern", "page:regellernen"), ("Thema bearbeiten", "page:themen"),
])
def test_the_settings_search_finds_the_pages(query, key):
    assert key in {entry.id for entry in search(query)}
