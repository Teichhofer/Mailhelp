# Mailhelp 1.0

Mailhelp verarbeitet ein persönliches IMAP-Postfach und zeigt Zusammenfassungen,
Rückfragen sowie Aufgaben- und Terminvorschläge in Telegram. Externe Änderungen
benötigen weiterhin eine ausdrückliche Bestätigung der angezeigten Version.

## Änderungen gegenüber 0.1

- `test_mode: true` simuliert jetzt sowohl Todoist als auch Google Kalender.
  Die Schreibgrenze führt dabei auch keinen Abgleich und keinen Kalenderdateiversand
  aus. Beide Bestätigungen heißen `Simulieren`. IMAP, LLM und Telegram bleiben online.
- Eine lokale, konfigurierbare Vorprüfung erkennt die Kombination bestimmter
  Kurzlink-Hosts und Köderformulierungen. Sie verlangt eine Relevanzklärung und
  verhindert Aktionsvorschläge auch nach einer positiven Relevanzentscheidung.
  Die Anwendung öffnet die Links nicht. Die Regel ist kein allgemeiner Spamfilter.
- Die Zustandsablage toleriert kurz verzögerte Freigaben von Betriebssystem-Sperren
  durch höchstens drei Wiederholungen im Abstand von 50 ms. Belegte Sperren werden
  weder gelöscht noch anhand gespeicherter Prozessnummern übergangen.
- `mailhelp-evaluate` prüft standardmäßig Jev einschließlich des Rückfalls auf die
  generative Relevanzstufe. Beide Dienste teilen sich das vorgegebene Aufrufbudget.
  Berichte enthalten die Jev-Konfiguration, Fingerprints und den geprüften Modus.
- Gleichbedeutende Uhrzeitangaben werden auch bei unvollständigen und wiederkehrenden
  Terminen semantisch verglichen. Die vorhandenen Korpuserwartungen bleiben bestehen.
- Windows- und Linux-CI prüfen zusätzlich gebaute Pakete. Die Release-Pipeline
  veröffentlicht Wheel und Quellarchiv erst nach Tests und Docker-Neustartprüfungen.

## Installation aus dem Release

Python 3.12.x verwenden. Das Quellarchiv enthält die benötigten Konfigurationsvorlagen
und die Lockdatei; persönliche Konfiguration, Geheimnisse und Laufzeitdaten fehlen.
Archiv entpacken, in das entpackte Verzeichnis wechseln und unter Windows ausführen:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.lock
.venv\Scripts\python -m pip install --no-deps .
Copy-Item config.example.yaml config.yaml
Copy-Item .env.example .env
Copy-Item irrelevant-senders.example.json irrelevant-senders.json
```

Anschließend die Vorlagen lokal anpassen und `mailhelp --check` ausführen.
Unter Linux `.venv/bin/python` und `cp` verwenden. Alternativ das Wheel mit
`pip install --no-deps <Datei.whl>` installieren und dieselben Konfigurationsdateien
aus dem Quellarchiv verwenden. `--check-access` ist ein ausdrücklich gestarteter
Zugriffstest und führt weiterhin seine dokumentierten Leseprüfungen durch.

## Aktualisieren, sichern und zurückkehren

1. Mailhelp beenden. Den gesamten konfigurierten Datenordner einschließlich
   `test/` und `production/`, alle verwendeten YAML-Dateien und den Absenderfilter
   gemeinsam sichern. Geheimnisse separat geschützt sichern. Niemals nur einzelne
   Vorschlagsdateien wiederherstellen.
2. Vorhandene offene Vorgänge möglichst mit der bisherigen Version und ihren
   bisherigen Prompts abschließen. Die neuen Prompts ändern den Fingerprint;
   dadurch gesperrte Vorgänge nur nach dem dokumentierten Verfahren fortsetzen
   oder ausdrücklich neu verarbeiten. Einen Fingerprint nie manuell ersetzen.
3. Paket und Lockdatei aktualisieren. Die neuen Promptregeln einschließlich
   `suspicious_link_hosts` und `suspicious_link_phrases` in die tatsächlich verwendete
   `prompts.yaml` übernehmen; Jev-Regeln in `decisions_prompts.yaml` aktualisieren.
   Themen, Ziele und Geheimnisse nicht durch Beispiele überschreiben.
4. Konfiguration prüfen. Einen neuen Testlauf zuerst mit `test_mode: true` ausführen.
   Alte im Testmodus real angelegte Kalendertermine bleiben bestehen. Sie werden
   durch das Update nicht entfernt; alte `created`-Zustände bleiben erhalten.
5. Für eine Rückkehr den Dienst stoppen, die vorherige Paketversion und den
   zusammengehörigen Konfigurations-/Datenstand wiederherstellen. Zwischenzeitliche
   externe Ergebnisse können existieren: Der Idempotenzabgleich muss diese erkennen.
   Schreibreferenzen und unklare Vorgänge niemals löschen, um eine Wiederholung zu
   erzwingen. Vor einem Downgrade offene Aktionen mit der neueren Version klären.

## Grenzen

Keine Anhangauswertung, kein Mehrbenutzerbetrieb, keine automatische Mailantwort
und keine allgemeine Erkennung aller Phishing-Nachrichten. Modellantworten bleiben
prüfpflichtig. Wiederkehrende oder unklare Termine erfordern die vorhandene manuelle
Klärung. Ollama bleibt experimentell. Geänderte Provider oder Prompts erfordern eine
erneute Qualitätsprüfung. Der Prüfstand wird im Repository unter `quality-reports/`
mit den tatsächlich ausgeführten Ergebnissen dokumentiert.
