# Mailhelp 7.8 – Lokalisierung und englische Demo

**Stand:** 18. November 2026. **Status:** Umsetzung und abschließende Abnahme laufen.
Dieser Bericht wird erst nach den vollständigen Prüfungen als abgeschlossen gekennzeichnet.

## Umfang 7.8.1

Die Umsetzung folgt den Paketen A–I aus [Planung 7.8](Planung-7.8.md). Die native
Sprachwahl, die englischen Beispieldaten, Besucher-Generationen, Sprachressourcen,
Hilfebestände und die frühe CLI-Sprachwahl sind im Kandidaten enthalten.

Das Oberflächeninventar steht in `Localization-7.8.json`; die dynamischen
Beschriftungstabellen stehen in `Localization-tables-7.8.json`. Originalmails und
vom Nutzer vergebene Texte bleiben unmarkierte Daten. Markierte Beschriftungen
werden beim Rendern übersetzt; ihre Identität und ihre Zustandsdarstellung bleiben erhalten.

## Beispieldaten und Erzeugung

| Bestand | Mails | Relevant | Irrelevant | Termine | Aufgaben |
| --- | ---: | ---: | ---: | ---: | ---: |
| Deutsch, `standard-v1` | 30 | 9 | 21 | 6 | 4 |
| Englisch, `standard-en-v1` | 30 | 10 | 20 | 6 | 5 |

Der deutsche freigegebene Bestand bleibt erhalten. Der englische Bestand wurde
am 17. November 2026 über `build_application` und `Orchestrator.process` erzeugt.
Er verwendet ausschließlich synthetische Originalmails und `.example`-Adressen.
Der Lauf entstand ausgehend von `8165098` mit lokalen 7.8-Änderungen am Generator,
englischen Quellen und der Normalisierung expliziter Aufgaben-Uhrzeiten.
Modell und Analyse-Fingerprint stehen im Paketmanifest; die wirksame englische
Promptvariante liegt in `prompts.yaml`. Alle elf englischen Vorschläge sind
`pending_confirmation` und haben keine offenen Fragen. Die Kuchenlieferung behält
ihren Termin am 5. Dezember 2026 um 13:30 in `Europe/Berlin`.

Der erste Prüflauf zeigte einen Verlust der expliziten Aufgaben-Uhrzeit.
Regressionen reproduzierten den Fehler; nach der Korrektur wurde der vollständige
englische Lauf wiederholt. Die Paketdaten wurden aus diesem zweiten Lauf übernommen.

## Bestandswechsel und Betrieb

Eine Sprachumschaltung ändert die Oberfläche, nicht die Besucherentscheidungen.
Ein bestätigter Neustart bindet Zielbestand und Quellgeneration und bereitet die
vollständige neue Kopie vor der Aktivierung vor. Kopierfehler erhalten den alten Bereich.
Authentifizierung und Sicherheitsfristen verwenden weiterhin Echtzeit.

Beim vorherigen Serverupdate auf 7.7.6 blieb eine ältere Demo-Kopie mit Rückfragen
erhalten. Am 18. November wurden die betroffenen synthetischen Bereiche nach Sicherung
selektiv erneuert. Mail-IDs allein erkennen alte Bestände nicht: sie bleiben über
Inhaltsänderungen hinweg gleich. 7.8 hält deshalb Datensatzsprache, Revision und
Generation ausdrücklich im Besucherindex und Metadaten pro Bereich fest.

## Befunde der Abnahme

Die Abnahme fand fünf Fehler im Kandidaten; jeder ist durch einen vorher fehlschlagenden Test belegt.

- Der Katalogeintrag `{p0} Uhr` der Diagrammbeschriftung wirkte als Vorlage auf gespeicherte
  Meldungen und entfernte im Englischen das Komma vor der letzten Uhrzeit. Die Stunden werden nun
  ohne Katalogvorlage beschriftet.
- Schnellfilter, Vorschlagsstatus, Zeiträume, „gruppiert“, „Noch nicht geprüft.“, „Ereignis“, „Ja“
  sowie „IMAP-Server“/„IMAP-Port“ blieben auf englischen Seiten deutsch. Die Tabellen der
  `review`-Schicht sind jetzt markiert. `tests/golden/test_english_output.py` prüft alle englischen
  Golden-Seiten auf eigene deutsche Beschriftungen.
- Die englische Navigation zeigte „emails“ in Kleinschreibung; `heading()` setzt Titel groß.
- Drei Browsertests erwarteten Markup oder Wortlaute, die es nicht gab (Master-Spalte ohne
  JavaScript, „Black Week“ auf Seite 1, „Not available in demo“), und einer wartete den Demo-Start
  nicht ab. Die Tests prüfen jetzt das tatsächliche Verhalten.

## Abnahme

**Prüfung 7.8.1:** `python -m devtools.check full --workers 12` mit 6 041 bestandenen Tests,
100 % Zeilen- und Branch-Abdeckung und bestandenen Lasttests. Die Browsersuite meldet
977 bestandene und 234 übersprungene Tests. `python -m devtools.help_index --check` besteht.

Docker ist auf dem Entwicklungsrechner nicht installiert; die Container-Abnahme sowie der
Übergang der HTTPS-Einstiege erfolgen auf dem Server und werden hier nachgetragen.
