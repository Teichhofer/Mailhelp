# Google Kalender über den OAuth 2.0 Playground einrichten

Stand: 4. November 2026. Dieser manuelle Browser-Ablauf liefert die Google-Zugangsdaten
für Mailhelp, auch wenn Mailhelp in Docker oder auf einem anderen Rechner läuft.
Seit 3.7 ist die Anleitung direkt im Einrichtungsschritt „Kalender und Aufgaben“
und bei den Zielprofilen erreichbar. Die bestehende lokale Anmeldung über
`mailhelp --google-auth` verwendet einen anderen Clienttyp (Desktop-App).

## 1. Eigenen Google-Client vorbereiten

1. In der [Google Cloud Console](https://console.cloud.google.com/) ein eigenes
   Projekt wählen oder anlegen und die **Google Calendar API** aktivieren.
2. Den OAuth-Zustimmungsbildschirm unter Google Auth Platform einrichten.
   Bei einer externen App im Teststatus das zur Kalenderanmeldung verwendete
   Google-Konto als Testnutzer hinzufügen.
3. Einen OAuth-Client vom Typ **Webanwendung / Web application** erstellen.
   Als autorisierten Weiterleitungs-URI exakt
   `https://developers.google.com/oauthplayground` eintragen.
4. **Client-ID** und **Client-Secret** dieses Clients für die nächsten Schritte
   bereithalten. Alle drei später in Mailhelp hinterlegten Werte müssen zu
   diesem Client und der damit erteilten Zustimmung gehören.

Google beschreibt die Client-Erstellung in der
[Anleitung für Zugangsdaten](https://developers.google.com/workspace/guides/create-credentials).
Für diesen Ablauf keinen Desktop-Client verwenden.

## 2. Zugriff im Playground erlauben

1. Den [offiziellen OAuth 2.0 Playground](https://developers.google.com/oauthplayground/)
   öffnen und über das Zahnrad die Konfiguration aufrufen.
2. **Use your own OAuth credentials** aktivieren und die eigene Client-ID sowie
   das zugehörige Client-Secret eingeben. **OAuth flow: Server-side**,
   **OAuth endpoints: Google**, **Access type: Offline** und
   **Force prompt: Consent Screen** wählen.
3. In „Step 1“ folgende Scopes auswählen beziehungsweise eingeben:

   ```text
   https://www.googleapis.com/auth/calendar.events
   https://www.googleapis.com/auth/calendar.calendars.readonly
   https://www.googleapis.com/auth/calendar.calendarlist.readonly
   ```

   Die ersten beiden Berechtigungen entsprechen Mailhelps bisherigem lokalen
   Anmeldeweg. Die dritte erlaubt die für 3.7 geplante Kalenderauswahlliste.
   Die [Scope-Referenz](https://developers.google.com/workspace/calendar/api/auth)
   und [CalendarList-Dokumentation](https://developers.google.com/workspace/calendar/api/v3/reference/calendarList/list)
   erläutern die Berechtigungen.
4. **Authorize APIs** anklicken, das gewünschte Google-Konto auswählen und den
   benötigten Berechtigungen zustimmen.
5. In „Step 2“ **Exchange authorization code for tokens** anklicken.
   Den angezeigten **Refresh token** für Mailhelp übernehmen. Der kurzlebige
   **Access token** und der Authorization Code werden nicht in Mailhelp eingetragen.

Eigene Clientdaten sind erforderlich: Der Playground widerruft mit seinen
Standard-Zugangsdaten erzeugte Refresh-Tokens nach 24 Stunden. Die Option für eigene
Clientdaten vermeidet diese Playground-Frist; andere Google-Ablaufregeln bleiben
gültig. Siehe die Hinweise im [Playground](https://developers.google.com/oauthplayground/).

## 3. Die drei Werte in Mailhelp hinterlegen

In der authentifizierten Zugangsdatenverwaltung das gewünschte Zielprofil wählen
und die Felder für Client-ID, Client-Secret und Refresh-Token befüllen. Für Profil 1
lauten die zugehörigen `.env`-Namen:

| Wert | Name |
| --- | --- |
| Eigene Client-ID | `GOOGLE_OAUTH_CLIENT_ID` |
| Zugehöriges Client-Secret | `GOOGLE_OAUTH_CLIENT_SECRET` |
| Refresh-Token aus Step 2 | `GOOGLE_OAUTH_REFRESH_TOKEN` |

Bei weiteren Profilen gelten beispielsweise `GOOGLE_OAUTH_2_CLIENT_ID`,
`GOOGLE_OAUTH_2_CLIENT_SECRET` und `GOOGLE_OAUTH_2_REFRESH_TOKEN`. Vorhandene
Prozessvariablen überschreiben `.env` und müssen bei einem Wechsel ebenfalls
angepasst werden. Im aktuellen Stand wirken geänderte Zugangsdaten nach Neustart.
Mailhelp beschafft Access-Tokens selbst aus dem Refresh-Token.

Den Zielkalender konfigurieren (`primary` für den Hauptkalender oder die konkrete
Kalender-ID) und den Zugriff prüfen. Die Einrichtung in 3.7 kann die Kalenderliste
laden und eine Auswahl anbieten. Verbindungsprüfung und OAuth-Zustimmung erzeugen
keinen Termin; jede Anlage braucht weiterhin eine separate Vorschlagsfreigabe.

## 4. Typische Probleme

- **`redirect_uri_mismatch`:** Webanwendungs-Client und exakt eingetragenen
  Playground-Weiterleitungs-URI prüfen.
- **Kein Refresh-Token:** Offline-Zugriff und erneute Zustimmung im Playground
  wählen; nicht den Access-Token in das Refresh-Token-Feld kopieren.
- **Token nach sieben Tagen ungültig:** Bei externen Apps im Status „Testing“
  laufen Refresh-Tokens für diese Calendar-Scopes nach sieben Tagen ab. Für den
  Dauerbetrieb Veröffentlichungsstatus und gegebenenfalls Verifizierung klären.
  Ein Refresh-Token ist auch danach nicht unbegrenzt garantiert gültig; er kann
  etwa durch Widerruf oder Richtlinien ungültig werden. Siehe
  [Googles Ablaufregeln](https://developers.google.com/identity/protocols/oauth2#expiration).
- **Kalender fehlt oder Schreibzugriff verweigert:** Konto, erteilte Scopes und
  Berechtigungen am Zielkalender prüfen. Ein reiner Leserzugriff genügt nicht zum Anlegen.

Client-Secret und Tokens nur in den vorgesehenen geschützten Feldern beziehungsweise
`.env` aufbewahren. Keine Playground-Freigabelinks mit eingebetteten Zugangsdaten
erzeugen und keine Tokens in Screenshots oder Anwendungslogs übernehmen.
