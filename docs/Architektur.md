# Architektur

Geprüft für Mailhelp 7.0 (Stand 16. November 2026)  
Dieses Dokument beschreibt den Aufbau des Pakets `mailhelp`, den Weg einer Mail, den
Bestätigungsweg für externe Schreibzugriffe und die gespeicherten Zustände. Es ersetzt die
früheren Dokumente `Architektur-1.6`, `-2.1`, `-2.4` und `Paketstruktur` (jetzt im
[Archiv](archiv/)). Wie die Regeln im Einzelnen getestet werden, steht in
[Zustandsregeln 3.6](Zustandsregeln-3.6.md); wie Weboberfläche und Abruf sich die Ressourcen
teilen, in [Entkopplung von Bedienung und Abruf](Entkopplung-Web-und-Abruf.md).

## 1. Pakete und Schichten

Ein Modul darf aus seiner eigenen Schicht und aus tieferen Schichten importieren, auch
innerhalb von Funktionen. `tests/unit/test_layers.py` erzwingt das; jede Ausnahme steht dort
mit Begründung, und eine nicht mehr benötigte Ausnahme lässt den Test ebenfalls scheitern.

| Schicht | Pakete und Module | Aufgabe |
| ---: | :--- | :--- |
| 0 | `domain`, `text`, `state_names`, `paths`, `formatting`, `log_reduction` | Fachmodelle (Mail, Vorschlag, Befund, Serie), deutsche Datums- und Zeitangaben, Namen der Zustandsdateien |
| 1 | `logging`, `persistence`, `support` | JSONL-Protokolle, JSON-Ablage mit Sperren und Migrationen, Kennzahlen |
| 2 | `config` | Einstellungsmodelle (`base`, `mail_settings`, `target_settings`, `runtime_settings`, `topics`, `prompts`), Laden, bestätigte Konfigurationsänderungen |
| 3 | `external`, `llm` | Kalender- und Aufgabenanbieter, OAuth, bestätigtes Schreiben; OpenRouter, Ollama, Laya |
| 4 | `mailbox`, `proposals` | IMAP und IServ, Postfachlauf; Vorschläge bauen, normalisieren, abgleichen, Zielprofile |
| 5 | `processing`, `review`, `rule_learning`, `notifications`, `activity` | Verarbeitung einer Mail, Prüfbefehle, Regellernen, Benachrichtigungen und Push, Aktivitätsberichte |
| 6 | `runtime` | Betrieb: Einrichtung, Diagnose, Aufbewahrung, Lernläufe, Erlebnisdienste |
| 7 | `telegram`, `web`, `helpdocs` | Bedienoberflächen und Hilfe |
| 8 | `app` | Zusammenbau (`composition`), laufende Anwendung, Zugangsprüfungen, Nachladen der Konfiguration |
| 9 | `cli` | Einstieg `mailhelp` |

Ausnahmen innerhalb eines Pakets: Bewertung, Entscheidungstest, Lernen und die
Entscheidungs-Clients in `llm` gehören zur Schicht 5, weil sie die Analyse ausführen;
`persistence/schemas.py` (Katalog aller Schemata für die Prüfwerkzeuge) zur Schicht 8.

Weitere dauerhafte Grenzen:

- **Größe.** Keine Funktion über 80 Zeilen, höchstens 10 Parameter; benannte Ausnahmen mit
  Begründung (`tests/unit/test_limits.py`).
- **Typen.** Jede Funktion ist vollständig annotiert (`mypy` mit `disallow_untyped_defs`,
  `disallow_incomplete_defs`, `disallow_untyped_calls`); der bisherige strenge Kern verbietet
  zusätzlich `Any` als Rückgabe und unparametrisierte Generika.
- **Einstieg.** `mailhelp.cli` bleibt im Wurzelpaket (Konsolenbefehl, Neustart per
  `-c "from mailhelp.cli import main"`, Docker).

## 2. Der Weg einer Mail

1. **Abruf** (`mailbox`). `MailboxRunService` legt je Postfach eine feste UID-Warteschlange an
   und gibt jede Mail an die Verarbeitung. Der Lauf merkt sich seinen Stand in `mail-run-<konto>`;
   nach einem Neustart setzt er dieselbe Warteschlange fort, ohne neu zu suchen.
2. **Verarbeitung** (`processing.orchestrator`, `processing.mail_pipeline`). Jeder Schritt
   schreibt sein Ergebnis in den Mailzustand `mail-<id>`, bevor der nächste beginnt:
   Vorbereitung (MIME, Anhänge, Grenzen), Dublettenprüfung, Bilderkennung (falls eingeschaltet),
   Relevanz, Zusammenfassung, Aktionserkennung (Router, Aufgaben, Termine), Normalisierung,
   Vorschlagsbau, Benachrichtigung, automatischer Antwortentwurf (je Postfach). Ein
   abgeschlossener Schritt wird nach einem Neustart nicht wiederholt.
3. **Rückfrage.** Ist die Relevanz unklar, wartet der Lauf auf die Antwort über Telegram oder
   die Weboberfläche, bevor er die nächste Mail verarbeitet.
4. **Vorschläge** (`proposals`). Termine und Aufgaben werden normalisiert (Zeitzonen, Dauer,
   Fristen), mit offenen Vorschlägen und vorhandenen Einträgen abgeglichen und als Version eines
   Vorschlags gespeichert. Jede Änderung erzeugt eine neue Version.

Mailinhalte und Antworten der Sprachmodelle gelten an jeder Stelle als nicht vertrauenswürdig:
Ausgaben werden gegen geschlossene Schemata geprüft, und kein Modell kann einen Schreibzugriff
auslösen.

## 3. Bestätigungsweg für Schreibzugriffe

Nichts wird in Google Kalender, Microsoft, CalDAV oder Todoist geschrieben, ohne dass eine
bestimmte Version eines Vorschlags ausdrücklich bestätigt wurde.

1. **Befehl.** Telegram und Weboberfläche erzeugen einen Prüfbefehl (`review.commands`) mit
   Postfach, Vorschlag, Version und Idempotenzschlüssel. Die Weboberfläche verlangt dazu eine
   gültige Sitzung, ein CSRF-Token und prüft beides bei der Ausführung erneut.
2. **Prüfdienst** (`review.service`). Er nimmt nur einen Befehl für die aktuelle Version an,
   speichert die Bestätigung (`CONFIRMED`) und quittiert den Befehl idempotent; ein
   wiederholter Schlüssel liefert das gespeicherte Ergebnis.
3. **Schreiben** (`external.confirmed.execute_confirmed`). Vor dem Schreiben wird `WRITING`
   gespeichert und das Ziel geprüft (Profil, Kalender oder Projekt, Anbieter). Jeder Eintrag
   trägt den Schlüssel `mailhelp:<mail>:<vorschlag>:v<version>`.
4. **Unklare Ergebnisse.** Bricht die Verbindung nach dem Senden ab, wird der Vorschlag
   `UNCERTAIN`. Vor jedem neuen Versuch sucht Mailhelp den Eintrag über seinen Schlüssel beim
   Anbieter; es schreibt nur, wenn er sicher fehlt.
5. **Nachweis.** Kann der Anbieter Einträge lesen, folgt auf das Schreiben `VERIFYING` mit
   einer dauerhaften Quittung (`write-verification-…`) und erst nach einem frischen Lesen
   `CREATED`.

Im Testmodus wird nie ein Anbieter kontaktiert; der Vorschlag wird `SIMULATED`.

## 4. Gespeicherte Zustände

Alle Zustände sind lesbare JSON-Dateien im Datenverzeichnis (`data_directory`), getrennt nach
`production/` und `test/` (Testmodus). Geschrieben wird über `persistence.storage.JsonStore`:
eine Sperre gegen einen zweiten laufenden Prozess, eine Sperre für Lese-Schreib-Abfolgen im
Prozess, atomares Ersetzen und Quarantäne (`.invalid`) für Dateien, die nicht dem Schema
entsprechen. Protokolle sind getrennte JSONL-Dateien. Die Namen bildet `state_names.py`:

| Name | Inhalt |
| :--- | :--- |
| `mail-<id>` | Mailzustand mit Schrittstatus und Ergebnissen jedes Verarbeitungsschritts |
| `mail-run-<konto>` | Warteschlange und Stand des laufenden Postfachabrufs |
| `proposal-<mail>-<vorschlag>[-v<version>]` | Vorschlag und seine Versionen |
| `clarification-<mail>-<vorschlag>-<version>` | offene Rückfrage mit Antwort und Auslegung |
| `draft-<id>` | Antwortentwurf |
| `write-verification-<operation>` | Quittung und Nachweis eines Schreibzugriffs |
| `action-ledger` | einmalige Buchung jeder geschriebenen Vorschlagsversion |
| `mailbox-folders` | erkannte Ordner je Postfach |

Weitere Dateien (Sitzungen, Befehlseingang, Einrichtung, Lernstand, Push-Abonnements) tragen
feste Namen in ihren Modulen. Gespeicherte Zustände enthalten keine Modulpfade; ein Umzug von
Code ändert kein Dateiformat.

## 5. Altformate

Ältere Dateien werden beim Lesen schrittweise auf das aktuelle Schema gehoben
(`persistence/migrations.py`) und erst beim nächsten regulären Schreiben zurückgeschrieben; ein
nur lesender Zugriff verändert nichts.

- **Mailzustand:** Schema 6 bis 8 werden auf 9 gehoben (getrennte Benachrichtigungsschritte,
  einzelne Extraktionsschritte, Normalisierung und Vorschlagsbau je Vorschlag).
- **Rückfragen:** Schema 1 bis 3 werden auf 4 gehoben (normalisierte und autorisierte Antwort,
  Versuche und Zeitpunkte).
- **Zielprofile:** Vorschläge, Mailzustände, Merge-Journale und Rückfragen ohne Profil erhalten
  Profil 1.
- **Herkunft:** Bestätigungen aus Versionen ohne nachweisbaren Absender tragen
  `web:unverified-legacy`; Schreibnachweise ohne Quittung `legacy_unverified`.

`tests/upgrade` prüft das Lesen aller früheren Formate gegen gespeicherte Schemaabbilder.
