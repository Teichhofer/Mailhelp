# Mailhelp 7.4 – Mehrtägige Termine und Datumsbereiche

Geprüft für Mailhelp 7.4.

Umsetzung von [Planung 7.4](Planung-7.4.md) in einem Patch (7.4.1); die Schritte M1 bis M5 hängen
eng zusammen.

## 7.4.1 – Datumsbereiche, getaktete Mehrtagestermine und Abnahme (M1 bis M5)

**Erkennung (M1)** in `proposals/action_normalization.py`:

- Wochentage am Anfang und Ende, ausgeschrieben oder abgekürzt, mit oder ohne Punkt und Komma:
  „Donnerstag 07. bis Freitag 08. Januar 2027“, „Do 07. – Fr 08.01.2027“, „Do. 07. bis Fr. 08.01.2027“.
- Kurzformen: `07./08.01.2027`, `07.-08.01.2027`, `7./8.1.2027`, „7./8. Januar 2027“.
- Monats- und Jahreswechsel: „28. Januar bis 2. Februar 2027“, `28.01. bis 02.02.2027`,
  „28. Dezember bis 2. Januar 2027“ (Beginn im Vorjahr).
- Ein genannter Wochentag wird gegen den Kalendertag geprüft; ein Widerspruch führt zur Rückfrage
  „Wochentag und Kalenderdatum widersprechen sich.“ statt zu einer Vermutung. Unmögliche
  Kalendertage ergeben keinen Bereich.

**Getaktete Mehrtagestermine (M2):** Hat ein Bereich Uhrzeiten, beginnt der Termin am ersten Tag zur
Beginnzeit und endet am letzten Tag zur Endzeit. Dafür kennt `_normalize_timed` einen Endtag, statt
eine zweite, fast gleiche Funktion zu führen; Zeitzonen, Sommerzeit, Dauer und Zonenbezeichnungen
gelten unverändert. Mit Dauer endet der Termin nach der Dauer; ohne Endzeit und Dauer fragt Mailhelp
„Wann endet der Termin am 08.01.2027?“ und behält den bekannten Beginn. Ausdrücklich ganztägige
Bereiche bleiben ganztägig.

**Originalfall (M3):** „Donnerstag 07. bis Freitag 08. Januar 2027“, 11.30 bis 12.30 Uhr, ergibt ohne
Rückfrage `2027-01-07T11:30:00+01:00` bis `2027-01-08T12:30:00+01:00`, nicht ganztägig
(`tests/unit/test_date_ranges_multiday.py`).

**Klärung und Bearbeitung (M4):** Die Bearbeitung nimmt Beginn und Ende als vollständige Zeitpunkte
an, ein abweichender Endtag ist also möglich. **Fehlerkorrektur:** Die neue Endfrage mit Datum blieb
nach einer Bearbeitung, einer Standarddauer oder dem Zusammenführen offen, weil diese Stellen nur die
festen Fragen „Wann beginnt/endet der Termin?“ erkannten. `domain.proposal.time_question` erkennt
jetzt beide Formen; Regressionstest in `tests/reconciliation/test_defaults.py`.

**Kalenderadapter (M5):** Google Kalender, CalDAV und Outlook schreiben einen getakteten Termin über
zwei Tage als eine Spanne (`tests/external/test_multiday_writes.py`); die Adapter selbst mussten nicht
geändert werden.

**Frühere Abweichung (behoben im Nachtrag).** Die in 7.4.1 fehlende automatische Auflösung jahresloser Datumsbereiche wird durch die bestehende Jahresregel für Einzeltage ergänzt; siehe unten.

Prüfung 7.4.1: 5 707 Python-Tests mit 100 % Zeilen- und Branch-Abdeckung. Browser 956 bestanden,
JavaScript zu 100 % abgedeckt. Der erste Lauf meldete fünf nicht abgedeckte Zeilen in `open-list.js`
aus 7.3.4 (Rücksprung nach „Ignorieren“): Der Test navigierte sofort weiter, und die Abdeckung ging je
nach Zeitablauf verloren. Er hält jetzt die Seite der Aktion an, bis die Abdeckung eingesammelt ist.

## Nachtrag vom 17. November 2026 – Jahreslose Datumsbereiche

Die Jahresregel entspricht den bereits unterstützten jahreslosen Einzeltagen: Ein eindeutiges Jahr
im Beleg wird verwendet; ohne solche Angabe gilt der nächste Beginn ab dem validierten lokalen
Maildatum. „07. bis 08. Januar“ in einer Mail vom September 2026 ergibt deshalb 7.–8. Januar 2027.
„28.12. bis 02.01.“ ergibt 28. Dezember 2026 bis 2. Januar 2027. Getaktete Bereiche behalten Beginn
und Ende an ihren jeweiligen Tagen; ganztägige Bereiche behalten das exklusive Kalender-Enddatum.
Die Jahresherkunft steht in `TemporalFact.year_source`, statt ein erfundenes explizites Jahr vorzutäuschen.

Unbrauchbarer Mailkontext, widersprüchliche Jahre, unmögliche Tage und widersprüchliche Wochentage
führen zu Rückfragen. Für Kalenderzugriffe gilt weiterhin die ausdrückliche versionsbezogene
Bestätigung. Die Auflösung verwendet den vorhandenen validierten Maildatumskontext.

Bei der vollständigen Planprüfung wurde zusätzlich eine Lücke im Klärungsdialog korrigiert.
Die Rückfrage enthielt das letzte Datum, speicherte dieses aber bisher nicht als Zeitfakt.
`known_temporal_facts.end_date` erhält jetzt den validierten letzten Kalendertag bei fehlendem
Beginn oder Ende. Eine nachgereichte Enduhrzeit wird diesem Tag zugeordnet, auch nach dem
erneuten Laden des Vorschlags. Die Revisionsgrenze schützt Beginn und Enddatum gleichermaßen.
Die drei ursprünglichen Regressionen in `tests/unit/test_multiday_end_clarification.py`
scheiterten vor der Korrektur. Weitere Fälle prüfen aufeinanderfolgende Antworten und
widersprüchliche Revisionen. Bestehende JSON-Daten bleiben ohne das optionale Feld lesbar.

Regressionen: `tests/unit/test_yearless_date_ranges.py`; die ersten zehn Fälle scheiterten vor dem
Fix. Die Prüfung des Abschlusses erfolgt getrennt auf Commit 7.4.1, da im Arbeitsverzeichnis parallel
7.5 entsteht. Der Nachtrag wird in den neueren Projektstand integriert.

### Prüfstand des Nachtrags

- Isolierte Basis: Commit `1cc04ac` (7.4.1) plus Datums-Korrektur und Regressionen.
- Vollständiger funktionaler Python-Lauf mit zwölf Arbeitern über `python -m devtools.check full --workers 12` mit anschließendem Lastlauf. **5 731 bestanden, 1 bestehend übersprungen**.
- Abdeckung umfasst **36 392 Anweisungen und 10 382 Zweige bei 100 % Zeilen- und Branch-Abdeckung**.
- Ruff und mypy bestehen für die geänderten Anwendungsmodule. Upgrade- und Kompatibilitätsauswahl umfasst zusätzlich **130 bestandene Tests**. Die sechs betroffenen Zustandsschemas enthalten das optionale Feld. Ein synthetischer Upgrade-Zustand prüft Lesbarkeit und Neustart.
- Beide Lasttests bestehen im abschließenden Lauf. Aktionsstart erreicht **364 ms Median und 545 ms Maximum**, Ergebnisanzeige **490 ms Median und 835 ms Maximum**.
- Frühere Latenzläufe überschritten die Grenze. Der Vergleich mit unveränderter 7.4.1 meldete ebenfalls eine Überschreitung mit 579 ms Median. Der abschließende Nachtragslauf besteht mit den bestehenden Grenzwerten. Protokolle liegen unter `.test-tmp-v74-review/`, der Gesamtlauf in `verified-release-full.log`.
- Vollständige Browserabnahme mit `python -m pytest ui_tests -n 6 --dist worksteal --no-cov` besteht. **956 bestanden, 232 durch die bestehende Testmatrix übersprungen**, Rückgabecode 0. JavaScript erreicht **100 % Blockabdeckung** für alle zehn geprüften Anwendungsskripte. Der Lauf erfolgte nach Abschluss der Python-Prüfungen. Das Protokoll liegt unter `.test-tmp-v74-review/verified-browser-complete.log`.

Der Nachtrag erfüllt damit die fachliche und automatisierte Abnahme des 7.4-Plans auf der
isolierten 7.4.1-Basis. Die geänderten Anwendungsmodule und Regressionstests stimmen inhaltlich
mit dem aktuellen Arbeitsstand überein.

## Integration in 7.5.5

Der Nachtrag wird in den mehrsprachigen Stand 7.5.4 (`dfae0fc`) übernommen. Der neue Commit
erhöht die Patchversion gemäß AGENTS.md auf 7.5.5. Der gepackte Hilfebestand verwendet dieselbe
Version. Der während der Prüfung hinzugekommene Plan 7.7 ist im Dokumentationsindex verlinkt.

Die vollständige Python-Prüfung auf dem integrierten Stand erreicht **36 597 Anweisungen und
10 424 Zweige bei 100 % Zeilen- und Branch-Abdeckung**. Im funktionalen Gesamtlauf bestehen
5 787 Tests, einer wird übersprungen. Der einzige Fehler betrifft den fehlenden Indexlink des
parallel committeten Plans 7.7. Nach Ergänzen dieses Links bestehen alle drei
Dokumentationslink-Prüfungen. Ruff, mypy, die Prüfung des Hilfebestands und der Pakettest für
die Hilfe außerhalb des Checkouts bestehen.

Der Aktionsstart-Lasttest besteht mit 345 ms Median und 522 ms Maximum. Die Ergebnislatenz
überschreitet auf diesem Windows-Rechner die bestehende Grenze von 500 ms Median. Die
Einzelwiederholung der Integration erreicht 533 ms Median bei 860 ms Maximum. Eine direkt
anschließende Messung mit unveränderter 7.5.4, denselben Testdaten und denselben Testpfaden
erreicht ebenfalls 531 ms Median bei 919 ms Maximum und scheitert an derselben Grenze.
Dieser bestehende Latenzbefund bleibt dokumentiert.

Die lokalen Prüfprotokolle liegen unter `.test-tmp-v74-review/` in `integrated-full-final.log`,
`integrated-final-gates.log`, `integrated-latency-recheck.log` und `baseline-754-latency.log`.

Der integrierte Browser-Gesamtlauf umfasst 955 bestandene und 232 übersprungene Fälle. Ein
Offline-Fall scheitert nach bestandenen fachlichen Prüfungen an Chromes
`ERR_NO_BUFFER_SPACE`. Derselbe unveränderte Test besteht anschließend in der
Einzelwiederholung. Die echten Abdeckungsdaten sämtlicher sechs Worker wurden mit
`merge_worker_coverage` und `COVERAGE.uncovered()` aus dem bestehenden Browser-Prüfwerkzeug
zusammengeführt und geprüft. Das Ergebnis enthält keine Zusammenführungsfehler und keine
unabgedeckten Blöcke. Alle zehn Anwendungsskripte erreichen 100 % Blockabdeckung.
Die Protokolle heißen `integrated-browser.log`, `integrated-offline-recheck.log` und
`integrated-browser-coverage.json` im selben lokalen Prüfverzeichnis.
