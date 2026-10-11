# Mailhelp 1.1 – Weboberfläche und App

Mailhelp 1.1 ergänzt Telegram um eine Weboberfläche. Sie läuft im Mailhelp-Prozess
auf dem eigenen PC und bietet dieselben Entscheidungen wie Telegram:

- Vorschläge prüfen, bestätigen und verwerfen
- Rückfragen beantworten
- Relevanzfragen klären

Telegram bleibt erhalten und ist weiterhin der Kanal für Benachrichtigungen.
Ohne `web.enabled: true` verhält sich Mailhelp exakt wie 1.0.

Hintergrund und Umsetzungsplan: [Konzept-1.1-Web-PWA.md](Konzept-1.1-Web-PWA.md),
Bestandsaufnahme: [1.1-Bestandsaufnahme.md](1.1-Bestandsaufnahme.md).

## Was die Weboberfläche kann

| Seite | Inhalt |
| --- | --- |
| **Offen** | Relevanzfragen zuerst, danach alle offenen Vorschläge. Der Vorschlag, der gerade in Telegram angezeigt wird, steht oben. Jede Karte zeigt dieselben Angaben wie die Telegram-Karte; Beschreibung und Beleg lassen sich vollständig aufklappen. Darunter steht „Zuletzt erledigt“. |
| **Details** | Über die Schaltfläche „Details“ jeder Karte: der Vorschlag mit allen Aktionen und darunter die vollständige Mail (Absender, Betreff, Datum, kompletter Text; Links darin sind nicht klickbar). Bei Relevanzfragen die Mail mit den Schaltflächen „Relevant“/„Irrelevant“. Nach Ablauf der Aufbewahrung steht dort, dass der Mailtext nicht mehr gespeichert ist. |
| **Status** | Version, Modus (produktiv/Test), Laufzeit, Adresse und gekoppelte Geräte; Fortschritt und Zähler des letzten Mail-Durchlaufs sowie das Ergebnis der Analyse (relevant, irrelevant, doppelt …); gespeicherte, zurückgestellte und auf Relevanz wartende Mails; Vorschläge je Zustand; die letzten fünf Mails mit Fehler (Ursache, Schritt, Zeitpunkt, ob automatisch wiederholt wird, mit Link zur Mail); zurückgehaltene Telegram-Nachrichten, unverarbeitete Telegram-Eingänge, Web-Aktionen der letzten 24 Stunden und KI-Aufrufe der letzten Minute im Verhältnis zum Limit. |
| **Geräte** | Gekoppelte Geräte mit letzter Nutzung; einzelne oder alle abmelden. |

**Aktionen:**

- Im Kalender bzw. in Todoist anlegen, auch die bestätigte Doppelanlage
- Verwerfen
- Antworten: Freitext, bei Ja/Nein-Fragen zusätzlich als Schaltflächen
- „Ändern“ für vollständige Vorschläge
- Bearbeitung beenden
- Relevant/Irrelevant

Jede Aktion gilt genau für die angezeigte Vorschlagsversion. Nach einer Antwort
entsteht eine neue Version, die erneut bestätigt werden muss.

**Ablauf einer Aktion:**

1. Mailhelp nimmt die Aktion sofort an. Ist sie schnell erledigt, geht es direkt zurück zur Übersicht, oben steht das Ergebnis (z. B. „Angelegt.“). Dauert sie länger, erscheint kurz „Aktion läuft“, und danach geht es ebenfalls automatisch zur Übersicht. Nur bei einer bereits früher angelegten Aktion bleibt eine Seite mit „Erneut anlegen“/„Nicht erneut anlegen“ stehen.
2. Ausgeführt wird sie vom Mailhelp-Hauptthread, genau wie eine Telegram-Eingabe: vor der nächsten Mail, im Leerlauf sofort und während einer offenen Relevanzfrage.
3. Läuft gerade eine längere Mailanalyse, kann das einige Sekunden dauern.

**Zusammenspiel mit Telegram:**

- Telegram meldet angelegte Einträge und überarbeitete Vorschläge wie gewohnt.
- Verwerfen und Relevanzentscheidungen aus dem Web erscheinen dort als „🌐 Im Web: …“.
- Eine Telegram-Schaltfläche für einen bereits im Web entschiedenen Vorschlag antwortet mit „Bereits entschieden oder geändert … diese Schaltfläche ist veraltet“.

Die Seiten funktionieren auch ohne JavaScript. Das Skript ergänzt nur drei Dinge:

- **Verbindungsanzeige:** „● Verbunden“ bzw. „PC nicht erreichbar“.
- **Automatische Aktualisierung:** Die Übersicht lädt sich neu, sobald sich der Stand ändert. Getippter, noch nicht gesendeter Text wird dabei nie verworfen; dann erscheint nur „Neue Daten – bitte neu laden“.
- **Schutz vor doppeltem Absenden:** Ein Formular wird nicht doppelt gesendet.

## Einrichtung am Windows-PC

1. Einen zufälligen Schlüssel erzeugen und in `.env` eintragen:

   ```powershell
   .venv\Scripts\python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

   ```text
   MAILHELP_WEB_SECRET=<ausgegebener Wert>
   ```

2. In `config.yaml` aktivieren (Vorlage: `config.example.yaml`):

   ```yaml
   web:
     enabled: true
     host: 127.0.0.1
     port: 8765
     allowed_hosts: [127.0.0.1:8765, localhost:8765]
     session_days: 30
   ```

3. `mailhelp --check` prüft Konfiguration und Schlüssel. Danach Mailhelp starten.
4. Im Browser `http://127.0.0.1:8765` öffnen, „Code per Telegram senden“ wählen
   und den Code aus Telegram eingeben. Jede neue Kopplung meldet Telegram.

**Schneller vom Telefon:** Der Telegram-Befehl `/web` sendet einen Link zur
Anmeldeseite mit einem frischen Einmal-Code (10 Minuten gültig, für ein Gerät).
Der Code steht im Link schon im Eingabefeld; ein Tipp auf „Gerät koppeln“ genügt.
Er steht zusätzlich in der Nachricht, falls die Seite anders geöffnet wird. Ist in
`web.lan_access` aktiv, enthält der Link die aktuelle IP-Adresse des PCs im
Heimnetz. Sonst verweist er auf einen in `web.allowed_hosts` eingetragenen
Tailnet-Namen per HTTPS, und ohne beides auf `http://127.0.0.1:<port>` mit dem
Hinweis, dass er nur am PC funktioniert. Ein neuer `/web`-Code ersetzt den vorherigen; Ratenbegrenzung und
Fehlversuche zählen wie bei angeforderten Codes.

Ist der Port belegt, meldet Telegram „Weboberfläche konnte nicht … starten“ und
die Mailverarbeitung läuft ohne Weboberfläche weiter.

## Zugriff vom Telefon im eigenen WLAN

Ist das Telefon im selben WLAN wie der PC, genügt die IP-Adresse des PCs:

```yaml
web:
  enabled: true
  host: 0.0.0.0
  lan_access: true
```

`/web` sendet dann einen Link wie `http://192.168.1.144:8765/anmelden?code=…`.
Die Adresse wird bei jedem `/web` neu ermittelt, weil der Router sie ändern kann.
Angenommen werden Aufrufe über private IPv4-Adressen mit dem konfigurierten Port;
fremde Host-Namen bleiben abgewiesen.

- Windows fragt beim ersten Start, ob Python Verbindungen im Netzwerk annehmen darf:
  nur für **private Netzwerke** erlauben. Das WLAN muss in Windows als „Privat“
  eingestuft sein.
- Die Verbindung ist unverschlüsseltes HTTP. Im eigenen, vertrauenswürdigen WLAN ist
  das vertretbar; in fremden Netzen (Hotel, Café) `lan_access` nicht verwenden.
  Verschlüsselt und auch von unterwegs geht es über Tailscale (nächster Abschnitt).
- Über HTTP installiert das iPhone die App ohne Offline-Seite (Service Worker
  benötigen HTTPS); alles andere funktioniert.

## Zugriff vom iPhone über Tailscale

Der Zugriff von unterwegs läuft über [Tailscale](https://tailscale.com) im eigenen
Tailnet. Der Mailhelp-Port wird nie ins Internet geöffnet.

1. Tailscale auf PC und iPhone installieren und mit demselben Konto anmelden.
   In der Tailscale-Verwaltung „MagicDNS“ und „HTTPS Certificates“ aktivieren.
2. Am PC (PowerShell) Tailscale Serve einrichten. Die Freigabe läuft im Hintergrund
   weiter, auch nach einem Neustart:

   ```powershell
   tailscale serve --bg --https=443 http://127.0.0.1:8765
   tailscale serve status
   ```

   `tailscale serve status` zeigt die Adresse, z. B. `https://mailhelp-pc.tailnet-name.ts.net`.
3. Diesen Namen **ohne Port** in `web.allowed_hosts` ergänzen und Mailhelp neu starten:

   ```yaml
   allowed_hosts: [127.0.0.1:8765, localhost:8765, mailhelp-pc.tailnet-name.ts.net]
   ```

4. Auf dem iPhone die Adresse in Safari öffnen, über „Teilen → Zum Home-Bildschirm“
   als App installieren, **die App öffnen und darin koppeln**. Eine installierte App
   hat auf iOS eigene Cookies; eine Kopplung in Safari gilt nicht für die App.

Tailscale Serve leitet Anfragen von `127.0.0.1` weiter. Mailhelp vertraut deshalb
keinem Identitäts-Header von Tailscale; nur die Kopplung per Telegram-Code zählt.
Ein Funnel (Freigabe ins Internet) wird nicht verwendet und darf nicht eingerichtet
werden.

**Schlaf und Neustart:** Schläft der PC oder läuft Mailhelp nicht, zeigt die App
„PC nicht erreichbar“. Offline ist keine Aktion möglich, und nichts wird später
automatisch gesendet. Nach dem Aufwachen „Erneut versuchen“ wählen. Gekoppelte
Geräte bleiben über Neustarts hinweg angemeldet, bis `session_days` abläuft.

## Docker

`compose.yaml` veröffentlicht den Port ausschließlich auf `127.0.0.1:8765` des Hosts.
Im Container muss Mailhelp auf allen Schnittstellen des Containers lauschen:

```yaml
web:
  enabled: true
  host: 0.0.0.0
  allowed_hosts: [127.0.0.1:8765, localhost:8765]
```

Tailscale läuft auf dem Host, nicht im Container.

## Sicherheit

- Anmeldung nur per einmaligem Code (8 Ziffern, 10 Minuten gültig, an den
  anfordernden Browser gebunden, höchstens 5 Fehlversuche je Code, höchstens
  3 Codes in 10 Minuten, Sperre nach 20 Fehlversuchen pro Stunde).
- Sitzungen: zufälliges Token, gespeichert nur als Hash (`web-sessions.json`);
  Cookie `HttpOnly`, `SameSite=Strict`, über Tailscale `Secure`. Abmelden einzeln,
  alle im Web oder per Telegram mit `/web_abmelden`. Eine Aktion wird nur
  ausgeführt, solange ihre Sitzung noch besteht.
- Jede schreibende Anfrage braucht das CSRF-Token ihrer Sitzung und Formulardaten.
  Fremde `Host`-Header werden abgewiesen (Schutz gegen DNS-Rebinding), es gibt kein
  CORS, und Anfragen sind auf 16 KB begrenzt.
- Content-Security-Policy ohne Inline-Skripte, `X-Frame-Options: DENY`,
  `Referrer-Policy: no-referrer`, `Cache-Control: no-store` für alle Daten.
- Mailinhalte werden escaped. Links aus Mails sind nicht klickbar; nur ein
  `https`-Videolink und der Link eines von Mailhelp angelegten Eintrags sind es.
- Der Service Worker speichert nur `offline.html`, `app.css` und die Icons.
- Das Zugriffsprotokoll enthält Methode, Pfad ohne Query-String, Status und Dauer,
  keine Mailinhalte, Codes oder Tokens.

## Neue Zustandsdateien

| Datei | Inhalt | Aufbewahrung |
| --- | --- | --- |
| `command-inbox.json` | Web-Aktionen mit Status und kurzem Ergebnis (ohne Mailinhalt) | erledigte Einträge 1 Tag |
| `web-sessions.json` | gekoppelte Geräte, Token-Hashes | bis Ablauf oder Abmeldung |
| `web-pairing.json` | offene Kopplungscodes als HMAC, Zähler für Ratenbegrenzung | 10 Minuten bzw. 1 Stunde |

Eine nach einem Absturz als `running` gespeicherte Web-Aktion wird beim Neustart
nicht erneut ausgeführt, sondern gegen den aktuellen Stand abgeglichen. Ist ihre
Wirkung sichtbar, gilt sie als erledigt; sonst wird um erneutes Auslösen gebeten.
`mailhelp --clear` löscht auch diese Dateien.

## Tests

- `python -m pytest`: Gesamtsuite mit 100 % Zeilen- und Branch-Abdeckung.
- `python -m pytest ui_tests --no-cov -p no:cacheprovider`: Browsertests. Voraussetzung ist `pip install playwright==1.62.0` sowie installiertes Google Chrome.
  - Startet den echten Webserver mit synthetischen Daten und einem simulierten Mailhelp-Hauptthread.
  - Bedient jede Seite im Desktop-Format (1366 × 900) und im iPhone-Format (390 × 844, Touch).
  - Speichert Screenshots in `.test-tmp/ui-screens`.
  - Prüft horizontalen Überlauf, Tippflächen (mindestens 40 px), Eingabeschrift (mindestens 16 px, kein Zoom unter iOS), Labels, Alternativtexte, Kontraste (WCAG AA) und Konsolen- bzw. CSP-Fehler.
  - Misst die Blockabdeckung von `app.js` und `sw.js` und scheitert unter 100 %.

  Die CI führt die Browsertests in einem eigenen Job aus und hängt die Screenshots an.

## Einschränkungen

- Keine Web-Push-Benachrichtigungen; Telegram bleibt Benachrichtigungskanal.
- Genau eine berechtigte Person (wie `telegram.user_id`), kein Mehrbenutzerbetrieb.
- Bereits gesendete Telegram-Schaltflächen werden nach einer Web-Entscheidung nicht
  entfernt, sondern beim Drücken als veraltet gemeldet.
- Die projektverantwortliche Person hat am 11. Oktober 2026 die autorisierte,
  versionsbezogene Bestätigung über Telegram oder Web ausdrücklich freigegeben.
  Bearbeiten und Speichern ersetzen keine Bestätigung der neuen Version.
