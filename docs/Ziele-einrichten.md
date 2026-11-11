# Kalender und Aufgaben verbinden

Stand: Mailhelp 5.4.1, Anbieterunterlagen am 11. November 2026 abgeglichen. Ein **Zielprofil** legt fest, in welchen Kalender und welche Aufgabenliste
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

Bei einem externen Google-Projekt im Veröffentlichungsstatus „Testing“ kann der Refresh-Token
nach sieben Tagen ablaufen. Dann die Anmeldung erneuern und den Projektstatus prüfen.

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

## Geprüfte Anbieterquellen

Prüfdatum: 11. November 2026. Dies ist ein Abgleich der Einrichtungshinweise mit offiziellen
Unterlagen; es wurden keine echten Konten verbunden oder externen Einträge angelegt.

- Google: [Kalenderberechtigungen](https://developers.google.com/workspace/calendar/api/auth)
  und [OAuth einschließlich Refresh-Token-Ablauf](https://developers.google.com/identity/protocols/oauth2).
- Todoist: [persönlicher API-Token und API](https://developer.todoist.com/).
- Microsoft: [Gerätecode-Anmeldung](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-device-code)
  und [Graph-Berechtigungen](https://learn.microsoft.com/en-us/graph/permissions-reference).
- CalDAV am Beispiel Nextcloud: [Sammlungsadresse und App-Passwort bei Zwei-Faktor-Schutz](https://docs.nextcloud.com/server/latest/user_manual/en/groupware/sync_windows10.html).
- Apple: [App-Passwörter](https://support.apple.com/en-gb/102654) und
  [Umstellung der iCloud-Erinnerungen](https://support.apple.com/en-us/102457).
  Mailhelp verwendet den vorhandenen CalDAV-/VTODO-Adapter; daraus folgt keine Unterstützung
  der neuen iCloud-Erinnerungslisten. Diese Grenze bleibt ausdrücklich bestehen.
