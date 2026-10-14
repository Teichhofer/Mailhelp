# Mailhelp 1.2 – Nachvollziehbarkeit, Auswertung und Einstellungen im Web

> Historischer Versionsstand: Dieses Dokument beschreibt die genannte Version oder
> deren damaligen Plan. Ursprüngliche Ziele und Prüfergebnisse sind kein Nachweis
> des heutigen Umfangs. Aktueller Betrieb: [README](../README.md),
> [Release 3.3](Release-3.3.md) und [Projektspezifikation](../Mailhelp-Projektspezifikation.md).

Mailhelp 1.2 erweitert die Weboberfläche aus 1.1. Sie zeigt nicht mehr nur offene
Vorschläge, sondern den ganzen gespeicherten Ablauf: Mails mit ihrer Analyse, den
Entscheidungsverlauf, Kosten und Zeiten der KI-Aufrufe. Wichtige Einstellungen und
Themen lassen sich im Web ändern, und Mailhelp lässt sich kontrolliert beenden.
Telegram bleibt Benachrichtigungskanal.

Grundlage: [Konzept-1.2-Web-Ausbau.md](Konzept-1.2-Web-Ausbau.md). Einrichtung der
Weboberfläche, Tailscale und iPhone: [Release-1.1.md](Release-1.1.md).

## Neue Seiten

| Seite | Inhalt |
| --- | --- |
| **Mails** | Alle noch gespeicherten Mails mit Suche (Absender, Betreff, Zusammenfassung) und Filtern: Relevanz, Thema, Verarbeitung (wartet auf dich, mit Fehler, abgeschlossen, ohne Vorschlag), Vorschlagszustand, Zeitraum, Sortierung. 25 Einträge je Seite. Nicht der ganze Posteingang, nur was Mailhelp gespeichert hat. |
| **Mail** | Zusammenfassung und Fristen, Relevanz mit Begründung und Themen, Quelle der Entscheidung (z. B. Jev, Mensch), erkannte Vorschläge und die Originalmail, solange sie aufbewahrt wird. |
| **Verlauf** | Ereignisse je Vorschlag (erzeugt, geändert, bestätigt, verworfen, angelegt …) mit Quelle Telegram/Web/System, filterbar. Ältere Versionen lassen sich lesend öffnen, mit den Änderungen gegenüber der Vorgängerversion. Vorgänge aus der Zeit vor 1.2 sind als „Altbestand / Ablauf nicht vollständig erfasst“ gekennzeichnet. |
| **Vorschlag bearbeiten** | Titel, Beschreibung, Ziel, Frist bzw. Beginn, Ende, ganztägig, Ort und Videolink (nur `https`) in Formularfeldern. Speichern erzeugt eine neue Version – **ohne** Eintrag in Kalender oder Todoist. Die neue Version muss separat bestätigt werden. Uhrzeiten gelten in der eingestellten Zeitzone; nicht existierende oder doppeldeutige Zeiten bei der Zeitumstellung werden abgelehnt. |
| **Status** | Zusätzlich: aktueller Verarbeitungsschritt mit Dauer, nächster Mailabruf, bearbeitete Mail sowie je Dienst (IMAP, KI, Jev, Telegram, Todoist, Google Kalender, Google-Anmeldung) der letzte belegte erfolgreiche Kontakt. Die Seite prüft selbst keinen Dienst. |
| **Auswertung** | Kosten und Zeiten nach Zeitraum, Erfassung (Betrieb oder Vergleichsläufe), Modell, Anbieter und Schritt: Anzahl, Fehler, gemeldete Kosten in USD, Aufrufe ohne Kostenangabe, Euro nur mit hinterlegtem Wechselkurs, geschätzte Stromkosten im Ollama-Betrieb, Dauer (Mittel, Median, 95 %). |
| **Einstellungen** | Modelle je Schritt mit Parametern und Quelle (`prompts.yaml`, `decisions_prompts.yaml`, Startparameter) – nur lesend. Darunter die bearbeitbaren Werte in Gruppen, jeweils mit „aktiv“ und „gespeichert“ und dem Zeitpunkt der Übernahme. |
| **Themen** | Relevante und ausgeschlossene Themen anlegen, ändern, deaktivieren (nicht löschen). Mindestens ein relevantes Thema bleibt aktiv. |
| **Mailhelp beenden** | Bestätigungsseite unter Einstellungen; erst ein ausdrücklich bestätigter Klick beendet Mailhelp. |

## Einstellungen im Web

Bearbeitbar sind:

- Abrufintervall, Zeitzone, Trockenlauf und die Ziele (Todoist-Projekt, Google-Kalender)
- KI-Aufrufe pro Minute, Mail- und Anfragegrößen
- Zeitlimits und Wiederholungen je Dienst
- Aufbewahrungsfristen
- Log-Level und vollständige KI-Protokollierung
- Metrik- und Stromannahmen

Nicht im Web bearbeitbar sind: Host, Port, erlaubte Hosts, Datenverzeichnis, IMAP-Konten
und alle Geheimnisse. So kann man sich nicht versehentlich aussperren.

- **Ablauf:** Jede Änderung wird vor dem Speichern noch einmal angezeigt. Erst
  „Änderung ausdrücklich speichern“ speichert. Hat jemand die Datei inzwischen geändert
  (Hand, Lernmodus, anderes Gerät), gibt es einen Konflikt statt eines Überschreibens.
- **Kommentarerhaltend:** `config.yaml` wird nicht neu geschrieben. Nur die Zeile des
  geänderten Werts wird ersetzt bzw. ein fehlender Schlüssel im passenden Abschnitt
  ergänzt; Kommentare und Aufbau bleiben. Ergäbe die Datei danach nicht genau den
  geprüften Inhalt, wird nichts gespeichert.
- **Übernahme:** Abrufintervall, Aufbewahrung und Metrikannahmen wirken an der nächsten
  sicheren Stelle zwischen zwei Mails. Alles andere wirkt nach einem Neustart und wird
  bis dahin als „gespeichert – wirkt erst nach einem Neustart“ angezeigt.
- **Laufende Mails:** Betriebseinstellungen halten keine laufende Mail mehr an. Nur
  Änderungen, die die Analyse betreffen (Zeitzone, Grenzen, Ziele, Prompts, Themen),
  werden wie bisher für bereits begonnene Mails nicht übernommen.
- **Aufrufbudget:** Ein gesenktes KI-Aufruflimit nutzt das bestehende Budget weiter;
  bereits gezählte Aufrufe bleiben gezählt.
- **Docker:** `compose.yaml` bindet `config.yaml` schreibgeschützt ein. Speichern im Web
  meldet dann „nicht schreibbar“ und ändert nichts. Wer im Container über das Web
  ändern will, muss die Datei beschreibbar einbinden.

Der Lernmodus ergänzt neu gefundene IMAP-Ordner jetzt ebenfalls kommentarerhaltend:
Er hängt nur die neuen Einträge an die Ordnerliste an.

## Themen

Neue oder geänderte Themen gelten für neu eingehende Mails. Bereits begonnene Mails
behalten den Themenstand, mit dem ihre Analyse begonnen hat. Vorhandene Vorschläge und
ihre Bestätigungen ändern sich nicht. Es startet kein Lernlauf und es entstehen keine
KI-Kosten. Ein gleichzeitig laufender Lernlauf hat Vorrang: Das Webformular meldet
dann einen Konflikt.

## Mailhelp beenden

1. Mailhelp bestätigt die Anforderung („Beenden angefordert“). Ab dann werden keine
   neuen Analysen und keine neuen Web-Aktionen mehr ausgeführt; noch nicht ausgeführte
   Web-Aktionen bleiben gespeichert und werden nach dem nächsten Start erneut geprüft.
2. Ein laufender KI-Aufruf darf bis zu seinem Zeitlimit zu Ende laufen (bei Ollama
   möglicherweise einige Minuten). Eine begonnene Anlage in Kalender oder Todoist wird
   abgeschlossen oder als „wird abgeglichen“ gespeichert, nie wiederholt.
3. Die Zustände `running → stop_requested → stopping → stopped` stehen im
   Anwendungsprotokoll. Strg+C bzw. SIGTERM nehmen denselben Weg.

Danach ist auch die Weboberfläche nicht erreichbar. Neu starten am PC oder über den
Dienst/Container. **Achtung Docker:** `compose.yaml` verwendet `restart: unless-stopped`.
Docker startet den Container deshalb nach dem Beenden aus dem Web sofort wieder;
dauerhaft anhalten nur mit `docker compose stop`. Andere Supervisoren (z. B. ein
Windows-Dienst) können sich ebenso verhalten. Eine Stoppanforderung wird nach einem
Neustart nie wiederholt.

## Neue Konfiguration und Dateien

| Schlüssel bzw. Datei | Bedeutung |
| --- | --- |
| `retention.analysis_days` | Aufbewahrung der kompakten Analyse. Fehlt der Schlüssel, gilt wie bisher `debug_llm_days`. |
| `retention.history_days` | Aufbewahrung des Verlaufs (Standard 90 Tage). Danach werden Ereignisdetails und Inhalte älterer Versionen entfernt; Sicherheitsreferenzen gegen Doppelanlagen bleiben. |
| `metrics.*` | Erfassung (`enabled`), Aufbewahrung der Einzelmessungen (`retention_days`), Stromannahmen und optionaler Wechselkurs mit Datum. |
| `analysis-<mail>.json` | Kompakte Analyse einer Mail |
| `history-<mail>.json` | Inhaltsarme Ereignisse des Entscheidungsverlaufs |
| `configuration-<schlüssel>.json` | Journal einer Einstellungs- oder Themenänderung (Wiederanlauf) |
| `processing-topics-<fingerprint>.json` | Themenstand, mit dem eine Mail analysiert wurde |
| `logs/metrics/llm.jsonl`, `logs/metrics/decision-tests.jsonl` | Inhaltsfreie Messungen je KI-Versuch (Betrieb bzw. Vergleichsläufe) mit Tagesaggregaten `*-daily.json` |

`mailhelp --clear` entfernt auch diese Dateien.

## Upgrade von 1.1

1. Vorher sichern: Datenverzeichnis, `config.yaml`, Themendateien.
2. Paket aktualisieren und `mailhelp --check` ausführen.
3. Beim ersten Start gilt Folgendes:
   - Fingerprints, die 1.1 für dieselbe Konfiguration berechnet hat, werden als gleichwertig registriert. Offene Relevanzfragen und Vorschläge laufen weiter.
   - Gespeicherte Web-Aktionen aus 1.1 werden normal abgearbeitet.
   - Metrikdateien aus einer 1.2-Beta werden einmalig nach `logs/metrics/` übernommen.
4. Vorgänge vor 1.2 haben keinen vollständigen Verlauf. Die Weboberfläche kennzeichnet
   das, statt Zeitpunkte oder Entscheidungen zu erfinden.

**Rollback auf 1.1:** Das Datenverzeichnis aus der Sicherung vor dem Upgrade
zurückspielen. 1.1 kennt die neuen Dateien und Schlüssel nicht und wird nicht
ungeprüft mit einem 1.2-Zustand gestartet. Vor dem Rollback offene Aktionen mit
Kalender und Todoist abgleichen, damit keine Doppelanlage entsteht.

## Tests

- Die Gesamtsuite deckt den eigenen Code zu 100 % (Zeilen und Branches) ab.
- Abgedeckt sind unter anderem:
  - Ende-zu-Ende-Abläufe mit einer echten Fixture-Mail
  - Upgrade-Fälle von 1.1
  - schreibgeschützte Konfiguration
  - kommentarerhaltendes Speichern
  - Stoppablauf
  - Metriken ohne Doppelzählung
- Browsertests (`ui_tests/`) prüfen jede Seite in drei Formaten (Desktop, iPhone, 320 px) und die Tastaturbedienung. Dazu kommen Screenshots, Bedienbarkeits- und Kontrastprüfungen sowie 100 % Blockabdeckung von `app.js` und `sw.js`.

## Einschränkungen

- Kein Import alter KI-Logs in die Auswertung; sie beginnt mit der Erfassung in 1.2.
- Die Liste der Ziele ist ein Textfeld, keine Auswahl aus abgefragten Projekten und
  Kalendern.
- Absender-Vorfilter (`irrelevant-senders.json`) werden im Web nur angezeigt, nicht
  bearbeitet.
- Modelle und Prompts bleiben im Web lesend.
