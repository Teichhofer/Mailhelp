# Nachprüfung der Spezifikationsabdeckung

## Umsetzungsstand vom 8. Oktober 2026

Die Befunde unten bleiben als ursprünglicher Prüfstand erhalten.

- **N1 umgesetzt:** Unklare Vorschlags- und Relevanzzustellungen erhalten eine
  dauerhafte Rückfragesperre, auch bei Neustart aus älteren sending-Einträgen.
  Regressionen prüfen Abbruch vor/nach dem Versand, Versandfehler, Neustart,
  unberechtigte Antworten und Freigabe nach Erledigung.
- **N2 umgesetzt:** Noch zurückgehaltene Relevanzfragen blockieren keine anderen
  Mails. Queue und Checkpoints bleiben für sie unvollständig. Auch in späteren
  begrenzten Abrufen verdrängen sie keine neue Mail. Regressionen prüfen
  Fortsetzung nach Neustart und beide Relevanzentscheidungen.
- **N3 teilweise umgesetzt:** Prompts durch konkrete, schema-geprüfte Beispiele
  verbessert; fachliche Erwartungen nicht abgeschwächt. Neue Evaluation versucht,
  aber keine verwertbaren Antworten: Verbindungsfehler beim Zugriffstest. Deshalb
  bleiben reale Qualitätsbestätigung und manuelle Bewertung ausdrücklich offen.
- **N4 umgesetzt:** Gesperrte Cache-Verzeichnisse lassen die Bereinigung nicht
  mehr fehlschlagen; reproduzierender PermissionError-Test vorhanden.
- **N5 umgesetzt:** Spec, README und Konfigurationsbeispiel unterscheiden
  Mailanalyse, Telegram-Zustellung und versandunsichere/noch zurückgehaltene Fragen.

**Abschlussprüfung:** 892 Tests bestanden, 6.565 Statements und 2.034 Branches
vollständig abgedeckt (jeweils 100 %), Exit-Code 0. Die Fehlerregressionen wurden
vor den jeweiligen Korrekturen fehlschlagend ausgeführt. Kein Coverage-Ausschluss.
`git diff --check` ohne Whitespace-Befund. Python 3.12.14 mit vorhandenen lokalen
Paketen; kein frischer Referenzlauf mit dem exakten Lockfile.

Details und verbleibende Betriebsnachweise:
[Einrichtung und Qualitätsprüfung](docs/Einrichtung-und-Qualitaetspruefung.md),
[Evaluationsbericht](quality-reports/evaluation-2026-10-08.json).
Docker fehlt lokal; GitHub-CLI ohne Anmeldung. Es wurde kein externer Kalender-
oder Todoist-Schreibzugriff ausgeführt. Vollständige Betriebs-/Qualitätsabnahme
bleibt daher offen.

---

Stand: 7. Oktober 2026, Commit `9840ae0`. Grundlage ist die aktuelle
`Mailhelp-Projektspezifikation.md`, einschließlich der neuen Telegram-Outbox und
der ergänzenden Qualitätsabnahme. Geprüft wurden Code, Tests, Konfiguration,
CI-Definition und dokumentierte Modellergebnisse. Keine produktiven Dienste
wurden aufgerufen, keine Zugangsdaten gelesen und kein Anwendungscode verändert.

## Ergebnis

**Noch keine vollständige Spec-Abdeckung.** Die früheren Implementierungslücken
sind weitgehend geschlossen. Die Tests erreichen die geforderten 100 % Coverage.
Es bleiben jedoch zwei reproduzierbare Fehler im Zusammenspiel von Outbox und
Wiederanlauf/Mailverarbeitung, dokumentierte fachliche Modellabweichungen sowie
offene Abnahmen. Coverage allein belegt diese Anforderungen nicht.

## Neue beziehungsweise verbleibende Befunde

### N1 – Hohe Priorität: Rückfragesperre geht im Absturzfenster verloren

Anforderung: Nach einer gesendeten Rückfrage müssen spätere Benachrichtigungen
bis zur Erledigung warten (Spec, Zeilen 708–729).

`src/mailhelp/telegram/outbox.py:181` persistiert zunächst `sending`. Die aktive
Rückfragesperre wird erst nach dem externen Versand gespeichert (Zeile 198).
Nach einem Abbruch entfernt `flush()` den `sending`-Eintrag ohne Rekonstruktion
der Sperre (Zeile 161).

**Synthetisch reproduziert:** Vorschlag A mit offener Frage und danach eine
normale Nachricht einreihen; unmittelbar nach erfolgreichem simuliertem Versand
von A mit `SystemExit` abbrechen; Store schließen und erneut öffnen; neue
Controllerinstanz ausführen. Ergebnis: A wurde angezeigt, `active` war nicht
persistiert, die nachfolgende Nachricht wurde beim Neustart gesendet, obwohl
`open_questions == ['Wann?']` weiterhin bestand. Es gab keine externen Aufrufe.

Der vorhandene Test `test_interrupted_send_is_not_repeated_after_restart`
behandelt nur eine normale Nachricht, keine Rückfrage.

**Erledigen:** Die Rückfragesperre über dieses Absturzfenster hinweg erhalten oder
konservativ aus der persistenten Vorschlags-/Relevanzreferenz rekonstruieren.
Unklare Zustellung weiterhin nicht blind wiederholen. Regressionen für
Vorschlags- und Relevanzfragen sowie Abbruch vor/nach dem Versand ergänzen.

### N2 – Hohe Priorität: Zurückgehaltene Relevanzfrage blockiert andere Mails

Die neue Outbox-Regel verlangt ausdrücklich: Eine zurückgehaltene Relevanzfrage
hält nur die Analyse ihrer eigenen Mail an (Spec, Zeilen 717–718).

`TelegramDialogController.awaiting_relevance_decision()` berücksichtigt jedoch
alle offenen Relevanzdialoge (`src/mailhelp/telegram/dialog.py:275`), unabhängig
vom Versandstatus. `Application._process_mail()` wartet darauf global
(`src/mailhelp/application.py:718`); auch die äußere Verarbeitungsschleife tut
dies (Zeile 781).

**Synthetisch reproduziert:** Vorschlagsfrage A anzeigen, anschließend eine
Relevanzfrage für B erzeugen. B bleibt korrekt in der Outbox und wurde noch nicht
angezeigt; trotzdem liefert die globale Wartebedingung bereits `True`.
Weitere Mails können dadurch auf eine unsichtbare Relevanzfrage warten. Solange
A nicht geklärt ist, kann diese regulär nicht versendet werden.

**Erledigen:** Wartezustand pro Mail und Zustellstatus unterscheiden und den
IMAP-Queue-/Checkpoint-Ablauf entsprechend absichern. Integrationstest A →
zurückgehaltenes B → unabhängige Mail C, einschließlich Neustart und späterer
Antwort auf B. Dabei darf B weder verloren gehen noch vorschnell als abgeschlossen
gelten.

### N3 – Fachliche Abweichungen im dokumentierten realen Modelllauf

`docs/Einrichtung-und-Qualitaetspruefung.md:147` dokumentiert zwei reale Läufe mit
je **14/17** vollständig bestandenen Fällen. Diese Angaben wurden anhand der
Dokumentation bewertet, hier weder erneut ausgeführt noch anhand eines
versionierten Rohberichts unabhängig bestätigt.

- `17_optional_booking`: Kein Aufgabenvorschlag. Die Spec verlangt für ein
  konkretes, persönlich adressiertes freiwilliges Buchungsangebot ausdrücklich
  einen freiwilligen Aufgabenvorschlag (Zeilen 594–601). Eine Zusammenfassung
  allein erfüllt das nicht.
- `14_invitation_registration`: Der Fachtagstermin fehlt in der Zusammenfassung.
  Die Spec verlangt alle ausdrücklich genannten Fristen **und Termine** in
  `deadlines` (Zeile 423).
- `03_council_event`: Die dokumentierten Varianten führen zur gleichen
  Rückfrage. Dies ist für sich kein nachgewiesener Funktionsfehler; die zulässigen
  Varianten und die Bewertung sollten konsistent sein.

Die Bezeichnung „bewusst akzeptiert“ in der Einrichtungsdokumentation ändert die
beiden entgegenstehenden Spec-Anforderungen nicht.

**Erledigen:** Die ersten beiden Fälle fachlich korrigieren und erneut evaluieren,
oder eine bewusst geänderte Anforderung ausdrücklich in Spec und Korpus
übernehmen. Die weiterhin ausstehende manuelle Prüfung von Zusammenfassungen,
Titeln, Beschreibungen und Evidenz durchführen und dokumentieren. Keine
Erwartungen allein zum Erzielen eines grünen Berichts abschwächen.

### N4 – Mittlere Priorität: Testbereinigung kann einen grünen Lauf scheitern lassen

Nach **878 bestandenen Tests** und vollständig erfüllter Coverage endete der
Testprozess trotzdem mit Exit-Code 1: `tests/conftest.py:53` wirft beim rekursiven
Prüfen eines fremden/älteren Cache-Unterordners einen unbehandelten
`PermissionError`. Betroffen war `.test-tmp/pytest-cache`.

Dies ist ein lokal beobachtetes Windows-/Berechtigungsproblem der Testbereinigung,
kein fehlgeschlagener Anwendungstest. Es verhindert hier aber einen insgesamt
erfolgreichen automatisierten Prüflauf. Ein erster Versuch war bereits beim
Zugriff auf einen vorhandenen System-Temp-Ordner gescheitert; mit einem separaten
Arbeitsverzeichnis konnten alle Tests ausgeführt werden.

**Erledigen:** Bereinigung auf eigene Laufartefakte begrenzen und gesperrte
Restverzeichnisse kontrolliert behandeln; Regression mit simuliertem
`PermissionError`. Anschließend vollständigen Lauf mit Exit-Code 0 nachweisen.

### N5 – Spezifikation enthält widersprüchliche Blockierungsregeln

- Zeile 162: Vorschläge blockieren keine weiteren Vorschläge.
- Zeilen 710–718: Vorschläge mit Rückfragen halten spätere Nachrichten zurück.
- Zeilen 704–705: Jede offene Relevanzentscheidung pausiert die weitere Analyse.
- Zeilen 717–718: Zurückgehaltene Relevanzfragen pausieren nur die eigene Mail.

**Erledigen:** Regeln für Analyse, Telegram-Zustellung, sichtbare Relevanzfragen
und zurückgehaltene Relevanzfragen einheitlich formulieren. N2 richtet sich nach
der ausdrücklich neu hinzugefügten Regel für zurückgehaltene Fragen.

## Abgleich der Anforderungsbereiche

| Bereich | Stand dieser Nachprüfung |
| --- | --- |
| IMAP, MIME-Aufbereitung, Filter, Themen, Duplikaterkennung | Implementierung und simulierte Tests vorhanden; keine zusätzliche Lücke in dieser Prüfung festgestellt. |
| YAML-Konfiguration, Geheimnistrennung, Modellparameter, Limits | Implementierung und Tests vorhanden, einschließlich neuer Reasoning-Parameter. |
| Zusammenfassungen und Vorschläge, Mengenabweichungen, Zeitkontext | Implementiert und simuliert geprüft; reale fachliche Abweichungen siehe N3. |
| Telegram, Versionierung, Autorisierung, Änderungsdialoge | Umfangreich getestet; neue Outbox-Probleme siehe N1/N2. |
| Google/Todoist-Schreibfreigabe, Idempotenz, Abgleich unklarer Ergebnisse | Simulierte Sicherheits-, Fehler- und Wiederanlauftests bestehen; keine neue Verletzung der Schreibfreigabe festgestellt. |
| JSON-Zustand, Migration, Logging, Aufbewahrung | Implementierung und Tests vorhanden; Outbox-Wiederanlauf bleibt unvollständig. |
| Windows/Linux, Docker, Lernen, OAuth-Einrichtung | Implementierung, Dokumentation und CI-Prüfungen vorhanden; frischer Linux-/Container-Lauf hier nicht verifiziert. |
| Tests und Qualitätsabnahme | 100 % Coverage erreicht; Testprozessbereinigung, reale Grenzfälle und manuelle Qualitätsprüfung noch offen. |

Die früheren Punkte F1–F5 und F7 sind im damaligen Umfang umgesetzt. F6 ist
gegenüber dem alten Bericht fortgeschritten: Evaluator und dokumentierte reale
Läufe existieren inzwischen. Eine vollständige Qualitätsabnahme ist damit noch
nicht erreicht. Der historische Bericht vom 6. Oktober ist kein aktueller
Nachweis fehlender Evaluationsläufe mehr.

## Messung und Grenzen

- 878 Tests bestanden; **6.541/6.541 Statements**, **2.020/2.020 Branches**,
  jeweils 100 %. Anwendungscode in 53 Coverage-Dateien erfasst.
- Windows, verfügbare Python-Laufzeit 3.12.14 mit lokalen Projektpaketen;
  die vorhandene `.venv` verweist weiterhin auf einen nicht vorhandenen Interpreter.
  Kein frischer Lauf mit exakt installiertem Lockfile/Referenz-Python 3.12.10.
- Pytest mit isoliertem `--basetemp` und `MAILHELP_TEST_TEMP`, deaktiviertem
  Cache-Plugin; dadurch erwartbare Warnung über dessen `cache_dir`-Option.
  Der abschließende Bereinigungsfehler ist separat unter N4 erfasst.
- `git diff --check` ohne Befund vor Erstellung dieses Berichts.
- Docker ist hier nicht verfügbar. CI definiert Windows-/Linux-Tests sowie
  normale und Lern-Containerstarts mit persistentem Zustand. Ihr erfolgreicher
  Lauf für den geprüften Commit wurde hier nicht bestätigt; die lokale GitHub-CLI
  ist nicht angemeldet.
- Keine kontobezogene Live-Abnahme von IMAP, Telegram, OAuth, Kalender oder
  Todoist durchgeführt. Dies sind Nachweisgrenzen, keine behaupteten Dienstfehler.

## Reihenfolge bis zur Abnahme

1. N1 und N2 mit zuerst fehlschlagenden Regressionstests beheben; N5 vereinheitlichen.
2. N4 beheben und vollständige Tests mit 100 % Zeilen-/Branch-Abdeckung und
   erfolgreichem Prozessende auf Windows sowie Linux ausführen.
3. N3 fachlich auflösen, reale Evaluation erneut dokumentieren und die manuelle
   Qualitätsprüfung abschließen.
4. Erfolgreiche CI-/Containerläufe für den endgültigen Commit und die getrennte
   kontobezogene Betriebsabnahme dokumentieren. Externe Schreibtests weiterhin
   ausschließlich nach ausdrücklicher versionsbezogener Telegram-Bestätigung.
