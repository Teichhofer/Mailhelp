# Mailhelp 7.5 – Mehrsprachigkeit und englische Lokalisierung

Geprüft für Mailhelp 7.5.

Umsetzung von [Planung 7.5](Planung-7.5.md) in Patches ab 7.5.1. Zwischenstand: Der Plan ist erst
erfüllt, wenn Weboberfläche, JavaScript, Telegram, CLI und Hilfetexte zweisprachig sind; die
Prompts, Themen und die Auswertung der Mails bleiben nach der Kernvorgabe deutsch.

## 7.5.1 – Sprachkern, Spracheinstellung und Seitenrahmen (L1)

- **Modul `mailhelp.i18n`:** `Locale` (de, en), die aktive Sprache als Kontextvariable je Anfrage,
  `tr()` zum Übersetzen, `use_locale()` für einen begrenzten Abschnitt und `negotiate()` für die
  Sprachwahl. Englische Texte stehen in `i18n/en.py`.
- **Abweichung vom Plan bei den Schlüsseln:** Statt Punktschlüsseln (`status.needs_clarification`)
  ist der deutsche Text selbst der Schlüssel, wie bei gettext. Fehlt eine Übersetzung, erscheint der
  deutsche Text, nie ein Schlüssel; der deutsche Katalog ist damit der Code selbst und kann nicht
  vom Code abweichen. Der Vollständigkeitstest (`tests/unit/test_i18n.py`) findet jeden wörtlichen
  `tr()`-Aufruf ohne englischen Eintrag und jeden Eintrag mit abweichenden Platzhaltern.
- **Sprachwahl:** Ein Browser, der eine Sprache gewählt hat (Cookie `mailhelp_lang`), sieht diese;
  sonst die erste unterstützte Sprache aus `Accept-Language`; sonst die Einstellung `language`
  (`de` Standard, `en`). Unbekannte Sprachen fallen auf die nächste Stufe zurück.
- **Einstellung `language`** unter Einstellungen → Mailabruf und Betrieb und in `config.yaml`; wirkt
  nach einem Neustart. Sie zählt nicht zur Analyse; alle Analyse-Fingerabdrücke bleiben gleich.
- **Seitenrahmen:** `<html lang>` folgt der Sprache; Navigation, Bereichsnamen, Sprunglink, Menü
  „Mehr“ und die Zahl offener Entscheidungen sind übersetzt. Am Ende der Navigation steht ein Link
  zur anderen Sprache (`/sprache?wert=en`), der die Wahl im Cookie merkt und zur Seite zurückführt;
  er folgt nur einem Rückweg auf denselben Host.
- **Statusbezeichnungen:** Status, Ereignisse, Quellen und Arten (`web/labels.py`) erscheinen in der
  aktiven Sprache, auch in jedem Status-Badge.
- Die deutsche Ausgabe bleibt bis auf den neuen Sprachlink unverändert (Golden-Seiten neu
  geschrieben; geändert hat sich nur dieser Link).

**Offen für die nächsten Patches.** Datums-, Zeit- und Zahlenformate (7.5.2), Telegram (7.5.3), die
übrigen Seiteninhalte (7.5.4), JavaScript und Einstellungshilfen (7.5.5), CLI und Abnahme (7.5.6).
Bis dahin sind auf Englisch nur Rahmen, Navigation und Statusbezeichnungen übersetzt.

Prüfung 7.5.1: 5 720 Python-Tests mit 100 % Zeilen- und Branch-Abdeckung; Browser 956 bestanden ohne
Fehler, JavaScript zu 100 % abgedeckt.

## 7.5.2 – Datum, Uhrzeit, Zahlen und Dauern (L2)

- `mailhelp.i18n.formatting`: Datum (`07.01.2027` / `Jan 7, 2027`), Uhrzeit mit „Uhr“ nur auf Deutsch,
  auf Englisch im 24-Stunden-Format (`14:30`), damit keine Zeit ein AM/PM braucht, Tausendertrenner
  (`1.234` / `1,234`) und Dezimalzahlen.
- Eingebunden in `format_datetime_local`, `duration_text` (`Min.`, `Std.`, `Tage` / `min`, `h`,
  `days`), `german_number` und die Terminzeile der Karten: einzelne Tage, Spannen über mehrere Tage,
  ganztägig, Dauer mit „höchstens“ und „Ende angenommen: Standarddauer …“.
- Die deutsche Ausgabe bleibt Zeichen für Zeichen gleich (Golden-Seiten unverändert).

**Abweichung.** Der Plan nennt für Englisch wahlweise 12- oder 24-Stunden-Zeit. Mailhelp zeigt
24-Stunden-Zeit: Sie ist eindeutig, passt zu den gespeicherten Zeiten und zur Eingabe in Formularen.

Prüfung 7.5.2: 5 735 Python-Tests mit 100 % Zeilen- und Branch-Abdeckung; Browser 956 bestanden ohne
Fehler, JavaScript zu 100 % abgedeckt.

## 7.5.3 – Telegram (L3)

- Telegram hat keinen Browser; seine Texte folgen der Einstellung `language`. Der Dialog führt jeden
  Abruf in dieser Sprache aus (`TelegramDialogController.locale`, gesetzt beim Start).
- Übersetzt: Kopfzeile der Karte (Termin, Aufgabe, Version), Fälligkeit, Zuständigkeit, Sicherheit,
  Einordnung, Kalenderänderungen, Widersprüche, Hinweise zu Testmodus und manueller Prüfung, offene
  Fragen, Beleg und Original-Mail; Rückfragen mit Antwortbeispiel; die Zusammenfassung einer Antwort;
  alle Knöpfe (Anlegen, Ändern, Verwerfen, Klären, Schon erledigt, Kalendertermin wählen, Zielprofil,
  Quelle zuordnen, Widerspruchswerte).
- Gespeicherte Fragen bleiben deutsche Kennungen der Fachlogik; nur ihre Anzeige wird übersetzt.
  `yes_no_question` erkennt Ja/Nein-Fragen unabhängig von der Anzeigesprache.
- Der Vollständigkeitstest prüft auch die Alternativen eines bedingten Arguments
  (`tr("A" if x else "B")`) und alle angezeigten Kartenbezeichnungen.

**Offen.** Quittungen und Fehlermeldungen des Dialogs (z. B. „Angelegt.“) folgen mit den übrigen
Texten in 7.5.4; Telegram-Befehle bleiben deutsch.

Prüfung 7.5.3: 5 752 Python-Tests mit 100 % Zeilen- und Branch-Abdeckung; ein zeitkritischer Test
scheiterte, während eine andere Sitzung gleichzeitig Tests ausführte, und bestand danach zweimal
einzeln. Der erste Browserlauf blieb bei etwa 99 % eine Stunde ohne Fortschritt stehen und wurde
abgebrochen; der Wiederholungslauf mit ausführlicher Ausgabe bestand vollständig (956 bestanden,
JavaScript zu 100 % abgedeckt). Die Ursache des Stillstands war nicht reproduzierbar.

## 7.5.4 – Offene Entscheidungen, Aktionen und Telegram-Meldungen (L4, erster Teil)

- **Arbeitsbereich „Offen“ auf Englisch:** Seitenkopf, Filter, Suche und Sortierung, Gruppen,
  Karten (Art, Badges, Fakten, Hinweise, Rückfragen, Kalenderabgleich, Serien, Relevanzfrage),
  Aktionsknöpfe mit Erklärung, Antwortformular, Ablehngründe, Prüfung angelegter Einträge,
  Fortschritts-, Ergebnis-, Veraltet- und Entfernen-Seite, die Detailseite eines Vorschlags und der
  Mailkopf mit Anhängen. Fehlerantworten der Weboberfläche (Sitzung, Formular, Version) ebenso.
- **Gespeicherte Meldungen:** Ergebnisse von Aktionen entstehen im Hintergrund und werden deutsch
  gespeichert (`de()` markiert sie). Angezeigt werden sie in der Sprache des Lesers: `stored()`
  übersetzt den ganzen Text oder jede Zeile, auch Einträge mit Werten („Grund gespeichert: …“) und
  deren Werte, und schreibt deutsche Datums- und Zeitangaben um (`07.01.2027, 11:30 Uhr` →
  `Jan 7, 2027, 11:30`). Jede Hinweisbox der Weboberfläche nutzt das.
- **Telegram-Quittungen und -Fehlermeldungen:** Der Telegram-Versand übersetzt jede Nachricht,
  jeden Knopf und jede Rückmeldung auf einen Knopfdruck in die eingestellte Sprache. Damit sind
  `/hilfe`, `/status`, Anlage-, Änderungs- und Absagequittungen, Doppelanlage-Rückfragen,
  Serien, Relevanz und alle Fehlermeldungen des Dialogs englisch, wenn `language: en` gilt.
- **Fehlerkorrektur:** Die zwischengespeicherte Übersicht war für alle Sprachen dieselbe; ein
  englischer Leser hinterließ englische Karten für den nächsten deutschen, und die vom Hauptthread
  veröffentlichte Übersicht blieb für englische Leser deutsch. Der Cache gilt jetzt je Sprache, und
  ein Leser einer anderen Sprache erhält die Übersicht in seiner Sprache. Regressionstests:
  `tests/review/test_review_language.py`, `tests/web/test_web_language_pages.py`.
- Web-Befehle laufen im Telegram-Dialog; ihr Ergebnis wird unabhängig von dessen Sprache deutsch
  gespeichert. Widerspruchsfelder („Endzeit“) erscheinen übersetzt.

**Abweichung vom Plan.** L4 umfasst mehr Seiten, als ein Patch sinnvoll prüfbar macht. 7.5.4 deckt
den täglichen Ablauf ab (Offen, Detail, Aktionen, Telegram); die übrigen Webseiten (Mails, Verlauf,
Status, Auswertung, Berichte, Einstellungen, Geräte, Abgleich, Lernen, Einrichtung) folgen in 7.5.5.
JavaScript und Einstellungshilfen rücken auf 7.5.6, CLI und Gesamtabnahme auf 7.5.7. Bis dahin
bleiben die unteren Abschnitte der Detail- und Mailseite (Analyse, Verlauf, Verarbeitungsschritte)
deutsch.

Prüfung 7.5.4: 5 788 Python-Tests mit 100 % Zeilen- und Branch-Abdeckung; Browser 956 bestanden ohne
Fehler, JavaScript zu 100 % abgedeckt. Ein erster Python-Lauf scheiterte, weil während des Laufs der
Hilfeindex neu erzeugt und die Versionsnummer erhöht wurde; der Wiederholungslauf ohne Eingriffe bestand.
