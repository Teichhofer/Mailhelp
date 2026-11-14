# Mailhelp 6.6 – Angelegte Einträge wieder entfernen

**Zielversion:** 6.6.0, Umsetzung in Patchversionen 6.6.1 bis 6.6.5

**Stand:** 14. November 2026

**Status:** Umsetzung beauftragt. E1 am 14.11.2026 entschieden: zehn Minuten. E2 entschieden: immer zwei Bestätigungsschritte im Web und in Telegram.

**Ausgangsstand:** 6.5.x; fachlich unabhängig von 6.4 und 6.5

**Grundlage:** [Entwicklungsregeln](../AGENTS.md), [Projektspezifikation](../Mailhelp-Projektspezifikation.md),
[Planung 6.3](Planung-6.3.md), [Release 5.2](Release-5.2.md) (Kontrollabruf nach dem Schreiben)

---

## 0. Bestandsaufnahme

| ID | Befund | Nachweis |
| :--- | :--- | :--- |
| R1 | Bestätigen sendet sofort; die frühere Rückhaltefrist von 5 Sekunden gibt es nicht mehr. Seit 6.3 genügt dafür ein Wisch. | `static/app.js`, [Release 6.3](Release-6.3.md) |
| R2 | Ein versehentlich angelegter Eintrag lässt sich nur außerhalb von Mailhelp entfernen (Google Kalender, Todoist). Mailhelp führt den Vorschlag danach weiter als „angelegt“. | `external/contracts.py`: nur `create`, `reconcile`, `prepare` |
| R3 | Für den Kalender existiert bereits ein geprüfter Weg, einen vorhandenen Termin abzusagen (Terminabsage seit 4.6, mit Kontrollabruf „nicht mehr aktiv“ seit 5.2). | `external/calendar.py`: `_prepare_target`, `CANCELLED` |
| R4 | Für Todoist gibt es keinen Weg, eine Aufgabe zu schließen oder zu löschen. | `external/todoist.py` |
| R5 | Per Telegram gesendete Kalenderdateien und simulierte Einträge (Testmodus) lassen sich grundsätzlich nicht zurückholen. | Zielarten in `review/views.py` |

**Warum eine eigene Aktion und keine Rückhaltefrist:** Eine Frist verzögert jede Entscheidung, auch
die richtige, und sperrt in der geteilten Ansicht so lange die Auswahl. Entfernen nach dem Anlegen
kostet nur dann etwas, wenn tatsächlich ein Fehler passiert ist.

---

## 1. Ziele und Nichtziele

**Ziele**

1. Ein von Mailhelp angelegter Kalendereintrag oder eine angelegte Aufgabe lässt sich aus Mailhelp
   heraus wieder entfernen – im Web und in Telegram.
2. Entfernen ist ein eigener externer Schreibzugriff und erfüllt dieselben Regeln wie Anlegen:
   ausdrückliche, versionsbezogene Bestätigung, Idempotenz, Abgleich unklarer Ergebnisse,
   Kontrollabruf.
3. Mailhelp entfernt nur, was es selbst angelegt hat und was seither unverändert ist.

**Nichtziele**

- Kein Entfernen von Einträgen, die Mailhelp nur gefunden („bereits vorhanden“), geändert oder
  zusammengeführt hat.
- Kein Zurückholen von Kalenderdateien und simulierten Einträgen (R5).
- Keine Wiederkehr der Rückhaltefrist; kein „Rückgängig“ für Verwerfen (ein verworfener Vorschlag
  hat nichts geschrieben; ihn wieder zu öffnen ist ein anderes Thema).
- Kein Sammel-Entfernen.

---

## 2. Entscheidungen

| ID | Frage | Vorschlag |
| :--- | :--- | :--- |
| **E1** | Wie lange ist Entfernen möglich? | **10 Minuten** nach dem Anlegen, ausdrücklich vom Betreiber gewählt. Danach wird der Eintrag beim Anbieter bearbeitet. |
| **E2** | Bestätigung | **Zwei Schritte auch per Tipp:** „Eintrag wieder entfernen“ öffnet eine Bestätigung mit Titel, Zeit und Ziel; erst „Jetzt entfernen“ sendet. Kein Wisch. Entfernen ist seltener und folgenreicher als Anlegen; ein versehentliches Entfernen eines richtigen Termins fällt niemandem auf. |
| **E3** | Was heißt Entfernen im Kalender? | Löschen des Termins im gebundenen Kalender. Die vorhandene Absage-Logik wird wiederverwendet; der Kontrollabruf erwartet „nicht mehr aktiv“. |
| **E4** | Was heißt Entfernen in Todoist? | Aufgabe **löschen**, nicht abschließen. Eine abgeschlossene Aufgabe erschiene in Auswertungen als erledigt. |
| **E5** | Geänderter Eintrag | Weicht der Eintrag beim Anbieter von den bestätigten Angaben ab (jemand hat ihn bearbeitet), entfernt Mailhelp ihn nicht und zeigt die Abweichung mit Link zum Eintrag. |
| **E6** | Zustand des Vorschlags danach | Neuer Endzustand „Angelegt und wieder entfernt“; der Vorschlag wird nicht wieder offen. Wer den Termin doch will, nutzt eine Neuprüfung der Mail. |

---

## 3. Maßnahmen

### 3.1 Schreibvertrag erweitern (R2, R3, R4)

- `external/contracts.py`: neue Operation „entfernen“ neben `create`, mit denselben Bausteinen –
  Vorbereitung (`PreparedWrite` mit erwartetem Endzustand), Idempotenzschlüssel, Abgleich
  (`reconcile`) vor einer Wiederholung.
- **Kalender:** Wiederverwendung des Absagewegs; bereits gelöscht oder abgesagt gilt als Erfolg ohne
  zweiten Schreibzugriff.
- **Todoist:** neuer Löschaufruf; „nicht gefunden“ gilt als bereits entfernt. Vor dem Löschen ein
  Lesezugriff für E5.
- Simulierte externe Dienste in `tests/fakes` erhalten dieselbe Operation mit den Fällen Erfolg,
  nicht gefunden, verboten, Zeitüberschreitung nach dem Schreiben, Zeitüberschreitung davor.

### 3.2 Befehl und Zustände

- Neuer Befehl „Eintrag entfernen“ im Befehlseingang, mit Vorschlagsversion, Idempotenzschlüssel
  und Akteur. Annahme nur, wenn der Vorschlag von Mailhelp angelegt wurde, eine Schreibreferenz hat
  und die Frist aus E1 läuft.
- Ablauf wie beim Anlegen: Schreibversuch festhalten, schreiben, Ergebnis speichern, Kontrollabruf.
  Ein Neustart zwischen Schreiben und Speichern führt zum Abgleich, nie zu einem zweiten Versuch
  auf Verdacht.
- Ergebnisse: „Entfernt und geprüft“, „Bereits entfernt“, „Nicht entfernt – Eintrag wurde geändert“
  (E5), „Entfernen noch nicht bestätigt“ (unklar; Abgleich läuft), „Entfernen fehlgeschlagen“.
- Die Sitzung wird bei Annahme und bei Ausführung geprüft (wie bei allen Webbefehlen).

### 3.3 Weboberfläche

- Ergebniskarte nach dem Anlegen und Vorschlagsseite: Text-Schaltfläche „Eintrag wieder entfernen“
  (keine hervorgehobene Hauptaktion), sichtbar während der Frist und nur für entfernbare Ziele.
- Bestätigungsseite nach E2 mit Titel, Zeit, Ziel und dem Satz „Der Eintrag wird im Kalender
  gelöscht. Der Vorschlag bleibt als ‚wieder entfernt‘ im Verlauf.“ Abbrechen führt zurück.
- Nach Ablauf der Frist: statt der Schaltfläche der Link „Im Kalender öffnen“ bzw. „Aufgabe öffnen“
  wie heute.
- Verlauf und „Zuletzt erledigt“ zeigen den neuen Endzustand als Plakette.

### 3.4 Telegram

- Unter der Meldung „Angelegt …“ die Schaltfläche „Wieder entfernen“; ein Druck fragt nach
  („Wirklich entfernen: …?“ mit „Ja, entfernen“ und „Abbrechen“). Ein veralteter oder doppelter
  Druck ändert nichts und sagt, warum.

### 3.5 Auswertung und Lernen

- „Wieder entfernt“ zählt in der Annahmequote (6.5) nicht als angenommen und erscheint dort als
  eigene Zeile.
- Das Lernprotokoll hält das Entfernen als Entscheidung fest.

---

## 4. Umsetzungsschritte

| Schritt | Patch | Arbeitspaket | Tests |
| :--- | :--- | :--- | :--- |
| D1 | 6.6.1 | Schreibvertrag „entfernen“ für Kalender und Todoist mit simulierten Diensten (3.1) | Erfolg, bereits entfernt, geändert (E5), verboten, Zeitüberschreitung vor und nach dem Schreiben, Wiederholung mit demselben Schlüssel ohne zweiten Schreibzugriff |
| D2 | 6.6.2 | Befehl, Zustände, Neustart-Abgleich (3.2) | Frist knapp davor und danach; nicht von Mailhelp angelegt; veraltete Version; Sitzung bei Ausführung widerrufen; Neustart in jeder Phase; doppelter Befehl |
| D3 | 6.6.3 | Weboberfläche mit Bestätigungsseite (3.3) | Zwei Schritte, Abbrechen, CSRF, ohne JavaScript, Desktop und Telefon, Barrierefreiheit; keine Schaltfläche für Kalenderdatei und Simulation |
| D4 | 6.6.4 | Telegram, Auswertung, Lernprotokoll (3.4, 3.5) | Rückfrage, doppelter und alter Druck; Quote zählt „wieder entfernt“ richtig |
| D5 | 6.6.5 | Doku, Abnahme, `docs/Release-6.6.md`; einmalige Probe gegen ein echtes Testkonto je Anbieter mit ausdrücklicher Freigabe | `python -m devtools.check full`, vollständige Browser-Suite |

---

## 5. Abnahmekriterien

- Kein Entfernen ohne die zweite, ausdrückliche Bestätigung genau dieser Vorschlagsversion.
- Derselbe Befehl zweimal, ein Neustart mittendrin oder eine verlorene Antwort führen zu höchstens
  einem Löschaufruf beim Anbieter.
- Ein beim Anbieter geänderter Eintrag wird nie entfernt.
- Nach Ablauf der Frist und für nicht entfernbare Ziele gibt es keine Schaltfläche und der Server
  lehnt den Befehl ab.
- 100 % Zeilen- und Branch-Abdeckung, 100 % JavaScript-Blockabdeckung; automatisierte Tests nur
  gegen simulierte Dienste.

## 6. Risiken

| Risiko | Gegenmaßnahme |
| :--- | :--- |
| Ein richtiger Termin wird versehentlich entfernt. | Zwei Schritte (E2), kein Wisch, keine Hauptaktion; Endzustand im Verlauf sichtbar; Mail lässt sich neu prüfen. |
| Mailhelp löscht einen Eintrag, den ein Familienmitglied inzwischen ergänzt hat. | E5: Vergleich mit den bestätigten Angaben vor dem Löschen. |
| Die Google-Berechtigung reicht nicht zum Löschen. | In D1 prüfen: Die Terminabsage nutzt denselben Zugriff bereits. Für Todoist den Löschaufruf an der aktuellen API-Dokumentation prüfen, bevor D1 beginnt. |
| Unklares Ergebnis nach Zeitüberschreitung. | Abgleich vor jeder Wiederholung, wie beim Anlegen. |

## 7. Dokumentation

`README.md`, `CHANGELOG.md`, `docs/Bedienung.md` (Abschnitt „Nach dem Anlegen“; Hilfeindex neu
erzeugen), Projektspezifikation (Schreibvertrag, Befehl, Zustände), `docs/Ziele-einrichten.md`
(benötigte Berechtigungen), `config.example.yaml` (Frist aus E1).
