# Prüfung der Dokumentation 7.0

Geprüft für Mailhelp 7.0
**Grundlage:** [Planung 7.0](Planung-7.0.md), Maßnahmen K1 bis K6
**Prüfstand:** Mailhelp 7.0.14 mit den Korrekturen aus 7.0.15 (16. November 2026)
**Status:** abgeschlossen mit Release 7.0.15. Offen: Satz-für-Satz-Prüfung der fachlichen Regeln
in der Spezifikation (siehe unten), Bewertung echter Modellantworten und Wege mit echten Konten.

Dieser Bericht ist der Nachweis der Dokumentationsprüfung von 7.0 und ersetzt den
[Bericht zu 5.3](archiv/Pruefung-Dokumentation-5.3.md) als laufende Inventur. Der erzeugte Teil
unten listet jede Einstellung so, wie der Code sie kennt; `python -m devtools.inventory` schreibt
ihn neu, und ein Test schlägt fehl, wenn er veraltet ist.

## 1. Umfang (K1)

Lebend und damit geprüft: `README.md`, `Mailhelp-Projektspezifikation.md`, `DATENSCHUTZ.md`,
`NUTZUNGSBEDINGUNGEN.md`, `AGENTS.md`, `config.example.yaml`, `.env.example` und in `docs/` die
Anleitungen ([Inhaltsverzeichnis](README.md)), dazu der Hilfeindex (`helpdocs/*.json`, aus den
Anleitungen erzeugt). Alles in [`docs/archiv/`](archiv/) beschreibt den Stand seiner Version und
wurde nicht geprüft.

## 2. Verfahren (K4)

Jedes Dokument wurde Abschnitt für Abschnitt gegen Code und Oberfläche gelesen, in der
Reihenfolge des Plans: Ersteinrichtung, Betrieb, Fehlerbehebung, Konten, Ziele, Bedienung,
Einstellungen, README, Datenschutz, Spezifikation, danach die übrigen. Hilfsmittel:

- Jede **fett** oder in „Anführungszeichen“ genannte Beschriftung der Anleitungen wurde im
  Oberflächencode gesucht. Zusammengesetzte Texte (`{title} öffnen`) wurden an ihrer Quelle
  nachgesehen.
- Zahlen (Grenzen, Standards, Fristen, Schwellen) wurden an ihrer Definition im Code geprüft;
  die Fundstelle steht in der Tabelle.
- Fremde Oberflächen (Google-Konsole, Azure, Browser) und Wege mit echten Konten sind
  „nicht prüfbar“: Tests verwenden ausschließlich simulierte Dienste.

Ergebnis je Aussage: **stimmt**, **veraltet (korrigiert)** oder **nicht prüfbar (begründet)**.

## 3. Protokoll

| Dokument | Abschnitt | Ergebnis | Nachweis |
| --- | --- | --- | --- |
| Ersteinrichtung | Alle Abschnitte | stimmt | Beschriftungen (fett und in Anführungszeichen) im Code; Schritttitel `initial_pages.TITLES` (5 Schritte); Prüfgrenze `initial_checks.LIMIT, WINDOW = 10, 60.0`; Meldungstabelle gleich `setup_messages.CATALOGUE`; Route `/einrichtung/start`; `--reset-web-password`, `--pair` in der Kommandozeile |
| Ersteinrichtung | Kopf | veraltet (korrigiert) | „Stand: Mailhelp 5.3“ → „Geprüft für Mailhelp 7.0“ |
| Betrieb | Wiederkehrende Verarbeitungsfehler | stimmt | `processing/retry.py`: `DELAYS = (60, 300, 1800, 7200)`, höchstens 5 Versuche, dauerhafte Fehler sofort aufgegeben; Schalter „Ausführliches Protokoll“ = `logging.verbose` |
| Betrieb | Wiederkehrende Verarbeitungsfehler | veraltet (korrigiert) | Ankündigung „Nachmessung am echten Bestand nach einer Woche“ aus 6.4 entfernt |
| Betrieb | Starten, prüfen, beenden; Speichern, Aktivieren, Neuladen | stimmt | Beschriftungen im Code; sofort wirksame Bereiche = `configuration.LIVE_FIELDS` (zusätzlich Hilfschat) |
| Betrieb | Update | veraltet (korrigiert) | „Stylesheet und Skript“ → mehrere Skripte seit 7.0.12, je Datei mit Inhaltskürzel |
| Betrieb | Sicherung, Aufbewahrung, Rückkehr | stimmt | `--prepare-rollback` vorhanden; Fristen unter `retention` |
| Betrieb | Web-Push | stimmt | neun Prüfstufen in `static/push.js` (`stage(1…9)`) |
| Fehlerbehebung | Tabelle, Wiederholte Mails, Analyse-Daten, Web-Passwort, Diagnose, Hilfschat, Web-Push | stimmt | Beschriftungen und Meldungen im Code (`pipeline_failures`, `status_pages`, `mail_archive_site`, `setup_site`, `help_window`); `token_refresh_denied`, `resume_abandoned` als Ereignisse vorhanden |
| Fehlerbehebung | Mail wird wiederholt nicht verarbeitet | veraltet (korrigiert) | Statusseite schreibt „aufgegeben“ klein (`status_pages.py`) |
| Konten verwalten | Postfach hinzufügen, Zuordnung, Regeln je Postfach, Weitere Ziele, Wenn etwas nicht klappt | stimmt | Beschriftungen im Code (`mailbox_site`, `mailbox_profiles`); Zugangsdaten wirken nach Neustart (`credential_pages.py`) |
| Konten verwalten | IServ-Konto ergänzen | veraltet (korrigiert) | Seit der Direktaktivierung: **Verbindung prüfen und Konto aktivieren**, Abruf ohne Neustart im nächsten sicheren Mailzyklus (`iserv_site.py`); vorher „Diagnose `iserv`, Abruf nach Neustart“ |
| Konten verwalten | Ändern, deaktivieren und entfernen | veraltet (korrigiert) | IServ-Änderungen werden als Entwurf gespeichert und nach Übernahme wirksam (`iserv_site.save`) |
| Kalender und Aufgaben verbinden | Alle Abschnitte | stimmt | `targets.removal_window_minutes` Standard 10 (`target_settings.py`); Zugangsvariablen werden gelesen; Beschriftungen in `oauth_site.py`, `initial_pages.py`. Anbieterquellen: nicht erneut geprüft (externe Seiten, Prüfdatum 11. November 2026 bleibt genannt) |
| Bedienung | Offene Entscheidungen, Wischen, Rückfragen, Abgleich, Nach dem Anlegen, Entfernen | stimmt | Wischschwellen `SWIPE.share 0.4`, `flingShare 0.5`, Breite 1024 px (`static/open-list.js`); Entfernfrist 10 Minuten; Status „Wieder entfernt“ (`review/views.py`); Beschriftungen im Code |
| Bedienung | Lernmodus, Aus Entscheidungen lernen | stimmt | Anzahl 1–1000 (`learning_jobs.LearningSelection`), höchstens 100/500 Belege (`rule_learning/mining.py`), `learning.parallel_llm_calls` Standard 4 |
| Bedienung | Annahmequote | stimmt | fünf angebotene Gründe (`reject_reasons.USER_REJECT_REASONS`); Absenderhinweis ab 5 Vorschlägen in 90 Tagen bei höchstens 10 % (`proposal_evaluation.py`); Lernhinweis ab 20 Ablehnungen, „Ausblenden“ für 7 Tage |
| Bedienung | Fehlgeschlagene Mails | veraltet (korrigiert) | Überschrift der Statusseite heißt „Letzte Fehler und Handlungsbedarf“ (`status_pages.py`), nicht „Handlungsbedarf und Wiederholungen“ |
| Bedienung | Telefon, Hilfe, Seitenübersicht, Auswertung, Web-Push | stimmt | Beschriftungen im Code; Rücklink „← Zurück zur Auswertung“ aus `page_head(back=…)` |
| Konten verwalten | Ändern, deaktivieren und entfernen | veraltet (korrigiert) | Entfernen eines Postfachs und IServ-Entwürfe wirken nach Übernahme erst nach Neustart (`setup_site.py`: Verbindungsfelder nicht in `LIVE_FIELDS`, „Neustart erforderlich“) |
| Einstellungen der Weboberfläche | Themen, Übersicht, Suche, Live-Suche, Bereiche, Postfach hinzufügen, Zugangsdaten, Diagramme, Kontenstatus | stimmt | `settings_search.MAX_QUERY = 80`, Verzögerung 150 ms (`static/settings.js`), Vorschau verfällt nach 86 400 s (`topic_editor.py`), Bereiche gleich `settings_pages.AREAS` |
| Einstellungen der Weboberfläche | IServ-Konten | veraltet (korrigiert) | Direktaktivierung ohne Neustart ergänzt; Entwurfsweg wirkt nach Neustart |
| Einstellungen der Weboberfläche | Tabellen aller Einstellungen | stimmt | automatisch geprüft: `tests/release/test_documentation_inventory.py` (eigener Eintrag je Einstellung, jede Grenze und jeder Standardwert) |
| Einstellungen der Weboberfläche | Kopf | veraltet (korrigiert) | „Stand … 6.9.1“ → „Geprüft für Mailhelp 7.0“ |
| Einrichtung und Qualitätsprüfung | Kopf, Entwicklungswerkzeuge, Prompt-Gate | stimmt | `devtools/check.py` (Aufgaben tdd/fast/full/ui/prompts/mutation, Mutationsgrenze 90 %), `hatchling==1.27.0` in `pyproject.toml`; Stand-Zeile 4.1.11 → 7.0 |
| Einrichtung und Qualitätsprüfung | Weboberfläche und Tailscale | veraltet (korrigiert) | „Browserbasierter Erststart, OAuth im Browser und Web-Lernmodus noch nicht implementiert“ – alle drei gibt es seit 3.7/3.8 |
| Einrichtung und Qualitätsprüfung | IServ-Elternbriefe einrichten | veraltet (korrigiert) | Direktaktivierung ohne Neustart als Hauptweg; Entwurfsweg als Alternative |
| Einrichtung und Qualitätsprüfung | Google OAuth, Docker | stimmt | Scopes `calendar.events`, `calendar.calendars.readonly` (`google_login.SCOPES`), Anmeldung läuft nach 300 s ab |
| Einrichtung und Qualitätsprüfung | Reale Erkennungsqualität, datierte Berichte | nicht prüfbar (begründet) | datierte Messberichte vom 7. und 8. Oktober 2026 beschreiben ausdrücklich den damaligen Stand; eine neue Messung bräuchte echte Modellaufrufe mit Kosten |
| Kalender und Aufgaben verbinden, Google OAuth Playground, Projektwebsite | Alle Abschnitte | stimmt | Mailhelp-seitige Angaben im Code bzw. in `.github/workflows/pages.yml` (Auslöser `push` auf `main`, `workflow_dispatch`, Seitenprüfung); Schritte in Googles Oberfläche: nicht prüfbar (fremde Oberfläche, keine echten Konten in Tests) |
| Zustandsregeln 3.6, Entkopplung von Bedienung und Abruf | Alle Abschnitte | stimmt | jede genannte Testdatei, Testfunktion und jedes Modul existiert (`tests/fakes/safety_harness.py`, `runtime/operator_thread.py`, …); Stand-Zeile ergänzt |
| Datenschutzerklärung | Kopf, Abschnitt 1 | veraltet (korrigiert) | technischer Stand 3.4.5 → 7.0; Apple Erinnerungen über iCloud-CalDAV als Ziel ergänzt |
| Datenschutzerklärung | Abschnitt 3 und 5 | veraltet (korrigiert) | fehlende Datenflüsse ergänzt: Lernbestand mit Ablehnungsgründen (`review/learning_log.py`), Hilfschat (Frage, Verlauf, Dokumentationsausschnitte an die KI), Regellernen und Lernlauf nach Freigabe, Nachprüfung geschriebener Einträge, Ändern, Absagen und Entfernen eigener Einträge |
| Datenschutzerklärung | Abschnitt 6 (Google) | veraltet (korrigiert) | `calendar.events` dient auch zu bestätigten Änderungen, Absagen, Nachprüfung und dem ausdrücklich gewünschten Entfernen |
| Datenschutzerklärung | Abschnitt 7 | veraltet (korrigiert) | Hilfschat: an die Sitzung gebunden, Löschung nach Abmeldung oder 24 Stunden Ruhe (`helpdocs/chat.cleanup`); übrige Fristen gleich den Standards (`RetentionSettings`, `metrics.retention_days` 90, `web.session_days` 30) |
| Datenschutzerklärung | Abschnitte 4, 8, 9, 10 | stimmt | Rechtsgrundlagen und Rechte: nicht technisch prüfbar (rechtliche Vorlage); technische Sicherheitsangaben (Cookies, CSRF, TLS, Zugangsdaten nur in `.env`) gleich dem Code |
| Datenschutzerklärung | Abschnitt 3 und 5 (Antwortentwürfe) | veraltet (korrigiert) | seit 4.8 je Postfach automatische Ablage einschaltbar (`auto_draft`, Standard aus); vorher hieß es „ausschließlich ausdrücklich bestätigt“ |
| Nutzungsbedingungen | Abschnitt 1 und 3 | veraltet (korrigiert) | Stand 3.3.1 → 7.0; Apple Erinnerungen ergänzt; automatische Entwurfsablage je Postfach ergänzt; „bis zu zehn Postfächer“ stimmt (`mail_settings.MAX_MAILBOXES = 10`) |
| Nutzungsbedingungen | Abschnitte 2, 4–10 | nicht prüfbar (begründet) | rechtliche Vorlage; technische Aussagen (`--clear`, kein Mailversand, Bestätigungspflicht) gleich dem Code |
| Spezifikation | Modulverweise, Konfigurationsschlüssel, Optionen, Variablen, Dateien | stimmt | automatisch geprüft (`tests/release/test_documentation_checks.py`); jeder genannte Modulpfad `mailhelp.…` und `paket.modul` löst auf |
| Spezifikation | Vorschlagsabgleich (23.x) | veraltet (korrigiert) | Knopf heißt seit 6.6 „Zu diesem Eintrag hinzufügen“, nicht „Zusatz ausdrücklich zuordnen“ |
| Spezifikation | Regellernen, Aktionsleiste | veraltet (korrigiert) | `learning.js` zeigt „n zur Übernahme ausgewählt · m zum Verwerfen markiert.“ (seit 6.0.4) |
| Spezifikation | Wieder entfernen (6.6) | veraltet (korrigiert) | Status heißt „Wieder entfernt“ (`review/views.py`), Knopf „Eintrag wirklich entfernen“ (`web/actions.py`), Telegram fragt „Wirklich entfernen: „Titel“?“ (`update_handling.py`) |
| Spezifikation | Fehlerklassen der Diagnose | veraltet (korrigiert) | Google-Meldung lautet „Die Google-Freigabe ist abgelaufen oder wurde widerrufen.“ (`setup_messages.py`) |
| Spezifikation | Quellbeleg, Offen auf dem Telefon, Auswertung | veraltet (korrigiert) | Verhalten liegt seit 7.0.12 in `open-list.js`, nicht in `app.js` |
| Spezifikation | Zitierte Meldungen | stimmt | übrige zitierte Telegram- und Weboberflächentexte entstehen zusammengesetzt im Code (z. B. `telegram/writes._created_text`, `review/service.py`, `web/open_toolbar.py`); Beispielsätze aus Mails sind keine Oberflächentexte |
| Spezifikation | Ergänzung 7.0 | neu | Schichten, Typgrenzen und Skriptdateien als Vertrag ergänzt |
| Spezifikation | Fachliche Abschnitte vor 7.0 im Einzelnen | nicht im Einzelnen geprüft (begründet) | 4 410 Zeilen in versionsweisen Ergänzungen; jede Ergänzung wurde mit ihrer Version abgenommen und ist durch Tests abgesichert (100 % Zeilen- und Branch-Abdeckung). Geprüft wurden in 7.0 alle Bezüge auf Code, Oberfläche und Konfiguration (siehe Zeilen oben); eine Satz-für-Satz-Prüfung jeder fachlichen Regel steht aus |
| README | Ganzes Dokument | veraltet (korrigiert) | auf Einstieg, Schnellstart, Konfiguration, Datenschutz, Entwicklung und Verweise gekürzt (K6); veraltete Angaben entfernt: `full --workers 4` mit sequenzieller Prozessgruppe, „strikte Typregeln nur für Kernpakete“, `test_ui_widescreen60.py`, Verweise auf archivierte Anleitungen für Updates |
| AGENTS.md, config.example.yaml, .env.example | Ganzes Dokument | stimmt | jeder Modellschlüssel steht in `config.example.yaml`; jede Variable aus `.env.example` wird gelesen; Prüfbefehle in AGENTS.md entsprechen `devtools/check.py` |

## 4. Dauerhafte automatische Prüfungen (K5)

`tests/release/test_documentation_checks.py` prüft bei jedem Lauf:

| Prüfung | Test |
| --- | --- |
| (a) genannte Konfigurationsschlüssel existieren; jeder Schlüssel steht in `config.example.yaml` | `test_named_configuration_keys_exist`, `test_every_configuration_key_is_in_the_example_configuration` |
| (b) genannte Kommandozeilenoptionen existieren | `test_named_command_line_options_exist` |
| (c) genannte Umgebungsvariablen werden gelesen; jede Variable aus `.env.example` wird gelesen | `test_named_environment_variables_are_read`, `test_every_example_variable_is_read` |
| (d) in den Anleitungen zitierte Beschriftungen kommen in der Oberfläche vor | `test_labels_quoted_in_the_guides_occur_in_the_interface` |
| (e) genannte Dateien des Repositorys existieren | `test_named_repository_files_exist` |
| (f) der Hilfeindex ist aus den aktuellen Anleitungen erzeugt | `tests/unit/test_helpdocs.py` |
| Stand-Zeile „Geprüft für Mailhelp X.Y“ nennt die aktuelle Hauptversion (K6) | `test_every_living_document_names_the_current_major_version` |
| relative Links aller Markdown-Dateien lösen auf (K2) | `tests/release/test_documentation_links.py` |

Bei (d) sind Zitate erlaubt, die keine Beschriftung sind (Beispielsätze, Statusnamen fremder
Oberflächen); sie stehen mit Begründung in der Ausnahmeliste des Tests.

## 5. Seiten der Weboberfläche

Jede Seite der Weboberfläche mit ihrer Aufgabe und dem Ort ihrer Dokumentation; ein Test
vergleicht die Liste mit den registrierten Seiten.
Technische Endpunkte (`/api/…`, `/static/…`, `/health`, Manifest, Service-Worker) sind
Teil der genannten Seiten und haben keine eigene Bedienung.

| Seite | Funktion | Dokumentation |
| --- | --- | --- |
| `/` | Offen: zu entscheidende Vorschläge und Fragen | [Bedienung](Bedienung.md) |
| `/offen` | Offene Vorschläge (Kurzform) | [Bedienung](Bedienung.md) |
| `/vorschlag/…` | Vorschlag mit Beleg, Prüfstand, Bearbeiten, Versionen | [Bedienung](Bedienung.md) |
| `/serie/…` | Termine einer Serie gemeinsam bestätigen | [Bedienung](Bedienung.md) |
| `/aktion/…` | Fortschritt einer Aktion | [Bedienung](Bedienung.md) |
| `/mails` | Mailarchiv | [Bedienung](Bedienung.md) |
| `/sprache` | Sprachwahl der Oberfläche (7.5.1, setzt nur ein Cookie) | [Bedienung](Bedienung.md) |
| `/mails/fehler/alle` | Sammelaktion für fehlgeschlagene Mails (7.3.3) | [Bedienung](Bedienung.md) |
| `/mail/…` | Mail mit Verarbeitungsweg, Anhängen und Originalen | [Bedienung](Bedienung.md) |
| `/abgleich` | Vorschlagsabgleich | [Bedienung](Bedienung.md) |
| `/verlauf` | Verlauf und Revisionen | [Bedienung](Bedienung.md) |
| `/berichte` | Tätigkeitsberichte, Export | Web-Einstellungen (activity_report) |
| `/berichte/neu` | Neuen Tätigkeitsbericht starten | Web-Einstellungen (activity_report) |
| `/auswertung` | Auswertung und Kennzahlen | [Bedienung](Bedienung.md) |
| `/auswertung/aufrufe` | Aufrufliste hinter jeder Kennzahl (5.9.10) | [Bedienung](Bedienung.md) |
| `/auswertung/schritte` | Langsamste Durchläufe je Verarbeitungsschritt (6.1.8) | [Bedienung](Bedienung.md) |
| `/briefing` | Tagesüberblick | [Bedienung](Bedienung.md) |
| `/themen` | Themenpflege | Web-Einstellungen |
| `/themen/relevant/{identity}` | Relevantes Thema einzeln bearbeiten oder anlegen | Web-Einstellungen |
| `/themen/ausschluss/{identity}` | Ausschlussthema einzeln bearbeiten oder anlegen | Web-Einstellungen |
| `/themen/pruefen` | Vorschau einer Themenänderung ohne Schreibzugriff | Web-Einstellungen |
| `/themen/entwurf/{identity}` | Eigene offene Themenvorschau erneut anzeigen | Web-Einstellungen |
| `/themen/lernen` | Themenregeln aus Entscheidungen, Vergleich und bestätigte Übernahme | Bedienung, Web-Einstellungen |
| `/lernen` | Gemeinsame Lernübersicht, kein Analysestart | Bedienung, Web-Einstellungen |
| `/lernen/postfach` | Lesender Lernlauf aus dem Postfach | Bedienung |
| `/lernen/entscheidungen` | Regeln aus protokollierten Entscheidungen | Bedienung, Web-Einstellungen |
| `/lernen/vorschlaege` | Annahmequote messen: Kacheln, Wochen, Themen, Absender, Gründe | [Bedienung](Bedienung.md) |
| `/lernen/absender-hinweis` | Vorschau und Übernahme eines vorgeschlagenen Absenders | [Bedienung](Bedienung.md) |
| `/status` | Status, Dienste, Neuladen | Web-Einstellungen, [Betrieb](Betrieb.md) |
| `/diagnose` | Diagnose und Diagnosebericht | [Fehlerbehebung](Fehlerbehebung.md) |
| `/diagnose/bericht` | Diagnosebericht herunterladen | [Fehlerbehebung](Fehlerbehebung.md) |
| `/push/kanaele` | Bestätigte Übernahme der Web-Push-Kanäle | [Release 6.8](archiv/Release-6.8.md) |
| `/benachrichtigungen` | Benachrichtigungen dieses Geräts | Web-Einstellungen (notifications) |
| `/geraete` | Gekoppelte Geräte | Web-Einstellungen (web) |
| `/einrichtung` | Ersteinrichtung | [Ersteinrichtung](Ersteinrichtung.md) |
| `/anmelden` | Anmeldung, Geräte koppeln | [Ersteinrichtung](Ersteinrichtung.md) |
| `/einstellungen` | Einstellungsbereiche und Suche | Web-Einstellungen |
| `/hilfe` | Hilfschat zu Einstellungen und Bedienung | Web-Einstellungen (Hilfschat) |
| `/hilfe/dokumentation` | Mitgelieferte Dokumentation lesen, auch ohne KI | Web-Einstellungen (Hilfe) |
| `/einstellungen/postfaecher` | Postfächer anlegen, prüfen, ändern | [Konten verwalten](Konten-verwalten.md) |
| `/einstellungen/iserv` | IServ-Konten | [Konten verwalten](Konten-verwalten.md) |
| `/einstellungen/zielprofile` | Zielprofile | [Ziele einrichten](Ziele-einrichten.md) |
| `/einstellungen/zugangsdaten` | Zugangsdaten und OAuth | [Ziele einrichten](Ziele-einrichten.md) |
| `/einstellungen/benachrichtigungen` | Benachrichtigungsregeln | Web-Einstellungen (notifications) |
| `/einstellungen/ignorierte-absender` | Ignorierte Absender | Web-Einstellungen |
| `/einstellungen/web-passwort` | Web-Passwort | Web-Einstellungen |
| `/einstellungen/neustarten` | Neustart | [Betrieb](Betrieb.md) |
| `/einstellungen/beenden` | Beenden | [Betrieb](Betrieb.md) |

## 6. Inventur der Einstellungen und Optionen

<!-- inventar:start -->

Erzeugt mit `python -m devtools.inventory`: **273 Einstellungen**, davon **273** mit eigenem Eintrag in [Web-Einstellungen](Web-Einstellungen.md).

| Schlüssel | Typ | Standard | Grenzen | Bedienweg | Referenz |
| --- | --- | --- | --- | --- | --- |
| `activity_report.enabled` | bool | False |  | Weboberfläche | ja |
| `activity_report.export_mails_without_events` | bool | True |  | Weboberfläche | ja |
| `activity_report.max_fulltext_chars` | int | 30000 | ≥ 1000, ≤ 32000 | Weboberfläche | ja |
| `activity_report.max_llm_calls` | int | 3000 | ≥ 1, ≤ 50000 | Weboberfläche | ja |
| `activity_report.max_mails` | int | 2000 | ≥ 1, ≤ 20000 | Weboberfläche | ja |
| `activity_report.max_share_of_llm_budget` | float | 0.5 | > 0, ≤ 1 | Weboberfläche | ja |
| `attachments.max_original_bytes` | int | 26214400 | ≥ 1024, ≤ 104857600 | Weboberfläche | ja |
| `attachments.max_total_bytes` | int | 52428800 | ≥ 1024, ≤ 524288000 | Weboberfläche | ja |
| `attachments.store_originals` | bool | True |  | Weboberfläche | ja |
| `auto_draft` | bool | False |  | Weboberfläche | ja |
| `briefings.enabled` | bool | False |  | Weboberfläche | ja |
| `briefings.mailbox` | int oder Auswahl: default | 'default' |  | Weboberfläche | ja |
| `briefings.skip_empty` | bool | True |  | Weboberfläche | ja |
| `briefings.times` | list[str] | ['07:00', '13:00', '18:00'] | Länge ≤ 1440 | Weboberfläche | ja |
| `daily_briefing.enabled` | bool | False |  | Einrichtung | ja |
| `daily_briefing.include_calendar` | bool | True |  | Weboberfläche | ja |
| `daily_briefing.include_open` | bool | True |  | Weboberfläche | ja |
| `daily_briefing.include_tasks` | bool | True |  | Weboberfläche | ja |
| `daily_briefing.time` | str | '07:30' |  | Einrichtung | ja |
| `data_directory` | Path | Pflicht |  | Datei | ja |
| `drafts.enabled` | bool | True |  | Weboberfläche | ja |
| `drafts.folder` | str (optional) | – |  | Weboberfläche | ja |
| `event_defaults.in_person_duration_minutes` | int | 180 | ≥ 1, ≤ 1440 | Weboberfläche | ja |
| `event_defaults.video_duration_minutes` | int | 60 | ≥ 1, ≤ 1440 | Weboberfläche | ja |
| `help_chat.enabled` | bool | True |  | Weboberfläche | ja |
| `help_chat.max_context_bytes` | int | 24000 | ≥ 2000, ≤ 48000 | Weboberfläche | ja |
| `help_chat.max_question_chars` | int | 4000 | ≥ 100, ≤ 8000 | Weboberfläche | ja |
| `help_chat.requests_per_minute_per_session` | int | 6 | ≥ 1, ≤ 20 | Weboberfläche | ja |
| `imap.batch_size` | int | 25 | ≥ 1, ≤ 1000 | Weboberfläche | ja |
| `imap.connection_mode` | Auswahl: ssl, starttls, plain (optional) | – |  | Einrichtung | ja |
| `imap.drafts_folder` | str (optional) | – |  | Einrichtung | ja |
| `imap.folders` | list[str] (optional) | – | Länge ≥ 1, Länge ≤ 100 | Einrichtung | ja |
| `imap.global_newest_first` | bool | False |  | Weboberfläche | ja |
| `imap.historical_start` | datetime (optional) | – |  | Einrichtung | ja |
| `imap.host` | str (optional) | – | Länge ≥ 1, Länge ≤ 253 | Einrichtung | ja |
| `imap.mailboxes[].activity_report_folder` | str (optional) | – |  | Postfachseite | ja |
| `imap.mailboxes[].auto_draft` | bool (optional) | – |  | Postfachseite | ja |
| `imap.mailboxes[].connection_mode` | Auswahl: ssl, starttls, plain | 'ssl' |  | Postfachseite | ja |
| `imap.mailboxes[].daily_briefing` | bool | True |  | Postfachseite | ja |
| `imap.mailboxes[].drafts_folder` | str | 'Drafts' | Länge ≥ 1, Länge ≤ 500 | Postfachseite | ja |
| `imap.mailboxes[].enabled` | bool | True |  | Datei | ja |
| `imap.mailboxes[].event_defaults.in_person_duration_minutes` | int (optional) | – | ≥ 1, ≤ 1440 | Postfachseite | ja |
| `imap.mailboxes[].event_defaults.video_duration_minutes` | int (optional) | – | ≥ 1, ≤ 1440 | Postfachseite | ja |
| `imap.mailboxes[].folders` | list[str] | Pflicht | Länge ≥ 1, Länge ≤ 100 | Postfachseite | ja |
| `imap.mailboxes[].historical_start` | datetime (optional) | – |  | Postfachseite | ja |
| `imap.mailboxes[].host` | str | Pflicht | Länge ≥ 1, Länge ≤ 253 | Postfachseite | ja |
| `imap.mailboxes[].id` | int | Pflicht | ≥ 1, ≤ 99 | Postfachseite | ja |
| `imap.mailboxes[].label` | str | 'Postfach' | Länge ≥ 1, Länge ≤ 40 | Postfachseite | ja |
| `imap.mailboxes[].mail_client` | Auswahl: auto, apple_mail, gmail_web, outlook_web, none | 'auto' |  | Postfachseite | ja |
| `imap.mailboxes[].notifications.categories.action_results` | list[Auswahl: telegram, web_push] (optional) | – | Länge ≤ 2 | Postfachseite | ja |
| `imap.mailboxes[].notifications.categories.daily_briefing` | list[Auswahl: telegram, web_push] (optional) | – | Länge ≤ 2 | Postfachseite | ja |
| `imap.mailboxes[].notifications.categories.decisions` | list[Auswahl: telegram, web_push] (optional) | – | Länge ≤ 2 | Postfachseite | ja |
| `imap.mailboxes[].notifications.categories.system_errors` | list[Auswahl: telegram, web_push] (optional) | – | Länge ≤ 2 | Postfachseite | ja |
| `imap.mailboxes[].notifications.quiet_hours.allow_system_errors` | bool (optional) | – |  | Postfachseite | ja |
| `imap.mailboxes[].notifications.quiet_hours.enabled` | bool (optional) | – |  | Postfachseite | ja |
| `imap.mailboxes[].notifications.quiet_hours.end` | str (optional) | – |  | Postfachseite | ja |
| `imap.mailboxes[].notifications.quiet_hours.start` | str (optional) | – |  | Postfachseite | ja |
| `imap.mailboxes[].own_addresses` | list[str] | [] | Länge ≤ 20 | Datei | ja |
| `imap.mailboxes[].personal_info` | str (optional) | – | Länge ≤ 2000 | Postfachseite | ja |
| `imap.mailboxes[].port` | int | Pflicht | ≥ 1, ≤ 65535 | Postfachseite | ja |
| `imap.mailboxes[].primary_folder` | str | 'INBOX' |  | Postfachseite | ja |
| `imap.mailboxes[].retention.full_mail_days` | int oder Auswahl: disabled, unlimited | Pflicht |  | Postfachseite | ja |
| `imap.mailboxes[].smart_reply` | bool (optional) | – |  | Postfachseite | ja |
| `imap.mailboxes[].target_profile` | int | 1 | ≥ 1, ≤ 99 | Postfachseite | ja |
| `imap.port` | int (optional) | – | ≥ 1, ≤ 65535 | Einrichtung | ja |
| `imap.primary_folder` | str (optional) | – |  | Einrichtung | ja |
| `iserv.accounts[].enabled` | bool | True |  | IServ-Seite | ja |
| `iserv.accounts[].historical_start` | datetime (optional) | – |  | IServ-Seite | ja |
| `iserv.accounts[].id` | int | Pflicht | ≥ 1, ≤ 10 | IServ-Seite | ja |
| `iserv.accounts[].label` | str | 'Elternbriefe' | Länge ≥ 1, Länge ≤ 40 | IServ-Seite | ja |
| `iserv.accounts[].mailbox` | int | 1 | ≥ 1, ≤ 99 | IServ-Seite | ja |
| `iserv.accounts[].server` | str | Pflicht | Länge ≥ 1, Länge ≤ 253 | IServ-Seite | ja |
| `language` | Auswahl: de, en | 'de' |  | Weboberfläche | ja |
| `learning.decision_llm_content` | bool | False |  | Weboberfläche | ja |
| `learning.learning_run_hint_rejections` | int | 20 | ≥ 1, ≤ 500 | Datei | ja |
| `learning.learning_run_hints_enabled` | bool | True |  | Datei | ja |
| `learning.parallel_llm_calls` | int | 4 | ≥ 1, ≤ 100 | Weboberfläche | ja |
| `learning.sender_hint_days` | int | 90 | ≥ 1, ≤ 365 | Datei | ja |
| `learning.sender_hint_max_acceptance_rate` | float | 0.1 | ≥ 0.0, ≤ 1.0 | Datei | ja |
| `learning.sender_hint_min_proposals` | int | 5 | ≥ 1, ≤ 100 | Datei | ja |
| `learning.sender_hints_enabled` | bool | True |  | Datei | ja |
| `limits.llm_calls_per_minute` | int | Pflicht | ≥ 1, ≤ 600 | Weboberfläche | ja |
| `limits.max_attachment_bytes` | int | 5000000 | ≥ 1024, ≤ 100000000 | Weboberfläche | ja |
| `limits.max_decoded_text_bytes` | int | 1000000 | ≥ 1, ≤ 100000000 | Datei | ja |
| `limits.max_display_header_characters` | int | 500 | ≥ 1, ≤ 10000 | Datei | ja |
| `limits.max_header_bytes` | int | 64000 | ≥ 256, ≤ 1000000 | Datei | ja |
| `limits.max_html_characters` | int | 1000000 | ≥ 1, ≤ 100000000 | Datei | ja |
| `limits.max_html_depth` | int | 100 | ≥ 1, ≤ 10000 | Datei | ja |
| `limits.max_html_tags` | int | 20000 | ≥ 1, ≤ 1000000 | Datei | ja |
| `limits.max_llm_payload_bytes` | int | 500000 | ≥ 1, ≤ 100000000 | Weboberfläche | ja |
| `limits.max_mail_bytes` | int | Pflicht | ≥ 1024, ≤ 100000000 | Weboberfläche | ja |
| `limits.max_mime_parts` | int | 100 | ≥ 1, ≤ 10000 | Datei | ja |
| `llm.ollama_address` | str | 'localhost:11434' |  | Datei | ja |
| `llm.provider` | Auswahl: openrouter, ollama | 'openrouter' |  | Datei | ja |
| `logging.console.enabled` | bool | True |  | Weboberfläche | ja |
| `logging.console.format` | Auswahl: text, jsonl | 'text' |  | Datei | ja |
| `logging.console.level` | str | 'INFO' |  | Weboberfläche | ja |
| `logging.directory` | Path | Pflicht |  | Datei | ja |
| `logging.file.backup_count` | int | Pflicht | ≥ 0 | Datei | ja |
| `logging.file.enabled` | bool | True |  | Weboberfläche | ja |
| `logging.file.filename` | Path | Pflicht |  | Datei | ja |
| `logging.file.format` | Auswahl: text, jsonl | 'jsonl' |  | Datei | ja |
| `logging.file.level` | str | 'INFO' |  | Weboberfläche | ja |
| `logging.file.max_bytes` | int | Pflicht | > 0 | Datei | ja |
| `logging.file.retention_days` | int | Pflicht | > 0, ≤ 3650 | Datei | ja |
| `logging.llm.backup_count` | int | Pflicht | ≥ 0 | Datei | ja |
| `logging.llm.enabled` | bool | True |  | Weboberfläche | ja |
| `logging.llm.filename` | Path | Pflicht |  | Datei | ja |
| `logging.llm.format` | Auswahl: text, jsonl | 'jsonl' |  | Datei | ja |
| `logging.llm.include_requests` | bool | False |  | Weboberfläche | ja |
| `logging.llm.include_responses` | bool | False |  | Weboberfläche | ja |
| `logging.llm.level` | str | 'INFO' |  | Weboberfläche | ja |
| `logging.llm.max_bytes` | int | Pflicht | > 0 | Datei | ja |
| `logging.llm.retention_days` | int | Pflicht | > 0, ≤ 3650 | Datei | ja |
| `logging.modules` | dict[str, str] | {} |  | Datei | ja |
| `logging.telegram.backup_count` | int | 5 | ≥ 0 | Datei | ja |
| `logging.telegram.enabled` | bool | True |  | Weboberfläche | ja |
| `logging.telegram.filename` | Path | 'telegram/messages.jsonl' |  | Datei | ja |
| `logging.telegram.format` | Auswahl: text, jsonl | 'jsonl' |  | Datei | ja |
| `logging.telegram.level` | str | 'INFO' |  | Weboberfläche | ja |
| `logging.telegram.max_bytes` | int | 10000000 | > 0 | Datei | ja |
| `logging.telegram.retention_days` | int | 30 | > 0, ≤ 3650 | Datei | ja |
| `logging.verbose` | bool | False |  | Weboberfläche | ja |
| `metrics.electricity_eur_per_kwh` | float | 0.3 | ≥ 0, ≤ 100 | Weboberfläche | ja |
| `metrics.enabled` | bool | True |  | Weboberfläche | ja |
| `metrics.exchange_rate_date` | date (optional) | – |  | Weboberfläche | ja |
| `metrics.ollama_power_watts` | float | 300 | ≥ 0, ≤ 100000 | Weboberfläche | ja |
| `metrics.retention_days` | int | 90 | ≥ 1, ≤ 3650 | Weboberfläche | ja |
| `metrics.usd_per_eur` | float (optional) | 1.1 | > 0 | Weboberfläche | ja |
| `notifications.batching.enabled` | bool | False |  | Einrichtung | ja |
| `notifications.batching.window_seconds` | int | 300 | ≥ 1, ≤ 86400 | Einrichtung | ja |
| `notifications.categories.action_results` | list[Auswahl: telegram, web_push] | [] | Länge ≤ 2 | Einrichtung | ja |
| `notifications.categories.daily_briefing` | list[Auswahl: telegram, web_push] | [] | Länge ≤ 2 | Einrichtung | ja |
| `notifications.categories.decisions` | list[Auswahl: telegram, web_push] | [] | Länge ≤ 2 | Einrichtung | ja |
| `notifications.categories.system_errors` | list[Auswahl: telegram, web_push] | [] | Länge ≤ 2 | Einrichtung | ja |
| `notifications.delivery.history_days` | int | 30 | ≥ 1, ≤ 3650 | Einrichtung | ja |
| `notifications.delivery.initial_backoff_seconds` | int | 30 | ≥ 1, ≤ 86400 | Einrichtung | ja |
| `notifications.delivery.max_attempts` | int | 3 | ≥ 1, ≤ 10 | Einrichtung | ja |
| `notifications.delivery.max_backoff_seconds` | int | 900 | ≥ 1, ≤ 86400 | Einrichtung | ja |
| `notifications.delivery.max_pending` | int | 1000 | ≥ 1, ≤ 100000 | Einrichtung | ja |
| `notifications.quiet_hours.allow_system_errors` | bool | False |  | Einrichtung | ja |
| `notifications.quiet_hours.enabled` | bool | False |  | Einrichtung | ja |
| `notifications.quiet_hours.end` | str | '07:30' |  | Einrichtung | ja |
| `notifications.quiet_hours.start` | str | '22:00' |  | Einrichtung | ja |
| `notifications.telegram_content` | Auswahl: neutral, summary | 'neutral' |  | Einrichtung | ja |
| `personal_info` | str | '' | Länge ≤ 2000 | Weboberfläche | ja |
| `poll_interval_seconds` | int | Pflicht | ≥ 5, ≤ 86400 | Weboberfläche | ja |
| `proposal_reconciliation.max_semantic_candidates` | int | 8 | ≥ 1, ≤ 50 | Weboberfläche | ja |
| `push.enabled` | bool | False |  | Einrichtung | ja |
| `push.subject` | str | 'mailto:admin@example.invalid' |  | Einrichtung | ja |
| `reanalysis.enabled` | bool | True |  | Datei | ja |
| `reanalysis.max_attempts` | int | 2 | ≥ 1, ≤ 5 | Datei | ja |
| `reanalysis.max_jobs_per_day` | int | 20 | ≥ 1, ≤ 500 | Datei | ja |
| `reanalysis.max_llm_calls_per_job` | int | 5 | ≥ 1, ≤ 10 | Datei | ja |
| `retention.activity_report_days` | int oder Auswahl: disabled, unlimited | 365 |  | Weboberfläche | ja |
| `retention.analysis_days` | int oder Auswahl: disabled, unlimited (optional) | – |  | Weboberfläche | ja |
| `retention.cleanup_interval_minutes` | int | 60 | ≥ 0, ≤ 1440 | Weboberfläche | ja |
| `retention.debug_llm_days` | int oder Auswahl: disabled, unlimited | 'disabled' |  | Weboberfläche | ja |
| `retention.decision_learning_days` | int oder Auswahl: disabled, unlimited | 'unlimited' |  | Weboberfläche | ja |
| `retention.full_mail_days` | int oder Auswahl: disabled, unlimited | 30 |  | Weboberfläche | ja |
| `retention.history_days` | int oder Auswahl: disabled, unlimited | 90 |  | Weboberfläche | ja |
| `retries.interpretation_attempts` | int | 3 | ≥ 1, ≤ 20 | Weboberfläche | ja |
| `retries.interpretation_backoff_seconds` | int | 60 | ≥ 1, ≤ 86400 | Weboberfläche | ja |
| `retries.json_repair` | int | Pflicht | ≥ 0, ≤ 10 | Datei | ja |
| `retries.provider_retry` | int | Pflicht | ≥ 0, ≤ 10 | Datei | ja |
| `retries.revision_attempts` | int | 3 | ≥ 1, ≤ 20 | Weboberfläche | ja |
| `retries.revision_backoff_seconds` | int | 60 | ≥ 1, ≤ 86400 | Weboberfläche | ja |
| `retries.schema_repair` | int | Pflicht | ≥ 0, ≤ 10 | Datei | ja |
| `smart_reply` | bool | False |  | Weboberfläche | ja |
| `target_profiles[].caldav_calendar_url` | str | '' | Länge ≤ 2000 | Zielprofilseite | ja |
| `target_profiles[].caldav_task_url` | str | '' | Länge ≤ 2000 | Zielprofilseite | ja |
| `target_profiles[].calendar_provider` | Auswahl: google, caldav, outlook | 'google' |  | Zielprofilseite | ja |
| `target_profiles[].google_calendar` | str | '' | Länge ≤ 500 | Zielprofilseite | ja |
| `target_profiles[].google_tasks_list` | str | '@default' | Länge ≥ 1, Länge ≤ 500 | Zielprofilseite | ja |
| `target_profiles[].id` | int | Pflicht | ≥ 2, ≤ 99 | Zielprofilseite | ja |
| `target_profiles[].label` | str | Pflicht | Länge ≥ 1, Länge ≤ 40 | Zielprofilseite | ja |
| `target_profiles[].microsoft_tenant` | str | 'common' |  | Zielprofilseite | ja |
| `target_profiles[].microsoft_todo_list` | str | 'default' | Länge ≥ 1, Länge ≤ 500 | Zielprofilseite | ja |
| `target_profiles[].notion_data_source_id` | str | '' | Länge ≤ 36 | Zielprofilseite | ja |
| `target_profiles[].notion_done_statuses` | list[str] | [] | Länge ≤ 50 | Zielprofilseite | ja |
| `target_profiles[].notion_open_status` | str | '' | Länge ≤ 100 | Zielprofilseite | ja |
| `target_profiles[].notion_properties.description` | str | '' | Länge ≤ 100 | Zielprofilseite | ja |
| `target_profiles[].notion_properties.due` | str | '' | Länge ≤ 100 | Zielprofilseite | ja |
| `target_profiles[].notion_properties.operation_key` | str | '' | Länge ≤ 100 | Zielprofilseite | ja |
| `target_profiles[].notion_properties.source` | str | '' | Länge ≤ 100 | Zielprofilseite | ja |
| `target_profiles[].notion_properties.status` | str | '' | Länge ≤ 100 | Zielprofilseite | ja |
| `target_profiles[].notion_properties.title` | str | '' | Länge ≤ 100 | Zielprofilseite | ja |
| `target_profiles[].outlook_calendar` | str | 'default' | Länge ≥ 1, Länge ≤ 500 | Zielprofilseite | ja |
| `target_profiles[].removal_window_minutes` | int | 10 | ≥ 1, ≤ 1440 | Zielprofilseite | ja |
| `target_profiles[].task_provider` | Auswahl: todoist, microsoft_todo, caldav, apple_reminders, google_tasks, notion | 'todoist' |  | Zielprofilseite | ja |
| `target_profiles[].todoist_project` | str | '' | Länge ≤ 500 | Zielprofilseite | ja |
| `targets.caldav_calendar_url` | str | '' | Länge ≤ 2000 | Weboberfläche | ja |
| `targets.caldav_task_url` | str | '' | Länge ≤ 2000 | Weboberfläche | ja |
| `targets.calendar_provider` | Auswahl: google, caldav, outlook | 'google' |  | Weboberfläche | ja |
| `targets.google_calendar` | str | '' | Länge ≤ 500 | Weboberfläche | ja |
| `targets.google_tasks_list` | str | '@default' | Länge ≥ 1, Länge ≤ 500 | Weboberfläche | ja |
| `targets.microsoft_tenant` | str | 'common' |  | Weboberfläche | ja |
| `targets.microsoft_todo_list` | str | 'default' | Länge ≥ 1, Länge ≤ 500 | Weboberfläche | ja |
| `targets.notion_data_source_id` | str | '' | Länge ≤ 36 | Einrichtung | ja |
| `targets.notion_done_statuses` | list[str] | [] | Länge ≤ 50 | Einrichtung | ja |
| `targets.notion_open_status` | str | '' | Länge ≤ 100 | Einrichtung | ja |
| `targets.notion_properties.description` | str | '' | Länge ≤ 100 | Datei | ja |
| `targets.notion_properties.due` | str | '' | Länge ≤ 100 | Datei | ja |
| `targets.notion_properties.operation_key` | str | '' | Länge ≤ 100 | Datei | ja |
| `targets.notion_properties.source` | str | '' | Länge ≤ 100 | Datei | ja |
| `targets.notion_properties.status` | str | '' | Länge ≤ 100 | Datei | ja |
| `targets.notion_properties.title` | str | '' | Länge ≤ 100 | Datei | ja |
| `targets.outlook_calendar` | str | 'default' | Länge ≥ 1, Länge ≤ 500 | Weboberfläche | ja |
| `targets.removal_window_minutes` | int | 10 | ≥ 1, ≤ 1440 | Datei | ja |
| `targets.task_provider` | Auswahl: todoist, microsoft_todo, caldav, apple_reminders, google_tasks, notion | 'todoist' |  | Weboberfläche | ja |
| `targets.todoist_project` | str | '' | Länge ≤ 500 | Weboberfläche | ja |
| `telegram.chat_id` | int | 1 |  | Weboberfläche | ja |
| `telegram.enabled` | bool | True |  | Einrichtung | ja |
| `telegram.sequential_questions` | bool | True |  | Weboberfläche | ja |
| `telegram.user_id` | int | 1 | > 0 | Weboberfläche | ja |
| `test_mode` | bool | False |  | Weboberfläche | ja |
| `timeouts.caldav.initial_backoff_seconds` | float | Pflicht | ≥ 0, ≤ 30 | Weboberfläche | ja |
| `timeouts.caldav.max_backoff_seconds` | float | Pflicht | ≥ 0, ≤ 60 | Weboberfläche | ja |
| `timeouts.caldav.retries` | int | Pflicht | ≥ 0, ≤ 10 | Weboberfläche | ja |
| `timeouts.caldav.timeout_seconds` | float | Pflicht | ≥ 1, ≤ 300 | Weboberfläche | ja |
| `timeouts.google_calendar.initial_backoff_seconds` | float | Pflicht | ≥ 0, ≤ 30 | Weboberfläche | ja |
| `timeouts.google_calendar.max_backoff_seconds` | float | Pflicht | ≥ 0, ≤ 60 | Weboberfläche | ja |
| `timeouts.google_calendar.retries` | int | Pflicht | ≥ 0, ≤ 10 | Weboberfläche | ja |
| `timeouts.google_calendar.timeout_seconds` | float | Pflicht | ≥ 1, ≤ 300 | Weboberfläche | ja |
| `timeouts.google_tasks.initial_backoff_seconds` | float | Pflicht | ≥ 0, ≤ 30 | Weboberfläche | ja |
| `timeouts.google_tasks.max_backoff_seconds` | float | Pflicht | ≥ 0, ≤ 60 | Weboberfläche | ja |
| `timeouts.google_tasks.retries` | int | Pflicht | ≥ 0, ≤ 10 | Weboberfläche | ja |
| `timeouts.google_tasks.timeout_seconds` | float | Pflicht | ≥ 1, ≤ 300 | Weboberfläche | ja |
| `timeouts.imap.initial_backoff_seconds` | float | Pflicht | ≥ 0, ≤ 30 | Weboberfläche | ja |
| `timeouts.imap.max_backoff_seconds` | float | Pflicht | ≥ 0, ≤ 60 | Weboberfläche | ja |
| `timeouts.imap.retries` | int | Pflicht | ≥ 0, ≤ 10 | Weboberfläche | ja |
| `timeouts.imap.timeout_seconds` | float | Pflicht | ≥ 1, ≤ 300 | Weboberfläche | ja |
| `timeouts.microsoft.initial_backoff_seconds` | float | Pflicht | ≥ 0, ≤ 30 | Weboberfläche | ja |
| `timeouts.microsoft.max_backoff_seconds` | float | Pflicht | ≥ 0, ≤ 60 | Weboberfläche | ja |
| `timeouts.microsoft.retries` | int | Pflicht | ≥ 0, ≤ 10 | Weboberfläche | ja |
| `timeouts.microsoft.timeout_seconds` | float | Pflicht | ≥ 1, ≤ 300 | Weboberfläche | ja |
| `timeouts.notion.initial_backoff_seconds` | float | Pflicht | ≥ 0, ≤ 30 | Weboberfläche | ja |
| `timeouts.notion.max_backoff_seconds` | float | Pflicht | ≥ 0, ≤ 60 | Weboberfläche | ja |
| `timeouts.notion.retries` | int | Pflicht | ≥ 0, ≤ 10 | Weboberfläche | ja |
| `timeouts.notion.timeout_seconds` | float | Pflicht | ≥ 1, ≤ 300 | Weboberfläche | ja |
| `timeouts.ollama.initial_backoff_seconds` | float | Pflicht | ≥ 0, ≤ 30 | Weboberfläche | ja |
| `timeouts.ollama.max_backoff_seconds` | float | Pflicht | ≥ 0, ≤ 60 | Weboberfläche | ja |
| `timeouts.ollama.retries` | int | Pflicht | ≥ 0, ≤ 10 | Weboberfläche | ja |
| `timeouts.ollama.timeout_seconds` | float | Pflicht | ≥ 1, ≤ 1800 | Weboberfläche | ja |
| `timeouts.openrouter.initial_backoff_seconds` | float | Pflicht | ≥ 0, ≤ 30 | Weboberfläche | ja |
| `timeouts.openrouter.max_backoff_seconds` | float | Pflicht | ≥ 0, ≤ 60 | Weboberfläche | ja |
| `timeouts.openrouter.retries` | int | Pflicht | ≥ 0, ≤ 10 | Weboberfläche | ja |
| `timeouts.openrouter.timeout_seconds` | float | Pflicht | ≥ 1, ≤ 300 | Weboberfläche | ja |
| `timeouts.telegram.initial_backoff_seconds` | float | Pflicht | ≥ 0, ≤ 30 | Weboberfläche | ja |
| `timeouts.telegram.max_backoff_seconds` | float | Pflicht | ≥ 0, ≤ 60 | Weboberfläche | ja |
| `timeouts.telegram.retries` | int | Pflicht | ≥ 0, ≤ 10 | Weboberfläche | ja |
| `timeouts.telegram.timeout_seconds` | float | Pflicht | ≥ 1, ≤ 300 | Weboberfläche | ja |
| `timeouts.telegram_poll_seconds` | int | Pflicht | ≥ 1, ≤ 50 | Datei | ja |
| `timeouts.todoist.initial_backoff_seconds` | float | Pflicht | ≥ 0, ≤ 30 | Weboberfläche | ja |
| `timeouts.todoist.max_backoff_seconds` | float | Pflicht | ≥ 0, ≤ 60 | Weboberfläche | ja |
| `timeouts.todoist.retries` | int | Pflicht | ≥ 0, ≤ 10 | Weboberfläche | ja |
| `timeouts.todoist.timeout_seconds` | float | Pflicht | ≥ 1, ≤ 300 | Weboberfläche | ja |
| `timezone` | str | Pflicht |  | Weboberfläche | ja |
| `vision.enabled` | bool | True |  | Weboberfläche | ja |
| `vision.max_edge_pixels` | int | 1600 | ≥ 512, ≤ 4096 | Weboberfläche | ja |
| `vision.max_image_bytes` | int | 5000000 | ≥ 10240, ≤ 50000000 | Weboberfläche | ja |
| `vision.max_images_per_mail` | int | 3 | ≥ 1, ≤ 10 | Weboberfläche | ja |
| `web.allowed_hosts` | list[str] | ['127.0.0.1:8765', 'localhost:8765'] | Länge ≥ 1, Länge ≤ 20 | Datei | ja |
| `web.enabled` | bool | False |  | Datei | ja |
| `web.google_redirect_uri` | str | 'http://localhost:8765/auth/google/call… |  | Datei | ja |
| `web.host` | str | '127.0.0.1' |  | Datei | ja |
| `web.lan_access` | bool | False |  | Weboberfläche | ja |
| `web.notion_redirect_uri` | str | 'http://localhost:8765/auth/notion/call… |  | Datei | ja |
| `web.port` | int | 8765 | ≥ 1, ≤ 65535 | Datei | ja |
| `web.session_days` | int | 30 | ≥ 1, ≤ 365 | Weboberfläche | ja |
| `write_verification.max_attempts` | int | 5 | ≥ 1, ≤ 10 | Datei | ja |
| `write_verification.max_elapsed_seconds` | int | 300 | ≥ 10, ≤ 86400 | Datei | ja |
| `write_verification.retry_delays_seconds` | list[int] | [1, 5, 15, 60] | Länge ≤ 9 | Datei | ja |

**25 Kommandozeilenoptionen** (`mailhelp --help`):

| Option | Bedeutung laut Hilfe |
| --- | --- |
| `--check` | Konfiguration validieren und beenden |
| `--check-access` | Zugänge prüfen, Telegram-Testnachricht senden und beenden |
| `--clear` | alle Zustandsdaten, Decision-Test-Berichte und Logs nach ausdrücklicher Bestätigung löschen |
| `--config-directory` | Verzeichnis mit config.yaml, prompts.yaml, topics.yaml und irrelevant_topics.yaml |
| `--decision-test` | ANZAHL Mails über Standardpfad und Ollama vergleichen; nur relevante Mails weiter analysieren |
| `--decision-test-file` | neue JSON-Testdatei für --decision-test (relativ zu --config-directory) |
| `--decision-test-laya` | EXPERIMENTELL: Relevanzprüfung des Ollama-Pfads im --decision-test mit dem Entscheidungsmodell Laya auf diesem Ollama-Server (/v1/systemone) |
| `--decision-test-laya-model` | Laya-Modell für --decision-test-laya; überschreibt model aus laya_prompts.yaml |
| `--decision-test-relevance-only` | im --decision-test ausschließlich die Relevanzprüfung beider Pfade vergleichen |
| `--demo, -demo` | Demo-Modus mit vorbereiteten Beispieldaten in einem eigenen, leeren Verzeichnis starten |
| `--google-auth` | Google-Anmeldung im lokalen Browser |
| `--ignore-historical-start` | konfiguriertes imap.historical_start und den gespeicherten historischen Startpunkt für diesen Abruf aufheben |
| `--learn` | ANZAHL Mails frei klassifizieren und Themen interaktiv im Terminal lernen |
| `--log-directory` | Logverzeichnis aus config.yaml für diesen Aufruf überschreiben |
| `--mailbox` | Postfach (imap.mailboxes.id) oder alle aktivierten Postfächer für --learn und --decision-test; bei mehreren aktivierten Postfächern erforderlich |
| `--max-mails` | höchstens ANZAHL Mails in einem einzelnen Abrufdurchlauf bearbeiten und beenden |
| `--microsoft-login` | bei Microsoft (Outlook-Kalender, Microsoft To Do) per Gerätecode anmelden und den Refresh-Token in microsoft-token.json neben .env speichern |
| `--ollama` | EXPERIMENTELL: alle LLM-Schritte statt über OpenRouter über den lokalen Ollama-Server HOST:PORT ausführen (IPv6 als [::1]:11434) |
| `--ollama-model` | Ollama-Modell für --ollama; überschreibt ollama.model aus prompts.yaml |
| `--pair` | Lokalen Einmalcode zur Webanmeldung anzeigen |
| `--prepare-rollback` | 5.2: vor der Rückkehr zu einer Version vor 5.2.0 alle Einträge „wird geprüft“ auf „angelegt“ umstellen; nur bei beendetem Dienst |
| `--profile` | Zielprofil (1–99) für die OAuth-Einrichtung |
| `--reset-web-password` | Am Host Web-Passwort zurücksetzen und alle Websitzungen abmelden |
| `--show-imap-credentials` | bei --check-access den tatsächlich verwendeten IMAP-Benutzernamen und das Passwort im Terminal ausgeben |
| `--yes` | Bestätigungsabfrage für --clear überspringen |

<!-- inventar:end -->
