# Mailhelp 3.0 – Einfache Einrichtung und gezielte Benachrichtigungen

**Zielversion:** 3.0.0  
**Stand:** 12. Oktober 2026  
**Status:** Geplant – noch nicht umgesetzt  
**Grundlage:** [Release 2.0](Release-2.0.md), [Planung 2.0](Planung-2.0.md), [Projektspezifikation](../Mailhelp-Projektspezifikation.md), [Entwicklungsregeln](../AGENTS.md)

## 1. Ziel und Umfang

Mailhelp 3.0 soll sich verständlich einrichten und im Alltag mit weniger Unterbrechungen betreiben lassen. Das Release konzentriert sich auf zwei Bereiche:

1. **Einrichtungs- und Diagnoseassistent:** Eine geführte Einrichtung mit überprüfbaren Verbindungstests, verständlichen Fehlermeldungen und konkreten nächsten Schritten.
2. **Benachrichtigungssteuerung:** Kanalwahl, Ruhezeiten, Bündelung und nachvollziehbare Zustellzustände für Telegram und Web-Push.

Version 2.0 bringt bereits Web-Push, Gerätekopplung ohne Telegram, Antwortentwürfe und einen Tagesüberblick mit. Version 3.0 baut darauf auf. Der Assistent verwendet dieselben Konfigurations- und Sicherheitsmechanismen wie der übrige Betrieb.

**Nicht Teil dieses Releases:** neue KI-Analysefunktionen, automatische Freigabe von Kalender- oder Todoist-Aktionen, SMTP-Versand, Mehrbenutzerbetrieb und zusätzliche Benachrichtigungskanäle. Passkeys und eine allgemeine Wiedervorlage bleiben eigenständige spätere Erweiterungen.

## 2. Verbindliche Grundsätze

- Python für Windows 11 und Docker unter Linux; keine getrennten fachlichen Implementierungen.
- Anwendungseinstellungen bleiben in `config.yaml`, Prompts und Modellparameter in `prompts.yaml`, Themen in `topics.yaml`. Geheimnisse bleiben außerhalb des Codes und außerhalb der normalen Konfigurationsdatei.
- Zustände werden als lesbare, schema-versionierte JSON-Dateien gespeichert; Betriebsereignisse getrennt als JSONL protokolliert.
- Mailinhalte, LLM-Ausgaben und Antworten externer Dienste bleiben nicht vertrauenswürdige Eingaben.
- Jeder externe Schreibzugriff auf Google Kalender oder Todoist verlangt weiterhin eine ausdrückliche Bestätigung der konkreten Vorschlagsversion. Ein abgeschlossener Assistent oder eine geänderte Benachrichtigungseinstellung erteilt keine solche Freigabe.
- Webänderungen benötigen Sitzung, CSRF-Schutz, Versionsprüfung und Idempotenzschlüssel. Bei verzögerter Ausführung wird die Sitzung erneut geprüft.
- Browser-Push enthält ausschließlich neutrale Hinweise. Vertrauliche Inhalte werden nicht auf Sperrbildschirme übertragen.
- Geheimnisse, Kopplungscodes und vollständige Push-Endpunkte erscheinen nicht in Diagnoseberichten oder normalen Anwendungslogs.

## 3. Einrichtungs- und Diagnoseassistent

### 3.1 Einstieg und Ablauf

Der Assistent ist nach der Anmeldung unter `/einrichtung` erreichbar und jederzeit über die Einstellungen erneut aufrufbar. Eine bestehende Installation wird zunächst eingelesen; vorhandene Werte werden nicht ungefragt ersetzt.

| Schritt | Inhalt | Ergebnis |
| :--- | :--- | :--- |
| 1. Betriebsart | Windows oder Docker, Zeitzone, Nutzung mit oder ohne Telegram | Verständliche Übersicht der benötigten Komponenten |
| 2. Postfach | IMAP-Verbindung, Quellordner und Entwurfsordner | Bestätigte Erreichbarkeit und ausgewählte vorhandene Ordner |
| 3. Analyse und Ziele | Konfiguriertes LLM, Google Kalender und Todoist | Getrennte Ergebnisse für Zugang, Erreichbarkeit und Zielauswahl |
| 4. Web und Geräte | Anmeldung, HTTPS, PWA, Push-Unterstützung und Berechtigungen | Status des aktuellen Geräts und konkrete Einrichtungshinweise |
| 5. Benachrichtigungen | Kanäle, Kategorien, Ruhezeiten und Bündelung | Vorschau des gewünschten Verhaltens |
| 6. Prüfen und übernehmen | Änderungsliste, Prüfergebnisse, erforderliche Neustarts | Ausdrücklich bestätigte, atomare Konfigurationsänderung |

Zwischenschritte dürfen gespeichert und nach einem Neustart fortgesetzt werden. Speichern verändert noch nicht die aktive Konfiguration. Erst „Einstellungen übernehmen“ bestätigt den gezeigten Konfigurationsstand. Bei zwischenzeitlichen Änderungen muss der Assistent die Differenz neu anzeigen.

### 3.2 Erstzugang und Geheimnisse

- Ohne bestehende Sitzung erfolgt die Erstkopplung über einen ausdrücklich gestarteten lokalen CLI-Befehl. Dieser zeigt einen kurzlebigen Einmalcode direkt im Terminal an; er wird nicht über den normalen Logger ausgegeben.
- Für Docker wird ein entsprechender `docker compose exec`-Ablauf dokumentiert. Der Bediener benötigt Zugriff auf den lokalen Host beziehungsweise Container.
- Rate-Limits, Ablaufzeit, einmalige Verwendung und serverseitige Sitzungsverwaltung gelten auch für diesen Einstieg.
- Der Assistent zeigt zu Geheimnissen nur „vorhanden“, „fehlt“ oder „Prüfung fehlgeschlagen“. Passwörter und Tokens werden nicht zurück an den Browser geliefert.
- Im ersten Umfang verweist der Assistent auf die vorhandene lokale Geheimniskonfiguration (`.env` beziehungsweise Prozessumgebung). Er bietet keine allgemeine Webbearbeitung von Zugangsdaten an.

### 3.3 Prüfungen und Sicherheitsgrenzen

Die Prüfungen sind einzeln startbar und besitzen begrenzte Laufzeiten. Eine langsame oder fehlerhafte Integration blockiert weder andere Prüfungen noch den normalen Mailbetrieb.

| Prüfung | Zulässiges Verhalten | Grenze |
| :--- | :--- | :--- |
| IMAP | Verbindung, Anmeldung, Ordnerliste, lesende Auswahl des Entwurfsordners | Keine Änderung von Mails, Flags oder Ordnern; kein Test-APPEND |
| Kalender | Lesender Zugriff auf ausgewählten Kalender | Kein Testtermin und keine Änderung vorhandener Termine |
| Todoist | Lesender Zugriff auf Projekt beziehungsweise Aufgaben | Keine Testaufgabe und keine Änderung vorhandener Aufgaben |
| LLM | Konfiguration lokal prüfen; optional ausdrücklich gestartete synthetische Testanfrage | Keine echten Maildaten; mögliche Kosten vor dem Start anzeigen |
| Telegram | Zugang separat prüfen; neutrale Testnachricht nur nach Klick auf „Testnachricht senden“ | Kein Versand durch bloßes Öffnen des Assistenten |
| Web-Push | Browserfähigkeit, sichere Herkunft, Berechtigung und Abonnement prüfen | Test-Push nur nach expliziter Nutzeraktion an das aktuelle Gerät |
| Dateisystem | Zustandsverzeichnis und atomare Speicherung mit synthetischer temporärer Datei prüfen | Keine Bereinigung oder Veränderung bestehender Mailzustände |

Ein lesend erreichbarer Entwurfsordner ist **kein Nachweis einer Schreibberechtigung**. Die Oberfläche erklärt diese Grenze, statt einen erfolgreichen APPEND-Test vorzutäuschen.

### 3.4 Diagnoseansicht

Unter `/diagnose` erhält jede Komponente einen Status: **nicht geprüft**, **wird geprüft**, **bereit**, **eingeschränkt**, **fehlgeschlagen** oder **deaktiviert**. Ergebnisse enthalten Prüfzeitpunkt, Dauer, einen sicheren Fehlercode und eine konkrete Handlungsempfehlung.

Beispiele:

- „IMAP-Anmeldung abgelehnt – Zugangsdaten oder App-Passwort prüfen.“
- „Entwurfsordner nicht gefunden – einen vorhandenen Ordner auswählen.“
- „Push auf diesem Gerät nicht erlaubt – Browserberechtigung prüfen.“
- „Google Kalender nicht erreichbar – die anderen Dienste bleiben nutzbar.“

Fehler werden soweit zuverlässig möglich als Netzwerk-, TLS-, Authentifizierungs-, Berechtigungs-, Konfigurations- oder Dienstfehler eingeordnet. Rohantworten externer Dienste werden nicht ungeprüft angezeigt.

Ein herunterladbarer Diagnosebericht enthält ausschließlich freigegebene Betriebsdaten: Programmversion, Betriebssystemklasse, aktivierte Komponenten, Prüfzeiten und bereinigte Fehlercodes. Keine Mailtexte, Betreffzeilen, Adressen, Tokens, Kopplungscodes, absoluten privaten Dateipfade oder Push-Endpunkte. Der Bericht wird nicht automatisch an Dritte übertragen.

### 3.5 Abnahmekriterien

- Neue Einrichtung und erneute Diagnose funktionieren mit und ohne Telegram.
- Der Assistent verändert Einstellungen nur nach Prüfung und ausdrücklicher Übernahme; parallele Änderungen werden erkannt.
- Ein Neustart erhält den Bearbeitungsstand, aber keine alte Autorisierung zur Übernahme.
- Diagnoseprüfungen erzeugen keine Kalendertermine, Aufgaben oder IMAP-Entwürfe.
- Testnachrichten und kostenpflichtige LLM-Tests benötigen eigene, eindeutig beschriftete Nutzeraktionen.
- Basisfunktionen arbeiten ohne JavaScript. Browserberechtigungen und Push-Abonnements werden als browserabhängige Ausnahme verständlich erklärt.
- Auf Smartphone und Desktop sind Status, nächste Schritte und Bedienflächen zugänglich; primäre Touch-Ziele sind mindestens 48 px hoch.

## 4. Benachrichtigungssteuerung

### 4.1 Kategorien und Kanalwahl

Unter `/einstellungen/benachrichtigungen` kann der Nutzer pro Kategorie einen oder mehrere Kanäle auswählen. Die lokale Anzeige bleibt verfügbar, auch wenn externe Kanäle deaktiviert sind.

| Kategorie | Beispiele | Verhalten |
| :--- | :--- | :--- |
| Offene Entscheidungen | Neuer Vorschlag, Klärungsfrage, neue zu bestätigende Version | Sofort oder gebündelt; Ruhezeiten beachten |
| Aktionsergebnisse | Anlage erfolgreich, abgelehnt oder weiterhin unklar | Sofortige Rückmeldung im auslösenden Kanal; zusätzliche Meldungen konfigurierbar |
| Tagesüberblick | Konfiguriertes Daily Briefing | Vorhandenen Zeitplan verwenden; Zustellung über die gemeinsame Kanalsteuerung |
| Betriebsprobleme | Dauerhafter Zugangsfehler oder ausgefallener Abruf | Wiederholungen begrenzen; identische anhaltende Fehler zusammenfassen |

Ein Kanal kann nur gewählt werden, wenn seine technischen Voraussetzungen erfüllt sind. Die Oberfläche erklärt fehlende Voraussetzungen und verlinkt den passenden Diagnoseschritt. Gerätespezifische Push-Abonnements bleiben vom globalen Versandprofil getrennt.

Für Telegram wird zwischen **neutralem Hinweis** und **inhaltlicher Zusammenfassung** unterschieden. Neue Installationen beginnen mit neutralen Hinweisen; vorhandene Inhaltsfreigaben werden beim Upgrade sichtbar übernommen. Die Aktivierung inhaltlicher Meldungen zeigt die betroffenen Datenarten an und erfordert eine bewusste Auswahl. Web-Push bleibt immer neutral.

### 4.2 Ruhezeiten

- Ein täglich wiederkehrendes Zeitfenster in der konfigurierten IANA-Zeitzone, beispielsweise 22:00 bis 07:30 Uhr.
- Zeitfenster über Mitternacht werden unterstützt. Bei aktivierten Ruhezeiten sind identische Start- und Endzeiten ungültig, damit keine unklare 24-Stunden-Sperre entsteht.
- Während der Ruhezeit werden automatische Meldungen gesammelt. Nach deren Ende entsteht eine aktuelle Zusammenfassung; kein Schwall einzelner nachgeholter Meldungen.
- Bereits erledigte Entscheidungen und ersetzte Vorschlagsversionen werden vor dem Versand entfernt beziehungsweise aktualisiert.
- Vom Nutzer ausgelöste Formularantworten, Kopplungen und Testmeldungen bleiben unmittelbar möglich. Sie werden nicht als automatische Hintergrundmeldungen behandelt.
- Optional darf der Nutzer Betriebsprobleme ausdrücklich von Ruhezeiten ausnehmen. Diese Ausnahme ist standardmäßig deaktiviert.
- Tests definieren das Verhalten bei Zeitumstellung, Neustart innerhalb einer Ruhezeit und Änderung der Zeitzone. Die Entscheidung erfolgt anhand lokaler Uhrzeit; Zustellzustände bleiben dauerhaft eindeutig.

### 4.3 Bündelung

- Konfigurierbares Zeitfenster, beispielsweise fünf Minuten; alternativ sofortige Zustellung.
- Gleichartige Ereignisse werden pro Kanal gebündelt. Ein Vorgang mit mehreren Änderungen trägt nur seinen aktuell relevanten Stand bei.
- Der Timer beginnt beim ersten Ereignis; weitere Ereignisse verlängern das Fenster nicht unbegrenzt.
- Push meldet beispielsweise „Mehrere Entscheidungen warten in Mailhelp“. Details werden erst nach Anmeldung geöffnet.
- Nach einer Ruhezeit wird unabhängig vom normalen Bündelungsfenster zunächst eine Zusammenfassung zugestellt.
- Das Briefing wird nicht zusätzlich als normale Entscheidungszusammenfassung versendet. Kategorien behalten getrennte Ereignisidentitäten.
- Gruppierung verändert weder Vorschläge noch deren Bestätigungsstatus. Jede fachliche Aktion bleibt an ihre konkrete Version gebunden.

### 4.4 Zustellung, Wiederholungen und Neustarts

Eine persistente Benachrichtigungswarteschlange ersetzt voneinander unabhängige spontane Versandpfade schrittweise. Vorgesehene Zustände sind `pending`, `deferred`, `sending`, `sent`, `failed`, `uncertain` und `cancelled`.

- Stabile Ereignis- und Kanalidentitäten verhindern doppelte Einreihung desselben Ereignisses.
- Direkt vor dem Versand werden aktuelle Einstellungen, Vorschlagsversion, Relevanz sowie bei Push der gültige Gerätezustand geprüft.
- Eindeutig fehlgeschlagene Zustellungen erhalten begrenzte Wiederholungen mit Backoff; danach einen sichtbaren Fehlerstatus.
- Unklare Resultate werden vor einer Wiederholung abgeglichen, soweit der Anbieter dies erlaubt. Ist kein belastbarer Abgleich möglich, bleibt der Vorgang `uncertain`; keine blinde Wiederholung und kein falscher Erfolgsstatus.
- Eine Annahme durch einen Push-Dienst bedeutet „an den Dienst übergeben“, nicht „am Endgerät gelesen“. Die Oberfläche unterscheidet diese Aussagen.
- Ausfälle eines Kanals verhindern keine Zustellung an andere konfigurierte Kanäle.
- Deaktivierte Kanäle, widerrufene Geräte und nicht mehr relevante Meldungen werden aus der ausstehenden Zustellung entfernt. Bereits übergebene Meldungen lassen sich nicht zurückrufen.
- Inhaltsarme Zustellhistorie mit konfigurierbarer Aufbewahrung und einer begrenzten Queue verhindert unbegrenztes Wachstum. Zusammenfassbare Ereignisse dürfen verdichtet, offene Entscheidungen aber nicht stillschweigend verloren werden.

### 4.5 Konfiguration

**Entwurf für neue Felder; noch keine gültige 2.0-Konfiguration.** Bestehende Felder wie `telegram.enabled`, `push.enabled` und `daily_briefing.time` bleiben die technischen beziehungsweise zeitlichen Voraussetzungen.

```yaml
notifications:
  quiet_hours:
    enabled: true
    start: "22:00"
    end: "07:30"
    # Zeitzone aus dem bestehenden Feld timezone
    allow_system_errors: false
  batching:
    enabled: true
    window_seconds: 300
  categories:
    decisions: [web_push]
    action_results: []
    daily_briefing: [web_push]
    system_errors: [web_push]
  telegram_content: neutral  # neutral | summary
  delivery:
    max_attempts: 3
    initial_backoff_seconds: 30
    max_backoff_seconds: 900
    history_days: 30
    max_pending: 1000
```

Das Beispiel stellt eine bewusst gewählte Einstellung dar, nicht eine automatische Upgrade-Änderung. Schema, Grenzwerte und Kanalnamen werden vor Implementierung verbindlich festgelegt. Die Weboberfläche bearbeitet dieselben YAML-Felder und zeigt an, welche Änderungen sofort gelten.

### 4.6 Abnahmekriterien

- Kategorien lassen sich unabhängig auf Telegram, Web-Push, beide oder keinen externen Kanal verteilen.
- Ruhezeiten verhindern automatische externe Meldungen, ohne den Mailabruf oder offene Entscheidungen zu blockieren.
- Nach Ruhezeiten werden ausschließlich noch relevante Meldungen zusammengefasst.
- Bündelung, Kanalwechsel und Neustarts erzeugen keine doppelte Einreihung oder unautorisierte Wiederholung.
- Fehler und unklare Resultate bleiben sichtbar; Geheimnisse und Mailinhalte gelangen nicht in Zustelllogs.
- Push-Berechtigung, Serveraktivierung und aktives Geräteabonnement werden getrennt dargestellt.
- Normale Telegram-Rückfragen, direkte Aktionsergebnisse und der Tagesüberblick funktionieren weiterhin über ihre fachlichen Dienste; ihre Hintergrundzustellung folgt der gemeinsamen Richtlinie.

## 5. Architektur und Persistenz

Vorgeschlagene Verantwortlichkeiten, deren konkrete Modulnamen bei der Implementierung an die vorhandene Struktur angepasst werden:

| Baustein | Verantwortung |
| :--- | :--- |
| Einrichtungsservice | Schritte, Entwurfsstand, Konfigurationsdifferenz und bestätigte Übernahme |
| Diagnoseservice | Begrenzte, voneinander unabhängige Prüfungen und sichere Ergebnisse |
| Benachrichtigungsrichtlinie | Kategorie, Kanal, Ruhezeit, Bündelung und aktuelle Relevanz |
| Zustellwarteschlange | Dauerhafte Ereignisse, Kanalzustände, Wiederholungen und Wiederaufnahme |
| Scheduler | Fällige Zustellungen und Diagnoseaufträge bearbeiten; kein externer Netzwerkzugriff unter globalem Store-Lock |
| Kanaladapter | Bestehende Telegram- und Web-Push-Transporte wiederverwenden |
| Webansichten | Assistent, Diagnose, Versandprofil und Zustellhistorie |

Vorgesehene Dateien: `setup-state.json`, `diagnostics-state.json` und `notification-queue.json`. Neue Dokumente enthalten eine `schema_version`. Die Zustellhistorie enthält Referenzen und Status statt Kopien vollständiger Mail- oder Briefingtexte. Ihre Fristen werden mit der bestehenden Retention abgestimmt.

Konfigurationsänderungen laufen über den vorhandenen authentifizierten Änderungsmechanismus. Operative Einstellungen des Assistenten und der Benachrichtigungen verändern nicht den Analyse-Fingerprint laufender Mails.

## 6. Umsetzungsphasen

| Phase | Schwerpunkt | Fertig, wenn … |
| :--- | :--- | :--- |
| 1 | Verträge und Upgrade | Konfigurationsschema, Kategoriezuordnung, Zustandsmodell und Migrationsregeln spezifiziert und getestet sind |
| 2 | Diagnosekern | Alle lesenden Prüfungen, Timeouts, Fehlerklassen und der bereinigte Bericht unabhängig funktionieren |
| 3 | Einrichtungsassistent | Erstkopplung, Wiederaufnahme, Konfigurationsprüfung und bestätigte Übernahme im Web vollständig bedienbar sind |
| 4 | Zustellwarteschlange | Bestehende Hintergrundmeldungen über dauerhafte, kanalbezogene Zustände laufen und Neustarttests bestehen |
| 5 | Benachrichtigungsprofil | Kanalwahl, Inhaltsfreigabe, Ruhezeiten, Bündelung und Zustellansicht integriert sind |
| 6 | Abnahme und Release | Python- und Browsertests, Windows-/Linux-/Docker-Prüfungen, Dokumentation und Release-Artefakte fertig sind |

Jede Phase enthält ihre Tests und Dokumentationsänderungen. Die letzte Phase ersetzt nicht die laufende Qualitätssicherung.

## 7. Teststrategie

- **Verbindlich:** 100 % Zeilen- und 100 % Branch-Abdeckung für sämtlichen eigenen Anwendungscode; das automatische Gate scheitert bei jeder Unterschreitung. Keine neuen Coverage-Ausnahmen.
- Regressionstests reproduzieren jeden behobenen Fehler vor dem Fix und bestehen danach.
- Simulierte externe Dienste und synthetische Daten für sämtliche automatisierten Tests; keine echten Nachrichten, Kalendertermine oder Aufgaben.
- Diagnosen: Erfolg, Ablehnung, Timeout, TLS-Fehler, ungültige Antwort, Abbruch, Wiederholung und voneinander unabhängige Teilausfälle.
- Autorisierung: fehlende beziehungsweise widerrufene Sitzung, CSRF-Fehler, veraltete Version, wiederholter Schlüssel und Widerruf vor verzögerter Ausführung.
- Zeitsteuerung mit injizierbarer Uhr: Mitternacht, Sommer-/Winterzeit, Ruhezeiten, Bündelungsfristen und Neustarts an jeder Zustellgrenze.
- Zustellung: identische Ereignisse, Vorschlagsrevisionen, inzwischen erledigte Vorgänge, deaktivierte Kanäle, abgemeldete Geräte, Providerfehler und unklare Resultate.
- Datenschutz: Diagnoseexport, Logs, Queue und Push-Payloads auf unerlaubte Inhalte prüfen.
- Playwright: Desktop, Smartphone, schmales Display, Tastaturbedienung und Basisfunktionen ohne JavaScript. Bestehende vollständige JavaScript-Abdeckung erhalten.
- CI: Windows 11-kompatibler Python-Betrieb, Linux und Docker; Paketinstallation sowie Upgrade und Wiederaufnahme aus synthetischen 2.0-Zuständen prüfen.

## 8. Upgrade und Release-Abnahme

- Vor Migration Konfiguration und Zustand sichern; Migrationsschritte atomar, versioniert und wiederholbar ausführen.
- Ohne neuen `notifications`-Abschnitt bleiben die bisherigen Kanalentscheidungen erhalten. Ruhezeiten und Bündelung werden nicht ungefragt aktiviert.
- Bereits unter 2.0 versandte Entscheidungs- und Briefingmeldungen dürfen durch Migration oder erstmaligen Start der neuen Queue nicht erneut verschickt werden. Bestehende Zustellmarker müssen in die Initialisierung einfließen.
- Die Queue-Migration benötigt eine dokumentierte Rollback-Strategie. Alte und neue Scheduler dürfen nicht gleichzeitig dieselben Ereignisse zustellen.
- `config.example.yaml`, README, Projektspezifikation und Datenschutzhinweise werden aktualisiert. `docs/Release-3.0.md` beschreibt Einrichtung, Migration, Diagnose, Grenzen und Wiederherstellung.
- Freigabe als 3.0.0 erst nach allen Abnahmekriterien, vollständigen Coverage-Gates und erfolgreicher Plattformmatrix. Versions- und Changelog-Pflege erfolgt gemäß den Commit-Regeln des Projekts.

## 9. Priorisierung bei Umfangsänderungen

Zum verbindlichen Kern gehören sichere Einrichtung, unabhängige Diagnosen, verständliche Fehlerhilfe, Kanalwahl, tägliche Ruhezeiten, Bündelung und dauerhafte Zustellzustände. Wenn zusätzliche Wünsche entstehen, bleiben diese Kernfunktionen samt Sicherheits- und Testanforderungen vorrangig.

Nicht nachträglich in diesen Plan hineinziehen: komplexe Wochenkalender für Ruhezeiten, neue Messenger, Fernsupport mit automatischem Datenexport oder automatisch ausgeführte fachliche Aktionen. Solche Erweiterungen benötigen eine eigene Planung.
