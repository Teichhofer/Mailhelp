# Bugreport: Offene Telegram-Klärung bleibt nach Neustart ohne erneute Handlungsaufforderung stehen

**Datum:** 06.10.2026  
**Untersuchter Commit:** `d08ec8653c5e18e904d6e2c4540bc1fa55aa6a2e`  
**Priorität:** Hoch – eine einzelne offene Entscheidung hält die gesamte weitere Mailverarbeitung an.  
**Kategorie:** Dialogführung und Wiederaufnahme; kein nachgewiesener Telegram-Ausfall.  
**Status:** Ursache anhand des lokalen Zustands und der Logs bestätigt, mit synthetischen Daten reproduziert. Behebung noch nicht implementiert.

## 1. Ergebnis

Mailhelp wartet auf eine Klärung, ohne beim Neustart die dazugehörige Frage oder bedienbare Vorschlagsansicht erneut zu zeigen. `/status` und `/offen` liefern ausschließlich eine Textübersicht. Die Statusmeldung „Warte auf Rückfrage/Korrektur“ unterscheidet nicht zwischen einem Vorschlag mit offenen Fragen und einem tatsächlich geöffneten Rückfragedialog.

Im konkreten Fall wurde der ursprüngliche Vorschlag bereits um **07:13 Uhr** mit den Schaltflächen **„Klären“ und „Verwerfen“** verschickt. Ein Rückfragedialog wird jedoch erst durch „Klären“ aktiviert. Im vorliegenden Datenbestand fehlt `telegram-dialog.json`; außerdem gibt es keine `clarification-*.json`-Datei. Die vorhandenen Logs zeigen keinen verarbeiteten Klären-Callback. Nach dem Neustart um **15:47 Uhr** folgt nur die Starthilfe. Um **18:38 Uhr** beantwortet der Bot `/status` mit dem im Screenshot sichtbaren Wartetext.

Der Prozess ist damit nicht abgestürzt: Telegram wird weiterhin abgefragt. Die fachliche Verarbeitung wartet absichtlich auf eine Benutzerentscheidung, während die aktuelle Oberfläche keine passende nächste Aktion anbietet. Die ursprüngliche Schaltfläche im älteren Chatverlauf bleibt der vorhandene Einstieg.

## 2. Belege aus dem konkreten Vorfall

Die Untersuchung nutzte den bereitgestellten Screenshot sowie die lokalen Zustands- und Logdateien ausschließlich lesend. Zugangsdaten und vollständige Mailinhalte wurden nicht in diesen Bericht übernommen. Zeiten in der folgenden Tabelle sind Europe/Berlin, am Vorfalltag UTC+02:00.

| Zeitpunkt am 06.10.2026 | Beobachtung | Bedeutung |
| --- | --- | --- |
| 07:13:16 | Versand des betroffenen Vorschlags mit „Klären“ und „Verwerfen“ in `logs/telegram/messages.jsonl` | Der ursprüngliche Vorschlagsversand ist protokolliert; die Schaltflächen sind auch im Screenshot sichtbar. |
| 07:13:16 | `proposal_decision_pending` in `logs/application.jsonl` | Der Orchestrator stoppt nach dem Vorschlag an der vorgesehenen Entscheidungsgrenze. |
| 15:47:54–15:47:55 | `application_started`, danach `startup_help_sent` | Neustart und Versand der allgemeinen Hilfe, ohne erneute konkrete Handlungsaufforderung. |
| 18:38:14 | Empfang von `/status`, `update_processing` mit Typ `message`, anschließend `update_processed` | Telegram-Empfang und Befehlsverarbeitung funktionieren. |
| 18:38:14 | Versand von „Videokonferenz per Skype vereinbaren · Version 1: Warte auf Rückfrage/Korrektur“ | Die Antwort zeigt nur den Status; keine neue Frage und keine Schaltflächen. |
| Bis mindestens 18:46:15 | Weitere `poll_completed`-Ereignisse | Der Dienst arbeitet weiter im Telegram-Polling. |

Betroffener aktueller Vorschlag:

`data/production/proposal-b39cc458ad051adcc1846c18-p_11dd496b8096b11835ca372b.json`

| Feld | Wert |
| --- | --- |
| `title` | `Videokonferenz per Skype vereinbaren` |
| `version` | `1` |
| `status` | `needs_clarification` |
| `open_questions` | `Welches konkrete Datum ist mit „Morgen oder am Mittwoch“ gemeint?` |
| Aktive Dialogdatei | Nicht vorhanden |
| Separate Klärungsdatei | Nicht vorhanden |

In `data/production/mail-b39cc458ad051adcc1846c18.json` steht die Benachrichtigung für genau diesen Vorschlag und Version auf `completed`. Gleichzeitig sind `steps.proposal_notification = sending` und `steps.completion = pending` gespeichert.

Diese Kombination ist hier durch den Kontrollfluss erklärbar: Der Orchestrator kehrt nach der erfolgreichen einzelnen Benachrichtigung mit `WAITING` zurück, bevor er den übergeordneten Schritt abschließt (`src/mailhelp/orchestrator.py:553`). Das übergeordnete `sending` allein beweist daher keinen fehlgeschlagenen Versand.

**Grenze der Aussage:** Die Logs belegen keinen verarbeiteten Klick auf „Klären“. Sie beweisen nicht, dass die Person niemals auf dem Gerät getippt hat. Ein verlorener oder nicht protokollierter Client-Vorgang lässt sich damit nicht ausschließen. Für einen serverseitigen Fehler beim Verarbeiten eines solchen Klicks liegt hier kein Beleg vor. Ebenso ist die damalige ausführbare Revision nicht allein durch den heutigen Git-Stand bewiesen; das beobachtete Verhalten lässt sich mit dem untersuchten Stand reproduzieren.

## 3. Erwartetes und tatsächliches Verhalten

| Situation | Erwartetes nutzbares Verhalten | Tatsächliches Verhalten |
| --- | --- | --- |
| Neustart mit offener Klärung | Die blockierende Entscheidung ist direkt wieder erreichbar, mit konkreter Frage oder versionsgebundenen Schaltflächen. | Allgemeine Starthilfe; danach Warten auf die alte Entscheidung. |
| `/offen` | Eine offene Aufgabe lässt sich aus der Übersicht wieder öffnen. | Dieselbe reine Statusübersicht wie `/status`, ohne Schaltflächen. |
| Status vor „Klären“ | Erkennbar: „Bitte beim Vorschlag ‚Klären‘ auswählen“. | „Warte auf Rückfrage/Korrektur“, obwohl noch kein Antwortdialog existiert. |
| Freitext vor Dialogöffnung | Klarer, zur sichtbaren Oberfläche passender Einstieg in die Klärung. | „Keine offene Rückfrage. Bitte zuerst ‚Ändern‘ wählen.“ Beim betroffenen Vorschlag heißt die Schaltfläche aber „Klären“. |
| `/abbrechen` ohne aktiven Dialog | Kein Wiederherstellungsversprechen; sinnvoller erreichbarer Einstieg. | „Keine aktive Bearbeitung. Offene Entscheidungen: /offen“; `/offen` führt wieder nur zur Statusübersicht. |

**Einordnung gegenüber der Spezifikation:** Die globale Pause und die initialen Schaltflächen entsprechen ausdrücklich der vorhandenen Spezifikation (`Mailhelp-Projektspezifikation.md:679` und `:681`). Auch die rein lesende Übersicht ist dort beschrieben (`:721`). Der Defekt liegt in der unvollständigen Bedien- und Wiederaufnahmegestaltung: Es fehlt eine durchgängige Rückführung aus dem Wartezustand zur konkreten Entscheidung. Eine automatische Rückfrage ohne vorherigen Klären-Klick wäre eine zusätzliche Verhaltensänderung und müsste entsprechend spezifiziert werden. Der Fehler darf nicht durch Entfernen der Bestätigungspflicht oder blindes Weiterverarbeiten „behoben“ werden.

## 4. Technische Ursache

### 4.1 Fachlicher Klärungsbedarf wird als aktiver Wartezustand behandelt

`TelegramDialogController.awaiting_decision()` (`src/mailhelp/telegram/dialog.py:189`) liefert für aktuelle Vorschläge mit `pending_confirmation` oder `needs_clarification` grundsätzlich `True`. Ein aktiver `TelegramDialogState` oder eine nachweislich gestellte Dialogfrage ist dafür keine Voraussetzung.

`TelegramCommands.overview()` (`src/mailhelp/telegram/commands.py:33`) leitet den Wartetext im vorliegenden Fall lediglich aus `proposal.status` ab. Die Methode prüft nicht, ob der Benutzer bereits „Klären“ gewählt hat. `/status` und `/offen` sind auf dieselbe Methode geroutet (`:26`).

### 4.2 Die tatsächliche Rückfrage entsteht erst durch einen Callback

`ProposalPresenter.present()` zeigt bei offenen Fragen „Klären“ als `DecisionAction.EDIT` (`src/mailhelp/telegram/presenter.py:63`). Erst `ProposalDecisionService.decide()` im EDIT-Zweig (`src/mailhelp/telegram/decisions.py:50`) speichert `telegram-dialog` und sendet `clarification_prompt(...)`.

Das ursprüngliche Senden eines Vorschlags aktiviert diesen Dialog nicht. Deshalb reicht der gespeicherte Status `needs_clarification` nicht aus, um eine spätere Freitextantwort zuzuordnen. `ProposalRevisionProcessor.answer()` weist sie ohne Dialogreferenz zurück (`src/mailhelp/telegram/revisions.py:106`). Diese Zuordnungssicherung ist sinnvoll; es fehlt der erreichbare Weg zur Dialogöffnung.

### 4.3 Der Neustart stellt nur die Sperre wieder her

`Application.run()` sendet zunächst die allgemeine Hilfe (`src/mailhelp/application.py:746`). Liegt bereits eine offene Entscheidung vor, ruft die Anwendung vor dem nächsten IMAP-Abruf `_wait_for_telegram_decision()` auf (`:769`). Diese Schleife pollt Telegram, stellt den Vorschlag aber nicht erneut dar (`:733`).

Die Wiederaufnahme in `ProposalRevisionProcessor` setzt gespeicherte Antworten bzw. Revisionen fort (`src/mailhelp/telegram/revisions.py:656` und `:690`). Sie öffnet keinen neuen Dialog für einen bloßen Vorschlag mit offenen Fragen.

### 4.4 Ein normaler erneuter Versand ist ebenfalls gesperrt

`ProposalDeliveryService.deliver()` kehrt bei einem Benachrichtigungsstatus von `completed` oder `sending` ohne Versand zurück (`src/mailhelp/telegram/delivery.py:36`). Beim konkreten Vorschlag steht der Status auf `completed`.

Das verhindert unkontrollierte Doppelmeldungen und erklärt, weshalb ein bloßer zusätzlicher Aufruf von `send_proposal()` keine ausreichende Korrektur wäre. Eine bewusst angeforderte Wiederanzeige muss von der erstmaligen Zustellung unterschieden werden.

## 5. Reproduktion mit simulierten Diensten

Die folgende Sequenz wurde unter Windows mit Python 3.12.10 tatsächlich ausgeführt. Verwendet wurden ein temporärer `JsonStore`, die vorhandenen Testhelfer `proposal`, `controller`, `message` und `callback` aus `tests/test_telegram_dialog.py`, synthetische Maildaten sowie gemockte Writer. Produktionsdaten wurden dabei nicht verändert; es wurden keine echten Telegram-, LLM-, Kalender- oder Todoist-Aufrufe ausgeführt.

1. Synthetischen Aufgabenvorschlag Version 1 mit einer offenen Datumsfrage erzeugen. Einen `MailState` mit passendem `ProposalNotification` im Status `pending` speichern.
2. Den Vorschlag über `controller.send_proposal()` zustellen. Den erzeugten Klären-Callback für später aufheben.
3. Prüfen: Versand erfolgt, Benachrichtigung `completed`, `awaiting_decision() == True`, aber kein `telegram-dialog` gespeichert.
4. Store schließen, erneut öffnen und einen neuen Controller konstruieren. `poll_once()` ohne Updates ausführen.
5. Prüfen: keine neue Nachricht; Entscheidung weiterhin offen. Auch erneutes `send_proposal()` sendet wegen `completed` nichts.
6. Autorisierte Updates `/status` und `/offen` verarbeiten. Beide liefern nur den Wartetext ohne konkrete Frage und ohne Inline-Schaltflächen.
7. Eine Datumsantwort als Freitext senden. Sie wird wegen fehlendem Dialog abgelehnt.
8. `/abbrechen` senden. Antwort: keine aktive Bearbeitung; der Vorschlag wird nicht erneut gezeigt.
9. Den ursprünglichen, versionsgebundenen Klären-Callback verarbeiten. Jetzt entstehen die Dialogreferenz und die konkrete Rückfrage. Die gemockten externen Writer bleiben unaufgerufen.

Alle Assertions dieser Reproduktion waren erfolgreich. Der Neustart der Dialogkomponenten wurde praktisch getestet; die Einbettung in die dauerhafte Anwendungsschleife wurde zusätzlich anhand des Codes und der vorhandenen Anwendungstests geprüft.

## 6. Auswirkung und unmittelbarer Workaround

Eine einzelne offene Klärung blockiert weitere Vorschläge und Mails auch über Neustarts hinweg. Die Anwendung wirkt hängen geblieben, obwohl der Telegram-Dienst erreichbar ist. `/offen`, `/status` und `/abbrechen` stellen im dokumentierten Zustand keinen bedienbaren Ersatz für die alte Vorschlagsnachricht bereit.

**Für den vorliegenden Fall:** Im Telegram-Verlauf zur Nachricht von **07:13 Uhr** zurückgehen und **„Klären“** drücken. Diese Schaltfläche ist oben im Screenshot noch sichtbar. Danach sollte die konkrete Datumsfrage erscheinen; die Antwort kann dann dem Vorschlag zugeordnet werden. Der entsprechende Ablauf funktionierte in der Simulation. Er wurde nicht im echten Chat ausgelöst.

Eine vervollständigte neue Vorschlagsversion muss anschließend ausdrücklich bestätigt werden. Falls die Aufgabe nicht übernommen werden soll, ist „Verwerfen“ die vorhandene bewusste Entscheidung zum Schließen dieses Vorschlags. Ein Neustart oder `/status` allein löst die offene Entscheidung nicht. Das manuelle Löschen von Zustandsdateien ist für diesen Workaround nicht nötig.

## 7. Empfohlene Behebung

1. **`/offen` als Einstieg nutzbar machen:** Aktuelle offene Vorschläge mit versionsgebundenen Schaltflächen erneut anzeigen oder je Vorschlag eine eindeutige Schaltfläche zum Öffnen anbieten. `/status` kann eine reine Übersicht bleiben. Bei mehreren Vorschlägen keine willkürliche Freitextzuordnung vornehmen.
2. **Neustart verständlich gestalten:** Nach der Hilfe einmal pro Start auf die konkret blockierende Entscheidung verweisen und eine direkte Wiederaufnahme ermöglichen. Einen bereits aktiven unbeantworteten Dialog mit seiner konkreten Frage wieder zugänglich machen; gespeicherte Antworten weiterhin über die vorhandene Revision fortsetzen.
3. **Status präzisieren:** Zwischen „Klärung erforderlich – bitte ‚Klären‘ wählen“, „Warte auf Antwort zur angezeigten Frage“, „Antwort gespeichert“ und „Verarbeitung pausiert“ unterscheiden. Die allgemeine Freitextfehlermeldung an „Klären“/„Ändern“ anpassen.
4. **Bewusste Wiederanzeige getrennt implementieren:** Die Anzeige darf weder den ursprünglichen Zustellnachweis zurücksetzen noch eine neue fachliche Version oder Schreibfreigabe erzeugen. `completed` nicht pauschal auf `pending` setzen. Die Behandlung unklarer Sendefälle (`sending`) gesondert erhalten.
5. **Spezifikation und Dokumentation aktualisieren:** Das neue Verhalten von `/offen` und der Startwiederaufnahme festhalten; Konfigurationsbeispiele bei Einführung einer Einstellung ergänzen.

Falls stattdessen die konkrete Frage bei jedem erstmaligen unvollständigen Vorschlag automatisch gestellt werden soll, muss das Öffnen der Dialogreferenz und deren Zustellung ausdrücklich Teil dieses Ablaufs werden. Nur den Text zu senden reicht nicht, weil Freitext sonst weiterhin mangels Dialogzuordnung abgewiesen wird.

## 8. Erforderliche Regressionstests und Abnahmekriterien

| Fall | Abnahmekriterium |
| --- | --- |
| Neustart mit `needs_clarification`, ohne Dialog, Zustellung `completed` | Der Benutzer erhält einen direkt bedienbaren Einstieg; keine externe Schreibaktion. |
| `/offen` im gleichen Zustand | Aktuelle Aufgabe und wirksamer, versionsgebundener Klären-Einstieg erscheinen. |
| Bereits aktiver unbeantworteter Dialog | Konkrete Frage ist wieder erreichbar und die Antwort wird korrekt zugeordnet. |
| Bereits gespeicherte Antwort | Keine erneute Antwortanforderung; vorhandene Verarbeitung wird fortgesetzt. |
| Mehrere offene Vorschläge | Auswahl bleibt eindeutig; keine automatische Zuordnung zu einem beliebigen Vorschlag. |
| Wiederholung, Neustart und Versandfehler | Keine Zustandsverluste, keine unkontrollierte Wiederholungsmeldung bei jedem Poll; erneute bewusste Anzeige möglich. |
| Veralteter Callback oder fremder Nutzer/Chat | Keine Änderung oder Schreibfreigabe für die aktuelle Version. |
| Antwort erzeugt neue Version | Neue ausdrückliche Bestätigung bleibt vor jeder externen Anlage erforderlich. |
| Letzte Entscheidung abgeschlossen | Die Anwendung verlässt die Warteschleife und setzt die Mailverarbeitung fort. |

Die vorhandenen Tests prüfen Statusausgaben und die absichtliche Pause, aber decken die geforderte durchgängige Wiederaufnahme ohne Suche im alten Chat nicht ab. Beispiele: `tests/test_telegram_usability.py:162`, `tests/test_application.py:769` und `tests/test_application.py:1266`. Vollständige Zeilen- und Branch-Abdeckung allein verhindert diese Lücke in den Verhaltensanforderungen nicht.

## 9. Validierung des untersuchten Stands

Die vollständige vorhandene Testsuite wurde mit folgendem PowerShell-Aufruf ausgeführt:

```powershell
& "$env:TEMP\mailhelp-python-3.12.10\python.exe" -m pytest -c pyproject.toml -q -x --cov=mailhelp --cov-branch --cov-fail-under=100
```

**Ergebnis:** 788 Tests bestanden; 6.075 Statements ohne fehlende Zeilen und 1.878 Branches ohne Teilabdeckung; ausgewiesene Gesamt-Coverage 100 %, Laufzeit 12,57 Sekunden.

Ein erster Lauf innerhalb der Sandbox scheiterte an Zugriffsrechten auf das vorhandene pytest-Tempverzeichnis. Der anschließende Lauf außerhalb der Sandbox war erfolgreich. Coverage meldete zusätzlich `module-not-measured` wegen eines vor Messbeginn importierten Moduls; der finale Bericht wies dennoch für alle 51 erfassten Dateien vollständige Abdeckung aus.

Für diesen Auftrag wurde ausschließlich der Bugreport ergänzt. Anwendungscode, Produktionszustand und Konfiguration wurden nicht geändert. Es wurde keine reale Telegram-Nachricht versendet und keine Aufgabe oder kein Kalendereintrag angelegt.
