<!--
Hinweise für Betreibende (vor Veröffentlichung entfernen):
- Platzhalter in [eckigen Klammern] ersetzen (Name, Anschrift, Kontakt).
- Die technischen Angaben entsprechen dem Repository-Stand 7.0 (16.11.2026).
  Bei abweichender Konfiguration (andere Modelle, Anbieter, Aufbewahrungsfristen,
  Logging) diese Erklärung anpassen.
- Für eine Google-OAuth-Prüfung muss diese Seite öffentlich erreichbar sein und zur
  im OAuth-Zustimmungsbildschirm eingetragenen Domain passen.
- Dieser Text ist eine sorgfältig erstellte Vorlage, keine Rechtsberatung.
-->

# Datenschutzerklärung für Mailhelp

Stand: 16. November 2026 · Geprüft für Mailhelp 8.1

## 1. Worum es geht

Mailhelp ist eine selbst betriebene Software. Sie liest E-Mails aus einem oder mehreren Postfächern derselben Person,
lässt sie mit KI-Modellen auswerten und schlägt daraus Aufgaben und Termine vor.
Als Ziele stehen Google Kalender, Todoist, Outlook / Microsoft 365, Microsoft To Do,
CalDAV und Apple Erinnerungen (über iCloud-CalDAV) zur Verfügung. Die Vorschläge werden über einen optionalen Telegram-Bot oder die
authentifizierte Weboberfläche zur Bestätigung vorgelegt. Mailhelp legt **nichts**
im Kalender oder in der Aufgabenliste an, solange die berechtigte Person die konkrete
Vorschlagsversion nicht ausdrücklich über einen dieser beiden Kanäle bestätigt hat.
Das Speichern einer Bearbeitung allein ist keine Bestätigung.

Mailhelp ist kein öffentlicher Dienst. Eine Instanz wird von einer Person für ihr
eigenen Postfächer (bis zu zehn) betrieben. Bei aktiviertem Telegram ist genau ein Konto
berechtigt; alternativ ist ein Betrieb ausschließlich über gekoppelte Webgeräte möglich.
Postfächer können eigene Themen, Filter, Zielprofile und Benachrichtigungsregeln besitzen.
Diese Erklärung beschreibt die Instanz der unten genannten verantwortlichen Person.

## 2. Verantwortliche Person

[Vor- und Nachname]
[Straße und Hausnummer]
[PLZ Ort]
E-Mail: [Kontakt-E-Mail-Adresse]

## 3. Welche Daten verarbeitet werden

| Daten | Herkunft | Zweck |
|---|---|---|
| E-Mails: Absender, Empfänger, Betreff, Datum, Nachrichten-IDs, Textinhalt und unterstützte Dokumenten-, Kalender- und Bildanhänge | eigene Postfächer per IMAP | Relevanzprüfung, Zusammenfassung, Erkennung von Aufgaben und Terminen; optional Bild-/Scan-Auswertung |
| IServ-Elternbriefe (optional): Titel, Veröffentlichungsdatum, Name des Kindes, Brieftext und Anhänge | eigenes Elternkonto der Schule über die IServ-Weboberfläche | wie E-Mails, ohne Relevanzprüfung (Elternbriefe gelten immer als relevant) |
| Telegram-Nachrichten und Schaltflächen-Eingaben des berechtigten Kontos | Telegram | Bestätigung, Änderung oder Verwerfen von Vorschlägen; Rückfragen |
| Aufgaben- und Terminvorschläge mit Belegstelle aus der Mail | von Mailhelp erzeugt | Vorlage zur Bestätigung, Anlage nach Bestätigung |
| Quellenreferenzen mit Nachrichtenzeit, Betreff und gehashten Gesprächsankern; Vorschlagsbeziehungen, Vergleichscache und Merge-Journal | lokale Mail- und Vorschlagsakten | Zusammengehörige offene Entscheidungen erkennen, Ergänzungen nachvollziehen und unterbrochene lokale Änderungen wiederaufnehmen |
| Bestehende Termine im Zeitraum eines Terminvorschlags: Titel, Beschreibung, Ort, Beginn, Ende, Link | gewählter Kalenderdienst des Zielprofils | Erkennen von Duplikaten; optional Tagesüberblick |
| Aufgaben in der konfigurierten Aufgabenliste | gewählter Aufgabendienst des Zielprofils | Erkennen bereits angelegter Aufgaben; optional Tagesüberblick |
| Antwortentwürfe mit persönlichen Angaben und Signatur | Mailinhalt und eigene Vorgaben | Entwurf durch KI, lokales Prüfen und Speichern im IMAP-Entwurfsordner nach ausdrücklicher Bestätigung oder, wenn für ein Postfach ausdrücklich eingeschaltet (`auto_draft`), automatisch |
| Tätigkeitsberichte mit Mailbelegen und XLSX-Exporten | ausgewählte Mails des Ursprungspostfachs | ausdrücklich gestartete Berichtsauswertung |
| Web-Push-Abonnements einschließlich Endpunkt und öffentlicher Schlüssel | freigegebener Browser | inhaltsneutrale Hinweise; Widerruf je Gerät |
| Postfachnummern, Zielprofilbindungen, Einrichtungsentwürfe und Diagnoseberichte | lokale Konfiguration und Prüfungen | getrennte Zugänge, Vererbung von Einstellungen und sichere Betriebsprüfung |
| Gelernte Absender- und Themenfilter | aus bestätigten Entscheidungen | künftige Relevanzprüfung |
| Lernbestand: manuelle Entscheidungen mit Mail, KI-Ergebnissen, ursprünglichem und entschiedenem Vorschlag sowie freiwillig gewähltem Ablehnungsgrund | eigene Entscheidungen | Annahmequote, Absenderhinweise und ausdrücklich gestartetes Regellernen |
| Fragen an den Hilfschat und seine Antworten | Eingabe der angemeldeten Person | Erklärung von Einstellungen mit der mitgelieferten Dokumentation |
| Nachweise geschriebener Einträge (Quittung, frisch beim Anbieter gelesene Angaben, Vergleich) | Kalender- bzw. Aufgabendienst des Zielprofils | Prüfen, ob der bestätigte Eintrag wirklich angelegt wurde |
| Technische Protokolle (Zeitpunkte, Status, Fehler) | Mailhelp | Betrieb und Fehlersuche |
| Nur bei aktivierter Weboberfläche: gekoppelte Geräte (selbst gewählter oder aus dem Browser abgeleiteter Gerätename, Zeitpunkte der Kopplung und letzten Nutzung, Sitzungsschlüssel nur als Hash), Kopplungscodes nur als Hash, Web-Aktionen mit Ergebnis | Browser der berechtigten Person | Anmeldung und Bedienung über das Web |

Von Absenderinnen und Absendern verarbeitet Mailhelp nur, was in den empfangenen
E-Mails steht. Der reguläre Abruf verändert weder Nachrichten noch Lesestatus.
Mailhelp versendet keine E-Mails. Die optionale Entwurfsfunktion kann nach gesonderter
Bestätigung einen neuen Entwurf im Ursprungspostfach speichern; ist die automatische Ablage für ein
Postfach ausdrücklich eingeschaltet (`auto_draft`, Standard aus), geschieht das ohne Einzelbestätigung.

Unterstützte Anhangstexte und bei aktivierter Bilderkennung ausgewählte Bild-/Scan-Daten
können an den konfigurierten KI-Dienst übermittelt werden. Optionale Originalanhänge und
Bildvorschauen werden lokal abgelegt und durch die Aufbewahrung des Mailvolltexts bereinigt.
Tätigkeitsberichte besitzen eine eigene Volltextfrist. Persönliche Angaben können auch
in die KI-Auswertung für diese Berichte eingehen.

Beim optionalen KI-Abgleich offener Vorschläge werden begrenzte Vorschlagsfelder
und die letzten drei Quellenbetreffe je Kandidat an den konfigurierten KI-Dienst
übergeben. Der lokale Vergleichscache speichert das strukturierte Vergleichsergebnis
mit Versions- und Policybezug. Quellenreferenzen kopieren keinen vollständigen
Mailtext. Ein laufendes Merge-Journal enthält die für die Wiederaufnahme nötigen
Revisionen; nach Abschluss wird sein Inhaltsanteil gelöscht. Ungeklärte Zusatzquellen
bleiben bis zur Entscheidung vor der Inhaltsbereinigung geschützt.

## 4. Zwecke und Rechtsgrundlagen

Mailhelp dient der Organisation eigener E-Mails. Soweit dies ausschließlich
persönlichen oder familiären Zwecken dient, gilt die DSGVO nach Art. 2 Abs. 2 lit. c
nicht. Soweit sie anwendbar ist, erfolgt die Verarbeitung:

- für die eigene Nutzung: auf Grundlage der Einwilligung beziehungsweise zur
  Erfüllung der selbst gewünschten Funktion (Art. 6 Abs. 1 lit. a und b DSGVO);
- für Daten Dritter in empfangenen E-Mails: auf Grundlage des berechtigten
  Interesses, eingehende Korrespondenz zu sichten und Termine sowie Aufgaben
  daraus zu organisieren (Art. 6 Abs. 1 lit. f DSGVO).

Es findet kein Profiling zu Werbezwecken, kein Verkauf und keine Weitergabe zu
Marketingzwecken statt. Automatisierte Entscheidungen mit rechtlicher Wirkung
(Art. 22 DSGVO) trifft Mailhelp nicht: Jede externe Kalender- oder Aufgabenaktion
erfordert eine ausdrückliche, versionsbezogene Bestätigung durch einen Menschen.

## 5. Empfänger und eingesetzte Dienste

Für die Funktion werden Daten an folgende Dienste übermittelt:

| Dienst | Übermittelte Daten | Zweck | Sitz |
|---|---|---|---|
| E-Mail-Anbieter der eingerichteten Postfächer | Abruf per IMAP, optional gespeicherte Antwortentwürfe | Lesen der E-Mails und Entwurfsablage | abhängig vom Anbieter |
| IServ-Server der Schule (optional) | Anmeldung mit dem Elternkonto und Lesen der Elternbriefe | Abruf von Briefen und Anhängen; in IServ wird nichts bestätigt oder beantwortet | abhängig von der Schule |
| OpenRouter und die tatsächlich gewählten Modellanbieter | Mail- und Anhangsinhalte, Vorschlagsfelder, bestehende Termine zur Duplikatprüfung, Klärungsantworten, optional persönliche Angaben; Fragen an den Hilfschat mit kurzem Verlauf und Dokumentationsausschnitten; nach ausdrücklicher Freigabe begrenzte Auszüge und Korrekturen aus dem Lernbestand (Regellernen) sowie die Mails eines gestarteten Lernlaufs | KI-Auswertung; Modelle und Routen gemäß `prompts.yaml` und `decisions_prompts.yaml` | abhängig vom Anbieter |
| Telegram Messenger, falls aktiviert | Hinweise gemäß Inhaltsprofil; direkte Vorschläge, Rückfragen und Antworten können Mailauszüge enthalten | Bedienung und Bestätigung | gemäß Anbieterangaben |
| Todoist (Doist Inc.) | bestätigte Aufgaben; Lesen des Zielprojekts und der angelegten Aufgabe zur Nachprüfung; Löschen einer eigenen Aufgabe nur auf ausdrücklichen Wunsch innerhalb der Entfernfrist | Aufgabenanlage | USA |
| Google Kalender (Google LLC / Google Ireland Ltd.) | bestätigte Termine, bestätigte Änderungen und Absagen bestehender Termine; Lesen von Terminen im betroffenen Zeitraum und des angelegten Termins zur Nachprüfung; Löschen eines eigenen Termins nur auf ausdrücklichen Wunsch innerhalb der Entfernfrist | Terminanlage, Duplikatprüfung | Irland / USA |
| Microsoft 365 / Outlook / Microsoft To Do, falls gewählt | bestätigte Termine oder Aufgaben und ihre Änderungen; lesender Abgleich und Nachprüfung; Löschen eigener Einträge nur auf ausdrücklichen Wunsch innerhalb der Entfernfrist | Kalender- und Aufgabenfunktionen | abhängig vom Konto und Anbieter |
| CalDAV-Anbieter einschließlich iCloud, falls gewählt | bestätigte Termine oder Aufgaben und ihre Änderungen; lesender Abgleich und Nachprüfung; Löschen eigener Einträge nur auf ausdrücklichen Wunsch innerhalb der Entfernfrist | Kalender- und Aufgabenfunktionen | abhängig vom Anbieter |
| Push-Dienst des Browsers, falls freigegeben | Abonnement-Endpunkt und verschlüsselter inhaltsneutraler Hinweis | Web-Push | abhängig vom Browseranbieter |

Die optionale Weboberfläche (ab Version 1.1) läuft auf dem eigenen PC und ist
standardmäßig ausgeschaltet. Sie ist lokal unter `127.0.0.1` und – falls
eingerichtet – über Tailscale Serve im eigenen Tailnet erreichbar. Tailscale
(Tailscale Inc., USA) vermittelt dabei die verschlüsselte Verbindung zwischen den
eigenen Geräten; die Inhalte werden Ende-zu-Ende verschlüsselt übertragen.
Kopplungscodes können bei aktiviertem Telegram über den Bot angefordert werden;
`mailhelp --pair` zeigt einen lokal autorisierten Code ausschließlich im aufrufenden
Terminal. Hinweise auf neue Geräte werden bei aktiviertem Telegram dorthin gesendet.

Optional kann statt OpenRouter ein lokaler KI-Server (Ollama) im eigenen Netz
genutzt werden. Dann verlassen die Mailinhalte für die KI-Auswertung das eigene Netz
nicht.

Bei Diensten außerhalb der EU erfolgt die Übermittlung auf Grundlage eines
Angemessenheitsbeschlusses (etwa EU-US Data Privacy Framework, soweit der Anbieter
zertifiziert ist) oder der Standardvertragsklauseln des jeweiligen Anbieters. Es
gelten zusätzlich deren eigene Datenschutzbestimmungen.

## 6. Daten aus Google-Konten (Google API Services)

### Zentrale Anmeldung und Postfachzugänge ab 8.1

Bei gehosteter Anmeldung verwaltet der getrennte Inboxstride-Anmeldedienst
Refresh-Tokens verschlüsselt. Der Schlüssel liegt außerhalb des Zustandsverzeichnisses;
Sicherung und Wiederherstellung benötigen beide getrennt gesicherten Bestandteile.
Die jeweilige Mailhelp-Instanz erhält über gegenseitig authentifiziertes TLS nur
zweckgebundene, kurzlebige Access-Tokens. Kalender- und Postfachfreigaben werden
getrennt erteilt und getrennt verwaltet. Der Anmeldedienst analysiert keine Mailinhalte.

Gmail-IMAP benötigt den weitreichenden Scope `https://mail.google.com/`.
Dieser Zugang bleibt standardmäßig deaktiviert. Vor seiner produktiven Freischaltung
müssen Anbieterfreigaben, öffentliche Anwendungsinformationen und die in Abschnitt 5
beschriebene Weitergabe ausgewählter Mailinhalte an den konfigurierten KI-Dienst
geprüft und aufeinander abgestimmt werden. Die Implementierung oder ein synthetischer
Test belegt keine Google-Freigabe. Microsoft-Postfachzugang verwendet separat
`https://outlook.office.com/IMAP.AccessAsUser.All` und `offline_access` und benötigt
eine eigene App-Registrierung und die erforderliche Zustimmung.

### Google-Kalender

Mailhelp greift mit OAuth und den folgenden Berechtigungen auf Google Kalender zu:

- `https://www.googleapis.com/auth/calendar.events`: Lesen von Terminen im Zeitraum
  eines Terminvorschlags (Duplikatprüfung), Anlegen bestätigter Termine, bestätigte
  Änderungen und Absagen bestehender Termine, frisches Lesen eines angelegten Termins zur
  Nachprüfung und – nur auf ausdrücklichen Wunsch innerhalb der Entfernfrist – Löschen eines
  von Mailhelp angelegten Termins;
- `https://www.googleapis.com/auth/calendar.calendars.readonly`: Prüfen, ob der
  konfigurierte Zielkalender erreichbar ist.
- Im zentralen Anmeldeablauf zusätzlich
  `https://www.googleapis.com/auth/calendar.calendarlist.readonly`: zugängliche
  Kalender zur ausdrücklichen Auswahl des Zielkalenders anzeigen.

Die Nutzung und Übertragung von Informationen, die Mailhelp von Google-APIs erhält,
hält die [Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy)
einschließlich der Anforderungen an die eingeschränkte Nutzung („Limited Use“) ein.
Insbesondere gilt:

- Kalenderdaten werden ausschließlich verwendet, um die für die Nutzerin oder den
  Nutzer sichtbare Funktion bereitzustellen: bestätigte Termine anlegen, ändern oder
  absagen, ihre Anlage nachprüfen und Duplikate vermeiden.
- Zur Duplikatprüfung werden Titel, Beschreibung, Ort und Zeitraum bestehender,
  zeitlich überlappender Termine zusammen mit dem Terminvorschlag an das
  KI-Modell übermittelt (siehe Abschnitt 5). Ein aktivierter Tagesüberblick kann
  gelesene Terminangaben anzeigen und bei ausdrücklich gewähltem Telegram-
  Inhaltsprofil `summary` auch dorthin übermitteln. Web-Push bleibt inhaltsneutral.
- Kalenderdaten werden nicht verkauft, nicht für Werbung genutzt und nicht zum
  Training allgemeiner KI-Modelle verwendet oder dafür weitergegeben.
- Menschen lesen diese Daten nur, wenn die Nutzerin oder der Nutzer zustimmt, es
  für Sicherheitszwecke oder zur Einhaltung geltenden Rechts erforderlich ist, oder
  bei ausschließlich interner Verarbeitung in den lokalen Protokollen zur Fehlersuche.

Der Zugriff kann jederzeit unter
[myaccount.google.com/permissions](https://myaccount.google.com/permissions)
widerrufen werden. Danach kann Mailhelp keine Termine mehr lesen oder anlegen.

## 7. Speicherung und Löschung

Mailhelp speichert Daten ausschließlich lokal auf dem Rechner oder Server der
verantwortlichen Person, als lesbare JSON-Dateien und Protokolle.

| Daten | Speicherdauer (ausgeliefertes Beispiel; für die eigene Instanz anpassen) |
|---|---|
| Vollständiger Mailinhalt in abgeschlossenen Vorgängen | 30 Tage, danach automatisch entfernt |
| Zwischenergebnisse der KI-Auswertung (Relevanz, Zusammenfassung, Diagnosen) | beim nächsten Lauf entfernt |
| Vorschläge, Entscheidungen und Schreibnachweise (Duplikatschutz) | solange für den Duplikatschutz erforderlich |
| Anwendungsprotokoll | 30 Tage, rotierend |
| Protokoll der KI-Anfragen und -Antworten, einschließlich Mailinhalten | 30 Tage, rotierend |
| Protokoll der Telegram-Nachrichten, einschließlich Inhalten | 30 Tage, rotierend |
| Gelernte Filter | bis zur manuellen Änderung |
| Kompakte Analyse einer Mail (Relevanz, Begründung, Themen, Zusammenfassung; ab 1.2) | `retention.analysis_days` nach Abschluss; ohne Angabe wie die KI-Zwischenergebnisse |
| Lernbestand manueller Entscheidungen mit Mailinhalt, KI-Ergebnissen und Vorschlägen (ab 3.5.3, `learning/decisions.jsonl`; vollständige KI-Anfragen nur mit `learning.decision_llm_content`) | `retention.decision_learning_days`, Standard unbegrenzt; `disabled` zeichnet nichts auf |
| Entscheidungsverlauf und ältere Vorschlagsversionen (ab 1.2) | `retention.history_days`, Standard 90 Tage nach Abschluss; Sicherheitsreferenzen gegen Doppelanlagen bleiben |
| Inhaltsfreie Messwerte von KI-Aufrufen (Dauer, Modell, Schritt, Kosten; ab 1.2) | `metrics.retention_days`, Standard 90 Tage; danach nur Tagessummen ohne Mailbezug |
| Journal von Einstellungs- und Themenänderungen über das Web (ab 1.2) | bis `mailhelp --clear` |
| Gekoppelte Geräte der Weboberfläche | bis zum Ablauf (Standard 30 Tage), zum Abmelden oder Widerruf (auch per `/web_abmelden`) |
| Kopplungscodes | 10 Minuten |
| Web-Aktionen und deren Ergebnis | ein Tag nach Abschluss |
| Vergleichs- und Testberichte, sofern manuell erzeugt (enthalten vollständige Mails) | bis zur manuellen Löschung |
| Volltexte und Belege abgeschlossener Tätigkeitsberichte | `retention.activity_report_days`, im Beispiel 365 Tage; kompakte Termin-, Absender- und Betreffangaben bleiben |
| Benachrichtigungsqueue und Zustellhistorie | ausstehende Meldungen bis zur Verarbeitung; Historie nach `notifications.delivery.history_days`, im Beispiel 30 Tage, ohne Nachrichtenvolltext |
| Web-Push-Abonnements | bis zum Widerruf oder zur Entfernung ungültiger Abonnements |
| Gespräche im Hilfschat | an die Websitzung gebunden; nach Abmeldung, Widerruf des Geräts oder 24 Stunden ohne Nutzung gelöscht |
| Nachweise geschriebener Einträge | wie Vorschläge und Entscheidungen, solange für den Duplikatschutz erforderlich |

Vollständige KI-Inhalte werden nur bei explizit gesetzten `logging.llm.include_requests`
und `logging.llm.include_responses` protokolliert. Die ausgelieferte Beispielkonfiguration
setzt beide Werte auf `true`; für einen Betrieb ohne diese Inhalte auf `false` setzen.
Logs können außerdem durch Größenrotation früher entfernt werden. Postfachbezogene
Volltextfristen dürfen die globale Frist verkürzen.

Offene Vorgänge (etwa eine unbeantwortete Rückfrage) werden erst nach ihrem Abschluss
bereinigt. Mit `mailhelp --clear` lassen sich alle Zustandsdaten und Protokolle
sofort löschen. In Todoist und Google Kalender angelegte Einträge verbleiben dort,
bis sie dort gelöscht werden.

## 8. Sicherheit

Einrichtung und Benachrichtigungssteuerung (seit 3.0): Diagnoseberichte enthalten nur
Version, Betriebssystemklasse, Komponentenstatus, Prüfdauer und sichere Fehlercodes. Queue und
Zustelllogs enthalten Referenzen statt Nachrichtentexten. Telegram-Inhaltsmeldungen werden im
Profil bewusst gewählt; Web-Push bleibt neutral. Erstkopplung ohne Telegram erfolgt durch
`mailhelp --pair` am lokalen Host, ohne Codeausgabe in Dienstlogs. Ausstehende Meldungen prüfen
Gerätesitzung und Abonnement erneut. Details: [Betriebsanleitung 3.0](docs/archiv/Release-3.0.md).

Zugangsdaten lassen sich seit 3.3.11 über die angemeldete Weboberfläche in `.env` speichern. Die
Weboberfläche gibt gespeicherte Werte nie aus, auch nicht maskiert; Protokolle enthalten nur den
Namen des geänderten Eintrags. Wer die Weboberfläche nutzen kann, kann Zugangsdaten ersetzen –
gekoppelte Geräte sollten daher geschützt und nicht mehr genutzte Sitzungen abgemeldet werden.

- Zugangsdaten (Postfach, OpenRouter, Telegram, Todoist, Google) liegen nur in
  Umgebungsvariablen beziehungsweise einer lokalen `.env`-Datei, nicht im Code, und
  werden nicht protokolliert.
- Cloud-Adapter verwenden TLS. IMAP sollte mit `ssl` oder `starttls` betrieben werden;
  eine ausdrücklich konfigurierte `plain`-Verbindung ist unverschlüsselt. Ein lokaler
  Ollama-Server kann über HTTP angesprochen werden und gehört in ein vertrauenswürdiges Netz.
- Nur ein konfiguriertes Telegram-Konto in einem konfigurierten Chat darf den Bot
  bedienen; andere Eingaben werden abgewiesen.
- Die Weboberfläche ist nur nach Kopplung per einmaligem lokal oder über Telegram
  angefordertem Code nutzbar.
  Sitzungs-Cookies sind `HttpOnly` und `SameSite=Strict`, über Tailscale zusätzlich
  `Secure`; schreibende Anfragen benötigen ein CSRF-Token, fremde Host-Namen werden
  abgewiesen. Mailinhalte werden ohne aktive Inhalte dargestellt; die installierbare
  App speichert offline nur ihre Hülle, keine Mails oder Vorschläge.
- Inhalte aus E-Mails und KI-Ausgaben werden als nicht vertrauenswürdig behandelt.
  Schreibzugriffe erfolgen nur nach ausdrücklicher, versionsbezogener Bestätigung;
  doppelte Anlagen werden verhindert.

## 9. Rechte betroffener Personen

Betroffene Personen haben das Recht auf Auskunft (Art. 15 DSGVO), Berichtigung
(Art. 16), Löschung (Art. 17), Einschränkung der Verarbeitung (Art. 18),
Datenübertragbarkeit (Art. 20) und Widerspruch gegen eine Verarbeitung auf Grundlage
berechtigter Interessen (Art. 21). Eine erteilte Einwilligung kann jederzeit mit
Wirkung für die Zukunft widerrufen werden. Anfragen bitte an die in Abschnitt 2
genannte Kontaktadresse.

Außerdem besteht ein Beschwerderecht bei einer Datenschutz-Aufsichtsbehörde,
insbesondere am Wohnort oder am Ort des mutmaßlichen Verstoßes.

## 10. Änderungen

Diese Erklärung wird angepasst, wenn sich Funktionen, eingesetzte Dienste oder
Aufbewahrungsfristen ändern. Maßgeblich ist die jeweils im Repository
veröffentlichte Fassung mit dem oben angegebenen Stand.
