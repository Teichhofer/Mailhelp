# Mailhelp 7.8 – Lokalisierung und englische Demo

**Stand:** 18. November 2026. **Status:** Abgeschlossen mit 7.8.1 (Umsetzung) und 7.8.2
(Serverabnahme und Bericht).

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

## Serverabnahme am 18. November 2026

Docker ist auf dem Entwicklungsrechner nicht installiert; die Container-Abnahme erfolgte auf dem
Server. Das Image `mailhelp-production:7.8.1-ae4dcb9` wurde aus dem Commit `ae4dcb9` gebaut.

- **Deployment:** Produktion und Demo wurden gemeinsam umgestellt. Vorher wurden die
  Compose-Dateien und beide Laufzeitverzeichnisse bei gestoppten Containern gesichert
  (`/opt/mailhelp/backups/upgrade-7.8.1-20261118T201811Z`). Beide Healthchecks und die
  Versionsprüfung im Container (7.8.1) bestanden. Für einen Rückwechsel bleiben das Image
  7.7.6-8165098 und die gesicherten Zustände gemeinsam erhalten.
- **Bestehende Besucher:** Der Demo-Container startete ohne Fehler mit dem vorhandenen
  Besucherbestand.
- **Native Einstiege:** `/de/`, `/en/` und `/sprache` antworten am Container mit 303 und setzen
  `mailhelp_lang` mit `Secure`, `SameSite=Lax` und einem Jahr Laufzeit; `wert=xx` ergibt 400.
  Danach wurden die Sprach-Maps, die beiden Header und die Weiterleitungen aus der nginx-
  Konfiguration `mailhelp-demo-https` entfernt (Sicherung unter
  `/opt/mailhelp-demo/backups/nginx-demo-https-20261118T202002Z.conf`).
- **Öffentlicher Durchlauf über HTTPS:** `/en/` führt bei deutschem Browser zur englischen
  Startseite. Der Start zeigt englische Karten mit dem englischen Bestand ohne deutsche
  Bedienelemente. Ein Vorschlag wurde simuliert angelegt und erscheint als „Created in demo“.
  Nach dem Wechsel auf Deutsch bleiben Beispieldaten und Entscheidung erhalten, und der Neustart
  wird angeboten. `/de/` führt bei englischem Browser zur deutschen Startseite.

| Messwert | 7.7.6 | 7.8.1 |
| --- | ---: | ---: |
| Image | 365 MB | 369 MB |
| Demo-Container nach dem Start | – | 83 MiB von 384 MiB |
| Demo-Grenzen | 384 MiB, 0,5 CPU, 128 Prozesse | unverändert |

**Nachtrag 7.8.2:** Sieben relative Links in `docs/en/` zeigten auf `archiv/…` und
`Pruefung-…` ohne `../`. `test_documentation_links.py` prüft nur versionierte Dateien und meldete
das erst nach dem Commit von 7.8.1; die Links sind korrigiert.

**Prüfung 7.8.2:** `devtools.check full` mit 6 041 bestandenen Tests und 100 % Abdeckung;
Browsersuite 977 bestanden, 234 übersprungen; `help_index --check` besteht.

**Befund außerhalb von 7.8:** Nach dem Neustart lehnte Google die Erneuerung des
Kalender-Zugangs ab (HTTP 400). Die Zugangsdaten wurden am 11. November gespeichert; Refresh-Tokens
einer Google-OAuth-App im Status „Testing“ verfallen nach sieben Tagen. Um 04:15 UTC desselben Tages
gelang die Erneuerung mit 7.7.6 noch. Der Code für die Token-Erneuerung ist in 7.8 unverändert.
Die Google-Anmeldung muss neu erteilt werden.
