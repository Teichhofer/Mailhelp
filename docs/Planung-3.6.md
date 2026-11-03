# Mailhelp 3.6 – Fundament und Absicherung

**Zielversion:** 3.6.0 (Schritte als Patchversionen 3.6.x)
**Stand:** 3. November 2026
**Status:** In Planung
**Ausgangsstand:** 3.5.9
**Grundlage:** [Entwicklungsregeln](../AGENTS.md), [Projektspezifikation](../Mailhelp-Projektspezifikation.md), [Planung 4.0](Planung-4.0.md) (Gesamtfahrplan), [Planung 3.5](Planung-3.5.md)
**Nachfolger:** [Planung 3.7](Planung-3.7.md)

---

## 1. Ziel

3.6 behebt bekannte Mängel, entkoppelt Web-Aktionen vom Mailabruf und sichert die
bestehenden Abläufe gegen gleichzeitige Bedienung und harte Prozessabbrüche ab, bevor
3.7 und 4.0 neue Einstiegspunkte hinzufügen. Für Nutzer sichtbar sind nur „Erneut prüfen“
für aussortierte Mails und schnellere Web-Aktionen während eines Abrufs.

## 2. Umfang

| Stufe | Inhalt | Schritte |
| :--- | :--- | :--- |
| 0 | Vorarbeiten: Startmeldung, „Erneut prüfen“, Entkopplung, mypy für `web.*`, Paketbündelung | 10 |
| 1 | Testgrundlage (Q1) | 5 |
| 6 | Parallelbedienung (Q2, Priorität 1) | 8 |
| 7 | Prozessabbrüche (Q3, Priorität 2) | 8 |

Es gelten die Regeln aus [Planung 4.0, Abschnitt 5.1](Planung-4.0.md#51-regeln-für-die-schritte):
jeder Schritt einzeln lieferbar mit eigener Patch-Version, Umfang S (≤ 1 Tag) oder M (≤ 2 Tage),
zu große Schritte werden vor dem Weiterarbeiten geteilt. Schrittnummern sind über alle drei
Pläne eindeutig.

## 3. Schritte

### 3.1 Stufe 0 – Vorarbeiten

Diese Schritte beheben bekannte Mängel und schaffen Voraussetzungen, ohne Funktionen aus
3.7 oder 4.0 vorwegzunehmen.

| Schritt | Inhalt | Fertig, wenn … | Umfang | Voraussetzung |
| :--- | :--- | :--- | :--- | :--- |
| 0.1 ✓ 3.6.0 | Fehlende `config.yaml` beim Start | Statt Traceback eine verständliche Meldung mit Hinweis auf `config.example.yaml` und Exitcode ≠ 0; Regressionstest. | S | – |
| 0.2 ✓ 3.6.1 | „Erneut prüfen“: Backend | Ein Befehl setzt eine als irrelevant abgeschlossene Mail kontrolliert auf die Relevanzprüfung zurück und verarbeitet sie mit der aktuellen Konfiguration neu; Checkpoints, Dublettenschutz und Verlauf bleiben konsistent; Wiederholung ist idempotent. | M | – |
| 0.3 ✓ 3.6.2 | „Erneut prüfen“: Web | Schaltfläche in Maildetail und Archiv mit Sitzung, CSRF, Versionsprüfung und Idempotenzschlüssel; Ergebnis im Verlauf sichtbar. | S | 0.2 |
| 0.4 ✓ 3.6.3 | Entkopplung B1: Analyse ([Analyse](Entkopplung-Web-und-Abruf.md)) | Gemeinsam genutzter Zustand von Abrufzyklus und Review-Befehlen dokumentiert (Store-Sperren, Ledger, Telegram-Dialog); Liste der nötigen Sperren und Reihenfolgen. | S | – |
| 0.5 ✓ 3.6.4 | Entkopplung B2: Arbeitsthread | Web-Befehle laufen in einem eigenen Arbeitsthread statt im Abrufzyklus; ein laufender LLM-Aufruf verzögert Web-Aktionen nicht mehr. | M | 0.4 |
| 0.6 (Tests ✓ 3.6.5, Messung im Betrieb offen) | Entkopplung B3: Nachweis | Tests für gleichzeitigen Abruf und Web-Befehl (ohne `sleep()`); gemessene Antwortzeiten während eines Zyklus im Log belegt. | S | 0.5 |
| 0.7 ✓ 3.6.6 | mypy strikt für `web.*` (Teil 1) | Seiten- und Formularmodule (`pages`, `forms`, `*_pages.py`) bestehen die strikte Prüfung. | M | – |
| 0.8a ✓ 3.6.7 | mypy strikt für `web.*` (Teil 2a) | Aktionen, Archiv, Verlauf, Bearbeiten, Beenden, Zugangsdaten, Kontenstatus und Einstellungen bestehen die strikte Prüfung. | M | 0.7 |
| 0.8b ✓ 3.6.8 | mypy strikt für `web.*` (Teil 2b) | Einrichtung, Postfächer, Postfach hinzufügen und IServ bestehen die strikte Prüfung (rund 110 Befunde). | M | 0.8a |
| 0.8c ✓ 3.6.9 | mypy strikt für `web.*` (Teil 2c) | Tätigkeitsberichte, Benachrichtigungen, Absender, Abgleich, Übersicht und `site.py` bestehen die strikte Prüfung; `pyproject.toml` erzwingt `mailhelp.web.*` dauerhaft. | M | 0.8b |
| 0.9 ✓ 3.6.10 | Paketbündelung: Zuordnung ([Paketstruktur](Paketstruktur.md)) | Zielstruktur der über 50 Wurzelmodule festgelegt (z. B. `imap/`, `mailbox/`, `notifications/`, `proposals/`), Kompatibilitätsimporte entschieden. | S | – |
| 0.10a ✓ 3.6.11 | Paketbündelung: `mailhelp.mailbox` | Abruf, Postfächer und IServ umgezogen; Prüfung nach [Paketstruktur](Paketstruktur.md), Abschnitt 4. | S | 0.9 |
| 0.10b ✓ 3.6.12 | Paketbündelung: `mailhelp.processing` | Verarbeitung einer Mail umgezogen. | S | 0.10a |
| 0.10c ✓ 3.6.13 | Paketbündelung: `mailhelp.proposals` | Vorschläge, Abgleich und Ziele umgezogen. | S | 0.10b |
| 0.10d ✓ 3.6.14 | Paketbündelung: `mailhelp.llm` | Sprachmodelle, Lernen und Bewertung umgezogen; `mailhelp-evaluate` umgestellt. | S | 0.10c |
| 0.10e | Paketbündelung: `mailhelp.notifications` | Benachrichtigungen, Push, Tagesüberblick und Entwürfe umgezogen. | S | 0.10d |
| 0.10f | Paketbündelung: `mailhelp.runtime` | Betrieb, Lebenszyklus, Einrichtung und Wartung umgezogen. | S | 0.10e |

### 3.2 Stufe 1 – Testgrundlage (Q1)

Q1 kommt vor Q2/Q3 (Abschnitt 4); die Infrastruktur wird außerdem in 3.7 und 4.0 genutzt.

| Schritt | Inhalt | Fertig, wenn … | Umfang | Voraussetzung |
| :--- | :--- | :--- | :--- | :--- |
| 1.1 | Zustandsregeln Review und Command-Inbox | Übergänge, Persistenzgrenzen und der Zeitpunkt, ab dem eine konkurrierende Entscheidung verbindlich ist, in der Spezifikation dokumentiert. | S | – |
| 1.2 | Zustandsregeln Schreibausführung, Ledger, Merge-Journal | Wie 1.1 für Schreibauftrag, Ledger und Merge; beide Reihenfolgen konkurrierender Entscheidungen beschrieben. | S | 1.1 |
| 1.3 | Teststeuerung mit Barrieren | Wiederverwendbare Haltepunkte (Events/Barrieren) mit festen Zeitgrenzen und Aufräumen bei Fehlern; unter Windows und Linux lauffähig. | M | – |
| 1.4 | Persistenter Simulationsdienst | Simulierter externer Dienst mit eigener, prozessunabhängiger Ablage und Aufrufhistorie; kann eine Änderung übernehmen und die Antwort zurückhalten oder abbrechen. | M | – |
| 1.5 | Unterprozess-Harness | Anwendungsablauf im Unterprozess startbar, an benannten Punkten hart beendbar (kein Exception-Abbruch), Coverage der Unterprozesse wird erfasst. | M | 1.3 |

### 3.3 Stufe 6 – Parallelbedienung (Q2)

Je Szenario aus Abschnitt 4, Q2, ein Schritt mit beiden Reihenfolgen, Prüfung von Version,
Status, Command-Inbox, Journal/Ledger und Nutzerrückmeldung sowie gültigen, fehlenden,
falschen und sitzungsfremden CSRF-Tokens.

| Schritt | Szenario | Umfang | Voraussetzung |
| :--- | :--- | :--- | :--- |
| 6.1 | P1 Web und Telegram bestätigen dieselbe Version | S | 1.2, 1.3, 1.4 |
| 6.2 | P2 Zwei Websitzungen mit unterschiedlichen Idempotenzschlüsseln | S | 6.1 |
| 6.3 | P3 Bearbeiten gegen Bestätigen | M | 6.1 |
| 6.4 | P4 Verwerfen gegen Bestätigen | S | 6.1 |
| 6.5 | P5 Merge gegen Bestätigen | M | 6.1 |
| 6.6 | P6 Sitzung widerrufen oder abgelaufen vor Ausführung | S | 6.1 |
| 6.7 | P7 Wiederholte identische Anfragen | S | 6.1 |
| 6.8 | Browsertest mit zwei Kontexten (sichtbare Konfliktmeldung) | S | 6.3 |

### 3.4 Stufe 7 – Prozessabbrüche (Q3)

Je Abbruchpunkt ein Schritt: harter Abbruch im Unterprozess (1.5), Neustart mit
unverändertem Simulationszustand (1.4), zweiter Neustart zum Nachweis der Idempotenz.
Bei A1–A4 zusätzlich Abgleich mit Treffer, ohne Treffer, mit temporärem Fehler und mit
ungültiger Antwort.

| Schritt | Abbruchpunkt | Umfang | Voraussetzung |
| :--- | :--- | :--- | :--- |
| 7.1 | A1 Schreibauftrag gespeichert, Aufruf nicht begonnen | S | 1.2, 1.4, 1.5 |
| 7.2 | A2 Änderung übernommen, Antwort zurückgehalten | M | 7.1 |
| 7.3 | A3 Antwort empfangen, Ergebnis nicht gespeichert | S | 7.1 |
| 7.4 | A4 Ergebnis gespeichert, Journal/Ledger unvollständig | S | 7.1 |
| 7.5 | A5 Merge-Journal gespeichert, Vorschlag nicht aktualisiert | S | 1.5 |
| 7.6 | A6 Vorschlag gespeichert, Aliasakte fehlt | S | 7.5 |
| 7.7 | A7 Vorschlag und Aliasakte gespeichert, Journal offen | S | 7.5 |
| 7.8 | Beschädigte oder fehlende maßgebliche Akten | S | 7.1 |

**Umfangsübersicht:** 31 Schritte, davon 21 S und 10 M; 0.10 wird je Zielpaket weiter geteilt.

## 4. Testausbau: Parallelbedienung und Absturzsicherheit

### Ziel und Umfang

Zusätzlich zu den Browserfunktionen erhält Version 4.0 reproduzierbare Tests für das
Zusammenspiel von Web, Telegram, Vorschlagsversionen, externen Schreibaktionen und
persistiertem Zustand. Vorhandene Tests für Wiederholungen, Sitzungsprüfung,
Schreibunsicherheit und Merge-Journale werden erweitert und nach Möglichkeit wiederverwendet.
Dieser Abschnitt beschreibt geplante Arbeit, keine bereits nachgewiesene Absicherung.

Alle Tests verwenden synthetische Daten und simulierte externe Dienste. Produktivkonten,
echte Zugangsdaten und externe Produktivzugriffe sind ausgeschlossen.

### Q1: Zustandsregeln und Testinfrastruktur festlegen

1. Die verbindlichen Zustandsübergänge und Persistenzgrenzen in Review, Command-Inbox,
   Schreibausführung, Ledger und Merge-Journal erfassen. Insbesondere festlegen, wann
   eine konkurrierende Entscheidung verbindlich wird und wann eine Aktion bereits läuft.
2. Erwartete Ergebnisse für beide Reihenfolgen konkurrierender Entscheidungen in der
   Projektspezifikation dokumentieren. Bereits laufende Schreibaktionen dürfen nicht
   durch eine nachträgliche Bearbeitung oder Verwerfung scheinbar rückgängig gemacht werden.
3. Eine wiederverwendbare Teststeuerung mit Events oder Barrieren einrichten.
   Zeitabhängige Zufallstests und `sleep()` als Synchronisation sind unzulässig.
   Warteoperationen erhalten feste Zeitgrenzen; Fehler müssen Prozesse und Ressourcen aufräumen.
4. Einen simulierten externen Dienst bereitstellen, dessen Einträge und Aufrufhistorie
   unabhängig vom Anwendungsprozess erhalten bleiben. Er muss eine Änderung übernehmen
   und die Antwort anschließend gezielt zurückhalten oder abbrechen können.

**Abnahme:** Die Synchronisationspunkte, erwarteten Zustandsübergänge und verwendeten
Testhilfen sind dokumentiert. Die Infrastruktur funktioniert unter Windows und Linux.

### Q2: Gleichzeitige Bedienung absichern (Priorität 1)

Integrationstests an den tatsächlichen Web- und Telegram-Einstiegspunkten ergänzen.
Die Ausführung der wartenden Befehle und die externe Schreibgrenze müssen enthalten sein.
Die Betriebssperre nicht umgehen; konkurrierende Oberflächen innerhalb einer laufenden
Instanz prüfen. Bei zwei konkurrierenden Entscheidungen beide Reihenfolgen erzwingen.

| ID | Szenario | Erwartetes Ergebnis |
| :--- | :--- | :--- |
| P1 | Web und Telegram bestätigen dieselbe Version. | Höchstens eine externe Aktion; die zweite Bestätigung erzeugt keine weitere Anlage. |
| P2 | Zwei Websitzungen bestätigen dieselbe Version mit unterschiedlichen Idempotenzschlüsseln. | Auch unterschiedliche Anfrageschlüssel umgehen die fachliche Dublettensperre nicht. |
| P3 | Eine Oberfläche bearbeitet, die andere bestätigt die bisherige Version. | Gewinnt die Bearbeitung, ist die alte Freigabe ungültig; gewinnt die Ausführung, bleibt die Änderung gemäß Zustandsregeln gesperrt oder ausdrücklich separat prüfbar. |
| P4 | Eine Oberfläche verwirft, die andere bestätigt. | Nur ein zulässiger Zustandsübergang gewinnt; eine bereits verworfene Version wird nicht ausgeführt. |
| P5 | Ein Merge konkurriert mit der Bestätigung einer beteiligten bisherigen Version. | Alias, kanonische Version und Freigabe bleiben konsistent; laufende Aktionen werden nicht überschrieben. |
| P6 | Eine angenommene Webaktion wartet; die Sitzung wird vor Ausführung widerrufen oder läuft ab. | Erneute Sitzungsprüfung verhindert die externe Aktion und liefert ein nachvollziehbares Ergebnis. |
| P7 | Identische Anfragen werden während der Verarbeitung und nach Abschluss wiederholt. | Wiederholungen führen zu keiner weiteren externen Aktion; Ergebnis und Status bleiben nachvollziehbar. |

Für jedes Szenario zusätzlich gespeicherte Vorschlagsversion, Status, Command-Inbox,
vorhandene Journal-/Ledger-Einträge und das Ergebnis für den Nutzer prüfen. An den
Web-Einstiegspunkten gültige sowie fehlende, falsche und sitzungsfremde CSRF-Tokens
berücksichtigen. Bearbeiten oder Speichern allein darf keine externe Anlage autorisieren.
Ein zusätzlicher Browsertest mit zwei getrennten Browserkontexten prüft die sichtbare
Konfliktrückmeldung; die deterministischen Integrationstests bleiben maßgeblich.

**Abnahme:** Alle P-Szenarien bestehen reproduzierbar. Keine aktuelle manuelle Änderung
geht verloren, kein veralteter Vorschlag wird freigegeben und keine nicht mehr gültige
Websitzung autorisiert die Ausführung.

### Q3: Echte Prozessabbrüche und Wiederherstellung prüfen (Priorität 2)

Den betroffenen Anwendungsablauf in einem Unterprozess ausführen und an folgenden
kontrollierten Punkten hart beenden. Eine bloß ausgelöste Python-Exception genügt nicht,
da sie reguläre Aufräumlogik ausführen kann.

| ID | Abbruchpunkt |
| :--- | :--- |
| A1 | Schreibauftrag dauerhaft gespeichert, externer Aufruf noch nicht begonnen. |
| A2 | Externer Dienst hat die Änderung übernommen, Antwort wird noch zurückgehalten. |
| A3 | Erfolgreiche Antwort empfangen, Ergebnis lokal noch nicht gespeichert. |
| A4 | Vorschlagsergebnis gespeichert, weitere Journal-/Ledger-Einträge noch nicht abgeschlossen, soweit diese getrennt geschrieben werden. |
| A5 | Merge-Journal gespeichert, kanonischer Vorschlag noch nicht aktualisiert. |
| A6 | Kanonischer Vorschlag gespeichert, Aliasakte noch nicht gespeichert. |
| A7 | Kanonischer Vorschlag und Aliasakte gespeichert, Merge-Journal noch nicht abgeschlossen. |

Nach jedem Abbruch einen frischen Anwendungsprozess mit demselben Datenverzeichnis
und unverändertem simuliertem externem Zustand starten. Anschließend mindestens einen
weiteren Neustart durchführen, um die Idempotenz der Wiederherstellung zu prüfen.
Bei A1–A4 außerdem Abgleich mit Treffer, ohne Treffer, mit temporärem Fehler und mit
ungültiger Antwort berücksichtigen, soweit der jeweilige Ablauf einen Abgleich benötigt.

Verbindliche Prüfungen:

- Bereits ausgeführte Aktionen werden erkannt und nicht erneut angelegt.
- Unklare Resultate bleiben geschützt, bis ein belastbarer Abgleich möglich ist.
  Ein fehlgeschlagener oder ergebnisloser Abgleich allein beweist keine ausgebliebene Anlage.
- Noch nicht ausgeführte Aktionen erfolgen nur mit weiterhin gültiger Autorisierung;
  der Neustart ersetzt weder Sitzungs- noch Versionsprüfung oder ausdrückliche Freigabe.
- Lokale Wiederherstellung vervollständigt fehlende Schritte idempotent. Eine weitere
  Wiederherstellung verändert ein bereits konsistentes Ergebnis nicht erneut.
- Merge-Wiederherstellung erhält Quellen und geschützte manuelle Werte. Zwischenzeitlich
  geänderte maßgebliche Akten werden nicht überschrieben; Konflikte bleiben sichtbar.
- Beschädigte oder fehlende maßgebliche Akten werden nicht als leerer Bestand behandelt,
  der eine neue externe Anlage erlauben würde.

**Abnahme:** Alle A-Szenarien bestehen unter Windows und Linux. Die unabhängig
gespeicherte externe Aufrufhistorie belegt, dass keine zusätzliche Schreibaktion erfolgt.
Nicht vorhandene Persistenzgrenzen werden begründet dokumentiert, nicht künstlich eingeführt.

## 5. Abnahme

- Alle Schritte aus Abschnitt 3 sind mit Version markiert.
- Q1 ist dokumentiert; P1–P7 und die Abbruchpunkte aus 7.1–7.8 bestehen reproduzierbar unter
  Windows und Linux.
- Web-Aktionen während eines Abrufzyklus warten nicht mehr auf die Mailverarbeitung (Nachweis aus 0.6).
- 100 % Zeilen- und Branch-Abdeckung, `ruff` und `mypy` (einschließlich `web.*` strikt) ohne Befund.
