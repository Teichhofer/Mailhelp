# Entkopplung von Bedienung und Mailabruf – Analyse

**Stand:** 3. November 2026 (Version 3.6.3)  
**Zweck:** Grundlage für [Planung 3.6](Planung-3.6.md), Schritte 0.5 (Arbeitsthread) und 0.6 (Nachweis)  
**Status:** Umgesetzt in 3.6.4 (Abschnitt 7); Tests in 3.6.5 (Abschnitt 8); Messung im Betrieb offen

---

## 1. Ist-Zustand

| Thread | Aufgaben |
| :--- | :--- |
| Hauptthread (`Application.run`) | Je Zyklus: ausstehende Postfach-/IServ-Aktivierungen (`apply_pending`), Aufbewahrung (`_maintain`), IMAP- und IServ-Stapel mit allen LLM-Aufrufen, danach `dialog.poll_once` und Leerlauf (`_idle`). |
| `dialog.poll_once` (im Hauptthread) | Schreibaufträge und Revisionen fortsetzen, unterbrochene Web-Befehle abgleichen, Telegram-Updates verarbeiten, **Web-Befehle ausführen** (`ReviewCommand` und `AdminCommand`), Outbox leeren. |
| Webserver-Threads | Seiten aus dem Store lesen; Aktionen nur in die persistente `CommandInbox` einreihen, nie ausführen. |
| Telegram-Empfänger | Füllt die `TelegramInbox`; weckt den Leerlauf. |
| Benachrichtigungsdienst | Eigener Ablauf mit `_runner`-Sperre. |

Folge: Ein Web-Befehl wartet, bis der laufende IMAP-/IServ-Stapel (bis `batch_size` = 25 Mails
mit allen LLM-Aufrufen) vollständig abgearbeitet ist. Gemessen am 2. November 2026: 0,6–3 s im
Leerlauf, 8,5–10,7 s während eines Zyklus, 36 s hinter einer einzelnen LLM-Analyse; bei einem
vollen Stapel entsprechend länger. Die Aufbewahrung blockiert seit 3.5.5 nur noch stündlich.

## 2. Ziel von Schritt 0.5

Ein eigener **Bedien-Thread** führt `dialog.poll_once` in einer Schleife aus: Telegram-Updates,
Web-Befehle, Fortsetzung von Schreibaufträgen und Revisionen, Outbox. Der Hauptthread verarbeitet
nur noch Mails. Der Telegram-Dialog wird damit von genau einem Thread bedient; die übrigen
Threads übergeben ihm Arbeit, statt ihn direkt aufzurufen.

## 3. Gemeinsam genutzte Ressourcen

| Ressource | Zugriffe heute | Schutz heute | Erforderlich nach 0.5 |
| :--- | :--- | :--- | :--- |
| `JsonStore` (Einzelzugriff) | alle Threads | `RLock` je `load`/`save`, atomares Ersetzen | ausreichend |
| `JsonStore` (Lesen–Ändern–Schreiben) | Abgleich, Review, Benachrichtigungen, Entwürfe, Einrichtung | `store.locked()` an 37 Stellen | Jede Änderung einer Datei, die beide Threads schreiben, muss in `store.locked()` geschehen (Prüfliste in 0.5). |
| Vorschläge | Hauptthread: Vorschlagsbau und Abgleich (`ProposalReconciliationService`, Zusammenführen offener Vorschläge); Bedien-Thread: Bestätigen, Bearbeiten, Zusammenführen, Neuprüfung | Abgleichsdienst nutzt `store.locked()`; Review prüft Version vor dem Speichern | Muster „außerhalb der Sperre berechnen, in der Sperre Version prüfen und speichern“ für alle Schreibpfade beider Threads; Vorschlagsbau des Orchestrators daraufhin prüfen. |
| Mailzustände | Hauptthread: Verarbeitung; Bedien-Thread: Relevanzentscheidung, Neuprüfung (`recheck_mail`) | Relevanzentscheidung nur für wartende, Neuprüfung nur für abgeschlossene Mails; atomares Speichern | Beide Bedienpfade in `store.locked()` mit erneutem Laden; der Hauptthread verarbeitet keine abgeschlossene oder wartende Mail. |
| Telegram-Dialog (Zeiger, Outbox, Offset, Inbox) | Hauptthread über den Notifier des Orchestrators (`send_proposal`, `send_relevance`) und `poll_once` | keiner (ein Thread) | Notifier-Aufrufe des Hauptthreads in eine threadsichere Warteschlange stellen, die der Bedien-Thread abarbeitet; der Dialog bleibt einthreadig. |
| Live-Einstellungen (`Application.apply_settings`) | `AdminCommand` aus `poll_once` | keiner (läuft heute im Hauptthread zwischen Zyklen) | Als ausstehende Aktivierung vormerken und im Hauptthread am Zyklusbeginn anwenden (Muster `PendingConnections`). |
| Themen (`Orchestrator.change_topics`) | `AdminCommand` aus `poll_once` | keiner | Wie Live-Einstellungen; der Fingerprint darf sich nie während einer Mailverarbeitung ändern. |
| Postfach-/IServ-Aktivierung | Web/Bedienung fordert an, Hauptthread installiert | `PendingConnections.lock` | unverändert |
| Relevanzfrage | Hauptthread wartet in `_wait_for_telegram_decision` und pollt dafür selbst Telegram | ein Thread | Hauptthread wartet auf ein Ereignis, das der Bedien-Thread nach einer Entscheidung setzt; er pollt Telegram nicht mehr selbst. |
| LLM-Clients | Hauptthread (Analyse), Bedien-Thread (Revisionen, Antworten aus der Mail) | `OpenRouterClient._state_lock` (auch für `OllamaClient`) | ausreichend; Budget- und Ratenbegrenzung gelten gemeinsam. |
| Schreibausführung, Ledger | Bedien-Thread (`write_executor.resume`, Bestätigung) | `store.locked()` in `telegram/writes.py` | unverändert; der Hauptthread schreibt nicht extern. |
| Logger, Metriken | alle | `RLock` | ausreichend |
| Lebenszyklus | Web (Beenden/Neustart), beide Threads prüfen `stop_event` | `Event` | Bedien-Thread endet bei `stop_event` und wird vor dem Schließen der Adapter beendet. |

## 4. Sperren und Reihenfolge

1. Höchstens eine Sperre aus jeder Stufe, immer in dieser Reihenfolge:
   **Dialog-Warteschlange → `store.locked()` → Blattsperren** (Logger, Metriken,
   LLM-Zustand, `PendingConnections`, Empfänger-Inbox).
2. Unter `store.locked()` keine Netzwerkaufrufe (LLM, Kalender, Todoist, IMAP, Telegram).
   Bestehendes Muster (z. B. `recheck_proposal`): extern prüfen, danach in der Sperre den
   unveränderten Stand bestätigen und speichern, sonst `StaleCommand`.
3. Blattsperren rufen nichts auf, was eine andere Sperre nimmt.
4. Der Hauptthread hält keine Sperre über die Dauer einer Mailverarbeitung.

## 5. Umsetzung in Schritt 0.5

1. Bedien-Thread mit Schleife um `poll_once`, geweckt durch `TelegramInbox` und `CommandInbox`
   (neues Ereignis beim Einreihen), sonst mit kurzem Zeitlimit; Start nach Empfänger und Web,
   Ende vor `services.stop_web()` und dem Schließen der Adapter.
2. Notifier-Aufrufe des Orchestrators über eine Warteschlange an den Bedien-Thread.
3. `apply_settings` und `change_topics` als ausstehende Aktivierung im Hauptthread.
4. `_wait_for_telegram_decision` wartet auf ein Ereignis statt selbst zu pollen.
5. Prüfliste aller Schreibpfade auf Vorschläge und Mailzustände aus Abschnitt 3 abarbeiten.
6. Ohne Web und ohne Telegram (`telegram.enabled: false`, Einmalläufe mit `--max-mails`)
   bleibt der bisherige einthreadige Ablauf erhalten.

## 6. Nachweis in Schritt 0.6

- Tests mit Barrieren (kein `sleep()`): ein Web-Befehl wird ausgeführt, während eine
  Mailanalyse im Hauptthread an einer Barriere hängt.
- Gleichzeitiger Vorschlagsbau und Bestätigung desselben offenen Vorschlags: genau ein
  zulässiger Ausgang, keine verlorene Änderung (Vorgriff auf P5 in Stufe 6).
- Einstellungs- und Themenänderung während einer Mailverarbeitung wirkt erst beim
  nächsten Zyklus; die laufende Mail behält ihren Fingerprint.
- Messung im Log: Zeit vom Einreihen bis `command_finished` während eines Zyklus.

## 7. Umsetzung in 3.6.4

- `OperatorThread` (`operator_thread.py`) bedient `poll_once`, sobald die `TelegramInbox` neue
  Eingaben meldet oder die `CommandInbox` einen Befehl einreiht, sonst spätestens nach dem
  Abrufintervall; nach einem fehlgeschlagenen Telegram-Abruf wartet er höchstens 30 Sekunden.
  Er startet nach Empfänger und Weboberfläche, nur wenn ein Empfangs-Thread läuft, und wird
  vor der Weboberfläche und den Adaptern beendet; `Application.stop` weckt ihn.
- `TelegramDialogController.lock` (reentrant) umschließt `poll_once`, `send`, `send_relevance`,
  `send_proposal`, `flush_outbox` und `show_open_decisions`. Benachrichtigungen aus der
  Mailverarbeitung bleiben dadurch synchron und behalten ihre absturzsichere Buchführung;
  die Analyse sah dafür eine Warteschlange vor, die Sperre erhält aber die bestehende
  Reihenfolge und Fehlerbehandlung.
- `ConfigurationService` meldet Live-Einstellungen und Themen an `Application.request_settings`
  und `request_topics`; der Hauptthread übernimmt sie mit `_apply_requested_configuration`
  am Beginn jedes Zyklus.
- `_wait_for_telegram_decision` wartet auf `OperatorThread.served` statt selbst zu pollen.

**Prüfliste der Schreibpfade (Abschnitt 3):**

| Pfad | Ergebnis |
| :--- | :--- |
| Dialog aus Mailverarbeitung | Notifier-Aufrufe der Pipeline liegen außerhalb von `store.locked()`; der Abgleich ruft den Dialog nicht auf. Reihenfolge Dialog → Store ist eingehalten. |
| Vorschläge zusammenführen/speichern | `ProposalReconciliationService.merge` und `save` prüfen Version und offenen Status in `store.locked()`; ein inzwischen bestätigter Vorschlag wird nicht überschrieben. |
| Relevanzentscheidung | betrifft nur eine wartende Mail; der Hauptthread verarbeitet sie währenddessen nicht. |
| Neuprüfung (`recheck_mail`) | betrifft nur abgeschlossene Mails; die Wiederaufnahme lädt den Zustand danach neu. |
| Live-Einstellungen, Themen | nur im Hauptthread zwischen zwei Zyklen. |

## 8. Nachweis in 3.6.5

- `tests/services/test_operator_decoupling.py`: Der Hauptthread hängt an einem Ereignis mitten
  in einer Mailanalyse; eine im Browser bestätigte Aktion wird währenddessen vom Bedien-Thread
  ausgeführt und genau einmal extern angelegt. Eine während der Analyse gespeicherte
  Themenänderung wirkt erst beim nächsten Zyklus. Synchronisation nur über Ereignisse mit
  festen Zeitgrenzen; 20 aufeinanderfolgende Läufe ohne Fehlschlag.
- Offen: Messung im Betrieb – Zeit zwischen `web.command_submitted` und
  `review.command_finished` im Anwendungslog während eines laufenden Abrufzyklus.
