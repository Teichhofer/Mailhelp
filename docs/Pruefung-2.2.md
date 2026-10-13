# Anforderungsprüfung bis Mailhelp 2.2

Stand: 13.10.2026. Geprüfter Commit: `edb3df8`, Anwendungsversion 2.2.1.

**Ergebnis: Die Anforderungen sind noch nicht vollständig erreicht.** Die
Grundfunktionen sind umfangreich implementiert; insbesondere bestehen sämtliche
Python-Tests mit 100 % Zeilen- und Branch-Abdeckung. Es bleiben jedoch fachliche
Fehler in den Tätigkeitsberichten und ausdrücklich geplante Qualitätsarbeiten offen.

Grundlage sind insbesondere Planung-2.1.md, Planung-2.2.md, die Release-Dokumente,
AGENTS.md und die vorhandenen Tests für ältere Versionen. Die Prüfung umfasst
Quellcode, statische Werkzeuge, automatisierte Tests und gezielte synthetische
Reproduktionen. Sie ist keine erneute manuelle Abnahme sämtlicher älterer Releases
oder ein Test gegen echte Mail-, Kalender- und Todoist-Konten. Linux/Docker wurde
in dieser lokalen Windows-Prüfung nicht zusätzlich ausgeführt.

## Priorisierte Befunde

### 1. Hoch: Manuelle Korrekturen können verloren gehen

`activity/runner.py:207–282` liest eine Mail, speichert das Relevanzergebnis und
führt die Terminanalyse außerhalb der Sperre aus. Anschließend schreibt `_record`
das alte Mailobjekt vollständig zurück. `ActivityService.correct` kann inzwischen
bereits eine Benutzerkorrektur gespeichert haben. Die Sperre verhindert zwar
gleichzeitiges Schreiben, aber nicht das Überschreiben mit veraltetem Inhalt.

Synthetisch reproduziert: Während der Terminanalyse wurde über
`set_relevance(..., False)` „nicht relevant“ gespeichert. Nach Abschluss der
Analyse war `user_relevant` wieder `None`. Entsprechend sind auch manuell
ergänzte/geänderte Termine gefährdet. Verletzt Planung 2.2, Abschnitt 6:
Benutzerkorrekturen müssen laufende Analysen überstehen.

### 2. Hoch: Das konfigurierte KI-Aufruflimit ist keine harte Grenze

`activity/runner.py:128`, `:207`, `:284`: Das Limit wird vor einer Mail geprüft,
nicht vor jedem KI-Schritt. Eine relevante Mail löst anschließend Relevanz- und
Terminanalyse aus. Nachgeforderte Extraktionen prüfen das Berichtslimit gar nicht.

Synthetisch reproduziert: `max_llm_calls = 1`, eine relevante Mail → zwei
Modellaufrufe und gespeicherter Zähler `2`. Verletzt Kostenbegrenzung aus
Planung 2.2, Abschnitte 3 und 4.4. Reparatur-/Wiederholungsaufrufe des Analyzers
sind zusätzlich von den fachlichen Schrittzählern zu unterscheiden.

### 3. Mittel: Fehlerbehandlung bei Zählung und UID-Wechsel unvollständig

`activity/runner.py:64–117`: Fehler beim Öffnen des Postfachs oder beim LIST/Zählen
werden nur an der äußeren Schleife protokolliert. Der Bericht bleibt `counting`
und wird weiter versucht. Synthetisch blieb er auch nach fünf LIST-Ausfällen in
diesem Zustand; es gibt dort keinen begrenzten Fehlerzähler.

`imap.py:322–330` verweigert den Abruf bei geänderter UIDVALIDITY korrekt. Der
Berichtsrunner behandelt das aber als gewöhnlichen Abruffehler (`runner.py:194`)
und setzt den Bericht nach drei Fehlern auf `failed`. Die geplante erneute
Auflistung mit Wiederverwendung der Message-ID-Ergebnisse fehlt.

### 4. Mittel: Gesendet-Ordner werden bei expliziter Auswahl falsch eingeordnet

`activity/runner.py:100–104` markiert alle explizit gewählten Ordner zunächst als
`sent=False`. Nur zusätzlich automatisch ergänzte Gesendet-Ordner erhalten
`sent=True`. Ist der Gesendet-Ordner schon in `definition.folders`, wird deshalb
der Absender statt des Empfängers gegen die Ignorierliste geprüft; auch die
Anzeige behandelt ihn wie einen Eingangsordner (`activity/scan.py:108–114`).

Synthetisch reproduziert: Auswahl nur `Gesendet` ergab `sent=False`; eine Mail
an den ignorierten Empfänger wurde trotzdem an die Relevanz-KI übergeben.

### 5. Mittel: Lokale Prüfung der extrahierten Datumsangaben fehlt

`activity/llm.py:69–90` prüft Schema und Vorkommen des Belegtexts und übernimmt
danach `candidate.day`. Der in Planung 2.2, Abschnitt 4.3 vorgeschriebene lokale
Wochentag-/Datumsabgleich über `action_normalization` fehlt. Ein echtes Zitat
allein beweist nicht, dass das vom Modell gelieferte Datum dazu passt.

Synthetisch reproduziert: Beleg „am 20. Januar um 19 Uhr“, Modelldatum
`2026-01-21` → der 21. Januar wurde unverändert als Termin gespeichert.

### 6. Mittel: Autorisierungs-/Idempotenzvertrag für Berichte nur teilweise erfüllt

Die HTTP-Routen sind durch `MailhelpSite.signed_in` mit Sitzung und CSRF geschützt.
Start, Pause und Korrekturen prüfen Version und Idempotenzschlüssel.

Allerdings verwirft der Löschpfad den übermittelten Schlüssel
(`web/activity_site.py:108`, `activity/service.py:103`). Für die später im
Hintergrund ausgeführten Aktionen speichert der Bericht keinen Sitzungsbezug;
`ActivityRunner` prüft die Sitzung bei Ausführung nicht erneut. Das entspricht
nicht dem ausdrücklichen Vertrag in Planung 2.2, Abschnitte 3 und 11. Dieser
Befund betrifft die neuen Berichte, nicht den bestehenden Kalender-/Todoist-
Bestätigungsmechanismus.

### 7. Mittel: Ruff/Mypy sind weder fehlerfrei noch verbindliche Release-Gates

Gemessen: **236 Ruff-Befunde und 339 Mypy-Fehler** unter Windows/Python 3.12.10.
Einzelne Typfehler sind plattformspezifisch; der Gesamtbestand ist damit trotzdem
weit vom geforderten fehlerfreien Zustand entfernt. Ruff meldet unter anderem
drei nicht definierte `Any`-Namen in `review/views.py`.

`.github/workflows/ci.yml:29` setzt für `static-analysis` weiterhin
`continue-on-error: true`. Planung 2.1 A1 und Phase 6 sind somit offen.

### 8. Mittel: Geplante Wirksamkeits- und Browserprüfungen fehlen

Es gibt keine `mutmut`-Einrichtung und keinen wöchentlichen/manuellen
Mutationstestjob. Die geforderten mindestens 90 % getöteten Mutanten sind nicht
nachgewiesen. `weekly.yml` enthält nur das Dependency-Audit.

Die geplante zusätzliche `axe-core`-Prüfung und die benannten Browser-
Seitenobjekte fehlen. Automatische CDP-Coverage-Hooks sind vorhanden, daneben
wird in `ui_tests/conftest.py:300` weiterhin manuell gesammelt.

Der abschließende, allein ausgeführte Browser-Gesamtlauf besteht zwar alle
101 Funktionstests, endet aber mit Exitcode 1 wegen unvollständiger
JavaScript-Abdeckung. Für `app.js` fehlen unter anderem Zeilen 112, 208,
224–231 und zahlreiche Blöcke ab 352; `sw.js` wird als „nie geladen“ gemeldet.
Damit ist die vorgeschriebene 100-%-JavaScript-Abnahme nicht nachgewiesen.
Ob die Ursache in fehlenden Tests oder in der Coverage-Erfassung liegt,
muss separat geklärt werden.

## Weitere offene Anforderungen aus 2.2

| Anforderung | Tatsächlicher Stand |
| --- | --- |
| Kostenschätzung aus bisherigen Token-/Kostendaten, ggf. Ollama-Stromkosten | `_estimate` in `web/activity_pages.py:103` nennt immer nur Aufrufzahlen; keine Verwendung vorhandener Kostendaten. |
| Neu bewerten mit geändertem Thema und Wiederverwendung geladener Mails | Kein entsprechender Service-/Webablauf vorhanden. |
| Filter nach Monat, Absender, Unsicherheit und ausgeschlossenen Einträgen | In den Berichtsseiten nicht implementiert. |
| Hervorgehobene Belege im Mailvolltext | Zitat wird separat angezeigt; Volltext bleibt ein normales escaped `pre`. |
| Fortschritt über bestehenden Fingerprint-Endpunkt | Berichte verwenden Seiten-Refresh; `/api/stand` enthält keinen Berichtszustand. |
| Nur per LIST bekannte Ordner zulassen | Freitextordner werden ohne LIST-Validierung angenommen; nicht lesbare Ordner später übersprungen. |
| Wartende Berichte in Anlagereihenfolge | Store liefert neueste zuerst, Runner verarbeitet in dieser Reihenfolge. Ein Thread verhindert parallele Scans, FIFO fehlt. |
| Absenderliste beim Start sichern | Wird schon beim Anlegen/Zählen gesichert, nicht beim späteren kostenpflichtigen Start. |
| Schema-Verträge sämtlicher persistierter Modelle | Bericht trägt `schema_version=1`; die neuen Berichtsmodelle sind aber nicht Teil der zentralen Schema-Snapshottests. |

Die fehlende FIFO-Reihenfolge wurde zusätzlich synthetisch bestätigt: Nach Anlage
von „first“ und „second“ wurde beim nächsten Tick zunächst „second“ gezählt.
Auch die Paketdokumentation ist nicht nachgezogen: Die explizite sdist-Includeliste
in `pyproject.toml` enthält die Release-/Architekturdokumente 2.1 und 2.2 nicht.

## Abgleich der Arbeiten aus 2.1

| Paket | Bewertung |
| --- | --- |
| A1 / T8 | Werkzeuge und CI-Jobs vorhanden; Fehlerfreiheit und verbindliches Gate fehlen. Dependency-Audit und Laufzeitberichte vorhanden. |
| A2 / A3 | StateStore, öffentliche Sperre, Zustandsnamen und PreparedMail-Modelle vorhanden; zugehörige Tests bestehen. |
| A4 | AST-Prüfung: keine Funktion über 80 Zeilen. Im aktuellen Stand hat ActivityRunner 21 Methoden und überschreitet die Grenze 20. Die geplante composition.py fehlt; Fabriken liegen weiterhin in application.py. |
| A5 / A6 | Wesentliche Aufteilungen vorhanden; daraus folgt kein vollständiger Nachweis sämtlicher geforderter Architekturgrenzen. |
| A7 / A8 | Gemeinsame Fehlerklassen, Log- und Formatierungshelfer vorhanden. Einzelne Client-Fähigkeitsweichen bestehen fort, etwa mailbox_run.py:148. |
| T1 / T2 / T3 | Fachverzeichnisse und gemeinsame Fakes vorhanden. Neue Activity-Tests importieren erneut aus test_application/test_core. Mypy prüft laut Paketkonfiguration Anwendungscode, nicht die geforderte Protokollkonformität sämtlicher Test-Doubles. |
| T4 | Mutationstests fehlen. |
| T5 | Alte Zustandsdatensätze und Schema-Snapshots vorhanden, Tests bestehen. Neue Activity-Modelle noch nicht im Snapshot-Vertrag. |
| T6 | Hypothesis-Tests für wesentliche Parser vorhanden und erfolgreich; das allein belegt nicht jede geplante Kombination aus Anhängen, MIME-Verschachtelung und Sommerzeitwechsel. |
| T7 | Automatische Coverage-Hooks und verkürzte Undo-Frist vorhanden; axe-core und Seitenobjekte fehlen. |

Die offenen fachlichen Entscheidungen aus Planung 2.1, Abschnitt 5, sind ebenfalls
nicht vollständig erledigt: `briefing.py:88` sendet weiterhin bei beliebig spätem
Start am selben Tag; `webpush.py:102` beschränkt Operationen weiterhin global auf
500 statt je Gerät. Das geplante Zeitfenster ist dort als Entscheidung formuliert
und deshalb zunächst zu entscheiden, nicht stillschweigend als feste Vorgabe
anzunehmen.

## Verifikation

- Python: `python -m pytest tests -q --durations=10` → **1785 bestanden**,
  **14427 Statements / 4100 Branches, jeweils 100 %**, zwei Warnungen.
- Statische Prüfung: `python -m ruff check` → 236 Befunde;
  `python -m mypy` → 339 Fehler.
- Synthetische Reproduktionen über bestehende Activity-Fakes: Budgetüberschreitung,
  verlorene Benutzerkorrektur, unbegrenzte Zählfehler, Gesendet-Filter,
  widersprüchliche Termindaten und umgekehrte Berichtsreihenfolge wie beschrieben.
- Browser: `python -m pytest ui_tests --no-cov -q` → **101 bestanden**, aber
  **Exitcode 1 wegen unvollständiger JavaScript-Abdeckung**, Laufzeit 177,92 s.
  Ein erster parallel zur Python-Suite ausgeführter Lauf hatte zwei Fehler;
  beide bestanden anschließend separat. Diese anfänglichen Fehler werden
  deshalb nicht als reproduzierbare Produktfehler gewertet.

Die belegten Fehler brauchen eigene Regressionstests, die zunächst fehlschlagen.
100 % Ausführungsabdeckung hat diese fehlenden Verhaltensprüfungen nicht ersetzt.
Anwendungscode wurde im Rahmen dieser Prüfung nicht verändert.
