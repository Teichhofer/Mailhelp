# Mailhelp 8.2 – Umsetzung und Freigabestand

Stand: 23. November 2026. Version 8.2.1; seit den Updates auf 8.3.2 und 8.4.2 auf dem
Produktionsserver (siehe [Betrieb](Betrieb.md)). Grundlage: [Planung 8.2](Planung-8.2.md), aufbauend auf [8.0](Release-8.0.md)
und [8.1](Release-8.1.md).

## Implementiert

- **Zentrale Ziel-OAuths in `inboxstride_auth`:**
  - Neue Zielzwecke `microsoft_targets` (`https://graph.microsoft.com/Calendars.ReadWrite`,
    `https://graph.microsoft.com/Tasks.ReadWrite`, freischaltbar über
    `INBOXSTRIDE_AUTH_MICROSOFT_TARGETS_ENABLED=1`) und `notion` (`src/inboxstride_auth/notion.py`,
    Betreiberkommando `set-notion-client`, öffentlicher Callback `/auth/notion/callback`).
  - Zweckgebundene Slot-Trennung (`_same_slot`): Ein Zielprofil (`profile:<n>` oder `draft:<id>`)
    kann gleichzeitig eine aktive Google-Kalenderverbindung (`calendar`) und eine aktive
    Notion- oder Microsoft-Zielverbindung halten, ohne dass die Aktivierung des einen Dienstes
    den anderen trennt.
- **Instanzseitige Zielanbindung (`src/mailhelp/web/hosted_targets_site.py`):**
  - „Mit Microsoft verbinden“ (`/microsoft/verbinden`, `/einrichtung/microsoft/abschluss`,
    `/microsoft/ziele`, `/microsoft/trennen`) und „Mit Notion verbinden“ (`/notion/verbinden`,
    `/einrichtung/notion/abschluss`, `/notion/ziele`, `/notion/trennen`).
  - Lokale Entwurfsspeicherung (`targets.microsoft_connection`, `targets.notion_connection`)
    erfolgt vor `/intern/activate`; ein Ausfall während der Aktivierung lässt sich ohne
    doppelte lokale Speicherung nachholen.
  - Verbindungsbindung `outlook-<Verbindung>` für bestätigte Outlook-Kalendervorschläge;
    Verbindungswarnungen bieten direkt „Microsoft erneut verbinden“ und „Notion erneut verbinden“.
  - `NotionSite` liest Datenquellen und Schemata im gehosteten Modus über den kurzlebigen
    Access-Token des zentralen Dienstes.
- **Geführtes 3-Schritte-Self-Service-Onboarding (`src/mailhelp/runtime/onboarding.py`,
  `src/mailhelp/web/onboarding_site.py`):**
  - Versioniertes Zustandsmodell `onboarding.json` mit Idempotenz-, Sitzungs- und CSRF-Prüfung.
  - Schritt 1 (Postfach prüfen mit lokaler Anbietererkennung und OAuth-Einstiegen),
    Schritt 2 (Zielsystem verbinden und prüfen), Schritt 3 (Starter-Themenprofile
    *Privat & Familie*, *Beruf & Projekte*, *Verein & Ehrenamt* sowie schreibfreier
    Testmodus-Probelauf mit Vorschau).
  - Ausdrückliche Aktivierung schreibt `topics.yaml` atomar; Überspringen in die
    Expertenansicht (`/einrichtung`) ist jederzeit möglich. Vollständig zweisprachig (DE/EN).

## Prüfnachweise (21. November 2026)

- **Python-Prüfung:** `python -m devtools.check full --workers 12` mit 6 372 bestandenen
  Tests (1 übersprungen), 2 bestandenen Lasttests (`V42_BUSY_LOAD`, `V441_LOAD`) und
  **100,00 % Zeilen- und Branch-Abdeckung** (41 187 Anweisungen, 11 602 Branches über
  383 Dateien einschließlich `inboxstride_auth`).
- **Statische Prüfungen:** `ruff check` und `mypy` (392 Quelldateien) ohne Befund.
- **Browser-Suite:** `python -m pytest ui_tests -n 6 --dist worksteal --no-cov -v` mit
  998 bestandenen und 234 übersprungenen Tests sowie 100 % JavaScript-Abdeckung
  (vier mobile Tippflächen-Befunde am Button „Anbietereinstellungen laden“ durch
  `class="button"` in `src/mailhelp/web/provider_fields.py` behoben und zusammen mit dem
  einzelnen Live-Such-Zeitausreißer über `--lf` grün nachgeprüft).

## Offene Freigabeschritte und Grenzen

1. Produktive Anbieterregistrierungen für Microsoft-Ziele und Notion-OAuth im zentralen
   Anmeldedienst sind durch den Betreiber einzurichten und freizuschalten, bevor diese
   Pfade auf dem Produktionsserver aktiviert werden.
2. Erledigt: Der Stand ist produktiv (8.4.2 am 23.11.2026); Microsoft-Ziele und Notion-OAuth
   bleiben bis zu den Anbieterregistrierungen gesperrt.
