# Konten verwalten

Geprüft für Mailhelp 7.0. Weitere Postfächer, IServ-Konten und weitere Kalender-/Aufgabenziele in
einer bereits eingerichteten Installation hinzufügen, ändern und entfernen.

**Grundsatz:** Zugangsdaten stehen nur in `.env` und werden unter **Einstellungen →
Zugangsdaten** gepflegt; angezeigt wird nur „hinterlegt“ oder „fehlt“. Änderungen an Postfächern
und Zielen sind Entwürfe und werden erst nach einer erneuten ausdrücklichen Bestätigung
übernommen. Keine dieser Seiten legt Aufgaben oder Termine an.

## Ein weiteres Postfach hinzufügen

**Voraussetzung:** Server, Port, Verbindungsart und Zugangsdaten des Postfachs.

1. **Einstellungen → Postfächer** öffnen und **Postfach hinzufügen** wählen.
2. Ausfüllen:
   - **Anzeigename**, z. B. „Schule“.
   - **IMAP-Server** und **Port**.
   - **Verbindungsart**: **SSL/TLS (meist Port 993)**, **STARTTLS (meist Port 143)** oder
     **Unverschlüsselt (nur im eigenen Netz)**.
   - **Benutzername (meist die vollständige E-Mail-Adresse)** und **Passwort oder App-Passwort**.
   - **Ordner (kommagetrennt, der erste ist der Posteingang)** und **Ordner für
     Antwortentwürfe**.
   - **Ältere Mails nicht verarbeiten vor (leer: alle vorhandenen Mails)**, vorbelegt mit heute.
3. **Verbindung prüfen und Postfach aktivieren** wählen.

**Ergebnis:** Nach erfolgreicher Prüfung von Anmeldung, Ordnerliste und Lesezugriff werden
`config.yaml` und `.env` gespeichert (`IMAP_<n>_USERNAME`/`IMAP_<n>_PASSWORD`). Das neue
Postfach wird zwischen zwei Mailzyklen ergänzt, ohne Neustart. Schlägt die Prüfung fehl, bleiben
alle Eingaben außer dem Passwort erhalten; die Meldung nennt die Ursache ohne Serverantwort.
Doppelte Konten werden abgewiesen. Wer nicht sofort aktivieren will, wählt **Stattdessen nur
als Entwurf hinzufügen**.

## Ein Postfach einem anderen Kalender oder einer anderen Aufgabenliste zuordnen

1. Unter **Einstellungen → Zielprofile** mit **Zielprofil hinzufügen** ein Profil anlegen
   (Bezeichnung, Kalenderdienst, Aufgabendienst und die jeweiligen Kennungen) – siehe
   „Weitere Ziele“ unten.
2. **Einstellungen → Postfächer**, das Postfach öffnen, Reiter **Ziele**, **Zielprofil** auf das
   neue Profil setzen.
3. **Entwurf prüfen** und anschließend **Entwurf übernehmen** bestätigen.

**Ergebnis:** Neue Vorschläge dieses Postfachs gehen an das neue Ziel. Bereits vorhandene
Vorschläge bleiben an ihr bisheriges Ziel gebunden; für das neue Ziel ist eine neue Bestätigung
nötig.

## Regeln je Postfach

Auf der Postfachseite gibt es die Reiter **Ziele**, **Filter**, **Themen**, **Antworten** und
**Benachrichtigungen**. Nicht belegte Felder erben die globale Einstellung; Zurücksetzen
entfernt die lokale Regel. Beispiele: eigene Standarddauern für Termine, eigene Signatur für
Antwortentwürfe, kürzere Aufbewahrung, eigene Ruhezeiten, lokale Absendersperren oder
Ausnahmen von globalen Sperren. Alle Felder: [Einstellungen](Web-Einstellungen.md#postfächer-imapmailboxes).

## IServ-Konto ergänzen

1. **Einstellungen → IServ-Konten** öffnen.
2. Unter **Direkt aktivieren** Anzeigename, Adresse der Schule (ein kopierter IServ-Link wird auf
   die Schuladresse gekürzt), das Postfach, dessen Zielprofil und Standards gelten, optional eine
   Startgrenze sowie Benutzername und Passwort eintragen. Leere Zugangsfelder verwenden bereits
   hinterlegte Werte (`ISERV_<n>_USERNAME`/`ISERV_<n>_PASSWORD`).
3. **Verbindung prüfen und Konto aktivieren** wählen.

**Ergebnis:** Erst nach erfolgreicher Anmeldung werden Konto und Zugangsdaten gespeichert. Der
Abruf startet ohne Neustart im nächsten sicheren Mailzyklus; offene Rückfragen gegebenenfalls
zuerst beantworten. Elternbriefe gelten immer als relevant. Wer nicht sofort aktivieren will,
wählt **IServ-Konto als Entwurf hinzufügen**.

## Weitere Ziele (Kalender und Aufgabenlisten)

Profil 1 ist das Ziel aus der Ersteinrichtung (**Standardprofil 1 bearbeiten**). Weitere Profile
(Nummer 2–99) unter **Einstellungen → Zielprofile**:

1. **Zielprofil hinzufügen**, Bezeichnung, Kalenderdienst (Google, CalDAV, Outlook) und
   Aufgabendienst (Todoist, Microsoft To Do, CalDAV, Apple Erinnerungen) wählen.
2. Die Kennungen eintragen; bei Google bzw. Microsoft über **Google verbinden** bzw.
   **Microsoft verbinden** anmelden und bei Google **Google-Kalender auswählen** beziehungsweise
   **Google-Tasks-Liste auswählen**. Die Zielauswahl wird als Einrichtungsentwurf gespeichert.
3. **Zugriffe prüfen**: Die Diagnose liest nur und legt nichts an.
4. Den Entwurf prüfen und übernehmen.

## Ändern, deaktivieren und entfernen

| Vorhaben | Weg | Wirkung |
| --- | --- | --- |
| Postfacheinstellung ändern | Postfachseite, Reiter wählen, **Entwurf prüfen**, **Entwurf übernehmen** | zwischen Mailzyklen bzw. nach Neustart |
| Postfach entfernen | Postfachseite, **Postfach entfernen**, bestätigen | wird aus der Konfiguration entfernt; nach dem Neustart nicht mehr abgerufen |
| Postfach vorübergehend abschalten | in `config.yaml` `enabled: false` beim Postfach | nach Neustart |
| Zielprofil entfernen | Zielprofilseite, **Profil entfernen** | erst möglich, wenn kein Postfach es mehr verwendet („Verwendet von: …“) |
| IServ-Konto ändern, deaktivieren oder entfernen | IServ-Seite; die Änderung wird als Entwurf gespeichert | nach ausdrücklicher Übernahme des Entwurfs und Neustart |
| Zugangsdaten erneuern | **Einstellungen → Zugangsdaten** | Diagnose sofort, Mailabruf nach Neustart |

## Wenn etwas nicht klappt

| Lage | Nächster Schritt |
| --- | --- |
| „Es sind bereits … Postfächer eingerichtet.“ | Ein vorhandenes Postfach entfernen oder ändern |
| Prüfung meldet falsche Anmeldedaten | Benutzername meist die vollständige Adresse; bei Zwei-Faktor-Schutz ein App-Passwort verwenden |
| Ordner fehlt | Ordnernamen genau so eintragen, wie der Server sie meldet; die Prüfung zeigt die gefundene Liste |
| Ziel nicht erreichbar | **Zugriffe prüfen**; bei Google oder Microsoft die Anmeldung erneuern |
| Zielprofil lässt sich nicht entfernen | Unter „Verwendet von“ genannte Postfächer erst einem anderen Profil zuordnen |
