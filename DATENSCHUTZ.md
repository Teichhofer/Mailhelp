<!--
Hinweise für Betreibende (vor Veröffentlichung entfernen):
- Platzhalter in [eckigen Klammern] ersetzen (Name, Anschrift, Kontakt).
- Die Angaben unten entsprechen der Konfiguration im Repository (Stand 10.10.2026).
  Bei abweichender Konfiguration (andere Modelle, Anbieter, Aufbewahrungsfristen,
  Logging) diese Erklärung anpassen.
- Für eine Google-OAuth-Prüfung muss diese Seite öffentlich erreichbar sein und zur
  im OAuth-Zustimmungsbildschirm eingetragenen Domain passen.
- Dieser Text ist eine sorgfältig erstellte Vorlage, keine Rechtsberatung.
-->

# Datenschutzerklärung für Mailhelp

Stand: 10. Oktober 2026

## 1. Worum es geht

Mailhelp ist eine selbst betriebene Software. Sie liest E-Mails aus einem Postfach,
lässt sie mit KI-Modellen auswerten und schlägt daraus Aufgaben (Todoist) und Termine
(Google Kalender) vor. Die Vorschläge werden über einen Telegram-Bot zur Bestätigung
vorgelegt. Mailhelp legt **nichts** in Todoist oder Google Kalender an, solange die
berechtigte Person den konkreten Vorschlag nicht ausdrücklich in Telegram bestätigt hat.

Mailhelp ist kein öffentlicher Dienst. Eine Instanz wird von einer Person für ihr
eigenes Postfach betrieben und von genau einem berechtigten Telegram-Konto bedient.
Diese Erklärung beschreibt die Instanz der unten genannten verantwortlichen Person.

## 2. Verantwortliche Person

[Vor- und Nachname]
[Straße und Hausnummer]
[PLZ Ort]
E-Mail: [Kontakt-E-Mail-Adresse]

## 3. Welche Daten verarbeitet werden

| Daten | Herkunft | Zweck |
|---|---|---|
| E-Mails: Absender, Empfänger, Betreff, Datum, Nachrichten-IDs und Textinhalt (Anhänge werden nicht ausgewertet) | eigenes Postfach per IMAP | Relevanzprüfung, Zusammenfassung, Erkennung von Aufgaben und Terminen |
| Telegram-Nachrichten und Schaltflächen-Eingaben des berechtigten Kontos | Telegram | Bestätigung, Änderung oder Verwerfen von Vorschlägen; Rückfragen |
| Aufgaben- und Terminvorschläge mit Belegstelle aus der Mail | von Mailhelp erzeugt | Vorlage zur Bestätigung, Anlage nach Bestätigung |
| Bestehende Termine im Zeitraum eines Terminvorschlags: Titel, Beschreibung, Ort, Beginn, Ende, Link | Google Kalender | Erkennen von Duplikaten vor dem Anlegen |
| Aufgaben im konfigurierten Todoist-Projekt | Todoist | Erkennen bereits angelegter Aufgaben vor dem Anlegen |
| Gelernte Absender- und Themenfilter | aus bestätigten Entscheidungen | künftige Relevanzprüfung |
| Technische Protokolle (Zeitpunkte, Status, Fehler) | Mailhelp | Betrieb und Fehlersuche |

Von Absenderinnen und Absendern verarbeitet Mailhelp nur, was in den empfangenen
E-Mails steht. Mailhelp versendet keine E-Mails und verändert das Postfach nicht.

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
(Art. 22 DSGVO) trifft Mailhelp nicht: Jede Aktion in Todoist oder Google Kalender
erfordert eine ausdrückliche, versionsbezogene Bestätigung durch einen Menschen.

## 5. Empfänger und eingesetzte Dienste

Für die Funktion werden Daten an folgende Dienste übermittelt:

| Dienst | Übermittelte Daten | Zweck | Sitz |
|---|---|---|---|
| E-Mail-Anbieter des Postfachs (konfiguriert: WEB.DE, 1&1 Mail & Media GmbH) | Abruf per IMAP | Lesen der E-Mails | Deutschland |
| OpenRouter, Inc. und die dort gewählten Modellanbieter (konfiguriert: DeepSeek-Modell über Together AI oder Parasail; Entscheidungsmodell Jev von TypeSafe) | Mailinhalt, Vorschläge, bestehende Termine zur Duplikatprüfung, Antworten aus Telegram | KI-Auswertung | USA |
| Telegram Messenger | Zusammenfassungen, Vorschläge mit Mailauszügen, Rückfragen | Bedienung und Bestätigung | Vereinigte Arabische Emirate / Vereinigtes Königreich |
| Todoist (Doist Inc.) | bestätigte Aufgaben; Lesen des Zielprojekts | Aufgabenanlage | USA |
| Google Kalender (Google LLC / Google Ireland Ltd.) | bestätigte Termine; Lesen von Terminen im betroffenen Zeitraum | Terminanlage, Duplikatprüfung | Irland / USA |

Optional kann statt OpenRouter ein lokaler KI-Server (Ollama) im eigenen Netz
genutzt werden. Dann verlassen die Mailinhalte für die KI-Auswertung das eigene Netz
nicht.

Bei Diensten außerhalb der EU erfolgt die Übermittlung auf Grundlage eines
Angemessenheitsbeschlusses (etwa EU-US Data Privacy Framework, soweit der Anbieter
zertifiziert ist) oder der Standardvertragsklauseln des jeweiligen Anbieters. Es
gelten zusätzlich deren eigene Datenschutzbestimmungen.

## 6. Daten aus Google-Konten (Google API Services)

Mailhelp greift mit OAuth und den folgenden Berechtigungen auf Google Kalender zu:

- `https://www.googleapis.com/auth/calendar.events`: Lesen von Terminen im Zeitraum
  eines Terminvorschlags (Duplikatprüfung) und Anlegen bestätigter Termine;
- `https://www.googleapis.com/auth/calendar.calendars.readonly`: Prüfen, ob der
  konfigurierte Zielkalender erreichbar ist.

Die Nutzung und Übertragung von Informationen, die Mailhelp von Google-APIs erhält,
hält die [Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy)
einschließlich der Anforderungen an die eingeschränkte Nutzung („Limited Use“) ein.
Insbesondere gilt:

- Kalenderdaten werden ausschließlich verwendet, um die für die Nutzerin oder den
  Nutzer sichtbare Funktion bereitzustellen: bestätigte Termine anlegen und
  Duplikate vermeiden.
- Zur Duplikatprüfung werden Titel, Beschreibung, Ort und Zeitraum bestehender,
  zeitlich überlappender Termine zusammen mit dem Terminvorschlag an das
  KI-Modell übermittelt (siehe Abschnitt 5). Andere Übermittlungen finden nicht statt.
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

| Daten | Speicherdauer (aktuelle Konfiguration) |
|---|---|
| Vollständiger Mailinhalt in abgeschlossenen Vorgängen | 30 Tage, danach automatisch entfernt |
| Zwischenergebnisse der KI-Auswertung (Relevanz, Zusammenfassung, Diagnosen) | beim nächsten Lauf entfernt |
| Vorschläge, Entscheidungen und Schreibnachweise (Duplikatschutz) | solange für den Duplikatschutz erforderlich |
| Anwendungsprotokoll | 30 Tage, rotierend |
| Protokoll der KI-Anfragen und -Antworten, einschließlich Mailinhalten | 30 Tage, rotierend |
| Protokoll der Telegram-Nachrichten, einschließlich Inhalten | 30 Tage, rotierend |
| Gelernte Filter | bis zur manuellen Änderung |
| Vergleichs- und Testberichte, sofern manuell erzeugt (enthalten vollständige Mails) | bis zur manuellen Löschung |

Offene Vorgänge (etwa eine unbeantwortete Rückfrage) werden erst nach ihrem Abschluss
bereinigt. Mit `mailhelp --clear` lassen sich alle Zustandsdaten und Protokolle
sofort löschen. In Todoist und Google Kalender angelegte Einträge verbleiben dort,
bis sie dort gelöscht werden.

## 8. Sicherheit

- Zugangsdaten (Postfach, OpenRouter, Telegram, Todoist, Google) liegen nur in
  Umgebungsvariablen beziehungsweise einer lokalen `.env`-Datei, nicht im Code, und
  werden nicht protokolliert.
- Alle Verbindungen zu externen Diensten sind verschlüsselt (TLS).
- Nur ein konfiguriertes Telegram-Konto in einem konfigurierten Chat darf den Bot
  bedienen; andere Eingaben werden abgewiesen.
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
