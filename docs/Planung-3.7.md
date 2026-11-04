# Mailhelp 3.7 – Ersteinrichtung und OAuth im Browser

**Zielversion:** 3.7.0 (Schritte als Patchversionen 3.7.x)
**Stand:** 4. November 2026
**Status:** In Planung
**Grundlage:** [Entwicklungsregeln](../AGENTS.md), [Projektspezifikation](../Mailhelp-Projektspezifikation.md), [Planung 4.0](Planung-4.0.md) (Gesamtfahrplan)
**Vorgänger:** [Planung 3.6](Planung-3.6.md) · **Nachfolger:** [Planung 4.0](Planung-4.0.md)

---

## 1. Ziel

Nach 3.7 lässt sich Mailhelp ohne vorbereitete `config.yaml` im Browser einrichten.
Der erste Zugriff wird mit einem beim Start im Terminal ausgegebenen Einmalcode
authentifiziert; ein zusätzlicher Einrichtungsbefehl ist dafür nicht nötig.
Google- sowie Microsoft-Konten werden im Browser verbunden. Der
Lernmodus und das Neuladen ohne Neustart folgen in 4.0; bis dahin schließt der Assistent
mit einem kontrollierten Neustart ab.

## 2. Fachliche Beschreibung

### 2.1 Pfeiler 1: Direkte Browser-Ersteinrichtung (Onboarding-Wizard)

#### 2.1.1 Direkter Einstieg ohne Hürden
Wenn Mailhelp gestartet wird und noch keine `config.yaml` existiert:
- Der Server startet direkt im Einrichtungsmodus.
- Der Dienst gibt beim Start automatisch einen kurzlebigen Authentifizierungscode im Terminal aus.
- Der Aufruf der Weboberfläche im Browser (`http://localhost:8765` bzw. die Server-IP) öffnet zunächst die Code-Eingabe. Erst nach erfolgreicher Authentifizierung ist der Ersteinrichtungs-Assistent zugänglich; das gilt auch für `localhost`.
- Es ist kein vorheriger Terminal-Befehl (`mailhelp --pair`) und keine manuelle Datei-Vorbereitung erforderlich. Der automatisch ausgegebene Code muss aus dem Terminal übernommen werden.
- Nicht authentifizierte Browser dürfen weder Einrichtungsdaten lesen oder ändern noch Verbindungstests starten oder die Konfiguration speichern.

#### 2.1.2 Terminal-Code als dauerhafter Anmeldeweg

- Auch nach der Ersteinrichtung bleibt ein Terminal-Code als zusätzliche, eigenständige Authentifizierungsmöglichkeit neben dem Telegram-Code verfügbar. Eine Kombination beider Codes ist nicht erforderlich.
- Dafür wird der vorhandene host-authentifizierte Weg `mailhelp --pair` weiterverwendet. Er gibt einen neuen Einmalcode im Terminal aus und funktioniert auch bei deaktiviertem oder nicht erreichbarem Telegram.
- Die Anmeldeseite erläutert beide Code-Wege. Die geplante Passwortanmeldung bleibt eine weitere Alternative.
- Für beide Code-Wege gelten Einmalverwendung, Ablaufzeit, Fehlversuchsbegrenzung und dieselben widerrufbaren Websitzungen. Der Code wird nur zur vorgesehenen Ausgabe im Terminal beziehungsweise im autorisierten Telegram-Chat im Klartext ausgegeben; er gelangt nicht in Anwendungslogs. Gespeichert wird ausschließlich ein geschützter Prüfwert.
- Ein neuer Code widerruft keine bereits gültigen Websitzungen. Browseranfragen erzeugen keine unaufgeforderten Terminal-Codes.

#### 2.1.3 Der 5-stufige Onboarding-Flow

```
[1. Web-Zugang] ──► [2. Postfach] ──► [3. KI-Anbieter] ──► [4. Kalender & Aufgaben] ──► [5. Fertig & Lernen]
```

1. **Schritt 1: Web-Zugang & Zeitzone**
   - Vergabe eines Passworts für die Weboberfläche.
   - `MAILHELP_WEB_SECRET` wird im Hintergrund automatisch generiert und in `.env` gespeichert.
   - Die Systemzeitzone wird automatisch anhand des Browsers vorbelegt (z. B. `Europe/Berlin`) und kann angepasst werden.
2. **Schritt 2: Erstes IMAP-Postfach**
   - Eingabe von Host, Port, Verschlüsselung (SSL/TLS/STARTTLS), Benutzername und Passwort.
   - **Schaltfläche „Verbindung jetzt prüfen“:**
     - Testet die Erreichbarkeit und listet gefundene Ordner auf.
     - Automatische Vorauswahl für `INBOX` und den Entwurfsordner (`Drafts`, `Entwürfe`).
3. **Schritt 3: KI-Anbindung (LLM)**
   - Auswahl zwischen:
     - *OpenRouter (Cloud):* Eingabe des API-Keys mit Schaltfläche zum Prüfen des Guthabens und der Modellverfügbarkeit.
     - *Ollama (Lokal):* Eingabe der URL (`http://localhost:11434`) mit automatischem Abruf der lokal installierten Modelle.
4. **Schritt 4: Kalender- und Aufgabenziele**
   - Auswahl der Zieldienste (Google Kalender, CalDAV, Todoist, Microsoft 365).
   - Direkte Autorisierung im Browser per Klick (siehe Pfeiler 3).
   - Für Google zusätzlich eine eingebettete Schritt-für-Schritt-Hilfe zum OAuth 2.0 Playground mit Eingabe von Client-ID, Client-Secret und Refresh-Token.
5. **Schritt 5: Abschluss & Direktsprung in den Lernmodus**
   - Speichert die Konfiguration atomar in `config.yaml` und `.env`.
   - Der Dienst startet direkt im Hintergrund und leitet den Nutzer nahtlos zum **Web-Lernmodus** weiter.

### 2.2 Pfeiler 3: Browserbasierte OAuth-Abläufe (Google & Microsoft)

Keine Terminal-Befehle mehr für OAuth:

* **Google Kalender (Anleitung zum OAuth 2.0 Playground):**
  - Die [vollständige Anleitung](Google-OAuth-Playground.md) wird im Assistenten
    und bei den Zielprofilen direkt an den Google-Zugangsdaten angeboten.
  - Sie beschreibt eigenes Cloud-Projekt, Calendar API, Zustimmungsbildschirm,
    Webanwendungs-Client, Playground-Weiterleitungs-URI, eigene Clientdaten,
    Offline-Zugriff, Scopes, Zustimmung und Ermittlung des Refresh-Tokens.
  - Client-ID, Client-Secret und Refresh-Token werden über den vorhandenen
    Zugangsdatendienst für das gewählte Profil gespeichert; kein Access-Token-Import.
    Sitzung, CSRF, Versionsprüfung und Schutz vor Klartextausgabe gelten wie bei
    den anderen Zugangsdaten. Die Prüfung bleibt lesend.
  - Dieser Weg funktioniert ohne Rückleitung auf den Mailhelp-Rechner und eignet
    sich deshalb auch für Docker und entfernte Server. Die eigene Web-Redirect-
    Integration unten bleibt als zusätzlicher geplanter Weg bestehen.
* **Google Kalender (Web-Redirect):**
  1. Klick auf *„Google Kalender verbinden“* im Browser.
  2. Weiterleitung zur Google-Zustimmungsseite.
  3. Automatische Rückleitung auf `http://localhost:8765/auth/google/callback`.
  4. Das Backend speichert den Refresh-Token direkt in `.env` und lädt die verfügbaren Kalender.
* **Microsoft 365 (Device-Code im Web-Modal):**
  1. Klick auf *„Microsoft-Konto verbinden“*.
  2. Ein Modal-Dialog im Browser zeigt den Microsoft-Code (z. B. `ABCD-EFGH`) mit Kopier-Button und Direktlink zu `https://microsoft.com/devicelogin`.
  3. Die Web-UI pollt im Hintergrund, erkennt die erfolgreiche Anmeldung automatisch und schließt das Modal.
* **Todoist & CalDAV:**
  * Direkte Eingabe von API-Token bzw. Zugangsdaten im Webformular mit Test-Button.

### 2.3 Neue Web-Routen

| Methode | Pfad | Zweck |
| :--- | :--- | :--- |
| `GET` | `/einrichtung/start` | Einstieg in den Ersteinrichtungs-Wizard |
| `POST` | `/einrichtung/test/imap` | Live-Verbindungstest für IMAP-Zugangsdaten |
| `POST` | `/einrichtung/test/llm` | Live-Test für OpenRouter / Ollama |
| `POST` | `/einrichtung/speichern` | Atomare Initial-Konfiguration speichern |
| `GET` | `/auth/google/start` | Startet Google OAuth Web-Redirect |
| `GET` | `/auth/google/callback` | Nimmt Auth-Code von Google entgegen und speichert Token |
| `POST` | `/auth/microsoft/device` | Fordert Microsoft Device-Code an |
| `GET` | `/auth/microsoft/poll` | Pollt Microsoft Token-Status bis zur Bestätigung |

### 2.4 Wireframe: Onboarding-Assistent (Postfach-Einrichtung)

```text
┌────────────────────────────────────────────────────────────────────────┐
│  MAILHELP ERSTEINRICHTUNG                          Schritt 2 von 5     │
├────────────────────────────────────────────────────────────────────────┤
│  [✓ 1. Web-Zugang] ──► [● 2. Postfach] ──► [○ 3. KI] ──► [○ 4. Ziele]  │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  E-Mail-Postfach verbinden (IMAP)                                      │
│                                                                        │
│  Bezeichnung:       [ Privat                     ]                     │
│  Server-Adresse:    [ imap.web.de                ]   Port: [ 993   ]   │
│  Verschlüsselung:   (•) SSL/TLS    ( ) STARTTLS    ( ) Keine           │
│  Benutzername:      [ max.mustermann@web.de      ]                     │
│  Passwort:          [ •••••••••••••••••••••••••• ]                     │
│                                                                        │
│  [ Verbindung jetzt testen ]                                           │
│  ✓ Verbindung erfolgreich hergestellt!                                 │
│                                                                        │
│  Gefundene Ordner:                                                     │
│  Haupt-Posteingang: [ INBOX                    ▼ ]                     │
│  Entwurfsordner:    [ Entwürfe                 ▼ ] (Erkannt)           │
│                                                                        │
│  [ Zurück ]                                            [ Weiter zu KI ]│
└────────────────────────────────────────────────────────────────────────┘
```

Es gelten die Regeln aus [Planung 4.0, Abschnitt 5.1](Planung-4.0.md#51-regeln-für-die-schritte):
jeder Schritt einzeln lieferbar mit eigener Patch-Version, Umfang S (≤ 1 Tag) oder M (≤ 2 Tage),
zu große Schritte werden vor dem Weiterarbeiten geteilt. Schrittnummern sind über alle drei
Pläne eindeutig.

## 3. Schritte

### 3.1 Stufe 2 – Ersteinrichtung im Browser (Pfeiler 1)

> **Entscheidung vom 4. November 2026:** Der allererste Zugriff erfordert einen
> automatisch beim Start im Terminal ausgegebenen Authentifizierungscode.
> Die Code-Prüfung gilt für lokale und entfernte Browser. Terminal-Codes bleiben
> anschließend neben Telegram-Codes als eigenständiger Anmeldeweg erhalten.
> Damit ist der Schutz des Erstzugangs festgelegt.

| Schritt | Inhalt | Fertig, wenn … | Umfang | Voraussetzung |
| :--- | :--- | :--- | :--- | :--- |
| 2.1 | Einrichtungsmodus ohne `config.yaml` | Der Start ohne Konfiguration öffnet einen minimalen Webserver, der nur Einrichtungsrouten bedient; kein Abruf, keine Adapter. | M | 0.1 |
| 2.2 | Erstzugang per Terminal-Code | Ohne Konfiguration wird beim Start automatisch ein Einmalcode im Terminal ausgegeben. Alle Einrichtungsaktionen benötigen die daraus entstandene Sitzung. Tests für lokalen und entfernten Zugriff, ungültige, abgelaufene und verbrauchte Codes, Fehlversuche und Neustart; kein Klartextcode in Anwendungslogs. | M | 2.1 |
| 2.2a | Terminal-Code neben Telegram-Code | Der vorhandene Weg `mailhelp --pair` bleibt im Normalbetrieb verfügbar, auch ohne Telegram. Beide Wege sind auf der Anmeldeseite erklärt und erzeugen gleichberechtigte widerrufbare Sitzungen; Tests für beide Wege, Wiederholungen und bestehende Sitzungen. | S | 2.2 |
| 2.3 | Web-Passwort: Speicherung | Passwort als langsamer Hash (z. B. scrypt) außerhalb von `config.yaml`; Ändern und Zurücksetzen definiert. | S | 2.2 |
| 2.4 | Web-Passwort: Anmeldung | Anmeldung per Passwort neben der Kopplung, mit bestehenden Sitzungen, CSRF und Sperre nach Fehlversuchen. | M | 2.3 |
| 2.5 | `MAILHELP_WEB_SECRET` automatisch | Wird beim Abschluss von Schritt 1 erzeugt und atomar in `.env` geschrieben; nie angezeigt oder protokolliert. | S | 2.1 |
| 2.6 | Assistent: Rahmen und Schritt 1 | Fünfstufige Navigation mit Zwischenspeicherung im Entwurf; Zeitzone aus dem Browser vorbelegt, ohne JavaScript manuell wählbar. | M | 2.4 |
| 2.7 | Assistent: Postfach | Nutzt die vorhandene Postfachprüfung inklusive Ordnerliste; Vorauswahl von `INBOX` und Entwurfsordner über die Special-Use-Rollen. | S | 2.6 |
| 2.8 | Assistent: OpenRouter | API-Schlüssel prüfen, Guthaben und Verfügbarkeit der konfigurierten Modelle anzeigen. | S | 2.6 |
| 2.9 | Assistent: Ollama | Adresse prüfen, installierte Modelle abrufen und zur Auswahl anbieten. | S | 2.6 |
| 2.10 | Assistent: Ziele ohne OAuth | Todoist-Token und CalDAV-Zugang eingeben und prüfen; Google und Microsoft verweisen auf Stufe 3. | S | 2.6 |
| 2.11 | Abschluss und Übergang | `config.yaml` und `.env` atomar geschrieben; Übergang in den Normalbetrieb (per kontrolliertem Neustart; ab 4.0, Schritt 5.6, ohne). | M | 2.7–2.10 |
| 2.12 | Browsertest Ersteinrichtung | Playwright-Durchlauf vom leeren Verzeichnis über die Eingabe des Terminal-Codes bis zum ersten Abruf mit simulierten Diensten; unberechtigter Zugriff bleibt gesperrt. | S | 2.11 |

### 3.2 Stufe 3 – OAuth im Browser (Pfeiler 3)

> **Festgelegt für die Anleitung:** Der Playground-Weg verwendet einen eigenen
> Webanwendungs-Client mit `https://developers.google.com/oauthplayground` als
> registrierter Rückleitungsadresse; siehe [Anleitung](Google-OAuth-Playground.md).
>
> **Offene Entscheidung für die zusätzliche Direktanmeldung (vor 3.1):** Der heutige Google-Client nutzt eine Loopback-Adresse
> (`127.0.0.1`) und funktioniert nur, wenn Browser und Mailhelp auf demselben Rechner laufen.
> Für den Zugriff über die Server-IP oder Docker auf einem anderen Rechner ist entweder ein
> Webclient mit registrierter Rückleitungsadresse oder ein Device-Flow nötig. Die Wahl
> bestimmt den Umfang von 3.1–3.3.

| Schritt | Inhalt | Fertig, wenn … | Umfang | Voraussetzung |
| :--- | :--- | :--- | :--- | :--- |
| 3.0 | Google: Playground-Anleitung | Die verlinkte Schritt-für-Schritt-Hilfe ist im Assistenten und bei den Zielprofilen an den Google-Zugangsdaten erreichbar. Profilbezogene Eingabe der drei Werte über den Zugangsdatendienst; Scopes einschließlich Kalenderliste, Token-Ablaufregeln und lesende Prüfung erklärt. Browserprüfung mit synthetischen Werten, keine Geheimnisse in HTML-Antworten oder Logs. | S | 2.4, 2.6 |
| 3.1 | Google: Start | `/auth/google/start` erzeugt `state` und PKCE, an die Websitzung gebunden und dauerhaft gespeichert. | S | 2.4 |
| 3.2 | Google: Rückleitung | `/auth/google/callback` prüft `state`, Sitzung und Ablauf, tauscht den Code und speichert den Refresh-Token über den Zugangsdatendienst; Fehler- und Abbruchfälle getestet. | M | 3.1 |
| 3.3 | Google: Kalenderauswahl | Verfügbare Kalender mit `calendar.calendarlist.readonly` laden und als Ziel im Zielprofil übernehmen; funktioniert auch mit per Playground hinterlegten Zugangsdaten. | S | 3.0, 3.2 |
| 3.4 | Microsoft: Device-Code | Anforderung und Abfrage laufen im Hintergrund, Status dauerhaft gespeichert; Ablauf, Ablehnung und Neustart während des Wartens getestet. | M | 2.4 |
| 3.5 | Microsoft: Oberfläche | Code mit Kopierknopf und Link; Statusanzeige ohne JavaScript per Neuladen, mit JavaScript automatisch. | S | 3.4 |
| 3.6 | Einbindung in Assistent und Zielprofile | Verbinden und Playground-Hilfe aus Schritt 4 des Assistenten und aus `/einstellungen/zielprofile`; CLI-Befehle bleiben als Alternative. | S | 2.10, 3.0, 3.3, 3.5 |

**Umfangsübersicht:** 20 Schritte, davon 13 S und 7 M.

## 4. Abnahme

- Alle Schritte aus Abschnitt 3 sind mit Version markiert. Der Schutz des Erststarts
  ist durch den Terminal-Code festgelegt; die noch offene Entscheidung zum
  Google-Clienttyp ist vor Umsetzung getroffen und dokumentiert.
- Vom leeren Konfigurationsverzeichnis bis zum ersten Abruf ist nach dem Start kein
  zusätzlicher Terminalbefehl nötig (Browsertest 2.12). Der beim Start ausgegebene
  Code muss vor dem Zugriff auf die Einrichtung im Browser eingegeben werden.
- Terminal-Code über `--pair` und Telegram-Code funktionieren nach der Einrichtung
  als eigenständige Alternativen; `--google-auth` bleibt ebenfalls erhalten.
- Die Playground-Anleitung ist im Google-Einrichtungsschritt und in den Zielprofilen
  erreichbar; synthetische Browserprüfungen decken die profilbezogene Eingabe der
  Clientdaten und des Refresh-Tokens ohne externe Kalenderanlage ab.
- Die Szenarien aus [Planung 3.6](Planung-3.6.md) bestehen weiterhin; neue Einstiegspunkte
  (Erstzugang per Terminal-Code, reguläre Terminal-/Telegram-Code-Anmeldung,
  Anmeldung per Passwort, OAuth-Rückleitung) sind in P6/P7 aufgenommen.
- 100 % Zeilen- und Branch-Abdeckung, `ruff` und `mypy` ohne Befund.
