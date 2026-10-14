# Mailhelp 3.1 – Mehrere Postfächer

**Zielversion:** 3.1.0

**Stand:** 14. Oktober 2026

**Status:** Umgesetzt in 3.1.0 (Release-Tag nach CI-Matrix) – Phase 1 (Verträge) in 3.0.1, Phase 2 (Laufzeitkern) in 3.0.2, Phase 3 (Duplikate) in 3.0.3, Phase 4 (zugeordnete Funktionen) in 3.0.4, Phase 5 (Web und Telegram, Teilumfang) in 3.0.5 umgesetzt; Entscheidungen vom 14. Oktober 2026 eingearbeitet
**Grundlage:** [Planung 3.0](Planung-3.0.md), [Planung 3.2](Planung-3.2.md), [Release 3.0](Release-3.0.md), [Projektspezifikation](../Mailhelp-Projektspezifikation.md), [Entwicklungsregeln](../AGENTS.md)

## 1. Ziel und Umfang

Eine Mailhelp-Instanz verarbeitet die Mails **mehrerer IMAP-Postfächer desselben Nutzers**
(z. B. privat und beruflich) in einem gemeinsamen Betrieb: eine Weboberfläche, ein
Telegram-Chat, dieselben Themen, Prompts, Ziele und Benachrichtigungsregeln.

**Nicht Teil dieses Plans:** Mehrbenutzerbetrieb, getrennte Themen/Prompts/Ziele je Postfach,
OAuth-Anmeldung an IMAP (Gmail/Microsoft XOAUTH2), SMTP-Versand, Verschieben oder Markieren von
Mails. **Alles, was je Postfach unterschiedlich konfiguriert wird** – eigene Kalender-/Aufgabenziele,
Ignorierlisten, Themen, Benachrichtigungen, Angaben für Antwortentwürfe – folgt in
[Planung 3.2](Planung-3.2.md). 3.1 legt dafür nur die stabile Postfachnummer als Grundlage.

## 2. Ausgangslage im Code

Vieles ist bereits kontobezogen und muss nicht neu erfunden werden:

| Bereich | Heutiger Stand |
| :--- | :--- |
| Technische Mailidentität | `(account_id, folder, uidvalidity, uid)`; `account_id` = SHA-256 aus Host, Port, Benutzername ([imap.py](../src/mailhelp/imap.py)) |
| Checkpoints | Dateiname aus `account_id` und Ordner ([mailbox_run.py](../src/mailhelp/mailbox_run.py)) |
| Verarbeitungslauf | `mail-run-<account_id>` ([state_names.py](../src/mailhelp/state_names.py)) |
| Mail-ID / Duplikatindex | enthalten `account_id` |

Einzelpostfach-Annahmen, die aufgelöst werden müssen:

| Stelle | Annahme |
| :--- | :--- |
| `config.py` `ImapSettings`, `Secrets.imap_username/password` | genau ein `imap`-Block, genau ein Zugangsdatenpaar |
| `composition.py` | baut genau einen `ImapReader` bzw. `_FailedAccessAdapter` |
| `Application` / `MailboxRunService` | ein `self.imap`; `resume_pending` überspringt Zustände fremder Konten |
| `Application._finish` | Laufzusammenfassung nur für ein Konto |
| `experience.py` | Entwürfe und Tätigkeitsberichte öffnen das eine Postfach; Absender = `IMAP_USERNAME` |
| `learning.py`, `decision_test.py`, `cli.py --check-access` | lesen genau ein Postfach |
| `setup_runtime.py`, `setup.py`, `diagnostics.py`, `/einrichtung`, `/diagnose` | ein IMAP-Schritt, eine IMAP-Prüfung |
| `mail_duplicates.py` | Duplikate nur innerhalb desselben Kontos |
| `telegram/outbox.py`, `review/views.py` | Sortierschlüssel `mail.imap.uid` – über Konten hinweg nicht eindeutig |
| **`fingerprints.py`** | **Der gesamte `imap`-Abschnitt (außer `drafts_folder`) ist Teil des Analyse-Fingerprints.** Jede Umstellung auf ein neues Schema würde alle laufenden Mails mit `configuration_changed` blockieren. |

## 3. Verbindliche Grundsätze

- Bestehende Installationen laufen **ohne Konfigurationsänderung** weiter; vorhandene Zustände,
  Checkpoints, offene Vorschläge und Fingerprints bleiben gültig.
- Die technische Identität bleibt `account_id` aus Host, Port und Benutzername. Dadurch behält
  das bisherige Postfach nach der Umstellung alle Checkpoints und Mailzustände.
- Ein ausgefallenes Postfach blockiert weder andere Postfächer noch Telegram, Web oder Schreibdienste.
- Postfachkonfiguration ist **operativ**: Hinzufügen, Entfernen oder Ändern eines Postfachs
  verändert keinen Analyse-Fingerprint.
- Zugangsdaten bleiben in `.env`/Prozessumgebung; Weboberfläche zeigt nur „vorhanden/fehlt“.
- Mailinhalte bleiben nicht vertrauenswürdig; Postfachbezeichnungen stammen ausschließlich
  aus `config.yaml`, nie aus Mailinhalten.
- Externe Schreibzugriffe erfordern unverändert eine versionsbezogene Bestätigung.

## 4. Konfiguration

### 4.1 Neues Schema

```yaml
imap:
  # Gemeinsame Abrufparameter für alle Postfächer
  batch_size: 25
  global_newest_first: true
  mailboxes:
    - id: 1                       # Ganzzahl 1–99, eindeutig, stabil; bestimmt IMAP_1_…
      label: Privat               # Anzeige in Web/Telegram, max. 40 Zeichen
      enabled: true
      host: imap.web.de
      port: 993
      connection_mode: ssl
      historical_start: '2026-09-15T00:00:00+02:00'
      primary_folder: INBOX
      folders: [INBOX, Sent, Spam]
      drafts_folder: Entwürfe
    - id: 2
      label: Arbeit
      host: imap.example.org
      port: 993
      connection_mode: ssl
      historical_start: null
      folders: [INBOX]
      drafts_folder: Drafts
```

- 1–10 Postfächer, `id` eindeutig. Die Einrichtung vergibt beim Anlegen die höchste
  vorhandene Nummer + 1 und verschiebt Nummern danach nie: Wird Postfach 1 entfernt, behält
  Postfach 2 seine Nummer und seine Geheimnisse. Vor einer Wiederverwendung einer frei
  gewordenen Nummer warnt die Einrichtung, falls dafür noch `IMAP_<n>_…`-Variablen gesetzt sind.
  Reihenfolge der Liste = Anzeige- und Abrufreihenfolge, unabhängig von der Nummer.
- Kombination Host/Port/Benutzername eindeutig (sonst
  identische `account_id` → Startfehler mit Schlüsselpfad).
- `enabled: false` hält ein Postfach konfiguriert, ohne es abzurufen (z. B. bei Kennwortwechsel).
- Grenzen wie bisher (Ports, Ordner, `historical_start`, `drafts_folder`).

### 4.2 Rückwärtskompatibilität

- Ein bisheriger `imap`-Block **ohne** `mailboxes` wird beim Laden als genau ein Postfach mit
  `id: 1` und `label: Postfach` interpretiert. Datei wird nicht automatisch umgeschrieben.
- `mailboxes` zusammen mit Host/Port/Ordnern auf oberster `imap`-Ebene ist ein Validierungsfehler.
- Die Weboberfläche schreibt erst bei der ersten bewussten Übernahme im Assistenten das neue Schema.

### 4.3 Geheimnisse

| Postfach | Variablen |
| :--- | :--- |
| `id: <n>` | `IMAP_<n>_USERNAME`, `IMAP_<n>_PASSWORD`, z. B. `IMAP_1_USERNAME`, `IMAP_2_PASSWORD` |
| `id: 1` | zusätzlich Rückfall auf `IMAP_USERNAME` / `IMAP_PASSWORD`, damit Bestandsinstallationen ohne `.env`-Änderung starten |

Sind für Postfach 1 sowohl nummerierte als auch alte Variablen gesetzt, gelten die nummerierten;
ein Hinweis (ohne Werte) erscheint in `--check` und `/diagnose`.

- `.env.example`, `config.py`-Geheimnisliste und Fehlermeldungen nennen die konkreten Namen.
- Fehlende Zugangsdaten eines **aktivierten** Postfachs: Start mit Fehler wie heute; bei
  `web.enabled` bleibt die Einrichtung erreichbar (bestehendes 3.0-Verhalten je Postfach).
- `--check-access --show-imap-credentials` gibt je Postfach Benutzername/Passwort aus;
  optional `--mailbox <n>` zur Einschränkung.

### 4.4 Fingerprint

- `imap` (bzw. `imap.mailboxes`, `batch_size`, `global_newest_first`) wird zu `OPERATIONAL`
  in [fingerprints.py](../src/mailhelp/fingerprints.py) verschoben.
- Für unveränderte Bestandskonfigurationen wird der bisherige Fingerprint (mit `imap`) als
  äquivalent registriert – derselbe Mechanismus wie beim 1.x→1.2-Übergang. Pflichttest:
  synthetischer 2.3-Zustand mit offener Entscheidung läuft nach dem Upgrade weiter.

## 5. Abruf und Verarbeitung

### 5.1 Laufzeitmodell

- Umgesetzt (3.0.2) als **`MailboxSource`** (Postfacheinstellungen + Reader bzw. Fehleradapter) je
  aktiviertem Postfach; `Application.sources` hält alle, `Application.imap` bleibt der Reader des ersten.
  Jeder Reader verbindet sich beim Start; ein Verbindungsfehler betrifft nur sein Postfach.
- `MailboxRunService` arbeitet pro Postfach mit dessen Reader; Checkpoints und `mail-run-<account_id>`
  bleiben unverändert getrennt.
- Analyse bleibt **sequentiell im Hauptthread** (ein LLM-Budget, eine Store-Sperre). Keine parallelen
  IMAP-Abrufe im ersten Umfang.

### 5.2 Reihenfolge und Kontingente

- Die **Auswahl** eines Laufs erfolgt über alle Ordner aller Postfächer nach IMAP-Empfangszeitpunkt
  (neueste zuerst). Gleichstand behält die Ermittlungsreihenfolge: Postfach-, dann Ordnerreihenfolge
  (für ein Postfach unverändert gegenüber 3.0).
- `batch_size` und `--max-mails N` sind **gemeinsame** Kontingente über alle Postfächer.
- Die ausgewählten Mails werden als ein Run-Zustand **je Postfach** gespeichert, bevor ein Inhalt
  geladen wird, und **je Postfach in Konfigurationsreihenfolge** bearbeitet.
- Solange irgendein Postfach noch einen unfertigen Run hat, werden nur diese Runs fortgesetzt; erst
  danach werden alle Postfächer neu durchsucht. Das hält Wiederaufnahmen deterministisch.

### 5.3 Wiederaufnahme und Fehler

- `resume_pending` holt Mails über den Reader des Postfachs mit passender `account_id`.
- Zustand eines **nicht mehr konfigurierten oder deaktivierten** Postfachs: bleibt unverändert liegen
  (kein `failed`, kein Checkpoint); das Ereignis `mailbox_unavailable` wird einmal pro Prozess und Konto
  protokolliert. Bereits erzeugte Vorschläge bleiben bestätigbar, da Schreibdienste kein IMAP benötigen.
- Verbindungs-/Anmeldefehler eines Postfachs: Ordnerfehler werden mit Postfachnummer protokolliert,
  die übrigen Postfächer laufen weiter. Offen für Phase 5: Betriebsproblem-Meldung über die
  3.0-Kategorie `system_errors` mit Postfach-Label.
- UIDVALIDITY-Wechsel und `--ignore-historical-start` wirken je Postfach (Option auf `--mailbox <n>` einschränkbar).

### 5.4 Duplikate über Postfächer hinweg

Typischer Fall: Eine Mail geht an beide Adressen oder wird weitergeleitet.

- Der Duplikatindex prüft **kontoübergreifend**. Gleiche Message-ID **und** gleicher
  Inhaltsfingerprint mit abgeschlossenem Vorgänger → `duplicate`, kein LLM-Aufruf, Verweis auf
  die zuerst verarbeitete Mail (Postfach-Label sichtbar).
- Weitergeleitete Mails mit neuer Message-ID bleiben neue Mails; unsichere Fälle wie bisher `ambiguous`.
- Bestehende Einträge bleiben gültig (Schema unverändert, nur Kandidatenauswahl erweitert).

### 5.5 Laufzusammenfassung

Telegram-Zusammenfassung am Laufende aggregiert über alle Postfächer, mit Zeile je Postfach
nur bei mehr als einem Postfach. Postfachfehler erscheinen als eigene Zeile.

## 6. Zugeordnete Funktionen

| Funktion | Verhalten |
| :--- | :--- |
| Antwortentwürfe | APPEND in den `drafts_folder` **des Postfachs, aus dem die Mail stammt**; Absender = Benutzername dieses Postfachs (optional späteres Feld `address`). Kein Rückfall auf ein anderes Postfach. |
| Originaldokumente / Volltextsuche | Unverändert lokal; Suche erhält Filter „Postfach“. |
| Tätigkeitsberichte | Postfachwahl im Formular (Links ohne JavaScript, `?postfach=<n>`); der Bericht speichert `mailbox` (Berichte vor 3.1: Postfach 1); Ordnervorschläge und -prüfung je Postfach; Zählen und Lesen öffnen nur dieses Postfach. |
| Lernmodus `--learn N` | Liest genau ein Postfach; bei mehreren aktivierten Postfächern ist `--mailbox <n>` Pflicht (umgesetzt in 3.0.4 statt „alle Postfächer“, damit `N` eindeutig bleibt). Ergänzt neue Ordner im Eintrag dieses Postfachs. Absenderfilter und Themen bleiben gemeinsam. |
| Decision-Test | Wie der Lernmodus genau ein Postfach; `--mailbox <n>` bei mehreren aktivierten Postfächern Pflicht. |
| Tagesüberblick | Offene Entscheidungen mit Postfach-Label; sonst unverändert. |
| Benachrichtigungen | Neutrale Push-Texte ohne Postfachnamen; Telegram `summary` darf das Label nennen. |

## 7. Weboberfläche und Telegram

- **Anzeige (3.0.5):** Maildetail, Archivliste und Telegram-Vorschläge (`✉️ [Label] Absender · Betreff`)
  zeigen das Postfach-Label, sobald mehr als ein Postfach aktiviert ist. Unbekannte `account_id` →
  „Entferntes Postfach“. Das Label wird zur Laufzeit aus `account_id` aufgelöst, **kein** neues Feld im
  Mailzustand. Offen für 3.2: Label auf den Karten der Entscheidungsübersicht und im Tagesüberblick.
- **Filter (3.0.5):** Archiv und Suche filtern nach Postfach (`postfach=<n>`, ohne JavaScript bedienbar).
- **Sortierung (geprüft in 3.0.3, keine Änderung):** Die Schlüssel in `telegram/outbox.py` und
  `review/views.py` enthalten nach der UID die Mail-ID und bleiben damit auch bei gleicher UID in zwei
  Postfächern eindeutig. Eine Umstellung auf den Empfangszeitpunkt würde die Telegram-Reihenfolge
  bestehender Installationen verändern und ist kein Fehler im Sinne dieser Planung.
- **Einrichtung `/einrichtung`, Schritt 2 (3.0.5):** Bearbeiten aller Felder jedes konfigurierten
  Postfachs einschließlich Anzeigename und Aktivierung über den bestehenden Entwurf (Sitzung, CSRF,
  Dateihash, Entwurfsversion, Idempotenz, Neuprüfung bei Ausführung); Ordnerauswahl je Postfach aus der
  letzten Diagnose; Anzeige der benötigten Variablennamen (`IMAP_2_USERNAME/IMAP_2_PASSWORD`) mit
  „vorhanden/fehlt“. **Verschoben nach 3.2** (Oberfläche „Einstellungen → Postfächer“): Hinzufügen und
  Entfernen ganzer Postfächer im Web; bis dahin in `config.yaml` (`imap.mailboxes`).
- **Diagnose `/diagnose` (3.0.5, abweichend):** Die Komponente `imap` prüft **alle** aktivierten
  Postfächer des Entwurfs nacheinander und scheitert, sobald eines scheitert; ein im Entwurf neues
  Postfach ohne geladene Zugangsdaten ergibt `auth`. Damit setzt die Übernahme von Postfachänderungen
  weiterhin eine aktuelle erfolgreiche Prüfung aller Postfächer voraus. Einzelkomponenten je Postfach
  folgen gegebenenfalls in 3.2. Der Bericht enthält weiterhin keine Hosts, Benutzer oder Ordner.
- **Telegram `/status`:** Status je Postfach – verschoben nach 3.2.

## 8. Umsetzungsphasen

| Phase | Schwerpunkt | Fertig, wenn … |
| :--- | :--- | :--- |
| 1 | Verträge | Konfigurationsschema inkl. Altformat, Geheimnisnamen, Fingerprint-Umstellung mit Äquivalenz, Spezifikation und `config.example.yaml` aktualisiert und getestet |
| 2 | Laufzeitkern | `MailboxRegistry`, `composition.py`, `MailboxRunService` je Postfach, gemeinsames Kontingent, globale Sortierung, Wiederaufnahme und `mailbox_unavailable` |
| 3 | Duplikate und Sortierung | kontoübergreifender Duplikatindex, Sortierschlüssel, Laufzusammenfassung |
| 4 | Zugeordnete Funktionen | Entwürfe, Tätigkeitsberichte, Lernmodus, Decision-Test, `--check-access`, `--mailbox` |
| 5 | Web und Telegram | Labels, Filter, Einrichtungsschritt, Diagnose je Postfach, `/status` |
| 6 | Abnahme | Upgrade-Tests aus 2.3-Zuständen, Plattformmatrix, Playwright, Dokumentation, Release-Notizen |

Phase 1 und 2 sind der Kern. Phase 4/5 lassen sich bei Zeitdruck teilweise auf 3.1 verschieben,
**nicht** aber die Postfachzuordnung von Entwürfen (sonst falscher Entwurfsordner/Absender).

## 9. Teststrategie

- **Verbindlich:** 100 % Zeilen- und Branch-Abdeckung, keine neuen Ausschlüsse, Regressionstest je Bugfix.
- Simulierte IMAP-Server je Postfach (Fakes in `tests/fakes/`) mit synthetischen Mails; gleiche
  Ordner und gleiche UIDs in zwei Postfächern als Standardfall.
- **Konfiguration:** Altformat, neues Format, Mischformat (Fehler), doppelte `id`, doppelte
  `account_id`, fehlende Geheimnisse je Postfach, Rückfallvariablen, `enabled: false`.
- **Fingerprint:** Hinzufügen/Entfernen/Ändern eines Postfachs ändert den Fingerprint nicht;
  unveränderte 2.3-Konfiguration bleibt äquivalent; offene Entscheidung läuft weiter.
- **Abruf:** globale Sortierung über Postfächer, Gleichstandsregeln, gemeinsames `--max-mails`,
  deterministische Wiederaufnahme nach Abbruch, UIDVALIDITY-Wechsel in nur einem Postfach.
- **Fehler:** Anmeldefehler, Timeout, TLS-Fehler und Verbindungsabbruch in einem Postfach,
  während das andere vollständig verarbeitet wird; Neustart in jedem Zwischenzustand.
- **Duplikate:** gleiche Mail in zwei Postfächern, Weiterleitung mit neuer Message-ID,
  gleiche Message-ID mit abweichendem Inhalt (`ambiguous`).
- **Entfernte Postfächer:** offene Vorschläge bleiben bestätigbar, keine Wiederholungsschleife.
- **Entwürfe:** Entwurf landet im richtigen Postfach; Fehler im Zielpostfach führt nicht zu
  Ausweichen auf ein anderes.
- **Autorisierung:** Einrichtungsänderungen an Postfächern ohne Sitzung, mit falschem CSRF,
  veralteter Entwurfsversion, wiederholtem Idempotenzschlüssel und widerrufener Sitzung bei Ausführung.
- **Datenschutz:** Logs, Diagnosebericht und Push-Payloads enthalten keine Hosts, Benutzernamen
  oder Passwörter; `account_id` und `id` sind zulässig.
- **Playwright:** Postfachliste im Assistenten, Filter im Archiv, Labels auf Smartphone und Desktop,
  Bedienung ohne JavaScript.

## 10. Upgrade, Rollback und offene Punkte

**Upgrade:** Ohne Konfigurationsänderung identisches Verhalten. Erst das Hinzufügen eines zweiten
Postfachs aktiviert Labels, Filter und Mehrpostfach-Zusammenfassung. Der erste Abruf eines neuen
Postfachs beginnt bei dessen `historical_start` (ohne Grenze bei UID 1 – die Oberfläche warnt davor).

**Rollback auf 2.3:** Nur möglich, solange `config.yaml` noch im Altformat vorliegt. Zustände eines
zusätzlichen Postfachs werden von 2.3 ignoriert (andere `account_id`), aber nicht beschädigt.
Release-3.0.md beschreibt das.

**Geänderte Zugangsdaten:** Ändert sich Host, Port oder Benutzername eines Postfachs, entsteht eine neue
`account_id` und das Postfach wird neu eingelesen (begrenzt durch `historical_start`). Die
Einrichtung warnt vor dieser Folge, bevor die Änderung übernommen wird.

**Entscheidungen (14. Oktober 2026):**

1. Release-Zuschnitt: 3.0.0 erscheint ohne Mehrpostfach; diese Planung wird als 3.1 umgesetzt.
2. Geheimnisse: nummeriert nach dem Muster `IMAP_<n>_USERNAME` / `IMAP_<n>_PASSWORD`.
3. Kontoübergreifende Duplikaterkennung: Empfehlung „immer aktiv, kein Schalter“ – vor Phase 3 bestätigen.
4. Postfachbezogene Ziele, Ignorierlisten und weitere Einstellungen je Postfach: [Planung 3.2](Planung-3.2.md).
