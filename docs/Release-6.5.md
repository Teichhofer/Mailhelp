# Mailhelp 6.5 – Umsetzung und Abnahme

Zielstand: 6.5.5.

Die Arbeitspakete D1 bis D5 aus [Planung 6.5](Planung-6.5.md) sind vollständig implementiert:

- **6.5.1 – Auswertung „Vorschläge“:** Neue Auswertungsseite unter Lernen (`/lernen/vorschlaege`)
  mit Kacheln für Annahmequote gesamt, Aufgaben und Termine; Verlauf je Kalenderwoche;
  sortierbare Tabellen nach Thema und Absender; Übersicht der Ablehnungsgründe;
  Zeitraumauswahl und barrierefreie Tabellen.
- **6.5.2 – Grund einer Ablehnung im Web:** Nach dem Verwerfen bietet die Ergebniskarte
  freiwillig fünf feste Ablehnungsgründe („Betrifft mich nicht“, „Nur zur Information“,
  „Werbung oder Rundschreiben“, „Falsch erkannt (Datum, Inhalt)“, „Anderer Grund“).
  Ein Klick speichert den Grund am Vorschlag und in `learning/decisions.jsonl`, ohne die
  Entscheidung zu verändern oder das Verwerfen zu verlangsamen.
- **6.5.3 – Grund in Telegram und Regellernen:** Rejection-Nachrichten in Telegram bieten
  dieselbe Auswahl als Inline-Buttons. Der gespeicherte Grund wird beim Regellernen
  (`mining.py`) als zusätzliches Merkmal an die KI übergeben. Prompts und Gate-Prüfungen
  bleiben stabil.
- **6.5.4 – Absender-Hinweise und Regellauf-Empfehlung:**
  - Absender mit mindestens 5 Vorschlägen in 90 Tagen und höchstens 10 % Annahmequote
    erhalten automatische Hinweise auf der Auswertungsseite und der Ergebniskarte.
  - Vorschauseite (`/lernen/absender-hinweis`) zeigt alle gespeicherten Mails des Absenders
    und hebt angenommene Vorschläge hervor; Übernahme in `irrelevant-senders.json` erfolgt
    nur nach ausdrücklicher, versionsgebundener Bestätigung.
  - „Nicht mehr vorschlagen“ blendet Hinweise aus und lässt sich in der Übersicht aufheben.
  - Bei mindestens 20 neuen Ablehnungen seit dem letzten Regellauf weisen Banner auf „Offen“
    und „Lernen“ auf einen neuen Regellauf hin (höchstens wöchentlich, für 7 Tage ausblendbar).
- **6.5.5 – Dokumentation und Qualitätssicherung:**
  - Dokumentation in `README.md`, `CHANGELOG.md`, `docs/Bedienung.md`, `docs/Web-Einstellungen.md`
    und `config.example.yaml` aktualisiert.
  - 100 % Zeilen- und Branch-Abdeckung für allen Anwendungscode.
