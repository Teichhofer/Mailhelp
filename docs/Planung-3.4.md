# Mailhelp 3.4 – Quellen, Zugangsdaten und Einstellungen vollständig im Web

**Zielversion:** 3.4.0

**Stand:** 15. Oktober 2026

**Status:** Umgesetzt in 3.4.0 (Phasen 1–3 in 3.3.10–3.3.12)
**Grundlage:** [Entwicklungsregeln](../AGENTS.md), [Projektspezifikation](../Mailhelp-Projektspezifikation.md),
[Planung 3.2](Planung-3.2.md), [Planung 4.0](Planung-4.0.md) (Pfeiler 4 wird vorgezogen)

---

## 1. Ziel

Postfächer und IServ-Konten lassen sich vollständig über die Weboberfläche anlegen, ändern,
deaktivieren und entfernen, einschließlich ihrer Zugangsdaten. Alle für den Betrieb relevanten
Einstellungen der `config.yaml` sind im Web bearbeitbar. Ein Texteditor ist für den laufenden
Betrieb nicht mehr nötig.

Nicht Teil von 3.4 (bleibt Planung 4.0): Erststart ohne gültige Konfiguration, OAuth-Anmeldung im
Browser (Google, Microsoft), Web-Lernmodus und Neustart ohne Prozesswechsel.

## 2. Ausgangslage (3.3.9)

| Bereich | Heute im Web | Lücke |
| :--- | :--- | :--- |
| Postfächer | Anlegen (id, Name, Server, Port, Ordner), Richtlinien je Postfach, Entfernen; Entwurf → Diagnose → Übernahme | `historical_start`, Verbindungsart und Aktivierung nur über die Einrichtung; Zugangsdaten nur in `.env` |
| IServ-Konten | Anzeige, ob Zugangsdaten vorhanden sind; Diagnose | Anlegen, Ändern, Entfernen fehlen |
| Zugangsdaten | Liste „vorhanden/fehlt“ in der Einrichtung | Eintragen und Ersetzen fehlen |
| Einstellungen | Positivliste in Einrichtung und `/einstellungen` | u. a. `imap.historical_start`, `imap.batch_size`, `imap.global_newest_first`, `telegram.user_id/chat_id/sequential_questions`, `smart_reply`, `vision.*`, `daily_briefing.include_*`, `activity_report.*`, `learning.parallel_llm_calls`, `retention.activity_report_days`, `web.session_days`, `web.lan_access`, Protokollstufen |

## 3. Umsetzung

### Phase 1 – IServ-Konten in der Weboberfläche (3.3.10)

- Bereich „IServ-Konten“ unter **Einstellungen → Postfächer**: Liste, Formular zum Hinzufügen
  (`id`, Name, Server, Postfach für Zielprofil und Standards, optional `historical_start`),
  je Konto Ändern, Aktivieren/Deaktivieren und Entfernen.
- Jede Änderung ist ein Entwurf (`iserv.accounts` als ganzer Block, wie `imap.mailboxes`), wird in
  der Entwurfsprüfung angezeigt und erst nach ausdrücklicher Übernahme kommentarerhaltend in
  `config.yaml` geschrieben. Gültigkeit (HTTPS-Ursprung, eindeutige `id`, aktives Postfach) prüft das
  bestehende Konfigurationsmodell vor dem Speichern.
- Wirkung nach dem nächsten Dienststart; die Diagnose `iserv` prüft den Entwurf vorher.

### Phase 2 – Zugangsdaten im Web, nur schreibend (3.3.11)

- Neue Seite **Einstellungen → Zugangsdaten** (`/einstellungen/zugangsdaten`) mit allen
  Geheimnissen, die die Entwurfskonfiguration benötigt: `IMAP_<n>_*` je Postfach, `ISERV_<n>_*` je
  IServ-Konto, OpenRouter, Telegram und die Geheimnisse der Zielanbieter je aktivem Zielprofil.
- Anzeige ausschließlich „hinterlegt“ oder „fehlt“; ein gespeicherter Wert wird nie ausgegeben, auch
  nicht maskiert oder teilweise. Eingabefelder sind `type="password"` mit `autocomplete="off"`.
- Schreiben nur mit gültiger, bei Ausführung erneut geprüfter Sitzung, CSRF-Token,
  Idempotenzschlüssel und ausdrücklicher Bestätigung. Werte ohne Zeilenumbrüche und
  Steuerzeichen, Länge begrenzt.
- `.env` wird zeilengenau und atomar geändert: vorhandene Zeile ersetzen, sonst anhängen;
  Kommentare und andere Zeilen bleiben unverändert. Eine Datei mit Inhaltsabweichung seit dem
  Laden (Hash) wird nicht überschrieben.
- Protokolle und Journal enthalten nur Namen, nie Werte; neue Werte werden sofort in die
  Log-Maskierung aufgenommen.
- `MAILHELP_WEB_SECRET` ist ausgenommen: eine Änderung würde alle Sitzungen ungültig machen und die
  laufende Seite aussperren. Prozess-Umgebungsvariablen haben weiterhin Vorrang vor `.env`; die
  Seite weist darauf hin, wenn ein Name dort gesetzt ist.
- Diagnose und Einrichtung lesen neue Werte sofort; der Abruf nutzt sie nach dem nächsten Start.

### Phase 3 – Einstellungen vervollständigen (3.3.12)

- Postfachformular: zusätzlich Verbindungsart, Aktivierung und `historical_start`.
- `/einstellungen` erhält die fehlenden Betriebseinstellungen aus Abschnitt 2 mit Beschriftung,
  Auswahllisten und Hilfetexten (`docs/Web-Einstellungen.md`).
- Bewusst nicht im Web: `data_directory`, Logpfade, Dateigrößen der Logrotation, `web.host`,
  `web.port`, `web.enabled`, `web.allowed_hosts` (Gefahr, sich selbst auszusperren) und die technischen
  Parser-Sicherheitsgrenzen unter `limits.max_html_*`, `max_mime_parts` u. ä.

### Phase 4 – Abnahme und Release (3.4.0)

- 100 % Zeilen- und Branch-Abdeckung, Browsertests mit Barrierefreiheitsprüfung für die neuen
  Seiten, ruff und mypy ohne Befund; Linux/Docker über die CI (in Docker muss `.env` beschreibbar
  eingebunden sein, sonst meldet die Seite das verständlich).
- Spezifikation, README, `docs/Web-Einstellungen.md`, Datenschutz und Changelog aktualisiert.

## 4. Sicherheitsinvarianten

- Keine Seite und kein Protokoll gibt Zugangsdaten aus.
- Schreibzugriffe auf `config.yaml` und `.env` nur über autorisierte, bestätigte und
  idempotente Webaktionen; Kalender- und Aufgabenanlage bleibt davon unberührt und erfordert
  weiterhin die versionsbezogene Bestätigung je Vorschlag.
- Mailinhalte und LLM-Ausgaben beeinflussen keine Konfiguration.

## 5. Umsetzungsstand

| Phase | Version | Ergebnis |
| :--- | :--- | :--- |
| 1 | 3.3.10 | `/einstellungen/iserv`: IServ-Konten anlegen, ändern, (de)aktivieren und entfernen als Entwurf des Blocks `iserv.accounts`; Übernahme nur nach aktueller Diagnose `iserv`. Nebenbei behoben: Ein übernommener Einrichtungsentwurf blieb auf dem alten Dateistand stehen, und die Postfachseite brach danach ab. |
| 2 | 3.3.11 | `/einstellungen/zugangsdaten`: alle von der Entwurfskonfiguration benötigten Zugangsdaten nur schreibend, mit Sitzungsprüfung vor dem Schreiben, CSRF, Idempotenzschlüssel, Bestätigung und Dateistandsprüfung; `.env` wird zeilengenau und atomar geändert, `MAILHELP_WEB_SECRET` ausgenommen. |
| 3 | 3.3.12 | 29 weitere Einstellungen mit Beschriftung, Hilfetext und Dokumentation in sechs neuen Bereichen (Telegram, Bildauswertung, Tagesüberblick, Tätigkeitsberichte, Lernmodus, Weboberfläche) sowie Abruf, Antworten, Aufbewahrung und Protokollierung; `historical_start` je Postfach in der Einrichtung. `web.allowed_hosts` bleibt abweichend vom Plan ausgenommen (Aussperrgefahr). |
| 4 | 3.4.0 | Gesamtabnahme: 2478 Tests mit 100 % Zeilen- und Branch-Abdeckung, 167 Browsertests einschließlich Barrierefreiheit für IServ-Konten, Zugangsdaten und Einstellungen (Desktop, Telefon, schmal), ruff und mypy ohne Befund; Linux/Docker über die CI. Offen für 4.0: Erststart ohne Konfiguration, OAuth im Browser, Web-Lernmodus und Neustart ohne Prozesswechsel. |
