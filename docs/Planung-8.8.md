# Mailhelp 8.8 – Kundenmodus-OAuth vervollständigen und Demo an Kundenmodus angleichen

**Stand:** 27. November 2026. **Status:** In Umsetzung; AP1–AP4 mit 8.8.1–8.8.4 umgesetzt
([Release 8.8](Release-8.8.md)). Noch keine Änderung an laufenden Serverinstanzen.

**Zielversion:** 8.8, erste Auslieferung 8.8.1; weitere Commits mit
fortlaufenden Patchversionen gemäß [Entwicklungsregeln](../AGENTS.md).

**Grundlagen:** [Entwicklungsregeln](../AGENTS.md),
[Spezifikation](../Mailhelp-Projektspezifikation.md),
[Planung 7.1](Planung-7.1.md),
[Planung 8.0](Planung-8.0.md),
[Planung 8.2](Planung-8.2.md),
[Planung 8.7](Planung-8.7.md),
[Betrieb](Betrieb.md).

Dieser Plan ändert keine Schreibautorisierung für Kalender oder Aufgabenlisten.
Jeder Schreibzugriff erfordert weiterhin eine gültige, erneut geprüfte Sitzung,
CSRF-Schutz, Versionsprüfung und einen Idempotenzschlüssel.

## 1. Ausgangslage und Befunde

Ein Codeabgleich der aktuellen Berechtigungsregeln am 26.11.2026 zeigte vier
strukturelle Lücken:

1. **Unvollständige gehostete OAuth-Routen im Kundenmodus (`permissions.py`)**:
   - In `src/mailhelp/web/permissions.py` gibt `CUSTOMER_ROUTES` zwar
     `/einstellungen/zielprofile`, `/einstellungen/postfaecher`,
     `/auth/(google|microsoft|notion)(/.*)?` und
     `/einrichtung/(google|microsoft|notion)(/.*)?` frei.
   - Die tatsächlich registrierten gehosteten OAuth-Routen fehlen jedoch in
     `CUSTOMER_ROUTES`:
     - `hosted_google_site.py`: `/google/verbinden`, `/google/kalender`, `/google/trennen`
     - `hosted_targets_site.py`: `/microsoft/verbinden`, `/microsoft/ziele`,
       `/microsoft/trennen`, `/notion/verbinden`, `/notion/ziele`, `/notion/trennen`
     - `mailbox_oauth_site.py`: `/postfach/oauth*`, `/einrichtung/postfach/abschluss`
     - `oauth_site.py`: `/auth/status/<id>`
   - Im aktivierten Kundenmodus (`customer_mode: true`) blockiert der
     Deny-by-Default-Guard in `MailhelpSite.signed_in()` diese Routen mit
     HTTP 403 (`operator_only`), und `customer_links()` entfernt die zugehörigen
     Links aus den Kundenansichten.

2. **Freigegebene persönliche Kunden-Einstellungen ohne UI-Zugang**:
   - In `configuration.py` sind `language`, `timezone`, `personal_info`,
     `event_defaults.{video_duration_minutes,in_person_duration_minutes}`,
     `briefings.*`, `drafts.*`, `smart_reply`, `auto_draft` sowie die
     Kalendererinnerung für Profil 1 (`targets.calendar_reminder_enabled`,
     `targets.calendar_reminder_minutes`) bereits als `CUSTOMER_FIELDS` erlaubt.
   - Da `POST /einstellungen/speichern` für Kunden gesperrt ist (HTTP 403) und
     `/einstellungen/zielprofile` nur Zusatzprofile ab ID 2 pflegt, gibt es im
     Kundenmodus derzeit keine Oberfläche, um diese eigenen Werte zu ändern.

3. **Keine eigene lesende Verbindungsprüfung für Kunden**:
   - Da `/status` und `/diagnose` für Kunden gesperrt sind, können Kunden bei
     abgelaufenen OAuth-Tokens oder geänderten IMAP-Passwörtern ihre eigenen
     Postfächer und Zielprofile nicht selbst gezielt lesend prüfen.

4. **Demo-Modus (`--demo`) entspricht noch dem Betreiber- statt dem Kundenmodus**:
   - `DemoSite` (`src/mailhelp/web/demo_site.py`) schützt Routen bisher über eine
     Negativliste (`BLOCKED`), während das dahinterliegende Besucher-`MailhelpSite`
     im Selbstbetriebs-/Betreiber-Layout läuft (`CUSTOMER_VIEW` nicht aktiv).
   - Dadurch erreichen Demo-Besucher Betreiber-Ansichten wie `/status`,
     `/abgleich` und `/auswertung`, die Kunden im Produktivbetrieb gar nicht
     sehen, während `GET /einstellungen` nicht die reduzierte Kunden-Übersicht
     (`customer_settings.py`) zeigt und `/verbrauch` fehlt.
   - Zudem fehlen neuere Pfade (wie `/google/*`, `/microsoft/*`, `/notion/*`,
     `/postfach/oauth*`, `/dienst/*`) in der Demo-Negativliste, und
     `POST /einstellungen/speichern` antwortet mit HTTP 503 statt konsistent mit
     HTTP 403.

## 2. Ziel und Abnahme aus Nutzersicht

### 2.1 Kundenmodus (`customer_mode: true`)
- Kunden können ihre eigenen gehosteten Verbindungen für Google Kalender,
  Outlook/Microsoft To Do, Notion und Postfach-OAuth vollständig starten,
  auswählen, übernehmen und trennen – ohne HTTP 403.
- Kunden erhalten eine eigene Unterseite **`/einstellungen/allgemein`**, auf der
  sie ihre bereits in `CUSTOMER_FIELDS` freigegebenen persönlichen Werte
  (`language`, `timezone`, `personal_info`, `event_defaults.*`, `briefings.*`,
  `drafts.*`, `smart_reply`, `auto_draft` sowie die Kalendererinnerung für
  Profil 1: `targets.calendar_reminder_enabled`, `targets.calendar_reminder_minutes`)
  mit Sitzungs-, CSRF-, Konfigurationsrevisions- und Idempotenzprüfung speichern
  können – ohne den Betreiber-Editor zu öffnen.
- Sobald gespeicherte Änderungen vorliegen, die erst nach einem Neustart wirken,
  zeigt ein **generisches, seitenübergreifendes Banner-System** auf **allen**
  Ansichten einen deutlichen Hinweis samt direktem Link zu
  **`/einstellungen/neustarten`**. Dafür wird der kontrollierte Neustart
  (`GET/POST /einstellungen/neustarten`, mit Bestätigung und CSRF) auch für
  Kundensitzungen freigegeben, während `/einstellungen/beenden` weiterhin
  strikt dem Betreiber vorbehalten bleibt.
- Kunden können über eine geheimnisfreie Aktion *„Eigene Verbindungen prüfen“*
  auf `/einstellungen/postfaecher` und `/einstellungen/zielprofile` ausschließlich
  ihre eigenen Postfächer und Zielprofile lesend testen (gedrosselt gegen
  Doppelklicks, mit klaren Timeouts, ohne KI-Anbieter, Telegram-Bot-Interna,
  `.env`-Details oder Systemmetriken offenzulegen).
- Alle Betreiber-Ansichten (`/status`, `/abgleich`, `/auswertung*`, `/einrichtung*`,
  `/diagnose*`, `/einstellungen/zugangsdaten*`, `/einstellungen/iserv*`,
  `/einstellungen/beenden`, `/dienst/*`, `POST /einstellungen/speichern`)
  bleiben für Kundensitzungen strikt gesperrt (HTTP 403).
- Kein generischer `.env`-Zugangsdaten-Editor und keine Betreiber-Einstellungen
  werden für Kunden freigegeben.

### 2.2 Demo-Modus (`--demo`) entspricht dem Kundenmodus
- Die öffentliche Demo präsentiert exakt die **Kundenoberfläche**:
  - gleiche Hauptnavigation wie im Kundenmodus (`CUSTOMER_VIEW` aktiv), ohne
    Betreiber-Punkte (`/status`, `/abgleich`, `/auswertung` → HTTP 403),
  - `GET /einstellungen` zeigt die reduzierte Kunden-Übersicht: demo-verfügbare
    Bereiche sind verlinkt, während in der Demo gesperrte Kundenbereiche
    (Postfächer, Zielprofile, Benachrichtigungen, Geräte, Web-Passwort) als
    klare, schreibfreie Info-Karten ohne 403-Links erklärt werden,
  - `GET /verbrauch` zeigt eine schreibfreie Beispiel-Verbrauchsansicht in
    Punkten (ohne Einkaufspreise oder Wechselkurse),
  - alle Links in der Demo führen nur auf tatsächlich erreichbare Demo-Seiten
    (keine Links auf 403-Routen).
- Die Demo nutzt ein **Deny-by-Default-Routenmodell**, abgeleitet aus
  `CUSTOMER_ROUTES` abzüglich demo-gesperrter Funktionen (zuzüglich
  `/demo/neu-starten` und öffentlicher Start-/Sprachrouten).
- Alle externen, kontobezogenen, schreibenden oder modellaufrufenden Routen
  bleiben in der Demo strikt blockiert (HTTP 403), darunter OAuth, Postfächer,
  Zielprofile, Zugangsdaten, Push, Geräte, Passwort, Hilfe-Chat, Berichte,
  Entwürfe, Nachanalyse, echte Lernläufe und das Speichern von Einstellungen,
  Themen oder Absenderregeln.
- Isolation, 2-Stunden-Sitzung, max. 50 parallele Besucher, Rate-Limits,
  `demo_generation` und rein simulierte Vorschlagbestätigungen bleiben unverändert.

## 3. Abgrenzung

Nicht Bestandteil von Version 8.8 sind:

- neue Benutzerrollen über `customer` und `operator` hinaus (kein Mehrbenutzer-RBAC
  innerhalb einer Kundeninstanz)
- Freigabe von `iserv`, `.env`-Zugangsdaten, `prompts.yaml`, `operator.yaml`
  oder technischen Betriebs-Einstellungen für Kunden
- echte OAuth-Verbindungen, E-Mail-Abrufe, externe Schreibzugriffe oder
  LLM-Aufrufe in der Demo
- Änderungen an der zentralen `inboxstride-auth`-Komponente

## 4. Arbeitspakete

### AP1 – Gehostete OAuth-Routen im Kundenmodus vervollständigen
- Alle in `hosted_google_site.py`, `hosted_targets_site.py`,
  `mailbox_oauth_site.py` und `oauth_site.py` registrierten Kunden-OAuth-Routen
  exakt prüfen und eng gefasst in `CUSTOMER_ROUTES`
  (`src/mailhelp/web/permissions.py`) aufnehmen:
  - Google gehostet (`/google/verbinden`, `/google/kalender`, `/google/trennen`
    sowie ggf. zugehörige Auswahl-/Abschlusspfade)
  - Microsoft gehostet (`/microsoft/verbinden`, `/microsoft/ziele`, `/microsoft/trennen`)
  - Notion gehostet (`/notion/verbinden`, `/notion/ziele`, `/notion/trennen`)
  - Postfach-OAuth (`/postfach/oauth(?:/.*)?`, `/einrichtung/postfach/abschluss`)
  - OAuth-Statusabfrage (`/auth/status/<id>` mit exaktem ID-Muster)
- Sicherstellen, dass jeder Handler weiterhin aktive Sitzung, CSRF,
  Entwurfs-/Konfigurationsrevision und `hosted_auth.enabled` prüft und
  keine Betreiber-Konfiguration oder Geheimnisse preisgibt.
- Keine unbeabsichtigte Öffnung von `/einrichtung` oder `/einrichtung/speichern`
  für Kunden.

### AP2 – Kunden-Unterseite `/einstellungen/allgemein` (inkl. Profil-1-Kalendererinnerung)
- Neue dedizierte Route `GET/POST /einstellungen/allgemein` in
  `CUSTOMER_ROUTES` aufnehmen und als ersten Bereich in `customer_settings.py`
  verlinken.
- Das Formular bietet ausschließlich die bereits durch `CUSTOMER_FIELDS`
  erlaubten persönlichen Einstellungen an:
  - Sprache (`language`), Zeitzone (`timezone`), persönliche Angaben (`personal_info`)
  - Standard-Termindauern (`event_defaults.video_duration_minutes`,
    `event_defaults.in_person_duration_minutes`)
  - Kalendererinnerung für das Standard-Zielprofil (`targets.calendar_reminder_enabled`,
    `targets.calendar_reminder_minutes`, `0`–`1440`)
  - Entwürfe & Briefings (`drafts.enabled`, `drafts.folder`, `smart_reply`,
    `auto_draft`, `briefings.*`, `daily_briefing.include_*`)
- Speichern erfolgt über ein eigenes, strikt auf diese Kundenfelder begrenztes
  Handler-Whitelist-Verfahren (mit Sitzungs-, CSRF-, Revisions- und
  Idempotenzprüfung sowie erneuter Prüfung in `ConfigurationService.permitted()`).
  `POST /einstellungen/speichern` bleibt für Kunden weiterhin gesperrt (HTTP 403).
- Beim Speichern von `language` wird wie bisher das Sprach-Cookie
  `mailhelp_lang` synchron aktualisiert; das Speichern löst niemals Schreibzugriffe
  auf Kalender oder Aufgabenlisten aus.
- Gespeicherte Änderungen, die erst nach einem Neustart greifen, werden klar als
  neustartpflichtig markiert und aktivieren den seitenübergreifenden
  Neustart-Hinweis (siehe AP3).

### AP3 – Generisches seitenübergreifendes Banner-System und Neustart-Hinweis
- **Bestandsaufnahme**: Bisher gibt es kein generisches seitenübergreifendes
  Hinweis-System (`connection_warnings` wird nur auf Startseite/Mail-Liste
  eingeblendet, der bisherige Hinweis zu noch nicht aktiven Änderungen nur in
  `settings_pages.py:529-533`). `layout()` in `src/mailhelp/web/pages.py`
  nutzt jedoch bereits `ContextVar`s aus `site.py` (`OPEN_DECISIONS`,
  `CUSTOMER_VIEW`, `HELP_BUTTON`), die auf jeder HTML-Seite wirken.
- **Generischer Baustein (`src/mailhelp/web/banners.py`)**:
  - Unveränderliche Datenstruktur `SystemBanner(id, severity, text, action_href, action_label)`
    sowie `PAGE_BANNERS: ContextVar[tuple[SystemBanner, ...]]`, zentral befüllt
    in `MailhelpSite` (`site.py`) und gerendert in `layout()` (`pages.py`) am
    Beginn von `<main id="inhalt">` (`role="status"` bzw. `role="alert"`).
  - Zielgruppen-/Link-Sicherheit: Banner-Links werden gegen die Berechtigungen
    der aktuellen Sitzung geprüft (`customer_may_link()` bzw. Demo-Filter), so
    dass niemals Betreiber-Links im Kunden- oder Demo-Modus erscheinen.
  - Erweiterbar für künftige Anwendungsfälle (z. B. Kontingent-/Punktehinweise,
    Wartungsankündigungen, ablaufende Verbindungen/Zertifikate).
- **Erster Anwendungsfall – Persistenter Neustart-Hinweis**:
  - Sobald gespeicherte Konfigurationsänderungen vorliegen, die erst nach einem
    Neustart aktiv werden, bleibt das Banner auf **allen** Ansichten sichtbar
    und verlinkt direkt auf `/einstellungen/neustarten` (mit eindeutigem Text in
    DE & EN, z. B. *„Gespeicherte Änderungen werden erst nach einem Neustart
    aktiv.“* + Link *„Mailhelp neu starten“*).
  - Nach erfolgtem Neustart verschwindet das Banner automatisch.
  - `GET/POST /einstellungen/neustarten` (kontrollierter Neustart mit
    Bestätigung, Sitzung und CSRF) wird in `CUSTOMER_ROUTES` und
    `Lifecycle.request_restart()` auch für Kundensitzungen freigegeben;
    `/einstellungen/beenden` bleibt strikt `operator_only` (403); in der Demo
    bleiben beide 403.

### AP4 – Lesende Kunden-Verbindungsprüfung („Eigene Verbindungen prüfen“)
- Auf `/einstellungen/postfaecher` und `/einstellungen/zielprofile` eine
  geheimnisfreie, lesende Prüfaktion (z. B. `POST /einstellungen/verbindungen/pruefen`,
  in `CUSTOMER_ROUTES` freigegeben) bereitstellen.
- Die Prüfung testet ausschließlich die konfigurierten **eigenen Postfächer**
  und **eigenen Zielprofile** (Kalender-/Aufgabenzugänge) mit `check_access()`
  (rein lesend, keine Schreibaktion, keine Anlage).
- **Drosselung & Zeitgrenzen**:
  - Schutz gegen Doppelklicks und schnelle Wiederholungen durch ein kurzes
    Cooldown je Sitzung (z. B. 15 Sekunden; wiederholte Klicks während des
    Cooldowns liefern eine klare, freundliche Hinweismeldung bzw. HTTP 429)
    sowie Einzelausführung unter Sperre ohne Parallelstau.
  - Begrenzte Einzel- und Gesamt-Timeouts je Prüfung, damit eine langsam
    antwortende Gegenstelle niemals die Weboberfläche blockiert; Timeouts werden
    sauber als *„vorübergehend nicht erreichbar“* ausgewiesen.
- Die Ergebnisdarstellung nennt je eigenem Postfach/Zielprofil nur Status
  (erreichbar / Anmeldung erneuern / vorübergehend nicht erreichbar) und
  hilfreichen nächsten Schritt – niemals KI-Anbieter, Telegram-Bot-Interna,
  Tokens, Host-Pfade, `.env`-Namen oder Betreiber-Systemmetriken.
- Im Demo-Modus ist diese Route gesperrt (HTTP 403) und der Button wird nicht
  angezeigt.

### AP5 – Demo-Modus auf Deny-by-Default und Kundenansicht umstellen
- `src/mailhelp/web/demo_site.py` und `src/mailhelp/app/demo.py`:
  - Für Demo-Besuchersitzungen die Kundenansicht aktivieren (`CUSTOMER_VIEW` /
    Kundenmodus-Navigation und Kunden-Einstellungsübersicht).
  - Route-Prüfung von einer offenen Negativliste auf **Deny-by-Default**
    umstellen: erlaubt sind ausschließlich definierte `DEMO_ROUTES` (echte
    Teilmenge von `CUSTOMER_ROUTES` plus `/demo/neu-starten`) und `PUBLIC`.
  - Jede nicht freigegebene Route – einschließlich Betreiber-Routen (`/status`,
    `/abgleich`, `/auswertung*`, `/dienst/*`, `/einrichtung*`, `/diagnose*`),
    OAuth-Routen (`/google/*`, `/microsoft/*`, `/notion/*`, `/postfach/oauth*`,
    `/auth/*`), `/einstellungen/neustarten`, `/einstellungen/verbindungen/pruefen`
    sowie schreibender Konfigurationsrouten (`POST /einstellungen/*`,
    `POST /themen/*`, `POST /lernen*`) – liefert konsistent **HTTP 403**.
- **Deterministische Datenquelle für `GET /verbrauch` in der Demo**:
  - Fester, rein synthetischer Beispieldatensatz (z. B. im Demo-Modul als
    unveränderliche Tabelle von Beispielpunkten nach Tag und Verarbeitungsschritt),
    **ohne** `MetricsRecorder`, **ohne** USD-Einkaufspreise oder Wechselkurse
    und identisch/deterministisch in Deutsch und Englisch.
- `GET /einstellungen` in der Demo über `customer_settings.py` rendern:
  - Demo-verfügbare Bereiche (z. B. Themen, Lernen, Verbrauch) sind aktiv
    verlinkt.
  - In der Demo gesperrte Kundenbereiche (Allgemein, Postfächer, Zielprofile,
    Absender-Regeln, Benachrichtigungen, Geräte, Web-Passwort) erscheinen als
    klare, schreibfreie **Info-Karten** mit dem Hinweis *„In deiner eigenen
    Mailhelp-Instanz verfügbar – in der Demo deaktiviert“* (ohne Links auf
    403-Routen), damit Interessenten den vollen Funktionsumfang des
    Kundenmodus sehen.

### AP6 – Link-Konsistenz und Zweisprachigkeit (DE & EN)
- Link-Filter für Demo-Antworten so anbinden, dass keine `<a>`-Links auf
  gesperrte Routen (403) in der gerenderten Demo-HTML-Ausgabe erscheinen.
- Alle neuen oder angepassten Texte (Kunden-Unterseite `/einstellungen/allgemein`,
  generisches Banner-System / Neustart-Hinweis, Verbindungsprüfung inkl.
  Cooldown-/Timeout-Meldungen, Demo-Info-Karten, Demo-Verbrauch) in Deutsch
  und Englisch (`src/mailhelp/i18n/en.py`) pflegen.
- Bestehende Demo-Unit- und Browser-Tests (`tests/web/test_demo*.py`,
  `ui_tests/test_ui_demo*.py`) prüfen und dort anpassen, wo bisher alte
  Betreiber-Routen in der Demo vorausgesetzt wurden.

### AP7 – Automatisierte Tests, Paritäts- & Link-Crawler-Tests
- **Kundenmodus-OAuth-, Einstellungs- & Banner-Regressionstests**:
  - Vor dem Fix schlägt der Zugriff einer Kundensitzung auf die gehosteten
    OAuth-Routen mit HTTP 403 fehl; nach dem Fix funktionieren sie mit
    gültiger Sitzung, CSRF und `hosted_auth.enabled`.
  - `/einstellungen/allgemein` speichert erlaubte Kundenfelder (inkl.
    Profil-1-Kalendererinnerung und Sprach-Cookie) und weist Betreiber-Felder
    strikt ab; kein Schreibzugriff auf Kalender/Aufgaben beim Speichern.
  - Generisches Banner-System (`banners.py`): Nach dem Speichern einer
    neustartpflichtigen Änderung erscheint das Neustart-Banner auf allen
    Ansichten (`/`, `/mails`, `/themen`, `/einstellungen`, `/verbrauch`) mit
    funktionierendem Link zu `/einstellungen/neustarten` und verschwindet nach
    dem Neustart; `/einstellungen/beenden` bleibt für Kunden 403.
  - `POST /einstellungen/verbindungen/pruefen` prüft nur eigene Postfächer und
    Zielprofile lesend, drosselt schnelle Wiederholungen (Cooldown), behandelt
    Timeouts sauber, gibt keine Betreiber-Interna oder Geheimnisse aus und
    erfordert gültige Sitzung + CSRF.
  - Konsistenztest, der alle registrierten gehosteten OAuth-Routen gegen
    `CUSTOMER_ROUTES` prüft, damit keine künftige Kunden-OAuth-Route vergessen
    wird.
- **Automatisierter Paritäts- und Link-Crawler-Test (Kundenmodus & Demo, DE & EN)**:
  - Läuft alle erreichbaren Seiten im **Kundenmodus** und im **Demo-Modus** in
    Deutsch und Englisch ab und verifiziert:
    - kein einziger gerenderter interner Link führt auf HTTP 403 oder 404,
    - keine Betreiber-Informationen (USD-Einkaufspreise, Wechselkurse,
      `.env`-Pfade, Modellnamen, Betreiber-Navigationspunkte) erscheinen im
      Kunden- oder Demo-HTML,
    - die Invariante `DEMO_ROUTES ⊆ CUSTOMER_ROUTES` gilt strikt.
- **Demo-Schutztests**:
  - Betreiber-Routen (`/status`, `/abgleich`, `/auswertung`, `/dienst/neu-laden`,
    `/einrichtung`, `/diagnose`) sowie alle OAuth-, Neustart-,
    Verbindungsprüfungs- und Schreibrouten liefern in der Demo HTTP 403.
  - Demo-Besucher sehen Kunden-Navigation, Kunden-`GET /einstellungen` (mit
    Info-Karten) und deterministischen Beispiel-Verbrauch unter `GET /verbrauch`
    in DE und EN; simulierte Entscheidungen, `/demo/neu-starten`, Rate-Limits
    und `demo_generation` bleiben intakt.
- **100 % Zeilen- und Branch-Abdeckung** für sämtlichen eigenen Code.

### AP8 – Dokumentation, Release und Vollprüfung
- [Betrieb.md](Betrieb.md) (Demo-Abschnitt), [Bedienung.md](Bedienung.md),
  [Ziele-einrichten.md](Ziele-einrichten.md), [Web-Einstellungen.md](Web-Einstellungen.md)
  sowie deren englische Fassungen unter `docs/en/` aktualisieren und
  `devtools.help_index` neu bauen.
- `pyproject.toml`, `src/mailhelp/__init__.py` (`8.8.1`), `CHANGELOG.md`,
  `README.md`, `docs/README.md`, `docs/Release-8.8.md` und Status in
  `docs/Planung-8.8.md` aktualisieren.
- Vollständige Python-Prüfung:
  `python -m devtools.check full --workers 12`
- Anschließend getrennte Browserprüfung:
  `python -m pytest ui_tests -n 6 --dist worksteal --no-cov`

## 5. Abnahmeszenarien

| Nr. | Szenario | Erwartung |
| --- | --- | --- |
| 1 | Kundensitzung öffnet `/google/verbinden`, `/google/kalender`, `/google/trennen` | Kein 403; gehosteter Google-OAuth-Ablauf funktioniert mit Sitzung & CSRF |
| 2 | Kundensitzung öffnet `/microsoft/*`, `/notion/*`, `/postfach/oauth*`, `/auth/status/<id>` | Kein 403; gehostete Ziel- und Postfach-OAuth-Abläufe funktionieren |
| 3 | Kundensitzung ändert auf `/einstellungen/allgemein` Sprache, Zeitzone, Termindauer und Profil-1-Kalendererinnerung | Erfolgreich gespeichert (CSRF + Revision), Sprach-Cookie synchronisiert, kein Kalender-Schreibzugriff |
| 4 | Nach Speichern neustartpflichtiger Änderungen wechselt der Nutzer zwischen beliebigen Ansichten (`/`, `/mails`, `/themen`, `/verbrauch`) | Seitenübergreifendes Banner bleibt überall sichtbar mit direktem Link zu `/einstellungen/neustarten` und verschwindet nach Neustart |
| 5 | Kundensitzung nutzt `/einstellungen/neustarten` vs. `/einstellungen/beenden` | Kontrollierter Neustart funktioniert mit Bestätigung & CSRF; `/einstellungen/beenden` bleibt HTTP 403 |
| 6 | Kundensitzung sendet Betreiber-Feld an `/einstellungen/allgemein` oder ruft `POST /einstellungen/speichern` auf | Strikt abgewiesen (HTTP 400/403); keine Änderung an Betreiber-Einstellungen |
| 7 | Kundensitzung startet „Eigene Verbindungen prüfen“ (`POST /einstellungen/verbindungen/pruefen`), inkl. Doppelklick und Timeout | Prüft nur eigene Postfächer & Zielprofile lesend; Cooldown bremst Doppelklicks; Timeout liefert saubere Statusmeldung ohne Hänger; keine KI-/System-/Secret-Details |
| 8 | Kundensitzung ruft Betreiber-Routen (`/status`, `/abgleich`, `/auswertung`, `/einrichtung`, `/einstellungen/zugangsdaten`, `/dienst/neu-laden`) auf | Weiterhin HTTP 403 (`operator_only`) |
| 9 | Demo-Besucher öffnet `/`, `/offen`, `/mails`, `/verlauf`, `/briefing`, `/lernen`, `/themen`, `/verbrauch`, `/einstellungen` | Kunden-Navigation aktiv; deterministischer Beispiel-Verbrauch in Punkten; `GET /einstellungen` zeigt Info-Karten ohne 403-Links (DE & EN) |
| 10 | Demo-Besucher ruft Betreiber-, OAuth-, Neustart-, Verbindungsprüfungs- oder Schreibrouten direkt auf | Konsistent HTTP 403 („In der Demo nicht verfügbar“), kein 503 |
| 11 | Paritäts- & Link-Crawler-Test (Kundenmodus & Demo, DE & EN) | Kein Link auf 403/404, keine Betreiber-Interna/Preise im HTML, `DEMO_ROUTES ⊆ CUSTOMER_ROUTES` |
| 12 | Vollprüfung & Browser-Suite | `devtools.check full --workers 12` (100 % Zeilen-/Branch-Abdeckung) und `ui_tests` bestehen |

## 6. Abwärtskompatibilität und Rückkehrverfahren

- Keine Schemaänderung an `config.yaml`, `operator.yaml` oder Zustandsdateien;
  ein Rückwechsel auf Version 8.7.x ist über Image-/Compose-Rollback ohne
  Datenmigration möglich.
- Im Selbstbetrieb (ohne `operator.yaml`) bleiben alle Betreiber-Ansichten
  unverändert nutzbar; das generische Neustart-Banner verbessert auch dort die
  Sichtbarkeit noch nicht aktiver Änderungen über alle Seiten hinweg.
- Beim späteren Deployment auf `demo.inboxstride.de` berücksichtigen, dass
  `/status`, `/abgleich` und `/auswertung` in der Demo künftig HTTP 403 liefern;
  Rauchprüfungen testen stattdessen die Kundenrouten (`/`, `/offen`, `/verbrauch`,
  `/einstellungen`).
