# Zustandsregeln und Testnachweise für 3.6

Stand: 3. November 2026. Verbindlicher Bestandteil der
[Projektspezifikation](../Mailhelp-Projektspezifikation.md), Schritte 1.1 und 1.2.

## Review und Command-Inbox

Der Bedien-Thread serialisiert Web und Telegram mit der Dialogsperre. Der Mailabruf kann
gleichzeitig Vorschläge abgleichen. Nach langsamen Vorprüfungen wird deshalb die gesamte
maßgebliche Vorschlagsakte unter `store.locked()` erneut mit dem zuvor geprüften Stand
verglichen. Prüfung und Speichern sind ein kritischer Abschnitt. Abweichungen führen zum
sichtbaren Konflikt. Netzwerkaufrufe liegen außerhalb der Store-Sperre; Sperrfolge:
Dialog → Store → Blattsperren. Sitzungsprüfungen erfolgen außerhalb der Store-Sperre (Auth → Store).

| Zustand | Bedeutung und nächste Grenze |
| --- | --- |
| HTTP-Anfrage | Sitzung, sitzungsgebundenes CSRF, Version und Idempotenzschlüssel prüfen; keine fachliche Freigabe |
| `queued` | Befehl einschließlich Akteur und Version dauerhaft angenommen; reserviert noch keine Vorschlagsversion |
| `running` | Vor dem ersten fachlichen Effekt gespeichert; Sitzung und Vorschlagsstand erneut prüfen |
| `done` / `rejected` / `failed` | Ergebnis, Abschlusszeit und Status dauerhaft anzeigen |
| Nach Neustart noch `running` | Wirkung abgleichen, niemals blind wiederholen; sichtbare Wirkung ergibt `done`, sonst erneute Nutzerprüfung |

Identische Anfragen derselben Sitzung erhalten während der Verarbeitung und nach Abschluss
denselben Inbox-Eintrag. Ein Schlüssel mit geändertem Inhalt oder Akteur wird abgewiesen.
Abgeschlossene Einträge bleiben einen Tag erhalten; danach schützen Vorschlagsstatus und
Ledger weiter gegen Doppelanlage. Speichern, Bearbeiten, Zusammenführen und Wiederherstellen
erzeugen keine externe Freigabe. Neue Versionen müssen separat ausdrücklich bestätigt werden.

| Konkurrenz | Erste Reihenfolge | Umgekehrte Reihenfolge |
| --- | --- | --- |
| Web / Telegram bestätigen | Web legt höchstens einmal an; Telegram erhält veraltete Schaltfläche | Telegram legt höchstens einmal an; Web erhält Konflikt |
| Zwei Websitzungen | Erster Befehl gewinnt, auch bei unterschiedlichen Schlüsseln | Anderer Befehl gewinnt, gleicher Dublettenschutz |
| Bearbeiten / Bestätigen | Neue unbestätigte Version; alte Bestätigung veraltet | Bestätigte oder laufende Version nicht überschreiben |
| Verwerfen / Bestätigen | Verworfene Version nicht ausführen | Laufende Anlage nicht scheinbar zurücknehmen |
| Merge / Bestätigen | Kanonische Revision und Alias ändern die Version; alte Freigabe veraltet | Bereits bestätigte Quelle oder Ziel nicht zusammenführen |
| Sitzungswiderruf / Schreiben | Ungültige Sitzung vor Schreibbeginn blockiert | Bereits begonnene Anlage nur abgleichen |
| Wiederholte Anfrage | Gleicher Eintrag mit laufendem Status | Gleicher Eintrag mit gespeichertem Ergebnis |

## Schreibausführung und Ledger

| Status | Regel |
| --- | --- |
| `pending_confirmation` / `needs_clarification` | Keine Anlage; nur vollständige erlaubte Version ausdrücklich bestätigen |
| `confirmed` | Dauerhafte Freigabe; aktuelle Akte, Ziel und Autorisierung vor Schreibbeginn erneut prüfen |
| `writing` | Schreibgrenze dauerhaft überschritten; ausschließlich abgleichen |
| `uncertain` | Resultat unbekannt; auch leerer oder fehlerhafter Abgleich erlaubt keine automatische Wiederholung |
| `created` | Externe ID gespeichert; Mailprojektion und Ledger idempotent vervollständigen |
| `failed` / `rejected` / `merged` | Keine automatische Neuanlage |

`confirmed_web_actor` bindet neue Web-Freigaben dauerhaft an die nicht geheime Sitzungs-ID.
Ein frischer Prozess prüft dieselbe Sitzung erneut. Auch nach langsamer Provider-Vorbereitung
werden Sitzung und aktuelle Akte unmittelbar vor der Schreibgrenze geprüft. Eine ungültige
Freigabe bleibt blockiert. Lesender Abgleich einer möglicherweise bereits ausgeführten
Aktion bleibt zulässig. Historische Akten ohne dieses additive Feld bleiben lesbar.
Noch `confirmed` gespeicherte Altakten werden nur anhand eines passenden ausgeführten
Web-Bestätigungsbelegs aus der Command-Inbox an die ursprüngliche Sitzung gebunden.
Ein passender ausgeführter Telegram-Beleg gilt nur für die weiterhin konfigurierten Nutzer- und Chat-IDs.
Fehlende alte Metadaten werden schon beim Lesen als ungeprüft markiert, damit auch eine
unterbrochene Schema-Migration keine scheinbar neue Telegram-Freigabe erzeugt.
Fehlt dieser Nachweis, bleibt die Anlage als „Freigabe des Altbestands nicht prüfbar“
gesperrt; Einreihen allein ersetzt keinen Ausführungsbeleg. Bereits erfolgte Anlagen werden
weiterhin lesend abgeglichen. Eine ungültige Freigabe wird pro Version und Prozess nur einmal gemeldet.

Externe Identität: `mailhelp:<mail>:<vorschlag>:v<version>`, unabhängig vom HTTP-Schlüssel.
Reihenfolge: Abgleich → Provider-Vorbereitung → Autorisierung prüfen → `writing` speichern →
Provider-Aufruf → `created` speichern → Verlauf/Mailprojektion → Ledger.
Bei einer Operation ohne Schreibbedarf entfällt die `writing`-Grenze. Ungültige Antworten
oder temporäre Lesefehler erzeugen keine neue Freigabe. Nur ein noch `confirmed` gespeicherter
Auftrag darf bei gültiger Autorisierung erstmals schreiben.

`save_revision` schreibt zuerst den unveränderlichen Versionsbefund, dann die aktuelle Akte,
danach Verlauf und Mail-/Abrufprojektionen. Der Versionsbefund ersetzt keinen aktuellen
Ausführungsstatus. `persist(created)` ergänzt das Ledger, höchstens einmal je Version.
Nach A4 repariert `resume()` diese lokale Buchführung ohne externen Schreibaufruf.

## Merge und beschädigte Akten

Ein Merge speichert `prepared` mit beiden Ausgangsversionen und beiden Revisionen,
dann die kanonische Akte, die Aliasakte und zuletzt `completed`.
`source_was_present` unterscheidet eine neue ungespeicherte Quelle von einer nachträglich
fehlenden maßgeblichen Quellakte. Neue Revisionen verweisen mit `reconciliation_journal`
auf ihr Journal; dessen Verlust bleibt auch nach A6/A7 sichtbar. Wiederherstellung prüft
beide Akten vollständig und überschreibt keine zwischenzeitliche Entscheidung, Änderung
oder geschützten manuellen Werte. Ein weiterer Neustart verändert das konsistente Ergebnis nicht.
KI-Revisionen dürfen weder Journalverweise noch Sitzungsbindungen ändern; beide Felder
sind an der Grenze für Revisionsnachfolger als anwendungseigene Metadaten geschützt.

`.corrupt` und `.invalid` ersetzen bei Vorschlägen, Mails, Inbox, Ledger und Merge-Journal
niemals einen leeren Bestand. Auch beim Inventarisieren bleiben isolierte Vorschläge und
Journale sperrend. Ein reparierter gültiger JSON-Ersatz kann wieder verwendet werden;
die isolierte Datei bleibt als Beleg. Optionale rekonstruierbare Daten wie der Absenderfilter
dürfen weiterhin ersetzt werden.

Auch die Bindung von Dateiname, Ursprungsmail und Vorschlags-ID wird geprüft. Eine
falsch benannte Akte darf beim Neustart keine fehlende maßgebliche Akte ersetzen.

Die Webübersicht berücksichtigt zusätzlich Dateinamen, Änderungszeiten und Größen der
JSON-Dateien. So bleibt externe Beschädigung auch bei zusammenfallenden Verzeichniszeitstempeln
sichtbar; die gecachten Inhalte werden bei unveränderten Metadaten weiterverwendet.
Fehler beim sicheren Serialisieren unzuverlässiger Mailkopfzeilen werden vor dem
IMAP-Zugriff als Eingabefehler gemeldet; lokal gespeicherter Entwurfstext bleibt erhalten.

## Testinfrastruktur (1.3–1.5)

- `tests/fakes/safety_harness.py`: `Gate` mit Events, 20 Sekunden Frist, Freigabe im
  `finally` und begrenztem Warten. Fehler werden weitergereicht; kein `sleep()` zur Synchronisation.
- `PersistentWriter`: Unabhängige JSON-Datei mit Einträgen und vollständiger Aufrufhistorie,
  atomar und mit fsync gespeichert. Kann nach Übernahme einer Anlage die Antwort zurückhalten.
  Abgleichmodi: Treffer, kein Treffer, temporärer Fehler, ungültige Antwort.
- `ProcessHarness`: Auf beiden Plattformen ausdrücklich `spawn`, echter `JsonStore` mit
  Betriebssperre, Pipe für benannte Haltepunkte, `Process.kill()` und begrenztes `join()`.
  Fehlgeschlagene Elternassertions räumen Kindprozesse auf.
- `tests/scenarios/safety_process.py`: Ausführung über `poll_once`, `CommandInbox` und echte
  Review-/Schreib-/Merge-Dienste. Instrumentiert werden vorhandene Persistenzgrenzen und
  der simulierte Provider. Keine künstlichen Persistenzgrenzen im Anwendungscode.
- Coverage startet auch im Kindprozess und wird vor Bestätigung des Haltepunkts gespeichert.
  pytest-cov kombiniert die parallelen Dateien. `test_safety_harness.py` liest zusätzlich
  Coverage einer hart beendeten Anwendung und prüft Zeilen und Branch-Arcs.

| ID | Haltepunkt | Erwartung nach zwei frischen Neustarts |
| --- | --- | --- |
| A1 | `confirmed` gespeichert, Provider-Aufruf nicht begonnen | Nur bei gültiger Freigabe erstmals schreiben |
| A2 | Provider hat Anlage übernommen, Antwort zurückgehalten | Treffer übernehmen; unklarer Abgleich führt zu keinem zweiten `create` |
| A3 | Antwort empfangen, `created` noch nicht gespeichert | Wie A2; externe Identität erkennen |
| A4 | Aktuelle Akte `created`, Projektion/Ledger offen | Lokale Buchführung vervollständigen |
| A5 | Journal `prepared`, kanonische Akte unverändert | Beide Revisionen herstellen |
| A6 | Kanonische Revision gespeichert, Alias fehlt | Alias und Journal vervollständigen |
| A7 | Beide Revisionen gespeichert, Journal offen | Journal abschließen, Quellen und manuelle Werte erhalten |

`test_parallel_safety.py` prüft P1–P7, beide Konfliktreihenfolgen, unabhängige Websitzungen,
Version/Status/Inbox/Ledger/Mailprojektion und Nutzerrückmeldung. Jeder P-Fall erhält gültige,
fehlende, falsche und sitzungsfremde CSRF-Eingaben. `test_ui_parallel_safety.py` prüft sichtbare
Konflikte mit zwei Browserkontexten in beiden Reihenfolgen. `test_process_safety.py` prüft
A1–A7, alle vier Abgleichmodi bei A1–A4, Sitzungswiderruf/-ablauf sowie beschädigte und fehlende Akten.

## Antwortzeiten während des Abrufs (0.6)

`review.command_finished` protokolliert `latency_ms` (Einreihen bis Abschluss) und
`execution_ms` (Ausführungsdauer). `command_id` verbindet Einreichen und Abschluss,
ohne Mailinhalte, Sitzungstokens oder Zugangsdaten zu protokollieren.
`test_operator_decoupling.py` betreibt Mailabruf und Bedien-Thread gleichzeitig, hält eine
synthetische Analyse an einem Event und liest die tatsächlichen JSONL-Ereignisse.
Die Aktion muss abgeschlossen sein, während die Analyse weiterhin blockiert ist.

Windows-Messung vom 3. November 2026: **125,102 ms** bis zum Abschluss,
**86,667 ms** Ausführung. Betriebsnachweis mit simulierten externen Diensten;
keine Messung der Latenz eines Produktivkontos. Der Test gibt mit `pytest -s`
den vollständigen synthetischen `command_finished`-Datensatz aus.

## Ausführen

Gesamtabnahme: `python -m pytest --cov=mailhelp --cov-branch --cov-fail-under=100`,
`python -m ruff check` und `python -m mypy`. Die bestehende CI-Matrix prüft Windows und Ubuntu.
Gezielt: `python -m pytest tests/services/test_parallel_safety.py
tests/services/test_process_safety.py tests/services/test_safety_harness.py
tests/services/test_safety_regressions.py --no-cov`.
Browser: `python -m pytest ui_tests/test_ui_parallel_safety.py --no-cov -k two_contexts`.
Alle Daten und Adapter sind synthetisch; Produktivzugriffe sind nicht erforderlich.
