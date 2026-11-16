# Mailhelp 7.2 – Notion und Google Tasks als Aufgabenziele

**Zielversion:** 7.2, Umsetzung in Patchversionen ab 7.2.1  
**Stand:** 16. November 2026  
**Status:** Umgesetzt in 7.2.1 bis 7.2.6 (16. November 2026); offen ist die reale Abnahme mit
Testkonten. Abnahme und Abweichungen in [Release 7.2](Release-7.2.md).  
**Ausgangsstand:** 7.0.12; nach Umsetzung von 7.1 erneut gegen den dann aktuellen Code prüfen.

**Grundlage:** [Entwicklungsregeln](../AGENTS.md),
[Projektspezifikation](../Mailhelp-Projektspezifikation.md),
[Demo-Plan 7.1](Planung-7.1.md).

## 1. Ziel und Umfang

Aus einer E-Mail erkannte Aufgaben lassen sich nach Prüfung und ausdrücklicher
Freigabe entweder in einer Google-Tasks-Liste oder einer Notion-Aufgabentabelle
anlegen. Beide Anbieter ergänzen die bisherigen Aufgabenziele. Kalender bleiben
eigenständig konfiguriert und verwenden ihre bestehenden Adapter.

Beispiel: Aus „Bitte bis Freitag das Formular zurückgeben“ entsteht ein Vorschlag.
Die Vorschau zeigt Titel, Beschreibung, Quelle, Frist und das konkrete Ziel. Erst
die Freigabe dieser Version erlaubt die externe Anlage. Danach zeigt Mailhelp das
Ergebnis und, soweit vom Anbieter geliefert, einen Link zum Eintrag.

### Festlegungen für die Umsetzung

| Bereich | Geplanter Umfang |
| :--- | :--- |
| Zielauswahl | Pro Zielprofil ein Aufgabenanbieter; neue Werte `google_tasks` und `notion` |
| Mehrere Anbieter | Unterschiedliche Zielprofile können unterschiedliche Anbieter verwenden; keine parallele Mehrfachanlage eines Vorschlags |
| Google Tasks | Bestehende Aufgabenliste auswählen, Aufgaben anlegen und für Dublettenprüfung/Tagesübersicht lesen |
| Notion | Bestehende Datenquelle einer Datenbank auswählen, Eigenschaften zuordnen, Aufgabenseiten anlegen und lesen |
| Freigaben | Telegram und authentifizierte Weboberfläche; keine automatische Anlage beim Speichern oder Verbinden |
| Anmeldung | Google OAuth; Notion interne Verbindung für eigene Instanzen und OAuth für nutzerseitige Workspace-Verbindung |
| Demo | Beide Ziele nur lokal simulieren; keine Anbieteranmeldung oder Netzwerkaufrufe |
| Betrieb | Windows 11 und Docker auf Linux; direkte HTTP-Adapter, keine zusätzlichen Hintergrunddienste |

Bidirektionale Synchronisation, externe Erledigen-/Bearbeiten-Aktionen, neue
Aufgabenlisten, neue Notion-Datenbanken, Unteraufgaben, Notion-Projektmanagement,
Anhang-Uploads und automatische Kalender-Zeitplanung gehören nicht zu 7.2.
Gelesene Anbieterzustände können Übersichten aktualisieren; sie überschreiben
keine lokalen Vorschläge oder bereits bestätigten Inhalte im Hintergrund.

## 2. Einbindung in die vorhandene Architektur

Der aktuelle Code bietet die benötigten Grenzen:

- `config/target_settings.py`: `TargetSettings`, Zielprofile und Anbieterwahl.
- `config/models.py`, `config/loader.py`, `config/configuration.py`: Geheimnisse,
  Validierung und editierbare Einstellungen.
- `external/contracts.py`: `TargetWriter`, `PreparedWrite`, Fehlerklassen,
  Bestandsabfrage und Abgleich unklarer Resultate.
- `external/providers.py`: Adapteraufbau, Ressourcenverwaltung und Anbieterlabels.
- `external/oauth.py`, `runtime/oauth_web.py`: Google-Token und sitzungsgebundene Anmeldung.
- `review/`, `proposals/`, `notifications/briefing.py`: Freigaben, Zielbindung,
  Dublettenprüfung, Ergebnisdarstellung und Tagesübersicht.

Neue Adapter `external/google_tasks.py` und `external/notion.py` verwenden diese
Verträge. API-Details bleiben dort; Web, Telegram und Verarbeitung erhalten keine
zweite Anlageimplementierung. Die derzeit Todoist-benannten Lesemodelle werden bei
Bedarf in ein neutrales Aufgabenmodell überführt, mit geprüfter Kompatibilität zu
allen bisherigen Anbietern und ohne unnötigen Umbau der Verarbeitung.

Für Fähigkeiten wie Datumsgenauigkeit, Statusabbildung, Link und sicheres Entfernen
werden ausdrückliche Anbietermerkmale verwendet. Oberflächen dürfen Fähigkeiten
nicht aus einem einzelnen bisherigen Anbieternamen ableiten.

## 3. Einrichtung und Konfiguration

### 3.1 Einstellungen ohne Geheimnisse

Folgende Erweiterung ist vorgesehen; endgültige Feldnamen werden bei Implementierung
mit den bestehenden Zielprofilen und Konfigurationseditoren abgeglichen:

```yaml
targets:
  task_provider: google_tasks
  google_tasks_list: "<ausgewählte Listen-ID>"
```

```yaml
targets:
  task_provider: notion
  notion_data_source_id: "<ausgewählte Datenquellen-ID>"
  notion_properties:
    title: "<Eigenschafts-ID>"
    description: "<Eigenschafts-ID>"
    due: "<Eigenschafts-ID>"
    source: "<Eigenschafts-ID>"
    operation_key: "<Eigenschafts-ID>"
    status: "<optionale Eigenschafts-ID>"
  notion_open_status: "<Option-ID, falls Status verwendet wird>"
  notion_done_statuses: []
```

Kalenderfelder und andere bestehende Einstellungen sind in diesen Ausschnitten
ausgelassen. Zielprofile erhalten dieselben Erweiterungen. Unbenutzte Anbieter
verlangen weder Zugangsdaten noch Ziele. Bestehende Konfigurationen bleiben gültig.
Prompts/Modelle bleiben in `prompts.yaml`, Themen in `topics.yaml`.

### 3.2 Einrichtung über die Oberfläche

1. Aufgabenanbieter im Zielprofil wählen und Verbindung herstellen.
2. Nur zugängliche Listen beziehungsweise Datenquellen anzeigen; Ergebnisse
   vollständig paginieren und bei Begrenzung ausdrücklich als unvollständig melden.
3. Konkretes Ziel auswählen. Bei Notion die Eigenschaften anhand von Typ und ID
   zuordnen; Datenbank und Datenquelle sind unterschiedliche Objekte. Bei mehreren
   Datenquellen keine stillschweigende Auswahl der ersten Tabelle.
4. Lesenden Verbindungs- und Schematest ausführen. Keine Testaufgabe anlegen,
   keine Datenquelle verändern und keine Eigenschaft automatisch hinzufügen.
5. Speichern. Die erste Anlage erfolgt erst nach Freigabe eines echten Vorschlags.

Notion erhält eine dokumentierte Tabellenvorlage, die der Nutzer selbst einrichtet.
Fehlende Zugriffsfreigabe, erforderliche Eigenschaften oder unpassende Typen werden
mit konkreter Abhilfe gemeldet. Ziele und Geheimnisse bleiben je Instanz und Profil
getrennt. Ein Ziel-/Kontowechsel invalidiert alte Freigaben und wartende Befehle.

## 4. Google Tasks

### 4.1 OAuth und Berechtigungen

Die Google Tasks API muss im verwendeten Google-Projekt aktiviert sein. Für Anlagen
wird `https://www.googleapis.com/auth/tasks` benötigt. Ein bisher nur für Kalender
erteilter Zugang wird nicht als Tasks-Berechtigung behandelt.

OAuth fordert die zum konfigurierten Profil passenden Berechtigungen an: Tasks bei
Google Tasks, Kalenderrechte bei Google Kalender, beide bei gemeinsamer Verwendung.
Bereits erteilte Kalenderrechte dürfen durch erneute Anmeldung nicht verloren gehen.
Zusätzliche Rechte verlangen eine erneute sichtbare Zustimmung; kein stiller Ersatz
eines vorhandenen Refresh-Tokens durch einen leeren oder unzureichenden Token.

Innerhalb eines Profils ist standardmäßig dasselbe Google-Konto für Kalender und
Tasks vorgesehen. Unterschiedliche Konten werden über getrennte Profile verbunden.
Konto-/Profilbindung und tatsächlich verfügbare Rechte werden geprüft. OAuth-Jobs
sind kurzlebig, einmalig sowie an Sitzung und Profil gebunden; Rückruf und Speicherung
prüfen diese Bindung erneut. API-Aktivierung, OAuth-App-Einrichtung und gegebenenfalls
Google-Verifizierung werden für lokale und gehostete Nutzung getrennt dokumentiert.

### 4.2 Abbildung von Aufgaben

- Titel → `title`; Beschreibung, Mail-Kontext, zulässiger Quellenlink und technischer
  Abgleichmarker → `notes`. Größenlimits werden vor Freigabe geprüft. Relevante
  Inhalte werden nicht still abgeschnitten; Kürzungen müssen sichtbar bestätigt sein.
- Datum → `due`, wenn vom Nutzer für Google Tasks bestätigt. Die API speichert dort
  nur einen Tag und bietet keine übertragbare Aufgaben-Uhrzeit. Google beschreibt
  dieses Feld als geplanten Aufgabentag, nicht als gesondertes Deadline-Feld.
- Mailhelp bewahrt die eigentliche Frist lokal. Eine genaue Uhrzeit samt Zeitzone
  wird zusätzlich lesbar in den Notizen festgehalten. Die Vorschau zeigt ausdrücklich:
  „Google Tasks übernimmt das Datum; die genaue Frist steht im Text.“ Keine Zusage
  einer zeitgenauen Google-Erinnerung und keine künstliche Kalenderanlage.
- Neue Aufgaben sind offen. Ohne Datum bleibt das Datum leer; kein erfundenes
  „heute“. Zeitumstellung und Zeitzonenwechsel dürfen den bestätigten Tag nicht ändern.
- Vom Anbieter gelieferte Statuswerte und Links werden normalisiert. Mail-Links
  stehen bei Bedarf in den Notizen; schreibgeschützte API-Linkfelder werden nicht gesetzt.
- Listen und Aufgaben vollständig über Pagination lesen. Gelöschte/erledigte
  Aufgaben sind keine offenen Aufgaben; beim Abgleich eines unklaren Schreibens
  müssen auch zwischenzeitlich erledigte Einträge berücksichtigt werden.

## 5. Notion

### 5.1 Verbindung und API-Vertrag

Lokale/eigene Instanzen können eine interne Notion-Verbindung verwenden, deren
Zugriff ausdrücklich auf die gewählte Tabelle freigegeben wird. Für einen gehosteten
Dienst ist zusätzlich ein regulärer Notion-OAuth-Ablauf mit Workspace-Auswahl und
korrekter Token-Erneuerung vorgesehen. Ein persönlicher Vollzugriffstoken wird nicht
als Standard verlangt. Lesen und Einfügen sind die benötigten Fähigkeiten; weitere
Schreibrechte werden nur bei tatsächlich unterstützter Zusatzfunktion angefordert.

Die REST-API wird mit explizitem `Notion-Version`-Header implementiert. Der geprüfte
Stand ist `2026-03-11`; vor Umsetzung erneut verifizieren und dann getestet pinnen.
Für neue Datenbankeinträge wird die gewählte `data_source_id` verwendet. Schema und
Eigenschaften werden über IDs referenziert, damit reine Umbenennungen die Zuordnung
nicht brechen. Entfernte Eigenschaften oder geänderte Typen sperren neue Anlagen
bis zur erneuten Zuordnung und Freigabe. Das Schema wird auch vor Ausführung geprüft.

### 5.2 Aufgabentabelle und Inhalt

| Inhalt | Vorgesehene Notion-Eigenschaft |
| :--- | :--- |
| Titel | `title`, erforderlich |
| Beschreibung mit kurzem Mail-Kontext | `rich_text`, erforderlich |
| Frist | `date`, erforderlich als Schemafeld; pro Aufgabe optional befüllt |
| Quellenlink | `url`, erforderlich als Schemafeld; leer, wenn kein brauchbarer Link existiert |
| Technischer Vorgangsschlüssel | `rich_text`, erforderlich; unabhängig vom Titel filterbar |
| Erledigungszustand | Optional `status`, `select` oder `checkbox`, mit expliziter Zuordnung |

Datumsfristen bleiben reine Daten; zeitgenaue Fristen behalten eine eindeutige
Zeitzone. Statusoptionen werden aus dem vorhandenen Schema gewählt, nicht automatisch
angelegt. Bei zugeordnetem Status werden offen/erledigt eindeutig abgebildet. Ohne
Statusfeld nennt die Oberfläche die Einschränkung: kein verlässlicher Erledigt-Filter
für diese Tabelle; keine Behauptung eines vollständig offenen Aufgabenbestands.

Pro Aufgabe wird eine Seite mit den bestätigten Eigenschaften in einem Anlageaufruf
erstellt. Keine nachträglichen Block- oder Anhangschreibvorgänge für die Grundanlage.
Längenlimits und Typen werden vor Bestätigung geprüft. Mailinhalte werden als Text
behandelt; Links, HTML und LLM-Ausgaben dürfen keine Befehle oder beliebige externe
Requests auslösen. Vollständige Mails werden nicht standardmäßig nach Notion kopiert.

## 6. Schreibvertrag und Schutz vor doppelten Anlagen

Die vorhandenen Sicherheitsregeln gelten ausdrücklich für beide neuen Anbieter:

1. Bestätigung bindet Vorschlagsversion, Anbieter, Profil, Konto/Workspace, konkretes
   Ziel, bestätigte Nutzdaten sowie die relevante Feldzuordnung aneinander.
2. Web: gültige Sitzung bei Annahme und erneut bei Ausführung, CSRF, Versionsprüfung
   und Idempotenzschlüssel. Telegram: berechtigter Chat und genau passende Version.
   Verbindungsfreigabe/OAuth ersetzt keine Freigabe einer Aufgabe.
3. Vor dem Request wird ein dauerhafter Schreibauftrag mit stabilem, nicht aus
   Klartext-Maildaten abgeleitetem öffentlichen Marker gespeichert. Parallelzugriffe
   auf denselben Auftrag werden serialisiert; Neustarts behalten die Identität.
4. Google speichert den Marker in `notes`, Notion in der zugeordneten Eigenschaft.
   Der lokale Beleg enthält Anbieter-ID, Ziel, Vorgang und bestätigte Daten. Marker
   und lokale Belege sind nicht als Zugangsdaten verwendbar.
5. Bei verlorener Antwort oder Prozessabbruch nach möglichem Versand wird zuerst im
   ursprünglichen Ziel abgeglichen: vorhandene ID lesen oder exakt nach Marker suchen.
   Mehrere Treffer werden als Konflikt behandelt, niemals als Anlass für eine Anlage.
6. Ein fehlender Treffer beweist nach einem unklaren POST nicht, dass nichts angelegt
   wurde. Weder Google- noch Notion-Marker begründen allein atomare Idempotenz.
   Bei unklarer Sichtbarkeit, entferntem Marker, unvollständiger Abfrage oder fehlender
   Anbieterzusage bleibt der Auftrag gesperrt/unklar. Kein blinder zweiter POST;
   manueller Klärungsablauf mit Erklärung statt „Erneut versuchen“ als Neuanlage.
7. Nur ein nachweislich nicht ausgeführter Request kann innerhalb des weiterhin
   autorisierten Auftrags wiederholt werden. 429, 5xx, Timeout und Verbindungsabbruch
   werden nach tatsächlicher Schreibunsicherheit behandelt, nicht allein nach Status.
   Begrenztes Backoff, `Retry-After` und die vorhandenen Zeitbudgets beachten.

Bestandsbasierte inhaltliche Dublettenprüfung bleibt vom Vorgangsabgleich getrennt.
Ein ähnlich betitelter fremder Eintrag darf weder automatisch übernommen noch
verändert werden. Wenn ein sicherer Abgleich nicht möglich ist, wird das dem Nutzer
angezeigt; fehlgeschlagene Lesezugriffe gelten nicht als leere Aufgabenliste.

## 7. Ergebnisse, Übersichten und Entfernen

Anbietername, tatsächliche Liste/Tabelle und ggf. Workspace stehen in Vorschau,
Bestätigungsdialog, Telegram, Ergebnisbeleg, Verlauf und Tagesübersicht. Links werden
aus geprüften Anbieterantworten übernommen; keine instabilen Notion-URLs als IDs
interpretieren. Fehlende Links verhindern nicht die korrekte Ergebnisdarstellung.

Nach externer Änderung darf ein gelesener Zustand die Anzeige aktualisieren, aber
keinen automatischen Rückschreibvorgang auslösen. Für 7.2 ist grundsätzlich die
Anlage mit lesender Bestandsprüfung vorgesehen, kein allgemeines externes Bearbeiten
oder Abhaken aus Mailhelp.

Die bestehenden Regeln für „Eintrag wieder entfernen“ bleiben erhalten: höchstens
zehn Minuten, immer zwei ausdrückliche Bestätigungsschritte, nur eigene und seitdem
unveränderte Anlagen. Für neue Anbieter ist Entfernen zunächst deaktiviert. Es darf
nur ergänzt werden, wenn ein nachgewiesener API-Vertrag Änderungen zwischen Prüfung
und Löschaufruf zuverlässig schützt; ein bloßes Lesen vor dem Löschen reicht nicht.
Insbesondere wird für Notion keine atomare Änderungsprüfung unterstellt. Ist sicheres
Entfernen nicht unterstützt, fehlt die Aktion und der Server lehnt direkte Befehle ab;
die Oberfläche verweist auf das Bearbeiten beim Anbieter. Kein heimlicher Rückfall auf
eine ungeschützte Löschung. Eine spätere Aktivierung benötigt eigene Abnahmetests.

## 8. Geheimnisse, Trennung und Demo

- Tokens, Client-Secrets und OAuth-Refresh-Daten bleiben außerhalb von `config.yaml`
  und Quellcode. Bestehende Secret-/Profilspeicherung wiederverwenden, atomar schreiben
  und unter Windows bzw. Linux angemessene Dateizugriffe sicherstellen.
- Notion-OAuth-Zustand einschließlich Token-Erneuerung wird dauerhaft je Profil und
  Workspace gebunden gespeichert. Gleichzeitige Refreshes dürfen rotierte Tokens
  nicht überschreiben. Verbindungen können getrennt und erneut eingerichtet werden.
- Keine Tokens, OAuth-Codes, geheimen Callback-Parameter oder vollständigen
  Anbieterantworten in JSONL-Logs, Fehlermeldungen, Screenshots oder Testartefakten.
- Anbieter-URLs und IDs werden validiert. Token-Requests gehen nur an festgelegte
  API-Endpunkte; keine frei konfigurierbaren Ziele oder Weitergabe an Redirect-Hosts.
- OAuth-Callback, Zielauflistung und Abfragen respektieren Instanz-/Profilgrenzen;
  eine Auswahl aus einem fremden Konto ist kein gültiges Ziel.
- Der 7.1-Demo-Modus simuliert beide Anbieter und ihre Ergebnisse ausschließlich
  lokal. Auch Anmeldung, Zieltest, Hintergrundabgleich und Fehlerbehandlung erzeugen
  dort keine echten Netzwerk- oder Schreibzugriffe. Netzwerkfallen testen dies.
- Kein zusätzlicher Polling-Daemon: vorhandene Übersichts-/Abgleichintervalle nutzen,
  Paginierung und Abrufbudgets begrenzen, API-Limits beachten und Ressourcen schließen.

## 9. Umsetzungsschritte

| Schritt | Geplante Version | Ergebnis |
| :--- | :--- | :--- |
| P1 | 7.2.1 | Aktuellen Stand nach 7.1 aufnehmen; API-Verträge, Fähigkeiten, neutralen Aufgabenlesevertrag und Konfigurationsmigration festlegen und testen |
| P2 | 7.2.2 | Google-Tasks-Adapter, OAuth-Rechte, Listenwahl, Datumsabbildung, persistente Aufträge und Abgleich umsetzen |
| P3 | 7.2.3 | Notion-Adapter, interne Verbindung, Datenquellenwahl, Schema-/Eigenschaftszuordnung, Anlage und Abgleich umsetzen |
| P4 | 7.2.4 | Notion OAuth mit Refresh und Workspace-Bindung; Einrichtung, Web und Telegram sowie Status-/Fehlermeldungen für beide Anbieter vervollständigen |
| P5 | 7.2.5 | Tagesübersicht, Dublettenprüfung, Demo, Migration/Neustarts, Dokumentation und vollständige Abnahme abschließen |

Jeder Schritt enthält passende Tests. Die Nummern sind eine geplante Aufteilung;
jeder tatsächliche Commit auf `main`/`beta` erhöht die Patchversion gemäß AGENTS.md.
Version in `pyproject.toml` und `src/mailhelp/__init__.py`, README und CHANGELOG müssen
übereinstimmen. Vor Abschluss veröffentlichte Zwischenstände dürfen den Gesamtplan
nicht als fertig ausweisen. Dieser Plan selbst führt keine Einrichtung oder
Bereitstellung auf dem Produktivserver aus.

## 10. Tests und Abnahme

Automatisierte Tests verwenden simulierte Google-/Notion-Dienste und synthetische
Mails, Aufgaben, Tabellen und Tokens. Erforderliche Fälle:

- Bestehende Konfigurationen unverändert laden; neue Felder, ungültige IDs,
  fehlende Secrets, nicht verfügbare Ziele und Profilgrenzen prüfen.
- Google nur Tasks, nur Kalender und beide; fehlende/abgelehnte Scopes, widerrufene
  Tokens, API deaktiviert, Refresh, erneute Anmeldung und falsche Kontozuordnung.
- Notion intern und OAuth; abgebrochene Anmeldung, falsches/wiederholtes/abgelaufenes
  State, widerrufene Sitzung, Token-Rotation, Workspace-Verwechslung und fehlende Freigabe.
- Notion mehrere Datenquellen, umbenannte/entfernte Eigenschaften, geänderter Typ,
  ungültige Statusoption, fehlendes Statusfeld, Pagination und Schemawechsel zwischen
  Bestätigung und Ausführung.
- Erfolg mit/ohne Frist, ohne Quelllink, lange Inhalte und unbekannte additive
  Antwortfelder; Google Datumsgrenze, exakte Frist nur im Text, Zeitzonen/Sommerzeit.
- Freigabe über Web und Telegram; fehlende/abgelaufene Sitzung, CSRF, alte Version,
  bearbeitete Daten, Zielwechsel nach Freigabe und Widerruf vor Warteschlangenausführung.
- Doppelklick und parallele Befehle; Crash vor Versand, nach Versand, vor lokalem
  Erfolgsbeleg sowie während Abgleich; Neustart erzeugt keine zweite Anlage.
- Verlorene Antwort, 429/5xx, ungültiges JSON, verzögerte Sichtbarkeit, entfernter
  Marker, mehrere Marker-Treffer und unvollständige Abfrage. Unklar bleibt gesperrt.
- Fremde ähnliche Aufgaben, extern erledigte/gelöschte eigene Einträge, fehlende
  Anbieterlinks und lesender Fehlerfall in Dublettenprüfung/Tagesübersicht.
- Kein Entfernen für nicht unterstützte Anbieter, auch bei direktem API-/Telegram-
  Befehl. Bisherige Zehn-Minuten-/Zwei-Schritte-Regeln bleiben unverändert geprüft.
- Demo ohne Netzwerk, bisherige Anbieter unverändert, Windows-Dateizugriffe,
  Linux-Docker und korrektes Schließen der HTTP-/Token-Ressourcen.
- Chromium und WebKit auf Desktop und Mobilgerät: Einrichtung, Auswahl, Vorschau,
  Freigabe, Ergebnis, Fehlermeldung; Kernaktionen auch ohne JavaScript.

100 % Zeilen- und 100 % Branch-Abdeckung für eigenen Anwendungscode sind verbindlich;
beide Grenzen müssen automatisiert erzwungen werden. Bestehende JavaScript-Prüfungen
weiter erfüllen. Bugfixes enthalten zuvor fehlschlagende Regressionstests.

Vollständige Prüfungen laufen nacheinander, gemäß aktuellem AGENTS.md:

```powershell
python -m devtools.check full --workers 12
python -m pytest ui_tests -n 6 --dist worksteal --no-cov
```

Zusätzlich Paket-/Containerprüfung und eine dokumentierte reale Abnahme je Anbieter
mit eigens freigegebenem Testkonto/Testziel. Auch Testanlagen brauchen eine konkrete
versionsbezogene Freigabe. Fehlende Konten, App-Verifizierung oder Anbieterkonfiguration
werden als offene Abnahme ausgewiesen; simulierte Tests ersetzen keinen Realnachweis.

### Fertig, wenn

Beide Anbieter sind einrichtbar, erzeugen nach Freigabe genau den bestätigten Inhalt,
zeigen ihre Einschränkungen vor der Freigabe, überstehen Wiederholung und Neustart
ohne blinde Neuanlage und funktionieren in den vorhandenen Übersichten. Alte Anbieter
und Demo bleiben geprüft. Dokumentation, vollständige Tests und reale Abnahme sind
abgeschlossen; offene externe Voraussetzungen werden nicht als erledigt markiert.

## 11. Dokumentation bei Umsetzung

README, CHANGELOG, Projektspezifikation (Schreibvertrag ausdrücklich auf neue Anbieter
erweitern), `config.example.yaml`, Secret-Beispiele ohne Werte, Ziele-/Ersteinrichtung,
Bedienung, Hilfetexte und Hilfeindex sowie Docker-/OAuth-Anleitung aktualisieren.
`docs/Release-7.2.md` dokumentiert Versionen, Migration, Berechtigungen, API-Grenzen,
Tests, reale Abnahme und Rückkehr zur vorherigen Version. Für Rückkehr neue Ziele
zuerst deaktivieren, offene/unklare Aufträge sichern und klären; unbekannte neue
Zustände dürfen nicht durch alte Software als neue Anlage verarbeitet werden.

Die Inboxstride-Landingpage erhält erst nach tatsächlicher Umsetzung und festgelegtem
gehosteten Startumfang eine entsprechende Verfügbarkeitsaussage.

## 12. Offizielle API-Grundlagen

Am 16. November 2026 geprüft; vor Implementierung erneut abgleichen:

- [Google Tasks: Aufgabenressource](https://developers.google.com/workspace/tasks/reference/rest/v1/tasks): Felder, Datumsgrenze, Notizen, Status und schreibgeschützte Links.
- [Google Tasks: Anlegen](https://developers.google.com/workspace/tasks/reference/rest/v1/tasks/insert) und [Auflisten](https://developers.google.com/workspace/tasks/reference/rest/v1/tasks/list): Ziel und Abgleich.
- [Google Tasks: OAuth-Berechtigungen](https://developers.google.com/workspace/tasks/auth): Tasks-Rechte und Veröffentlichungsvoraussetzungen.
- [Notion: Versionierung](https://developers.notion.com/reference/versioning) und [Upgrade auf 2026-03-11](https://developers.notion.com/guides/get-started/upgrade-guide-2026-03-11): explizite API-Version; `in_trash` statt alter Archivfelder.
- [Notion: Autorisierung](https://developers.notion.com/guides/authorization/overview): interne Verbindung, OAuth und Token-Erneuerung.
- [Notion: Datenquelle abfragen](https://developers.notion.com/reference/query-a-data-source): zielgebundene Abfrage und Filter für Vorgangsmarker.

Nicht dokumentierte Idempotenz oder atomare Änderungsbedingungen werden nicht
angenommen. Entsprechende API-Nachweise sind Teil von P1; fehlen sie, greifen die
beschriebenen Sperren und Fähigkeitsgrenzen.
