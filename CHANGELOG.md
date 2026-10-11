# Änderungen

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
