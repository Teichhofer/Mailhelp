# Kalender und Aufgaben verbinden

Stand: Mailhelp 5.3. Ein **Zielprofil** legt fest, in welchen Kalender und welche Aufgabenliste
bestätigte Vorschläge eines Postfachs eingetragen werden. Profil 1 ist der Abschnitt `targets`
aus der Ersteinrichtung; weitere Profile verwaltet **Einstellungen → Zielprofile**. Ein
**Konto** ist der Zugang beim Anbieter (Zugangsdaten in `.env`), die Kalender- bzw.
Listen-ID das konkrete Ziel innerhalb dieses Kontos.

Mailhelp schreibt nur nach deiner ausdrücklichen Bestätigung genau der angezeigten
Vorschlagsversion und prüft jede Eintragung anschließend mit einem frischen Abruf.

## Anbieter und ihre Fähigkeiten

| Anbieter | Rolle | Zugang (`.env`) | Kennung | Geprüft wird | Grenzen |
| --- | --- | --- | --- | --- | --- |
| Google Kalender | Kalender | `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REFRESH_TOKEN` | Kalender-ID oder `primary` | Titel, Zeiten, Ganztägigkeit, Ort, Beschreibung | Rücksprungadresse muss in der Google-Konsole eingetragen sein |
| Todoist | Aufgaben | `TODOIST_TOKEN` | Projekt-ID | Titel, Beschreibung, Fälligkeit, Projekt | Änderungen und Absagen nur für Termine |
| Outlook | Kalender | `MICROSOFT_CLIENT_ID`, optional `MICROSOFT_CLIENT_SECRET`, Anmeldung per Gerätecode | Kalender oder `default` | wie Google | Absagen löschen den Termin |
| Microsoft To Do | Aufgaben | wie Outlook | Liste oder `default` („Aufgaben“) | Titel, Beschreibung, Fälligkeitstag | nur tagesgenau, keine Uhrzeit |
| CalDAV | Kalender und Aufgaben | `CALDAV_USERNAME`, `CALDAV_PASSWORD` (App-Passwort) | Adresse der Sammlung | Ressource mit UID, Feldern, Status | Serientermine werden nie verändert |
| Apple Erinnerungen | Aufgaben (über CalDAV) | wie CalDAV (iCloud-App-Passwort) | Adresse der Liste | wie CalDAV | auf neue iCloud-Erinnerungen umgestellte Listen sind über CalDAV nicht erreichbar |
| Kalenderdatei | Kalender (über Telegram) | – | – | nicht prüfbar | ob die Datei importiert wurde, kann Mailhelp nicht wissen |

## Google Kalender

1. Unter **Einstellungen → Zugangsdaten** Client-ID und Client-Geheimnis des
   Webanwendungs-Clients hinterlegen; die **Google-Rückleitungsadresse (Webanwendungs-Client)**
   muss in der Google-Cloud-Konsole eingetragen sein.
2. **Google verbinden** wählen, im Google-Fenster zustimmen und **Google-Anmeldung abschließen**.
3. **Google-Kalender auswählen** und den gewünschten Kalender übernehmen.
4. **Zugriffe prüfen**.

Alternativ ohne Webanwendungs-Client: [Google: OAuth-Playground-Anleitung](Google-OAuth-Playground.md).

## Todoist

1. Den API-Token aus den Todoist-Einstellungen unter **Einstellungen → Zugangsdaten** als
   `TODOIST_TOKEN` hinterlegen.
2. Die **Todoist-Projekt-ID** eintragen (aus der Projektadresse im Browser).
3. **Zugriffe prüfen**.

## Outlook und Microsoft To Do

1. `MICROSOFT_CLIENT_ID` hinterlegen (App-Registrierung mit „Öffentliche Clientflows zulassen“).
2. **Microsoft verbinden**, **Anmeldung starten**, den angezeigten Code mit **Code kopieren**
   übernehmen und bei Microsoft eingeben. Am Rechner geht das auch mit
   `mailhelp --microsoft-login --config-directory .`.
3. **Outlook-Kalender-ID** bzw. **Microsoft-To-Do-Liste** eintragen (`default` für den
   Standardkalender bzw. die Liste „Aufgaben“) und **Zugriffe prüfen**.

## CalDAV und Apple Erinnerungen

1. `CALDAV_USERNAME` und `CALDAV_PASSWORD` hinterlegen; bei iCloud ein App-Passwort verwenden.
2. **CalDAV-Kalenderadresse** bzw. **CalDAV-Aufgabenadresse** als vollständige Adresse der
   Sammlung eintragen.
3. **Zugriffe prüfen**: Mailhelp prüft lesend, ob die Adresse eine Kalendersammlung ist und den
   passenden Eintragstyp annimmt.

## Ziel sicher wechseln

Ein geändertes Ziel gilt für neue Vorschläge. Bereits angezeigte Vorschläge bleiben an das Ziel
gebunden, für das sie erstellt wurden; nach einem Zielwechsel sperrt Mailhelp ihre Anlage und
verlangt eine neue Bestätigung. Ein Zielprofil lässt sich erst entfernen, wenn kein Postfach es
mehr verwendet. Anleitung zur Zuordnung: [Konten verwalten](Konten-verwalten.md).
