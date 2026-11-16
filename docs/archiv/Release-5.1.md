# Release 5.1 – Nachvollziehbare Erkennung

Versionen 5.1.0 bis 5.1.9, 10. November 2026. Grundlage: [Planung 5.1](Planung-5.1.md).

5.1 beantwortet die Frage „Warum wurde aus dieser Mail keine Aufgabe?“ direkt in der
Mailansicht und erlaubt eine gezielte, begrenzte Nachanalyse. Keine Funktion dieser Version
schreibt selbst in Kalender oder Aufgabenlisten; jeder Vorschlag braucht weiterhin die
ausdrückliche Bestätigung seiner aktuellen Version.

## Neu

| Version | Änderung |
| --- | --- |
| 5.1.0 | Erklärungsmodell: der tatsächliche Verarbeitungsweg jeder Mail aus dem gespeicherten Zustand, mit festen Texten und ohne Modellaufruf; „nichts gefunden“, „ausgelassen“, „fehlgeschlagen“, „ausstehend“ und „nicht mehr aufbewahrt“ sind getrennt. |
| 5.1.1 | Mailansicht „So wurde diese Mail verarbeitet“ mit Analyserunde, Plaketten, gekennzeichneten Modellbewertungen und Themennamen; ohne JavaScript nutzbar. |
| 5.1.2 | Dauerhafte Nachanalyse-Aufträge, gebunden an Mail, Runde und ursprüngliche Postfachidentität; gezählte Aufrufe, Budget, Versuchsgrenze, Fortsetzung nach Neustart. |
| 5.1.3 | Vergleich mit den bestehenden Vorschlägen und versionsgeprüfte, einmalige Übernahme: nur neue Befunde und Änderungen offener Vorschläge; geschriebene, verworfene und nicht mehr erkannte Vorschläge bleiben unverändert. |
| 5.1.4 | Prüfhinweise mit Regel, Schwere, Beleg und Analyserunde (Zählkonflikt, mögliche Auslassung, nicht zugeordnete Anmeldepflicht, Widerspruch, unvollständige Verarbeitung). |
| 5.1.5 | Bedienung: „Aufgabe oder Termin übersehen?“ mit Budgethinweis, Fortschritt, „Vorher und nachher“ und vorgemerkter Übernahme durch den Hintergrunddienst. |
| 5.1.6 | Korpus v4 (46 synthetische Fälle) und `mailhelp-quality-report` mit Erkennung, Auslassungen, Fehlalarmen und Feldkorrektheit getrennt nach Aufgaben und Terminen. |
| 5.1.7 | Fehlerbehebung bei der Wiederaufnahme (siehe unten) und eingefrorene Qualitäts-Baseline mit Abnahmeschwellen. |
| 5.1.8 | Aufbewahrungsfristen auch für Nachanalyse-Aufträge; beschädigte Auftragsdateien werden isoliert. |

### Fehlerbehebungen

- **5.1.7:** Die Wiederaufnahme unfertiger Mails prüfte die Konfiguration gegen den globalen
  statt den Postfach-Fingerabdruck. Mails eines Postfachs mit eigenen Einstellungen warteten
  dauerhaft (im Betrieb über 3.000 Warnungen für eine Mail), und eine abgeschlossene Mail mit
  fehlgeschlagener Aktionserkennung wurde nie wiederholt. Der Regressionstest schlug vor der
  Korrektur fehl.
- **Während der Entwicklung gefunden:** Ein während eines Modellaufrufs abgebrochener Auftrag
  hätte den Abbruch beim nächsten Zwischenspeichern überschrieben; nach einer Nachanalyse ohne
  Neues fehlte das Angebot für einen weiteren Start. Beide sind mit Tests abgesichert.

## Einrichtung, Upgrade und Rückkehr

Neu in `config.yaml` (Standardwerte, keine Pflicht):

```yaml
reanalysis:
  enabled: true
  max_llm_calls_per_job: 5   # Router, Aufgaben- und Terminextraktion plus zwei Wiederholungen
  max_attempts: 2
  max_jobs_per_day: 20
```

Nach dem Update den Dienst neu starten. Aufträge liegen als `reanalysis-<id>.json` im
Zustandsverzeichnis; sie gehören zur Sicherung wie die übrigen Zustände. Die Fristen unter
`retention` gelten auch für sie. Wichtig: Den Dienst vor einer Neuinstallation des Pakets in
derselben virtuellen Umgebung beenden, sonst kann Windows die Programmdatei sperren.

Rückkehr zu 5.0: den Block `reanalysis` entfernen; `reanalysis-*.json` werden von 5.0 nicht
gelesen und können gesichert oder gelöscht werden. Mail- und Vorschlagszustände benötigen
keine Migration; übernommene Vorschläge bleiben gewöhnliche Vorschläge.

## Abnahme

Automatisierte Tests verwenden ausschließlich synthetische Daten und simulierte Dienste
für Postfach, Modell und Zielanbieter.

| Prüfung | Ergebnis |
| --- | --- |
| Windows 11, Python 3.12.10 | **4.134 bestanden**, ein POSIX-Berechtigungstest plattformbedingt übersprungen (Lasttests getrennt; ein Lasttest scheiterte im Parallellauf am Zeitbudget und besteht einzeln) |
| Zeilenabdeckung Windows | **27.261 / 27.261, 100 %** |
| Branch-Abdeckung Windows | **7.904 / 7.904, 100 %**, keine partiellen Zweige |
| Browser-Gesamtsuite | **331 von 332 bestanden** auf Desktop, Mobilgerät und 320-Pixel-Ansicht mit 44-px- und axe-core-Prüfung; der eine zeitkritische Test (`test_ui_pending_selection`, mobil) besteht einzeln dreimal hintereinander; JavaScript seit 5.0.9 unverändert |
| Statische Prüfung | Ruff ohne Befunde; mypy ohne Befunde in **261 Quelldateien** |
| Prompt-Qualitätsgate | Drei synthetische Tests bestanden; Prompt-Fingerabdrücke unverändert |
| Paketprüfung | Wheel und sdist gebaut, Paketprüfungen bestanden |
| Linux/Docker | **Nicht durchgeführt**: Docker war auf dem Abnahmerechner nicht verfügbar. Nachzuholen, bevor 5.1 als plattformübergreifend geprüft gilt. |

Lasttests einzeln, Grenzen unverändert: 4.2 (fünf Browser) Median Warteschlange **387,9 ms**,
Maximum **567,2 ms**; 4.4.1 (2.000 Mails) Median Antwortzeit **336,5 ms**, Maximum
**424,3 ms**.

### Fachliche Nachweise (Abnahmefälle der Planung)

| Fall | Nachweis |
| --- | --- |
| Mail ohne Aufgabe | Erklärung mit gespeichertem Grund und Runde, ohne Modellaufruf (`test_explanation`, `test_processing_path`) |
| Übersehener Auftrag | Nachanalyse findet ihn, Übernahme als unbestätigter Vorschlag (`test_reanalysis_web`, Browsertest) |
| Besprechungsinformation ohne Auftrag | Korpus v4 Fall 40; kein Hinweis allein wegen eines Datums (`test_consistency_hints`) |
| Router-/Extraktionskonflikt | Hinweis und Erklärungsnotiz statt stiller Erfolgsmeldung |
| Frist ohne Handlungsbeleg | höchstens Prüfhinweis, keine Aufgabe oder Freigabe |
| Angelegter oder unklar geschriebener Vorschlag | externe ID und Schreibbeleg bleiben; keine neue Anlage (`test_reanalysis_adoption`) |
| Verworfener Vorschlag | bleibt verworfen |
| Wiederholter Start, Abbruch, Neustart | ein Auftrag, Fortsetzung ohne doppelte Aufrufe, Budget erhalten (`test_reanalysis_jobs`, `test_reanalysis_safety`) |
| Neue Runde oder Version während der Nachanalyse | Übernahme abgelehnt, Stand bleibt |
| Ungültige Sitzung, CSRF, manipulierter Hinweis | keine Wirkung; Hinweis nur als markierte Eingabe |
| Original fehlt, UIDVALIDITY geändert | erklärter Abbruch, keine andere Mail |
| Inhalt nach Aufbewahrung entfernt | Erklärung meldet fehlende Daten; Aufträge folgen den Fristen |
| Modell-/Extraktionsfehler, großer Anhang | als unvollständig ausgewiesen; alte Ergebnisse bleiben |
| Qualitätsbericht mit aufgezeichneten Antworten | `model_quality_proven: false` mit ausdrücklichem Hinweis |

### Grenzen

- **Modellqualität nicht nachgewiesen.** Alle Qualitätsaussagen beruhen auf simulierten
  bzw. aufgezeichneten Antworten. Ein Vorher-/Nachher-Lauf mit einem echten Modell auf Korpus
  v4 wurde nicht durchgeführt; er braucht eine ausdrückliche Freigabe für Modell,
  Datenübertragung, Umfang und Kostenbudget. Vorgehen: `docs/Einrichtung-und-Qualitaetspruefung.md`.
- Die Prompts wurden in 5.1 nicht verändert; die eingefrorene Baseline
  `quality-reports/baseline-5.1.json` ist die Messlatte für künftige Änderungen.
- Tests mit echten Postfächern oder Zielanbietern wurden nicht durchgeführt.

### Reproduzierbare Prüfungen

```powershell
python -m pytest -n 8 --dist loadgroup -q --ignore=tests/services/test_v42_load.py --ignore=tests/services/test_v441_load.py
python -m pytest tests/services/test_v42_load.py tests/services/test_v441_load.py --no-cov -q -s
python -m pytest ui_tests --no-cov -q
python -m ruff check src tests ui_tests devtools
python -m mypy
python -m devtools.check prompts
python -m hatchling build
mailhelp-quality-report tests/fixtures/mail_corpus_v4/corpus.json tests/fixtures/mail_corpus_v4/recorded_answers.json quality-report.json
```
