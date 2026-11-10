# Ersteinrichtung

Stand: Mailhelp 5.3. Diese Anleitung führt von einem leeren Verzeichnis bis zum ersten
geprüften Vorschlag. Sie gilt für Windows 11 und Linux; Abweichungen für Docker sind markiert.

**Ziel:** Mailhelp läuft, ist im Browser erreichbar, liest ein Postfach, hat eine KI-Anbindung
und kennt Kalender und Aufgabenliste. Eine externe Eintragung geschieht erst nach deiner
ausdrücklichen Bestätigung.

## Voraussetzungen

- Python 3.12 (Windows: `py -3.12`, Linux: `python3.12`) oder Docker mit Compose.
- Zugangsdaten eines IMAP-Postfachs (Server, Port, Benutzername, Passwort oder App-Passwort).
- Ein Schlüssel für OpenRouter **oder** ein lokal laufender Ollama-Server.
- Optional: Zugänge zu Google Kalender/Todoist, Outlook/Microsoft To Do oder einem
  CalDAV-Server; optional ein Telegram-Bot mit deiner Benutzer- und Chat-ID.

## 1. Installieren

**Windows 11** (PowerShell im Mailhelp-Verzeichnis):

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.lock
.venv\Scripts\python -m pip install --no-deps -e .
```

**Linux:**

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .
```

**Docker:** keine Installation nötig; weiter mit Schritt 2.

## 2. Starten und den Terminal-Code ablesen

Ohne `config.yaml` startet Mailhelp den geschützten Einrichtungsassistenten.

- Windows: `.venv\Scripts\mailhelp --config-directory .`
- Linux: `.venv/bin/mailhelp --config-directory .`
- Docker: `docker compose -f compose.setup.yaml up --build`

**Ergebnis:** Das Terminal zeigt einen Einmalcode und die Adresse `http://localhost:8765`.
Fehlt der Code, mit `mailhelp --pair --config-directory .` einen neuen anfordern (Docker:
`docker compose exec mailhelp mailhelp --pair --config-directory /config`).

## 3. Im Browser koppeln

1. `http://localhost:8765/einrichtung/start` öffnen.
2. Den Code in **Code aus der Mailhelp-Konsole** eingeben und **Gerät koppeln** wählen.

**Ergebnis:** Die Seite „Mailhelp einrichten: Web-Zugang und Zeitzone“ erscheint (Schritt 1 von 5).

## 4. Assistent durchlaufen

Jeder Schritt hat **Speichern und weiter**; über die Schrittliste kommst du jederzeit zurück.
Passwortfelder bleiben leer angezeigt: **Leer: gespeicherten Wert behalten**.

1. **Web-Zugang und Zeitzone:** **Zeitzone** prüfen (z. B. `Europe/Berlin`) und ein
   **Web-Passwort (mindestens 12 Zeichen)** vergeben.
2. **Postfach:** **IMAP-Server**, **Port**, **Verschlüsselung** (`ssl` meist Port 993,
   `starttls` meist 143), Benutzername (`IMAP_USERNAME`) und Passwort (`IMAP_PASSWORD`)
   eintragen und **Verbindung jetzt prüfen** wählen. Danach **Posteingang** und
   **Entwurfsordner** aus der gefundenen Ordnerliste wählen.
3. **KI-Anbieter:** `openrouter` mit `OPENROUTER_API_KEY` oder `ollama` mit
   **Ollama-Adresse (HOST:PORT)**; **Verbindung jetzt prüfen** wählen.
4. **Kalender und Aufgaben:** **Kalenderdienst** und **Aufgabendienst** wählen und die passende
   Kennung eintragen (**Google-Kalender-ID**, **Todoist-Projekt-ID**, **CalDAV-Kalenderadresse**,
   **CalDAV-Aufgabenadresse**, **Outlook-Kalender-ID**, **Microsoft-To-Do-Liste**). Für Google und
   Microsoft stehen **Google verbinden** bzw. **Microsoft verbinden** bereit. Einzelheiten:
   [Einstellungen, Abschnitt Ziele](Web-Einstellungen.md#ziele).
5. **Abschluss:** Das **Prüfergebnis** lesen, **Konfiguration speichern und Normalbetrieb
   starten** ankreuzen und **Speichern und starten** wählen.

**Ergebnis:** „Einrichtung abgeschlossen“. `config.yaml` und `.env` sind gespeichert; die
Zugangsdaten stehen nur in `.env`.

## 5. Anmelden und Verbindungen prüfen

1. `http://localhost:8765/anmelden` öffnen und mit dem Web-Passwort anmelden. Weitere Geräte
   koppelst du mit **Code per Telegram senden** (bei aktivem Telegram) oder einem neuen
   Terminal-Code.
2. **Einstellungen → Diagnose** öffnen: Die Prüfungen lesen nur und ändern nichts.
3. Unter **Status** siehst du den letzten Kontakt je Dienst; das Postfach erscheint nach dem
   ersten Mailabruf.

## 6. Gespeicherten und aktiven Stand erkennen

In **Einstellungen** steht bei jeder Einstellung „aktiv“ oder „gespeichert – wirkt erst nach
einem Neustart“ bzw. „… an der nächsten sicheren Stelle“. Neustart: **Einstellungen →
Mailhelp neu starten**.

## 7. Erster Testfall

1. Eine Mail mit einer klaren Bitte an dich selbst senden, z. B. „Bitte bis Freitag das
   Formular zurückschicken.“
2. Nach dem nächsten Abruf erscheint unter **Offen** ein Vorschlag mit Beleg.
3. **Als Aufgabe anlegen** (bei Terminen **Im Kalender anlegen**) wählen. Mailhelp meldet erst „Gespeichert – der Eintrag wird beim Anbieter
   geprüft“ und nach dem Kontrollabruf „Angelegt und geprüft“.

Für einen Durchlauf ohne echte Eintragung `test_mode: true` setzen: Bestätigungen werden dann
nur simuliert.

## Wenn etwas nicht klappt

| Meldung oder Lage | Nächster Schritt |
| --- | --- |
| „Mailhelp läuft bereits …“ | Laufende Instanz über **Einstellungen → Mailhelp beenden** oder Strg+C beenden |
| Code abgelaufen oder vergessen | `mailhelp --pair --config-directory .` |
| Postfachprüfung scheitert | Server, Port und Verschlüsselung prüfen; Fehlermeldungen nennen die Ursache ohne Zugangsdaten |
| Web-Passwort vergessen | Am Rechner `mailhelp --reset-web-password --config-directory .` |
| Docker: Dateirechte unter Linux | `mkdir -p data logs` und `sudo chown 65532:65532 data logs` |

Weiter: [Konten verwalten](Konten-verwalten.md), [Einstellungen](Web-Einstellungen.md).
