# Entwicklungsregeln für Mailhelp

Geprüft für Mailhelp 8.1.

- Entwickle in Python für lokale Nutzung unter Windows 11 und Docker auf Linux.
- Halte Prompts/Modelle/LLM-Parameter in prompts.yaml, Themen in topics.yaml,
  Anwendungseinstellungen in config.yaml und Geheimnisse außerhalb des Codes.
- Verwende lesbare JSON-Dateien für den Zustand und separate JSONL-Logs.
- Erzwinge vor jedem Schreibzugriff auf Google Kalender oder Todoist eine
  ausdrückliche, versionsbezogene Bestätigung über Telegram oder die authentifizierte
  Weboberfläche. Bearbeiten und Speichern allein autorisieren keine externe Anlage.
  Webaktionen benötigen eine gültige, auch bei Ausführung erneut geprüfte Sitzung,
  CSRF-Schutz, Versionsprüfung und einen Idempotenzschlüssel.
- Behandle Mailinhalte und LLM-Ausgaben als nicht vertrauenswürdige Eingaben.
- Verhindere doppelte Aktionen; gleiche unklare Schreibresultate vor Wiederholung ab.
- Protokolliere keine Zugangsdaten. Vollständige LLM-Inhalte sind explizit zuschaltbar.
- Für sämtlichen eigenen Anwendungscode sind 100 % Zeilen- und 100 %
  Branch-Abdeckung verbindlich. Jede Codeänderung enthält passende Tests.
- Jeder Bugfix muss einen Regressionstest enthalten, der den behobenen Fehler
  reproduziert, vor dem Fix fehlschlägt und nach dem Fix besteht, damit ein erneutes
  Auftreten des Bugs künftig automatisch erkannt wird.
- Die automatisierte Prüfung muss bei Unterschreitung eines der beiden Werte scheitern.
- Lokal nutzt die Prüfung die 12 Threads des Entwicklungsrechners: die vollständige
  Python-Prüfung mit `python -m devtools.check full --workers 12` (rund 10 Minuten; Paketbau und
  Lasttests trennt das Werkzeug selbst, die Abdeckung bleibt vollständig), die Browsersuite mit
  `python -m pytest ui_tests -n 6 --dist worksteal --no-cov` (rund 8 Minuten). Python- und
  Browserprüfung laufen nie gleichzeitig, weil die Zeitmessungen sonst unzuverlässig werden.
- Umgehe die Vorgabe nicht durch Coverage-Ausschlüsse oder wirkungslose Tests.
- Prüfe Erfolgsfälle, Fehlerfälle, Wiederholungen, Neustarts und Autorisierung.
- Automatisierte Tests verwenden simulierte externe Dienste und synthetische Daten.
- Aktualisiere bei Verhaltensänderungen Spezifikation und Konfigurationsbeispiele.
- Pflege nach jeder erfolgreich geprüften Änderung an der Servereinrichtung das
  versionierte Serverhandbuch und die betroffenen Konfigurationsvorlagen, bevor die
  Arbeit als abgeschlossen gemeldet wird. Dies gilt auch für manuelle Reparaturen,
  Updates, Migrationen, Rücksetzungen und Änderungen außerhalb des Anwendungscodes
  (DNS, nginx, TLS, Docker, systemd, Firewall, Ports, Rechte, Sicherung, OAuth und Dienste).
  Maßgeblich ist nach Umsetzung von 8.0 das geplante Serverhandbuch docs/Serverhandbuch.md mit `ops/server/`;
  bis dahin den bestätigten Stand in `docs/Betrieb.md` dokumentieren.
- Halte zusätzlich eine geheimnisfreie Kopie der aktuellen Serveranleitungen und
  Konfigurationsvorlagen unter `/opt/mailhelp/server-docs` auf dem Server synchron.
  Diese Ablage ist verpflichtender Bestandteil des täglichen Serverbackups.
  Nach erfolgreich geprüften Serveränderungen auch diese Kopie aktualisieren und
  ihren Stand prüfen; die Serverkopie ersetzt weder Git noch die getrennte Sicherung
  von Zugangsdaten. Kein privates `.env`, Token oder Schlüssel in den Dokumentationsbestand.
- Übernimm Serveränderungen erst nach überprüftem Erfolg als gültigen Istzustand.
  Dokumentiere Datum, betroffene Komponenten, reproduzierbare Schritte, Versionen,
  Prüfungen/Ergebnisse und Rückkehrverfahren. Fehlgeschlagene oder zurückgenommene
  Versuche getrennt als solche kennzeichnen; bei Rückkehr den zuletzt verifizierten
  Stand beschreiben. Geplante Einrichtungen nicht als bereits vorhanden darstellen.
- Serverhandbuch und geheimnisfreie Vorlagen müssen in Git erfasst werden; lokale
  Notizen, temporäre Deploymentskripte und nur auf dem Server vorhandene Dateien
  reichen nicht. Keine Passwörter, Tokens, privaten Schlüssel, produktiven `.env`-
  Dateien oder Kundendaten übernehmen. Stattdessen benötigte Secret-Namen, sichere
  Bereitstellung und getrennte Sicherung/Wiederherstellung beschreiben. Ohne konkrete
  Commit-/Push-Anweisung Änderungen nachvollziehbar vorbereiten und den noch nicht
  versionierten Stand ausdrücklich nennen; keine erfolgreiche Git-Sicherung behaupten.
- Bei jeder neuen Version muss auch die Datei `README.md` aktualisiert werden (z. B. Versionsstand, neue Funktionen und geänderte Abläufe).
- Jeder Commit in `main` und `beta` erhöht die Versionsnummer (Patch-Version `X.X.+1`) in `pyproject.toml` und `src/mailhelp/__init__.py`, führt die Änderungen in `CHANGELOG.md` auf und hält `README.md` aktuell.
