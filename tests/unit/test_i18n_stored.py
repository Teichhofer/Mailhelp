"""7.5.4: German texts made earlier (stored results, Telegram messages) shown in the reader's language."""
import pytest

import mailhelp.i18n as i18n
from mailhelp.i18n import Locale, de, stored, use_locale


def english(text):
    with use_locale(Locale.EN):
        return stored(text)


def test_de_fills_the_german_text_in_every_language():
    with use_locale(Locale.EN):
        assert de("Grund gespeichert: {label}.", label="Werbung") == "Grund gespeichert: Werbung."
        assert de("Bereits entfernt.") == "Bereits entfernt."


def test_german_readers_see_the_stored_text_unchanged():
    assert stored("Grund gespeichert: Werbung oder Rundschreiben.") == "Grund gespeichert: Werbung oder Rundschreiben."


def test_exact_texts_entries_with_values_and_values_of_their_own_are_translated():
    assert english("Bereits entfernt.") == "Already removed."
    assert english("Grund gespeichert: Werbung oder Rundschreiben.") == "Reason saved: Advertising or newsletter."
    # A value that is itself a stored message (the web notice in Telegram) is translated the same way.
    assert english("🌐 Im Web: Mail als irrelevant eingestuft.") == "🌐 On the web: Email classified as irrelevant."
    assert english("Erstellen von „Elternabend“ fehlgeschlagen.") == "Creating “Elternabend” failed."


def test_unknown_and_english_text_stays_as_it_is():
    assert english("Ein ganz eigener Satz") == "Ein ganz eigener Satz"
    assert english("Already removed.") == "Already removed."


def test_several_lines_match_a_whole_entry_or_line_by_line():
    assert english("Absender: Schule\nBetreff: Elternabend") == "Sender: Schule\nSubject: Elternabend"
    assert english("Bereits entfernt.\nEin eigener Satz\nNicht autorisiert.") == (
        "Already removed.\nEin eigener Satz\nNot authorised.")
    # A short generic entry never swallows text of several lines.
    assert english("Aktuelle Entscheidung: x\nNicht autorisiert.") == "Current decision: x\nNot authorised."
    help_text = english(de("Mailhelp – Befehle\n/offen – aktuelle Entscheidung erneut zeigen\n/status – Zahl "
                           "verarbeiteter Mails und alle offenen Vorgänge\n/abbrechen – laufende Rückfrage beenden\n"
                           "/web – Link und Code für die Weboberfläche\n/web_abmelden – alle Geräte der "
                           "Weboberfläche abmelden\n/hilfe – diese Übersicht\n\nVorschläge kommen einzeln "
                           "nacheinander. Rückfragen beantwortest du einfach mit einer Nachricht; die nächste offene "
                           "Frage folgt automatisch. Angelegt wird erst, wenn du „Im Kalender anlegen“ bzw. „Als "
                           "Aufgabe anlegen“ drückst."))
    assert help_text.startswith("Mailhelp – commands\n/offen – show the current decision again")


@pytest.mark.parametrize(("german", "expected"), [
    ("✅ Angelegt im Kalender: „Elternabend“ · 07.01.2027, 11:30 Uhr",
     "✅ Created in the calendar: “Elternabend” · Jan 7, 2027, 11:30"),
    ("✅ Angelegt als Aufgabe: „Formular“ · 07.01.2027, ganztägig", "✅ Created as a task: “Formular” · Jan 7, 2027, all day"),
    ("Beginn 04.12.2026 18:00 Uhr → 11.12.2026 18:00 Uhr", "Beginn Dec 4, 2026, 18:00 → Dec 11, 2026, 18:00"),
    ("Ende 20:30 Uhr", "Ende 20:30"),
    ("Kennung 31.13.2026", "Kennung 31.13.2026"),
])
def test_german_dates_and_times_are_rewritten(german, expected):
    assert english(german) == expected


def test_entries_with_a_repeated_value_and_entries_without_text_of_their_own(monkeypatch):
    monkeypatch.setattr(i18n, "EN", {"{a} und {a}": "{a} and {a}", "{a}{b}": "never", "Ja": "Yes"})
    i18n._templates.cache_clear()
    try:
        assert english("Ja und Ja") == "Yes and Yes"
        assert english("Ja und Nein") == "Ja und Nein"
        assert english("JaNein") == "JaNein"
    finally:
        monkeypatch.undo()
        i18n._templates.cache_clear()
