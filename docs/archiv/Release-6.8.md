# Mailhelp 6.8 – Web-Push prüfen und wiederherstellen

## Nachtrag 6.8.2

6.8.2 begrenzt den Releaseumfang auf die beauftragten Dateien. Die versehentlich
aufgenommene Zukunftsplanung für 7.0 bleibt lokal erhalten und gehört nicht zum
Versionsbestand. Der geprüfte Funktionsumfang von 6.8.1 bleibt erhalten.

## Umfang

6.8.1 bündelt die Umsetzung der Arbeitspakete D1 bis D7 aus
[Planung 6.8](Planung-6.8.md) in einer gemeinsamen Veröffentlichung.
Die dort vorgeschlagenen Zwischenstände 6.8.2 bis 6.8.7 sind keine separat
veröffentlichten Versionen.

Die Benachrichtigungseinstellungen zeigen neun Prüfstufen einschließlich
Browserberechtigung, Hintergrunddienst, Schlüsselvergleich, Speicherung,
effektiven Postfachkanälen und letzter Anbieterantwort. Der Status betrifft nur
die angemeldete Sitzung. Ohne JavaScript bleiben die Serverstufen sichtbar.
Bei ausgeschaltetem Server-Push fehlen Aktivierungs- und Testschaltflächen.

Ein vorhandenes Browser-Abonnement wird bei gleichem Anwendungsschlüssel
weiterverwendet. Ein abweichender Schlüssel erfordert ein neues Abonnement.
401 und 403 sperren weitere Zustellversuche bis zur ausdrücklichen
Neuaktivierung; 404 und 410 entfernen das abgelaufene Abonnement. Bei 429,
5xx und Netzwerkfehlern gelten weiterhin die Wiederholungsregeln der Warteschlange.
Auch der ältere `notify`-Weg verwendet diese Behandlung.

Zusätzlicher Befund B14: JSON `null` am Aktivierungsendpunkt wurde als Abmeldung
behandelt. Der Regressionstest meldet zunächst ein Gerät an und weist nach,
dass die ungültige Aktivierung dessen Abonnement entfernen konnte. Der Endpunkt
akzeptiert jetzt ausschließlich JSON-Objekte und lässt den gespeicherten Zustand
bei ungültigen Eingaben unverändert.

Jede Nachrichtenart hat einen festen neutralen Text und ein festes Ziel im
Service Worker. Die übertragene Nachricht enthält ausschließlich die Art,
keine Mailinhalte oder Links. Das Gerät bestätigt den Empfang an offene
Mailhelp-Fenster. „Vom Anbieter angenommen“, „am Gerät angekommen“ und die
tatsächlich sichtbare Systemmeldung werden getrennt beurteilt.

Neue Konfigurationsvorlagen enthalten Web-Push für Entscheidungen und
Tagesüberblick. Bestehende Profile werden erst über eine authentifizierte
Vorschau mit ausdrücklicher Bestätigung und Dateiversionsprüfung geändert.
Die bisherigen Kanäle bleiben erhalten. Postfachabweichungen werden angezeigt.

Der Aktivierungszeitpunkt und die Herkunft jeder Vorschlagsversion werden
dauerhaft gespeichert. Bereits offene Vorschläge erzeugen beim Aktivieren
keine Meldung. Eigene Änderungen aus Web und Telegram bleiben still;
spätere systemseitige Versionen können wieder gemeldet werden.
Alte Abonnements erhalten beim ersten Start den Migrationszeitpunkt.
Die zusätzliche Herkunft im Rückfragezustand ist optional und bleibt mit
vorhandenen Zuständen kompatibel.

## Befund der Produktivinstanz vor dem Update

Am 14. November 2026: installierte iOS-Web-App laut Betreiber, bekannte
Produktivadresse `https://stefan.inboxstride.de`. Die genaue iOS-Version und
ein Geräteprotokoll liegen noch nicht vor.

Die rein lesende Serverprüfung fand `push.enabled: false`, den Beispielwert
`mailto:admin@example.invalid` und **kein gespeichertes Geräteabonnement**.
Damit scheitert bereits Stufe 1 (B4). Ein Fehler des Apple-Dienstes oder ein
VAPID-Ablehnungscode ist dadurch nicht nachgewiesen. Der Beispielabsender
wird als Konfigurationshinweis angezeigt, nicht als bewiesene Ursache einer
Anbieterablehnung.

WebKit beschreibt Push für zum Home-Bildschirm hinzugefügte Web-Apps unter
iOS/iPadOS: [WebKit-Dokumentation](https://webkit.org/blog/13878/web-push-for-web-apps-on-ios-and-ipados/).
Der VAPID-Kontakt ist in [RFC 8292](https://www.rfc-editor.org/rfc/rfc8292.html)
beschrieben.

## Betrieb und Geräteabnahme

1. Unter „Einrichtung“ Web-Push einschalten und eine gültige Betreiberkontaktadresse
   als `push.subject` eintragen; Änderung bestätigen und Mailhelp neu starten.
2. Die installierte iOS-Web-App über dieselbe HTTPS-Adresse öffnen. Unter
   „Einstellungen → Benachrichtigungen“ Push aktivieren und die neun Stufen prüfen.
3. Falls der Profilhinweis erscheint, die Kanalvorschau öffnen und ausdrücklich bestätigen.
4. Den neutralen Test-Push senden; Systemmeldung und Ziel beim Antippen kontrollieren.

Der Betreiber hat den neutralen echten Test-Push nach Installation ausdrücklich
freigegeben. Ohne registriertes Gerät ist ein echter Versand technisch nicht
möglich. Die tatsächliche Anzeige auf iPhone, Android und Desktop sowie der
Empfang bei geschlossener App bleiben bis zur Geräteprüfung **offene Abnahme**.
Automatisierte Browserattrappen ersetzen diese Prüfung nicht.

Der Testendpunkt benötigt Sitzung, CSRF-Token, Prüfversion und Idempotenzschlüssel.
Er begrenzt neue Aufrufe auf drei pro Minute je Sitzung. Nach 20 Sekunden ohne
Geräterückmeldung nennt die Oberfläche Fokus-Modus, Systemeinstellungen und
Energiesparen als nächste Prüfpunkte.

`web-vapid.json`, `push-key-status.json`, `push-subscriptions.json`,
`push-decision-events.json` und die Sitzungsdatei gehören ins dauerhaft
eingebundene Datenverzeichnis und in die Sicherung. Sie enthalten vertrauliche
Zustände und dürfen nicht öffentlich erreichbar sein. Protokolle enthalten nur
Stufe, festen Ergebniscode, HTTP-Statusklasse und Anbieterkurzname.

## Prüfstand

Automatisierte Tests verwenden ausschließlich synthetische Mails, Geräte und
Anbieter. Der vollständige Python-Lauf umfasste 5.288 Fälle. Die Nachprüfung
von 129 Fällen ergänzt die letzte fehlende Verzweigung, die B14-Regression und
den präzisen Passwort-Hilfeabschnitt im Hilfekorpus. Gemessen sind **34.075
Anweisungen und 9.968 Zweige mit jeweils 100 % Abdeckung**. Rückfrageantworten
werden zusätzlich über den echten Befehlsweg für Web und Telegram geprüft,
einschließlich späterer Systemversion, zweier Geräte, Postfachabweichungen und Ruhezeiten.

Beide getrennten Lasttests bestanden. Bei 2.000 Mails betrug die Zeit bis zur
Ergebnisanzeige im Median 485 ms, maximal 669 ms.

Die vollständige Browser-Suite lief mit 982 Fällen. Zwei Fehler in den neuen
Testattrappen (Worker-Zugriff und zu frühe Abfrage einer laufenden Aktivierung)
wurden behoben. Die Nachprüfung bestand mit 91 Fällen. Ihre Messungen wurden
mit dem vollständigen Lauf zusammengeführt; die fünf Skriptdateien wurden dabei
per SHA-256 auf unveränderte Inhalte geprüft. Ergebnis: **100 % JavaScript-
Blockabdeckung** in `app.js`, `sw.js`, `setup.js`, `topics.js` und `learning.js`.
Für B1, B2, B3, B11, B12 und B13 liegen scheiternde Nachweise auf dem
ursprünglichen Code beziehungsweise der Vorlage von 6.7.4 vor.

Die Geräteabnahme wird erst nach realer Rückmeldung als erfolgreich vermerkt.


## Nachtrag 6.9.1: gleicher Uhrtakt

Bei der Abschlussprüfung von 6.9 scheiterte ein Push-Test zeitabhängig. Ursache: Ein Gerät
erhielt nur Vorschläge, die strikt nach seiner Aktivierung erschienen. Unter Windows liefert
die Uhr für aufeinanderfolgende Aufrufe oft denselben Wert; ein Vorschlag im selben Takt wie
die Aktivierung wurde dann nie gemeldet. Seit 6.9.1 zählt der gleiche Zeitpunkt als „danach“.
Ältere offene Vorschläge bleiben stumm. Ein Regressionstest mit fester Uhr belegt beides.

## Produktivinstallation 6.8.2

Am 15. November 2026 wurde das geprüfte Image `6.8.2-6d52f39597b1` installiert.
Die vollständige Sicherung liegt unter `/opt/mailhelp/backups/pre-6.8.2-20261115T062537Z`.
Alle zehn Sitzungen sowie die Prüfsummen der Konfigurations- und Geheimnisdateien
blieben erhalten. HTTPS, ausgelieferte Skripte und Stylesheets sowie Anmeldungspflicht
wurden geprüft. Nach 345 Sekunden: keine Neustarts und keine neuen Fehlerereignisse.
Push war weiterhin deaktiviert und kein Gerät registriert; der freigegebene echte
Test-Push wartet auf Aktivierung des iOS-Geräts.
