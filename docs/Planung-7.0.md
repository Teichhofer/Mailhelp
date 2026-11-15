# Mailhelp 7.0 – Code aufräumen und Dokumentation prüfen

**Zielversion:** 7.0 (Patches 7.0.1 bis 7.0.14)

**Stand:** 15. November 2026

**Status:** Entschieden am 15. November 2026: R1 bis R8 (Code) und K1 bis K6 (Dokumentation)
übernommen, darunter **R1** (projektfremde Dateien aus der Versionierung nehmen), **R6**
(Testdateien nach Thema statt nach Version benennen) und **K2** (abgeschlossene Pläne und
Release-Berichte in ein Archiv verschieben). Umsetzung läuft; Stand und Nachweise je Patch in
[Release 7.0](Release-7.0.md). Die Liste zu R1 hat der Betreiber am 15. November 2026 bestätigt.

**Ausgangsstand:** der Stand nach Abschluss von 6.8 und 6.9. Die Zahlen unten wurden am
15. November 2026 am Arbeitsstand 6.8.1 gemessen und werden in Schritt 7.0.1 neu erhoben.

**Grundlage:** [Entwicklungsregeln](../AGENTS.md), [Projektspezifikation](../Mailhelp-Projektspezifikation.md),
[Paketstruktur](Paketstruktur.md), [Prüfung der Dokumentation 5.3](Pruefung-Dokumentation-5.3.md)

7.0 ändert **kein Verhalten**. Die Version macht den Code leichter änderbar und stellt sicher, dass
jede lebende Anleitung zum tatsächlichen Stand passt. **Teil A** ist das Refactoring, **Teil B** die
Prüfung der Dokumentation.

---

## 0. Bestandsaufnahme

### 0.1 Code

| Kennzahl | Wert | Bemerkung |
| :--- | :--- | :--- |
| Anwendungscode | 305 Python-Dateien, rund 54 500 Zeilen | `web/` allein 71 Dateien und 12 600 Zeilen |
| Tests | 502 Dateien, rund 75 600 Zeilen | 100 % Zeilen- und Branch-Abdeckung |
| Funktionen | 3 037; davon 46 über 60 Zeilen, 7 über 100 Zeilen | längste: `proposal_evaluation_page` (179), `evaluate_proposals` (147), `collect_decided_proposals` (125), `build_application` (111), `_confirmation` in `telegram/update_handling.py` (107), `_attach_web` (103), `MailboxSite.mailbox` (102) |
| Parameterlisten | 46 Funktionen mit mehr als 8 Parametern | `logging.__init__` 32, `llm/learning.__init__` 20, `Orchestrator.__init__` 19, `telegram/dialog.__init__` 18, `openrouter.complete` 17, `MailhelpSite.__init__` 15 |
| Große Klassen | `ReviewService` 585 Zeilen / 27 Methoden, `MailboxRunService` 577 / 22, `Application` 538 / 32, `MailboxSite` 533 / 16, `Orchestrator` 496 / 30 | |
| Größte Datei | `config/models.py`, 1 119 Zeilen | |
| Importe innerhalb von Funktionen | 328 | 32 in `runtime/composition.py`, 26 in `review/service.py`, 24 in `web/site.py`; Hinweis auf Importzyklen |
| Unterdrückungen | 5 `noqa`, 3 `type: ignore`, kein `pragma: no cover`, keine TODO-Marken | guter Stand, bleibt so |
| Frontend | `app.js` 1 385 Zeilen in einer Datei mit 60 Ereignisbehandlern; `app.css` 1 247 Zeilen | |
| Typprüfung | `mypy` streng nur für eine Liste von Modulen | nicht streng: `runtime` (bis auf drei Module), `processing`, `llm`, `external`, `mailbox`, `proposals` (jeweils größtenteils), `activity`, `rule_learning`, `helpdocs` |

**Auffälligkeiten**

| ID | Beobachtung | Nachweis |
| :--- | :--- | :--- |
| C1 | Im Repository liegen versionierte Dateien, die nicht zu Mailhelp gehören: `output/` (Auswertungen, PDFs, Grafiken), `tmp/` (Bildschirmfotos, PDF-Seiten), `.tools/ocr/` samt einer virtuellen Umgebung mit `.exe`-Dateien, Sprachdaten und alten Testverzeichnissen, `.tools/instaloader/`. | `git ls-files` |
| C2 | Versionierte Arbeitsreste im Wurzelverzeichnis: `irrelevant-senders.corrupt`, `irrelevant-senders.json.v1`, `irrelevant-senders.json`, `.coverage-spec-audit`. | `git ls-files` |
| C3 | Kompatibilitätsfassaden aus früheren Umbauten: `models.py` (Stern-Importe aus `domain`), `telegram/_core.py`. In `pyproject.toml` steht noch eine Ausnahme für `src/mailhelp/integrations.py`, die Datei gibt es nicht mehr. | `models.py`, `pyproject.toml` |
| C4 | Module auf oberster Ebene neben ihren Paketen: `configuration.py` (498 Zeilen) neben `config/`, `storage.py` (362) neben `persistence/`, dazu `temporal_answers.py` (410), `german_dates.py`, `formatting.py`, `log_reduction.py`, `state_names.py`. | Verzeichnisliste |
| C5 | 250 von 437 Testdateien tragen eine Versionsnummer im Namen (`test_v43_series.py`, `test_ui_v20.py`, `test_log_reduction64.py`). Wer ein Verhalten sucht, muss wissen, in welcher Version es entstand. Die größten Testdateien: `test_telegram_dialog.py` 2 335 Zeilen, `test_services.py` 2 182, `test_application.py` 1 918. | Dateiliste |
| C6 | Die Weboberfläche erzeugt HTML in 71 Dateien mit Zeichenketten. Ob und wo sich Bausteine (Karten, Formulare, Schaltflächenzeilen) wiederholen, ist nicht gemessen. | `web/` |
| C7 | Altformate werden an mehreren Stellen gelesen (`legacy_format` für IMAP, `legacy_fingerprints`, `LEGACY_UNVERIFIED`). Das ist gewollte Abwärtskompatibilität, aber nirgends an einer Stelle aufgelistet. | Suche nach `legacy` (32 Dateien) |

### 0.2 Dokumentation

| Kennzahl | Wert |
| :--- | :--- |
| Dateien in `docs/` | 128; davon 50 Pläne, 46 Release-Berichte, 6 Konzepte, mehrere Prüfberichte |
| Umfang | rund 32 000 Zeilen; Spezifikation 4 381, CHANGELOG 3 337, README 906, `Web-Einstellungen.md` 739 |
| Verweise | 882 relative Verweise, keiner davon defekt |
| Vorhandene Prüfungen | `tests/release/test_documentation.py`, `test_documentation_inventory.py`, `test_guides.py`, `test_spec_implementation.py` |

| ID | Beobachtung | Nachweis |
| :--- | :--- | :--- |
| K-1 | Lebende Anleitungen nennen alte Stände: `Betrieb.md` 5.4.1, `Fehlerbehebung.md` 5.4, `Ersteinrichtung.md` 5.3, `Konten-verwalten.md` 5.3, `Ziele-einrichten.md` 5.4.1, `Einrichtung-und-Qualitaetspruefung.md` 4.1.11. Ob der Inhalt veraltet ist oder nur die Angabe, ist ungeprüft. | Zeile „Stand“ |
| K-2 | Drei Architekturdokumente für alte Stände (`Architektur-1.6`, `-2.1`, `-2.4`), keines für den heutigen. `Paketstruktur.md` nennt 3.6.10; seither kamen u. a. `rule_learning`, `helpdocs` und `activity` hinzu. | Dateien |
| K-3 | Lebende Anleitungen, abgeschlossene Pläne und Release-Berichte liegen ungetrennt in einem Verzeichnis. Die 96 historischen Dateien verdecken die rund 15, die man im Alltag braucht. | `docs/` |
| K-4 | Die letzte vollständige Prüfung der Dokumentation war zu 5.3. | `Pruefung-Dokumentation-5.3.md` |
| K-5 | README (906 Zeilen) wächst mit jeder Version, weil die Entwicklungsregeln eine Aktualisierung je Version verlangen. | `README.md` |

---

## 1. Ziele und Nichtziele

**Ziele**

1. Das Verhalten von Mailhelp ist nach 7.0 dasselbe wie davor, nachweisbar (Abschnitt 6).
2. Keine Funktion über 80 Zeilen, keine über 10 Parameter; die fünf größten Klassen sind in
   benannte Teile zerlegt.
3. Importe stehen am Dateianfang; die Schichten des Codes sind festgelegt und werden automatisch geprüft.
4. Das Repository enthält nur Mailhelp.
5. `mypy` prüft das ganze Paket streng.
6. Jede lebende Anleitung ist Aussage für Aussage gegen Code und Oberfläche geprüft; was sich
   automatisch prüfen lässt, wird künftig automatisch geprüft.
7. Lebende Dokumente und Archiv sind getrennt; es gibt ein aktuelles Architekturdokument.

**Nichtziele**

- Keine neuen Funktionen, keine geänderten Texte oder Abläufe in Oberfläche und Telegram.
- Kein geändertes Zustandsformat, keine geänderten Konfigurationsschlüssel, keine entfernte
  Abwärtskompatibilität für gespeicherte Daten (C7 wird dokumentiert, nicht gelöscht).
- Kein Wechsel der Technik: keine Vorlagen-Bibliothek, kein JavaScript-Bündler, kein Framework.
- Kein Umschreiben der Git-Historie.
- Keine inhaltliche Überarbeitung abgeschlossener Pläne und Release-Berichte.

---

## 2. Leitplanken

Diese Regeln gelten für jeden Patch in Teil A:

1. **Ein Patch, eine Art Änderung.** Verschieben, Umbenennen und Zerlegen werden nie mit einer
   inhaltlichen Änderung gemischt.
2. **Tests bleiben inhaltlich unverändert.** In einem Refactoring-Patch ändern sich an Tests nur
   Importpfade und Dateinamen. Muss eine Prüfung selbst geändert werden, ist das ein Zeichen für
   eine Verhaltensänderung und wird als solche gesondert behandelt.
3. **Gefundene Fehler werden nicht nebenbei behoben.** Sie bekommen einen eigenen Patch mit
   Regressionstest nach den Entwicklungsregeln.
4. **Jeder Patch ist für sich grün:** `python -m devtools.check full`, danach die Browsersuite
   (nicht gleichzeitig), 100 % Abdeckung, Versionsnummer, CHANGELOG, README.
5. **Sicherheitskritischer Kern zuletzt und klein:** `domain`, `storage.py`, `external/confirmed.py`
   werden nur verschoben oder umbenannt, wenn die Mutationsprüfung danach dieselben Werte liefert.
6. **Keine parallelen Arbeiten:** 7.0 verschiebt viele Dateien. Die Umsetzung beginnt erst, wenn
   6.8 und 6.9 abgeschlossen sind und keine andere Sitzung im selben Checkout arbeitet.

---

# Teil A – Refactoring

## 3. Entscheidungen

| ID | Frage | Vorschlag |
| :--- | :--- | :--- |
| **R1** | Projektfremde Dateien (C1, C2) | **Übernommen:** `output/`, `tmp/`, `.tools/` und die Arbeitsreste im Wurzelverzeichnis werden aus der Versionierung genommen (`git rm --cached`) und in `.gitignore` eingetragen. Die Dateien bleiben auf der Festplatte; die Historie bleibt unverändert. Vorher wird geprüft, ob ein Test oder die Konfiguration eine der Dateien liest (`irrelevant-senders.json` steht nicht in `also_copy`, `irrelevant-senders.example.json` schon und bleibt). **Vor dem Ausführen wird die Liste dem Betreiber zur Bestätigung vorgelegt.** |
| **R2** | Fassaden und Module auf oberster Ebene (C3, C4) | Fassaden `models.py` und `telegram/_core.py` entfallen; alle Aufrufer importieren aus dem eigentlichen Modul. `configuration.py` zieht nach `config/`, `storage.py` nach `persistence/`, `temporal_answers.py` und `german_dates.py` nach `domain/` bzw. ein Paket `text/`. Die tote Ausnahme für `integrations.py` wird gestrichen. Der Einstiegspunkt `mailhelp.cli:main` und die Konsolenbefehle bleiben. |
| **R3** | Schichten | Festgelegte Richtung der Importe: `domain` → `persistence`/`config` → `external`, `llm`, `mailbox` → `proposals`, `processing`, `review`, `rule_learning`, `notifications`, `activity` → `telegram`, `web` → `runtime` (Zusammenbau) → `cli`. Ein Test liest alle Importe aus dem Quelltext und scheitert bei einem Import gegen die Richtung. Die endgültige Reihenfolge ergibt die Messung in 7.0.1; Ausnahmen stehen namentlich mit Begründung im Test. |
| **R4** | Importe in Funktionen | Ziel: höchstens 20 statt 328, jeder verbliebene mit Kommentar (z. B. wahlfreie Abhängigkeit, Startzeit der Kommandozeile). Zyklen werden durch Verschieben der gemeinsamen Typen nach `domain` oder in ein Protokoll (`typing.Protocol`) aufgelöst, nicht durch weitere späte Importe. |
| **R5** | Lange Funktionen, Parameterlisten, große Klassen | Grenzen: 80 Zeilen je Funktion, 10 Parameter. Lange Parameterlisten werden zu unveränderlichen Datenklassen für Abhängigkeiten (z. B. `OrchestratorDependencies`). Große Klassen werden entlang ihrer Aufgaben zerlegt, die öffentliche Schnittstelle bleibt als dünne Klasse erhalten. Beide Grenzen prüft danach ein Test, damit sie nicht wieder überschritten werden; die McCabe-Grenze 15 bleibt. |
| **R6** | Testdateien (C5) | **Übernommen:** Umbenennen nach Thema, verzeichnisweise und rein mechanisch (`test_v43_series.py` → `test_series.py`, bei Namensgleichheit zusammenführen). Die drei größten Dateien werden nach Thema geteilt. Die Liste in `[tool.mutmut]` wird nachgezogen. Vorher und nachher wird die Zahl der gesammelten Tests verglichen; sie muss gleich sein. |
| **R7** | Weboberfläche und Frontend (C6) | Zuerst messen: wiederholte HTML-Bausteine in `web/` finden und in `forms.py`, `rows.py`, `pages.py` zusammenführen, nur wo die Ausgabe Byte für Byte gleich bleibt. `app.js` wird in Dateien je Bereich geteilt (Offen-Liste, Wischgeste, Diagramme, Hilfefenster, Push, Einstellungen) und ohne Bündler in fester Reihenfolge geladen; der Hash für den Service-Worker-Cache umfasst alle Dateien. `app.css` wird in derselben Gliederung sortiert; Regeln, die auf keiner Seite der Browsersuite greifen, werden einzeln geprüft und entfernt. |
| **R8** | Typprüfung | `disallow_untyped_defs`, `disallow_incomplete_defs` und `disallow_untyped_calls` gelten für das ganze Paket; die Modulliste in `pyproject.toml` entfällt. |

## 4. Maßnahmen

### 4.1 Sicherungsnetz vor dem ersten Umbau

- **Kennzahlen festhalten** (`devtools/inventory.py` erweitern): Funktionslängen, Parameterzahlen,
  Klassengrößen, Importe in Funktionen, Importgraph. Ausgabe nach `quality-reports/refactoring-7.0-vorher.json`.
- **Ausgabe einfrieren:** Für die Kernseiten (Offen, Mail, Verlauf, Lernen, Auswertung, Status,
  Einstellungen, Ersteinrichtung) und die Telegram-Nachrichten der Standardabläufe wird die
  erzeugte Ausgabe aus synthetischen Daten als Vergleichsdatei gespeichert. Ein Test vergleicht
  Byte für Byte. Diese Dateien dürfen sich in ganz 7.0 nicht ändern.
- **Bestandsprüfung:** Eine Kopie des Produktionsbestands wird vor und nach 7.0 gelesen; jede
  Zustandsdatei muss nach Laden und Speichern identisch sein. Ob die Bestandsprüfung aus 6.3.2
  das schon leistet oder dafür erweitert werden muss, klärt Schritt 7.0.1. Die Kopie bleibt
  lokal und wird nicht versioniert; die automatisierten Tests nutzen weiter nur synthetische Daten.
- **Mutationswerte** des Kerns vor Beginn festhalten.

### 4.2 Reihenfolge der Umbauten

Von außen nach innen und vom Mechanischen zum Inhaltlichen: erst aufräumen und verschieben, dann
Schichten, dann zerlegen. So wird jede lange Funktion nur einmal angefasst.

- **Zusammenbau (`runtime/composition.py`)**: `build_application` (111 Zeilen, 13 Parameter) und
  `_attach_web` (103) werden zu einzelnen Bauschritten je Bereich; die 32 späten Importe entfallen
  mit R3/R4.
- **`Application`, `Orchestrator`, `MailboxRunService`, `ReviewService`, `MailboxSite`**: je Klasse
  zuerst eine Karte der Methoden nach Aufgabe, dann Auslagern in Mitarbeiterklassen. Reihenfolge
  nach Risiko: `MailboxSite` und `ReviewService` zuerst, `Orchestrator` und `MailboxRunService`
  zuletzt.
- **`config/models.py`** (1 119 Zeilen) wird nach Bereichen geteilt (Postfach, Ziele, KI,
  Benachrichtigungen, Web); `config/__init__.py` exportiert dieselben Namen.
- **Altformate (C7)**: eine Tabelle in `docs/Architektur.md` nennt jedes gelesene Altformat, seit
  wann es abgelöst ist und welcher Test es abdeckt. Es wird nichts entfernt.

---

# Teil B – Dokumentation prüfen

## 5. Entscheidungen und Maßnahmen

| ID | Frage | Vorschlag |
| :--- | :--- | :--- |
| **K1** | Was ist „lebend“? | Lebend und damit vollständig zu prüfen: `README.md`, `Mailhelp-Projektspezifikation.md`, `DATENSCHUTZ.md`, `NUTZUNGSBEDINGUNGEN.md`, `AGENTS.md`, `config.example.yaml`, `.env.example`, und in `docs/`: `Bedienung`, `Betrieb`, `Ersteinrichtung`, `Fehlerbehebung`, `Konten-verwalten`, `Ziele-einrichten`, `Web-Einstellungen`, `Einrichtung-und-Qualitaetspruefung`, `Google-OAuth-Playground`, `GitHub-Pages`, `Zustandsregeln-3.6`, `Entkopplung-Web-und-Abruf`, `Paketstruktur`, dazu der Hilfeindex (`helpdocs/*.json`) und die Website (`website/`). Alles andere ist historisch. |
| **K2** | Archiv | **Übernommen:** Pläne, Release-Berichte, Konzepte, Prüfberichte und die alten Architekturdokumente ziehen nach `docs/archiv/`. Die Verweise (882) werden mechanisch angepasst; der vorhandene Verweis-Test sichert das ab. `docs/README.md` wird ein Inhaltsverzeichnis der lebenden Dokumente. Offene Pläne bleiben bis zu ihrem Abschluss in `docs/`. |
| **K3** | Architektur (K-2) | Ein aktuelles `docs/Architektur.md` ersetzt die drei alten Dokumente: Pakete und Schichten nach R3, Ablauf einer Mail, Bestätigungsweg für Schreibzugriffe, Zustandsdateien, Altformate. `Paketstruktur.md` geht darin auf. Geschrieben wird es nach Teil A, damit es den Zielzustand beschreibt. |
| **K4** | Prüfverfahren | Jedes lebende Dokument wird Abschnitt für Abschnitt gegen Code und laufende Oberfläche geprüft. Ergebnis je Aussage: stimmt, veraltet (korrigiert), nicht prüfbar (begründet). Das Protokoll steht in `docs/Pruefung-Dokumentation-7.0.md` mit derselben Tabellenform wie zu 5.3. Reihenfolge nach Nutzen: Ersteinrichtung, Betrieb, Fehlerbehebung, Konten, Ziele, Bedienung, Web-Einstellungen, README, Datenschutz, Spezifikation. |
| **K5** | Dauerhafte automatische Prüfungen | Erweiterung von `tests/release/test_documentation*.py`: (a) jeder in lebenden Dokumenten genannte Konfigurationsschlüssel existiert im Modell, und jeder Schlüssel des Modells steht in `config.example.yaml`; (b) jeder genannte Befehl `mailhelp …` existiert in der Kommandozeile samt Optionen; (c) jede genannte Umgebungsvariable wird vom Code gelesen; (d) in Anführungszeichen genannte Beschriftungen von Schaltflächen und Menüpunkten kommen in der Oberfläche vor; (e) genannte Dateipfade existieren; (f) der Hilfeindex ist aus dem aktuellen `Bedienung.md` erzeugt. |
| **K6** | Stand-Angaben und README (K-1, K-5) | Jedes lebende Dokument trägt eine Zeile „Geprüft für Mailhelp X.Y“. Ein Test verlangt, dass sie die aktuelle Hauptversion nennt (7.x); so fällt ein ungeprüftes Dokument spätestens bei 8.0 auf, ohne dass jeder Patch alle Dateien anfassen muss. README wird auf Einstieg, Schnellstart und Verweise gekürzt; die Versionsgeschichte steht nur im CHANGELOG. Die Regel in `AGENTS.md` („README bei jeder Version aktualisieren“) bleibt und bezieht sich dann auf Versionsstand und Funktionsübersicht. |

**Spezifikation:** Die 4 381 Zeilen werden nicht neu geschrieben. Geprüft wird, ob spätere
Entscheidungen frühere Abschnitte überholt haben (z. B. Wischgeste 6.3 → 6.9, Benachrichtigungen
2.0 → 6.8); überholte Stellen werden an Ort und Stelle berichtigt, nicht durch Nachträge ergänzt.
`test_spec_implementation.py` bleibt die automatische Sicherung.

---

## 6. Umsetzungsschritte

| Schritt | Patch | Arbeitspaket | Nachweis |
| :--- | :--- | :--- | :--- |
| D1 | 7.0.1 | Sicherungsnetz nach 4.1: Kennzahlen, eingefrorene Ausgaben, Bestandsprüfung, Mutationswerte | Vergleichstests grün; Vorher-Bericht gespeichert |
| D2 | 7.0.2 | Repository bereinigen (R1) nach Bestätigung der Liste | Paketbau und alle Tests grün; `git ls-files` enthält nur Mailhelp |
| D3 | 7.0.3 | Fassaden entfernen, Module in ihre Pakete (R2) | nur Importpfade geändert; Mutationswerte gleich |
| D4 | 7.0.4 | Schichtentest und Auflösen der Zyklen (R3, R4) | Schichtentest grün; Importe in Funktionen ≤ 20 |
| D5 | 7.0.5 | Zusammenbau zerlegen (`composition.py`, `experience.py`, `setup_runtime.py`) | Start, Neustart und Ersteinrichtung in den Prozess-Tests unverändert |
| D6 | 7.0.6 | Web: `MailboxSite`, `MailhelpSite`, lange Seitenfunktionen, gemeinsame Bausteine (R5, R7) | eingefrorene Seiten Byte für Byte gleich |
| D7 | 7.0.7 | `ReviewService`, `proposal_evaluation`, Telegram (`_confirmation`, `present`, `_compose`) | eingefrorene Telegram-Ausgaben gleich |
| D8 | 7.0.8 | `Application`, `Orchestrator`, `MailboxRunService`, `MailPipeline`; Abhängigkeits-Datenklassen | Wiederaufnahme-, Neustart- und Doppelungs-Tests unverändert grün; Bestandsprüfung identisch |
| D9 | 7.0.9 | `config/models.py` teilen; Grenzen 80 Zeilen / 10 Parameter als Test (R5); `mypy` streng für alles (R8) | Lint und Typprüfung ohne Befund |
| D10 | 7.0.10 | Frontend teilen und sortieren (R7) | Browsersuite mit 100 % JS-Blockabdeckung; Bildschirmfotos unverändert; Service Worker lädt nach Aktualisierung alle Dateien neu |
| D11 | 7.0.11 | Tests umbenennen und teilen (R6) | Zahl der gesammelten Tests gleich; Mutationsliste nachgezogen |
| D12 | 7.0.12 | Dokumentation: Archiv und Inhaltsverzeichnis (K2), `Architektur.md` (K3) | Verweis-Test grün |
| D13 | 7.0.13 | Dokumentation: Prüfung aller lebenden Dokumente (K4), automatische Prüfungen (K5), Stand-Zeilen und README (K6), Hilfeindex | `Pruefung-Dokumentation-7.0.md` vollständig; neue Tests grün |
| D14 | 7.0.14 | Abnahme: Nachher-Kennzahlen, Vergleich, Release-Bericht | Abschnitt 7 |

D12 und D13 hängen nur an D2 bis D4 (Pfade und Paketnamen) und können vorgezogen werden, wenn der
Code-Teil pausiert; `Architektur.md` wird dann nach D9 nachgezogen.

---

## 7. Abnahmekriterien

| Kriterium | Grenzwert |
| :--- | :--- |
| Eingefrorene Ausgaben (Web, Telegram) | Byte für Byte unverändert gegenüber 7.0.1 |
| Bestandsprüfung am Produktionsbestand | jede Zustandsdatei nach Laden und Speichern identisch |
| Tests | Zahl der Tests nicht gesunken; keine inhaltlich geänderte Prüfung in Refactoring-Patches |
| Abdeckung | 100 % Zeilen und Branches; 100 % JS-Blöcke |
| Mutationswerte des Kerns | nicht schlechter als vor 7.0 |
| Längste Funktion | ≤ 80 Zeilen (vorher 179) |
| Meiste Parameter | ≤ 10 (vorher 32) |
| Importe in Funktionen | ≤ 20, jeder begründet (vorher 328) |
| Schichten | kein Import gegen die Richtung außer den benannten Ausnahmen |
| `mypy` | streng für das ganze Paket, ohne Befund |
| Laufzeit | Dauer eines Abrufzyklus und Startzeit im Lasttest nicht schlechter als vorher (Toleranz 5 %) |
| Lebende Dokumente | alle geprüft, Protokoll vollständig, „Geprüft für Mailhelp 7.0“ |
| Betrieb | Aktualisierung des Produktivservers von 6.9 auf 7.0 ohne manuelle Schritte; Rückweg auf 6.9 möglich, weil das Zustandsformat gleich bleibt |

---

## 8. Risiken

| Risiko | Gegenmaßnahme |
| :--- | :--- |
| Unbemerkte Verhaltensänderung trotz grüner Tests | Eingefrorene Ausgaben, Bestandsprüfung, Mutationswerte; kleine Patches, die sich einzeln zurücknehmen lassen |
| Zusammenstöße mit parallelen Sitzungen im selben Checkout | Beginn erst nach 6.8 und 6.9; während 7.0 keine andere Arbeit im Checkout (Leitplanke 6) |
| Verschobene Module und der laufende Dienst teilen sich `.venv` | Kein `pip install` bei laufendem Dienst; Dienst für jeden Patch mit verschobenen Modulen anhalten, installieren, starten |
| Umbenannte Tests verlieren ihre Geschichte | `git mv`, je Verzeichnis ein eigener Patch ohne inhaltliche Änderung, damit Git die Umbenennung erkennt |
| Zerlegen erzeugt nur mehr kleine Dateien statt Klarheit | Je Klasse zuerst die Karte der Aufgaben; zerlegt wird entlang von Aufgaben, nicht nach Zeilenzahl; die Grenzen 80/10 sind Wächter, kein Ziel für sich |
| Gelöschte CSS-Regel wird doch gebraucht | Entfernen nur einzeln und mit Bildvergleich aller Seiten in hell und dunkel, Telefon und Desktop |
| Entfernen fremder Dateien trifft etwas Benötigtes (R1) | Nur aus der Versionierung, nicht von der Festplatte; Liste vorab bestätigt; Paketbau als Prüfung |
| Archiv bricht Verweise von außen (Website, Hilfechat) | Hilfeindex und Website in derselben Prüfung; Verweis-Test über alle Dateien |
| Dokumentationsprüfung findet echte Fehler im Programm | Als eigener Fehler mit Regressionstest außerhalb der Refactoring-Patches (Leitplanke 3) |

---

## 9. Dokumentation

- `docs/Architektur.md` (neu), `docs/README.md` (neu, Inhaltsverzeichnis), `docs/archiv/`.
- `docs/Pruefung-Dokumentation-7.0.md` (Protokoll), `docs/Release-7.0.md` (Kennzahlen vorher und nachher).
- `AGENTS.md`: Schichtenregel, Grenzen 80 Zeilen / 10 Parameter, Zeile „Geprüft für“.
- README und CHANGELOG je Patch.
