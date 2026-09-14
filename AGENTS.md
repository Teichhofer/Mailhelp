# Entwicklungsregeln für Mailhelp

- Entwickle in Python für lokale Nutzung unter Windows 11 und Docker auf Linux.
- Halte Prompts/Modelle/LLM-Parameter in prompts.yaml, Themen in topics.yaml,
  Anwendungseinstellungen in config.yaml und Geheimnisse außerhalb des Codes.
- Verwende lesbare JSON-Dateien für den Zustand und separate JSONL-Logs.
- Erzwinge ausdrückliche, versionsbezogene Telegram-Bestätigung vor jedem
  Schreibzugriff auf Google Kalender oder Todoist.
- Behandle Mailinhalte und LLM-Ausgaben als nicht vertrauenswürdige Eingaben.
- Verhindere doppelte Aktionen; gleiche unklare Schreibresultate vor Wiederholung ab.
- Protokolliere keine Zugangsdaten. Vollständige LLM-Inhalte sind explizit zuschaltbar.
- Für sämtlichen eigenen Anwendungscode sind 100 % Zeilen- und 100 %
  Branch-Abdeckung verbindlich. Jede Codeänderung enthält passende Tests.
- Die automatisierte Prüfung muss bei Unterschreitung eines der beiden Werte scheitern.
- Umgehe die Vorgabe nicht durch Coverage-Ausschlüsse oder wirkungslose Tests.
- Prüfe Erfolgsfälle, Fehlerfälle, Wiederholungen, Neustarts und Autorisierung.
- Automatisierte Tests verwenden simulierte externe Dienste und synthetische Daten.
- Aktualisiere bei Verhaltensänderungen Spezifikation und Konfigurationsbeispiele.
