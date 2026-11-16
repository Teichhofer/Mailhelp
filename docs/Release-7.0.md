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
`tests/release/test_repository_scope.py` verhindert, dass sie wieder versioniert werden.

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

**Schichten.** `tests/unit/test_layers.py` legt die Richtung der Importe fest, von unten nach
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

## 7.0.9 – Große Klassen nach Aufgaben (D8)

Die Rümpfe von Methoden ziehen als Funktionen in Module neben ihrer Klasse; statt `self` erhalten sie
das Objekt als ersten Parameter. Die Klasse behält jede Methode als einzeilige Weiterleitung. Aufrufe
zwischen den Methoden laufen weiter über das Objekt, sodass Tests, die Methoden ersetzen, unverändert
wirken. Namen aus dem Klassenmodul erreichen die neuen Module über das Modul selbst; so entstehen
keine Ladezyklen.

| Klasse | vorher | nachher | neue Module |
| :--- | :--- | :--- | :--- |
| `app.application.Application` | 532 Zeilen | 218 | `access_checks`, `run_loop` |
| `processing.orchestrator.Orchestrator` | 483 | 272 | `orchestrator_proposals`, `orchestrator_failures` |
| `mailbox.mailbox_run.MailboxRunService` | 578 | 156 | `run_polling`, `run_resume` |
| `review.service.ReviewService` | 566 | 366 | `removal`, `command_reconciliation` |
| `web.mailbox_site.MailboxSite` | 550 | 234 | `mailbox_profiles`, `mailbox_draft` |
| `processing.mail_pipeline.MailPipeline` | 465 | 243 | `pipeline_proposals`, `pipeline_failures` |

**Abweichung vom Plan.** Vorgesehen waren Mitarbeiterklassen. Tests rufen viele interne Methoden der
Klassen direkt auf oder ersetzen sie; eigene Mitarbeiterobjekte hätten Teständerungen über
Importpfade hinaus verlangt. Mixin-Klassen schieden aus, weil mypy in einem Mixin die Attribute der
eigentlichen Klasse nicht kennt.

**Beim Umbau gefunden und vor dem Commit behoben.**
- In `_reconcile_proposal` hieß eine lokale Variable wie der neue Parameter (`service`); die
  Zuweisung hätte das Objekt überschrieben. Mypy meldete die Typverletzung, eine Prüfung aller
  verschobenen Rümpfe fand keinen weiteren Fall. Der Parameter heißt dort `review`.
- `access_checks` ruft `_check_telegram_access` wie das Original bewusst über die Klasse auf.
- Die Typangabe von `_writer_for` zeigte auf einen nirgends importierten Namen (`ExternalWriter`,
  Befund seit 6.6); richtig ist `TargetWriter`, das als einziges `prepare_remove` kennt. Mypy meldet
  jetzt 12 statt 13 Fehler.

Schichtentest und Telegram-Grenze nennen die neuen Module; die Ausnahmen sind dieselben, nur unter
den neuen Modulnamen.

Prüfung: 5 334 Python-Tests mit voller Abdeckung (Lasttests bestanden), 922 Browsertests. Nebenbei
entfernte ruff einen ungenutzten Import in `web/proposal_evaluation_site.py` (Befund seit 6.5).

## 7.0.10 – Konfigurationsmodelle geteilt, Grenzwerte als Test (D9, Teil 1)

**`config/models.py`** (1 119 Zeilen) ist nach Bereichen geteilt: `base` (gemeinsame Basisklasse),
`mail_settings` (Postfächer, IServ), `target_settings` (Ziele, Zielprofile, Termin-Vorgaben),
`runtime_settings` (Telegram, Grenzen, Zeitlimits, Protokolle, Aufbewahrung, Web und weitere Dienste),
`topics` und `prompts`. In `models.py` bleiben `Settings`, `ImapCredentials` und `Secrets` (181 Zeilen).
`mailhelp.config` exportiert dieselben Namen wie vorher; `loader.py`, `setup_checks.py` und vier Tests
importieren aus dem neuen Modul. Ein Test zur Auflösung von Vorwärtsverweisen nutzte als Beispiel ein
Modell, das jetzt in einem anderen Modul als `Settings` liegt; er nutzt jetzt `ImapCredentials`.

**Grenzwerte.** `tests/unit/test_limits.py`: keine Funktion über 80 Zeilen (vorher 16, längste 179),
höchstens 10 Parameter. Zerlegt wurden noch `cli._parser` (91 Zeilen, jetzt nach Optionsgruppen) und
`llm/evaluation.evaluate` (87 Zeilen). `_build_orchestrator` erhält die Analysekonfiguration als
unveränderliche Datenklasse. 19 Funktionen bleiben benannte Ausnahmen mit Begründung: Konstruktoren,
denen der Zusammenbau jede Abhängigkeit einzeln übergibt, Aufrufe eines KI-Anbieters und
Einstiegspunkte, die Tests mit Schlüsselwörtern oder allen Argumenten aufrufen.

**Abweichung vom Plan.** Die strenge Typprüfung für das ganze Paket (R8) folgt wegen ihres Umfangs
als eigener Patch 7.0.11; die folgenden Patchnummern verschieben sich um eins.

Prüfung: 5 336 Python-Tests mit voller Abdeckung (Lasttests bestanden), 922 Browsertests.

## 7.0.11 – Vollständige Typangaben (D9, Teil 2; R8)

**Typprüfung.** `disallow_untyped_defs`, `disallow_incomplete_defs` und `disallow_untyped_calls`
stehen jetzt global unter `[tool.mypy]`. Vorher galten sie nur für eine Modulliste; mit den drei
Schaltern für alles meldete mypy 362 Fehler, jetzt keinen. Auch die 12 Fehler der bisherigen
Standardprüfung sind behoben (Ausgang 14).

**Vorgehen.** Fehlende Rückgabetypen und Parameter wurden mit den tatsächlichen Typen ergänzt. Für
zusammengesetzte Objekte (laufende Anwendung, Webseite, Komponenten) in unteren Schichten steht `Any`
mit einer Begründung im Code, weil selbst ein reiner Typimport der höheren Schicht eine
Schichtverletzung wäre. Zugelassene Werte sind benannte Typen (`MeetingMode`, `JobStatus`,
`Matcher`, `Pending`, `Snapshot`). `ConnectionActivation` ist generisch über die Art der Verbindung.
Lambdas mit Standardargumenten, deren Typ mypy nicht ableiten kann, sind durch `functools.partial`
oder kleine Fabrikmethoden ersetzt. Wo der Vertrag eines Modells einen Wert garantiert (Vorschlags-ID
eines Vorschlagsbefehls, Postfachliste bei `--learn`, Zeitpunkt eines nicht ganztägigen Termins),
steht ein `assert` mit Verweis auf die Garantie statt einer neuen Verzweigung.

**Abweichung vom Plan.** Die Modulliste in `pyproject.toml` entfällt nicht ganz. Sie verlangt für
den bisherigen strengen Kern weiterhin zusätzlich `disallow_any_generics`, `warn_return_any`,
`no_implicit_reexport` und `strict_equality`. Diese Schalter für das ganze Paket ergäben 117 weitere
Meldungen und sind nicht Teil von R8; sie wegzulassen hätte die Prüfung des Kerns gelockert.

**Nebenbei.** Vier Zeilen über 120 Zeichen aus den Verschiebungen von 7.0.9 umbrochen;
`ExperienceRuntime.__init__` wieder unter 80 Zeilen. Ruff meldet 27 Befunde (7.0.10: 29).

## 7.0.12 – Frontend nach Bereichen (D10; R7)

**Skripte.** `app.js` (1 593 Zeilen) ist in sechs Dateien geteilt, die jede Seite ohne Bündler in
fester Reihenfolge mit `defer` lädt (`PAGE_SCRIPTS` in `web/pages.py`): `app.js` (Verbindung,
Formularsperre, fixierte Leisten; 178 Zeilen), `open-list.js` (Offen-Liste, Hintergrundabgleich,
Kartenaktionen und Wischgeste; 600), `dialogs.js` (Dialoge, Diagrammdetails, Tastenkürzel,
Schnellfilter, Bildvorschau, Entwurf kopieren; 207), `push.js` (206), `settings.js`
(Seitenleiste, Einstellungslinks, Live-Suche; 125) und `help.js` (Hilfefenster; 303). Die Reihenfolge
entspricht der bisherigen Reihenfolge im Quelltext. Damit bleiben die Reihenfolge der Ereignis-Handler
und die Reihenfolge der in die Kopfleiste eingefügten Knöpfe gleich. `dialogs.js` liest den Zustand
der Offen-Liste über `window.MailhelpOpen`; Ausschnitt und Auswahl sind dort Getter, weil sie sich
zur Laufzeit ändern. Jede Datei hat einen eigenen Hash in ihrer Adresse, sodass der Browser nach
einer Aktualisierung jede geänderte Datei neu lädt. Der Service Worker speichert wie bisher nur
`offline.html`, `app.css` und die Symbole; Skripte gehören nicht zu seinem Cache. Die
JavaScript-Abdeckung der Browsersuite umfasst alle neuen Dateien und bleibt bei 100 % der Blöcke.

**Abweichung: Wischgeste nicht getrennt.** Offen-Liste und Wischgeste rufen sich gegenseitig auf,
auch aus Rückrufen laufender Statusabfragen. Getrennte Dateien hätten zwischen dem Ausführen beider
Dateien eine Lücke gelassen, in der eine Antwort auf noch nicht geladene Funktionen trifft. Beide
bleiben daher in `open-list.js`.

**Stylesheet.** Die Nutzung jeder Regel wurde einmalig über die ganze Browsersuite gemessen
(Chrome-DevTools `CSS.startRuleUsageTracking`, alle Geräteprofile). Von 752 Regeln griffen 60 auf
keiner Seite. Jede davon wurde gegen den Quelltext geprüft. Entfernt sind die sechs Regeln, deren
Klassen nirgends mehr erzeugt werden: `.filter-box` (seit 6.2.6 ungenutzt), `.model-overview` und
`.rule-select` (seit 6.0.4). Die übrigen 54 bleiben. Ihre Klassen entstehen zur Laufzeit
(`share-…` der Ablaufbalken, `help-top-left` aus gespeicherten Fensterpositionen) oder sie gelten
für Zustände, die die Suite nicht herstellt (dunkles Farbschema, Hover, seltene Ergebnisse).

**Abweichung: keine Umsortierung.** `app.css` wird nicht nach Bereichen umsortiert. Bei gleicher
Spezifität entscheidet die Reihenfolge, welche Regel gilt. Eine Umsortierung hätte daher die
Darstellung ändern können, ohne dass ein Test es zuverlässig bemerkt.

**Eingefrorene Seiten.** Die Vergleichsdateien in `tests/golden/output` enthalten die Adressen von
Stylesheet und Skripten samt Hash. Sie wurden neu geschrieben. Der Unterschied besteht nur aus den
fünf neuen Skriptzeilen und den geänderten Hashes; sonst ist jede Seite byte-gleich.

**Bildschirmfotos.** Alle 525 Bildschirmfotos der Browsersuite wurden pixelweise mit einem Lauf von
7.0.11 (eigener Worktree) verglichen. Zwei Läufe desselben Stands unterscheiden sich bereits in 91
Bildern (Uhrzeiten, Zeitpunkt von Animationen). Zehn Bilder weichen nur gegenüber 7.0.12 ab; alle
zehn wurden angesehen. Die Unterschiede liegen in der Kantenglättung gedrehter Karten mitten in der
Wischgeste, im Schatten eines gerade eingeblendeten Hinweises und in der Lage der festen Leiste beim
Scrollen. Inhalt und Anordnung sind gleich.

Prüfung: 5 342 Python-Tests mit voller Abdeckung, 922 Browsertests, JavaScript-Abdeckung 100 % der
Blöcke in allen zehn Skripten.

## 7.0.13 – Testdateien nach Thema (D11; R6)

**Umbenannt.** 185 Testdateien trugen eine Versionsnummer im Namen (`test_v43_series.py`,
`test_ui_swipe69.py`, `test_layers70.py`). Sie heißen jetzt nach ihrem Thema (`test_series.py`,
`test_ui_swipe_tracking.py`, `test_layers.py`). Umbenannt wurde mit `git mv`, sodass die Historie
jeder Datei erhalten bleibt. Angepasst sind die Verweise in `devtools/check.py` (Lasttests), der
Testauswahl von `[tool.mutmut]`, `tests/release/test_quality_commands.py`, der Spezifikation,
`docs/archiv/Paketstruktur.md` und den Quellcode-Kommentaren zu den Schichtausnahmen. Verlaufsdokumente
(CHANGELOG, frühere Pläne und Berichte) nennen weiter die damaligen Namen.

**Abweichung: genauer benannt statt zusammengeführt.** Wo zwei Dateien denselben Themennamen
bekommen hätten (zum Beispiel `test_ui_swipe63.py` und `test_ui_swipe69.py`) oder der Name ohne
Version kein Thema mehr nannte (`test_ui_v20.py`), steht jetzt ein genauerer Name aus dem Docstring
der Datei: `test_ui_swipe_decide.py` / `test_ui_swipe_tracking.py`, `test_ui_comfort.py`,
`test_load_action_start.py` / `test_load_store_lock.py` / `test_load_result_latency.py`.
Zusammenführen hätte gleichnamige Hilfsfunktionen auf Modulebene kollidieren lassen, ohne für die
Prüfung etwas zu gewinnen. Alle Basisnamen bleiben projektweit eindeutig; das ist nötig, weil die
Testordner keine Pakete sind.

**Geteilt.** Die drei größten Dateien sind nach Themen in zusammenhängende Blöcke geteilt. Die
Reihenfolge innerhalb jedes Blocks ist unverändert, die Importe sind auf das Nötige reduziert:

| Vorher | Zeilen | Nachher |
| :--- | ---: | :--- |
| `tests/telegram/test_telegram_dialog.py` | 2 336 | `test_telegram_temporal_answers`, `_persistence`, `_cards`, `_answers`, `_client_api`, `_confirmation` |
| `tests/services/test_services.py` | 2 187 | `test_analyzer_core`, `test_analyzer_prompts`, `test_analyzer_revisions`, `test_service_integrations`, `test_orchestrator_flow`, `test_calendar_duplicates`, `test_reasoning_budgets` |
| `tests/services/test_application.py` | 1 920 | `test_mailbox_run_queue`, `test_mailbox_checkpoints`, `test_run_relevance_wait`, `test_run_resume_summary`, `test_composition_startup` |

Die größte Testdatei hat jetzt 1 037 Zeilen (`tests/services/test_experience.py`), vorher 2 336.

**Nachweis.** Vorher und nachher wurden die gesammelten Tests verglichen. Nach dem Umbenennen
entsprechen sich alle 5 345 Python- und 1 136 Browsertests eins zu eins (alter Pfad über die
Zuordnung auf den neuen abgebildet). Nach dem Teilen sind die Test-IDs ohne Dateipfad dieselben
5 345, keine fehlt und keine ist doppelt.

## 7.0.14 – Archiv, Inhaltsverzeichnis und Architektur (D12; K2, K3)

**Archiv.** 114 abgeschlossene Pläne, Release-Berichte, Konzepte, Prüfberichte, die drei alten
Architekturdokumente, `Paketstruktur.md` und die vier Bilder zu 5.8 (118 Dateien) liegen jetzt in
[`docs/archiv/`](archiv/), verschoben mit `git mv`. In `docs/` bleiben die zwölf lebenden
Dokumente aus K1, die laufenden Pläne (Planung 7.0, Release 7.0, Lernmodus) und der Prüfbericht
5.3. Den schreibt `devtools/inventory.py` als laufende Inventur aller Einstellungen fort; er wird
in 7.0.15 durch den Prüfbericht 7.0 abgelöst.

**Verweise.** Jeder relative Link in allen Markdown-Dateien wurde vom alten Ort aus aufgelöst und
vom neuen Ort aus neu berechnet; ebenso Erwähnungen der Form `docs/…` in Code, Konfiguration und
Tests sowie die Liste der Dateien im Quellpaket (`[tool.hatch.build.targets.sdist]`). Ausgenommen
sind die Versionshinweise zu getaggten Ständen (`devtools/release_notes.py` und sein Test): Dort
lagen die Dokumente noch unter `docs/`. Vor dem Umzug zeigten 16 Links ins Leere (geplante Dateien,
Quellpfade aus alten Versionen); danach sind es dieselben.

**Fehler gefunden und behoben: Versionshinweise alter Tags.** `.github/scripts/release_notes.py`
macht aus den Links eines CHANGELOG-Abschnitts Links auf den getaggten Stand. Nach dem Umzug
hätte er für Tags vor 7.0.14 auf `docs/archiv/…` gezeigt, das es dort nicht gibt, und den
Release-Leitfaden nicht mehr gefunden. Er setzt solche Links jetzt für ältere Tags auf `docs/`
zurück und sucht den Leitfaden an beiden Orten. Der Regressionstest
`test_regression_archived_documents_are_linked_where_the_tag_holds_them` scheitert mit dem alten
Skript und besteht mit dem neuen.

**Neuer Test.** Der in K2 vorausgesetzte Verweis-Test existierte nicht.
`tests/release/test_documentation_links.py` prüft jetzt jeden relativen Link aller versionierten
Markdown-Dateien. Links aus dem Archiv in den Code sind ausgenommen, weil archivierte Dokumente den
Stand ihrer Version beschreiben. Dazu prüft er, dass keine Pläne oder Berichte vor 7.0 außerhalb
des Archivs liegen und dass `docs/README.md` jedes lebende Dokument nennt. Ein Link eines alten
Qualitätsberichts auf `src/mailhelp/analysis.py` zeigt jetzt auf den heutigen Ort in `processing/`.

**Inhaltsverzeichnis.** [`docs/README.md`](README.md) ordnet die lebenden Dokumente nach Einrichten
und Bedienen, Betrieb, Aufbau und laufender Arbeit.

**Architektur.** [`docs/Architektur.md`](Architektur.md) ersetzt `Architektur-1.6`, `-2.1`, `-2.4`
und `Paketstruktur`. Es beschreibt die Schichten aus `tests/unit/test_layers.py`, die Grenzen für
Größe und Typen, den Weg einer Mail durch die Verarbeitungsschritte, den Bestätigungsweg vom
Prüfbefehl bis zum nachgewiesenen Eintrag, die Zustandsdateien aus `state_names.py` und die
Migrationen der Altformate. Jede Aussage wurde beim Schreiben gegen den Code geprüft.

## 7.0.15 – Prüfung der lebenden Dokumente (D13; K4, K5, K6)

**Prüfung (K4).** Jedes lebende Dokument wurde Abschnitt für Abschnitt gegen Code und Oberfläche
gelesen. Das Protokoll steht in [Prüfung der Dokumentation 7.0](Pruefung-Dokumentation-7.0.md)
und nennt je Abschnitt Ergebnis und Fundstelle im Code. Korrigiert wurden unter anderem:

- **Konten verwalten, Einstellungen, Einrichtung:** IServ-Konten werden seit der Direktaktivierung
  ohne Neustart im nächsten sicheren Mailzyklus abgerufen. Drei Dokumente beschrieben noch den
  Weg über Diagnose, Entwurf und Neustart. Entwürfe für Postfach- und IServ-Verbindungen brauchen
  dagegen weiterhin einen Neustart; das fehlte beim Entfernen.
- **Einrichtung und Qualitätsprüfung:** Der Satz, Erststart, OAuth und Lernmodus im Browser seien
  „noch nicht implementiert“, stimmte seit 3.7/3.8 nicht mehr.
- **Bedienung:** Die Statusseite heißt „Letzte Fehler und Handlungsbedarf“.
- **Datenschutzerklärung:** Der technische Stand war 3.4.5. Ergänzt sind Lernbestand mit
  Ablehnungsgründen, Hilfschat, Regellernen, Nachprüfung, Ändern, Absagen und Entfernen eigener
  Einträge (auch bei der Google-Berechtigung), die automatische Entwurfsablage je Postfach und
  die Frist für Hilfschat-Gespräche.
- **Nutzungsbedingungen:** Stand 3.3.1; automatische Entwurfsablage und Apple Erinnerungen.
- **Spezifikation:** Knopf- und Statustexte aus 6.0.4 und 6.6 sowie die Zuordnung des
  Verhaltens zu `open-list.js`; neue Ergänzung 7.0 (Schichten, Typen, Skriptdateien).
- **Betrieb:** eine längst erledigte Ankündigung aus 6.4 entfernt.

Nicht im Einzelnen geprüft sind die fachlichen Regeln der Spezifikation aus früheren Versionen
(4 410 Zeilen in versionsweisen Ergänzungen). Geprüft wurden dort alle Bezüge auf Code,
Oberfläche und Konfiguration; die Satz-für-Satz-Prüfung jeder Regel bleibt offen und ist im
Protokoll so vermerkt. Ebenfalls nicht prüfbar sind Schritte in fremden Oberflächen (Google,
Microsoft) und Wege mit echten Konten.

**Automatische Prüfungen (K5).** `tests/release/test_documentation_checks.py` prüft bei jedem
Lauf die in den lebenden Dokumenten genannten Konfigurationsschlüssel, Kommandozeilenoptionen,
Umgebungsvariablen (in beide Richtungen mit `.env.example`), die in den Anleitungen zitierten
Beschriftungen und die genannten Repository-Dateien. Zitate, die keine Beschriftung sind,
stehen mit Begründung in einer Ausnahmeliste. Ein Selbsttest weist nach, dass jede Prüfung eine
falsche Angabe findet. Die Inventur aller Einstellungen schreibt `devtools/inventory.py` jetzt
in den Prüfbericht 7.0; der Bericht 5.3 liegt im Archiv.

**Stand-Zeilen und README (K6).** Jedes lebende Dokument trägt „Geprüft für Mailhelp 7.0“; ein
Test verlangt die aktuelle Hauptversion, sodass ein ungeprüftes Dokument spätestens bei 8.0
auffällt. Das README ist von 955 auf 191 Zeilen gekürzt: Einstieg, Schnellstart,
Konfiguration, Datenschutz, Entwicklung und Verweise. Die Versionsgeschichte steht nur noch im
CHANGELOG; das README nennt nur die aktuelle Version. Dabei sind veraltete Angaben zur
parallelen Prüfung und zur Typprüfung entfallen.

**Prüfhilfe für die Wartung.** Die Prüfung der fett gesetzten Beschriftungen diente als
Hilfsmittel und ist kein Test, weil Fettdruck auch zur Betonung dient.

**Zeitabhängiger Wischtest behoben.** `test_bounded_momentum[mobile-80-False-True]` scheiterte
etwa bei jedem dritten Lauf, auch einzeln. Mit dem Stand 7.0.11 waren es drei von sechs Läufen; die
Ursache lag also nicht in der Teilung der Skripte. Der Test simuliert einen schnellen Wisch über
1 ms. Die Seite misst die Geschwindigkeit aus `event.timeStamp`, und dieser Zeitstempel kam aus der
echten Zeit zwischen den CDP-Aufrufen, die unter Last weit über 1 ms liegt. Der Helfer
`ui_tests/swipe_fakes69.Touch` kann jetzt jedes Ereignis mit einem Zeitstempel einer virtuellen Uhr
senden (`exact=True`, CDP-Parameter `timestamp`). Damit misst die Seite genau die verlangte Dauer.
Schwelle und Erwartung des Tests sind unverändert. Neu prüft
`test_exact_touch_clock_sets_the_event_times`, dass die Abstände trotz langer echter Wartezeit auf
0,1 ms genau ankommen. Danach bestand der Wischtest zehnmal hintereinander.

**Live-Suche im parallelen Lauf.** `test_results_are_visible_within_300_ms_in_95_percent_of_100_searches`
schlug in den letzten drei Browserläufen mit sechs Prozessen fehl, besteht aber allein. Einzeln
gemessen liegen 7.0.13 und 7.0.15 gleich (Median 229 bzw. 228 ms, 95. Perzentil 242–247 ms): keine
Verlangsamung, sondern die Last der parallel laufenden Browser. Die Grenze von 300 ms bleibt; die
Frage, ob dieser Messtest seriell laufen soll, gehört zur Abnahme (7.0.16).

Prüfung: 5 458 Python-Tests mit voller Abdeckung, 922 Browsertests (ein Lastfehlschlag wie oben),
JavaScript-Abdeckung 100 %.

## 7.0.16 – Abnahme

Gemessen an den Abnahmekriterien aus Abschnitt 7 der [Planung](Planung-7.0.md); Vorher-Werte aus
7.0.1, Nachher-Werte vom Stand 7.0.15.

| Kriterium | Grenzwert | Ergebnis | Erfüllt |
| :--- | :--- | :--- | :--- |
| Eingefrorene Ausgaben | Byte für Byte gleich 7.0.1 | Telegram unverändert; Webseiten bis auf die Skript- und Stylesheet-Zeilen mit ihren Hashes gleich (7.0.12, beabsichtigt) | mit Abweichung |
| Bestandsprüfung | jede Zustandsdatei nach Laden und Speichern identisch | Prüfsumme über 4 840 Dateien vorher und nachher `66a76398…2d6aba` | ja |
| Tests | Zahl nicht gesunken; keine geänderte Prüfung in Umbau-Patches | 5 318 (7.0.3) → 5 458 Python-Tests, 1 136 → 1 138 gesammelte Browsertests; Umbenennen und Teilen eins zu eins nachgewiesen (7.0.13) | ja |
| Abdeckung | 100 % Zeilen und Branches; 100 % JS-Blöcke | 34 688 Anweisungen, 10 014 Branches, alle JS-Dateien 100 % | ja |
| Mutationswerte des Kerns | nicht schlechter als vor 7.0 | 1 158 → 1 163 getötet (78,35 % → 78,69 %); `domain` 520 → 524, `storage` 454 → 455, `confirmed` 184 → 184 | ja |
| Längste Funktion | ≤ 80 Zeilen (vorher 179) | 80 Zeilen; über 80: 16 → 0, über 60: 46 → 35 | ja |
| Meiste Parameter | ≤ 10 (vorher 32) | weiterhin 32 (`JsonlLogger.__init__`); 19 Funktionen über 10 als benannte Ausnahmen in `test_limits.py` | nein |
| Importe in Funktionen | ≤ 20, jeder begründet (vorher 328) | 25, jeder mit Begründung im Code | nein (25 statt 20) |
| Schichten | kein Import gegen die Richtung außer benannten Ausnahmen | `test_layers.py` grün, 26 benannte Ausnahmen | ja |
| `mypy` | streng für das ganze Paket, ohne Befund | 0 Befunde; Zusatzschalter weiter nur für den Kern (7.0.11) | ja |
| Laufzeit des Dienstes | Abrufzyklus und Start im Lasttest nicht schlechter (5 %) | Lasttests bestanden; Live-Suche allein unverändert (Median 228 ms) | ja |
| Laufzeit der Prüfung | volle Prüfung ≤ 6 Minuten, kein Test über 30 s | 9:33 Minuten mit `--workers 12` (vorher 44 Minuten) | nein |
| Lebende Dokumente | alle geprüft, Protokoll vollständig, Stand-Zeile | geprüft und protokolliert; Satz-für-Satz-Prüfung der fachlichen Regeln der Spezifikation offen | mit Abweichung |
| Betrieb | Produktivserver ohne manuelle Schritte von 6.9 auf 7.0; Rückweg möglich | Zustandsformat unverändert (Bestandsprüfung), Rückweg damit möglich; die Aktualisierung des Servers führt der Betreiber aus | offen (Betreiber) |

**Begründung der Abweichungen.**

- *Parameter:* Die verbleibenden langen Parameterlisten gehören zu Konstruktoren, denen der
  Zusammenbau jede Abhängigkeit einzeln übergibt, und zu Einstiegspunkten, die Tests mit
  Schlüsselwörtern aufrufen. Sie in Parameterobjekte zu bündeln, hätte jeden dieser Aufrufe
  geändert, ohne Verhalten oder Lesbarkeit zu verbessern. Sie stehen als Ausnahmen mit Grund im
  Test, neue kommen nicht unbemerkt hinzu.
- *Späte Importe:* 18 sind benannte Importe gegen die Schichtrichtung, zwei laden plattformabhängige
  Module (`msvcrt`, `fcntl`), fünf lösen echte Paarzyklen auf (siehe 7.0.4). Jeder trägt im Code eine
  Zeile `# Late: …` mit dem Grund.
- *Prüfdauer:* Die Abdeckungsmessung kostet bei 12 Prozessen den größten Teil der Zeit (siehe
  7.0.5). Ohne Abdeckung laufen die Tests in unter zwei Minuten. Die Python-Prüfung ist trotzdem
  rund viermal schneller als vor 7.0.
- *Eingefrorene Ausgaben:* Die Teilung von `app.js` ändert die Script-Zeilen jeder Seite. Der
  Unterschied wurde auf genau diese Zeilen geprüft, und die Bildschirmfotos wurden pixelweise
  verglichen (7.0.12).

**Mutation.** Gemessen in WSL mit dem Stand 7.0.15, gespeichert in
`quality-reports/mutation-7.0-nachher.json`. Die Schwelle von 90 % des wöchentlichen Laufs erreicht
Mailhelp wie vor 7.0 nicht; das ist kein Ziel von 7.0 gewesen.

Prüfung: 5 458 Python-Tests mit voller Abdeckung (9:25 Minuten). Browser: 921 bestanden; die Live-Suche
(siehe 7.0.15) und einmal `test_overview_refreshes_itself_but_never_discards_typed_text[mobile]`
scheiterten unter Last und bestanden einzeln (fünfmal je drei Ansichten).

**Offen für den Betreiber.** Aktualisierung des Produktivservers auf 7.0 und die Frage, ob die
Messtests (Live-Suche, Latenz v441) im parallelen Browserlauf seriell laufen sollen.

