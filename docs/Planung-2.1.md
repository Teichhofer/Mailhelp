# Mailhelp 2.1 – Planung: Aufräumen und bessere Tests

**Zielversion:** 2.1.0
**Stand:** 12. Oktober 2026
**Status:** In Planung (folgt auf 2.0.0)
**Grundlage:** [Entwicklungsregeln](../AGENTS.md), [Architektur-1.6.md](Architektur-1.6.md),
[Release-2.0.md](Release-2.0.md)

---

## 1. Ziel

Version 2.1 bringt keine neuen Funktionen. Sie macht den Code nach fünf
Funktionsreleases wieder leicht änderbar und die Tests aussagekräftiger.

Verbindlich für jeden Schritt:

- Nutzerabläufe, Web-Routen, CLI-Optionen, Konfiguration, JSON-Zustandsschemas
  und externe API-Verträge bleiben gleich. Eine Ausnahme braucht einen eigenen
  Eintrag in `CHANGELOG.md` und einen Upgrade-Test.
- Die Bestätigungsschranke, Idempotenz und das Abgleichen unklarer
  Schreibresultate werden nicht angefasst, sondern nur verschoben – mit
  unveränderten Tests davor und danach.
- Jeder Schritt ist für sich grün: 100 % Zeilen- und Branch-Abdeckung,
  Browsertests mit 100 % JavaScript-Blockabdeckung.
- Gefundene Fehler werden als Bugfix mit Regressionstest behoben, nicht im
  Refactoring versteckt.

---

## 2. Bestandsaufnahme (Stand 2.0.0)

| Messgröße | Wert |
| :--- | :--- |
| Anwendungscode | 21.400 Zeilen in 114 Modulen |
| Testcode | 26.800 Zeilen, 1.081 Testfunktionen (1.613 Fälle mit Parametrisierung), 86 Browsertests |
| Laufzeit Python-Suite | ca. 100 s; langsamster Test 1,6 s |
| Funktionen ≥ 60 Zeilen | 38; die größten: `Orchestrator.process` (298), `MailboxRunService.poll_global` (229), `build_application` (200), `interpret_pending` (191), `cli._main` (189) |
| Klassen mit > 20 Methoden | `MailhelpSite` (27), `TelegramDialogController` (26), `Orchestrator` (24), `Analyzer` (21) |
| Importe innerhalb von Funktionen | 49, davon 8 in `application.py`, 7 in `telegram/dialog.py`, 10 in `web/site.py` und `web/archive_site.py` |
| `except Exception` / nacktes `except` | 69, davon 12 in `application.py` |
| `hasattr`/`getattr`-Weichen | 44; viele nur, weil Test-Fakes Methoden fehlen (z. B. `hasattr(self.store, "load_model")`) |
| Zugriffe auf private Namen anderer Module | in 27 Modulen (z. B. `store._thread_lock`, `imap._mailbox_argument`, `vision._open`, `_MailBudget`) |
| Zeilen > 120 Zeichen | 185, davon 34 in `web/archive_site.py` |
| Statische Prüfung | keine (kein Linter, keine Typprüfung in der CI) |
| Testdateien nach Version benannt | 15 (`test_v12_gaps.py`, `test_v13_*.py`, `test_experience_v20.py`, …) |
| Fake-Klassen in Tests | 59 Definitionen, z. B. `Log` 8×, `Logger` 6×, `Provider` 6×, `Telegram` 5× |
| Importe zwischen Testmodulen | z. B. 14× aus `test_core`, 11× aus `test_telegram_dialog`, 9× aus `test_application` |
| Tests über private Methoden | `_poll_imap` 66×, `_decide` 12×, `_resume_pending` 8× |

---

## 3. Aufräumen des Anwendungscodes

Die Arbeitspakete sind nach Nutzen geordnet. A1–A3 schaffen die Grundlage für
alle weiteren.

### A1 – Statische Prüfung einführen

- `ruff` (Pyflakes, isort, pyupgrade, bugbear, `E501` mit 120 Zeichen) und
  `mypy` in `pyproject.toml` konfigurieren, Versionen fest in
  `requirements.lock` (Testabhängigkeiten).
- Zuerst nur melden, Bestand als Ausgangsbasis erfassen; dann je Paket auf
  „fehlerfrei“ ziehen und als CI-Schritt erzwingen.
- `mypy --strict` zuerst für `domain/`, `external/contracts.py`, `drafts.py`,
  `webpush.py`, `briefing.py`, `attachments.py`; danach schrittweise erweitern.
- Abschluss: keine Zeile > 120 Zeichen, keine ungenutzten Importe, einheitlich
  `from __future__ import annotations` (fehlt in 19 Modulen).

### A2 – Ein Speicher-Protokoll statt Duck-Typing

Heute prüfen `orchestrator.py`, `application.py` und `mailbox_run.py` mit
`hasattr(self.store, "load_model")`, `hasattr(self.store, "names")` oder
`hasattr(self.store, "directory")`, weil einzelne Test-Fakes nur `load`/`save`
haben. Produktiv gibt es nur `JsonStore`.

- `StateStore`-Protokoll (`typing.Protocol`) mit `load`, `save`, `load_model`,
  `peek_model`, `names`, `locked()`, `directory`.
- Öffentliche Sperre: `JsonStore.locked()` ersetzt alle direkten Zugriffe auf
  `store._thread_lock` (`drafts.py`, `webpush.py`, Tests).
- Alle Weichen entfernen; Test-Fakes delegieren an einen echten `JsonStore`
  in `tmp_path` (siehe T2).
- Zustandsnamen zentral: Ein Modul `state_names.py` mit Funktionen wie
  `mail(mail_id)`, `draft(mail_id)`, `proposal(mail_id, pid, version=None)`
  ersetzt die verstreuten Zeichenketten `"mail-"`, `"mail-run-"`, `"draft-"`,
  `"push-subscriptions"` usw. Das Filtern von `mail-run-` aus `mail-` geschieht
  heute an fünf Stellen.

### A3 – Typisierte vorbereitete Mail

`MailState.mail` ist ein `dict[str, Any]`, auf das an vielen Stellen mit
Zeichenkettenschlüsseln zugegriffen wird (`mail["headers"]["message_id"]`,
`extracted_attachments`, `preview`, `calendar_events`). `analysis.py` behandelt
Anhänge sogar wahlweise als Dict oder Objekt.

- Pydantic-Modelle `PreparedMail`, `MailHeaders`, `ExtractedAttachment`,
  `ImagePreview` mit `extra="allow"` für das Lesen alter Zustände.
- Gespeichertes JSON bleibt byte-gleich; ein Snapshot-Test mit gespeicherten
  Zuständen aus 1.4, 1.6 und 2.0 sichert das (siehe T5).

### A4 – Große Abläufe in benannte Schritte zerlegen

Ziel: keine Funktion über 80 Zeilen, keine Klasse über 20 Methoden.
Jede Zerlegung erfolgt ohne Verhaltensänderung, abgesichert durch die
bestehenden Neustarttests (Unterbrechung an jeder dauerhaften Grenze).

| Ort | Vorgehen |
| :--- | :--- |
| `Orchestrator.process` (298 Z.) | Je `ProcessingStage` eine Methode (`_prepare`, `_relevance`, `_summary`, `_actions`, `_notify`, `_complete`) mit gemeinsamem Rückgabetyp; `process` wird zur Schleife über die Stufen. |
| `MailboxRunService.poll_global` / `poll` | Discovery, Queue-Fortschritt und Checkpoint-Schreiben trennen; die privaten Helfer (`_MailBudget`, `_RunSummary`, `_add_uid`, `_checkpoint_name`), die `application.py` heute importiert, werden öffentlich oder bleiben im Modul. |
| `build_application` (200 Z.) | In `composition.py` je Teil eine Fabrik (`build_llm`, `build_writers`, `build_telegram`, `build_web`, `build_experience`); die 8 lokalen Importe wandern an den Modulanfang oder bewusst in eine Fabrik. |
| `cli._main` (189 Z.) | Je Unterbefehl eine Funktion, Zuordnung über ein Dict. |
| `telegram/answer_interpretation.interpret_pending`, `telegram/revisions.answer`, `TelegramDialogController` | Entlang der in 1.6 begonnenen Grenzen weiter teilen; `poll_once` und `_handle` als Dispatcher. |
| `MailhelpSite` (27 Methoden) | Anmeldung/Geräte in `web/login_site.py`, Vorschlags- und Mailseiten in `web/review_site.py`; `MailhelpSite` nur noch Routing und gemeinsame Helfer. |

### A5 – Seiten ohne String-Ersetzung zusammensetzen

`web/site.py` fügt Inhalte per `page.replace("</main>", …)` und
`page.replace('<main id="inhalt">', …)` ein; Filterchips, Entwurfseditor und
Analyse werden so nachträglich in fertiges HTML geschoben.

- Renderer nehmen zusätzliche Abschnitte als Parameter
  (`detail_page(…, extra_sections=[…])`, `overview_page(…, before=…)`).
- `ExperienceSite` registriert heute `/offen` neu und baut HTML selbst; Routen
  und Abschnitte werden an einer Stelle zusammengeführt.
- Der Byte-Vertrag aus `test_refactoring_v16.py` bleibt gültig.

### A6 – Schichten und Abhängigkeiten bereinigen

- `review/queries.py` importiert `web/filters.py` in einer Schleife: Die
  Filterlogik gehört nach `review/`, das Web rendert nur die Chips.
- `web/archive_site.history` sucht für jede Verlaufszeile die Mail per
  `next(...)` in allen Mails (quadratisch). Ein Index nach Mail-ID beim Laden
  reicht.
- Private Importe zwischen Modulen auflösen: `vision._open` (von
  `attachments.py`), `imap._mailbox_argument` (von `drafts.py`),
  `storage._atomic_replace` (von `configuration.py`, `metrics.py`),
  `decisions._yaml`/`_validated_file` (von `laya.py`), `_raise_for_status`
  (von `laya.py`, `ollama.py`). Was geteilt wird, bekommt einen öffentlichen
  Namen in einem passenden Modul.
- Kompatibilitätsfassaden prüfen: `integrations.py` und die Re-Exporte in
  `web/review_pages.py` und `telegram/__init__.py` reichen auch private Namen
  weiter. Interne Aufrufer stellen auf die echten Module um; die Fassaden
  bleiben nur für öffentliche Namen und erhalten einen Hinweis auf ihr
  Entfallen in 3.0.

### A7 – Fehlerbehandlung vereinheitlichen

- Die 69 breiten `except`-Blöcke einzeln einordnen: (a) Prozessgrenze mit
  Protokoll und Fortsetzung – bleibt, mit einheitlichem Helfer
  `log_and_continue(logger, module, event)`; (b) gezielt fangbare Fehler –
  konkreten Typ angeben; (c) überflüssig – entfernen.
- Eine gemeinsame Ausnahmehierarchie für externe Dienste
  (`ExternalUnavailable`, `ExternalRefused`, `ExternalUncertain`) statt
  Mischungen aus `OSError`, `httpx`-Fehlern und eigenen Klassen. Die
  Einordnung „unklar“ bleibt fachlich unverändert.
- Ausnahmetexte enthalten nie Mail-, Prompt- oder Zugangsdaten; ein Test
  prüft das für alle eigenen Ausnahmeklassen.

### A8 – Kleinere Punkte

- `hasattr`/`getattr`-Weichen auf Settings und Clients (`primary_folder`,
  `service_name`, `last_relevance_source`) durch Protokolle oder Pflichtattribute
  ersetzen.
- Gleiche Zeitformatierung (`%d.%m.%Y, %H:%M Uhr`) steht in sechs Modulen von
  `review/` und `web/`; ein gemeinsamer Helfer.
- Bildvorschau: Anhänge werden heute nur über den MIME-Typ erkannt, die
  Bilderkennung zusätzlich über die Dateiendung. Beide über dieselbe Funktion
  auswählen (eigenes Paket mit Regressionstest, da Verhaltensänderung).

---

## 4. Bessere Tests

### T1 – Tests nach Fachgebiet statt nach Version ordnen

15 Dateien sind nach Release benannt; dazu kommen Sammeldateien
(`test_services.py` 2.185 Zeilen, `test_telegram_dialog.py` 2.342,
`test_application.py` 1.882, `test_core.py` 852).

Neue Ordnung (Verzeichnisse unter `tests/`):

```text
tests/
  unit/         domain, mime, temporal, calendar_parser, action_normalization, yaml_edit
  services/     orchestrator, mailbox_run, review, drafts, webpush, briefing, retention
  telegram/     dialog, outbox, receiver, revisions
  web/          auth, pages, actions, archive, experience, server
  external/     calendar, todoist, oauth, ical, openrouter, ollama
  upgrade/      Fingerprints, gespeicherte Altzustände, Renderer-Verträge
  e2e/          simulierte Gesamtabläufe
  fakes/        gemeinsame Test-Doubles (T2)
  scenarios/    synthetische Daten (web_scenario, Qualitätskorpus)
```

Verschoben wird zuerst ohne Inhaltsänderung (Coverage und Testanzahl gleich),
erst danach werden Tests umgeschrieben. Kein Test importiert mehr aus einem
anderen Testmodul, nur aus `fakes/` und `scenarios/`.

### T2 – Gemeinsame Test-Doubles

- `tests/fakes/`: `RecordingLogger`, `FakeTelegram`, `FakeImap` (inklusive
  `APPEND`, `SEARCH`, UTF-7-Ordner), `FakeWriter` (Kalender/Todoist mit
  Fehler- und Unklar-Szenarien), `FakeLlm` (Antworten je Schritt,
  Ratenbegrenzung), `FakePushService`, `FakeClock`.
- Jedes Double implementiert dasselbe Protokoll wie die echte Klasse; mypy
  prüft das (A1). Fehlende Methoden fallen so beim Testen auf, statt per
  `hasattr` im Anwendungscode abgefangen zu werden (A2).
- `SimpleNamespace` (138×) nur noch für reine Datenwerte, nicht als Ersatz
  ganzer Dienste.
- Ein Vertragstest je Double läuft dieselben Fälle gegen Double und – soweit
  ohne Netz möglich – die echte Klasse.

### T3 – Über öffentliche Schnittstellen testen

Tests rufen heute oft private Methoden direkt auf (`_poll_imap` 66×,
`_decide` 12×, `_resume_pending` 8×, `_handle` 6×). Das erschwert jedes
Refactoring aus Abschnitt 3.

- Für die betroffenen Abläufe öffentliche Einstiege schaffen bzw. nutzen
  (`MailboxRunService.poll`, `ReviewService.decide`, `Application.run_once`).
- Private Aufrufe nur noch dort, wo eine Fehlerinjektion anders nicht möglich
  ist, mit Kommentar.
- Tests mit mehr als 60 Zeilen (22 Stück) in Arrange-Hilfen und mehrere
  benannte Tests aufteilen; ein Test prüft ein Verhalten. Beispiele:
  `test_core.test_models_and_config` (118 Z.),
  `test_v13_orchestrator.test_web_presentation_reschedule_diff_and_duplicate_match` (110 Z.).
- Lesbarkeit: 270 Zeilen mit mehreren Anweisungen per `;` auflösen; vier Tests
  ohne erkennbare Prüfung bekommen eine ausdrückliche Prüfung
  (`test_storage_windows_directory_sync`, `test_every_size_and_complexity_limit`,
  `test_revision_service_public_api_handles_absent_dialog_and_resume`,
  `test_delivery_does_not_send_if_pending_transition_was_lost`).

### T4 – Wirksamkeit der Tests messen (Mutationstests)

100 % Abdeckung sagt nur, dass Code lief, nicht dass ein Fehler auffiele.

- `mutmut` für die sicherheitskritischen Module: Bestätigungsschranke
  (`telegram/writes.py`, `external/confirmed.py`, `review/service.py`),
  Idempotenz (`review/inbox.py`, `drafts.py`, `webpush.py`), Web-Sitzung und
  CSRF (`web/auth.py`), Aufbewahrung (`retention.py`).
- Ziel: ≥ 90 % getötete Mutanten in diesen Modulen; überlebende Mutanten werden
  mit Tests geschlossen oder begründet dokumentiert.
- Läuft wöchentlich bzw. manuell in der CI (zu langsam für jeden Push).

### T5 – Upgrade- und Zustandsverträge

- Ordner `tests/upgrade/states/` mit echten, synthetischen JSON-Zuständen je
  Release (1.1, 1.2, 1.3, 1.4, 1.6, 2.0): Mail, Vorschlag mit Versionen,
  Outbox, Checkpoints, Entwurf, Push-Abos.
- Ein Test lädt jeden Satz mit der aktuellen Version, setzt die Verarbeitung
  fort und prüft: keine Datenverluste, kein erneuter externer Schreibzugriff,
  gleiche Fingerprints. Damit wird der Fehlertyp aus 2.0
  (2.0-Felder in Legacy-Fingerprints) systematisch abgedeckt.
- JSON-Schema-Snapshots der gespeicherten Modelle; eine Schemaänderung
  ohne neuen Snapshot und Upgrade-Test lässt den Test scheitern.

### T6 – Eigenschaftsbasierte Tests für Parser

Mit `hypothesis` für Code, der nicht vertrauenswürdige Eingaben verarbeitet:

- `mime.prepare` und `attachments`: beliebige Header, Kodierungen,
  verschachtelte Multiparts – nie Ausnahme außer den erwarteten, Grenzen
  eingehalten.
- `telegram/temporal.py` und `action_normalization._parse_date`: Datums- und
  Zeitangaben, Sommerzeitwechsel, Rundreise Parsen ↔ Formatieren.
- `calendar_parser`/`external/ical.py`: Faltung, Escaping, Rundreise.
- `drafts.message`: Header-Injektion (`\r`, `\n`, `\x00`) in allen Feldern
  wird immer abgewiesen.
- `webpush.subscription`: nur erlaubte Anbieter, nie eine akzeptierte
  beliebige URL.

### T7 – Browsertests stabiler und schneller

- Die Coverage eines Dokuments geht verloren, sobald die Seite selbst
  navigiert; Tests müssen heute vorher `page.collect()` aufrufen. Ein
  Fixture-Hook, der vor jeder Navigation sammelt (über
  `Page.frameRequestedNavigation`/`Page.frameStartedLoading` der DevTools),
  macht das automatisch.
- Die 5-Sekunden-Rückgängig-Frist verlängert jeden Bestätigungstest. Die Frist
  wird über ein `data-undo-ms`-Attribut gesetzt, das nur der Testserver
  verkürzt; ein eigener Test prüft die echten 5 Sekunden.
- Gemeinsame Seitenobjekte (`Overview`, `DetailPane`, `SettingsPage`) statt
  wiederholter Selektoren.
- Barrierefreiheit zusätzlich mit `axe-core` prüfen (ergänzt das eigene Audit
  in `checks.py`).

### T8 – CI erweitern

- Neue Schritte: `ruff`, `mypy`, Prüfung, dass `requirements.lock` die
  Abhängigkeitshülle aus `pyproject.toml` vollständig enthält (der fehlende
  `pywebpush`-Eintrag in 2.0 wäre so früh aufgefallen).
- Testlaufzeiten berichten (`--durations=20`), damit langsame Tests auffallen.
- Wöchentlicher Lauf: Mutationstests (T4) und `pip-audit` gegen
  `requirements.lock`.

---

## 5. Offene fachliche Punkte aus 2.0

Diese Punkte sind keine Aufräumarbeiten. Sie werden vor oder während 2.1 als
eigene, kleine Änderungen mit Regressionstest entschieden:

1. **Tagesüberblick nach spätem Start:** Startet Mailhelp nach der eingestellten
   Uhrzeit (z. B. um 23 Uhr), wird der Überblick noch am selben Tag gesendet.
   Gewünscht ist vermutlich ein Zeitfenster (z. B. höchstens 3 Stunden nach
   `time`).
2. **Web-Reload durch Recovery:** Unveränderte Vorschläge werden bei der
   Wiederaufnahme neu geschrieben und lösen einen Reload aus
   ([Architektur-1.6.md](Architektur-1.6.md#hinweis-für-folgearbeiten)). Mit
   dem Split-View fällt das stärker auf, weil die Auswahl zurückgesetzt wird.
3. **Push-Operationsprotokoll:** Je Gerät nur die letzten Schlüssel speichern
   statt global 500.

---

## 6. Phasen und Reihenfolge

| Phase | Inhalt | Abnahme |
| :--- | :--- | :--- |
| 1 | A1 (melden), T8, T1 (nur verschieben) | gleiche Testanzahl, 100 % Coverage; CI zeigt Lint-/Typbefunde |
| 2 | A2, T2, T5 | keine `hasattr`-Weichen auf dem Store; Upgrade-Sätze aller Releases bestehen |
| 3 | A3, T3, T6 | typisierte Mail; keine Tests über `_poll_imap`; Hypothesis-Tests grün |
| 4 | A4, A5, A6 | keine Funktion > 80 Zeilen, keine Klasse > 20 Methoden, kein `replace("</main>")` |
| 5 | A7, A8, T4, T7 | Mutationsquote ≥ 90 % in den kritischen Modulen; UI-Suite ohne manuelle `collect()` |
| 6 | A1 (erzwingen), Doku, Release 2.1.0 | ruff und mypy fehlerfrei in der CI; Architekturdokument 2.1 |

Jede Phase endet mit einem eigenen Commit samt Versionserhöhung und
`CHANGELOG.md`-Eintrag gemäß [AGENTS.md](../AGENTS.md).

---

## 7. Nicht im Umfang

- Neue Funktionen oder Änderungen an der Oberfläche.
- Wechsel von Web-Framework, Speicherformat (JSON bleibt) oder
  Python-Version.
- Entfernen der Kompatibilitätsfassaden; sie werden nur als veraltet markiert.
