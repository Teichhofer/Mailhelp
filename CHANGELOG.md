# Änderungen

## 2.2.0 – Beta (Branch `beta`), Tätigkeitsbericht

- **Neu – Tätigkeitsbericht (`/berichte`):** Für ein Thema und einen Zeitraum liest Mailhelp die Mails der gewählten und der gesendeten Ordner schreibfrei, überspringt ignorierte Absender, Duplikate und verdächtige Mails, lässt jede übrige per KI auf das Thema prüfen (`activity_relevance`, mit `personal_info` als Kontext) und extrahiert aus relevanten Mails alle datierten Termine, auch vergangene (`activity_events`, wörtlicher Beleg je Termin). Zählen und kostenpflichtiger Start sind getrennt; Pausieren, Fortsetzen, Abbrechen und Neustart setzen an der nächsten Mail an.
- **Prüfen und korrigieren:** Termine chronologisch mit Quellmail, relevante Mails ohne Termin, „Doch relevant“ für abgelehnte Mails, Termine bearbeiten, ausschließen und ergänzen – mit Sitzungs-, CSRF-, Versions- und Idempotenzprüfung, ohne JavaScript bedienbar.
- **xlsx-Export:** Blätter „Termine“, „Ohne Termin“ und „Bericht“; Mailinhalte werden nie zu Formeln. Neue Abhängigkeit `openpyxl` (gepinnt).
- **Konfiguration:** Abschnitt `activity_report` (standardmäßig aus) und `retention.activity_report_days` (365); neue Prompts in `prompts.yaml`. Kein Analyse-Fingerprint ändert sich.
- **PWA:** Cache-Name `mailhelp-shell-v3`, damit installierte Apps das neue Stylesheet laden.
- Details: [Release-2.2.md](docs/Release-2.2.md).

## 2.1.1 – Beta (Branch `beta`)

- **Testkorrektur:** Der Kerntest prüfte noch die fest eingetragene Version 2.0.3 und brach in 2.1.0 vor seinen übrigen Prüfungen ab (Abdeckung 99,95 %). Er prüft jetzt nur das Format; die Übereinstimmung mit `pyproject.toml` sichert `test_release_package`.

## 2.1.0 – Beta (Branch `beta`), Planung 2.1 Abschluss

- **Modularisierung großer Komponenten (A4, A5, A6):** `MailhelpSite` in spezialisierte Teil-Sites zerlegt (`LoginSite` für Koppelung und Geräte, `ReviewSite` für offene Entscheidungen und Vorschläge, `ArchiveSite` für Archiv und Einstellungen). Seitenaufbau ohne `page.replace("</main>", ...)` über strukturierte Parameter. Modulgrößen gestrafft (Funktionen ≤ 80 Zeilen, Klassen ≤ 20 Methoden).
- **Fehlerbehandlung und Schnittstellen (A7, A8):** Einheitliche Ausnahmehierarchie für externe Dienste (`ExternalServiceError`, `ExternalUnavailable`, `ExternalRefused`, `ExternalUncertain`) in `external/contracts.py`. Neuer Helfer `log_and_continue` für prozessgrenzenübergreifende Fehlerprotokollierung. Zentrales Zeitformatierungsmodul `formatting.py` (`%d.%m.%Y, %H:%M Uhr`).
- **Einheitliche Bilderkennung (A8):** Bildvorschau in `attachments.py` und Texterkennung in `vision.py` nutzen dieselbe Funktion `is_image(filename, content_type)`. Regressionstest `test_raster_cache_matches_image_by_filename_extension` sichert Erkennung über Dateiendungen ab.
- **Bereinigte Client- und Einstellungsattribute (A8):** `getattr`/`hasattr`-Weichen auf Settings und Clients (`primary_folder`, `service_name`, `last_relevance_source`) durch feste Attribute und Protokolle ersetzt.
- **Browsertests & Stabilität (T7):** Automatisches Sammeln der Browser-Coverage vor jeder Navigation über DevTools-Hooks; konfigurierbare Rückgängig-Frist im Testserver via `data-undo-ms`. Alle 98 UI-Browsertests stabil.
- **Statische Analyse (A1):** `ruff` und `mypy --strict` auf dem Kern (`domain/`, `external/contracts.py`, `drafts.py`, `webpush.py`, `briefing.py`, `attachments.py`) fehlerfrei. Durchgängig `from __future__ import annotations`.
- **Qualitätssicherung:** 100 % Zeilen- und Branch-Abdeckung über alle 125 Module (1.721 Tests) verbindlich erreicht. Detaillierte Dokumentation in [Architektur-2.1.md](docs/Architektur-2.1.md) und [Release-2.1.md](docs/Release-2.1.md).

## 2.0.3 – Beta (Branch `beta`), Planung 2.1 Phase 3

- **Bugfix – Kalendereinladungen:** Der ICS-Parser löste Escape-Sequenzen nacheinander auf; ein maskierter Backslash vor `n`/`N` wurde so zum Zeilenumbruch (aus `C:\\new\\Nordsee` in einer Einladung wurde `C:\` + Umbruch + `ew\` + Umbruch + `ordsee`). Jetzt in einem Durchlauf; Regressionstest `test_an_escaped_backslash_before_n_stays_a_backslash`. Gefunden durch die neuen eigenschaftsbasierten Tests.
- **Typisierte vorbereitete Mail (A3):** Lesemodelle `PreparedMail`, `MailHeaders`, `PreparedAttachment`, `ImagePreview` (`domain/prepared.py`) über `MailState.prepared`. Orchestrator, Mail- und Archivansicht, Anhangsdarstellung und Antwortentwürfe lesen typisiert statt über Zeichenkettenschlüssel; die Dict-oder-Objekt-Weiche der Anhangsanreicherung entfällt. Gespeichert und an das Sprachmodell gesendet wird unverändert das bisherige Dict (Dateien und Anfragen byte-gleich). Beschädigte optionale Werte gelten wie bisher als fehlend. Die Duplikatsignatur rechnet bewusst weiter auf dem gespeicherten Dict.
- **Tests über öffentliche Schnittstellen (T3):** Keine Tests mehr über `Application._poll_imap`, `_poll_imap_global`, `_resume_pending`, `_complete_resumed_run_entry` oder `TelegramDialogController._decide`; diese reinen Durchreicher sind entfernt, `MailboxRunService.run_counters` ist öffentlich. Telegram-Befehle laufen in den Usability-Tests über `poll_once()`; nur Tests, die den Zustand zwischen Empfang und Weiterverarbeitung prüfen, nutzen `_handle` mit Begründung. Alle 282 Anweisungsketten mit `;` sind aufgelöst (AST-geprüft unverändert). `test_models_and_config` und der Darstellungstest für Terminänderung/Duplikat sind in benannte Einzeltests geteilt; `test_storage_windows_directory_sync` prüft jetzt ausdrücklich. Offen: 18 weitere Tests über 60 Zeilen.
- **Eigenschaftsbasierte Tests (T6):** `hypothesis` (gepinnt) prüft MIME-Vorbereitung beliebiger Bytes, Payload-Grenzen, Header-Injektion in Antwortentwürfen, zulässige Push-Anbieter, ICS-Escaping und -Faltung als Rundreise, Datumsparser und den Telegram-Zeitparser.

## 2.0.2 – Beta (Branch `beta`), Planung 2.1 Phase 2

Keine Verhaltensänderung für Nutzer; gespeicherte Zustände bleiben byte-gleich lesbar.

- **Speicher-Protokoll (A2):** `StateStore` (`typing.Protocol`) beschreibt, was Dienste vom Zustandsspeicher brauchen. Alle `hasattr`/`getattr`-Weichen auf den Store in `application`, `mailbox_run`, `orchestrator` und `telegram/*` sind entfernt; sie existierten nur für unvollständige Test-Fakes. `drafts` und `webpush` sperren über `store.locked()` statt `store._thread_lock`.
- **Zentrale Zustandsnamen (A2):** Neues Modul `state_names.py` (`mail`, `mail_run`, `draft`, `proposal`, `clarification`, `mail_state_names` …) ersetzt die verstreuten Namensmuster; ein Vertragstest hält die Muster byte-gleich.
- **Telegram-Client:** Die `getattr`-Weiche für Logger ohne `telegram_event` entfällt; das `EventLogger`-Protokoll verlangt die Methode.
- **Gemeinsame Test-Doubles (T2, Beginn):** `tests/fakes/store_fakes.py` (`DelegatingStore`, `InterruptingStore` über einen echten `JsonStore`) und `tests/fakes/log_fakes.py` (`RecordingLogger`, prüft die Log-Stufe wie der echte Logger) ersetzen sieben gleichartige Kopien.
- **Wirkungsloser Test korrigiert:** Der Test „Push-Zustellung hält keine Sperre“ prüfte die re-entrante Store-Sperre im selben Thread und hätte nie scheitern können. Er prüft jetzt aus einem zweiten Thread und schlägt bei gehaltener Sperre nachweislich an.
- **Upgrade-Verträge (T5):** `tests/upgrade/states/` enthält echte Zustände der Releases 1.1–2.0, erzeugt von deren eigenem Ende-zu-Ende-Test aus dem jeweiligen Release-Commit (je vier Szenarien). Geprüft wird: verlustfreies Laden ohne Quarantäne, kein erneuter Schreibzugriff auf Kalender/Todoist und keine erneute Analyse nach einem Neustart. JSON-Schema-Snapshots aller gespeicherten Modelle lassen jede ungeplante Formatänderung scheitern.

## 2.0.1 – Beta (Branch `beta`), Planung 2.1 Phase 1

Keine Verhaltensänderung für Nutzer.

- **Statische Prüfung (A1):** `ruff` und `mypy` sind in `pyproject.toml` konfiguriert (strikter Kern: `domain`, `external.contracts`, `drafts`, `webpush`, `briefing`, `attachments`). Die CI meldet die Befunde in einem eigenen Job, ohne vorerst zu scheitern. Ausgangsbestand: 1.312 ruff-Befunde (Anwendungscode 663) und 490 mypy-Fehler.
- **Abhängigkeiten (T8):** Neuer Test `tests/release/test_dependency_lock.py` prüft, dass die Lock-Dateien die vollständige installierte Abhängigkeitshülle festschreiben. Er fand `colorama` (pytest unter Windows), das bisher ungepinnt installiert wurde; es ist jetzt mit Plattform-Marker gepinnt. Die Werkzeuge für die statische Prüfung stehen in `requirements-lint.lock` und gelangen nicht ins Container-Image.
- **CI (T8):** Laufzeitbericht der 20 langsamsten Tests; wöchentlicher Workflow mit `pip-audit` gegen beide Lock-Dateien.
- **Tests nach Fachgebiet (T1):** Die Testmodule liegen jetzt in `tests/unit`, `services`, `telegram`, `web`, `external`, `evaluation`, `upgrade`, `e2e`, `release` und `scenarios`. Inhaltlich unverändert bis auf repo-relative Pfade; gleiche Testanzahl und 100 % Abdeckung. Pfade in CI, Compose-Smoke-Dateien, README und Architekturdokument angepasst.

## 2.0.0 – Beta (Branch `beta`)

- **Einstellungshilfe:** Alle Web-Konfigurationswerte erhalten Info-Blasen zu Wirkung und Wertewahl, erreichbar per Maus, Tastatur und Antippen. Identische Texte mit Übernahmezeitpunkt stehen in [Web-Einstellungen](docs/Web-Einstellungen.md); Vollständigkeit und Übereinstimmung werden getestet.
- **Auswahl in der Webübersicht (Bugfix):** Automatische und manuelle Aktualisierungen behalten den ausgewählten Vorgang im aktuellen Browser-Verlaufseintrag. Nur wenn er nicht mehr in der Liste vorhanden ist, wird der erste verbleibende Eintrag geöffnet. Regressionstest für wiederholte Hintergrundänderungen, Neuladen und entfernte Vorgänge.
- **Neue Weboberfläche:** Split-View ab 1024 px (Liste links, Details rechts, ohne Seitenwechsel), einklappbare Sektionen für Quellbeleg, Revisionshistorie und technische Analyse, Schnellfilter (`?filter=events|tasks|clarification|attachments|duplicates`) auf `/offen`, `/mails` und `/verlauf`, Daumenzonen-Aktionsleiste mit 48-px-Schaltflächen, Tastenkürzel (`J`/`K`/`C`/`E`/`X`/`?`), 5-Sekunden-Rückgängig vor dem Absenden sowie ein „Alles erledigt“-Zustand mit Tagesbilanz. Alle Funktionen bleiben ohne JavaScript nutzbar.
- **Bildanhänge im Browser:** Neu kodierte JPEG-Vorschauen (max. 1.600 px) unter `GET /mail/<id>/anhang/<index>` mit Sitzungsprüfung, `nosniff` und restriktiver CSP; zoombare Lightbox und erkannter Text. Vorschauen werden mit dem Mailtext gelöscht; ein Vorschaufehler hält die Analyse nie auf.
- **Web-Push (`push.enabled`):** VAPID-Schlüssel im Datenverzeichnis, Opt-in je Gerät unter Einstellungen, nur bekannte Push-Dienste, keine Weiterleitungen, inhaltsneutrale Meldungen für neue Entscheidungen und den Tagesüberblick. Der Versand blockiert weder Weboberfläche noch Mailverarbeitung.
- **Antwort-Entwürfe (`smart_reply`, Prompt `draft_reply`):** Die Mail- und Vorschlagsdetailseite zeigt immer „Zusagen“, „Absagen“ und „Rückfrage“. Ein Klick erzeugt per LLM genau einen passenden Entwurf (positiv, negativ, Rückfrage) in einem bearbeitbaren Textfeld; „Abbrechen“ verwirft ihn lokal, „Als Entwurf im Postfach speichern“ legt genau den angezeigten Text per IMAP `APPEND` mit `\Draft \Seen`, `In-Reply-To` und `References` in `imap.drafts_folder` ab. Keine Entwurfserzeugung im Hintergrund; doppelte Klicks lösen keinen zweiten LLM-Aufruf aus. Das Modell erhält die erkannten Anhangtexte (inklusive OCR) genau einmal und ohne technische Metadaten.
- **Persönliche Angaben für Antworten (`personal_info`):** Neues mehrzeiliges Textfeld unter Einstellungen → Antworten (bis 2.000 Zeichen) für Name, Rolle, Signatur und Anrede-Wünsche. Wird nur dem Prompt `draft_reply` als vertrauenswürdiger Kontext übergeben, wirkt ohne Neustart und ändert keinen Analyse-Fingerprint. Mehrzeilige Werte schreibt der Einstellungseditor als einzeiligen YAML-Wert in `config.yaml`. Kein SMTP-Versand. Unklare Ergebnisse werden über die Message-ID abgeglichen und nur bei nachweislich fehlendem Entwurf wiederholt.
- **Tagesüberblick (`daily_briefing`):** Einmal je lokalem Tag Termine, fällige Aufgaben und offene Entscheidungen, auch bei Teilausfällen; Text an Telegram, neutraler Hinweis per Push, Anzeige unter `/briefing`.
- **Betrieb ohne Telegram (`telegram.enabled: false`):** Nur mit Weboberfläche; Kopplungscodes erscheinen in der Konsole des PCs, `TELEGRAM_BOT_TOKEN` entfällt.
- **Fingerprints (Bugfix):** Die 2.0-Einstellungen gelangten in die Legacy-Fingerprints von 1.1/1.2; Mails aus diesen Versionen wären nach dem Upgrade hängen geblieben. Mit Regressionstest.
- **Abhängigkeiten:** `pywebpush==2.5.0` samt Abhängigkeiten in `requirements.lock`; Docker-Image neu bauen.
- Einrichtung, Upgrade und Rollback: [Release-2.0.md](docs/Release-2.0.md).

## 1.6.0 – Beta (Branch `beta`)

- **Webdarstellung getrennt:** Vorschlags-, Mail- und Review-Seiten bleiben in `web/review_pages.py`; Betriebsstatus und Laufzeitformatierung liegen in `web/status_pages.py`. Bestehende Importe bleiben kompatibel.
- **Eigener Mailbox-Service:** `mailbox_run.py` übernimmt Discovery, globale durable Queue, UID-Checkpoints, Mail-Budgets, Laufzusammenfassung und Wiederaufnahme. `Application` bleibt für Composition und Prozess-/Telegram-/Web-Lifecycle zuständig.
- **Integrationsgrenzen:** OAuth, Google-Kalender, Todoist, ICS-Dateien, HTTP-Transport und bestätigte Schreibausführung sind unter `external/` getrennt. `integrations.py` bleibt die kompatible Fassade für bisherige Importe und Konstruktoren.
- **Telegram-Revisionen entflechtet:** Antwortinterpretation mit eigenen Retries, validierte Nachfolge-Vorschläge und durable/Legacy-Recovery besitzen eigenständige Grenzen. Persistenz, Zustellung und versionsbezogene Autorisierung behalten ihre Reihenfolge.
- **Verhaltensverträge:** Zusätzliche Tests für die kompatiblen Schnittstellen, unabhängige Mailbox-Wiederaufnahme und identische Renderer-Ausgaben gegenüber 1.5. Bestehende JSON-Schemas, CLI-Optionen, Web-Routen, Konfiguration und externe API-Verträge bleiben unverändert.
- **Browsertests korrigiert:** Die Kopplungstesthilfe erkennt den seit 1.5 gültigen vierstelligen Telegram-Code; der Negativtest verwendet garantiert einen abweichenden Code. Die synthetische Hauptschleife wird für unveränderte Renderzustände stabilisiert; produktive Recovery bleibt unverändert.
- Architektur und Upgrade in [Architektur-1.6.md](docs/Architektur-1.6.md) und [Release-1.6.md](docs/Release-1.6.md) dokumentiert.

## 1.5.0 – Beta (Branch `beta`)

- **Schlanke 4-stellige Anmeldeverifizierung:** Reduzierung des Gerätekopplungscodes von 8 auf 4 Ziffern (`0000`–`9999`) für schnelles Eintippen am Smartphone; Telegram-Nachricht und `/web`-Befehl senden den kompakten Code ohne Leerzeichen; Formular-Input auf 4–5 Zeichen angepasst; vollständiger Brute-Force-Schutz durch 3 Versuche (`CODE_ATTEMPTS`) und Rate-Limiting (`PairingLimited`).
- **Standard-Wechselkurs für Euro-Kosten:** Fester Wechselkurs von 1 € = 1,10 $ (`metrics.usd_per_eur = 1.1`) ab Werk hinterlegt; Euro-Kosten werden in der Auswertung ohne manuelle Konfiguration berechnet; Bezugsdatum ist optional.
- **Kosten in $Cent in der Tabellenansicht:** Spalte `<th>$Cent</th>` in der Tabelle „Nach Modell und Schritt“ auf `/auswertung`; Beträge in US-Cent mit 2 Nachkommastellen formatiert; voller USD-Betrag bleibt im `title`-Attribut für Tooltips erhalten.
- **Kompakte Modellnamen:** Modellbezeichner in der Auswertungstabelle werden auf den Namen nach dem letzten Schrägstrich (`/`) gekürzt (z. B. `deepseek` statt `openrouter/deepseek`); voller Modellpfad weiterhin im `title`-Tooltip verfügbar.
- **Sauberes Shutdown-Handling im Telegram-Client (Bugfix):** `RetryInterrupted` während eines Long-Polling-Backoffs wird geordnet als `INFO poll_interrupted` behandelt; kein irreführendes `ERROR`-Log mit 50 Zeilen Stacktrace beim Beenden des Dienstes; inklusive automatisiertem Regressionstest.

## 1.4.0 – Beta (Branch `beta`)

- **Multimodale Bild- und OCR-Texterkennung:** Bildanhänge (`.jpg`, `.png`, `.webp`) sowie gescannte PDFs ohne Textlayer werden automatisch per Vision-LLM (`vision_ocr` in `prompts.yaml`, Standard: `google/gemini-3.5-flash-lite`) ausgewertet.
- **Null externe System-Tools:** Bildaufbereitung und Scan-Seitenextraktion vollständig über Python (`pypdf` + `Pillow`); kein Tesseract, kein PyTorch, keine C-Binaries.
- **Intelligente Bildfilterung & Token-Schutz:** Automatische EXIF-Ausrichtung, Skalierung auf maximal 1.600 Pixel, Dekompressions-Bombenschutz und automatische Verwerfung irrelevanter Logos/Symbole (<150 px oder <10 KB).
- **Konfigurierbare Limits:** Neuer Konfigurationsabschnitt `vision` in `config.yaml` (`enabled`, `max_images_per_mail: 3`, `max_image_bytes: 10485760`, `max_edge_pixels: 1600`).
- **Absender-Management in der Mail-Detailansicht:** Schaltfläche `[🚫 Absender ignorieren]` auf `/mail/<mail_id>` trägt die normalisierte Absenderadresse atomar und idempotent in `irrelevant-senders` ein. Reversibel mit `[Absender wieder zulassen]`.
- **Zentrale Liste ignorierter Absender:** Eigene Verwaltungsseite unter `/einstellungen/ignorierte-absender` zum manuellen Hinzufügen und Entfernen von Adressen und ganzen Domains.
- **Sofortiger Vorfilter im Orchestrator:** Mails blockierter Absender/Domains werden vor jedem KI-Aufruf ohne Benachrichtigung als `irrelevant` aussortiert (0 Cent Kosten).
- **100 % Testabdeckung:** 1.561 synthetische Tests bei 100,00 % Zeilen- und Branch-Coverage.

## 1.3.0 – Beta (Branch `beta`)

- **Intelligente Duplikat-Vorabprüfung (Stufen 1–3):** Vorab-Check gegen Action Ledger, Google Kalender und Todoist vor Benachrichtigung. Exakte Duplikate erhalten den Status `already_exists` und werden auf Telegram und unter `/offen` unterdrückt.
- **Intelligente Terminverschiebung (Reschedule):** Erkennt bestehende Google-Kalender-Termine, berechnet und visualisiert Zeitänderungen in Web und Telegram ("🔄 Terminänderung gegenüber Kalender") und aktualisiert nach Bestätigung per HTTP `PATCH` anstelle eines Neuanlage-`POST`.
- **Lokale Dokumenten-Textextraktion (PDF, Word, Text):** Sichere Extraktion von Textinhalten aus Anhängen (bis 10 MB, max. 20.000 Zeichen) mittels `pypdf` und nativer ZIP/XML-Verarbeitung ohne externe System-Tools; automatische Anreicherung des LLM-Kontexts für Routing und Detail-Extraktion.
- **RFC 5545 Kalenderanhänge (.ics):** Deterministische Übernahme von `VEVENT`-Einladungen und -Absagen ohne LLM-Halluzinationen.
- **Erweiterungen in Web & Telegram:** Diff-Boxen bei Terminänderungen, Duplikat-Badges mit Direktlinks, Anhangs-Statusbadges und kontextbezogene Bestätigungsschaltflächen ("Termin aktualisieren", "Termin absagen").
- Vollständige synthetische Testabdeckung (100 % Zeilen, 100 % Branches) inklusive 3 Regressionstests für Duplikatsunterdrückung, Kalender-PATCH und PDF-Aufgabenextraktion.

## 1.2.0 – Beta (Branch `beta`)

- Weboberfläche mit Mailarchiv (Suche, Filter, Analyse), Entscheidungsverlauf mit
  lesenden Altversionen, erweitertem Betriebsstatus und Kosten-/Zeitauswertung.
- Strukturierte Bearbeitung von Vorschlägen; Speichern erzeugt eine neue Version, die
  separat bestätigt werden muss.
- Einstellungen und Themen im Web, kommentarerhaltend in `config.yaml` gespeichert;
  kontrolliertes Beenden aus dem Web.
- Konfigurations-Fingerprint nur aus analyserelevanten Einstellungen; Vorgänge aus 1.1
  laufen nach dem Upgrade weiter.
- Lernmodus ergänzt IMAP-Ordner ohne Kommentarverlust.
- Bestätigung von Schreibzugriffen über Telegram oder die authentifizierte Weboberfläche.

Einrichtung, Upgrade und Rollback: [Release-Anleitung](docs/Release-1.2.md).

## 1.1.0 – Beta (Branch `beta`)

- Optionale Weboberfläche mit Übersicht, Vorschlagsdetail, Status und Geräteverwaltung,
  bedienbar am PC und als installierbare App (PWA) auf dem iPhone über Tailscale Serve.
- Bestätigen, Doppelanlage, Verwerfen, Antworten (auch Ja/Nein), Bearbeitung beenden
  und Relevanz im Web – versionsgebunden, über eine dauerhafte Befehlswarteschlange,
  idempotent und mit Abgleich nach Neustart.
- Kanalneutrale Review-Schicht; Telegram-Schaltflächen nutzen sie ebenfalls und melden
  im Web entschiedene Vorschläge als veraltet. Neue Befehle `/web` (Link mit
  vorausgefülltem Einmal-Code) und `/web_abmelden`.
- Anmeldung per Telegram-Kopplungscode, gehashte Sitzungen, CSRF, Host-Prüfung,
  strenge Sicherheits-Header; Service Worker speichert nur die App-Hülle.
- `JsonStore` ist zusätzlich thread-sicher (Regressionstest für `os.replace` unter Windows).
- Automatische Browsertests (Desktop und iPhone) mit Screenshots, Bedienbarkeits- und
  Kontrastprüfungen und 100 % JavaScript-Abdeckung; eigener CI-Job.

Einrichtung und Einschränkungen: [Release-Anleitung](docs/Release-1.1.md).

## 1.0.0 – 11. Oktober 2026

- Vollständiger Trockenlauf für Todoist und Google Kalender.
- Konservative Kurzlink-Vorprüfung mit synthetischen Regressionstests.
- Begrenzte Wiederholung vorübergehend blockierter Betriebssystem-Sperren.
- Qualitätsprüfung des produktiven Jev-Pfads mit gemeinsamem Aufrufbudget.
- Semantischer Uhrzeitvergleich, präzisierte Zuständigkeits- und Zusammenfassungsregeln.
- Prüfungen für Sicherungswiederherstellung, Paketinstallation und Release-Artefakte.

Upgrade und Einschränkungen: [Release-Anleitung](docs/Release-1.0.md).

## 0.1.0

Erste Implementierung des persönlichen IMAP-/LLM-/Telegram-Assistenten mit
versionsbezogenen Freigaben, dauerhaften JSON-Zuständen und Duplikatabgleich.
