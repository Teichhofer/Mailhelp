# Mailhelp 6.4 – Wiederkehrende Fehler erkennen, begrenzen und bedienen

**Zielversion:** 6.4.0, Umsetzung in Patchversionen 6.4.1 bis 6.4.5

**Stand:** 14. November 2026

**Status:** Umsetzung beauftragt, Implementierung und Prüfung laufen.

**Präzisierung E1:** Die Abnahmegrenze von insgesamt fünf Versuchen hat Vorrang.
Zwischen diesen liegen vier Wartezeiten: 1 Minute, 5 Minuten, 30 Minuten und 2 Stunden.
Nach dem fünften Fehlschlag wird sofort aufgegeben; eine zusätzliche Wartezeit von
12 Stunden würde keinen weiteren Versuch auslösen und entfällt daher.

**Ausgangsstand:** 6.3.2 (nach [Planung 6.3.2](Planung-6.3.2.md))

**Grundlage:** [Entwicklungsregeln](../AGENTS.md), [Projektspezifikation](../Mailhelp-Projektspezifikation.md),
[Betrieb](Betrieb.md), [Fehlerbehebung](Fehlerbehebung.md)

---

## 0. Bestandsaufnahme

Der Fehler aus [Planung 6.3.2](Planung-6.3.2.md) lief vom 6. bis mindestens 13. November bei jedem
Zyklus, ohne dass es jemand bemerkte. 6.3.2 behebt diese eine Ursache. Dieser Plan sorgt dafür, dass
die **nächste** unbekannte Ursache nach Minuten auffällt statt nach einer Woche.

| ID | Befund | Nachweis |
| :--- | :--- | :--- |
| W1 | Eine fehlschlagende Wiederaufnahme wird bei jedem Zyklus ohne Pause wiederholt. Eine Wartezeit (`deferred_until`) setzt nur das Rate-Limit des Modellanbieters. | `mailbox_run.py`, `mail_pipeline.py` Zeile 519 |
| W2 | Jeder Fehlschlag schreibt zwei Fehlerzeilen, eine davon mit vollständigem Stacktrace: 6 937 Zeilen für eine einzige Ursache. | Protokolle 10.–13.11. |
| W3 | Rund 80 % aller Protokollzeilen sind Routinemeldungen: `messages_discovered` 183 809, `request` 24 460, `poll_started`/`poll_completed` je rund 7 700. `messages_discovered` wird je Ordner und Zyklus geschrieben, auch wenn sich nichts geändert hat. | Protokolle; `mailbox/imap.py` Zeilen 411, 418, 544 |
| W4 | Aufbewahrt werden 6 Dateien zu je 10 MB (`max_bytes`, `backup_count: 5`). Bei diesem Aufkommen sind das rund drei Tage; der Beginn des Fehlers war bereits herausrotiert. | `config/models.py`, `logs/` |
| W5 | Die Statusseite nennt „1 Mail mit Fehler“ mit Link ins Mailarchiv. Sie zeigt nicht, dass derselbe Fehler tausendfach wiederkehrt, seit wann, und bietet keine Aktion an. | `web/status_pages.py` |
| W6 | Für eine fehlgeschlagene Mail gibt es im Web keine Aktion. „Erneut prüfen“ existiert nur für aussortierte Mails (3.6.1). | `web/`, Suche nach Wiederholungsaktionen |
| W7 | Telegram meldet einen Verarbeitungsfehler einmal (`notification_marked_at`); eine Dauerwiederholung löst keine weitere Meldung aus. | Zustand der betroffenen Mail |

---

## 1. Ziele und Nichtziele

**Ziele**

1. Eine Mail, die wiederholt aus demselben Grund scheitert, wird in wachsenden Abständen und nach
   einer festen Zahl von Versuchen gar nicht mehr automatisch wiederholt.
2. Wiederkehrende Fehler erscheinen **einmal**, mit Zähler und „seit wann“ – im Protokoll, auf der
   Statusseite und einmalig in Telegram.
3. Der Betreiber kann eine aufgegebene Mail im Web bewusst erneut versuchen oder endgültig ablegen.
4. Die Protokolle reichen bei normalem Betrieb mindestens 30 Tage zurück, ohne mehr Platz zu
   brauchen.

**Nichtziele**

- Keine neue Überwachungsinfrastruktur, kein externer Dienst.
- Keine Änderung an Bestätigungen und Schreibzugriffen. Unklare Schreibergebnisse behalten ihren
  eigenen Abgleich; dieser Plan betrifft nur die Mailverarbeitung vor einer Bestätigung.
- Kein Versand von Protokollinhalten.

---

## 2. Entscheidungen

| ID | Frage | Vorschlag |
| :--- | :--- | :--- |
| **E1** | Wartezeiten und Obergrenze | 5 Versuche mit 1 min, 5 min, 30 min, 2 h, 12 h; danach „aufgegeben“. Gezählt wird je Mail und Fehlerbild (Schritt und Fehlercode). Ein anderes Fehlerbild oder eine geänderte Konfiguration beginnt neu. **Alternative:** 3 Versuche, wenn Modellkosten wichtiger sind als Selbstheilung. |
| **E2** | Was heißt „aufgegeben“? | Die Mail bleibt mit ihrem Fehler gespeichert, wird nicht mehr automatisch aufgenommen und erscheint auf der Statusseite unter „Handlungsbedarf“. Nichts wird gelöscht. |
| **E3** | Routinemeldungen | `messages_discovered` nur noch, wenn sich die Zahlen gegenüber dem letzten Eintrag desselben Ordners geändert haben, mindestens aber einmal pro Stunde als Lebenszeichen. `poll_started`/`poll_completed` zu einer Zeile je Zyklus zusammenfassen. Webanfragen (`request`) nur bei Status ab 400 oder Dauer über 1 s; alles über eine Einstellung wieder vollständig einschaltbar. |
| **E4** | Stacktraces | Vollständig beim ersten Auftreten eines Fehlerbilds je Prozesslauf; danach nur Fehlerbild und Zähler. |
| **E5** | Telegram | Eine Meldung beim Aufgeben („Mail … wird nicht weiter versucht: …“), keine bei den Zwischenversuchen. |

---

## 3. Maßnahmen

### 3.1 Versuchszähler und Wartezeit (W1)

- Der Mailzustand erhält je Fehlerbild: Zahl der Versuche, Zeitpunkt des ersten und des letzten
  Fehlschlags. Ältere Zustände ohne diese Felder bleiben gültig (Zähler 0).
- Nach einem Fehlschlag setzt die Wiederaufnahme `deferred_until` nach E1. Die Auswahl in
  `mailbox_run.py` überspringt zurückgestellte und aufgegebene Mails, **bevor** sie die Mail per
  IMAP abruft oder Budget verbraucht.
- Die Rate-Limit-Wartezeit des Anbieters bleibt unverändert und zählt nicht als Versuch.
- Ein Erfolg löscht Zähler und Wartezeit.

### 3.2 Fehler zusammenfassen (W2, E4)

- Der Logger erhält eine Stelle, die Fehlerereignisse nach Fehlerbild (Modul, Ereignis, Schritt,
  Fehlercode, Mail) zusammenfasst: erste Zeile vollständig, Folgezeilen als `repeated` mit Zähler,
  spätestens alle 15 Minuten eine Sammelzeile.
- Zugangsdaten und Mailinhalte bleiben wie bisher aus den Protokollen heraus.

### 3.3 Weniger Routinezeilen, längere Historie (W3, W4, E3)

- Umsetzung von E3 in `mailbox/imap.py`, im Abrufzyklus und im Webserver.
- Neue Einstellung „Ausführliches Protokoll“ (Standard aus) in `config.yaml`, in der Weboberfläche
  unter den Protokolleinstellungen, in `config.example.yaml` und der Einstellungshilfe.
- Messung vor und nach der Umstellung an einem synthetischen Tageslauf: Ziel höchstens 2 MB je Tag
  im Leerlauf mit den Postfächern des Testszenarios (im echten Betrieb heute rund 20 MB). `max_bytes` und `backup_count` bleiben.

### 3.4 Statusseite und Mailarchiv (W5, W6)

- **Status:** „Handlungsbedarf“ nennt aufgegebene Mails einzeln: Betreff, Schritt in Worten,
  „seit 06.11., 5 Versuche“, Link zum Maildetail. Laufende Wiederholungen stehen darunter als
  „wird erneut versucht (3 von 5, nächster Versuch 14:30 Uhr)“.
- **Maildetail** einer fehlgeschlagenen Mail: zwei Aktionen über `/aktion` mit Sitzung, CSRF,
  Analyserunde als Version und Idempotenzschlüssel, wie bei „Erneut prüfen“:
  - **Erneut versuchen** setzt Zähler und Wartezeit zurück; die nächste Wiederaufnahme nimmt die
    Mail auf.
  - **Ablegen** beendet die Mail dauerhaft als „nicht verarbeitet“; sie zählt nicht mehr als
    Handlungsbedarf und bleibt im Archiv auffindbar.
- Beide Aktionen ändern nur den Mailzustand; es gibt keinen externen Schreibzugriff.
- Verlauf: Ereignisse „erneut versucht“ und „abgelegt“ mit Akteur.

### 3.5 Telegram (W7, E5)

- Eine Meldung beim Aufgeben, mit Link zum Maildetail (bevorzugte Domain nach 6.2.5).
- `/status` nennt die Zahl aufgegebener Mails.

---

## 4. Umsetzungsschritte

| Schritt | Patch | Arbeitspaket | Tests |
| :--- | :--- | :--- | :--- |
| D1 | 6.4.1 | Versuchszähler, Wartezeiten, Aufgeben (3.1) | Folge der Wartezeiten mit gestellter Uhr; kein IMAP-Abruf und kein Budget während der Wartezeit; Neustart mitten in der Folge; anderes Fehlerbild beginnt neu; Erfolg setzt zurück; alter Zustand ohne Felder; Rate-Limit zählt nicht |
| D2 | 6.4.2 | Fehler zusammenfassen (3.2) | Erster Fehler vollständig, 100 Wiederholungen ergeben höchstens eine Sammelzeile je Fenster; zwei Fehlerbilder getrennt; keine Zugangsdaten |
| D3 | 6.4.3 | Routinezeilen und Einstellung (3.3) | Unveränderte Zahlen schreiben nichts, Änderung schreibt, Lebenszeichen nach einer Stunde; ausführlicher Modus wie bisher; Messung des Tagesvolumens als Test mit Obergrenze |
| D4 | 6.4.4 | Statusseite, Maildetail-Aktionen, Verlauf, Telegram (3.4, 3.5) | Aktionen: Erfolg, veraltete Runde (409), abgelaufene und bei Ausführung widerrufene Sitzung, CSRF, doppelter Klick; Neustart zwischen Annahme und Ausführung; Browsertests Desktop und Telefon; Telegram-Meldung genau einmal |
| D5 | 6.4.5 | Doku, Abnahme, `docs/Release-6.4.md` | `python -m devtools.check full`, vollständige Browser-Suite |

D1 ist allein auslieferbar und beseitigt das Kernrisiko. D2 und D3 sind voneinander unabhängig.

---

## 5. Abnahmekriterien

- Eine Mail, die immer gleich scheitert, wird innerhalb von 24 Stunden höchstens fünfmal versucht
  und danach nicht mehr.
- Dieselbe Störung erzeugt in 24 Stunden höchstens 120 Protokollzeilen (heute rund 2 300).
- Leerlauf im Testszenario: höchstens 2 MB Protokoll je Tag; am echten Bestand nach einer Woche nachgemessen.
- Statusseite und Telegram nennen eine aufgegebene Mail mit Schritt und Beginn; beide Aktionen
  funktionieren mit und ohne JavaScript.
- 100 % Zeilen- und Branch-Abdeckung, 100 % JavaScript-Blockabdeckung.

## 6. Risiken

| Risiko | Gegenmaßnahme |
| :--- | :--- |
| Eine vorübergehende Störung (Anbieter für einen Tag nicht erreichbar) führt zu vielen aufgegebenen Mails. | Netzwerk- und Anbieterfehler zählen nach E1 mit den langen Stufen; „Erneut versuchen“ für alle aufgegebenen Mails eines Fehlerbilds in einer Aktion. |
| Weniger Protokoll erschwert die Fehlersuche. | Einstellung „Ausführliches Protokoll“; erster Fehler bleibt vollständig. |
| Zusammenfassen verschluckt einen zweiten, ähnlichen Fehler. | Fehlerbild enthält Schritt, Code und Mail; unterschiedliche Stacktraces gelten als verschiedene Fehlerbilder. |

## 7. Dokumentation

`README.md`, `CHANGELOG.md`, `docs/Betrieb.md` (Protokollumfang, Einstellung), `docs/Fehlerbehebung.md`
(aufgegebene Mails), `docs/Bedienung.md` (Aktionen im Maildetail, Hilfeindex neu erzeugen),
Projektspezifikation, `config.example.yaml`.
