# Mailhelp 8.1 – Einfache Postfacheinrichtung und zuverlässige Terminrückfragen

**Stand:** 20. November 2026. **Status:** In Umsetzung; Nachweise und offene
Freigaben im [Releasebericht](Release-8.1.md). Arbeitsversion 8.1.1.

**Zielversion:** 8.1, erste Auslieferung 8.1.1; Patchversionen gemäß AGENTS.md.

**Grundlagen:** [Entwicklungsregeln](../AGENTS.md), [Planung 8.0](Planung-8.0.md),
[Ersteinrichtung](Ersteinrichtung.md), [Kontenverwaltung](Konten-verwalten.md).
Dieser Plan autorisiert weder eine Produktionsumstellung noch neue Anbieterfreigaben.

**Zusätzlicher verbindlicher Umfang:** Fehlerbehebung für die Übernahme eines
fehlenden Datums bei bereits bekannter Uhrzeit sowie sichere Wiederaufnahme der
dadurch pausierten Rückfragen; siehe Abschnitt 9. Die Anbietereinrichtung und
Postfach-OAuth2 bleiben unverändert Bestandteil dieser Version.

## 1. Ziel und Abnahme aus Nutzersicht

Der Nutzer gibt seine E-Mail-Adresse ein, bestätigt den vorgeschlagenen Anbieter oder
wählt ihn aus einer Liste und verbindet sein Postfach. Mailhelp übernimmt IMAP-Server,
Port und TLS-Einstellungen. Je nach Anbieter erfolgt die Anmeldung mit Passwort,
App-Passwort oder über Google beziehungsweise Microsoft. Technische Serverkenntnisse
sind für unterstützte Standardangebote nicht erforderlich.

- Derselbe Ablauf funktioniert bei der Ersteinrichtung, beim Hinzufügen weiterer
  Postfächer und beim Ändern oder erneuten Verbinden bestehender Zugänge.
- Ein Beispiel: `name@web.de` schlägt WEB.DE mit `imap.web.de`, Port 993 und TLS vor.
  Der Nutzer erhält vor der Prüfung den Hinweis auf die notwendige IMAP-Freischaltung.
- Bei einer eigenen Domain kann der Nutzer den tatsächlichen Hoster auswählen.
  Aus der Domain allein wird kein sicher erkannter Anbieter behauptet.
- Gmail und Outlook bieten eine passende OAuth2-Verbindung statt eines irreführenden
  Formulars für das normale Kontopasswort an.
- „Anderer Anbieter / Manuell einrichten“ bleibt verfügbar. Erweiterte Einstellungen
  zeigen die tatsächlich verwendeten Werte und erlauben bewusstes Überschreiben.
- Die Verbindung wird geprüft; Posteingang und Entwurfsordner werden anhand der
  vorhandenen Ordner und IMAP-Spezialattribute vorgeschlagen und bestätigt.
- Abbruch oder fehlgeschlagener Kontowechsel erhalten den bisher funktionierenden
  Zugang. Bestehende Vorschläge und die Verarbeitungsposition bleiben erhalten.

## 2. Tatsächlicher Ausgangsstand

Mailhelp besitzt OAuth2-Bausteine für Google-Kalender beziehungsweise Google Tasks
und Microsoft-Ziele sowie Token-Erneuerung. 8.0 erweitert die gehostete
Google-Kalenderverbindung über den zentralen Inboxstride-Anmeldedienst.

Der IMAP-Reader in `src/mailhelp/mailbox/imap.py` verwendet dagegen gegenwärtig
`connection.login(username, password)`. Ein OAuth2-Zugang für ein Kalenderziel
ist keine Berechtigung zum Lesen eines Postfachs. IMAP-XOAUTH2, Postfachberechtigungen
und ihre Anbindung an Einrichtung und Kontenverwaltung gehören neu zu 8.1.

## 3. Anbietervorlagen und Erkennung

Versionierte, lokal verfügbare Vorlagen bilden den verbindlichen Ausgangspunkt.
Umsetzungsentscheidung: Die Anbieterreferenzdaten liegen getrennt unter
`src/mailhelp/defaults/imap-providers.yaml`; nach Auswahl werden nur die tatsächlichen
Verbindungswerte in `config.yaml` übernommen. Neue Vorlagen ändern keine aktiven Konten.
Keine Zugangsdaten in Vorlagen. Der Katalog enthält stabile Anbieter-ID,
Anzeigename, bekannte Domains, Host, Port, TLS-Modus, Anmeldeverfahren,
Benutzernamensmuster, Hilfelinks, Hinweise und Datum der Quellenprüfung.

| Erste unterstützte Auswahl | IMAP-Host | Anmeldung / Besonderheit |
| --- | --- | --- |
| WEB.DE | `imap.web.de` | Passwort oder App-Passwort; IMAP freischalten |
| GMX Deutschland | `imap.gmx.net` | Passwort oder App-Passwort; IMAP freischalten |
| Telekom / T-Online | `secureimap.t-online.de` | Passwort für E-Mail-Programme |
| IONOS Mail Basic / Business | `imap.ionos.de` | Postfachpasswort; Exchange ist separates Angebot |
| STRATO | `imap.strato.de` | Postfachpasswort |
| Gmail / Google Workspace | `imap.gmail.com` | OAuth2; Administratorregeln berücksichtigen |
| Outlook.com / Hotmail / Microsoft 365 Exchange Online | `outlook.office365.com` | OAuth2; IMAP muss für das Postfach erlaubt sein |
| Apple iCloud | `imap.mail.me.com` | Anwendungsspezifisches Passwort |

Alle Vorlagen verwenden Port 993 mit TLS und Zertifikatsprüfung. Vor Umsetzung
und Freigabe jede Vorlage gegen aktuelle Anbieterquellen prüfen. Abweichende
Produkte und Regionen erhalten eigene Vorlagen statt pauschaler Gleichsetzung.
App-Passwort-Verfügbarkeit und Benutzernamen können vom Konto abhängen.

Thunderbird ISPDB dient als ergänzende Quelle für weitere Domains. Die erste
Auslieferung muss ohne erreichbaren Datenbankdienst funktionieren. Online-Erkennung
ist optional, überträgt höchstens die Domain und niemals Passwort, Token oder die
vollständige Adresse. Nur fester HTTPS-Endpunkt, begrenzte Antwortgröße und Laufzeit,
keine beliebigen Weiterleitungen, keine XML-Entitäten und strikte Schemaprüfung.
Unbekannte oder widersprüchliche Daten verlangen eine bewusste Auswahl. Übernommene
Werte werden lokal gespeichert; Datenbankänderungen ändern aktive Konten nicht.
Automatische Abfragen beliebiger Autoconfig-URLs oder interne DNS-/Netzwerkziele
sind nicht Bestandteil dieser Version. Vor Übernahme von ISPDB-Dateien Lizenz und
erforderliche Hinweise dokumentieren.

## 4. OAuth2 für den Mailabruf

### Gemeinsamer Ablauf

- IMAP unterstützt ausdrücklich getrennte Verfahren `password` und `oauth2`.
  Bestehende Konfigurationen bleiben ohne Migration im bisherigen Passwortmodus.
- XOAUTH2 verwendet kurzlebige Access-Tokens aus einem Tokenprovider. Tokens werden
  vor Ablauf erneuert; parallele Abrufe koordinieren die Erneuerung. Rotation,
  Neustarts und Verbindungswiederaufbau dürfen keine gültigen Tokens verlieren.
- Autorisierungsauftrag bindet Instanz, Postfach-ID, Zweck und Konfigurationsversion.
  State, PKCE, Ablaufzeit, authentifizierte Sitzung und CSRF-Schutz sind verpflichtend.
  Callback-Ziele und Rücksprünge stammen ausschließlich aus erlaubter Konfiguration.
- Ein Kandidatenzugang wird erst nach erfolgreicher Postfachprüfung und explizitem
  Übernehmen aktiviert. Abbruch oder verspätete Callbacks überschreiben nichts.
- Eine fremde IMAP-Adresse darf niemals ein Token erhalten: Host, Anbieter und
  OAuth-Verfahren werden gebunden; manuelle Hoständerung erfordert Neuprüfung.
- Fehler unterscheiden Verbindungsstörung, gesperrtes IMAP, fehlende Berechtigungen,
  abgelaufene Anmeldung und Administratorvorgaben. Keine endlosen Anmeldeversuche.
  Die Mailübersicht zeigt die betroffene Verbindung und „Erneut verbinden“.
- Postfachzugänge und Kalender-/Aufgabenzugänge werden getrennt verwaltet.
  Trennen eines Postfachs löscht keine Kalenderverbindung und keine externen Daten.

### Google

Den zentralen Dienst aus 8.0 um den ausdrücklichen Zweck „Postfach“ erweitern.
Gmail-IMAP verwendet den Scope `https://mail.google.com/`; Kalender-Scopes reichen
nicht. Keine automatische Erweiterung bestehender Kalenderfreigaben. Verbindungen
und Tokenausgabe müssen den freigegebenen Zweck und die tatsächlichen Scopes prüfen.
Kein stiller Rückfall auf das normale Google-Passwort. Ein optionaler App-Passwortmodus
muss als eigener manueller Weg mit seinen Kontovoraussetzungen gekennzeichnet sein.

Vor produktiver Freigabe Anforderungen an eingeschränkte Google-Berechtigungen,
OAuth-Verifizierung und gegebenenfalls Sicherheitsprüfung klären. Der IMAP-Scope ist
breit; Anforderungen und Aufwand gegen eine spätere Gmail-API-Alternative bewerten.
Datenschutzerklärung, Google-Anwendungsinformationen und tatsächliche Weitergabe an
LLM-Dienste auf Zulässigkeit und Übereinstimmung prüfen. Offene Freigaben bleiben als
Releaseblocker sichtbar; erfolgreiche Tests ersetzen keine Anbieterfreigabe.

### Microsoft

Delegierte Postfachfreigabe mit `https://outlook.office.com/IMAP.AccessAsUser.All`
und `offline_access` gemäß aktueller Microsoft-Dokumentation einrichten. Keine
vorsorglichen SMTP-, Graph-Mail- oder anwendungsweiten Postfachrechte anfordern.
Private Microsoft-Konten und Microsoft-365-Mandanten getrennt prüfen; vorhandene
Graph-Tokens für Kalender beziehungsweise Aufgaben nicht für IMAP wiederverwenden.
App-Registrierung, Kontotypen, Redirect, Zustimmung und Administratorbeschränkungen
für den gehosteten Dienst dokumentieren. Selbstbetrieb erhält einen dokumentierten
Modus mit eigener App-Registrierung. Gemeinsame Postfächer und lokale Exchange-Server
gehören nicht zur zugesagten Standardunterstützung von 8.1.

## 5. Sicherheit, Speicherung und Betrieb

Passwörter und Refresh-Tokens bleiben außerhalb von Konfigurationsvorlagen und Git.
Gehostete OAuth-Geheimnisse liegen im geschützten zentralen Speicher aus 8.0;
Instanzen erhalten nur berechtigte Access-Tokens über die abgesicherte Schnittstelle.
Sicherstellen, dass Protokolle, Fehlermeldungen und IMAP-Debugausgaben weder Tokens
noch die kodierte XOAUTH2-Nutzlast enthalten. Tests verwenden synthetische Konten.

Neue Anmeldeverfahren autorisieren keine Kalender-/Todoist-Schreibaktionen.
Verbindungsprüfungen erstellen keine Testmails oder Entwürfe und verändern keine
Nachrichtenflags. Unterschiedliche Zugangsdaten dürfen keine doppelte Verarbeitung
derselben Nachrichten auslösen; Kontowechsel und UIDVALIDITY-Wechsel explizit behandeln.

Serverhandbuch und Vorlagen enthalten Google-/Microsoft-App-Einrichtung, Callbacks,
Secrets-Namen, ausgehende HTTPS-/IMAPS-Verbindungen, TLS, Tokenwarnungen,
Wiederverbindung sowie Wiederherstellung und Rückkehr zur Vorversion. Neue
Zustandsformate versionieren; vor Migration sichern und Downgrade-Grenzen benennen.
Backup muss den erweiterten OAuth-Zustand samt benötigten Schlüsseln erfassen.
Nach erfolgreich geprüften Serveränderungen gemäß AGENTS.md auch die Kopie unter
`/opt/mailhelp/server-docs` aktualisieren und ihre Aufnahme ins Backup nachweisen.

## 6. Umsetzung in Arbeitspaketen

Den unabhängig reproduzierbaren Terminfehler aus Abschnitt 9 zuerst mit einem
Regressionstest absichern und beheben; er benötigt keine neuen OAuth-Freigaben.
Die anschließenden Arbeitspakete betreffen die Postfacheinrichtung:

1. Vorlagenmodell, aktuelle Quellenprüfung, Validierung, rückwärtskompatibles
   Konfigurationsschema und gemeinsame Nutzung in Einrichtung/Kontenverwaltung.
2. Anbieterauswahl, Domainvorschlag, Anbieterhinweise, erweiterte Felder und
   Ordnererkennung vollständig auf Deutsch und Englisch; passende Demo-Beispiele.
3. IMAP-Authentifizierung abstrahieren; XOAUTH2 und sichere Token-Erneuerung anbinden.
4. Zentralen Google-Postfachzweck samt separater Zustimmung und Freigaben integrieren.
5. Microsoft-Postfach-OAuth einschließlich Registrierung und Wiederverbindung ergänzen.
6. Optionalen ISPDB-Abgleich ergänzen, ohne Abhängigkeit für den Grundablauf.
7. Bedienung, Spezifikation, Datenschutz, Serverhandbuch und Konfigurationsbeispiele
   aktualisieren; Freigaben, Abnahme und gestaffelte Bereitstellung dokumentieren.

## 7. Verbindliche Prüfung und Freigabekriterien

- Erfolg, unbekannter Anbieter, eigene Domain, manuelle Überschreibung, App-Passwort,
  IMAP deaktiviert, falsche Zugangsdaten, TLS-Fehler und nicht verfügbare Datenbank.
- XOAUTH2 gegen simulierte IMAP-Server: gültiger Token, Ablauf, Rotation, Widerruf,
  fehlende Scopes, falsche Zielgruppe, Neustart, gleichzeitige Abrufe und Wiederverbindung.
- OAuth-Abbruch, veraltete Sitzung, CSRF-/State-/PKCE-Fehler, Callback-Wiederholung,
  Kontowechsel und zwei gleichzeitig aktive Instanzen ohne Zugriff auf fremde Tokens.
- Bestehende Passwortkonten funktionieren unverändert; Kalender-/Aufgabenzugänge
  behalten ihre Rechte und Bestätigungsregeln. Kein Credential-Logging und kein
  Passwort-/Tokenversand an unbestätigte Hosts oder Erkennungsdienste.
- End-to-End-Assistent und Kontenverwaltung in DE/EN, mobile Ansicht, Fehlermeldungen
  und Warnlinks; Verbindung und Ordnerprüfung ohne externe Schreibaktionen.
- 100 % Zeilen- und Branch-Abdeckung für eigenen Code; jeder Bugfix mit nachweislich
  vor dem Fix fehlschlagendem Regressionstest. Vollständige Python-Prüfung mit
  `python -m devtools.check full --workers 12`, danach getrennt Browsersuite mit
  `python -m pytest ui_tests -n 6 --dist worksteal --no-cov`.
- Anbieterfreigaben, isolierte Betriebs-/Wiederherstellungsprobe und Rollback-Nachweis
  vor Produktivfreigabe. README, CHANGELOG und Versionen gemäß Commit-Regeln pflegen.

## 8. Primärquellen

- [Thunderbird ISPDB](https://github.com/thunderbird/autoconfig/wiki/The-ISP-database)
- [WEB.DE Serverdaten](https://hilfe.web.de/pop-imap/imap/imap-serverdaten.html)
- [GMX Serverdaten](https://hilfe.gmx.net/pop-imap/imap/imap-serverdaten.html)
- [Telekom Serverdaten](https://www.telekom.de/hilfe/apps-dienste/e-mail/posteingang-postausgang-server)
- [IONOS Serverdaten](https://www.ionos.de/hilfe/e-mail/allgemeine-themen/serverinformationen-fuer-imap-pop3-und-smtp/)
- [STRATO Serverdaten](https://www.strato.de/faq/mail/externes-e-mail-programm-mit-strato-e-mail-adresse-nutzen/)
- [iCloud Serverdaten](https://support.apple.com/en-mt/102525)
- [Google XOAUTH2 und Mail-Scope](https://developers.google.com/workspace/gmail/imap/xoauth2-protocol)
- [Google eingeschränkte Berechtigungen](https://support.google.com/cloud/answer/13464325)
- [Microsoft IMAP-OAuth](https://learn.microsoft.com/en-us/exchange/client-developer/legacy-protocols/how-to-authenticate-an-imap-pop-smtp-application-by-using-oauth/)

## 9. Bugfix: Fehlendes Datum bei bekannter Beginnzeit ergänzen

### 9.1 Befund und reproduzierte Ursache

Am 19. November 2026 wurde der Vorgang „Vlf Schulungstagung Bad Waldsee“ auf dem
Produktivserver lesend untersucht. Der Vorschlag steht in Version 3 auf
`needs_clarification`. Die Antwort auf „Wann beginnt der Termin?“ wurde als gültig
interpretiert und dauerhaft als `2027-01-07 11:30` gespeichert. Drei Versuche der
Übernahme scheiterten zwischen 15:26 und 15:28 Uhr Europe/Berlin mit
`ContradictoryRevision`; danach wechselte die Rückfrage in `paused`.

Eine lokale Nachstellung mit synthetischen Daten reproduziert die Ursache ohne
LLM-Aufruf und ohne externe Dienste:

1. Der Vorschlag enthält `known_temporal_facts.start_time = 11:30`, aber weder
   ein Datum noch einen vollständigen Beginn. Beginn und Ende sind offene Fragen.
2. `deterministic_temporal_revision` ergänzt aus der Antwort Datum und Uhrzeit.
   Die Modellnormalisierung speichert den noch unvollständigen Zeitraum in
   `known_temporal_facts`: Datum und vollständiger Beginn sind gesetzt, die separate
   Uhrzeit entfällt zugunsten des vollständigen Beginns. Das Ende bleibt offen.
3. `validate_revision_successor` in `processing/analysis.py` akzeptiert eine
   Anreicherung derzeit nur, wenn das Datum im Faktenobjekt unverändert bleibt.
   Der Übergang von unbekanntem zu bekanntem Datum wird deshalb fälschlich mit
   „Bekannte Zeitfakten dürfen nicht verändert werden“ abgewiesen.

Die gespeicherte Nutzerantwort ist nicht verloren. Ein Neustart allein behebt
weder die Konsistenzprüfung noch den pausierten Zustand. Dieser Befund ist kein
Google-Authentifizierungsfehler. Die ursprüngliche fehlende Datumsextraktion ist
ein gesonderter Aspekt; der hier zugesagte Fix betrifft die gültige Rückfrageantwort.

### 9.2 Geplante Korrektur

- Den Revisionsvertrag für Zeitfakten feldweise präzisieren: Unbekannte Fakten
  dürfen durch eine validierte Antwort ergänzt werden; bereits bekannte Fakten
  müssen erhalten bleiben. Eine bloße Entfernung von Schutzprüfungen ist unzulässig.
- Den Übergang von `start_time` zu einem vollständigen Beginn ausdrücklich erlauben,
  wenn die lokale Beginnzeit in der konfigurierten Zeitzone mit der bisherigen
  Uhrzeit übereinstimmt und das neue Datum durch die Antwort belegt ist.
- Bereits bekanntes Datum, vollständigen Beginn und Enddatum weiter schützen.
  Ein Widerspruch muss weiterhin scheitern. Ein vorhandenes Enddatum darf weder
  verloren gehen noch durch die Ergänzung eines Beginndatums unbemerkt ändern.
- Deterministische Übernahme, `apply_proposal_revision`, Modellnormalisierung und
  `validate_revision_successor` gemeinsam prüfen. Der reparierte Weg führt über
  `build_revision_successor`; kein Sonderweg nur für diesen Produktionsvorgang.
- Unvollständige Intervalle bleiben im vorgesehenen Faktenobjekt. Solange das Ende
  fehlt, bleiben Status und offene Endfrage konsistent. Kein geratenes Ende, keine
  automatische Ganztagsumwandlung und keine Freigabe zur externen Anlage.
- Die akzeptierte Antwort erzeugt genau eine Nachfolgeversion, schützt die
  ergänzten Nutzerangaben und leitet zur nächsten offenen Frage weiter.

### 9.3 Regressionstests und Abnahme

Vor Änderung des Codes einen synthetischen Regressionstest ergänzen, der den
vollständigen Weg über `build_revision_successor` mit ausschließlich bekannter
Beginnzeit und einer Antwort mit Datum und gleicher Uhrzeit ausführt. Er muss
vor dem Fix an der genannten Konsistenzprüfung scheitern und danach bestehen.

Zusätzlich verbindlich prüfen:

- Unbekanntes Datum wird ergänzt; gleicher lokaler Beginn bleibt erhalten,
  Ende bleibt unbekannt und nur die Endfrage bleibt offen.
- Eine abweichende bekannte Uhrzeit, ein geändertes bekanntes Datum oder ein
  geänderter vollständiger Beginn werden weiterhin abgewiesen; vorhandenes Enddatum
  bleibt erhalten. Andere vorgeschlagene Änderungen umgehen den Schutz nicht.
- Kein Jahresraten bei zweistelligen Angaben: Für die Wiederaufnahme wird die
  bereits normalisierte Antwort mit vierstelligem Jahr verwendet. Den bestehenden
  Interpretationsweg mit kurzem Jahr separat gegen seine bisherigen Regeln prüfen.
- Zeitvergleich in der konfigurierten Zeitzone, UTC-Darstellung desselben Zeitpunkts,
  Sommer-/Winterzeit sowie mehrdeutige oder nicht existierende Ortszeiten.
- Integration über gespeicherte Rückfrage und Revisionsprozessor für Web und Telegram:
  gültige Antwort, nächste Frage, Neustart, Wiederholung und konkurrierender
  Versionswechsel; keine zweite Nachfolgeversion und kein erneuter LLM-Aufruf für
  eine eindeutig deterministisch auswertbare normalisierte Antwort.
- Zustands- und Fehlerfalltests der gezielten Wiederaufnahme aus Abschnitt 9.4.
  Automatisierte Tests nutzen ausschließlich synthetische Daten und simulierte Dienste.

Es gelten die vollständigen Python-/Browserprüfungen und die verbindlichen
100 % Zeilen- und Branch-Abdeckung aus Abschnitt 7 und AGENTS.md.

### 9.4 Sichere Wiederaufnahme bereits pausierter Vorgänge

Nach geprüftem Fix einen dokumentierten, gezielten Betreiberablauf vorsehen.
Kein pauschales Zurücksetzen sämtlicher pausierter Rückfragen beim Start:

1. Betroffene Zustandsdateien konsistent sichern. Vorschlag, gespeicherte Rückfrage,
   aktuelle Version, beantwortete Frage und gültige normalisierte Antwort abgleichen.
2. Nur den nachweislich betroffenen, unveränderten Vorgang auswählen. Eine inzwischen
   bearbeitete, abgeschlossene, abgelehnte oder entfernte Version nicht reaktivieren.
   Da die bisherigen Logs nur die Fehlerklasse speichern, genügt
   `ContradictoryRevision` allein nicht als Auswahlkriterium.
3. Die gespeicherte Antwort mit der korrigierten Logik ohne Persistierung und ohne
   externe Dienste vorprüfen. Bei Widerspruch Zustand unverändert lassen.
4. Mit Versionsprüfung und Sperre ausschließlich den passenden Rückfragestatus auf
   `retry_required` setzen, den Versuchszähler für diesen Reparaturversuch zurücksetzen
   und einen sofort möglichen Wiederholungszeitpunkt setzen. Nutzerantwort und Herkunft
   erhalten; bestehende Wiederaufnahmelogik kontrolliert ausführen.
5. Prüfen, dass genau eine neue Vorschlagsversion entsteht, die Beginnangabe korrekt
   übernommen wurde, die Rückfrage als verarbeitet gilt und die Endfrage sichtbar ist.
   Erneuter Start oder Wiederholen des Betreiberablaufs darf nichts doppelt übernehmen.
6. Bei erneutem Fehler begrenzt pausieren und einen datensparsamen Fehlercode
   dokumentieren. Keine Kalender-/Todoist-Schreibaktion im Reparaturablauf; deren
   versionsgebundene Bestätigung erfolgt weiterhin ausschließlich über die Anwendung.

Für den konkreten Vorgang ist anschließend das Terminende durch den Nutzer zu
klären. Das Programm darf weder aus dem Titel noch aus einem Programmpunkt ein
ungeprüftes Ende ableiten.

### 9.5 Dokumentation und Bereitstellung

Spezifikation um erlaubte Ergänzungen bekannter Zeitfakten erweitern. Fehlerhilfe
und Betrieb beschreiben Pausengrund, Voraussetzungen, gezielte Wiederaufnahme,
Erfolgskontrolle und Rückkehr zum gesicherten Zustand. Ein strukturierter,
datensparsamer Fehlercode soll den verletzten Revisionsvertrag erkennbar machen;
keine Rohantworten, Mailinhalte oder Zugangsdaten in Logs aufnehmen.

README, CHANGELOG und Versionsnummern bei Umsetzung gemäß Commit-Regeln aktualisieren.
Vor Produktion Migration beziehungsweise Kompatibilität mit alten Vorschlägen und
Rückfragen prüfen. Nach erfolgreicher Serveränderung Betriebsdokumentation und
`/opt/mailhelp/server-docs` synchronisieren und Sicherung nachweisen. Dieser Abschnitt
ist ein Umsetzungsplan; auf dem Server wurden dadurch keine Zustände geändert.
