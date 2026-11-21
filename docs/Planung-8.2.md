# Mailhelp 8.2 – Geführtes Self-Service-Onboarding und zentrale Ziel-OAuths

**Stand:** 20. November 2026. **Status:** In Umsetzung (Arbeitsversion 8.2.1); Nachweise und offene
Anbieterfreigaben im [Releasebericht 8.2](Release-8.2.md).

**Zielversion:** 8.2, erste Auslieferung 8.2.1; weitere Commits mit fortlaufenden Patchversionen gemäß [Entwicklungsregeln](../AGENTS.md).

**Grundlagen:** [Entwicklungsregeln](../AGENTS.md), [Spezifikation](../Mailhelp-Projektspezifikation.md), [Planung 8.0](Planung-8.0.md), [Planung 8.1](Planung-8.1.md), [Ersteinrichtung](Ersteinrichtung.md), [Ziele einrichten](Ziele-einrichten.md).  
Dieser Plan autorisiert weder eine Produktionsumstellung noch neue Betreiberfreigaben.

---

## 1. Ziel und Abnahme aus Nutzersicht

Nach **8.0** (Google-Konten über Inboxstride) und **8.1** (einfache Postfacheinrichtung mit Anbietervorlagen und Postfach-OAuth2) schließt **8.2** die verbleibenden Lücken zum vollständigen Self-Service-Einstieg:

1. **Zentrale OAuth-Anbindung auch für Microsoft-Ziele und Notion:**  
   Nutzer einer freigeschalteten Inboxstride-Instanz verbinden neben Google (8.0) auch **Microsoft Outlook / Microsoft To Do** sowie **Notion** über denselben „Mit … verbinden“-Fluss des zentralen OAuth-Dienstes. Eigene App-Registrierungen, Client-IDs, Client-Secrets oder Token-Kopien in `.env` entfallen.
2. **Geführtes 3-Schritte-Startonboarding (`/onboarding`):**  
   Bei der allerersten Anmeldung an einer noch unkonfigurierten Instanz führt ein schlanker Assistent durch die Ersteinrichtung – ohne technisches Vorwissen, ohne SSH und jederzeit unterbrech- oder überspringbar:
   - **Schritt 1 – Postfach verbinden:** E-Mail-Adresse eingeben, erkannten Anbieter bestätigen, per OAuth2 oder App-Passwort verbinden und Verbindung sofort testen (auf Basis von 8.1).
   - **Schritt 2 – Zielsystem verbinden:** Kalender- oder Aufgabenziel wählen (Google, Microsoft, Notion, Todoist oder CalDAV), zentral autorisieren und konkretes Ziel (Kalender, Aufgabenliste oder Notion-Datenquelle) auswählen.
   - **Schritt 3 – Themen wählen & Probelauf im Testmodus:** Passendes Starter-Themenprofil wählen (z. B. *Privat & Familie*, *Beruf & Projekte*, *Verein & Schule*) und die **neuesten 5 bis 10 Mails einmalig im Testmodus** auswerten lassen. Erst wenn der Nutzer die erzeugten Beispielvorschläge gesehen hat und ausdrücklich bestätigt (*„Produktiven Betrieb aktivieren“*), wird der Echtbetrieb freigeschaltet.

---

## 2. Ausgangsstand und Abgrenzung zu 8.0 und 8.1

| Baustein | Stand vor 8.2 | Neu in 8.2 |
| :--- | :--- | :--- |
| **Google Kalender & Tasks (OAuth)** | Zentraler Inboxstride-OAuth-Dienst über mTLS (`external/hosted_oauth.py`, `web/oauth_site.py`). | Bleibt unverändert als Referenzmuster. |
| **Postfach-Einrichtung (IMAP & OAuth2)** | Anbietervorlagen + Google-/Microsoft-OAuth2 für IMAP (8.1). | Direkt in Schritt 1 des Onboardings eingebettet. |
| **Microsoft Kalender / To Do & Notion** | Erfordern im gehosteten Betrieb eigene OAuth-App-Daten in `.env` bzw. manuelle Secrets (`external/microsoft.py`, `external/notion_oauth.py`). | Nutzung des zentralen OAuth-Dienstes über Provider-Erweiterung (`microsoft_targets`, `notion`), analog zu Google in 8.0. |
| **Ersteinrichtung (`/einrichtung`)** | Technische Schrittübersicht mit Verweisen auf Zugangsdaten, Diagnose, `prompts.yaml` und Entwurfsübernahme (`web/setup_site.py`). | Bleibt als Expertenansicht erhalten; unkonfigurierte Instanzen starten auf `/onboarding` mit klarem 3-Schritte-Pfad. |

Der lokale Selbstbetrieb unter Windows 11 und Docker/Linux ohne zentralen Inboxstride-Dienst bleibt vollständig unterstützt: Dort greifen bei Bedarf weiterhin die lokalen OAuth- bzw. Token-Wege.

---

## 3. Teil A: Zentrale Ziel-OAuths (Microsoft & Notion)

### 3.1 Erweiterung des zentralen OAuth-Dienstes
Der in 8.0 eingeführte zentrale OAuth-Dienst wird provider-fähig verallgemeinert, ohne das Vertrauensmodell zu verändern:

- **Unterstützte Provider im zentralen Dienst:**
  - `google` (8.0 – Kalender & Google Tasks)
  - `microsoft` (8.2 – Outlook-Kalender & Microsoft To Do über Microsoft Graph `Calendars.ReadWrite`, `Tasks.ReadWrite`, `offline_access`)
  - `notion` (8.2 – Notion OAuth-Verbindung für Seiten- und Datenquellenzugriff)
- **Zentrale Geheimnishaltung:**  
  Client-IDs, Client-Secrets und Refresh-Tokens bzw. rotierende Notion-Grants liegen ausschließlich im geschützten Geheimnisspeicher des zentralen Dienstes. Die Nutzerinstanz erhält wie in 8.0 nur eine undurchsichtige Verbindungsreferenz (`connection_id`, Generation) und ruft kurzlebige Access-Tokens über die mTLS-API ab.
- **Besonderheit Notion:**  
  Da Notion bei der Autorisierung Workspace- und Bot-Metadaten zurückliefert und Tokens gemäß `external/notion_oauth.py` verwaltet, speichert der zentrale Dienst `workspace_id` / `bot_id` als geschützte Verbindungsmetadaten und liefert der Nutzerinstanz nur das benötigte Token sowie die lesbaren Workspace-Bezeichnungen für die Datenquellenauswahl (`Einstellungen → Zielprofile`).

### 3.2 Verbindungs- und Bestätigungsablauf in der Instanz
1. Ein geschützter POST (`session`, `CSRF`, `Entwurfs-/Profilrevision`, `Idempotenzschlüssel`) registriert beim zentralen Dienst einen Auftrag mit `provider` (`microsoft` oder `notion`), `operation` (`connect`, `reauthorize`, `replace`) und Zielbindung.
2. Der Browser authentifiziert beim jeweiligen Anbieter und kehrt zum zentralen Callback zurück.
3. Der zentrale Dienst validiert State/PKCE und erteilte Berechtigungen und leitet mit einem kurzlebigen, einmaligen Abschlussbeleg zur Nutzerinstanz zurück.
4. Auf der neutralen Abschlussseite (`SameSite=Strict`-sicher) übernimmt der Nutzer per geschütztem POST den vorläufigen Zugang und wählt anschließend sein konkretes Ziel (Microsoft-Kalender / To-Do-Liste bzw. Notion-Datenquelle mit Eigenschaftszuordnung).
5. Erst eine zweite ausdrückliche Bestätigung aktiviert die neue Zielverbindung im Entwurf oder Zielprofil.

### 3.3 Schutzmaßnahmen
- Bei unklarem Code-Tausch oder Verbindungsabbruch zum zentralen Dienst wird keine halb umgestellte Verbindung genutzt; die bestehende aktive Verbindung bleibt unberührt (`ExternalUnavailable` / `HostedUnavailable`).
- Trennt der Nutzer die Verbindung in seiner Instanz, vergisst der Prozess das Token sofort (`forget_locally`) und meldet die Widerrufung an den zentralen Dienst.

---

## 4. Teil B: Geführtes 3-Schritte-Self-Service-Onboarding

### 4.1 Einstieg und Zustandsmodell (`onboarding.json`)
Das Onboarding verwaltet einen eigenen, lesbaren Zustand im Datenverzeichnis (`onboarding.json`), streng getrennt vom Produktivbestand:

```text
not_started ──► step_mailbox ──► step_target ──► step_topics_dryrun ──► completed
                     │                │                   │
                     └────────────────┴───────────────────┴──► skipped (jederzeit über „Expertenansicht“)
```

- **Automatischer Einstieg:** Ist eine Instanz noch unkonfiguriert (kein aktives Postfach und kein aktives Ziel) und `onboarding.status` weder `completed` noch `skipped`, leitet `/` angemeldete Nutzer auf `/onboarding` (mit sichtbarem Link zur normalen Ansicht).
- **Wiederaufnahme:** Jeder abgeschlossene Schritt wird atomar gespeichert; bei Browser-Schließung oder Neustart setzt `/onboarding` exakt beim aktuellen Schritt fort.

### 4.2 Die drei Schritte im Detail

#### Schritt 1: Postfach verbinden
- Bindet den vereinfachten Einrichtungsfluss aus **8.1** direkt in den Assistenten ein (E-Mail-Adresse, erkannter Anbieter, OAuth2 oder App-Passwort).
- Führt sofort eine lesende IMAP-Diagnose durch (Login, Ordnerliste) und zeigt ein klares Ergebnis („Verbunden – X Nachrichten im Posteingang“ oder verständliche Hilfestellung bei App-Passwort-/2FA-Fehlern).

#### Schritt 2: Zielsystem verbinden
- Bietet eine klare Kachelauswahl ohne Fachjargon:
  - **Google** (Kalender & Google Tasks via „Mit Google verbinden“, 8.0)
  - **Microsoft** (Outlook-Kalender & To Do via „Mit Microsoft verbinden“, 8.2)
  - **Notion** (Aufgaben-Datenbank via „Mit Notion verbinden“, 8.2)
  - **Weitere:** Todoist (Token) oder CalDAV (Serverdaten)
- Nach erfolgreicher Verbindung erfolgt die Zielauswahl (z. B. Hauptkalender oder To-Do-Liste) und ein rein lesender Zugriffstest.

#### Schritt 3: Themen-Kurzprofil & Testlauf ohne Risiko
- **Starter-Themenprofile:**  
  Statt eine leere `topics.yaml` manuell zu editieren, wählt der Nutzer per Checkboxen aus kuratierten Starter-Paketen (z. B. *Privat & Termine*, *Schule & Familie*, *Beruf & Projekte*, *Vereine & Ehrenamt*), die in einen gültigen Themenentwurf übernommen werden. Spätere Feinanpassung unter `/themen` bleibt unverändert möglich.
- **Begrenzter Probelauf im Testmodus:**  
  Der Nutzer kann per Klick (*„5 aktuelle Mails probeweise auswerten“*) einen einmaligen, budget- und anzahlbegrenzten Abruf (maximal 10 Mails) **ausschließlich im Testmodus** starten.
  - Mailhelp zeigt das Ergebnis direkt im Assistenten als kompakte Vorschau (gefundene Termine und Aufgaben).
  - Es werden garantiert **keine** externen Einträge angelegt und keine Telegram-Nachrichten versendet.
- **Ausdrückliche Aktivierung:**  
  Erst der abschließende geschützte POST (*„Einrichtung übernehmen und Echtbetrieb starten“*) validiert den Gesamtenwurf (Diagnoseprüfung), speichert die Konfiguration atomar und setzt `onboarding.status = completed`. Bis zu diesem Klick verändert das Onboarding keine aktive Produktivkonfiguration.

---

## 5. Sicherheit, Datenschutz und Barrierefreiheit

- **Autorisierung:** Jeder zustandsändernde Schritt im Onboarding und bei den Ziel-OAuths prüft aktive Sitzung, CSRF-Token, Entwurfs-/Onboarding-Revision und Idempotenzschlüssel; bei Ausführung wird die Sitzung erneut geprüft.
- **Vertraulichkeit:** Mailinhalte werden nur im Schritt 3 (auf ausdrückliche Nutzeraktion im Testmodus) von der eigenen Instanz verarbeitet und niemals an den zentralen OAuth-Dienst übertragen. Client-Secrets, Refresh-Tokens und Passwörter erscheinen weder in URLs noch in HTML, JSONL-Logs oder Fehlermeldungen.
- **Barrierefreiheit & Sprache:** Alle Seiten von `/onboarding` und den neuen OAuth-Abschlüssen funktionieren vollständig ohne JavaScript (progressive Erweiterung für Statusaktualisierung beim Testlauf) und sind vollständig zweisprachig (Deutsch und Englisch via `mailhelp.i18n.tr()`).

---

## 6. Arbeitspakete

| Paket | Inhalt | Kernmodule |
| :--- | :--- | :--- |
| **8.2.1** | Verallgemeinerung des zentralen OAuth-Clients auf Provider (`google`, `microsoft`, `notion`) mit Schema- und Protokolltests. | `external/hosted_oauth.py`, `runtime/oauth_web.py`, `web/oauth_site.py` |
| **8.2.2** | Anbindung von Microsoft (Kalender/To Do) und Notion an den zentralen OAuth-Fluss inklusive Ziel-/Datenquellenauswahl. | `external/microsoft.py`, `external/notion_oauth.py`, `web/target_pages.py` |
| **8.2.3** | Zustandsmodell `onboarding.json` und Starter-Themenprofile mit atomarer Entwurfs- und Revisionsprüfung. | `domain/onboarding.py` (oder `runtime/onboarding.py`), `config/` |
| **8.2.4** | Weboberfläche `/onboarding` (Schritte 1 & 2: Postfach + Ziel mit direkter Diagnose und Überspringen-Pfad). | `web/onboarding_site.py`, `web/setup_site.py` |
| **8.2.5** | Schritt 3: Begrenzter Testmodus-Probelauf, Ergebnisvorschau und ausdrückliche Aktivierung; vollständige i18n-Einträge (`de`/`en`). | `runtime/onboarding.py`, `web/onboarding_site.py`, `i18n/en.py` |
| **8.2.6** | Browser-Tests (kompletter 3-Schritte-Durchlauf mit simulierten Anbietern), Dokumentation (`Ersteinrichtung.md`, `Ziele-einrichten.md`, Spezifikation) und Gesamtabnahme. | `ui_tests/test_ui_onboarding.py`, `docs/` |

---

## 7. Verbindliche Prüfung und Freigabekriterien

1. **Vollständige Abdeckung (`AGENTS.md`):**  
   `python -m devtools.check full --workers 12` besteht mit **100 % Zeilen- und 100 % Branch-Abdeckung** über den gesamten Anwendungscode, einschließlich Schichten- (`test_layers.py`), Funktionsgrößen- (`test_limits.py`), Typ- (`mypy`) und Übersetzungstests (`test_i18n.py`).
2. **Browser-Abnahme:**  
   `python -m pytest ui_tests -n 6 --dist worksteal --no-cov` prüft den gesamten Onboarding-Fluss (Desktop und mobil, Deutsch und Englisch, mit und ohne JavaScript) gegen simulierte IMAP-, OAuth- und Ziel-Endpunkte.
3. **Sicherheits- und Negativtests:**
   - Abbruch, abgelaufene Aufträge, fremde Sitzungen, fehlende Scopes, geänderte Entwurfsrevisionen und doppelte Idempotenzschlüssel werden sauber abgewiesen, ohne aktive Konfigurationen oder Verbindungen zu beschädigen.
   - Der Probelauf in Schritt 3 ruft nachweislich keinen produktiven Schreiber auf.
4. **Abgrenzung:**  
   Automatisierte Tests verwenden ausschließlich simulierte Dienste und synthetische Daten. Eine spätere Aktivierung produktiver Microsoft-/Notion-OAuth-Apps im gehosteten Betrieb erfordert vorab eine gesonderte Betreiberprüfung und Freigabe.
