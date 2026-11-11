"""5.5.6 regression: the help chat found no documentation for questions about learning.

The released guides described the learning mode only as two settings, and words such as
"Lernfunktion", "lernt" or "Lernen" matched nothing. These questions must reach the guide.
"""
import pytest

from mailhelp.helpdocs import load
from mailhelp.web.settings_search import search

GUIDE = {"bedienung/lernmodus-lernfunktion", "bedienung/lernlauf-in-der-weboberflaeche-starten",
         "bedienung/ergebnis-pruefen-und-uebernehmen", "bedienung/lernmodus-im-terminal-und-einstellungen",
         "bedienung/lernbestand"}


@pytest.mark.parametrize(("question", "expected"), [
    ("Wie funktioniert die Lernfunktion?", "bedienung/lernmodus-lernfunktion"),
    ("Was macht Lernen?", "bedienung/lernmodus-lernfunktion"),
    ("Wie lernt Mailhelp neue Themen?", "bedienung/lernmodus-lernfunktion"),
    ("Wie starte ich einen Lernlauf?", "bedienung/lernlauf-in-der-weboberflaeche-starten"),
    ("Was kostet ein Lernlauf?", "bedienung/lernlauf-in-der-weboberflaeche-starten"),
    ("Wie übernehme ich die gelernten Themen?", "bedienung/ergebnis-pruefen-und-uebernehmen"),
    ("Was ist der Lernbestand?", "bedienung/lernbestand"),
])
def test_questions_about_learning_reach_the_guide(question, expected):
    chosen = [section.id for section in load().select(question)]
    assert expected in chosen
    assert chosen[0] in GUIDE | {"web-einstellungen/lernmodus"}


def test_the_guide_names_the_real_controls_of_the_learning_page():
    text = " ".join(" ".join(section.text for section in load().sections if section.id in GUIDE).split())
    for label in ("Neuer Lernlauf", "Schätzung anzeigen", "Lesenden Lernlauf kostenpflichtig starten",
                  "Pausieren", "Fortsetzen", "Abbrechen", "Auswahl als Entwurf speichern",
                  "Ordnerauswahl speichern", "Ausgewählte Themen, Filter und Ordner ausdrücklich übernehmen",
                  "Verwerfen", "Konfiguration neu laden", "--learn"):
        assert label in text


def test_the_settings_search_knows_the_word_lernfunktion():
    assert {entry.key for entry in search("Lernfunktion")} >= {"learning.parallel_llm_calls"}
