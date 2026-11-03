# Entkopplung von Bedienung und Mailabruf – Analyse

**Stand:** 3. November 2026 (Version 3.6.3)  
**Zweck:** Grundlage für [Planung 3.6](Planung-3.6.md), Schritte 0.5 (Arbeitsthread) und 0.6 (Nachweis)  
**Status:** Analyse; noch keine Verhaltensänderung

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
