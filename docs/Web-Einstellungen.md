# Einstellungen der Weboberfläche

Stand: 15. Oktober 2026, Anwendungsversion 3.4.1.

Die globalen Einstellungen bieten eine Bereichsübersicht mit direkten Sprunglinks, beispielsweise
zu Antworten, Zielen, Aufbewahrung und Protokollierung. Die verwendeten KI-Modelle stehen in einer
aufklappbaren, nur lesenden Übersicht. Auf großen Bildschirmen bleiben die Bereichslinks neben den
Werten erreichbar; auf dem Handy stehen sie oberhalb der Einstellungsgruppen.

Einrichtungsentwürfe unter `/einrichtung` und das Versandprofil unter
`/einstellungen/benachrichtigungen` bearbeiten ebenfalls `config.yaml`.
Speichern erhält zunächst den Entwurf. Erst die gezeigte, versionsbezogene Übernahme aktiviert
Änderungen; Verbindungs- und Zieländerungen benötigen eine aktuelle erfolgreiche Diagnose.
Feldnamen, Grenzwerte, Kanalwahl und Sofort-/Neustartwirkung:
[Betriebsanleitung 3.0](Release-3.0.md#konfigurationsvertrag).

Jedes Info-Symbol erklärt, was die Einstellung verändert und welche Folgen andere Werte haben. Mit der Maus darüberfahren, per Tab fokussieren oder auf dem Handy antippen. Escape blendet die Blase aus. Das Lesen verändert keine Einstellung.

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

## Mailabruf und Betrieb

| Einstellung / Schlüssel | Wirkung und Werte | Übernahme |
| --- | --- | --- |
| Abrufintervall (Sekunden) (`poll_interval_seconds`) | Abstand zwischen Mailabrufen: 5–86400 Sekunden. 60 prüft etwa jede Minute, 300 etwa alle fünf Minuten. Kleinere Werte erkennen neue Mails früher, größere entlasten den Mailserver. Ein laufender Durchlauf kann den nächsten Abruf verzögern. | Im laufenden Betrieb |
| Trockenlauf (`test_mode`) | ja (true) aktiviert den Trockenlauf: bestätigte Kalender- und Todoist-Aktionen werden simuliert; Testdaten werden getrennt gespeichert. nein (false) aktiviert echte Schreibaktionen nach ausdrücklicher Bestätigung. Der Trockenlauf verhindert nicht sämtliche Netzwerkzugriffe, etwa Mailabruf und KI-Aufrufe. | Nach Neustart |
| Zeitzone (`timezone`) | Zeitzone für lokale Datums- und Zeitangaben, z. B. Europe/Berlin mit automatischer Sommerzeit oder UTC ohne Zeitumstellung. Verwende einen gültigen IANA-Zeitzonennamen. Eine andere Zone verändert die Interpretation lokaler Terminzeiten und deren Anzeige. | Nach Neustart |
| Mails je Abrufdurchlauf (`imap.batch_size`) | Höchstens so viele neue Mails nimmt ein Abrufdurchlauf über alle Postfächer auf: 1–1000; Standard 25. Größere Werte arbeiten Rückstände schneller ab, verlängern aber einen einzelnen Durchlauf; kleinere verteilen die Arbeit auf mehr Durchläufe. --max-mails ersetzt den Wert für einen einzelnen Lauf. | Nach Neustart |
| Neueste Mails zuerst (alle Postfächer) (`imap.global_newest_first`) | ja (true) wählt je Durchlauf die neuesten Mails über alle Postfächer und Ordner nach Empfangszeit. nein (false) arbeitet Postfach für Postfach und Ordner für Ordner in der konfigurierten Reihenfolge. Die Einstellung bestimmt nur die Reihenfolge, nicht welche Mails verarbeitet werden. | Nach Neustart |

## Antworten

| Einstellung / Schlüssel | Wirkung und Werte | Übernahme |
| --- | --- | --- |
| Persönliche Angaben für Antworten (`personal_info`) | Bis zu 2000 Zeichen, z. B. Name, Rolle, Signatur oder gewünschte Anrede. Diese Angaben erhält das KI-Modell beim Erstellen eines Antwort-Entwurfs. Leer bedeutet keine persönlichen Zusatzangaben. Mehr Kontext kann Ton und Inhalt des Entwurfs verändern; die Angaben werden nicht für die Mailanalyse verwendet. | Im laufenden Betrieb |
| Antwortentwürfe anbieten (`smart_reply`) | ja (true) bietet in der Weboberfläche KI-Antwortentwürfe an; sie werden nur nach ausdrücklichem Speichern im Entwurfsordner des Postfachs abgelegt, Mailhelp versendet nie selbst. nein (false) blendet die Funktion aus. Postfächer können den Wert einzeln überschreiben; benötigt den Schritt draft_reply in prompts.yaml. | Nach Neustart |

## Ziele

| Einstellung / Schlüssel | Wirkung und Werte | Übernahme |
| --- | --- | --- |
| Aufgabendienst (`targets.task_provider`) | Dienst für neue Aufgabenvorschläge: todoist, microsoft_todo (Microsoft To Do), caldav (Aufgabenliste mit VTODO, z. B. Nextcloud Tasks) oder apple_reminders (iCloud-Erinnerungen über CalDAV; auf die neuen iCloud-Erinnerungen aktualisierte Listen sind dort nicht erreichbar). Der Wechsel wirkt nach einem Neustart. Zuerst das passende Ziel eintragen, dann den Dienst wechseln. | Nach Neustart |
| CalDAV-Aufgabenliste (Adresse) (`targets.caldav_task_url`) | Vollständige https-Adresse der CalDAV-Aufgabenliste (VTODO), z. B. https://cloud.example.org/remote.php/dav/calendars/anna/tasks/. Bei Apple Erinnerungen eine Adresse unter https://caldav.icloud.com. Bestehende Einträge werden nicht verschoben. Die Anlage erfordert weiterhin deine ausdrückliche Bestätigung. | Nach Neustart |
| CalDAV-Kalender (Adresse) (`targets.caldav_calendar_url`) | Vollständige https-Adresse der CalDAV-Kalendersammlung, z. B. https://cloud.example.org/remote.php/dav/calendars/anna/personal/. Nur bei Kalenderdienst caldav benötigt; Anmeldung mit CALDAV_USERNAME und App-Passwort CALDAV_PASSWORD. Bestehende Einträge werden nicht verschoben. Die Anlage erfordert weiterhin deine ausdrückliche Bestätigung. | Nach Neustart |
| Google-Kalender (`targets.google_calendar`) | ID des Zielkalenders für neue Terminvorschläge. primary bezeichnet den Hauptkalender; eine konkrete Kalender-ID wählt einen anderen zugänglichen Kalender. Bestehende Termine werden nicht verschoben. Nicht leer, höchstens 500 Zeichen. Die Anlage erfordert weiterhin deine ausdrückliche Bestätigung. | Nach Neustart |
| Kalenderdienst (`targets.calendar_provider`) | Dienst für neue Terminvorschläge: google (Google Kalender), caldav (z. B. Nextcloud, iCloud, mailbox.org) oder outlook (Outlook / Microsoft 365). Der Wechsel wirkt nach einem Neustart; bereits bestätigte Vorschläge für das bisherige Ziel werden nicht in das neue geschrieben. Zuerst das passende Ziel eintragen, dann den Dienst wechseln. Zugangsdaten stehen in der .env-Datei. | Nach Neustart |
| Microsoft-Mandant (`targets.microsoft_tenant`) | Microsoft-Mandant für die Anmeldung: common (private und geschäftliche Konten), consumers, organizations oder die Mandanten-ID. Gilt für Outlook-Kalender und Microsoft To Do. | Nach Neustart |
| Microsoft-To-Do-Liste (`targets.microsoft_todo_list`) | ID der Microsoft-To-Do-Liste oder default für die Standardliste „Aufgaben“. Nur bei Aufgabendienst microsoft_todo benötigt. Bestehende Einträge werden nicht verschoben. Die Anlage erfordert weiterhin deine ausdrückliche Bestätigung. | Nach Neustart |
| Outlook-Kalender (`targets.outlook_calendar`) | ID des Outlook-Kalenders oder default für den Standardkalender des angemeldeten Microsoft-Kontos. Nur bei Kalenderdienst outlook benötigt. Bestehende Einträge werden nicht verschoben. Die Anlage erfordert weiterhin deine ausdrückliche Bestätigung. | Nach Neustart |
| Todoist-Projekt (`targets.todoist_project`) | ID des Todoist-Projekts für neue Aufgabenvorschläge, nicht dessen Anzeigename. Eine andere ID lenkt neue Vorschläge in ein anderes Projekt; bestehende Aufgaben werden nicht verschoben. Nicht leer, höchstens 500 Zeichen. Die Anlage erfordert weiterhin deine ausdrückliche Bestätigung. | Nach Neustart |

## Aufrufbudget und Mailgrenzen

| Einstellung / Schlüssel | Wirkung und Werte | Übernahme |
| --- | --- | --- |
| KI-Aufrufe pro Minute (`limits.llm_calls_per_minute`) | Budget von 1–600 KI-Aufrufen pro Minute. Ein kleinerer Wert bremst die Verarbeitung und reduziert Lastspitzen; ein größerer erlaubt mehr Aufrufe, soweit Anbieter und übrige Grenzen dies zulassen. Dies ist keine feste Geld- oder Tageskostengrenze. | Nach Neustart |
| Maximale KI-Anfragegröße (Bytes) (`limits.max_llm_payload_bytes`) | Größengrenze für aufbereitete Maildaten an die KI: 1–100000000 Bytes, keine Tokenzahl. Größere Werte erlauben mehr Inhalt und können Kosten und Laufzeit erhöhen. Zu große aufbereitete Inhalte werden abgewiesen; ein kleinerer Wert ist keine automatische Zusammenfassung. | Nach Neustart |
| Maximale Mailgröße (Bytes) (`limits.max_mail_bytes`) | Größengrenze für die Mailverarbeitung: 1024–100000000 Bytes. 1000000 entspricht ungefähr 1 MB. Größere Werte erlauben größere Mails und erhöhen den Ressourcenbedarf; kleinere können zur Ablehnung zu großer Inhalte führen. Anhänge und weitere MIME-Grenzen werden zusätzlich geprüft. | Nach Neustart |

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
| Höchstgröße je Datei (Bytes) (`attachments.max_original_bytes`) | Größte Datei, die als Original gespeichert wird: 1024–104857600 Bytes (Standard 25 MB). Größere Anhänge bleiben nur im Postfach. | Nach Neustart |
| Höchstgröße je Mail (Bytes) (`attachments.max_total_bytes`) | Höchstens so viele Bytes an Originalen je Mail: 1024–524288000 (Standard 50 MB). Weitere Anhänge derselben Mail werden nicht gespeichert. | Nach Neustart |
| Originale speichern (`attachments.store_originals`) | ja (true) speichert Originaldokumente (PDF, Word, Excel, OpenDocument, Text, Bilder) neu verarbeiteter Mails zum Herunterladen in der Weboberfläche. nein (false) speichert nur Bildvorschauen. Gespeicherte Originale werden mit der Aufbewahrungsfrist für Mailinhalte gelöscht. | Nach Neustart |

## Aufbewahrung

| Einstellung / Schlüssel | Wirkung und Werte | Übernahme |
| --- | --- | --- |
| Analysen aufbewahren (Tage) (`retention.analysis_days`) | Aufbewahrung archivierter Analysen. null übernimmt die Frist für KI-Diagnosedaten (debug_llm_days). 1–3650 bedeutet volle Tage seit der letzten Aktualisierung des abgeschlossenen Vorgangs. Kleinere Werte entfernen Inhalte früher. disabled entfernt sie beim nächsten Bereinigungslauf, unlimited bewahrt sie ohne Frist auf. Offene Vorgänge bleiben geschätzt. Entfernte Inhalte lassen sich durch späteres Verlängern der Frist nicht wiederherstellen. | Im laufenden Betrieb |
| KI-Diagnosedaten aufbewahren (Tage) (`retention.debug_llm_days`) | Aufbewahrung von KI-Diagnosedaten im Vorgang, etwa Zusammenfassung und Validierungsfehlern; separate JSONL-Logdateien haben eigene Fristen. 1–3650 bedeutet volle Tage seit der letzten Aktualisierung des abgeschlossenen Vorgangs. Kleinere Werte entfernen Inhalte früher. disabled entfernt sie beim nächsten Bereinigungslauf, unlimited bewahrt sie ohne Frist auf. Offene Vorgänge bleiben geschätzt. Entfernte Inhalte lassen sich durch späteres Verlängern der Frist nicht wiederherstellen. | Im laufenden Betrieb |
| Mailtexte aufbewahren (Tage) (`retention.full_mail_days`) | Aufbewahrung gespeicherter Mailtexte, Bildvorschauen und lokaler Entwurfstexte; die Originalmail im Postfach wird nicht gelöscht. 1–3650 bedeutet volle Tage seit der letzten Aktualisierung des abgeschlossenen Vorgangs. Kleinere Werte entfernen Inhalte früher. disabled entfernt sie beim nächsten Bereinigungslauf, unlimited bewahrt sie ohne Frist auf. Offene Vorgänge bleiben geschätzt. Entfernte Inhalte lassen sich durch späteres Verlängern der Frist nicht wiederherstellen. | Im laufenden Betrieb |
| Verlauf aufbewahren (Tage) (`retention.history_days`) | Aufbewahrung des Vorgangsverlaufs und der Inhalte historischer Vorschlagsversionen; Kennungen zum Schutz vor Doppelanlagen bleiben erhalten. 1–3650 bedeutet volle Tage seit der letzten Aktualisierung des abgeschlossenen Vorgangs. Kleinere Werte entfernen Inhalte früher. disabled entfernt sie beim nächsten Bereinigungslauf, unlimited bewahrt sie ohne Frist auf. Offene Vorgänge bleiben geschätzt. Entfernte Inhalte lassen sich durch späteres Verlängern der Frist nicht wiederherstellen. | Im laufenden Betrieb |
| Tätigkeitsberichte aufbewahren (Tage) (`retention.activity_report_days`) | Aufbewahrung gespeicherter Tätigkeitsberichte und ihrer Exporte; das Postfach bleibt unverändert. 1–3650 bedeutet volle Tage seit der letzten Aktualisierung des abgeschlossenen Vorgangs. Kleinere Werte entfernen Inhalte früher. disabled entfernt sie beim nächsten Bereinigungslauf, unlimited bewahrt sie ohne Frist auf. Offene Vorgänge bleiben geschätzt. Entfernte Inhalte lassen sich durch späteres Verlängern der Frist nicht wiederherstellen. | Im laufenden Betrieb |

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
| Bildauswertung: Höchstgröße je Bild (Bytes) (`vision.max_image_bytes`) | Größere Bilder werden nicht ausgewertet: 10240–50000000 Bytes; Standard 10485760 (10 MB). Größere Werte erlauben hochaufgelöste Scans und erhöhen Speicher- und Übertragungsbedarf. | Nach Neustart |
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

## Weboberfläche

| Einstellung / Schlüssel | Wirkung und Werte | Übernahme |
| --- | --- | --- |
| Web: Sitzungsdauer (Tage) (`web.session_days`) | So lange bleibt ein gekoppeltes Gerät angemeldet, bevor es neu gekoppelt werden muss: 1–365 Tage; Standard 30. Kürzere Werte verringern das Risiko verlorener Geräte, längere ersparen Kopplungen. | Nach Neustart |
| Web: Zugriff im eigenen Netzwerk (`web.lan_access`) | ja (true) macht die Weboberfläche im eigenen WLAN unter der privaten IP-Adresse des PCs erreichbar (unverschlüsseltes HTTP); erfordert web.host 0.0.0.0, sonst wird die Änderung abgelehnt. nein (false) beschränkt den Zugriff auf diesen PC und die freigegebenen Adressen. | Nach Neustart |

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
