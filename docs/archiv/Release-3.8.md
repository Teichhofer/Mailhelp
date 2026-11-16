# Mailhelp 3.8 – Web-Lernmodus und Betrieb

Arbeitsstand 3.8.28, 4. November 2026. Die Gesamtabnahme ist bestanden (Abschnitt
„Abnahme“). 4.0.0 wird hier nicht veröffentlicht.

## Lernen im Browser

Nach der Anmeldung `/lernen` öffnen. Postfach, Ordner (ein Name je Zeile), Anzahl
Mails, Preisobergrenze in USD je Million Tokens und Gesamtbudget wählen. Die
verfügbare Ordnerliste stammt aus dem letzten Postfachabruf. Zunächst die Schätzung
anzeigen und erst danach den kostenpflichtigen lesenden Lernlauf ausdrücklich starten.

Die Schätzung reserviert konservativ Eingabe, Ausgabe, Routen und Reparaturen.
Die Preisobergrenze muss die tatsächlich verwendeten Modelle einschließlich Ausgabe
und Reasoning abdecken. Sie ist eine Annahme des Benutzers, keine garantierte
Anbieterabrechnung. Jeder tatsächliche Modellaufruf reserviert vor dem Netzwerkzugriff
Tokens einschließlich möglicher Transportwiederholungen. Reservierungen bleiben nach
Abbruch oder verlorener Antwort erhalten. Ein nicht ausreichendes Budget pausiert den
Lauf; für andere Preisannahmen oder mehr Umfang einen neuen Lauf starten.

Der Lernlauf verwendet eigene IMAP-Verbindungen und verändert keine Mailflags.
Pause und Abbruch greifen an den Aufruf- beziehungsweise Mailgrenzen. Nach Neustart
wartet der persistierte Lauf auf eine ausdrücklich bestätigte Fortsetzung mit gültiger
Sitzung. Bereits abgeschlossene Mails werden nicht nochmals analysiert; eine beim
Absturz laufende Analyse kann erneut nötig sein. Zwischenstände enthalten Kategorien,
Betreffbelege und Absender, keine Zugangsdaten oder vollständigen Mailtexte.

Jeder neue Lauf besitzt eine eigene Generation. Ein sofortiger Neustart nach
„Abbrechen“ kann daher keine Ergebnisse, Reservierungen oder Fehlermeldungen aus
dem vorherigen Lauf übernehmen, auch wenn dessen Netzwerkantwort noch unterwegs ist.

Im Review jede Karte bearbeiten und als Thema, Ausschlussthema oder „Nicht übernehmen“
auswählen. Die Zuordnung gilt zunächst nur für das gewählte Postfach; „Für alle
Postfächer“ erweitert sie ausdrücklich. Absender werden ausschließlich bei gewähltem
Ausschlussthema und zusätzlichem Häkchen ignoriert. Änderungen als Entwurf speichern.
Zusätzliche Ordner werden separat ausgewählt; die Rollen `junk` und `trash` sind
anfangs abgewählt. Erst „Ausgewählte Themen, Filter und Ordner ausdrücklich übernehmen“
schreibt die vier lokalen Dateien gemeinsam. Das Journal vervollständigt unterbrochene
Übernahmen bei Wiederanlauf. Bei fremden Dateiänderungen stoppt die Wiederherstellung.

Die Terminalalternative `mailhelp --learn ANZAHL` bleibt erhalten und verwendet
denselben Klassifikationskern. Keine Lernaktion legt Termine oder Aufgaben an.

## Neuladen und Selbsttest

Unter `/dienst/neu-laden` den gespeicherten Stand ausdrücklich übernehmen. Der nächste
sichere Mailzyklus bereitet eine vollständige neue Laufzeitgeneration vor: Themen,
Prompts, Postfachänderungen und entfernte Postfächer, Zugangsdaten sowie Zielprofile
und OAuth-Tokens. Offene Vorschläge bleiben an ihre bisherige Version und ihr Ziel
gebunden; das Neuladen autorisiert keine neue Anlage.

Unfertige Mailanalysen und Warteschlangen werden unter ihrer ursprünglichen
Konfiguration abgeschlossen. Bei wartender Relevanzentscheidung diese zuerst
beantworten; bei Analysefehlern zuerst die Ursache beheben beziehungsweise erneut
prüfen. Es werden keine halben Analysen mit einem neuen Fingerprint liegen gelassen.
Hintergrunddienste werden angehalten, laufende Bedienaktionen dürfen abschließen.
Neue Adapter werden aufgebaut und lesend geprüft. Sitzung und Dateistand werden vor
der Aktivierung nochmals geprüft; ein Fehler erhält die bisherige Generation.
Danach wechseln die HTTP-Routen am bestehenden Socket, und alte Verbindungen schließen.

Änderungen am Web-Zugang einschließlich Sitzungsschlüssel, Web-Konfiguration,
Datenverzeichnis oder Test-/Produktivmodus erfordern weiterhin einen Prozessneustart.
Diese Grenzen werden beim Neuladen abgelehnt. Prozessvariablen haben weiterhin Vorrang
vor `.env`. Der erste Einrichtungsabschluss aktiviert dagegen den Normalbetrieb im
selben Prozess und bietet den Link zum Lernmodus an.

`/dienst/selbsttest` prüft alle Komponenten lesend im Hintergrund. Die Diagnose
enthält je Komponente Ergebnis und Handlungsempfehlung. Die ausdrücklich separaten
Telegram-, Push- und kostenpflichtigen Modell-Testaktionen werden dabei ausgelassen.
`/status` zeigt die erfassten Cloudkosten des laufenden Monats in der konfigurierten
Zeitzone, Aufrufe ohne Preisangabe und die letzte beobachtete Abfrage je Postfach.

## Sicherheits- und Anbietermatrix

`tests/external/test_provider_safety_matrix.py` verwendet Produktionsadapter mit
unabhängig gespeichertem synthetischem HTTP-Dienstzustand. Anbieter sind Google
Kalender, Todoist, Outlook-Kalender, Microsoft To Do, CalDAV-Kalender und -Aufgaben
sowie Apple Erinnerungen. Es werden keine echten Konten oder Daten verwendet.

| Szenario | Nachweis |
| :--- | :--- |
| P1 | Web- und Telegram-Bestätigung derselben Version in beiden Reihenfolgen |
| P2/P7 | Wiederholung während der tatsächlichen HTTP-Schreiboperation; gleiche Command-ID, höchstens eine Anlage |
| P3/P4 | Bearbeiten beziehungsweise Ablehnen vor alter Bestätigung; alte Version schreibt nicht |
| P5 | Zusammenführen und anschließende alte Bestätigung; neue Version bleibt unbestätigt |
| P6 | Widerruf vor Ausführung und erneute Autorisierung an der Adaptergrenze |
| CSRF | Fehlender oder ungültiger Schutz verhindert jede externe Aktion |
| A1–A4 | Harter Abbruch vor Schreiben, nach externem Erfolg, vor und nach lokaler Erfolgsmarkierung; zwei frische Neustarts |
| Verlorene Antwort | Echtes Transport-Timeout nach persistiertem Erfolg, anschließend lesender Abgleich mit frischen Adaptern |
| Zieländerung/Testmodus | Keine externe Anfrage bei abweichendem bestätigtem Ziel oder Testmodus |
| Kalenderänderung/Storno | Bestehende Ressource ändern; Google/CalDAV stornieren im Kalenderformat, Outlook löscht den Termin |
| A5–A7 | Bestehende gemeinsame Merge-Journal-Prüfungen laufen erneut in der Gesamtsuite |

Aufgabenänderung und -löschung sind keine unterstützten Mailhelp-Operationen; dafür
werden keine fiktiven Erfolgsszenarien behauptet. Harte Kalenderlöschung ist nur beim
Outlook-Stornoweg vorgesehen. Google und CalDAV verwenden eine bestätigte Stornierung.
Eine unklare Änderung einer bestehenden CalDAV-Ressource wird nicht blind wiederholt;
der deterministische Neuanlagepfad lässt sich über seine Ressourcenadresse abgleichen.

## Abnahme

Geprüfter Stand: Commit `0cc4aa0` (3.8.27). Alle Prüfungen verwenden ausschließlich
simulierte Dienste und synthetische Daten; es wurden keine echten Termine oder Aufgaben
angelegt. Die Linux-Prüfungen liefen in einem eigenen nativen Ubuntu-Verzeichnis
(WSL 2, Ubuntu 24.04) unter dem unprivilegierten Benutzer `nobody`.

### Plattformen

| Prüfung | Plattform | Ergebnis |
| :--- | :--- | :--- |
| Vollständige Python-Suite | Windows 11, Python 3.12.10 | 3.210 bestanden; 100 % Zeilen- und 100 % Branch-Abdeckung |
| Vollständige Python-Suite | Linux, Python 3.12.3 | 3.209 bestanden, 1 übersprungen¹; 100 % Zeilen- und 100 % Branch-Abdeckung |
| Browser: Desktop, Mobilgeräte, ohne JavaScript | Windows 11, Chromium | 219 bestanden; 100 % JavaScript-Blockabdeckung für `app.js`, `sw.js`, `setup.js` |
| Installiertes Wheel 3.8.27: Paketinhalt, CLI, Lernmodus, Neuladen, Browserbedienung, Anbietermatrix, Prozessabbrüche | Windows 11 | 333 bestanden |
| Installiertes Wheel 3.8.27 (unter Linux gebaut), gleiche Auswahl | Linux | 333 bestanden |
| Docker (`container-smoke` aus der CI) | Linux, Docker 29.1.3, Compose 2.40.3 | Image gebaut; `--check`, Start und Neustart im frischen Container, Lernen und Prüfung im frischen Container, harter Abbruch mit zwei Neustarts: 28/28 bestanden |
| Statische Prüfungen | Windows 11 | `ruff check src tests ui_tests` ohne Befund; `mypy` ohne Befund in 223 Quelldateien |

¹ `test_built_artifacts_exclude_private_runtime_files` setzt gebaute Artefakte voraus und
wird im Paketlauf geprüft; dort ist er auf beiden Plattformen bestanden.

### Szenarien nach Q4.6

Anbieter: Google Kalender, Todoist, Outlook-Kalender, Microsoft To Do, CalDAV-Kalender,
CalDAV-Aufgaben und Apple Erinnerungen (7). Testreferenzen beziehen sich auf
`tests/external/test_provider_safety_matrix.py` (M) und `tests/services/test_process_safety.py` (S).
Jedes Szenario lief auf Windows und Linux, jeweils im Quellstand und gegen das installierte Wheel.

| Szenario | Anbieter / Operation | Testreferenz | Fälle je Plattform | Ergebnis |
| :--- | :--- | :--- | ---: | :--- |
| P1 | alle 7 / Anlage; Web und Telegram bestätigen dieselbe Version, beide Reihenfolgen | M `test_both_channels_confirm_same_version_with_real_provider_adapter` | 14 | bestanden, höchstens eine Anlage |
| P2–P7, CSRF | alle 7 / Anlage; Wiederholung während HTTP-Schreiben, Bearbeiten/Ablehnen vor alter Bestätigung, Zusammenführen, Widerruf, fehlender CSRF-Schutz | M `test_parallel_safety_scenarios_with_actual_adapters` | 49 | bestanden |
| Autorisierung | alle 7 / Anlage; widerrufene Sitzung, abweichendes Ziel, Testmodus, unklarer fehlender Eintrag | M `test_actual_adapters_never_write_without_current_matching_authorization` | 28 | bestanden, keine externe Anfrage |
| Verlorene Antwort | alle 7 / Anlage; Abgleich mit frischen Adaptern vor jeder Wiederholung | M `test_actual_adapters_reconcile_persisted_result_before_any_retry` | 14 | bestanden |
| A1–A4 | alle 7 / Anlage; harter Abbruch vor/nach externem Erfolg und lokaler Markierung, zwei Neustarts | M `test_hard_kill_matrix_reconciles_real_adapter_after_two_restarts` | 28 (+ 28 in Docker) | bestanden |
| A1–A4 (Persistenz) | gemeinsame Schreibschicht | S `test_write_crash_and_two_restarts`, `test_a2_missing_or_damaged_authorities_never_repeat_provider_write`, `test_fresh_process_does_not_replace_web_authorization` | 30 | bestanden |
| A5–A7 | gemeinsames Merge-Journal; Abbruch, beschädigte und geänderte Ziele, Quarantäne | S `test_merge_crash_and_two_restarts_preserve_sources_and_manual_values`, `test_merge_recovery_*`, `test_quarantined_merge_journal_blocks_later_restarts` | 15 | bestanden |
| Änderung / Storno | Google Kalender, Outlook-Kalender, CalDAV-Kalender / Änderung und Absage bestehender Termine | M `test_supported_calendar_change_and_cancellation_use_existing_resource` | 6 | bestanden |

### Gefundene Fehler

| Fehler | Fund | Behebung | Regressionstest |
| :--- | :--- | :--- | :--- |
| Vorschläge „Nachricht manuell prüfen“ (ID `manual_attachment_<Mail-ID>`, 42 Zeichen) ließen sich weder verwerfen noch bestätigen; Web und Telegram meldeten „Die Eingabe ist ungültig.“ | Produktivbetrieb, Anwendungslog (`command_finished … status: invalid`) | 3.8.27: Entscheidungsmodell akzeptiert wie `Proposal.id` 64 Zeichen; abgewiesene Befehle protokollieren `command_refused` mit Feldnamen | `tests/web/test_long_proposal_ids.py`; vor dem Fix mit `string_pattern_mismatch` fehlgeschlagen, danach bestanden |
| Branch „Neuladen ohne Diagnosedienst“ in `ReloadService.helpers` ungetestet; die 100-%-Prüfung schlug fehl | Abnahmelauf mit Coverage | 3.8.27: Test ergänzt (kein Verhaltensfehler) | `tests/services/test_runtime_reload.py::test_helpers_stop_before_swap_and_start_afterwards` |

### Begründete Einschränkungen

- Aufgabenänderung und -löschung sind keine unterstützten Mailhelp-Operationen; dafür gibt
  es keine Szenarien. Harte Kalenderlöschung gibt es nur beim Outlook-Stornoweg; Google
  und CalDAV stornieren im Kalenderformat (siehe „Sicherheits- und Anbietermatrix“).
- Echte Konten, OAuth-Zustimmungen und externe Verbindungen gehören nicht zur
  automatisierten Abnahme.
- Docker lief unter WSL 2 auf dem Entwicklungsrechner, nicht auf einem eigenständigen
  Linux-Host. Der gleiche Ablauf ist als CI-Job `container-smoke` hinterlegt.
- Die GitHub-CI (Windows und Linux) wurde für diesen Stand nicht ausgelöst, weil nicht
  gepusht wurde; ihre Schritte wurden lokal nachgestellt.

Die XML-Berichte liegen unter `.test-tmp-38/` (`ui-results.xml`, `linux-results.xml`,
`linux-coverage.json`, `wheel-results.xml`, `linux-wheel-results.xml`, `docker-output.txt`).
