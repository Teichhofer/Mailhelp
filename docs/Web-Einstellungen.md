# Einstellungen der Weboberfläche

Stand: 11. November 2026, Anwendungsversion 5.7.6; Inventur aller Schlüssel: [Prüfbericht 5.3](Pruefung-Dokumentation-5.3.md).

## Themenübersicht

`/themen` zeigt relevante Themen und Ausschlussthemen in getrennten Reitern mit Anzahlen.
Suche durchsucht Name, ID, Beschreibung, Beispiele und Ausschlüsse; der Statusfilter zeigt
alle, aktive oder deaktivierte Themen. Ohne JavaScript „Themen suchen“ wählen, mit JavaScript
wird sofort gefiltert. Die Tabelle wird auf kleinen Bildschirmen zur Kartenliste.
Deaktivierte Themen stehen am Ende. „Änderung ausstehend“ markiert wartende Themenbefehle.
„Bearbeiten“ und „Neues Thema“ öffnen jeweils eine eigene Seite. Bestehende Postfachbereiche
werden nur angezeigt und beim Speichern aus der aktuellen Datei erhalten. In Beispielen und
Ausschlüssen steht ein Eintrag je Zeile; ein Semikolon bleibt Teil des Eintrags.

### Thema bearbeiten

1. In der Übersicht „Bearbeiten“ oder „Neues Thema“ wählen.
2. Name, Beschreibung, Beispiele und Ausschlüsse anpassen; „Aktiv“ ein- oder ausschalten.
   Bei einem neuen Thema wird die Themen-ID aus dem Namen vorgeschlagen und kann vor dem
   ersten Speichern geändert werden. Die ID eines bestehenden Themas bleibt fest.
3. „Änderung prüfen“ wählen. Die Vorschau zeigt je geändertem Feld den bisherigen und den
   neuen Wert; neue und entfernte Beispiele sind mit „+ neu“ und „− entfernt“ markiert,
   unveränderte Felder öffnet „Unveränderte Felder anzeigen“. Die Vorschau speichert noch nichts.
4. „Änderung ausdrücklich speichern“ ankreuzen und „Änderung speichern“ wählen. Mit
   „Weiter bearbeiten“ geht es ohne Speichern zurück.

Fehler stehen direkt am betroffenen Feld; die Eingaben bleiben erhalten. Wurde die
Themendatei inzwischen geändert, „Neu laden“ wählen und die Änderung erneut prüfen. Eine
offene Vorschau erscheint in der Übersicht unter „Ausstehende Themenänderungen“ und verfällt
nach 24 Stunden. Das letzte aktive relevante Thema kann nicht deaktiviert werden.

Ausschlussthemen sind negative Kategorien für Lern- und Entscheidungstests. Im normalen
Mailbetrieb wirken die relevanten Themen und ihre Ausschlüsse; die Datei ist kein weiterer
globaler Vorfilter.

Ab 5.7 bündelt Lernen (`/lernen`) die Funktionen „Aus dem Postfach lernen“
(`/lernen/postfach`) und „Aus Entscheidungen lernen“ (`/lernen/entscheidungen`).
Auch die Themenseite verlinkt das Regellernen. `/themen/lernen` wird dauerhaft
weitergeleitet; alte offene POST-Formulare führen nichts aus und verlangen eine neue Bestätigung.
Sie analysiert vorhandene protokollierte Entscheidungen nach ausdrücklicher Freigabe von
Kosten und Datenübertragung. Alt und Neu stehen nebeneinander; ausgewählte Regeln lassen
sich als Felder oder vollständiges Themen-YAML bearbeiten und gesondert bestätigt übernehmen.
Parser-, Schema-, Sitzungs- und Revisionsprüfungen schützen beide Themendateien. Bei einem
Schreibabbruch lässt sich die freigegebene Übernahme ohne erneute KI-Analyse abschließen.
Anleitung: [Aus Entscheidungen lernen](Bedienung.md#aus-entscheidungen-lernen).

Es gibt dafür keine neuen `config.yaml`-Schalter. Der optionale Prompt
`decision_rule_learning` liegt in `prompts.yaml`, nutzt die aktive Modellroute und die
bestehenden KI-Limits. Ältere Promptdateien bleiben gültig; fehlt der Block, wird die
Analyse mit Hinweis beendet. Externe Kalender und Aufgabenlisten werden nicht beschrieben.

`/einstellungen` zeigt Kacheln für Konten, allgemeine Regeln, Inhalte und Systemaktionen.
Kontenkacheln nennen die Anzahl der im laufenden Dienst eingerichteten Konten. Bereichskacheln
markieren gespeicherte, noch nicht aktive Änderungen. Verglichen wird mit den Werten, die der
nächste Start anwenden würde: Eine in `config.yaml` fehlende Einstellung gilt mit ihrem
Standardwert und ist keine ausstehende Änderung. Die Suche (`?suche=…`, höchstens 80 Zeichen)
findet Einstellungen und Seiten (Postfächer, IServ, Zielprofile, Zugangsdaten, Themen, Geräte,
Neustart …), deren Bezeichnung, Schlüssel, Gruppe, Bereich, Hilfetext oder Synonyme alle
eingegebenen Wörter enthalten. Großschreibung, Leerraum und Umlaute (`ä`/`ae`, `ß`/`ss`) zählen
nicht; Synonyme verbinden etwa „KI“ und „Modell“, „Postfach“ und „Konto“, „Abruf“ und
„Intervall“. Zuerst stehen exakte Schlüssel oder Bezeichnungen, dann Wortanfänge, dann übrige
Treffer, bei Gleichstand alphabetisch. Jeder Treffer führt mit einem Anker
(`#einstellung-<schlüssel>`) direkt zur Einstellung und klappt sie auf.

Live-Suche (5.3): Auf der Übersicht und jeder Bereichsseite erscheinen beim Tippen ab dem ersten
Zeichen bis zu zehn Treffer direkt unter dem Suchfeld, ohne Klick auf „Suchen“ und ohne neue
Seite. Gesucht wird 150 ms nach der letzten Eingabe; eine neue Eingabe bricht die vorige Anfrage
ab, verspätete Antworten werden verworfen. Eine Ansage nennt die Trefferzahl. Leeren entfernt die
Treffer sofort; „Suchen“ oder Enter öffnet weiterhin die vollständige Ergebnisseite. Bei einem
Fehler bleibt die normale Suche nutzbar. Die Sofortsuche ruft nie die KI auf und liest nur
Bezeichnungen und Hilfetexte, keine gespeicherten Werte. Endpunkt:
`GET /api/einstellungen/suche?suche=…` (nur angemeldet, nicht zwischengespeichert).
Ein unbekannter Bereich liefert HTTP 404. Die Oberfläche funktioniert ohne JavaScript.

| Bereich | Adresse | Inhalt |
| --- | --- | --- |
| Mailabruf | `?bereich=abruf` | Abruf, Mailgrenzen, Zeitlimits, Wiederholungen |
| Benachrichtigungen | `?bereich=benachrichtigungen` | Telegram, Tagesüberblick, Push-Steuerung |
| Antworten und Termine | `?bereich=antworten` | Antworten, Termindauern, Abgleich, Ziele |
| KI und Auswertung | `?bereich=ki` | Modelltabelle (nur lesend), Bilder, Lernen, Berichte, Kosten |
| Daten und Protokolle | `?bereich=daten` | Anhänge, Aufbewahrung, Protokollierung |
| Weboberfläche und System | `?bereich=system` | Sitzungen, Netzwerk, Geräte, Neustart, Beenden |
| Zugangsdaten | `?bereich=zugangsdaten` | Passwörter und API-Schlüssel |

Auf großen Bildschirmen bleibt die Bereichsnavigation neben den Werten erreichbar;
auf dem Handy steht sie oberhalb der Einstellungsgruppen. Speichern und Bestätigung
laufen weiterhin über `/einstellungen/speichern` und die Befehlswarteschlange.

## Postfach hinzufügen (3.5)

Unter `/einstellungen/postfaecher` Server, Port, SSL/TLS, STARTTLS oder unverschlüsselte Verbindung,
Benutzername, Passwort, Quellordner und Entwurfsordner gemeinsam eingeben. Der erste Quellordner
ist der Posteingang. Die Startgrenze ist mit heute vorbelegt (00:00 Uhr in der konfigurierten
Zeitzone); leer bedeutet alle vorhandenen Mails. **Verbindung prüfen und Postfach aktivieren**
prüft Anmeldung, Ordnerliste und lesenden Zugriff. Doppelte Konten (auch deaktivierte) werden
abgewiesen. Fehlermeldungen enthalten keine Serverantworten oder Zugangsdaten; übrige Eingaben
bleiben erhalten, das Passwortfeld wird geleert.

Erst nach erfolgreicher Prüfung werden `config.yaml` und `.env` gespeichert. Neue Reader werden
zwischen Mailzyklen ergänzt, einschließlich Postfachlabels, Metriken, Antwortentwürfen und
Postfachfiltern. Verbindungsfehler beim Nachladen lassen die bisherigen Reader weiterlaufen und
werden im nächsten Zyklus erneut versucht. Gespeicherte Konten sind auch nach einem Neustart aktiv.
Leere Zugangsfelder verwenden bereits hinterlegte `IMAP_<id>_USERNAME`/`IMAP_<id>_PASSWORD`.
Prozessvariablen haben Vorrang; widersprechende Eingaben werden zurückgewiesen.

Sitzung, CSRF, Entwurfsversion, Konfigurations- und `.env`-Hash sowie Idempotenzschlüssel werden
geprüft; die Sitzung erneut unmittelbar vor dem Schreiben. Unterbrochene Aktivierungen werden
mit demselben Schlüssel nicht erneut ausgeführt: Seite neu laden und gespeicherten Stand prüfen.
Andere Entwürfe bleiben erhalten. Die Karten unterscheiden aktiv, deaktiviert, Entwurf,
gespeichert mit ausstehender Aktivierung und Änderungen im Entwurf. Die eingeklappte Alternative
**Stattdessen nur als Entwurf hinzufügen** bleibt verfügbar. Änderungen und Entfernen bestehender
Postfächer benötigen weiterhin Entwurfsübernahme und Neustart.

Einrichtungsentwürfe unter `/einrichtung` und das Versandprofil unter
`/einstellungen/benachrichtigungen` bearbeiten ebenfalls `config.yaml`.
Speichern erhält zunächst den Entwurf. Erst die gezeigte, versionsbezogene Übernahme aktiviert
Änderungen; Verbindungs- und Zieländerungen benötigen eine aktuelle erfolgreiche Diagnose.
Feldnamen, Grenzwerte, Kanalwahl und Sofort-/Neustartwirkung:
[Betriebsanleitung 3.0](Release-3.0.md#konfigurationsvertrag).

Jedes Info-Symbol erklärt, was die Einstellung verändert und welche Folgen andere Werte haben. Mit der Maus darüberfahren, per Tab fokussieren oder auf dem Handy antippen. Escape blendet die Blase aus. Das Lesen verändert keine Einstellung.

Neben **Mailhelp beenden** steht **Mailhelp neu starten**. Beide Aktionen haben
eine eigene Bestätigungsseite. Neustarten stoppt den laufenden Dienst kontrolliert
und startet denselben Interpreter mit denselben Optionen neu. Gespeicherte Einstellungen,
Zugangsdaten und Code werden neu geladen; Einrichtungsentwürfe werden dadurch nicht
übernommen. Offene Vorgänge bleiben erhalten. Danach die Weboberfläche erneut öffnen.
Stammt eine Bestätigung von einem früheren Start (zum Beispiel von einer Seite, die vor einem
Neustart geöffnet wurde) oder ist sie unvollständig, nennt Mailhelp den Grund und zeigt auf
derselben Seite eine neue Bestätigung.

Die folgende Liste enthält dieselben Hilfetexte wie die Weboberfläche. Änderungen werden erst nach der separaten Bestätigung gespeichert. „Im laufenden Betrieb“ bedeutet Übernahme an der nächsten sicheren Stelle; andere Einstellungen erfordern einen Neustart. Zahlen mit Dezimalpunkt eingeben, z. B. `0.30`. `null`, `disabled` und `unlimited` nur verwenden, wo sie unten erlaubt sind. Bei Zahlenfeldern lassen sich Sonderwerte gegebenenfalls nur direkt in `config.yaml` setzen.

## Zugangsdaten

Der separate Bereich **Zugangsdaten** ist über die Bereichsübersicht erreichbar.
Er gruppiert Postfächer, OpenRouter, Telegram und die eingerichteten Zielprofile.
Jeder Eintrag zeigt nur „vorhanden“ oder „fehlt“ und bietet ein leeres Passwortfeld
für einen neuen Wert. Bestehende Werte werden auch nach dem Speichern nicht angezeigt.

„Zugang speichern“ ersetzt ausschließlich den gewählten Schlüssel in `.env`;
Kommentare und andere Schlüssel bleiben erhalten. Die Werte gelten nach einem Neustart.
Prozessvariablen haben Vorrang und werden gesondert gekennzeichnet. Bei zusätzlichen
Zielprofilen wird eine geerbte Client-ID bzw. ein geerbter Client-Schlüssel angezeigt;
ein dort gespeicherter Wert ist eine eigene Überschreibung für dieses Profil.
Gespeicherte Microsoft-Anmeldungen werden über `mailhelp --microsoft-login` erneuert,
Google-Anmeldungen über `mailhelp --google-auth` (für zusätzliche Profile mit `--profile`).

Die Formulare prüfen Sitzung, CSRF, Konfigurations- und `.env`-Version sowie einen
Idempotenzschlüssel. Ein veraltetes Formular überschreibt keine neueren Änderungen.
Unterbrochene Speichervorgänge werden bei einer Wiederholung anhand des Dateistands
abgeglichen. Die Belege unter `credential-edits.json` enthalten nur schlüsselgebundene
HMACs und Statusdaten; Zugangswerte werden weder in HTML noch in Logs oder der
Befehlswarteschlange gespeichert. Das Bearbeiten löst keine externe Anlage aus.
Die Oberfläche funktioniert auch ohne JavaScript.

**Alle Zugangsdaten und neue Konten** öffnet `/einstellungen/zugangsdaten`.
Diese vollständige Kontenübersicht berücksichtigt auch IServ-Konten und Postfächer
im aktuellen Einrichtungsentwurf. Hier müssen neue Werte ausdrücklich bestätigt werden;
die Formulare prüfen den `.env`-Dateistand und verhindern wiederholte Schreibvorgänge
über wertfreie Belege unter `secret-operations.json`. Die Diagnose verwendet dort
gespeicherte Werte sofort. So lässt sich ein neues Konto prüfen, bevor sein
Konfigurationsentwurf übernommen wird. Die im vorigen Absatz beschriebenen HMAC-Belege
gelten für den Schnellzugriff innerhalb der allgemeinen Einstellungsseite.

## IServ-Konten

Unter `/einstellungen/iserv` lassen sich Konten als Einrichtungsentwurf anlegen und ändern.
„Ältere Briefe nicht verarbeiten vor“ akzeptiert `TT.MM.JJJJ [HH:MM]` (z. B. `01.09.2026 07:30`),
`JJJJ-MM-TT` (z. B. `2026-09-01`) oder einen ISO-8601-Zeitpunkt mit UTC-Offset.
Ein reines Datum gilt ab 00:00 Uhr in der Zeitzone des Konfigurationsentwurfs;
für `Europe/Berlin` wird `01.09.2026` als `2026-09-01T00:00:00+02:00` gespeichert.
Im Winter gilt der entsprechende Winterzeit-Offset. Ein leeres Feld erbt die Grenze des
zugeordneten Postfachs. Deutsche Angaben mit Uhrzeit gelten in der konfigurierten Zeitzone.
Ungültige Daten und ISO-Zeitpunkte ohne Offset werden abgewiesen.
Zugangsdaten werden separat unter **Zugangsdaten** gespeichert. Erst nach Diagnose und
ausdrücklicher, versionsbezogener Übernahme wird die Konfiguration geändert.
Ein Versionskonflikt antwortet mit HTTP 409; Konfiguration und Entwurf bleiben unverändert.
Dann die Konfiguration in der Einrichtung neu einlesen und die Änderungen erneut prüfen.

## Diagramme der Auswertung

Ein Klick auf ein Diagramm oder seine Schaltfläche **Vergrößern** öffnet eine große Ansicht.
Bei kleinen Bildschirmen lässt sich die Grafik darin horizontal verschieben. **Schließen**
oder Escape beendet die Ansicht und setzt den Tastaturfokus auf **Vergrößern** zurück.
Beim Darüberfahren, Fokussieren mit Tab oder Antippen eines Balkens werden Zeitraum bzw.
Kategorie, Datenreihe und Wert mit Einheit angezeigt. Die Details bleiben auch beim Bewegen
der Maus auf den Hinweis lesbar; Escape blendet sie aus. Die Daten ändern sich dadurch nicht.
Tabellen und SVG-Beschreibungen sind weiterhin ohne JavaScript verfügbar.

## Kontenstatus

Die Statusseite zeigt unter **Konfigurierte Konten** alle gespeicherten IMAP- und IServ-Konten,
Kalender und Aufgaben je Zielprofil sowie Telegram. Kontonummer und Anzeigename unterscheiden
die Zugänge. Auch deaktivierte Konten und nicht verwendete Zielprofile bleiben sichtbar.
Ein Konto beginnt nach jedem Dienststart mit „noch nicht geprüft“. Ein belegter erfolgreicher
Kontakt zeigt seinen Zeitpunkt; ein fehlgeschlagener Versuch zeigt „Fehler“. Die Ergebnisse
eines Kontos bestätigen kein anderes Konto. Offene IMAP-Ordnerfehler halten den Kontostatus
auf „Fehler“, auch wenn ein anderer Ordner erfolgreich gelesen wurde.

Bereits übernommene Verbindungsänderungen zeigen bis zum Dienstneustart „Neustart erforderlich“;
unbestätigte Entwürfe werden nicht aufgeführt. Ist die gespeicherte Konfiguration vorübergehend
nicht lesbar oder ungültig, zeigt die Seite die Konten des laufenden Dienstes.
Der Seitenaufruf startet weder eine Anmeldung noch eine externe Schreibaktion. Statuswechsel
aktualisieren die Seite automatisch; laufende erfolgreiche Abrufe allein laden sie nicht ständig neu.

## Mailabruf und Betrieb

| Einstellung / Schlüssel | Wirkung und Werte | Übernahme |
| --- | --- | --- |
| Abrufintervall (Sekunden) (`poll_interval_seconds`) | Abstand zwischen Mailabrufen: 5–86400 Sekunden. 60 prüft etwa jede Minute, 300 etwa alle fünf Minuten. Kleinere Werte erkennen neue Mails früher, größere entlasten den Mailserver. Ein laufender Durchlauf kann den nächsten Abruf verzögern. | Im laufenden Betrieb |
| Trockenlauf (`test_mode`) | ja (true) aktiviert den Trockenlauf: bestätigte Kalender- und Todoist-Aktionen werden simuliert; Testdaten werden getrennt gespeichert. nein (false) aktiviert echte Schreibaktionen nach ausdrücklicher Bestätigung. Der Trockenlauf verhindert nicht sämtliche Netzwerkzugriffe, etwa Mailabruf und KI-Aufrufe. | Nach Neustart |
| Zeitzone (`timezone`) | Zeitzone für lokale Datums- und Zeitangaben, z. B. Europe/Berlin mit automatischer Sommerzeit oder UTC ohne Zeitumstellung. Verwende einen gültigen IANA-Zeitzonennamen. Eine andere Zone verändert die Interpretation lokaler Terminzeiten und deren Anzeige. | Nach Neustart |
| Mails je Abrufdurchlauf (`imap.batch_size`) | Höchstens so viele neue Mails nimmt ein Abrufdurchlauf über alle Postfächer auf: 1–1000; Standard 25. Größere Werte arbeiten Rückstände schneller ab, verlängern aber einen einzelnen Durchlauf; kleinere verteilen die Arbeit auf mehr Durchläufe. --max-mails ersetzt den Wert für einen einzelnen Lauf. | Nach Neustart |
| Neueste Mails zuerst (alle Postfächer) (`imap.global_newest_first`) | ja (true) wählt je Durchlauf die neuesten Mails über alle Postfächer und Ordner nach Empfangszeit. nein (false) arbeitet Postfach für Postfach und Ordner für Ordner in der konfigurierten Reihenfolge. Die Einstellung bestimmt nur die Reihenfolge, nicht welche Mails verarbeitet werden. | Nach Neustart |

## Antworten

Ab 4.8.5 sperrt `drafts.enabled: false` neue Entwürfe und neue Ablagen global.
Gespeicherte Entwürfe im Postfach bleiben erhalten. Automatische Ablage benötigt
zusätzlich `smart_reply: true` und `auto_draft: true`; beide bleiben standardmäßig aus.
`drafts.enabled`, `drafts.folder` und `auto_draft` werden ohne Neustart übernommen.
Der Ordner ist ein IMAP-Ordnername oder `null` für die bisherige Postfachvorgabe.
`auto_draft` ist auch unter Postfächer → Antworten überschreibbar.

| Einstellung / Schlüssel | Wirkung und Werte | Übernahme |
| --- | --- | --- |
| Antwortentwürfe zulassen (`drafts.enabled`) | Globaler Schalter für manuelle und automatische Antwortentwürfe, Standard an. false verhindert neue Entwürfe und neue Ablagen. Bereits im Postfach abgelegte Entwürfe bleiben erhalten. smart_reply und auto_draft behalten ihre eigenen Einstellungen. | Im laufenden Betrieb |
| Entwurfsordner überschreiben (null: Postfachvorgabe) (`drafts.folder`) | Optionaler IMAP-Entwurfsordner für alle Postfächer. null verwendet deren drafts_folder. Fehlt der bevorzugte Ordner, sucht Mailhelp nach der SPECIAL-USE-Kennzeichnung oder üblichen Entwurfsordnernamen. Keine Ordner werden angelegt. Gilt für künftige Ablagen ohne Neustart. | Im laufenden Betrieb |
| Antwortentwürfe automatisch im Postfach ablegen (`auto_draft`) | ja (true) legt bei erkanntem schriftlichem Antwortbedarf automatisch einen Entwurf ab; benötigt smart_reply und drafts.enabled. Standard aus. Mailhelp versendet nie selbst. Pro Postfach überschreibbar; wird am nächsten sicheren Verarbeitungspunkt übernommen. | Im laufenden Betrieb |
| Persönliche Angaben für Antworten (`personal_info`) | Bis zu 2000 Zeichen, z. B. Name, Rolle, Signatur oder gewünschte Anrede. Diese Angaben erhält das KI-Modell beim Erstellen eines Antwort-Entwurfs. Leer bedeutet keine persönlichen Zusatzangaben. Mehr Kontext kann Ton und Inhalt des Entwurfs verändern; die Angaben werden nicht für die Mailanalyse verwendet. | Im laufenden Betrieb |
| Antwortentwürfe anbieten (`smart_reply`) | ja (true) bietet KI-Antwortentwürfe an; benötigt drafts.enabled und den Schritt draft_reply in prompts.yaml. Ohne auto_draft wird nur nach ausdrücklichem Speichern im Entwurfsordner abgelegt. Mailhelp versendet nie selbst. Postfächer können den Wert einzeln überschreiben. | Nach Neustart |

## Ziele

| Einstellung / Schlüssel | Wirkung und Werte | Übernahme |
| --- | --- | --- |
| Aufgabendienst (`targets.task_provider`) | Dienst für neue Aufgabenvorschläge: todoist, microsoft_todo (Microsoft To Do), caldav (Aufgabenliste mit VTODO, z. B. Nextcloud Tasks) oder apple_reminders (iCloud-Erinnerungen über CalDAV; auf die neuen iCloud-Erinnerungen aktualisierte Listen sind dort nicht erreichbar). Der Wechsel wirkt nach einem Neustart. Zuerst das passende Ziel eintragen, dann den Dienst wechseln. | Nach Neustart |
| CalDAV-Aufgabenliste (Adresse) (`targets.caldav_task_url`) | Vollständige https-Adresse der CalDAV-Aufgabenliste (VTODO), z. B. https://cloud.example.org/remote.php/dav/calendars/anna/tasks/. Bei Apple Erinnerungen eine Adresse unter https://caldav.icloud.com. Bestehende Einträge werden nicht verschoben. Die Anlage erfordert weiterhin deine ausdrückliche Bestätigung. | Nach Neustart |
| CalDAV-Kalender (Adresse) (`targets.caldav_calendar_url`) | Vollständige https-Adresse der CalDAV-Kalendersammlung, z. B. https://cloud.example.org/remote.php/dav/calendars/anna/personal/. Nur bei Kalenderdienst caldav benötigt; Anmeldung mit CALDAV_USERNAME und App-Passwort CALDAV_PASSWORD. Bestehende Einträge werden nicht verschoben. Die Anlage erfordert weiterhin deine ausdrückliche Bestätigung. | Nach Neustart |
| Google-Kalender (`targets.google_calendar`) | ID des Zielkalenders für neue Terminvorschläge. primary bezeichnet den Hauptkalender; eine konkrete Kalender-ID wählt einen anderen zugänglichen Kalender. Bestehende Termine werden nicht verschoben. Nicht leer, höchstens 500 Zeichen. Die Anlage erfordert weiterhin deine ausdrückliche Bestätigung. | Nach Neustart |
| Kalenderdienst (`targets.calendar_provider`) | Dienst für neue Terminvorschläge: google (Google Kalender), caldav (z. B. Nextcloud, iCloud, mailbox.org) oder outlook (Outlook / Microsoft 365). Der Wechsel wirkt nach einem Neustart; bereits bestätigte Vorschläge für das bisherige Ziel werden nicht in das neue geschrieben. Zuerst das passende Ziel eintragen, dann den Dienst wechseln. Zugangsdaten unter Einstellungen → Zugangsdaten oder in der .env-Datei eintragen. | Nach Neustart |
| Microsoft-Mandant (`targets.microsoft_tenant`) | Microsoft-Mandant für die Anmeldung: common (private und geschäftliche Konten), consumers, organizations oder die Mandanten-ID. Gilt für Outlook-Kalender und Microsoft To Do. | Nach Neustart |
| Microsoft-To-Do-Liste (`targets.microsoft_todo_list`) | ID der Microsoft-To-Do-Liste oder default für die Standardliste „Aufgaben“. Nur bei Aufgabendienst microsoft_todo benötigt. Bestehende Einträge werden nicht verschoben. Die Anlage erfordert weiterhin deine ausdrückliche Bestätigung. | Nach Neustart |
| Outlook-Kalender (`targets.outlook_calendar`) | ID des Outlook-Kalenders oder default für den Standardkalender des angemeldeten Microsoft-Kontos. Nur bei Kalenderdienst outlook benötigt. Bestehende Einträge werden nicht verschoben. Die Anlage erfordert weiterhin deine ausdrückliche Bestätigung. | Nach Neustart |
| Todoist-Projekt (`targets.todoist_project`) | ID des Todoist-Projekts für neue Aufgabenvorschläge, nicht dessen Anzeigename. Eine andere ID lenkt neue Vorschläge in ein anderes Projekt; bestehende Aufgaben werden nicht verschoben. Nicht leer, höchstens 500 Zeichen. Die Anlage erfordert weiterhin deine ausdrückliche Bestätigung. | Nach Neustart |

## Aufrufbudget und Mailgrenzen

| Einstellung / Schlüssel | Wirkung und Werte | Übernahme |
| --- | --- | --- |
| KI-Aufrufe pro Minute (`limits.llm_calls_per_minute`) | Budget von 1–600 KI-Aufrufen pro Minute. Ein kleinerer Wert bremst die Verarbeitung und reduziert Lastspitzen; ein größerer erlaubt mehr Aufrufe, soweit Anbieter und übrige Grenzen dies zulassen. Dies ist keine feste Geld- oder Tageskostengrenze. | Nach Neustart |
| Maximale KI-Anfragegröße (Bytes) (`limits.max_llm_payload_bytes`) | Größengrenze für aufbereitete Maildaten an die KI: 1–100000000 Bytes, keine Tokenzahl; Standard 500000. Größere Werte erlauben mehr Inhalt und können Kosten und Laufzeit erhöhen. Zu große aufbereitete Inhalte werden abgewiesen; ein kleinerer Wert ist keine automatische Zusammenfassung. | Nach Neustart |
| Maximale Mailgröße (Bytes) (`limits.max_mail_bytes`) | Größengrenze für den Nachrichtentext ohne Anhänge: 1024–100000000 Bytes. Anhänge haben eine eigene Grenze für die Texterkennung. | Nach Neustart |
| Texterkennung: maximale Anhanggröße (Bytes) (`limits.max_attachment_bytes`) | Maximale Größe je Anhang für lokale Textextraktion und OCR: 1024–100000000 Bytes; Standard 5000000 Bytes (5 MB). Größere Anhänge werden nicht ausgewertet. Die Nachricht erhält immer einen Vorschlag zur manuellen Prüfung; weitere Nachrichten werden weiter abgerufen. | Nach Neustart |

## Zeitlimits und Wiederholungen

| Einstellung / Schlüssel | Wirkung und Werte | Übernahme |
| --- | --- | --- |
| Antworten verstehen: Versuche (`retries.interpretation_attempts`) | Gesamtzahl der Versuche beim Verstehen einer Telegram-Antwort: 1–20, einschließlich des ersten Versuchs. 1 erlaubt keinen erneuten Versuch; 3 erlaubt bis zu drei Versuche. Höhere Werte können vorübergehende KI-Fehler auffangen, verlängern aber die Verarbeitung und können mehr KI-Aufrufe verursachen. | Nach Neustart |
| Antworten verstehen: Wartezeit (s) (`retries.interpretation_backoff_seconds`) | Wartezeit vor einem erneuten Versuch beim Verstehen einer Telegram-Antwort: 1–86400 Sekunden. 60 bedeutet eine Minute, 300 fünf Minuten. Größere Werte geben dem Dienst mehr Erholungszeit und verzögern die Fortsetzung. Wenn nur ein Versuch erlaubt ist, entsteht keine Wiederholung. | Nach Neustart |
| CalDAV: erste Wartezeit (s) (`timeouts.caldav.initial_backoff_seconds`) | CalDAV: Erste Wartezeit vor einem Wiederholungsversuch: 0–30 Sekunden. 0 wartet zunächst nicht; größere Werte lassen dem Dienst mehr Erholungszeit. Weitere Wartezeiten steigen bis zur längsten Wartezeit. Ohne Wiederholungen hat dieser Wert keine Wirkung. | Nach Neustart |
| CalDAV: längste Wartezeit (s) (`timeouts.caldav.max_backoff_seconds`) | CalDAV: Obergrenze der Wartezeit zwischen Wiederholungsversuchen: 0–60 Sekunden und mindestens so groß wie die erste Wartezeit. Größere Werte erlauben längere Pausen, kleinere begrenzen die Verzögerung. Ohne Wiederholungen hat dieser Wert keine Wirkung. | Nach Neustart |
| CalDAV: Wiederholungen (`timeouts.caldav.retries`) | CalDAV: Zusätzliche Wiederholungen bei wiederholbaren Dienstfehlern: 0–10. 0 bedeutet nur den ersten Versuch, 2 erlaubt bis zu drei Versuche insgesamt. Mehr Wiederholungen können vorübergehende Fehler überbrücken, erhöhen aber Laufzeit und gegebenenfalls Kosten. Unklare externe Schreibresultate werden vor einer erneuten Anlage abgeglichen. | Nach Neustart |
| CalDAV: Zeitlimit (s) (`timeouts.caldav.timeout_seconds`) | CalDAV: Zeitlimit eines Aufrufversuchs: 1–300 Sekunden. Kleine Werte erkennen nicht antwortende Dienste schneller, können aber langsame Antworten abbrechen. Große Werte geben dem Dienst mehr Zeit und verlängern mögliche Wartezeiten. | Nach Neustart |
| Google Kalender: erste Wartezeit (s) (`timeouts.google_calendar.initial_backoff_seconds`) | Google Kalender: Erste Wartezeit vor einem Wiederholungsversuch: 0–30 Sekunden. 0 wartet zunächst nicht; größere Werte lassen dem Dienst mehr Erholungszeit. Weitere Wartezeiten steigen bis zur längsten Wartezeit. Ohne Wiederholungen hat dieser Wert keine Wirkung. | Nach Neustart |
| Google Kalender: längste Wartezeit (s) (`timeouts.google_calendar.max_backoff_seconds`) | Google Kalender: Obergrenze der Wartezeit zwischen Wiederholungsversuchen: 0–60 Sekunden und mindestens so groß wie die erste Wartezeit. Größere Werte erlauben längere Pausen, kleinere begrenzen die Verzögerung. Ohne Wiederholungen hat dieser Wert keine Wirkung. | Nach Neustart |
| Google Kalender: Wiederholungen (`timeouts.google_calendar.retries`) | Google Kalender: Zusätzliche Wiederholungen bei wiederholbaren Dienstfehlern: 0–10. 0 bedeutet nur den ersten Versuch, 2 erlaubt bis zu drei Versuche insgesamt. Mehr Wiederholungen können vorübergehende Fehler überbrücken, erhöhen aber Laufzeit und gegebenenfalls Kosten. Unklare externe Schreibresultate werden vor einer erneuten Anlage abgeglichen. | Nach Neustart |
| Google Kalender: Zeitlimit (s) (`timeouts.google_calendar.timeout_seconds`) | Google Kalender: Zeitlimit eines Aufrufversuchs: 1–300 Sekunden. Kleine Werte erkennen nicht antwortende Dienste schneller, können aber langsame Antworten abbrechen. Große Werte geben dem Dienst mehr Zeit und verlängern mögliche Wartezeiten. | Nach Neustart |
| IMAP: erste Wartezeit (s) (`timeouts.imap.initial_backoff_seconds`) | IMAP: Erste Wartezeit vor einem Wiederholungsversuch: 0–30 Sekunden. 0 wartet zunächst nicht; größere Werte lassen dem Dienst mehr Erholungszeit. Weitere Wartezeiten steigen bis zur längsten Wartezeit. Ohne Wiederholungen hat dieser Wert keine Wirkung. | Nach Neustart |
| IMAP: längste Wartezeit (s) (`timeouts.imap.max_backoff_seconds`) | IMAP: Obergrenze der Wartezeit zwischen Wiederholungsversuchen: 0–60 Sekunden und mindestens so groß wie die erste Wartezeit. Größere Werte erlauben längere Pausen, kleinere begrenzen die Verzögerung. Ohne Wiederholungen hat dieser Wert keine Wirkung. | Nach Neustart |
| IMAP: Wiederholungen (`timeouts.imap.retries`) | IMAP: Zusätzliche Wiederholungen bei wiederholbaren Dienstfehlern: 0–10. 0 bedeutet nur den ersten Versuch, 2 erlaubt bis zu drei Versuche insgesamt. Mehr Wiederholungen können vorübergehende Fehler überbrücken, erhöhen aber Laufzeit und gegebenenfalls Kosten. Unklare externe Schreibresultate werden vor einer erneuten Anlage abgeglichen. | Nach Neustart |
| IMAP: Zeitlimit (s) (`timeouts.imap.timeout_seconds`) | IMAP: Zeitlimit eines Aufrufversuchs: 1–300 Sekunden. Kleine Werte erkennen nicht antwortende Dienste schneller, können aber langsame Antworten abbrechen. Große Werte geben dem Dienst mehr Zeit und verlängern mögliche Wartezeiten. | Nach Neustart |
| Microsoft 365: erste Wartezeit (s) (`timeouts.microsoft.initial_backoff_seconds`) | Microsoft 365: Erste Wartezeit vor einem Wiederholungsversuch: 0–30 Sekunden. 0 wartet zunächst nicht; größere Werte lassen dem Dienst mehr Erholungszeit. Weitere Wartezeiten steigen bis zur längsten Wartezeit. Ohne Wiederholungen hat dieser Wert keine Wirkung. | Nach Neustart |
| Microsoft 365: längste Wartezeit (s) (`timeouts.microsoft.max_backoff_seconds`) | Microsoft 365: Obergrenze der Wartezeit zwischen Wiederholungsversuchen: 0–60 Sekunden und mindestens so groß wie die erste Wartezeit. Größere Werte erlauben längere Pausen, kleinere begrenzen die Verzögerung. Ohne Wiederholungen hat dieser Wert keine Wirkung. | Nach Neustart |
| Microsoft 365: Wiederholungen (`timeouts.microsoft.retries`) | Microsoft 365: Zusätzliche Wiederholungen bei wiederholbaren Dienstfehlern: 0–10. 0 bedeutet nur den ersten Versuch, 2 erlaubt bis zu drei Versuche insgesamt. Mehr Wiederholungen können vorübergehende Fehler überbrücken, erhöhen aber Laufzeit und gegebenenfalls Kosten. Unklare externe Schreibresultate werden vor einer erneuten Anlage abgeglichen. | Nach Neustart |
| Microsoft 365: Zeitlimit (s) (`timeouts.microsoft.timeout_seconds`) | Microsoft 365: Zeitlimit eines Aufrufversuchs: 1–300 Sekunden. Kleine Werte erkennen nicht antwortende Dienste schneller, können aber langsame Antworten abbrechen. Große Werte geben dem Dienst mehr Zeit und verlängern mögliche Wartezeiten. | Nach Neustart |
| Ollama: erste Wartezeit (s) (`timeouts.ollama.initial_backoff_seconds`) | Ollama: Erste Wartezeit vor einem Wiederholungsversuch: 0–30 Sekunden. 0 wartet zunächst nicht; größere Werte lassen dem Dienst mehr Erholungszeit. Weitere Wartezeiten steigen bis zur längsten Wartezeit. Ohne Wiederholungen hat dieser Wert keine Wirkung. | Nach Neustart |
| Ollama: längste Wartezeit (s) (`timeouts.ollama.max_backoff_seconds`) | Ollama: Obergrenze der Wartezeit zwischen Wiederholungsversuchen: 0–60 Sekunden und mindestens so groß wie die erste Wartezeit. Größere Werte erlauben längere Pausen, kleinere begrenzen die Verzögerung. Ohne Wiederholungen hat dieser Wert keine Wirkung. | Nach Neustart |
| Ollama: Wiederholungen (`timeouts.ollama.retries`) | Ollama: Zusätzliche Wiederholungen bei wiederholbaren Dienstfehlern: 0–10. 0 bedeutet nur den ersten Versuch, 2 erlaubt bis zu drei Versuche insgesamt. Mehr Wiederholungen können vorübergehende Fehler überbrücken, erhöhen aber Laufzeit und gegebenenfalls Kosten. Unklare externe Schreibresultate werden vor einer erneuten Anlage abgeglichen. | Nach Neustart |
| Ollama: Zeitlimit (s) (`timeouts.ollama.timeout_seconds`) | Ollama: Zeitlimit eines Aufrufversuchs: 1–1800 Sekunden. Kleine Werte erkennen nicht antwortende Dienste schneller, können aber langsame Antworten abbrechen. Große Werte geben dem Dienst mehr Zeit und verlängern mögliche Wartezeiten. | Nach Neustart |
| OpenRouter: erste Wartezeit (s) (`timeouts.openrouter.initial_backoff_seconds`) | OpenRouter: Erste Wartezeit vor einem Wiederholungsversuch: 0–30 Sekunden. 0 wartet zunächst nicht; größere Werte lassen dem Dienst mehr Erholungszeit. Weitere Wartezeiten steigen bis zur längsten Wartezeit. Ohne Wiederholungen hat dieser Wert keine Wirkung. | Nach Neustart |
| OpenRouter: längste Wartezeit (s) (`timeouts.openrouter.max_backoff_seconds`) | OpenRouter: Obergrenze der Wartezeit zwischen Wiederholungsversuchen: 0–60 Sekunden und mindestens so groß wie die erste Wartezeit. Größere Werte erlauben längere Pausen, kleinere begrenzen die Verzögerung. Ohne Wiederholungen hat dieser Wert keine Wirkung. | Nach Neustart |
| OpenRouter: Wiederholungen (`timeouts.openrouter.retries`) | OpenRouter: Zusätzliche Wiederholungen bei wiederholbaren Dienstfehlern: 0–10. 0 bedeutet nur den ersten Versuch, 2 erlaubt bis zu drei Versuche insgesamt. Mehr Wiederholungen können vorübergehende Fehler überbrücken, erhöhen aber Laufzeit und gegebenenfalls Kosten. Unklare externe Schreibresultate werden vor einer erneuten Anlage abgeglichen. | Nach Neustart |
| OpenRouter: Zeitlimit (s) (`timeouts.openrouter.timeout_seconds`) | OpenRouter: Zeitlimit eines Aufrufversuchs: 1–300 Sekunden. Kleine Werte erkennen nicht antwortende Dienste schneller, können aber langsame Antworten abbrechen. Große Werte geben dem Dienst mehr Zeit und verlängern mögliche Wartezeiten. | Nach Neustart |
| Telegram: erste Wartezeit (s) (`timeouts.telegram.initial_backoff_seconds`) | Telegram: Erste Wartezeit vor einem Wiederholungsversuch: 0–30 Sekunden. 0 wartet zunächst nicht; größere Werte lassen dem Dienst mehr Erholungszeit. Weitere Wartezeiten steigen bis zur längsten Wartezeit. Ohne Wiederholungen hat dieser Wert keine Wirkung. | Nach Neustart |
| Telegram: längste Wartezeit (s) (`timeouts.telegram.max_backoff_seconds`) | Telegram: Obergrenze der Wartezeit zwischen Wiederholungsversuchen: 0–60 Sekunden und mindestens so groß wie die erste Wartezeit. Größere Werte erlauben längere Pausen, kleinere begrenzen die Verzögerung. Ohne Wiederholungen hat dieser Wert keine Wirkung. | Nach Neustart |
| Telegram: Wiederholungen (`timeouts.telegram.retries`) | Telegram: Zusätzliche Wiederholungen bei wiederholbaren Dienstfehlern: 0–10. 0 bedeutet nur den ersten Versuch, 2 erlaubt bis zu drei Versuche insgesamt. Mehr Wiederholungen können vorübergehende Fehler überbrücken, erhöhen aber Laufzeit und gegebenenfalls Kosten. Unklare externe Schreibresultate werden vor einer erneuten Anlage abgeglichen. | Nach Neustart |
| Telegram: Zeitlimit (s) (`timeouts.telegram.timeout_seconds`) | Telegram: Zeitlimit eines Aufrufversuchs: 1–300 Sekunden. Kleine Werte erkennen nicht antwortende Dienste schneller, können aber langsame Antworten abbrechen. Große Werte geben dem Dienst mehr Zeit und verlängern mögliche Wartezeiten. | Nach Neustart |
| Todoist: erste Wartezeit (s) (`timeouts.todoist.initial_backoff_seconds`) | Todoist: Erste Wartezeit vor einem Wiederholungsversuch: 0–30 Sekunden. 0 wartet zunächst nicht; größere Werte lassen dem Dienst mehr Erholungszeit. Weitere Wartezeiten steigen bis zur längsten Wartezeit. Ohne Wiederholungen hat dieser Wert keine Wirkung. | Nach Neustart |
| Todoist: längste Wartezeit (s) (`timeouts.todoist.max_backoff_seconds`) | Todoist: Obergrenze der Wartezeit zwischen Wiederholungsversuchen: 0–60 Sekunden und mindestens so groß wie die erste Wartezeit. Größere Werte erlauben längere Pausen, kleinere begrenzen die Verzögerung. Ohne Wiederholungen hat dieser Wert keine Wirkung. | Nach Neustart |
| Todoist: Wiederholungen (`timeouts.todoist.retries`) | Todoist: Zusätzliche Wiederholungen bei wiederholbaren Dienstfehlern: 0–10. 0 bedeutet nur den ersten Versuch, 2 erlaubt bis zu drei Versuche insgesamt. Mehr Wiederholungen können vorübergehende Fehler überbrücken, erhöhen aber Laufzeit und gegebenenfalls Kosten. Unklare externe Schreibresultate werden vor einer erneuten Anlage abgeglichen. | Nach Neustart |
| Todoist: Zeitlimit (s) (`timeouts.todoist.timeout_seconds`) | Todoist: Zeitlimit eines Aufrufversuchs: 1–300 Sekunden. Kleine Werte erkennen nicht antwortende Dienste schneller, können aber langsame Antworten abbrechen. Große Werte geben dem Dienst mehr Zeit und verlängern mögliche Wartezeiten. | Nach Neustart |
| Überarbeitung: Versuche (`retries.revision_attempts`) | Gesamtzahl der Versuche beim Überarbeiten eines Vorschlags: 1–20, einschließlich des ersten Versuchs. 1 erlaubt keinen erneuten Versuch; 3 erlaubt bis zu drei Versuche. Höhere Werte können vorübergehende KI-Fehler auffangen, verlängern aber die Verarbeitung und können mehr KI-Aufrufe verursachen. | Nach Neustart |
| Überarbeitung: Wartezeit (s) (`retries.revision_backoff_seconds`) | Wartezeit vor einem erneuten Versuch beim Überarbeiten eines Vorschlags: 1–86400 Sekunden. 60 bedeutet eine Minute, 300 fünf Minuten. Größere Werte geben dem Dienst mehr Erholungszeit und verzögern die Fortsetzung. Wenn nur ein Versuch erlaubt ist, entsteht keine Wiederholung. | Nach Neustart |

## Originalanhänge

| Einstellung / Schlüssel | Wirkung und Werte | Übernahme |
| --- | --- | --- |
| Höchstgröße je Datei (Bytes) (`attachments.max_original_bytes`) | Größte Datei, die als Original gespeichert wird: 1024–104857600 Bytes (Standard 26214400 Bytes = 25 MiB). Größere Anhänge bleiben nur im Postfach. | Nach Neustart |
| Höchstgröße je Mail (Bytes) (`attachments.max_total_bytes`) | Höchstens so viele Bytes an Originalen je Mail: 1024–524288000 (Standard 50 MB). Weitere Anhänge derselben Mail werden nicht gespeichert. | Nach Neustart |
| Originale speichern (`attachments.store_originals`) | ja (true) speichert Originaldokumente (PDF, Word, Excel, OpenDocument, Text, Bilder) neu verarbeiteter Mails zum Herunterladen in der Weboberfläche. nein (false) speichert nur Bildvorschauen. Gespeicherte Originale werden mit der Aufbewahrungsfrist für Mailinhalte gelöscht. | Nach Neustart |

## Aufbewahrung

| Einstellung / Schlüssel | Wirkung und Werte | Übernahme |
| --- | --- | --- |
| Analysen aufbewahren (Tage) (`retention.analysis_days`) | Aufbewahrung archivierter Analysen. null übernimmt die Frist für KI-Diagnosedaten (debug_llm_days). 1–3650 bedeutet volle Tage seit der letzten Aktualisierung des abgeschlossenen Vorgangs. Kleinere Werte entfernen Inhalte früher. disabled entfernt sie beim nächsten Bereinigungslauf, unlimited bewahrt sie ohne Frist auf. Offene Vorgänge bleiben geschützt. Entfernte Inhalte lassen sich durch späteres Verlängern der Frist nicht wiederherstellen. | Im laufenden Betrieb |
| KI-Diagnosedaten aufbewahren (Tage) (`retention.debug_llm_days`) | Aufbewahrung von KI-Diagnosedaten im Vorgang, etwa Zusammenfassung und Validierungsfehlern; separate JSONL-Logdateien haben eigene Fristen. 1–3650 bedeutet volle Tage seit der letzten Aktualisierung des abgeschlossenen Vorgangs. Kleinere Werte entfernen Inhalte früher. disabled entfernt sie beim nächsten Bereinigungslauf, unlimited bewahrt sie ohne Frist auf. Offene Vorgänge bleiben geschützt. Entfernte Inhalte lassen sich durch späteres Verlängern der Frist nicht wiederherstellen. | Im laufenden Betrieb |
| Mailtexte aufbewahren (Tage) (`retention.full_mail_days`) | Aufbewahrung gespeicherter Mailtexte, Bildvorschauen und lokaler Entwurfstexte; die Originalmail im Postfach wird nicht gelöscht. Standard 30 Tage. 1–3650 bedeutet volle Tage seit der letzten Aktualisierung des abgeschlossenen Vorgangs. Kleinere Werte entfernen Inhalte früher. disabled entfernt sie beim nächsten Bereinigungslauf, unlimited bewahrt sie ohne Frist auf. Offene Vorgänge bleiben geschützt. Entfernte Inhalte lassen sich durch späteres Verlängern der Frist nicht wiederherstellen. | Im laufenden Betrieb |
| Verlauf aufbewahren (Tage) (`retention.history_days`) | Aufbewahrung des Vorgangsverlaufs und der Inhalte historischer Vorschlagsversionen; Kennungen zum Schutz vor Doppelanlagen bleiben erhalten. Standard 90 Tage. 1–3650 bedeutet volle Tage seit der letzten Aktualisierung des abgeschlossenen Vorgangs. Kleinere Werte entfernen Inhalte früher. disabled entfernt sie beim nächsten Bereinigungslauf, unlimited bewahrt sie ohne Frist auf. Offene Vorgänge bleiben geschützt. Entfernte Inhalte lassen sich durch späteres Verlängern der Frist nicht wiederherstellen. | Im laufenden Betrieb |
| Tätigkeitsberichte aufbewahren (Tage) (`retention.activity_report_days`) | Aufbewahrung gespeicherter Tätigkeitsberichte und ihrer Exporte; das Postfach bleibt unverändert. 1–3650 bedeutet volle Tage seit der letzten Aktualisierung des abgeschlossenen Vorgangs. Kleinere Werte entfernen Inhalte früher. disabled entfernt sie beim nächsten Bereinigungslauf, unlimited bewahrt sie ohne Frist auf. Offene Vorgänge bleiben geschützt. Entfernte Inhalte lassen sich durch späteres Verlängern der Frist nicht wiederherstellen. | Im laufenden Betrieb |
| Lernbestand der Entscheidungen aufbewahren (Tage) (`retention.decision_learning_days`) | Aufbewahrung des Lernbestands manueller Entscheidungen (Mail, KI-Ergebnisse, Vorschlag vorher und nachher): 1–3650 bedeutet volle Tage seit der Entscheidung. unlimited (Standard) bewahrt ohne Frist auf, disabled zeichnet nichts mehr auf und leert den Bestand beim nächsten Bereinigungslauf. Entfernte Datensätze lassen sich nicht wiederherstellen. | Im laufenden Betrieb |
| Bereinigung alle (Minuten) (`retention.cleanup_interval_minutes`) | Abstand der Aufbewahrungsbereinigung in Minuten: 0–1440; Standard 60. Die Bereinigung läuft im Verarbeitungsablauf und hält währenddessen Mailabruf und Web-Aktionen kurz an. 0 bereinigt bei jedem Abrufzyklus; größere Werte entfernen abgelaufene Inhalte entsprechend später. | Im laufenden Betrieb |

## Protokollierung

| Einstellung / Schlüssel | Wirkung und Werte | Übernahme |
| --- | --- | --- |
| Konsole: Mindeststufe (`logging.console.level`) | Mindeststufe der Konsolenmeldungen: DEBUG zeigt auch Diagnoseangaben, INFO den normalen Ablauf, WARNING nur Warnungen und schwerere Meldungen, ERROR Fehler und CRITICAL nur schwerste Fehler. Höhere Stufen reduzieren die Ausgabe und erschweren die Fehlersuche. Inhaltsprotokolle werden separat gesteuert. | Nach Neustart |
| Logdatei: Mindeststufe (`logging.file.level`) | Mindeststufe der allgemeinen Logdatei: DEBUG enthält Diagnoseangaben, INFO den normalen Ablauf, WARNING Warnungen und schwerere Meldungen, ERROR Fehler und CRITICAL nur schwerste Fehler. Höhere Stufen reduzieren die Datenmenge. Separate KI-Inhaltslogs werden damit nicht aktiviert oder deaktiviert. | Nach Neustart |
| KI-Anfragen vollständig protokollieren (`logging.llm.include_requests`) | ja (true) erlaubt vollständige KI-Anfragen im separaten KI-Log, sofern dieses aktiviert ist. Das kann Prompts und private Mailinhalte speichern und benötigt mehr Speicher. nein (false) lässt die vollständigen Anfrageinhalte weg. Bereits geschriebene Logs werden dadurch nicht gelöscht. | Nach Neustart |
| KI-Antworten vollständig protokollieren (`logging.llm.include_responses`) | ja (true) erlaubt vollständige KI-Antworten im separaten KI-Log, sofern dieses aktiviert ist. Das hilft bei der Fehlersuche, kann aber private Inhalte speichern. nein (false) lässt vollständige Antwortinhalte weg. Bereits geschriebene Logs werden dadurch nicht gelöscht. | Nach Neustart |
| Konsolenausgabe aktivieren (`logging.console.enabled`) | ja (true) schreibt Meldungen ins Terminal bzw. in das Containerprotokoll. nein (false) unterdrückt die Konsolenausgabe; die Logdatei bleibt davon unberührt. | Nach Neustart |
| Logdatei aktivieren (`logging.file.enabled`) | ja (true) schreibt die allgemeine Logdatei im Logverzeichnis. nein (false) schreibt keine allgemeine Logdatei; die Fehlersuche wird dadurch erschwert. | Nach Neustart |
| KI-Log aktivieren (`logging.llm.enabled`) | ja (true) schreibt das separate KI-Log mit Aufrufmetadaten; vollständige Inhalte nur, wenn zusätzlich Anfragen oder Antworten freigegeben sind. nein (false) schreibt kein KI-Log. | Nach Neustart |
| KI-Log: Mindeststufe (`logging.llm.level`) | Mindeststufe des KI-Logs: DEBUG enthält Diagnoseangaben, INFO den normalen Ablauf, WARNING Warnungen und schwerere Meldungen, ERROR Fehler und CRITICAL nur schwerste Fehler. Höhere Stufen reduzieren die Datenmenge. | Nach Neustart |
| Telegram-Log aktivieren (`logging.telegram.enabled`) | ja (true) schreibt ein separates Prüfprotokoll der Telegram-Nachrichten einschließlich Inhalten. nein (false) verzichtet darauf; Zustellungen bleiben im allgemeinen Log ohne Inhalte sichtbar. | Nach Neustart |
| Telegram-Log: Mindeststufe (`logging.telegram.level`) | Mindeststufe des Telegram-Logs: DEBUG enthält Diagnoseangaben, INFO den normalen Ablauf, WARNING Warnungen und schwerere Meldungen, ERROR Fehler und CRITICAL nur schwerste Fehler. | Nach Neustart |

## Kosten und Messung

| Einstellung / Schlüssel | Wirkung und Werte | Übernahme |
| --- | --- | --- |
| Strompreis (EUR/kWh) (`metrics.electricity_eur_per_kwh`) | Strompreis für lokale KI-Kostenschätzungen: 0–100 EUR/kWh. 0.30 bedeutet 30 Cent je kWh. Ein höherer Preis erhöht die Schätzung proportional; 0 ergibt keine geschätzten Stromkosten. Der Wert beeinflusst weder Cloudpreise noch den Stromverbrauch. | Im laufenden Betrieb |
| Metrikerfassung aktivieren (`metrics.enabled`) | ja (true) erfasst Messwerte zu KI-Aufrufen, Laufzeiten und Kosten ohne Mailinhalte. nein (false) stoppt neue Messungen; bereits erfasste Werte bleiben bis zur Bereinigung vorhanden. Diese Einstellung schaltet weder KI-Aufrufe noch die allgemeinen Logs ab. | Im laufenden Betrieb |
| Wechselkurs vom (`metrics.exchange_rate_date`) | Bezugsdatum des manuell gepflegten Wechselkurses im Format JJJJ-MM-TT, z. B. 2026-10-12. null lässt das Datum offen. Es kennzeichnet die Aktualität des Kurses und verändert den Umrechnungsfaktor nicht. Ein Datum ist nur mit gesetztem Wechselkurs erlaubt. | Im laufenden Betrieb |
| Ollama-Leistung (Watt) (`metrics.ollama_power_watts`) | Angenommene Leistungsaufnahme während lokaler KI-Aufrufe: 0–100000 Watt. 300 steht für 300 W; doppelte Leistung ergibt bei gleicher Dauer doppelte geschätzte Stromkosten. 0 ergibt keine geschätzten Stromkosten. Dies misst oder begrenzt die tatsächliche Hardwareleistung nicht. | Im laufenden Betrieb |
| Einzelmessungen aufbewahren (Tage) (`metrics.retention_days`) | Aufbewahrung einzelner Messungen: 1–3650 Tage. 30 hält ungefähr einen Monat, 90 ungefähr drei Monate vor. Kürzere Fristen sparen Speicher, schränken aber rückblickende Auswertungen ein. Ältere Messungen werden bereinigt; disabled und unlimited sind hier nicht erlaubt. | Im laufenden Betrieb |
| Wechselkurs (USD je EUR) (`metrics.usd_per_eur`) | US-Dollar je Euro, größer als 0: Bei 1.1 werden 11 USD als 10 EUR angezeigt. Ein höherer Kurs ergibt für denselben Dollarbetrag weniger Euro. null deaktiviert die Euro-Umrechnung; dann muss auch das Kursdatum null sein. Der Kurs wird manuell gepflegt, nicht automatisch abgerufen. | Im laufenden Betrieb |

## Telegram

| Einstellung / Schlüssel | Wirkung und Werte | Übernahme |
| --- | --- | --- |
| Telegram: berechtigte Benutzer-ID (`telegram.user_id`) | Numerische Telegram-ID des einzigen Kontos, dessen Eingaben Mailhelp annimmt; größer als 0. Nachrichten anderer Konten werden ignoriert. Eine falsche ID sperrt die Bedienung über Telegram aus; die Weboberfläche bleibt nutzbar. | Nach Neustart |
| Telegram: Chat für Nachrichten (`telegram.chat_id`) | Numerische ID des Chats, in den Mailhelp schreibt; bei einem Privatchat meist gleich der Benutzer-ID. Eine falsche ID führt zu Zustellfehlern; Diagnose und --check-access melden sie und nennen gefundene Chats. | Nach Neustart |
| Telegram: Entscheidungen nacheinander (`telegram.sequential_questions`) | ja (true) zeigt jeweils nur die aktuelle Entscheidung mit Schaltflächen; weitere folgen nacheinander. nein (false) sendet alle offenen Vorschläge sofort. Nacheinander verhindert verwechselte Antworten, wenn viele Fragen gleichzeitig offen sind. | Nach Neustart |

## Bildauswertung

| Einstellung / Schlüssel | Wirkung und Werte | Übernahme |
| --- | --- | --- |
| Bildanhänge und Scans auswerten (`vision.enabled`) | ja (true) lässt Bildanhänge und gescannte PDFs vom KI-Modell lesen (Schritt vision_ocr in prompts.yaml), damit Termine und Aufgaben darin erkannt werden; die Bilder werden dafür übertragen und verursachen Kosten. nein (false) wertet nur Text aus. | Nach Neustart |
| Bildauswertung: Bilder je Mail (`vision.max_images_per_mail`) | Höchstens so viele Bilder je Mail werden ausgewertet: 1–10; Standard 3. Mehr Bilder erfassen umfangreiche Scans vollständiger und erhöhen Kosten und Laufzeit. | Nach Neustart |
| Bildauswertung: Höchstgröße je Bild (Bytes) (`vision.max_image_bytes`) | Zusätzliche Größengrenze für die Bildauswertung: 10240–50000000 Bytes; Standard 5000000 (5 MB). Die Texterkennungsgrenze limits.max_attachment_bytes gilt zusätzlich; bei ihrer Überschreitung entsteht eine manuelle Prüfaufgabe. | Nach Neustart |
| Bildauswertung: längste Kante (Pixel) (`vision.max_edge_pixels`) | Bilder werden vor der Übertragung auf diese längste Kante verkleinert: 512–4096 Pixel; Standard 1600. Größere Werte erhalten feine Schrift besser und erhöhen Datenmenge und Kosten. | Nach Neustart |

## Tagesüberblick

| Einstellung / Schlüssel | Wirkung und Werte | Übernahme |
| --- | --- | --- |
| Tagesüberblick: Termine (`daily_briefing.include_calendar`) | ja (true) nimmt die heutigen Termine des Zielkalenders in den Tagesüberblick auf. nein (false) lässt sie weg. Wirkt nur bei aktiviertem Tagesüberblick. | Nach Neustart |
| Tagesüberblick: Aufgaben (`daily_briefing.include_tasks`) | ja (true) nimmt fällige Aufgaben der Aufgabenliste in den Tagesüberblick auf. nein (false) lässt sie weg. Wirkt nur bei aktiviertem Tagesüberblick. | Nach Neustart |
| Tagesüberblick: offene Entscheidungen (`daily_briefing.include_open`) | ja (true) nennt im Tagesüberblick die offenen Vorschläge und Rückfragen. nein (false) lässt sie weg. Wirkt nur bei aktiviertem Tagesüberblick. | Nach Neustart |

## Tätigkeitsberichte

| Einstellung / Schlüssel | Wirkung und Werte | Übernahme |
| --- | --- | --- |
| Tätigkeitsberichte aktivieren (`activity_report.enabled`) | ja (true) erlaubt Tätigkeitsberichte in der Weboberfläche: ein reiner Lesedurchlauf durch ein Postfach zu einem Thema mit XLSX-Export; benötigt die Schritte activity_relevance und activity_events in prompts.yaml. nein (false) blendet die Funktion aus. | Nach Neustart |
| Tätigkeitsbericht: höchstens Mails (`activity_report.max_mails`) | Ein Bericht pausiert nach so vielen gelesenen Mails: 1–20000; Standard 2000. Größere Werte erfassen längere Zeiträume und erhöhen Laufzeit und KI-Kosten. | Nach Neustart |
| Tätigkeitsbericht: höchstens KI-Aufrufe (`activity_report.max_llm_calls`) | Ein Bericht pausiert nach so vielen KI-Aufrufen: 1–50000; Standard 3000. Die Grenze schützt vor unerwartet hohen Kosten; ein pausierter Bericht lässt sich fortsetzen. | Nach Neustart |
| Tätigkeitsbericht: Anteil am KI-Budget (`activity_report.max_share_of_llm_budget`) | Anteil von limits.llm_calls_per_minute, den ein laufender Bericht nutzen darf: größer als 0 bis 1; Standard 0.5. Kleinere Werte lassen der normalen Mailverarbeitung mehr Spielraum und verlangsamen den Bericht. | Nach Neustart |
| Tätigkeitsbericht: Zeichen je Volltext (`activity_report.max_fulltext_chars`) | Volltexte im Export werden auf so viele Zeichen gekürzt: 1000–32000; Standard 30000, passend zur Zellgrenze von Excel. | Nach Neustart |
| Tätigkeitsbericht: Mails ohne Termine exportieren (`activity_report.export_mails_without_events`) | ja (true) exportiert auch relevante Mails ohne erkannte Termine. nein (false) exportiert nur Mails mit erkannten Terminen. | Nach Neustart |

## Lernmodus

| Einstellung / Schlüssel | Wirkung und Werte | Übernahme |
| --- | --- | --- |
| Lernmodus: parallele KI-Aufrufe (`learning.parallel_llm_calls`) | Gleichzeitige KI-Aufrufe im Lernmodus (--learn): 1–100; Standard 4. Mehr parallele Aufrufe beschleunigen das Lernen und erhöhen Lastspitzen; das Minutenbudget limits.llm_calls_per_minute gilt weiterhin. | Nach Neustart |
| Lernbestand: vollständige KI-Inhalte übernehmen (`learning.decision_llm_content`) | ja (true) übernimmt vollständige KI-Anfragen und -Antworten aus dem KI-Log in jeden Datensatz des Entscheidungs-Lernbestands; sie sind nur vorhanden, wenn das KI-Log diese Inhalte protokolliert. nein (false, Standard) speichert nur die Aufruf-IDs. | Nach Neustart |

## Weboberfläche

| Einstellung / Schlüssel | Wirkung und Werte | Übernahme |
| --- | --- | --- |
| Web: Sitzungsdauer (Tage) (`web.session_days`) | So lange bleibt ein gekoppeltes Gerät angemeldet, bevor es neu gekoppelt werden muss: 1–365 Tage; Standard 30. Kürzere Werte verringern das Risiko verlorener Geräte, längere ersparen Kopplungen. | Nach Neustart |
| Web: Zugriff im eigenen Netzwerk (`web.lan_access`) | ja (true) macht die Weboberfläche im eigenen WLAN unter der privaten IP-Adresse des PCs erreichbar (unverschlüsseltes HTTP); erfordert web.host 0.0.0.0, sonst wird die Änderung abgelehnt. nein (false) beschränkt den Zugriff auf diesen PC und die freigegebenen Adressen. | Nach Neustart |

## Hilfschat

Ab 5.4.1 entfernt **Chat leeren** auch Fragetexte und Feldbezüge aus gespeicherten Aufträgen.
Nur inhaltsfreie Auftragskennungen, Status und Hashes bleiben gegen doppelte Übertragung erhalten.
Früher geleerte Altbestände werden beim nächsten Start bereinigt. Ein ausgeschalteter Hilfschat
startet auch für wartende Fragen und Wiederholungen keinen weiteren Modellaufruf.

Die Suche findet auch Datei- und Einrichtungseinstellungen, etwa `web.port` und
`reanalysis.max_jobs_per_day`. Solche Treffer nennen den Bedienweg und öffnen die passende
mitgelieferte Dokumentation; sie bieten kein Webformular zum Ändern eines Dateiwerts.

**Hilfe zu Einstellungen** beantwortet Fragen zur Bedeutung von Einstellungen und zu
Bedienabläufen. Auf allen Einstellungsseiten öffnet das runde Chatsymbol unten rechts (auf dem
Handy über der unteren Leiste) den Chat. „Dazu fragen“ an einer Einstellung oder einem Treffer
der Sofortsuche öffnet dasselbe kleine Fenster mit diesem Bezug. Die Einstellungsseite bleibt
bedienbar. Suche, Bereichswechsel, Bearbeiten, Bestätigen und Speichern schließen das Fenster
nicht. Alte `/hilfe`-Links öffnen es auf der Einstellungsübersicht. Jede Frage wird ausdrücklich mit **Frage senden** abgeschickt; Tippen,
Suchen und Hilfetexte lösen nie einen KI-Aufruf aus.

- **Quellen:** Mailhelp wählt höchstens sechs passende Abschnitte der mitgelieferten
  Dokumentation aus und schickt sie mit der Frage und dem kurzen Verlauf (höchstens zehn Fragen)
  über die aktive KI-Anbindung (Schritt `settings_help`, gleiches Modell wie `action_router`).
  Im Fenster erscheint zuerst eine Kurzantwort in ein bis zwei Sätzen; **Ausführliche Antwort
  anzeigen** klappt die vollständige Anleitung auf. Beide Fassungen entstehen im selben KI-Aufruf.
  Die KI schreibt sie als Markdown; das Fenster zeigt nummerierte Schritte, Aufzählungen,
  **Fettdruck**, `Code` und Zwischenüberschriften formatiert an. HTML, Bilder und Links aus der
  Antwort werden nie übernommen; die geprüften Quellen stehen darunter.
  Unter jeder Antwort stehen die verwendeten Abschnitte und Einstellungen als Links; ohne passende
  Abschnitte antwortet Mailhelp selbst, ohne KI-Aufruf, und bittet um eine genauere Frage.
- **Grenzen:** Der Chat ändert nichts – keine Einstellungen, Konten, Kalender oder Nachrichten.
  Auch auf die Bitte „Stell das für mich um“ gibt er nur eine Anleitung.
- **Datenschutz und Kosten:** Frage, Verlauf und Dokumentationsausschnitte gehen an den
  KI-Anbieter und verursachen Kosten wie andere Abfragen, auch im Testmodus. Bekannte
  Zugangsdaten aus `.env` werden vorher entfernt; Passwörter oder Tokens nicht eintippen.
  Aktuelle Einstellungswerte werden nie mitgeschickt. Im Fenster steht dieser Hinweis
  eingeklappt unter **Kostenpflichtig**; ein Klick oder die Eingabetaste klappt ihn auf.
- **Aufbewahrung:** Der Verlauf gehört zur Sitzung und wird beim Abmelden, Widerrufen oder nach
  24 Stunden ohne Aktivität gelöscht; **Chat leeren** löscht ihn sofort. Protokolle enthalten
  Fragen und Antworten nur bei eingeschalteter Inhaltsprotokollierung.
- **Fenster bedienen:** Den Kopf ziehen, um das Fenster zu verschieben, und an einem Rand oder
  einer Ecke ziehen, um die Größe zu ändern (mindestens 280 × 180 Pixel, höchstens bis zum
  Bildschirmrand). Per Tastatur den Titel „Hilfe zu Einstellungen“ fokussieren: Pfeiltasten
  verschieben, Umschalt+Pfeiltasten ändern die Größe. Die Größe merkt sich der Browser-Tab. **Hilfschat schließen** blendet es aus, ohne Verlauf oder Entwurf zu löschen.
  **Chat leeren** verwirft beides und hält das Fenster offen. Klicken außerhalb und Escape
  schließen es nicht. Quellen lassen sich im Fenster lesen; **Zurück zum Gespräch** kehrt zurück.
- **Entwurf und Position:** Im JavaScript-Betrieb merkt sich der aktuelle Browser-Tab den
  Zustand, die Leseposition im Gespräch und die ungesendete Frage in `sessionStorage`, begrenzt auf Sitzung und höchstens
  24 Stunden. Keine Tokens eingeben; dies ist keine Geheimnisablage. Der Gesprächsverlauf bleibt
  serverseitig an die Sitzung gebunden. Zwei Tabs haben eigene Fenster und Entwürfe, aber denselben
  Verlauf. Beim Abmelden oder bei ungültiger Sitzung wird die lokale Kopie entfernt.
- **Ohne Browserspeicher/JavaScript:** Ein serverseitiger Zustand erhält das geöffnete Fenster.
  Ohne JavaScript bleibt eine ungesendete Frage bei einem Seitenwechsel nicht erhalten; eine neue
  Antwort erscheint beim nächsten Seitenaufruf oder Neuladen. Das Fenster lässt sich dann nicht
  verschieben; verdeckt es eine Schaltfläche, das Suchfeld mit der Eingabetaste absenden oder das
  Fenster schließen. Die Einstellungsseite wird wegen einer Chatantwort nicht automatisch
  neu geladen. Bei gesperrtem Browserspeicher sichert JavaScript den Entwurf vor Navigation;
  scheitert die Sicherung, bleibt die aktuelle Seite erhalten und zeigt den Fehler.
- **Ablauf:** Pro Chat läuft eine Frage; mit JavaScript wird nur das Fenster aktualisiert.
  Nach einem Neustart sind offene Fragen „unterbrochen“ und werden nicht
  erneut gesendet. Ohne den Schritt `settings_help` in `prompts.yaml` nennt der Chat einen
  Einrichtungshinweis.

| Einstellung / Schlüssel | Wirkung und Werte | Übernahme |
| --- | --- | --- |
| Hilfschat anbieten (`help_chat.enabled`) | ja (true) bietet den Hilfschat an: Er erklärt Einstellungen und Bedienwege mit der mitgelieferten Dokumentation über die aktive KI-Anbindung; Frage, kurzer Verlauf und passende Abschnitte gehen dafür an den KI-Anbieter und verursachen Kosten. nein (false) nimmt keine neuen Fragen an; die Dokumentation bleibt lesbar. Standard ja. | Im laufenden Betrieb |
| Hilfschat: längste Frage (Zeichen) (`help_chat.max_question_chars`) | Längste Frage an den Hilfschat: 100–8000 Zeichen; Standard 4000. Längere Fragen werden mit Hinweis abgewiesen, nicht gekürzt. | Im laufenden Betrieb |
| Hilfschat: Dokumentation je Frage (Bytes) (`help_chat.max_context_bytes`) | Höchstens so viele Bytes Dokumentation gehen je Frage mit: 2000–48000; Standard 24000. Mehr Kontext kann Antworten vollständiger machen und erhöht Kosten. | Im laufenden Betrieb |
| Hilfschat: Fragen je Minute (`help_chat.requests_per_minute_per_session`) | Neue Fragen je Sitzung und Minute: 1–20; Standard 6. Das globale KI-Aufruflimit gilt zusätzlich; eine wiederholte Abfrage derselben Frage zählt nicht. | Im laufenden Betrieb |

## Weitere Hinweise

| Bereich | Erklärung |
| --- | --- |
| Modelle (nur lesend) | Die Tabelle zeigt die tatsächlich verwendeten KI-Modelle, Parameter und deren Quelle. Andere Modelle können Qualität, Geschwindigkeit und Kosten verändern. Parameter und Modelle werden in prompts.yaml gepflegt; ein Start mit --ollama kann die Modellwahl ersetzen. Hier ist die Anzeige nur lesbar. |
| Benachrichtigungen | Push aktivieren meldet diesen Browser für inhaltsneutrale Hinweise an; Mailbetreff und Mailtext werden nicht übertragen. Push deaktivieren beendet das Abonnement dieses Browsers. Andere Geräte bleiben unverändert. Die Funktion benötigt serverseitig aktiviertes Web-Push und deine Browserfreigabe; HTTPS oder localhost ist erforderlich. |


## Termindauern und Vorschlagsabgleich (2.4)

| Einstellung | Wirkung |
| --- | --- |
| `event_defaults.video_duration_minutes` · Standarddauer Videokonferenz (Minuten) | Standarddauer Videokonferenz: 1–1440 Minuten; Standard 60. Ergänzt ein fehlendes Ende nur bei eindeutigem Beginn und belegter Online-Teilnahme. Explizite Endzeiten und Dauern haben Vorrang. Bestehende Vorschläge werden nicht automatisch umgerechnet; Speichern autorisiert keine Kalenderaktion. |
| `event_defaults.in_person_duration_minutes` · Standarddauer Präsenztermin (Minuten) | Standarddauer Präsenztermin: 1–1440 Minuten; Standard 180. Ergänzt ein fehlendes Ende bei belegter Präsenz und eindeutigem Beginn. Eine Anschrift in der Signatur belegt keine Präsenz. Explizite Zeitangaben haben Vorrang; die Annahme wird im Vorschlag angezeigt. |
| `proposal_reconciliation.max_semantic_candidates` · Abgleich: höchstens KI-Kandidaten | 1–50 mögliche offene Vorschläge je semantischem KI-Vergleich; Standard 8. Weitere plausible Treffer blockieren die automatische Zuordnung, statt als fehlende Dublette zu gelten. Ein fehlender Vergleichsprompt erfordert bei unklaren Fällen eine manuelle Zuordnung. |

## IServ-Konten (3.3.10)

Unter `/einstellungen/iserv` werden IServ-Konten für Elternbriefe angelegt, geändert, aktiviert,
deaktiviert und entfernt. Je Konto: Anzeigename, HTTPS-Adresse der Schule (ein kopierter IServ-Link
oder die Adresse ohne `https://` wird auf die Schuladresse gekürzt), das Postfach, dessen Zielprofil
und Standards gelten, und optional die Startgrenze (`TT.MM.JJJJ [HH:MM]` oder ISO 8601; leer: die des
Postfachs). Ungültige Angaben nennt die Seite mit ihrer Ursache.
Jede Änderung ist ein Entwurf; übernommen wird nach aktueller Diagnose `iserv` und ausdrücklicher
Bestätigung. Elternbriefe gelten immer als relevant. Die Zugangsdaten gehören auf die Seite
Zugangsdaten. Wirkung nach dem nächsten Neustart.

## Zugangsdaten (3.3.11)

`/einstellungen/zugangsdaten` zeigt für jeden benötigten Eintrag nur „hinterlegt“ oder „fehlt“ und
nimmt neue Werte nur schreibend an: `IMAP_<n>_USERNAME/_PASSWORD` je Postfach (bei Postfach 1 im
älteren Format `IMAP_USERNAME/_PASSWORD`), `ISERV_<n>_USERNAME/_PASSWORD` je IServ-Konto,
`OPENROUTER_API_KEY`, `TELEGRAM_BOT_TOKEN` bei aktivem Telegram und die Geheimnisse der Kalender- und
Aufgabendienste je Zielprofil. Jede Änderung wird ausdrücklich bestätigt; ersetzt wird nur die
betroffene Zeile in `.env`. `MAILHELP_WEB_SECRET` bleibt ausgenommen. Werte aus der Prozessumgebung
haben Vorrang und werden als solche gekennzeichnet. Diagnose und Einrichtung lesen neue Werte
sofort, der Mailabruf nach dem nächsten Neustart.

## Postfächer und Zielprofile (3.2)

Unter `/einstellungen/postfaecher` zeigt jedes Postfach die Tabs Ziele, Filter, Themen, Antworten
und Benachrichtigungen. Nicht belegte Felder erben global; Zurücksetzen entfernt die lokale Regel.
Profil 1 ist der bestehende `targets`-Abschnitt; weitere Profile verwaltet `/einstellungen/zielprofile`.
Verwendete Profile lassen sich erst nach Auflösen aller angezeigten Verweise entfernen.

| Lokale Einstellung | Wirkung |
| --- | --- |
| `target_profile` | ID 1–99 eines konfigurierten Profils; gilt nach Neustart für neue Vorschläge. Bestehende Vorschläge bleiben gebunden. |
| `personal_info`, `smart_reply` | Eigene Rolle/Signatur und Antwortentwürfe für dieses Postfach; Speicherung bleibt im Ursprungspostfach. |
| `notifications.quiet_hours`, `notifications.categories` | Vererbte Ruhezeiten und Kategoriekanäle; gemeinsame Queue mit getrennten Postfachbündeln. |
| `daily_briefing` | Dieses Postfach als eigenen Abschnitt ein-/ausschließen. |
| `activity_report_folder` | Vorausgewählter Ordner für Tätigkeitsberichte. |
| `retention.full_mail_days` | Volltexte kürzer aufbewahren als global; `disabled` entfernt Inhalte, `unlimited` nur bei global unbegrenzter Aufbewahrung. |
| `event_defaults` | Lokale Standarddauern in Minuten, 1–1440; explizite Mailzeiten haben Vorrang. |
| Themen-Geltungsbereich | Global, nur dieses Postfach oder hier ausschließen; eigene Fingerprints nur betroffener Postfächer. |
| Filter | Lokale Adress-/Domainsperren und exakte Ausnahmen von globalen Sperren. |

Speichern erstellt einen Einrichtungsentwurf. Die Übernahme benötigt eine erneute ausdrückliche lokale
Bestätigung. Ziel-/Verbindungsänderungen verlangen aktuelle lesende Diagnosen. Der Entwurf zeigt laufende
Mails, die durch eine relevante Änderung zurückgehalten werden. Zugangsdaten werden
getrennt unter **Einstellungen → Zugangsdaten** direkt in `.env` bearbeitet.
Anleitung: [Release 3.2](Release-3.2.md).


## Postfach-Briefings (4.9)

Unter `/einstellungen?bereich=briefing`; Zeiten werden mit Komma oder Semikolon eingegeben.

| Einstellung / Schlüssel | Wirkung und Werte | Übernahme |
| --- | --- | --- |
| Briefings als Postfachentwurf aktivieren (`briefings.enabled`) | Aktiviert zeitgesteuerte Briefings als IMAP-Entwürfe, Standard aus. Kein SMTP-Versand. Das Aktivieren autorisiert nur die Entwurfsablage; Kalender- und Aufgabenaktionen erfordern weiterhin eine eigene versionsbezogene Bestätigung. | Im laufenden Betrieb |
| Uhrzeiten für Postfach-Briefings (`briefings.times`) | Eindeutige lokale Uhrzeiten im Format HH:MM, durch Komma, Semikolon oder Leerzeichen getrennt, etwa 07:00, 13:00, 18:00. Verwendet die konfigurierte Zeitzone. Aktiviert muss mindestens eine Uhrzeit angegeben sein. | Im laufenden Betrieb |
| Zielpostfach für Briefings (`briefings.mailbox`) | Zielpostfach für die Briefing-Entwürfe. default verwendet das erste aktive Postfach; alternativ eine aktive Postfachnummer. Das Briefing sammelt offene Entscheidungen aller Postfächer. Es wird nie an fremde Empfänger versendet. | Im laufenden Betrieb |
| Leere Postfach-Briefings auslassen (`briefings.skip_empty`) | Standard true: Ohne offene Entscheidungen und ohne relevante Zusammenfassungen wird kein leerer Entwurf angelegt. false legt stattdessen ein kurzes Alles-ruhig-Briefing ab. | Im laufenden Betrieb |

## Vollständige Referenz weiterer Einstellungen (5.3)

Diese Einstellungen stehen nicht in den allgemeinen Einstellungsbereichen. Sie werden in der
Ersteinrichtung, auf eigenen Seiten (Postfach, IServ, Zielprofile, Benachrichtigungen) oder nur
in `config.yaml` gepflegt. „Pflicht“ heißt: Der Wert muss in `config.yaml` stehen; das
mitgelieferte `config.example.yaml` enthält ihn. Werte ohne Angabe gelten mit ihrem Standard.
Änderungen in `config.yaml` wirken nach einem Neustart, sofern nichts anderes genannt ist.

### Ersteinrichtung und Postfach 1 (älteres Einzelformat)

| Schlüssel | Wirkung und Werte | Bedienweg |
| --- | --- | --- |
| `imap.host` | Mailserver des ersten Postfachs im älteren Einzelformat, z. B. `imap.example.org`; 1–253 Zeichen. Ohne `imap.mailboxes` beschreibt dieser Block Postfach 1. | Ersteinrichtung |
| `imap.port` | Port des Mailservers, 1–65535; üblich 993 (SSL/TLS) oder 143 (STARTTLS). | Ersteinrichtung |
| `imap.connection_mode` | Verbindungsart `ssl`, `starttls` oder `plain` (unverschlüsselt, nur im eigenen Netz sinnvoll); ohne Angabe `ssl`. | Ersteinrichtung |
| `imap.folders` | Ordner, die gelesen werden, 1–100 Einträge; der erste ist der Posteingang. | Ersteinrichtung |
| `imap.primary_folder` | Ordner, der als Posteingang gilt und in `imap.folders` stehen muss; ohne Angabe der erste Eintrag von `imap.folders`. | Ersteinrichtung |
| `imap.drafts_folder` | Ordner für Antwort- und Briefing-Entwürfe; ohne Angabe `Drafts`. | Ersteinrichtung |
| `imap.historical_start` | Startgrenze: ältere Mails werden nicht verarbeitet (Datum mit Uhrzeit und Zeitzone). Leer bedeutet alle vorhandenen Mails. `mailhelp --ignore-historical-start` hebt sie für einen Abruf auf. | Ersteinrichtung |
| `telegram.enabled` | Telegram-Bot für Rückfragen, Bestätigungen und Meldungen; Standard an. Aus: Bedienung nur über die Weboberfläche. | Ersteinrichtung |
| `push.enabled` | Web-Push (inhaltsneutrale Hinweise) serverseitig anbieten; Standard aus. Jedes Gerät schaltet Push zusätzlich selbst ein. Nur über HTTPS oder localhost. | Ersteinrichtung |
| `push.subject` | Kontaktadresse des Betreibers für den Push-Dienst (VAPID), Format `mailto:name@domain`; Standard `mailto:admin@example.invalid`. | Datei |
| `daily_briefing.enabled` | Täglicher Tagesüberblick per Telegram; Standard aus. | Ersteinrichtung, Benachrichtigungen |
| `daily_briefing.time` | Uhrzeit des Tagesüberblicks im Format HH:MM in der konfigurierten Zeitzone; Standard 07:30. | Ersteinrichtung, Benachrichtigungen |

### Postfächer (`imap.mailboxes`)

Jedes Postfach ist ein Eintrag der Liste `imap.mailboxes`. Postfächer werden unter
**Einstellungen → Postfächer** angelegt, geprüft und geändert; nicht belegte lokale Felder erben
die globale Einstellung. Zugangsdaten stehen als `IMAP_<n>_USERNAME`/`IMAP_<n>_PASSWORD` in `.env`.

| Schlüssel | Wirkung und Werte | Bedienweg |
| --- | --- | --- |
| `imap.mailboxes[].id` | Nummer des Postfachs, 1–99; bestimmt die Namen der Zugangsdaten. Wird beim Anlegen vergeben und nicht geändert. | Postfachseite |
| `imap.mailboxes[].label` | Anzeigename, 1–40 Zeichen; Standard „Postfach“. | Postfachseite |
| `imap.mailboxes[].enabled` | Ob das Postfach abgerufen wird; Standard an. Ein deaktiviertes Postfach bleibt eingetragen. | Datei |
| `imap.mailboxes[].host` | Mailserver, 1–253 Zeichen (Pflicht). | Postfachseite |
| `imap.mailboxes[].port` | Port 1–65535 (Pflicht). | Postfachseite |
| `imap.mailboxes[].connection_mode` | `ssl` (Standard), `starttls` oder `plain`. | Postfachseite |
| `imap.mailboxes[].folders` | Gelesene Ordner, 1–100 (Pflicht); der erste ist der Posteingang. | Postfachseite |
| `imap.mailboxes[].primary_folder` | Posteingang; Standard `INBOX`. | Postfachseite |
| `imap.mailboxes[].drafts_folder` | Entwurfsordner, 1–500 Zeichen; Standard `Drafts`. | Postfachseite |
| `imap.mailboxes[].historical_start` | Startgrenze dieses Postfachs; leer bedeutet alle Mails. | Postfachseite |
| `imap.mailboxes[].own_addresses` | Weitere eigene Absenderadressen (Aliase), höchstens 20; der IMAP-Benutzername zählt bereits. Mails von diesen Adressen gelten als eigene Notiz oder Weiterleitung. | Datei |
| `imap.mailboxes[].target_profile` | Zielprofil 1–99 für neue Vorschläge dieses Postfachs; Standard 1. Bestehende Vorschläge bleiben an ihr Ziel gebunden. | Postfachseite (Ziele) |
| `imap.mailboxes[].mail_client` | Wohin „Original-Mail öffnen“ führt: `auto` (Standard), `apple_mail`, `gmail_web`, `outlook_web` oder `none`. | Postfachseite (Ziele) |
| `imap.mailboxes[].event_defaults.video_duration_minutes` | Lokale Standarddauer für Videotermine, 1–1440 Minuten; leer erbt global. | Postfachseite (Ziele) |
| `imap.mailboxes[].event_defaults.in_person_duration_minutes` | Lokale Standarddauer für Präsenztermine, 1–1440 Minuten; leer erbt global. | Postfachseite (Ziele) |
| `imap.mailboxes[].personal_info` | Eigene Rolle, Signatur und Angaben für Antwortentwürfe dieses Postfachs, bis 2000 Zeichen; leer erbt global. | Postfachseite (Antworten) |
| `imap.mailboxes[].smart_reply` | Antwortentwürfe für dieses Postfach; leer erbt global. | Postfachseite (Antworten) |
| `imap.mailboxes[].auto_draft` | Entwürfe ohne Klick im Entwurfsordner ablegen; leer erbt global (Standard aus). | Postfachseite (Antworten) |
| `imap.mailboxes[].activity_report_folder` | Vorausgewählter Ordner für Tätigkeitsberichte. | Postfachseite (Antworten) |
| `imap.mailboxes[].retention.full_mail_days` | Volltexte kürzer aufbewahren als global: Tage, `disabled` (sofort entfernen) oder `unlimited` (nur bei global unbegrenzter Aufbewahrung). | Postfachseite (Antworten) |
| `imap.mailboxes[].daily_briefing` | Dieses Postfach im Tagesüberblick als eigenen Abschnitt zeigen; Standard an. | Postfachseite (Benachrichtigungen) |
| `imap.mailboxes[].notifications.quiet_hours.enabled` | Eigene Ruhezeiten für dieses Postfach; leer erbt global. | Postfachseite (Benachrichtigungen) |
| `imap.mailboxes[].notifications.quiet_hours.start` | Beginn der Ruhezeit, HH:MM; leer erbt global. | Postfachseite (Benachrichtigungen) |
| `imap.mailboxes[].notifications.quiet_hours.end` | Ende der Ruhezeit, HH:MM; leer erbt global. | Postfachseite (Benachrichtigungen) |
| `imap.mailboxes[].notifications.quiet_hours.allow_system_errors` | Betriebsfehler trotz Ruhezeit melden; leer erbt global. | Postfachseite (Benachrichtigungen) |
| `imap.mailboxes[].notifications.categories.decisions` | Kanäle (`telegram`, `web_push`) für Entscheidungen dieses Postfachs; leer erbt global. | Postfachseite (Benachrichtigungen) |
| `imap.mailboxes[].notifications.categories.action_results` | Kanäle für Ergebnisse von Eintragungen; leer erbt global. | Postfachseite (Benachrichtigungen) |
| `imap.mailboxes[].notifications.categories.daily_briefing` | Kanäle für den Tagesüberblick; leer erbt global. | Postfachseite (Benachrichtigungen) |
| `imap.mailboxes[].notifications.categories.system_errors` | Kanäle für Betriebsfehler; leer erbt global. | Postfachseite (Benachrichtigungen) |

Änderungen auf der Postfachseite sind Entwürfe; übernommen wird nach erneuter ausdrücklicher
Bestätigung. Die Übernahme erfolgt zwischen Mailzyklen bzw. nach einem Neustart (siehe oben).

### IServ-Konten (`iserv.accounts`)

| Schlüssel | Wirkung und Werte | Bedienweg |
| --- | --- | --- |
| `iserv.accounts[].id` | Nummer 1–10; bestimmt die Zugangsdaten `ISERV_<n>_USERNAME`/`_PASSWORD`. | IServ-Seite |
| `iserv.accounts[].label` | Anzeigename, 1–40 Zeichen; Standard „Elternbriefe“. | IServ-Seite |
| `iserv.accounts[].server` | HTTPS-Adresse der Schule (Pflicht, bis 253 Zeichen); ein kopierter IServ-Link wird auf die Schuladresse gekürzt. | IServ-Seite |
| `iserv.accounts[].mailbox` | Postfach 1–99, dessen Zielprofil und Standards gelten; muss aktiv sein. Standard 1. | IServ-Seite |
| `iserv.accounts[].enabled` | Konto abrufen; Standard an. | IServ-Seite |
| `iserv.accounts[].historical_start` | Startgrenze; leer übernimmt die des Postfachs. | IServ-Seite |

### Weitere Zielprofile (`target_profiles`)

Profil 1 ist der Abschnitt `targets`; weitere Profile (ID 2–99) verwaltet
**Einstellungen → Zielprofile**. Die Felder entsprechen `targets` (siehe „Ziele“).

| Schlüssel | Wirkung und Werte | Bedienweg |
| --- | --- | --- |
| `target_profiles[].id` | Nummer 2–99 (Pflicht). | Zielprofilseite |
| `target_profiles[].label` | Anzeigename, 1–40 Zeichen (Pflicht). | Zielprofilseite |
| `target_profiles[].calendar_provider` | `google` (Standard), `caldav` oder `outlook`. | Zielprofilseite |
| `target_profiles[].task_provider` | `todoist` (Standard), `microsoft_todo`, `caldav` oder `apple_reminders`. | Zielprofilseite |
| `target_profiles[].google_calendar` | Kalender-ID bei Google, bis 500 Zeichen. | Zielprofilseite |
| `target_profiles[].todoist_project` | Todoist-Projekt-ID, bis 500 Zeichen. | Zielprofilseite |
| `target_profiles[].caldav_calendar_url` | Adresse der CalDAV-Kalendersammlung, bis 2000 Zeichen. | Zielprofilseite |
| `target_profiles[].caldav_task_url` | Adresse der CalDAV-Aufgabensammlung (auch Apple Erinnerungen), bis 2000 Zeichen. | Zielprofilseite |
| `target_profiles[].outlook_calendar` | Outlook-Kalender, Standard `default`. | Zielprofilseite |
| `target_profiles[].microsoft_todo_list` | Microsoft-To-Do-Liste, Standard `default` (Liste „Aufgaben“). | Zielprofilseite |
| `target_profiles[].microsoft_tenant` | Microsoft-Mandant für die Anmeldung, Standard `common`. | Zielprofilseite |

### Benachrichtigungen (`notifications`)

Unter **Einstellungen → Benachrichtigungen** und in der Ersteinrichtung. Fehlt der ganze Block
`notifications`, meldet Mailhelp alle Kategorien per Telegram (Entscheidungen und Tagesüberblick
zusätzlich per Push, falls aktiv) mit Inhalt `summary`. Ist der Block vorhanden, gelten seine Werte.

| Schlüssel | Wirkung und Werte | Bedienweg |
| --- | --- | --- |
| `notifications.quiet_hours.enabled` | Ruhezeiten: in diesem Zeitraum werden Meldungen zurückgehalten; Standard aus. | Benachrichtigungen |
| `notifications.quiet_hours.start` | Beginn, HH:MM; Standard 22:00. | Benachrichtigungen |
| `notifications.quiet_hours.end` | Ende, HH:MM; Standard 07:30. | Benachrichtigungen |
| `notifications.quiet_hours.allow_system_errors` | Betriebsfehler auch in der Ruhezeit melden; Standard aus. | Benachrichtigungen |
| `notifications.batching.enabled` | Meldungen in einem Zeitfenster bündeln; Standard aus. | Benachrichtigungen |
| `notifications.batching.window_seconds` | Bündelungsfenster 1–86400 Sekunden; Standard 300. | Benachrichtigungen |
| `notifications.categories.decisions` | Kanäle (`telegram`, `web_push`) für Entscheidungen; eine leere Liste meldet diese Kategorie nicht. | Benachrichtigungen |
| `notifications.categories.action_results` | Kanäle für Ergebnisse von Eintragungen. | Benachrichtigungen |
| `notifications.categories.daily_briefing` | Kanäle für den Tagesüberblick. | Benachrichtigungen |
| `notifications.categories.system_errors` | Kanäle für Betriebsfehler. | Benachrichtigungen |
| `notifications.telegram_content` | `neutral` (Standard): Telegram-Meldungen ohne Mailinhalte; `summary`: mit kurzer Übersicht der Entscheidungen bzw. dem Tagesüberblick. | Benachrichtigungen |
| `notifications.delivery.max_attempts` | Zustellversuche je Meldung, 1–10; Standard 3. | Benachrichtigungen |
| `notifications.delivery.initial_backoff_seconds` | Wartezeit vor dem zweiten Versuch, 1–86400 Sekunden; Standard 30. | Benachrichtigungen |
| `notifications.delivery.max_backoff_seconds` | Längste Wartezeit zwischen Versuchen, 1–86400 Sekunden; Standard 900. | Benachrichtigungen |
| `notifications.delivery.max_pending` | Höchstens wartende Meldungen, 1–100000; Standard 1000. | Benachrichtigungen |
| `notifications.delivery.history_days` | Aufbewahrung des Zustellverlaufs, 1–3650 Tage; Standard 30. | Benachrichtigungen |

### KI-Anbindung, Nachanalyse und Nachprüfung

| Schlüssel | Wirkung und Werte | Bedienweg |
| --- | --- | --- |
| `llm.provider` | `openrouter` (Standard) oder `ollama` (lokaler Server). `--ollama HOST:PORT` beim Start überschreibt die Wahl. Mit `openrouter` ist `OPENROUTER_API_KEY` in `.env` nötig. | Datei |
| `llm.ollama_address` | Adresse des Ollama-Servers bei `llm.provider: ollama`; Standard `localhost:11434`, auch `http://localhost:11434`. | Datei |
| `retries.provider_retry` | Wiederholungen eines KI-Aufrufs nach vorübergehendem Anbieterfehler, 0–10 (Pflicht). Jede Wiederholung zählt gegen `limits.llm_calls_per_minute`. | Datei |
| `retries.json_repair` | Korrekturversuche, wenn die KI kein gültiges JSON liefert, 0–10 (Pflicht). | Datei |
| `retries.schema_repair` | Korrekturversuche, wenn das JSON nicht dem erwarteten Aufbau entspricht, 0–10 (Pflicht). | Datei |
| `reanalysis.enabled` | „Aufgabe oder Termin übersehen?“ anbieten; Standard an. | Datei |
| `reanalysis.max_llm_calls_per_job` | KI-Aufrufe je Nachanalyse, 1–10; Standard 5 (drei Schritte und zwei Wiederholungen). | Datei |
| `reanalysis.max_attempts` | Versuche je Modellaufruf nach Fehler oder Neustart, 1–5; Standard 2. | Datei |
| `reanalysis.max_jobs_per_day` | Gestartete Nachanalysen je Tag über alle Mails, 1–500; Standard 20 (Kostenschutz). | Datei |
| `write_verification.max_attempts` | Kontrollabrufe nach einer Eintragung, 1–10; Standard 5. Der erste Abruf ist Versuch 1. | Datei |
| `write_verification.retry_delays_seconds` | Wartezeit vor jedem weiteren Abruf, genau `max_attempts − 1` Werte zu 1–3600 Sekunden; Standard `[1, 5, 15, 60]`. Ein `Retry-After` des Anbieters kann länger sein. | Datei |
| `write_verification.max_elapsed_seconds` | Höchstdauer der Prüfung, 10–86400 Sekunden, mindestens die Summe der Wartezeiten; Standard 300. Danach bleibt der Eintrag ausdrücklich ungeprüft. | Datei |

### Sicherheitsgrenzen beim Zerlegen von Mails

Eine Mail, die eine dieser Grenzen überschreitet, wird nicht ausgewertet: Sie erscheint mit dem
Hinweis „Die Nachricht überschreitet ein Sicherheitslimit“ und ohne KI-Aufruf. Die Standards
reichen für gewöhnliche Mails; erhöhen nur bei wiederholt betroffenen, vertrauenswürdigen Mails.

| Schlüssel | Wirkung und Werte | Bedienweg |
| --- | --- | --- |
| `limits.max_header_bytes` | Größe aller Kopfzeilen, 256–1000000 Bytes; Standard 64000. | Datei |
| `limits.max_display_header_characters` | Längste angezeigte Kopfzeile (Absender, Betreff), 1–10000 Zeichen; Standard 500. Längere werden als „—“ angezeigt. | Datei |
| `limits.max_mime_parts` | Teile einer Mail, 1–10000; Standard 100. | Datei |
| `limits.max_decoded_text_bytes` | Entschlüsselter Text aller Teile, 1–100000000 Bytes; Standard 1000000. | Datei |
| `limits.max_html_characters` | Länge des HTML-Teils, 1–100000000 Zeichen; Standard 1000000. | Datei |
| `limits.max_html_tags` | HTML-Elemente, 1–1000000; Standard 20000. | Datei |
| `limits.max_html_depth` | Verschachtelungstiefe des HTML, 1–10000; Standard 100. | Datei |

### Pfade, Protokolle und Webserver

| Schlüssel | Wirkung und Werte | Bedienweg |
| --- | --- | --- |
| `data_directory` | Verzeichnis der Zustandsdaten (Pflicht); darunter `production` bzw. `test` je nach Testmodus. Relativ zur Konfiguration. | Datei |
| `logging.directory` | Verzeichnis der Protokolle (Pflicht); `--log-directory` überschreibt es für einen Start. | Datei |
| `logging.console.format` | Bildschirmausgabe als `text` (Standard) oder `jsonl`. | Datei |
| `logging.file.filename` | Datei des Anwendungsprotokolls im Protokollverzeichnis (Pflicht). | Datei |
| `logging.file.format` | `jsonl` (Standard) oder `text`. | Datei |
| `logging.file.max_bytes` | Größe, ab der die Datei gewechselt wird, größer 0 (Pflicht). | Datei |
| `logging.file.backup_count` | Aufbewahrte ältere Dateien, ab 0 (Pflicht). | Datei |
| `logging.file.retention_days` | Höchstalter der Protokolldateien, 1–3650 Tage (Pflicht). | Datei |
| `logging.llm.filename` | Datei des KI-Protokolls (Pflicht). Inhalte von Anfragen und Antworten stehen dort nur mit `logging.llm.include_requests`/`include_responses`. | Datei |
| `logging.llm.format` | `jsonl` (Standard) oder `text`. | Datei |
| `logging.llm.max_bytes` | Wechselgröße, größer 0 (Pflicht). | Datei |
| `logging.llm.backup_count` | Aufbewahrte ältere Dateien, ab 0 (Pflicht). | Datei |
| `logging.llm.retention_days` | Höchstalter, 1–3650 Tage (Pflicht). | Datei |
| `logging.telegram.filename` | Datei des Telegram-Nachrichtenprotokolls; Standard `telegram/messages.jsonl`. | Datei |
| `logging.telegram.format` | `jsonl` (Standard) oder `text`. | Datei |
| `logging.telegram.max_bytes` | Wechselgröße, größer 0; Standard 10000000. | Datei |
| `logging.telegram.backup_count` | Aufbewahrte ältere Dateien, ab 0; Standard 5. | Datei |
| `logging.telegram.retention_days` | Höchstalter, 1–3650 Tage; Standard 30. | Datei |
| `logging.modules` | Protokollstufe je Modul, z. B. `openrouter: INFO`; Standard leer. | Datei |
| `timeouts.telegram_poll_seconds` | Wartezeit einer Telegram-Abfrage auf neue Nachrichten, 1–50 Sekunden (Pflicht). | Datei |
| `web.enabled` | Weboberfläche starten; Standard aus. | Datei |
| `web.host` | Netzwerkadresse des Webservers; Standard `127.0.0.1` (nur dieser PC). `0.0.0.0` ist für `web.lan_access` nötig. | Datei |
| `web.port` | Port 1–65535; Standard 8765. | Datei |
| `web.allowed_hosts` | Erlaubte Host-Angaben im Browseraufruf (Schutz vor DNS-Rebinding), 1–20 Einträge; Standard `127.0.0.1:8765`, `localhost:8765`. | Datei |
| `web.google_redirect_uri` | Rücksprungadresse der Google-Anmeldung; muss in der Google-Cloud-Konsole eingetragen sein. Standard `http://localhost:8765/auth/google/callback`. | Datei |
