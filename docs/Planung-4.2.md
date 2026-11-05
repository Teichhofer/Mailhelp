# Mailhelp 4.2 – Reaktionsschnelle Web-Aktionen

**Zielversion:** 4.2.0 (Schritte als Patchversionen 4.2.x)  
**Stand:** 5. November 2026  
**Status:** In Planung  
**Grundlage:** [Entwicklungsregeln](../AGENTS.md), [Projektspezifikation](../Mailhelp-Projektspezifikation.md), [Planung 4.0](Planung-4.0.md) (Gesamtfahrplan)  
**Vorgänger:** [Planung 4.1](Planung-4.1.md)

---

## 1. Anlass und Ziel

> **„Eine im Browser gewählte Aktion beginnt innerhalb einer Sekunde, auch während eine Mail analysiert wird oder Telegram-Nachrichten versendet werden.“**

Nach der Auswahl einer Aktion zeigt die Weboberfläche oft mehrere Sekunden lang „Wird
ausgeführt … Mailhelp bearbeitet die Aktion, sobald die aktuelle Mail analysiert ist.“

**Befund vom 5. November 2026** (Produktionslog, 13 Web-Aktionen, und Messung auf einer
Kopie der Zustandsablage mit 1.532 Mails und 403 Vorschlägen):

| Messgröße | Wert |
| :--- | :--- |
| Wartezeit vom Absenden bis zum Ausführungsbeginn | 1,3–5,8 s |
| Ausführung (Verwerfen / Bestätigen mit externer Anlage) | 0,3–0,6 s / 4–6 s |
| Antwortzeit der Statusseite `/aktion/<id>`, die sich jede Sekunde neu lädt | 1,5–2,6 s |
| Lesezugriffe der Ablage (`recover()`, `current()`, Startseite) | je etwa 0,1 s |
| `views.system()` | 0,6 s |

**Ursachen:**

1. **Der Text ist veraltet.** Seit 3.6.4 führt der eigene Bedien-Thread (`mailhelp-operator`)
   Web-Befehle aus. Er wartet nicht auf das Ende der Mailanalyse, und die LLM-Aufrufe der
   Analyse laufen ohne Sperre. Ein zusätzlicher Thread würde deshalb wenig bringen.
2. **Die Sperre des Telegram-Dialogs wird über Netzwerkaufrufe gehalten.** Die Mailanalyse
   sendet Vorschläge, Rückfragen und Hinweise unter `TelegramDialogController.lock`
   (`send`, `send_proposal`, `send_relevance`, `flush_outbox`). Jede Nachricht dauert rund
   0,3 s, und so lange wartet der Bedien-Thread. Umgekehrt hält der Bedien-Thread die Sperre
   für seinen ganzen Durchlauf in `poll_once`.
3. **Web-Befehle stehen hinten in der Reihe.** `poll_once` arbeitet vor `_process_commands`
   zuerst `write_executor.resume()`, `revisions.resume()` und die Telegram-Eingaben ab und
   versendet danach unter derselben Sperre die Outbox.
4. **Die Statusseite erzeugt selbst Last.** Jede Sekunde wird die ganze Seite neu gerendert.
   Jedes Neuladen wartet auf die Sperre der Zustandsablage und reiht sich damit hinter den
   anderen Threads ein.

Einen einzelnen großen Blocker konnte die Stichprobe nicht live erfassen, weil während der
Messung keine Mailanalyse lief. Schritt 10.1 belegt deshalb im Betrieb, wie sich die
Wartezeit auf die einzelnen Ursachen aufteilt, bevor die Schritte 10.2–10.5 sie beseitigen.

Unverändert gilt: Jede externe Anlage braucht die ausdrückliche, versionsgebundene
Bestätigung. Web-Befehle führt weiterhin genau ein Thread in Eingangsreihenfolge aus,
mit Idempotenzschlüssel und erneuter Sitzungsprüfung.

---

## 2. Umsetzungsschritte (Stufe 10)

Es gelten die Regeln aus [Planung 4.0, Abschnitt 5.1](Planung-4.0.md#51-regeln-für-die-schritte):
Jeder Schritt wird als eigener Commit mit Patchversion geliefert, hat den Umfang S (≤ 1 Tag)
oder M (≤ 2 Tage) und erhält die 100-%-Abdeckung. Jede Verhaltensänderung bekommt Tests;
jede Beseitigung einer Wartezeit einen Regressionstest, der vor der Änderung scheitert.

| Schritt | Inhalt | Fertig, wenn … | Umfang | Voraussetzung |
| :--- | :--- | :--- | :---: | :--- |
| **10.1** | Wartezeiten messen | `command_finished` enthält neben `latency_ms` und `execution_ms` die Wartezeit in der Warteschlange und je Sperre (`dialog_lock_wait_ms`, `store_lock_wait_ms`), ohne Inhalte zu protokollieren; `/status` zeigt Median und Maximum der letzten Web-Aktionen. | S | – |
| **10.2** | Telegram-Versand ohne Dialogsperre | Unter der Dialogsperre werden Nachrichten nur in die dauerhafte Outbox eingetragen; der Versand läuft danach ohne Dialogsperre. Reihenfolge, Outbox-Sperren (Rückfragen) und Absturzsicherheit bleiben erhalten. Regressionstest: Eine Web-Aktion beginnt, während ein simulierter Telegram-Versand hängt. | M | 10.1 |
| **10.3** | Web-Befehle zuerst | `poll_once` führt wartende Web-Befehle vor den Wiederaufnahmen und dem Outbox-Versand aus; nach Neustarts werden unterbrochene Befehle weiterhin zuerst abgeglichen. Regressionstest: Ein wartender Befehl beginnt vor einer langen Wiederaufnahme. | S | 10.2 |
| **10.4** | Schlanke Statusabfrage | `/api/aktion/<id>` liefert nur Status und Ziel aus dem Befehlseingang (Sitzungsprüfung bleibt); die Statusseite fragt diesen Endpunkt ab, statt sich jede Sekunde ganz neu zu laden. Ohne JavaScript bleibt das Neuladen der Seite als Rückfall erhalten. | S | – |
| **10.5** | Hinweistext und Rückmeldung | Der Text lautet „Wird ausgeführt … Danach geht es automatisch zur Übersicht.“; dauert eine Bestätigung wegen externer Anlage länger, nennt die Seite das Ziel (Kalender oder Todoist). Browsertests für Desktop, Mobilgerät und ohne JavaScript. | S | 10.4 |
| **10.6** | Abnahme Reaktionszeit | Simulierter Lastlauf (laufende Mailanalyse, Telegram-Versand, Benachrichtigungen, fünf gleichzeitige Browser) unter Windows, Linux und Docker: Ausführungsbeginn im Median unter 0,5 s, im Maximum unter 1 s; keine doppelten oder unberechtigten Aktionen; Release-Bericht `docs/Release-4.2.md`. | M | 10.1–10.5 |

**Umfangsübersicht:** 6 Schritte, davon 4 S und 2 M.

---

## 3. Abnahmekriterien

1. **Reaktionszeit:** Eine Web-Aktion beginnt im Median nach weniger als 0,5 s und im
   Maximum nach weniger als 1 s, auch während Mailanalyse und Telegram-Versand.
2. **Keine Netzwerkaufrufe unter gemeinsamen Sperren:** Weder die Dialogsperre noch die
   Sperre der Zustandsablage wird über Telegram-, Push-, LLM- oder Zielanbieteraufrufe gehalten.
3. **Unveränderte Sicherheit:** Versionsbindung, CSRF, Idempotenz, erneute Sitzungsprüfung
   und Abgleich unklarer Schreibresultate bleiben bestehen; die Prozessabbruch- und
   Konkurrenzszenarien aus 3.6 (A1–A7, P1–P7) bestehen weiterhin.
4. **Belegbarkeit:** Wartezeiten je Ursache stehen im Log und auf `/status`.
5. **Abdeckung:** 100 % Zeilen- und Branch-Abdeckung ohne Ausschlüsse.
