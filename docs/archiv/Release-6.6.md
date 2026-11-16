# Mailhelp 6.6 – Umsetzung und Abnahme

Zielstand: 6.6.5.

Die Arbeitspakete D1 bis D5 aus [Planung 6.6](Planung-6.6.md) sind vollständig implementiert:

- **6.6.1 – Schreibvertrag „entfernen“ (D1):**
  - Erweiterung von `external.contracts.ExternalWriter` um die Operation `remove(prepared, key)`.
  - Abgleich vor Wiederholung (`reconcile`) prüft, ob der Eintrag beim Anbieter gelöscht oder zwischenzeitlich verändert wurde.
  - Implementierung für Google Kalender, Outlook Kalender, CalDAV, Todoist und Microsoft To Do sowie Test-Fakes.
  - Schutz vor Datenverlust: Ein beim Anbieter veränderter Eintrag wird niemals entfernt.
- **6.6.2 – Befehl, Zustände und Neustart-Abgleich (D2):**
  - Neuer Befehl `CommandKind.REMOVE_CREATED` mit strikter Sitzungsprüfung, CSRF-Schutz und Idempotenzschlüssel.
  - Neuer Endzustand `ProposalStatus.REMOVED` („Angelegt und wieder entfernt“).
  - Zeitfenster-Prüfung (`targets.removal_window_minutes`, Standard 10 Minuten) verhindert verspätetes Entfernen.
  - Neustart-Sicherheit: Bei unklarem Ergebnis oder Neustart vor Ergebnisquittung gleicht Mailhelp den externen Zustand ab.
- **6.6.3 – Weboberfläche mit Bestätigungsseite (D3):**
  - Ergebniskarten und Vorschlagsdetails zeigen innerhalb des Zeitfensters die Schaltfläche „Eintrag wieder entfernen“.
  - Dedizierte Bestätigungsseite `/vorschlag/<mail_id>/<proposal_id>/entfernen` mit Anzeige von Titel, Zeit, Ziel und Erläuterung vor Ausführung.
  - Nach Ablauf des Zeitfensters wird die Schaltfläche durch den direkten Link zum externen Kalender/Aufgabendienst ersetzt.
  - Barrierefreie Plaketten und Verlaufseinträge für den Zustand „Angelegt und wieder entfernt“.
- **6.6.4 – Telegram, Auswertung und Lernprotokoll (D4):**
  - Unter der Erfolgsmeldung in Telegram wird die Inline-Schaltfläche „Wieder entfernen“ angeboten.
  - Zweistufige Rückfrage („Wirklich entfernen: ...?“) mit „Ja, entfernen“ und „Abbrechen“.
  - In der Vorschlagsauswertung (`/lernen/vorschlaege`) wird „Wieder entfernt“ separat ausgewiesen und zählt nicht als angenommen.
  - Das Lernprotokoll hält das Entfernen als eigenständige Entscheidung fest.
- **6.6.5 – Dokumentation und Qualitätssicherung (D5):**
  - Dokumentation in `README.md`, `CHANGELOG.md`, `docs/Bedienung.md`, `docs/Web-Einstellungen.md`, `docs/Ziele-einrichten.md`, `Mailhelp-Projektspezifikation.md` und `config.example.yaml`.
  - Hilfeindex und Inventare synchronisiert.
  - 100 % Zeilen- und Branch-Abdeckung für allen Anwendungscode.
