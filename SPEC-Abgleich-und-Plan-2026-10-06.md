# Spezifikationsabgleich und Umsetzungsplan

## Umsetzungsstand vom 7. Oktober 2026

Die unten dokumentierten Befunde beschreiben den ursprünglichen Prüfstand.
Die beauftragten Änderungen sind inzwischen im Arbeitsbaum umgesetzt:

| Punkt | Umsetzung und Nachweis |
| --- | --- |
| D1 | Spec 1.4 und README vereinheitlichen Relevanzwarten, asynchrone Vorschläge, Mengenprüfung, Fehlerisolation, Zeitsemantik und Delta-Revision. |
| F1 | Vorschläge blockieren keine Mailanalyse; auch nach Neustart werden sie angezeigt, ohne zu warten. Alle Vorschläge eines Batches bleiben einzeln bedienbar. Run-Zähler erfassen offene Aktionen und werden nach Entscheidungen aktualisiert. |
| F2 | Analyzer validiert Struktur unabhängig von Routerzahlen. Beide Extraktionen bleiben erhalten; Mengenfragen werden dem Nutzer überlassen. Leere Extraktionen führen zu einer ausdrücklichen manuellen Prüfung ohne erfundene Aktionen. Prompts sind angepasst. |
| F3 | Normal-Compose bindet den Absenderfilter ein. `compose.learn.yaml` bietet den atomar beschreibbaren Verzeichnismount. Offline-Tests prüfen Filter und Lernpersistenz; die Linux-CI startet dafür frische Container. |
| F4 | Der Zugriffstest sammelt Fehler aller IMAP-Ordner; Nebenordnerfehler ergeben einen fehlgeschlagenen Gesamtstatus. Weitere Dienste werden trotzdem geprüft. |
| F5 | OAuth-Ersteinrichtung, Scopes, Refresh-Token und Wiederautorisierung sind anhand offizieller Google-Dokumentation beschrieben. |
| F6 | `mailhelp-evaluate` prüft tatsächliche Providerantworten gegen unabhängige Korpuserwartungen, mit expliziter Netzwerkfreigabe, Aufruf-/Tokenbegrenzung und JSON-Bericht. Die Tests des Werkzeugs sind vollständig simuliert. Ein realer Qualitätsnachweis ist weiterhin separat auszuführen. |
| F7 | Doppelanlage-Rückfragen zeigen Absender/Betreff oder einen neutralen Ersatztext, keine internen IDs. |

Zusätzlich wurde ein im neuen Batch-Regressionstest nachgewiesener Statistikfehler
behoben: Ein Duplikatprüfergebnis `new` oder `ambiguous` zählt nicht mehr als
übersprungene Duplikatmail.

**Abschlussprüfung:** 814 Tests bestanden, 6.201/6.201 Statements und
1.918/1.918 Branches abgedeckt, jeweils 100 %, ohne Test- oder Coverage-Warnungen.
`git diff --check` meldet keine Whitespace-Fehler. Die Regressionstests für
Mengenprüfung, Blockierung, IMAP-Teilfehler, sichtbare IDs, fehlenden Filtermount
und falsche Duplikatzählung wurden vor dem jeweiligen Fix fehlschlagend ausgeführt.

Getestet wurde lokal unter Windows mit Python 3.12.14 und den vorhandenen
Projektpaketen; die nicht startbare alte `.venv` wurde nicht umgeschrieben.
Der Abgleich mit `requirements.lock` ergab genau eine Paketabweichung:
lokal `idna 3.20` statt `3.19`. Die CI installiert weiterhin die exakten Lockversionen;
eine lokale Referenzmessung mit diesem exakten Paketstand ist noch offen.
Ein Docker-Programm ist hier nicht verfügbar. Die erweiterten Containerprüfungen
sind lokal als simulierte Dateisystemtests bestanden und in der CI konfiguriert,
aber noch nicht in Linux-Containern ausgeführt. Es wurden keine echten
OpenRouter-, Telegram-, Todoist- oder Google-Calendar-Konten angesprochen.
Ein aktueller Linux-CI-Lauf, ein realer Modellbericht und die kontobezogene
OAuth-Abnahme bleiben daher **offene Betriebsnachweise**, keine behaupteten Erfolge.

Die Bedienung steht in `docs/Einrichtung-und-Qualitaetspruefung.md`.

---

Stand: 6. Oktober 2026. Grundlage: `Mailhelp-Projektspezifikation.md`, aktueller
Arbeitsbaum auf Commit `448794e`, einschließlich der bereits vorhandenen lokalen
Änderungen. Anwendungscode, Tests und bestehende Dokumentation wurden bei dieser
Prüfung nicht verändert.

## Ergebnis

**Eine vollständige Erfüllung der Spezifikation ist derzeit nicht gegeben.**
Der Kern ist weitgehend implementiert und durch eine umfangreiche simulierte
Testsuite abgesichert. Es gibt aber konkrete Abweichungen, fehlende
Betriebsdokumentation und widersprüchliche Anforderungen. Deshalb wäre auch eine
grüne Testsuite allein keine vollständige fachliche Abnahme.

Die wichtigsten offenen Punkte sind:

1. Offene Vorschläge blockieren weiterhin die Verarbeitung anderer Mails.
2. Abweichende Router-/Extraktionszahlen werden als Schemafehler behandelt.
3. Docker übernimmt den Absenderfilter nicht; der Lernmodus kann die einzeln
   schreibgeschützt eingebundenen Konfigurationsdateien nicht atomar aktualisieren.
4. Der Zugriffstest meldet nicht lesbare konfigurierte Nebenordner nicht als
   fehlgeschlagenen IMAP-Zugriff.
5. Google-OAuth-Ersteinrichtung und tatsächliche LLM-Erkennungsqualität sind nicht
   ausreichend dokumentiert beziehungsweise nachgewiesen.

Es wird bewusst kein Prozentwert für die Spec-Erfüllung angegeben: Anforderungen
sind unterschiedlich gewichtig und teilweise gegenseitig unvereinbar.

## Durchgeführte Prüfung und Grenzen

- Die gesamte Spezifikation einschließlich der vorangestellten Ergänzungen und
  Schlussabschnitte wurde gelesen und den Implementierungs- und Testbereichen
  zugeordnet. Kritische Abweichungen wurden an den tatsächlichen Aufrufpfaden geprüft.
- Vollständige vorhandene Testsuite: **800 bestanden** in 16,34 Sekunden.
- Coverage-Bericht `spec-audit-coverage.json`: **6.104/6.104 Statements** und
  **1.892/1.892 Branches**, jeweils 100 %, keine fehlenden Zeilen oder Branches.
- Coverage führt außerdem 87 automatisch ausgeschlossene Zeilen an
  Protocol-/Ellipsis-Deklarationen auf. Es wurden keine projektspezifischen
  `pragma: no cover`-Umgehungen gefunden. Diese Deklarationen sind bei der
  Formulierung „sämtlicher eigener Code“ von ausführbarer Implementierung zu trennen.
- Der Lauf meldete einen nicht beschreibbaren bestehenden Pytest-Cache und eine
  Coverage-Warnung `module-not-measured`. Die Zahlen sind das Ergebnis dieses Laufs;
  eine saubere Wiederholung in der Referenzumgebung bleibt Teil der Abnahme.
- Die vorhandene `.venv` und das `python` im PATH verweisen auf einen nicht
  startbaren Python-3.12.10-Interpreter. Für die Prüfung wurde der verfügbare
  Python 3.12.14 mit den bereits vorhandenen Paketen aus `.venv/Lib/site-packages`
  und `src` im `PYTHONPATH` verwendet. Keine Installation und keine Veränderung
  der vorhandenen Umgebung waren erforderlich.
- Zwei zusätzliche synthetische Prüfungen bestätigten den Zählerfehler und den
  falschen IMAP-Erfolgsstatus, ohne Netzwerk oder echte Zugangsdaten.
- Kein realer Dienst wurde aufgerufen. Die Kompatibilität mit aktuellen externen
  APIs und die Qualität des konfigurierten realen Modells wurden nicht neu geprüft.
- Windows wurde lokal getestet. Linux-/Containerprüfungen sind in der CI vorhanden,
  wurden hier aber nicht ausgeführt; ein Docker-Befehl ist lokal nicht verfügbar.
  Ein erfolgreicher aktueller CI-Lauf wurde nicht verifiziert.

## Abdeckung nach Anforderungsbereich

„Vorhanden“ bedeutet: Implementierung und passende simulierte Tests gefunden;
es bedeutet keine uneingeschränkte Garantie für jeden denkbaren Betriebsfall.

| Spec-Bereich | Stand und Belege | Restarbeit |
| --- | --- | --- |
| Einleitung: CLI, Polling, Einmalläufe, Signale | `cli.py`, `application.py`; `test_application.py`, `test_cli_paths.py`, `test_runtime_reliability.py` | Blockierregeln vereinheitlichen und korrigieren, F1 |
| Lernmodus und Absenderfilter | `learning.py`, `sender_filter.py`; `test_learning.py`, `test_sender_filter.py` | Docker-Bereitstellung, F3 |
| Aufbewahrung/Datenminimierung | `retention.py`; `test_retention.py` prüft Fristen, offene Vorgänge, Wiederholung und getrennte Namensräume | Kein konkreter zusätzlicher Implementierungsfehlbestand in der Prüfung festgestellt |
| 1–2: Ziel und V1-Umfang | Python-Anwendung, IMAP, OpenRouter, Telegram, Todoist und Google Calendar vorhanden | Keine fehlende Kernintegration gefunden |
| 3: Mail-Verarbeitung | `orchestrator.py`, `application.py`; simulierte E2E-Tests | Widersprüche zu asynchronen Vorschlägen und Fehlerisolation, F1/D1 |
| 4: IMAP, MIME, persistente Queue | `imap.py`, `mime.py`, `domain/run.py`; `test_application.py`, `test_mime_security.py`, `test_duplicates.py` | Queue-/Interaktionszustände bei Behebung von F1 mitprüfen |
| 5: Themen und Relevanz | Geschlossene Konfiguration und Ergebnisse; `test_core.py`, `test_validation_boundaries.py`, `test_services.py` | Kein konkreter zusätzlicher Fehlbestand festgestellt |
| 6: LLM-Stufen, Routing und Retries | `analysis.py`, `openrouter.py`, `prompts.yaml`; `test_adapter.py`, `test_services.py` | Zählerkonflikte dürfen nicht Schemafehler sein, F2 |
| 7: Vorschläge, Zeitfakten, Zusammenfassungen | `action_normalization.py`, `proposal_builder.py`, Domänenmodelle; entsprechende Tests und `test_date_context.py` | Widersprüchliche Altregeln entfernen; reale Erkennungsqualität nachweisen, F6 |
| 8: Telegram und externe Schreibgrenze | Getrennte Telegram-Komponenten, Versionsbindung, Autorisierung, persistente Schreibzustände; `test_review_write_safety.py`, `test_telegram_*.py`, `test_write_improvements.py` | F1 und sichtbare interne IDs, F7 |
| 9: Konfiguration, Geheimnisse, Zugriffstest | `config.py`, `cli.py`; `test_access_check.py`, `test_google_oauth.py` | F3–F5 |
| 10: JSON, Wiederanlauf und Duplikate | `storage.py`, `persistence/`, `telegram/persistence.py`, `telegram/ledger.py`; `test_validation_boundaries.py`, `test_duplicates.py`, `test_runtime_reliability.py` | Veraltete Fehler-/Queuebeschreibung korrigieren, D1 |
| 11: Logging | `logging.py`, getrennte LLM-/Telegram-Logs; `test_observability.py` | Kein konkreter zusätzlicher Fehlbestand festgestellt |
| 12: Architektur und Betrieb | Adaptertrennung, Windows-/Linux-Pfade, Dockerfile und Compose vorhanden | Docker-Konfiguration vervollständigen; Plattformabnahme, F3/V1 |
| 13: Tests/Entwicklungsregeln | 800 grüne Tests, Coverage-Gate in `pyproject.toml`, CI-Matrix Windows/Ubuntu | Fachlich falsche Sollwerte korrigieren, echte Qualitätsauswertung F6; saubere Referenzmessung V1 |
| 14: Abnahme | Siehe separate Tabelle unten | Noch keine Gesamtfreigabe |
| 15–16: Einrichtung/Kurzbeschreibung | Beispiele und Projektbeschreibung vorhanden | OAuth-Anleitung und verifizierte API-/Modellkompatibilität fehlen als aktueller Nachweis |
| 17 und Revisionsnachträge | Delta-Revision, lokale Zeitinterpretation, persistente Antworten und Retry-Zustände vorhanden; `test_telegram_dialog.py`, `test_telegram_usability.py` | Widersprüche zwischen Vollausgabe/Delta und Antwortzuständen beseitigen, D1 |
| Google-Calendar-Nachtrag | OAuth, Idempotenz, Paginierung, fachliche Duplikatsuche und begrenzte Ergänzung vorhanden | Ersteinrichtung F5; reale Kompatibilität nicht verifiziert |
| Betriebszuverlässigkeit | Pfadauflösung, tzdata, Cursorprüfung, CI-Containerneustarttest vorhanden | Containerfilter/Lernmodus F3; aktueller Linux-Nachweis V1 |

## Konkrete Befunde

### F1 – P1: Vorschläge halten weiterhin die Mail-Queue an

**Soll:** Spec Zeilen 28–33: Nur unklare Relevanz unterbricht die Analyse; Aufgaben-
und Terminvorschläge bleiben asynchron offen, auch bei `--max-mails`.

**Ist:** `Application._process_mail()` in `src/mailhelp/application.py:714` wartet
vor beziehungsweise nach der Verarbeitung auf `dialog.awaiting_decision()`.
Diese Methode zählt in `src/mailhelp/telegram/dialog.py:189` ausdrücklich
`pending_confirmation` und `needs_clarification` dazu. Die vorhandene Methode
`awaiting_relevance_decision()` wird an diesen Grenzen nicht verwendet.
`test_open_proposal_blocks_next_mail_even_in_bounded_run` in
`tests/test_application.py:810` fordert sogar das blockierende Verhalten.

**Folge:** Eine unbeantwortete Vorschlagsnachricht kann die weitere Mailanalyse
und das Ende eines begrenzten Laufs auf unbestimmte Zeit verzögern.

**Plan:** Relevanzwarten, offene Vorschläge und technische Revisionspausen als
getrennte Zustände verwenden. Mailanalyse nur für die tatsächlich blockierende
Relevanzentscheidung anhalten. Die beabsichtigte Sonderbehandlung bereits beim
Start offener Entscheidungen ausdrücklich festlegen. Versand, Run-Zähler,
`waiting_for_user`, Abschlussmeldung und spätere Telegram-Bearbeitung gemeinsam
anpassen, ohne die versionsbezogene Schreibfreigabe abzuschwächen.

**Abnahme:** Mit zwei synthetischen Mails und offenem Vorschlag der ersten wird die
zweite analysiert. `--max-mails 2` beendet den Durchlauf mit dauerhaft erhaltenem
Vorschlag. Eine unklare Relevanz hält dagegen die Analyse an und wird nach Antwort
fortgesetzt. Neustart, spätere Bestätigung, mehrere Vorschläge, Shutdown und
pausierte Revision erhalten eigene Regressionstests.

### F2 – P1: Zählerkonflikte zerstören den vorgesehenen Klärungspfad

**Soll:** Spec Abschnitt 6, Zeilen 302 ff.: Routerzahlen sind nur Diagnosewerte.
Schema-gültige Extraktionen werden vollständig erhalten; die andere Extraktion
wird fortgesetzt. Konflikte führen zur fachlichen Klärung.

**Ist:** `src/mailhelp/analysis.py:305` und `:320` werfen bei abweichender Anzahl
`ValueError` innerhalb der Schema-Reparaturschleife. Die normale Analyzer-Grenze
gibt deshalb das schema-gültige Ergebnis nicht an den Orchestrator weiter.
Zusätzlich bricht `src/mailhelp/orchestrator.py:457` beziehungsweise `:473` bei
einer Abweichung ab. Die vorhandene Konfliktpersistenz allein erfüllt das Soll
nicht. `tests/test_services.py:190`, `:212` und `:1565` sichern den Abbruch ab.

**Reproduktion:** Synthetischer Completer liefert
`{"schema_version": 1, "tasks": []}` bei `expected_count=1`, Reparaturbudget 0.
Ergebnis: `LlmSchemaValidationFailed`, obwohl das Extraktionsschema gültig ist.

**Plan:** Schema- und Mengenvalidierung trennen. Gültige Ergebnisse samt Call-ID
sofort speichern, Zählerabweichungen als eigene Fachdiagnose speichern, Task- und
Eventpfad unabhängig fortsetzen. Vorhandene Vorschläge mit Mengenfrage sperren.
Für den Fall einer leeren Extraktion muss ein ausdrücklicher Klärungsweg definiert
werden, der keine erfundene Aufgabe und keinen erfundenen Termin erzeugt.

**Abnahme:** Router 2/Extraktion 1, Router 1/Extraktion 0 und beide Aktionsarten
prüfen. Keine reine Mengenabweichung darf Schema-Retries verbrauchen oder die
andere Extraktion verhindern. Wiederanlauf verwendet dieselben Ergebnisse und
Konflikte. Erst geklärte, neue und separat bestätigte Versionen dürfen schreiben.

### F3 – P1: Docker-Konfiguration ist für Filter und Lernen unvollständig

**Soll:** Identische Programmlogik unter Windows und Linux; der Filter liegt neben
den Themendateien und wird vor der LLM-Prüfung verwendet. Lernen aktualisiert
Themen, Ordnerkonfiguration und Absenderfilter atomar.

**Ist:** `compose.yaml:9` bindet vier YAML-Dateien einzeln mit `:ro` sowie Daten
und Logs ein. `irrelevant-senders.json` wird nicht eingebunden.
`src/mailhelp/application.py:901` verwendet aber das Konfigurationsverzeichnis als
Filter-Store. Der lokal gepflegte Filter ist somit im ausgelieferten Container
nicht verfügbar. `src/mailhelp/learning.py:59` verwendet für YAML-Änderungen
`os.replace`; dies funktioniert nicht auf den schreibgeschützten Einzelmounts.
Bloßes Entfernen von `:ro` ist wegen des atomaren Dateiaustauschs keine vollständige
Lösung für einzeln eingebundene Dateien.

**Plan:** Filter für den Normalbetrieb explizit bereitstellen. Einen dokumentierten,
bewusst beschreibbaren Konfigurations-Verzeichnismount für den Lernmodus anbieten,
mit Rechten für UID/GID 65532. Normalbetrieb und Lernaufruf eindeutig dokumentieren.
Synthetische Filterdaten für CI verwenden.

**Abnahme:** Ein blockierter synthetischer Absender erzeugt auch im Container keinen
LLM-Aufruf. Ein Lernlauf aktualisiert Konfiguration, relevante/irrelevante Themen
und Filter; ein frischer Container liest diese Änderungen wieder. Test mit den
tatsächlichen Compose-Mounts und ausgeschaltetem Netzwerk.

### F4 – P2: Zugriffstest meldet einen Teilfehler als vollständigen Erfolg

**Soll:** Abschnitt 9 verlangt die Prüfung aller konfigurierten IMAP-Ordner und
einen Fehlerstatus bei einem Teilfehler.

**Ist:** `src/mailhelp/application.py:154` behandelt nur den Hauptordner als
verbindlich. Ausnahmen anderer Ordner werden geloggt und verschluckt. Der Test
`tests/test_access_check.py:183` verlangt dieses Verhalten.

**Reproduktion:** Synthetisch lesbare INBOX und nicht lesbares konfiguriertes
Archive ergeben `{'IMAP': None, ...}`; alle Dienste erscheinen erfolgreich.

**Plan:** Im Diagnosemodus je Ordner ein Ergebnis sammeln und jeden Teilfehler im
Gesamtergebnis/Exit-Code darstellen. Dass der normale Dienst einen nicht lesbaren
Zusatzordner überspringen kann, muss davon getrennt bleiben. Falls Nebenordner
bewusst unverbindlich sein sollen, ist dies stattdessen explizit zu spezifizieren.

**Abnahme:** INBOX erfolgreich, Archive fehlerhaft: beide Ergebnisse sichtbar,
andere Dienste trotzdem geprüft, abschließender Exit-Code 1, keine Geheimnisse.

### F5 – P2: Google-OAuth-Ersteinrichtung nicht vollständig beschrieben

**Soll:** Spec Abschnitt 9 verlangt einen dokumentierten Ablauf für erstmalige
Autorisierung und Erneuerung abgelaufener Berechtigungen.

**Ist:** `README.md:103` nennt Client-ID, Client-Secret und Refresh-Token, setzt
deren Beschaffung aber voraus. Die vorhandene Tokenprovider-Implementierung
erneuert Access-Tokens aus einem bereits vorhandenen Refresh-Token; sie ersetzt
keine Anleitung zum Erhalt oder Austausch dieses Tokens.

**Plan:** Einrichtung von Cloud-Projekt/API, OAuth-Client, Zustimmung, benötigten
Scopes, Offline-Zugriff/Refresh-Token, sicherer Ablage und Wiederautorisierung
konkret dokumentieren. Dabei offizielle aktuelle Google-Dokumentation prüfen und
verlinken; die Prüfung hier hat keine aktuelle API-Recherche vorgenommen.
Ein zusätzliches Werkzeug ist nur nötig, wenn die Dokumentation allein nicht
praktikabel ist.

**Abnahme:** Eine Person ohne vorhandenen Refresh-Token kann mit der Anleitung
die Einrichtung und später die Wiederautorisierung durchführen. Beispielwerte
bleiben synthetisch; die Anleitung endet mit dem Zugriffstest.

### F6 – P2: Erkennungsqualität eines echten Modells nicht nachgewiesen

**Soll:** Abschnitt 13 verlangt neben Coverage eine Qualitätsbewertung anhand
fester erwarteter Beispielentscheidungen.

**Ist:** `tests/test_quality_corpus.py:34` gibt im simulierten OpenRouter-Client
direkt die erwarteten Antworten aus den Fixtures zurück. Das prüft sinnvoll
Schema, Routing, Normalisierung und Builder, aber nicht, ob ein Modell aus der
Mail diese Antworten erkennt. Die README erklärt ausdrücklich, dass auch kein
optionales Skript für reale Modellbewertung vorhanden ist.

**Plan:** Einen getrennten, ausdrücklich aktivierten Evaluationslauf mit
synthetischem Korpus bereitstellen. Modell, Prompt-Fingerprint, Parameter und
Ergebnisse dokumentieren. Kriterien für Relevanz, Kandidaten, Zuständigkeit,
Zeitangaben, Prompt-Injection und unbelegte Aktionen definieren. Automatisierte
Standardtests bleiben vollständig simuliert; weder Standard-Pytest noch die
reguläre CI dürfen hierfür echte Dienste oder Zugangsdaten verwenden.

**Abnahme:** Ein reproduzierbarer Ergebnisbericht bewertet tatsächliche
Modellantworten gegen unabhängige Erwartungen; Kosten-/Aufrufgrenzen sind explizit.
Ein absichtlich falsches Ergebnis wird als Qualitätsfehler erkannt.

### F7 – P2: Doppelanlage-Rückfrage zeigt interne IDs

**Soll:** Vorschlagsnachrichten sollen die Ursprungsmail über Absender/Betreff
zuordnen und keine internen Mail-/Vorschlags-IDs anzeigen.

**Ist:** `src/mailhelp/telegram/decisions.py:88` zeigt in der Doppelanlage-Rückfrage
`Frühere Quelle: Mail {previous.mail_id}, Vorschlag {previous.proposal_id}, ...`.
Diese Ausgabe umgeht die ansonsten bereinigte Darstellung.

**Plan:** Frühere Quelle über gespeicherte Anzeigeheader und gegebenenfalls
externen Link darstellen; bei fehlenden alten Metadaten neutralen Ersatztext
verwenden. IDs bleiben in technischen Referenzen und Callback-Daten.

**Abnahme:** Doppelanlage mit vorhandenen und fehlenden alten Mailmetadaten testen.
Die sichtbare Nachricht enthält keine internen IDs; Versionsprüfung und
Doppelanlagefreigabe bleiben unverändert wirksam.

## D1 – P1: Spezifikation als eindeutige Soll-Grundlage konsolidieren

Vor Änderungen an strittigem Verhalten müssen die widersprüchlichen Stellen
auf eine gemeinsame Regel gebracht werden. Für den Plan wird die jeweils konkret
beschriebene neue Funktion als Ziel vorgeschlagen; das ist keine Behauptung, dass
die bestehende Spec bereits eine eindeutige Vorrangregel enthält.

| Konflikt | Stellen | Vorschlag für die bereinigte Regel |
| --- | --- | --- |
| Vorschläge asynchron versus globales Warten | Einleitung Zeile 31 versus Abschnitt 3 Zeile 162 und Abschnitt 8 | Relevanz blockiert Analyse; Vorschläge bleiben asynchron. Startup-Sonderregel ausdrücklich definieren. |
| Routerzahl Diagnose versus zwingende Anzahl | Abschnitt 6 Zeile 302 versus Abschnitt 7 Zeile 422 | Schema-gültige Extraktionen erhalten, Mengenabweichung fachlich klären. |
| Fehler einer Mail isolieren versus komplette Queue stoppen | Einleitung Zeilen 34 ff. versus Abschnitt 10 Zeile 940 und Abschnitt 11 | Dauerhaft gespeicherter einzelner Mailfehler isoliert; unerwarteter Fehler ohne sichere Persistenz darf stoppen. |
| Pausierte Revision isolieren versus gesamte Queue blockieren | Spec-Nachtrag Zeile 1260 versus README Zeile 849 | Nur betroffenen Vorschlag pausieren; README an den bereits teilweise umgesetzten Stand anpassen. |
| Datum ohne Uhrzeit automatisch ganztägig versus ausdrückliche Evidenz | Abschnitt 7 Zeilen 455 ff. versus `time_requirement`-Regeln Zeilen 503 ff. | Kein Ganztag allein aufgrund fehlender Uhrzeit; ausdrücklich geregelte mehrtägige Bereiche berücksichtigen. |
| Vollständiges Proposal vom LLM versus geschlossenes Delta | Abschnitt 17 Zeile 1181 versus Nachtrag Zeile 1239 | LLM liefert Delta; Anwendung baut und validiert den vollständigen Nachfolger. |
| Nur normalisierte Antwort persistieren versus Wiederaufnahme der Interpretation | Abschnitt 8 Zeilen 597–601 versus `authorized_answer` in `domain/processing.py:62` und spätere Retry-Beschreibung | Autorisierten Rohtext als getrennte untrusted Eingabe, normalisierte Antwort als validiertes Ergebnis beschreiben. |
| Zwei bis vier Sätze versus ein bis zwei | Prompt-Beispiel Abschnitt 6 versus Abschnitt 7 und aktuelle Prompts | Beispiel auf ein bis zwei Sätze aktualisieren. |
| Bestehende Termine nicht ändern versus Ergänzung erkannter Duplikate | V1-Ausschlüsse Abschnitt 2 versus Google-Calendar-Nachtrag | Begrenzte, bestätigte Ergänzung als ausdrückliche Ausnahme dokumentieren. |

Außerdem Versions-/Datumsstand der Spec und veraltete Migrationsverweise
vereinheitlichen. Die README muss dieselben Betriebsregeln beschreiben.

## Abnahmekriterien aus Abschnitt 14

| Nr. | Bewertung |
| --- | --- |
| 1 | Teilweise nachgewiesen: lokale Windows-Tests erfolgreich, Linux-CI konfiguriert; Containerfilter/Lernen und aktueller Containerlauf offen. |
| 2 | Implementiert und simuliert getestet: UID-/Backlog-Verarbeitung, Wiederanlauf und Duplikate. |
| 3 | Simuliert nachgewiesen; reale Modellqualität offen, F6. |
| 4 | Implementiert: YAML-basierte Prompts, Modelle, Parameter und Themen. |
| 5 | Teilweise: Vorschläge und Pflichtfeldvalidierung vorhanden; Mengenabweichungen und Queue-Verhalten offen. |
| 6 | Implementiert und umfangreich simuliert geprüft: versionsbezogene Telegram-Freigabe vor externem Schreiben. |
| 7 | Adapter und simulierter E2E-Ablauf vorhanden; reale Konten nicht geprüft, OAuth-Anleitung unvollständig. |
| 8 | Implementiert und simuliert geprüft: Idempotenz, unklare Resultate, Paginierung und Doppelanlagefreigabe. |
| 9 | Persistenz vorhanden und getestet; Wiederaufnahme muss nach F1 zusätzlich für asynchrone Vorschläge geprüft werden. |
| 10 | Implementiert und simuliert geprüft: getrennte Logs, Call-IDs und Geheimnismaskierung. |
| 11 | Implementiert und simuliert geprüft: Todoist-Simulation, Kalender bleibt bestätigungspflichtiger realer Schreibpfad. |
| 12 | Aktueller lokaler Bericht meldet 100 %/100 %; saubere Referenz-/Linux-Messung und fachliche Korrektur alter Solltests stehen aus. |

## Reihenfolge der Umsetzung

1. **D1 – Sollzustand bereinigen.** Eine verbindliche Regel je Konflikt, danach
   README und Beispiele angleichen. Dabei jede Regel einem Verhaltenstest zuordnen.
2. **F2 – Extraktionspipeline korrigieren.** Zuerst Regressionstests mit echtem
   Analyzer und simuliertem Provider hinzufügen; dann Mengenprüfung entkoppeln und
   dauerhafte Klärung einschließlich leerer Extraktionen umsetzen.
3. **F1 – Queue und Telegram entkoppeln.** Regressionstests für den vollständigen
   Application-/Dialogpfad anlegen, danach Wartegrenzen und Run-Status anpassen.
   Neustarts und Autorisierung müssen ausdrücklich Bestandteil dieser Änderung sein.
4. **F3 – Docker vervollständigen.** Filtermount, beschreibbaren Lernmodus und
   produktionsnahe Offline-Containerprüfungen ergänzen.
5. **F4 und F7 – Diagnose/Darstellung korrigieren.** Jeweils erst reproduzierenden
   Regressionstest anlegen und dann den begrenzten Fix umsetzen.
6. **F5 und F6 – Einrichtung und fachliche Qualitätsabnahme ergänzen.** Aktuelle
   offizielle Integrationsdokumentation prüfen; optionalen realen Evaluationslauf
   außerhalb der automatisierten simulierten Suite dokumentieren/bereitstellen.
7. **V1 – Abschlussprüfung.** Funktionsfähige Python-3.12-Referenzumgebung herstellen,
   mit `requirements.lock` prüfen, komplette Windows-/Ubuntu-Suite und die beiden
   Containerstarts auf gemeinsamen Volumes ausführen. Messwarnungen klären und
   Coverage ohne Unterschreitung bestätigen. Abnahmetabelle mit den Ergebnissen
   aktualisieren.

Für jeden Bugfix gilt die AGENTS.md-Regel: Der Regressionstest muss vor dem Fix
fehlschlagen und nach dem Fix bestehen. Bestehende Tests, die widersprüchliche
Altregeln festschreiben, werden fachlich ersetzt und nicht nur entfernt.
Jede Änderung an Anwendungscode muss anschließend weiterhin 100 % Zeilen- und
100 % Branch-Abdeckung erreichen. Konfigurations- und Verhaltensänderungen erhalten
passende Beispiele und Dokumentation.
