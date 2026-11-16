# Mailhelp 4.0 – Browser-First Inbetriebnahme und Web-Lernmodus

Release 4.0.0, 4. November 2026. Es fasst die abgenommenen Arbeitsstände 3.6.38
(Fundament und Absicherung), 3.7.19 (Ersteinrichtung und OAuth im Browser) und
3.8.28 (Web-Lernmodus, Neuladen und Anbietermatrix) zusammen. Die Planung steht in
[Planung 4.0](Planung-4.0.md), die Teilabnahmen in [Release 3.6](Release-3.6.md),
[Release 3.7](Release-3.7.md) und [Release 3.8](Release-3.8.md).

## Was sich ändert

- **Einrichtung im Browser:** Ohne `config.yaml` startet nur der geschützte
  Einrichtungsserver. Der beim Start im Terminal ausgegebene Einmalcode öffnet den
  fünfstufigen Assistenten für Web-Passwort, Postfach, KI-Anbieter und Ziele. Danach
  wechselt Mailhelp im selben Prozess in den Normalbetrieb.
- **Anmeldung:** Terminal-Code (`mailhelp --pair`), Telegram-Code und Web-Passwort
  erzeugen gleichberechtigte, widerrufbare Sitzungen.
- **OAuth im Browser:** Google über Rückleitung oder OAuth-Playground, Microsoft über
  Gerätecode; die CLI-Befehle bleiben als Alternative erhalten.
- **Lernen im Browser:** `/lernen` schätzt Umfang und Kosten, läuft im Hintergrund mit
  Pause, Abbruch und Wiederaufnahme und übernimmt Themen, Ausschlüsse, Absender und
  Ordner erst nach ausdrücklicher Bestätigung. `mailhelp --learn` bleibt erhalten.
- **Betrieb ohne Neustart:** `/dienst/neu-laden` aktiviert gespeicherte Änderungen am
  nächsten sicheren Mailzyklus; `/dienst/selbsttest` prüft alle Komponenten lesend.
  `/status` zeigt Monatskosten und die letzte Abfrage je Postfach.
- **Absicherung:** Gleichzeitige Bedienung über Web und Telegram sowie harte
  Prozessabbrüche erzeugen keine doppelten oder unberechtigten Anlagen; nachgewiesen
  für sieben Anbieter unter Windows, Linux und Docker.

Unverändert gilt: Keine Einrichtung, Anmeldung, Lernaktion und kein Neuladen legt
Termine oder Aufgaben an. Jede externe Anlage braucht die ausdrückliche Bestätigung
einer konkreten Vorschlagsversion.

## Neu einrichten

- **Windows oder Linux:** In einer virtuellen Umgebung zuerst die geprüften Abhängigkeiten
  (`python -m pip install -r requirements.lock`), dann das Wheel installieren
  (`python -m pip install --no-deps mailhelp-4.0.0-py3-none-any.whl`) und
  `mailhelp --config-directory <Verzeichnis>` starten. Den Code aus dem Terminal unter
  `http://localhost:8765/anmelden` eingeben.
- **Docker:** `docker compose -f compose.setup.yaml up --build`. Das Volume
  `mailhelp-config` hält Konfiguration, `.env`, Zustände und Logs; den Code der
  Dienstausgabe entnehmen.

Einzelheiten zu Schritten, Hostfreigaben und OAuth stehen in [Release 3.7](Release-3.7.md),
zum Lernmodus und Neuladen in [Release 3.8](Release-3.8.md).

## Upgrade

1. Dienst beenden. Datenverzeichnis, `config.yaml`, `prompts.yaml`, `topics.yaml`,
   `irrelevant_topics.yaml`, `irrelevant-senders.json` und `.env` sichern.
2. Neues Wheel installieren beziehungsweise das Docker-Image neu bauen.
3. Dienst starten. Eine vorhandene `config.yaml` bleibt gültig; die Einstellungen `llm`,
   `learning` und `web.google_redirect_uri` sind optional und haben Standardwerte
   (siehe `config.example.yaml`). Mit aktivierter Weboberfläche bleibt `MAILHELP_WEB_SECRET`
   (mindestens 32 Zeichen) wie bisher Pflicht; nur die Ersteinrichtung erzeugt ihn selbst.
4. Offene Vorschläge bleiben an ihre Version und ihr Ziel gebunden. Ältere Freigaben ohne
   passenden Ausführungsbeleg bleiben sichtbar gesperrt und brauchen eine neue Bestätigung.

Nie zwei Versionen gleichzeitig auf demselben Datenverzeichnis starten.

## Rückkehr zu 3.x

Dienst beenden, die vorherige Paketversion installieren und die vor dem Upgrade
gesicherten Dateien und das Datenverzeichnis zurückspielen. Ältere strikte Modelle
kennen die neuen Felder (`llm`, `web.google_redirect_uri`, Web-Freigabe- und
Journalfelder) nicht; eine nach dem Upgrade geänderte Konfiguration oder Zustandsablage
ist deshalb für ältere Versionen nicht geeignet.

## Datenschutz

Der Lernmodus sendet Inhalte der gewählten Mails an das konfigurierte KI-Modell; nur
Postfächer und Ordner auswählen, deren Verarbeitung erlaubt ist. Zwischenstände enthalten
Kategorien, Betreffbelege und Absender, aber keine Zugangsdaten oder vollständigen
Mailtexte. Passwörter, Tokens und Codes erscheinen nicht in Logs oder HTML-Antworten.

## Abnahme

Grundlage ist die bestandene Gesamtabnahme in [Release 3.8](Release-3.8.md) mit Szenario-,
Anbieter- und Plattformbericht nach Q4.6. Für 4.0.0 wurden alle Prüfungen mit dem
endgültigen Stand wiederholt. Es wurden ausschließlich simulierte Dienste und synthetische
Daten verwendet; die Linux-Prüfungen liefen in einem nativen Ubuntu-Verzeichnis (WSL 2,
Ubuntu 24.04) unter dem unprivilegierten Benutzer `nobody`.

| Prüfung | Plattform | Ergebnis |
| :--- | :--- | :--- |
| Vollständige Python-Suite | Windows 11, Python 3.12.10 | 3.226 Tests; 100 % Zeilen- und 100 % Branch-Abdeckung¹ |
| Vollständige Python-Suite | Linux, Python 3.12.3 | 3.225 bestanden, 1 übersprungen²; 100 % Zeilen- und 100 % Branch-Abdeckung |
| Browser: Desktop, Mobilgeräte, ohne JavaScript | Windows 11, Chromium | 219 bestanden; 100 % JavaScript-Blockabdeckung für `app.js`, `sw.js`, `setup.js` |
| Installiertes Wheel 4.0.0: Paketinhalt, CLI, Lernmodus, Neuladen, Browserbedienung, Anbietermatrix, Prozessabbrüche, Uhrkorrekturen | Windows 11 | 365 bestanden |
| Installiertes Wheel 4.0.0 (unter Linux gebaut), gleiche Auswahl | Linux | 365 bestanden |
| Docker (`container-smoke` aus der CI) | Linux, Docker 29.1.3, Compose 2.40.3 | Image gebaut; `--check`, Start und Neustart, Lernen und Prüfung im frischen Container, harter Abbruch mit zwei Neustarts für sieben Anbieter: 28/28 bestanden |
| Statische Prüfungen | Windows 11 | `ruff check src tests ui_tests` und `mypy` (223 Quelldateien) ohne Befund |

¹ 3.225 bestanden. `test_built_artifacts_exclude_private_runtime_files` scheiterte im
Gesamtlauf, weil in `dist/` noch ein Wheel aus einem früheren Zwischenstand lag; nach dem
Neubau des Wheels 4.0.0 bestand er (Prüfablauf, kein Produktfehler).
² `test_built_artifacts_exclude_private_runtime_files` setzt gebaute Artefakte voraus; er
ist im Paketlauf auf beiden Plattformen bestanden.

### Gefundene Fehler

| Fehler | Fund | Behebung | Regressionstests |
| :--- | :--- | :--- | :--- |
| Wurde die Systemuhr während der Verarbeitung zurückgestellt, scheiterte die Mail mit `internal_error` (zunächst in `proposal_notification`, in einem zweiten Lauf in `duplicate_precheck`), oder ihr Zustand wurde als `.invalid` isoliert. Ursache: Orchestrator und Vorschlagsablage setzten `updated_at` direkt auf die Wanduhr, ein neuer Mailzustand las die Uhr zweimal, `MailState` verlangt `updated_at >= created_at`. | Linux-Gesamtlauf unter WSL 2 (Hyper-V-Zeitabgleich `hv_utils.timesync_implicit=1`); der Fehler trat nur sporadisch auf. Nachweis: Die Zeitstempel im Zustand liefen gegenüber der monotonen Testdauer, und eine simulierte zurückspringende Uhr reproduzierte beide Fehlerbilder. | 4.0.0: `next_updated_at()` bewegt `updated_at` nie rückwärts (Orchestrator und alle drei Schreibstellen der Vorschlagsablage); ein neuer Mailzustand liest die Uhr nur einmal; die erneute Prüfung übernimmt den bisherigen Zeitstempel. | `tests/unit/test_mail_timestamps.py`, `tests/e2e/test_e2e_simulated.py::test_the_pipeline_completes_when_the_wall_clock_steps_back`, `tests/services/test_mail_recheck.py` (zwei Tests), `tests/telegram/test_telegram_extracted_services.py::test_repository_writes_stay_valid_after_the_clock_stepped_back`; vor dem Fix scheiterten 10 dieser Fälle, danach bestehen alle. |

### Einschränkungen

- Echte Konten, OAuth-Zustimmungen und externe Anlagen gehören nicht zur automatisierten
  Abnahme. Vor dem produktiven Einsatz einmal mit einem Testkalender beziehungsweise
  Testprojekt prüfen.
- Docker lief unter WSL 2 auf dem Entwicklungsrechner, nicht auf einem eigenständigen
  Linux-Host; derselbe Ablauf ist als CI-Job `container-smoke` hinterlegt.
- Die GitHub-CI läuft für diesen Stand erst nach dem Push; der Release-Workflow
  veröffentlicht Wheel und Quellarchiv erst nach einem Tag `v4.0.0` und bestandener CI.

Die Berichte liegen unter `.test-tmp-40/` (`windows-results.xml`, `linux-results.xml`,
`linux-coverage.json`, `wheel-results.xml`, `linux-wheel-results.xml`, `ui-results.xml`,
`linux-output.txt`).
