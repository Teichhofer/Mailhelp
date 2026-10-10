<!--
Hinweise für Betreibende (vor Veröffentlichung entfernen):
- Platzhalter in [eckigen Klammern] ersetzen.
- Für eine Google-OAuth-Prüfung muss diese Seite öffentlich erreichbar sein.
- Dieser Text ist eine sorgfältig erstellte Vorlage, keine Rechtsberatung.
-->

# Nutzungsbedingungen für Mailhelp

Stand: 10. Oktober 2026

## 1. Gegenstand

Mailhelp ist eine selbst betriebene Software. Sie liest E-Mails aus einem Postfach,
wertet sie mit KI-Modellen aus und schlägt über einen Telegram-Bot Aufgaben
(Todoist) und Termine (Google Kalender) vor, die erst nach ausdrücklicher Bestätigung
angelegt werden.

Diese Bedingungen regeln die Nutzung der von [Vor- und Nachname] („Betreiber“)
betriebenen Mailhelp-Instanz einschließlich der zugehörigen Google-OAuth-Anwendung
und des Telegram-Bots. Für den Quellcode gilt unabhängig davon die MIT-Lizenz in
der Datei `LICENSE`.

## 2. Berechtigte Nutzung

Die Instanz ist ausschließlich für die private Nutzung durch den Betreiber bestimmt.
Nur das in der Konfiguration hinterlegte Telegram-Konto darf den Bot bedienen.
Ein öffentlicher Zugang, eine Registrierung oder eine Nutzung durch Dritte ist nicht
vorgesehen.

Wer Mailhelp mit dem eigenen Konto verbindet (Postfach, Google Kalender, Todoist,
Telegram), erklärt, zur Nutzung dieser Konten berechtigt zu sein.

## 3. Funktionsweise und Grenzen

- Zusammenfassungen, Relevanzeinschätzungen sowie Aufgaben- und Terminvorschläge
  werden von KI-Modellen erzeugt. Sie können unvollständig, ungenau oder falsch sein,
  etwa bei Datum, Uhrzeit, Ort oder Zuständigkeit.
- Jeder Vorschlag ist vor der Bestätigung zu prüfen. Mit der Bestätigung in Telegram
  übernimmt die bestätigende Person die Verantwortung für den angelegten Eintrag.
- Mailhelp legt nur bestätigte Vorschläge an, versendet keine E-Mails und verändert
  das Postfach nicht.
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
  Todoist, OpenRouter und des E-Mail-Anbieters.
- Der Bot darf nicht genutzt werden, um Dienste zu überlasten, Schutzmaßnahmen zu
  umgehen oder unbefugt auf fremde Konten zuzugreifen.

## 5. Datenschutz

Wie Daten verarbeitet, an welche Dienste sie übermittelt und wie lange sie
gespeichert werden, beschreibt die [Datenschutzerklärung](DATENSCHUTZ.md).

## 6. Dienste Dritter und Kosten

Mailhelp nutzt externe Dienste (E-Mail-Anbieter, OpenRouter und Modellanbieter,
Telegram, Todoist, Google Kalender). Für deren Verfügbarkeit, Inhalte und
Datenverarbeitung ist der jeweilige Anbieter verantwortlich. Kosten für
kostenpflichtige Schnittstellen, insbesondere für KI-Aufrufe, trägt der Betreiber.

## 7. Verfügbarkeit und Änderungen

Ein Anspruch auf ständige Verfügbarkeit, bestimmte Funktionen oder Fehlerfreiheit
besteht nicht. Funktionen können jederzeit geändert, eingeschränkt oder eingestellt
werden. Mailhelp stoppt bewusst, wenn ein Zugang ungültig wird (etwa eine abgelaufene
Google-Anmeldung), statt Aktionen ungeprüft fortzusetzen.

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

Bereits in Todoist oder Google Kalender angelegte Einträge bleiben dort bestehen.

## 10. Schlussbestimmungen

Es gilt das Recht der Bundesrepublik Deutschland. Sollte eine Bestimmung unwirksam
sein, bleibt die Wirksamkeit der übrigen Bestimmungen unberührt. Änderungen dieser
Bedingungen werden im Repository mit neuem Stand veröffentlicht.

Kontakt: [Kontakt-E-Mail-Adresse]
