<!--
Hinweise für Betreibende (vor Veröffentlichung entfernen):
- Platzhalter in [eckigen Klammern] ersetzen.
- Für eine Google-OAuth-Prüfung muss diese Seite öffentlich erreichbar sein.
- Dieser Text ist eine sorgfältig erstellte Vorlage, keine Rechtsberatung.
-->

# Nutzungsbedingungen für Mailhelp

Stand: 14. Oktober 2026 · technische Beschreibung für Mailhelp 3.3.1

## 1. Gegenstand

Mailhelp ist eine selbst betriebene Software. Sie liest E-Mails aus bis zu zehn
eigenen Postfächern, wertet sie mit KI-Modellen aus und schlägt Aufgaben und Termine
vor. Die Bedienung erfolgt über einen optionalen Telegram-Bot oder gekoppelte,
authentifizierte Webgeräte. Kalender- und Aufgabenaktionen benötigen eine
ausdrückliche, versionsbezogene Bestätigung. Zieldienste können Google Kalender,
Todoist, Microsoft-Dienste oder CalDAV sein.

Diese Bedingungen regeln die Nutzung der von [Vor- und Nachname] („Betreiber“)
betriebenen Mailhelp-Instanz einschließlich der zugehörigen Google-OAuth-Anwendung
und des Telegram-Bots. Für den Quellcode gilt unabhängig davon die MIT-Lizenz in
der Datei `LICENSE`.

## 2. Berechtigte Nutzung

Die Instanz ist ausschließlich für die private Nutzung durch den Betreiber bestimmt.
Nur das in der Konfiguration hinterlegte Telegram-Konto darf den Bot bedienen.
Die zugehörige Person darf außerdem über lokal oder per Telegram gekoppelte Webgeräte
Vorschläge bearbeiten und ausdrücklich bestätigen.
Ein öffentlicher Zugang, eine Registrierung oder eine Nutzung durch Dritte ist nicht
vorgesehen.

Wer Mailhelp mit eigenen Postfächern, Kalender-, Aufgaben-, KI- oder Telegram-Diensten
verbindet, erklärt, zur Nutzung dieser Konten berechtigt zu sein.

## 3. Funktionsweise und Grenzen

- Zusammenfassungen, Relevanzeinschätzungen sowie Aufgaben- und Terminvorschläge
  werden von KI-Modellen erzeugt. Sie können unvollständig, ungenau oder falsch sein,
  etwa bei Datum, Uhrzeit, Ort oder Zuständigkeit.
- Jeder Vorschlag ist vor der Bestätigung zu prüfen. Mit der versionsbezogenen
  Bestätigung in Telegram oder der authentifizierten Weboberfläche
  übernimmt die bestätigende Person die Verantwortung für den angelegten Eintrag.
- Der normale Mailabruf verändert weder Nachrichten noch Lesestatus. Mailhelp
  versendet keine E-Mails. Optional können KI-Antwortentwürfe nach gesonderter
  Bestätigung im IMAP-Entwurfsordner des Ursprungspostfachs gespeichert werden.
- Als irrelevant eingestufte E-Mails werden nicht weiter ausgewertet. Mailhelp
  ersetzt nicht das eigene Lesen wichtiger Post; insbesondere Fristen sind
  eigenverantwortlich zu überwachen.

## 4. Pflichten bei der Nutzung

- Zugangsdaten und Tokens sind geheim zu halten und nur in der lokalen
  Konfiguration (`.env`) abzulegen.
- Mailhelp darf nur im Einklang mit geltendem Recht genutzt werden, insbesondere
  mit dem Datenschutzrecht gegenüber den Absenderinnen und Absendern von E-Mails.
- Die Bedingungen der angebundenen Dienste sind einzuhalten, insbesondere die von
  Google (einschließlich der Google API Services User Data Policy), Telegram,
  Todoist, Microsoft, OpenRouter sowie der gewählten CalDAV- und E-Mail-Anbieter.
- Der Bot darf nicht genutzt werden, um Dienste zu überlasten, Schutzmaßnahmen zu
  umgehen oder unbefugt auf fremde Konten zuzugreifen.

## 5. Datenschutz

Wie Daten verarbeitet, an welche Dienste sie übermittelt und wie lange sie
gespeichert werden, beschreibt die [Datenschutzerklärung](DATENSCHUTZ.md).

## 6. Dienste Dritter und Kosten

Mailhelp nutzt die konfigurierten externen Dienste (E-Mail-Anbieter, OpenRouter
und Modellanbieter sowie optional Telegram, Kalender-, Aufgaben- und Push-Dienste).
Für deren Verfügbarkeit, Inhalte und
Datenverarbeitung ist der jeweilige Anbieter verantwortlich. Kosten für
kostenpflichtige Schnittstellen, insbesondere für KI-Aufrufe, trägt der Betreiber.

## 7. Verfügbarkeit und Änderungen

Ein Anspruch auf ständige Verfügbarkeit, bestimmte Funktionen oder Fehlerfreiheit
besteht nicht. Funktionen können jederzeit geändert, eingeschränkt oder eingestellt
werden. Ein fehlerhafter Zugang verhindert Aktionen für das betroffene Postfach
oder Zielprofil; unabhängige Profile können weiterarbeiten. Mailhelp setzt
Schreibaktionen nicht ungeprüft fort.

## 8. Haftung

Die Software wird gemäß MIT-Lizenz „wie besehen“ und unentgeltlich bereitgestellt.
Für Schäden aus fehlerhaften Zusammenfassungen, Vorschlägen, verpassten oder doppelt
angelegten Einträgen haftet der Betreiber nur bei Vorsatz und grober Fahrlässigkeit.
Die Haftung für Schäden aus der Verletzung des Lebens, des Körpers oder der
Gesundheit sowie nach zwingenden gesetzlichen Vorschriften bleibt unberührt.

## 9. Beendigung

Die Nutzung kann jederzeit beendet werden:

- Mailhelp stoppen und mit `mailhelp --clear` alle lokalen Zustandsdaten und
  Protokolle löschen;
- den Google-Zugriff unter
  [myaccount.google.com/permissions](https://myaccount.google.com/permissions)
  widerrufen;
- Todoist- und Telegram-Bot-Tokens beim jeweiligen Anbieter widerrufen.

Bereits im gewählten Kalender oder in der Aufgabenliste angelegte Einträge sowie
gespeicherte IMAP-Entwürfe bleiben dort bestehen.

## 10. Schlussbestimmungen

Es gilt das Recht der Bundesrepublik Deutschland. Sollte eine Bestimmung unwirksam
sein, bleibt die Wirksamkeit der übrigen Bestimmungen unberührt. Änderungen dieser
Bedingungen werden im Repository mit neuem Stand veröffentlicht.

Kontakt: [Kontakt-E-Mail-Adresse]
