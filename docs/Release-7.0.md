# Mailhelp 7.0 – Code aufräumen und Dokumentation prüfen

Umsetzung von [Planung 7.0](Planung-7.0.md). 7.0 ändert kein Verhalten; jeder Patch wird gegen
die in 7.0.1 festgehaltenen Vorher-Werte geprüft.

## 7.0.1 – Sicherungsnetz

Ausgangsstand ist 6.9.3 (Commit `68d6250`).

**Eingefrorene Ausgaben.** `tests/golden/test_frozen_output.py` erzeugt aus synthetischen Daten
bei fester Uhr elf Kernseiten (Übersicht, gefilterte Liste, Mails, Mail, Vorschlag, Verlauf,
Lernen, Auswertung, Status, Einstellungen, Abgleich) und die Telegram-Darstellung aller
14 Vorschläge. Ersetzt werden nur Werte, die sich bei jedem Lauf ändern: Sitzungs- und
Formular-Token, Fingerabdrücke, Ablaufzeiten und Rückruf-Token. Die Vergleichsdateien liegen
unter `tests/golden/output` und dürfen sich in ganz 7.0 nicht ändern.

**Kennzahlen vorher** (`python -m devtools.code_metrics`, gespeichert in
`quality-reports/refactoring-7.0-vorher.json`):

| Kennzahl | Wert |
| :--- | :--- |
| Python-Dateien / Zeilen | 305 / 54 539 |
| Funktionen | 3 037 |
| davon über 60 / 80 / 100 Zeilen | 46 / 16 / 7 |
| längste Funktion | `proposal_evaluation_page`, 179 Zeilen |
| Funktionen mit mehr als 10 Parametern | 20 (höchstens 32, `logging.__init__`) |
| Importe innerhalb von Funktionen | 328 |

**Bestandsprüfung.** `python -m devtools.state_roundtrip <Verzeichnis>` lädt jede Zustandsdatei
einer Kopie mit ihrem Modell und serialisiert sie wie der Speicher. Der Bericht enthält nur
Zählwerte und eine SHA-256-Prüfsumme. Auf einer festen lokalen Kopie des Bestands
(4 840 Dateien, keine ungültig) ist die Vorher-Prüfsumme festgehalten; Kopie und Bericht bleiben
lokal und unversioniert. Nach 7.0 muss dieselbe Prüfsumme entstehen.

**Mutationswerte vorher** (WSL, `python -m devtools.check mutation` auf 6.9.3, gespeichert in
`quality-reports/mutation-7.0-vorher.json`): 1 478 Mutanten, 1 158 getötet (78,35 %), 185 überlebt,
135 ohne Test. Je Kernbereich getötet / überlebt / ohne Test: `domain` 520 / 26 / 135,
`storage.py` 454 / 69 / 0, `external/confirmed.py` 184 / 90 / 0. Der Ausgangsstand erreicht die
90 %, die der wöchentliche Mutationslauf verlangt, schon vor 7.0 nicht; Maßstab für 7.0 ist,
dass kein Wert schlechter wird. `core_mutation_scores` in `devtools/check.py` bricht bei Mutanten
ohne Test (Code 33) ab; die Werte oben sind deshalb direkt aus den Metadaten gezählt.

**Abweichung vom Plan.** Die Kennzahlen erzeugt ein eigenes Werkzeug `devtools/code_metrics.py`
statt einer Erweiterung von `devtools/inventory.py`; die Inventur der Einstellungen bleibt davon
getrennt.

## 7.0.2 – Nur Mailhelp im Repository (R1)

Nach Bestätigung der Liste durch den Betreiber sind 186 Dateien aus der Versionierung genommen
und in `.gitignore` eingetragen: `output/` (Auswertungen und PDFs anderer Arbeiten), `tmp/`
(Bildschirmfotos und PDF-Seiten), `.tools/` (OCR- und Instaloader-Werkzeuge samt virtueller
Umgebung) und im Wurzelverzeichnis `irrelevant-senders.json`, `irrelevant-senders.json.v1`,
`irrelevant-senders.corrupt`, `.coverage-spec-audit`, `coverage-audit.json` und
`spec-audit-coverage.json`. Die Dateien liegen weiter auf der Festplatte; die Git-Historie ist
unverändert. Kein Test, kein Paketbau und keine Konfiguration las eine davon; die CI legt
`irrelevant-senders.json` für den Containertest weiterhin aus `tests/fixtures` an.
`tests/release/test_repository_scope70.py` verhindert, dass sie wieder versioniert werden.

**Hinweis Datenschutz.** Die beiden Dateien `irrelevant-senders.json*` enthielten rund 54 echte
Absenderadressen und liegen in früheren Commits auf GitHub. Entfernen aus der Historie wäre ein
Umschreiben der Historie und ist nach Plan nicht Teil von 7.0; es bleibt eine Entscheidung des
Betreibers.

## 7.0.3 – Fassaden entfernt, Module in ihren Paketen (R2)

- `mailhelp/models.py` (Stern-Importe aus `domain`) und `mailhelp/telegram/_core.py` sind entfallen.
  Alle Importe in Code und Tests zeigen auf das Modul, das den Namen definiert. Die öffentliche
  Schnittstelle `mailhelp.telegram` bleibt.
- Verschoben (mit `git mv`): `storage.py` → `persistence/storage.py`, `configuration.py` →
  `config/configuration.py`, `temporal_answers.py` und `german_dates.py` → neues Paket `text/`.
  `text/` statt `domain/`, damit der mutationsgeprüfte Kern unverändert bleibt.
- `pyproject.toml`: tote Ausnahme für `integrations.py` und die Ausnahmen der Fassaden gestrichen,
  Pfade für Mutationsprüfung und mypy nachgezogen; `devtools/check.py` liest die Mutationsdaten von
  `persistence/storage.py`.
- Tests: nur Importpfade und Patch-Ziele geändert. Zwei Architekturtests prüften die gelöschten
  Fassaden selbst; sie prüfen jetzt, dass die Fassaden fehlen und die öffentlichen Pakete dieselben
  Objekte liefern.
- Ruff meldet 41 statt 46 Befunde (das Sortieren der Importblöcke behob fünf alte), mypy weiterhin
  die 14 Fehler des Ausgangsstands.
- Mutationswerte nach der Verschiebung (WSL): 1 159 von 1 478 getötet; `domain` 521 / 25 / 135,
  `persistence/storage.py` 454 / 69 / 0, `external/confirmed.py` 184 / 90 / 0. Kein Wert ist
  schlechter als vor 7.0.
- Prüfung: 5 318 Python-Tests mit voller Abdeckung, 922 Browsertests.

## 7.0.4 – Schichten und späte Importe (R3, R4)

**Schichten.** `tests/unit/test_layers70.py` legt die Richtung der Importe fest, von unten nach
oben: Basis (`domain`, `text`, `state_names`, `paths`, `formatting`, `log_reduction`) →
Infrastruktur (`logging`, `persistence`, `support`) → `config` → Adapter (`external`, `llm`) →
`mailbox`, `proposals` → Dienste (`processing`, `review`, `rule_learning`, `notifications`,
`activity`) → `runtime` → Kanäle (`telegram`, `web`, `helpdocs`) → Zusammenbau (`app`) → `cli`.
Auch Importe innerhalb von Funktionen zählen. Der Test scheitert an jedem neuen Import gegen
die Richtung und an jeder nicht mehr benötigten Ausnahme.

Die Messung ergab mehr Gegenrichtungen als im Plan angenommen (52 Modulpaare). Aufgelöst durch
Verschieben (mit `git mv`, Importe und Patch-Ziele nachgezogen):

- Neues Paket `app` für den Zusammenbau: `composition`, `application`, `bootstrap`,
  `service_coordinator`, `setup_runtime`, `browser_accounts`, `reload` (bisher in `runtime`).
- Neues Paket `support` (Infrastruktur): `metrics`, `stage_metrics`, `lock_metrics`, `yaml_edit`.
- `runtime/env_file` → `config/env_file`, `notifications/notification_config` →
  `config/notifications`, `review/revision_origin` und `review/archive` → `persistence`,
  `processing/calendar_parser` und `processing/attachment_extractor` → `text`,
  `runtime/local_pairing` → `web/local_pairing`.
- `_mailbox_labels` und `_build_iserv` aus dem Zusammenbau als `mailbox_labels` und
  `build_iserv_sources` nach `mailbox/sources.py`.
- `app/application.py` gab drei Funktionen aus `composition` weiter (weitere Fassade); entfernt.
  Damit ist der Importzyklus zwischen beiden aufgelöst, der `composition` bisher nur in einer
  bestimmten Ladereihenfolge importierbar machte.

Verblieben sind 23 benannte Ausnahmen mit Begründung, vor allem die Validierung der Einstellungen,
die Fachregeln aus `mailbox`, `proposals` und `llm` nutzt, und der Abruf, der jede Mail an
`processing` übergibt. Module eines gemischten Pakets mit eigener Schicht: die Werkzeuge in `llm`
(Auswertung, Entscheidungstest, Lernen, Entscheidungsclients) und der Schemakatalog
`persistence.schemas`, den nur Prüfwerkzeuge lesen.

**Späte Importe: 25 statt 328.** Angehoben wurden alle Importe in niedrigere Schichten sowie
innerhalb einer Schicht, wo kein Ladezyklus entsteht; jedes Modul wird dafür in einem eigenen
Prozess als erstes importiert. Wo Tests eine Klasse im Ursprungsmodul ersetzen, greift der Aufrufer
jetzt über das Modul zu (`imap_module.ImapReader`), sodass der Ersatz weiterhin wirkt. Übrig sind
18 Importe gegen die Schichtrichtung (die benannten Ausnahmen), zwei plattformabhängige Module
(`msvcrt`, `fcntl`) und fünf echte Paarzyklen. Jeder trägt eine Zeile `# Late: …` mit dem Grund;
der Schichtentest erzwingt Grund und Obergrenze. **Abweichung vom Plan:** Ziel waren höchstens 20.
Die übrigen fünf Zyklen und die Validierungsimporte von `config` aufzulösen hieße, Fachregeln
zwischen Paketen zu verlagern; das geschieht nicht in einem reinen Umbau-Patch.

**Gefundener Fehler beim Umbau.** Zwei Funktionen in `web/history_site.py` importierten je ein
anderes `SORTS`; nebeneinander am Dateianfang hätte das zweite das erste verdeckt und die Sortierung
„Kosten“ der Aufrufliste abgelehnt. Vor dem Commit bemerkt (ruff F811) und behoben; ein neuer
Regressionstest scheitert mit der Verdeckung und besteht ohne sie.

**Prüfung.** 5 322 Python-Tests mit voller Abdeckung, Lasttests bestanden (mit `--workers 12` in
44 Minuten, siehe R9). Browsersuite mit 6 Prozessen: 921 bestanden, ein Fehlschlag in
`test_no_swipe_starts_where_the_touch_means_something_else`; der Test ist unabhängig von 7.0.4
unzuverlässig (allein gestartet einer von drei Läufen rot, `app.js` und Test unverändert) und wird
in 7.0.5 untersucht. Ruff 41 Befunde, mypy 14 Fehler wie zuvor.

## 7.0.5 – Laufzeit der Prüfung (R9, vorgezogen)

**Messung.** Ohne Abdeckungsmessung lief die ganze Suite mit 12 Prozessen in 3 Minuten 33 Sekunden;
kein Test dauerte länger als 9 Sekunden (längster: `test_evaluation_matches_production_baseline_numbers`,
8,9 s). Lange Tests zu teilen ist daher nicht nötig. Der Engpass war `tests/conftest.py`: Im
parallelen Lauf lagen alle 162 Prozess- und Ende-zu-Ende-Tests in einer Gruppe auf einem einzigen
Prozess, dort mit Abdeckungsmessung rund 40 Minuten, während die übrigen Prozesse nach etwa
18 Minuten warteten.

**Änderung.** Nur die beiden Container-Tests (`tests/e2e/test_container_*`, echtes Docker) bleiben
in einer gemeinsamen Gruppe; alle anderen verteilen sich auf die Prozesse. Der Test der Gruppierung
prüft die neue Regel.

| Lauf | vorher | nachher |
| :--- | :--- | :--- |
| `devtools.check full` seriell | 18 min | – |
| `devtools.check full --workers 12` | 44 min | 10 min 21 s |
| Browsersuite | 4 Prozesse, rund 9,5 min | 6 Prozesse, rund 7,5 min |

**Abweichung vom Ziel (6 Minuten).** Die Abdeckungsmessung kostet rund 6 der 10 Minuten. Die
schnellere Messart `sys.monitoring` kann Branch-Abdeckung erst ab Python 3.14; das Projekt läuft
auf 3.12.

**Unzuverlässiger Wischtest.** `test_no_swipe_starts_where_the_touch_means_something_else` scheiterte
in 7.0.4 einmal unter Last beim Antippen des Textfelds. In 34 gezielten Wiederholungen, auch
parallel, trat der Fehler nicht wieder auf. Abgesichert sind beide möglichen Ursachen, ohne eine
Prüfung zu ändern: Die Einführungsbewegung (6.9, U6) ist wie im benachbarten Scrolltest
unterdrückt, und der Test wartet, bis das aufgeklappte Textfeld sichtbar ist.

`AGENTS.md` nennt die gemessenen Aufrufe für Python- und Browserprüfung.

## 7.0.6 – Zusammenbau in benannten Schritten (D5)

`app/composition.py`: `build_application` (vorher 111 Zeilen) ruft jetzt benannte Schritte auf
(`_record_write_services`, `_configure_mail_numbers`, `_attach_mail_runtimes`, `_wire_profiles`,
`_attach_interfaces`) und hat 77 Zeilen. `_attach_web` (vorher 103 Zeilen) besteht aus
`_web_components`, `_attach_configuration`, `_attach_views`, `_attach_workers` und
`_record_service_health`. Die Anweisungen stehen in derselben Reihenfolge wie vorher; ein Prüfskript
stellte beim Zerlegen sicher, dass jede Anweisung genau einmal übernommen wurde. Die öffentliche
Signatur von `build_application` bleibt, weil Tests die Funktion mit Schlüsselwörtern aufrufen;
intern bündelt eine unveränderliche Datenklasse die Optionen der Oberflächen. Funktionen über
80 Zeilen im ganzen Paket: 10 statt 16.

Prüfung: 5 322 Python-Tests mit voller Abdeckung, 922 Browsertests. Der Lasttest
`test_an_action_shows_its_result_within_half_a_second_with_two_thousand_mails` lag im Gesamtlauf mit
einem Median von 508 ms knapp über der Grenze von 500 ms (direkt nach der parallelen Hauptsuite)
und bestand in drei Einzelläufen (höchstens 826 ms, Median jeweils unter 500 ms). Der gemessene Weg
ist durch 7.0.6 nicht verändert. Scheitert er erneut, wird er wie die Gruppierung in 7.0.5 untersucht.

## 7.0.7 – Weboberfläche (D6)

Vor dem Umbau in die eingefrorenen Ausgaben aufgenommen: die Auswertung der Vorschläge
(`/lernen/vorschlaege`) in sechs Sortierungen und mit Absender-Hinweisen sowie alle fünf Reiter der
Postfach-Einstellungen. Zerlegt, mit byte-gleicher Ausgabe:

| Funktion | vorher | nachher |
| :--- | :--- | :--- |
| `proposal_evaluation_page` | 179 Zeilen | 23 Zeilen und sieben Abschnittsfunktionen |
| `MailboxSite.mailbox` | 102 Zeilen | 28 Zeilen und eine Methode je Reiterart |
| `status_page` | 87 Zeilen | 37 Zeilen und drei Abschnittsfunktionen |

Gemeinsame Bausteine: Die vier gleich aufgebauten Tabellenabschnitte der Auswertungsseite nutzen
`_table_section`. Die Tabellen der übrigen Seiten unterscheiden sich in Tastaturzugang, Klassen und
Spaltenattributen; ein gemeinsamer Baustein müsste jede Abweichung als Option tragen und bleibt
deshalb aus. Funktionen über 80 Zeilen im Paket: 7 (keine mehr im Webteil).

Prüfung: 5 334 Python-Tests mit voller Abdeckung, 922 Browsertests. Der Lasttest
`test_an_action_shows_its_result_within_half_a_second_with_two_thousand_mails` scheiterte erneut
knapp (Median 500,2 ms bei Grenze 500 ms). Vergleich unter gleichen Bedingungen, je fünf Einzelläufe:
Stand 7.0.7 Median 454–556 ms (einmal rot), Ausgangsstand 6.9.3 in eigenem Arbeitsverzeichnis
460–521 ms (einmal rot). Der Umbau hat den Weg nicht verlangsamt; der Test liegt auf diesem Rechner
schon vor 7.0 an seiner Grenze. Die Grenze ist eine Produktanforderung und bleibt; offener Punkt für
die Abnahme (7.0.15): auf dem Produktivsystem messen und entscheiden.

## 7.0.8 – Prüfdienst und Telegram (D7)

| Funktion | vorher | nachher |
| :--- | :--- | :--- |
| `review/proposal_evaluation.py` `evaluate_proposals` | 146 Zeilen | 20 Zeilen und fünf Abschnittsfunktionen |
| `review/proposal_evaluation.py` `collect_decided_proposals` | 125 Zeilen | 58 Zeilen; Aufbereitung je Quelle in `_state_record` und `_log_record` |
| `telegram/update_handling.py` `_confirmation` | 103 Zeilen | 45 Zeilen; `_relevance_answer`, `_ask_removal`, `_execute_decision` |
| `telegram/presenter.py` `present` | 89 Zeilen | 40 Zeilen; `_decision_rows`, `_add_choice_rows`, `_association_row` |
| `review/views.py` `_view` | 84 Zeilen | 55 Zeilen; `_state_and_actions`, `_can_remove`, `_confirm_target` |

Die Reihenfolge jeder Prüfung blieb erhalten, etwa dass ein Eintrag aus dem Entscheidungsprotokoll
auch dann als gesehen gilt, wenn er am Zeitraum scheitert. Die letzte Zeile von `_confirmation`
(`return confirmation, None`) war unerreichbar, weil jeder Weg im `try`-Block zurückkehrt; sie entfällt.
Nebenbei verschwinden zwei Befunde des Ausgangsstands: die Verzweigungstiefe von
`collect_decided_proposals` (ruff C901) und ein Typfehler in `update_handling.py` (mypy jetzt 13).
Funktionen über 80 Zeilen im Paket: 2 (`cli._parser`, `llm/evaluation.evaluate`).

Prüfung: 5 334 Python-Tests mit voller Abdeckung (Lasttests bestanden), 922 Browsertests.
