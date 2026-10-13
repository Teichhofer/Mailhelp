# Architektur ab Mailhelp 2.1

Version 2.1 führt keine neuen Endnutzerfunktionen ein, sondern konsolidiert die
Architektur nach fünf Funktionsreleases. Sie macht den Anwendungscode modularer,
beseitigt technische Schulden und erhöht die Aussagekraft der Testsuite.

Verbindliche Garantien wie die Bestätigungsschranke vor externen Schreibzugriffen,
CSRF- und Sitzungsschutz, Idempotenzschlüssel sowie die Vorabprüfung unklarer
Schreibresultate bleiben unverändert erhalten.

---

## 1. Modul- und Klassenorganisation

Große Klassen und Funktionen wurden entlang klarer Verantwortungsgrenzen
zerlegt (Richtwerte: Funktionen ≤ 80 Zeilen, Klassen ≤ 20 Methoden):

- **Web-Seiten (`web/`):** `MailhelpSite` wurde von einer monolithischen Klasse
  in modulare Teil-Sites aufgeteilt:
  - `LoginSite` (`login_site.py`): Koppelung, Sitzungsprüfung, Geräteverwaltung,
    Anmeldung via Telegram-Code.
  - `ReviewSite` (`review_site.py`): Darstellung offener Entscheidungen,
    Detailansichten, Vorschlagskarten und Mailanzeige.
  - `ArchiveSite` (`archive_site.py`): Archiv, Verlauf, Einstellungen und
    Administration.
  - `MailhelpSite` (`site.py`): Dient als verbindender Dispatcher und Router
    ohne unübersichtliche Methodenansammlungen.
- **HTML-Zusammensetzung:** Das nachträgliche Einfügen von Filterchips oder
  Entwurfseditoren via `page.replace("</main>", ...)` wurde durch strukturierte
  Parameterübergabe (`extra_sections`, `before`) in den Renderern abgelöst.
- **Composition (`composition.py`):** Fabrikfunktionen für LLM-Clients, Writer,
  Telegram-Adapter, Webserver und Experience-Dienste kapseln die Instanziierung
  und entlasten `application.py`.
- **CLI (`cli.py`):** Unterbefehle sind in eigenständige Handler-Funktionen mit
  tabellarischem Dispatch gegliedert.

---

## 2. Speicher-Protokoll und Zustandsnamen

Zuvor vorhandene Duck-Typing-Weichen (`hasattr(store, "load_model")`,
`hasattr(store, "directory")`) wurden vollständig beseitigt:

- **`StateStore`-Protokoll:** `storage.py` definiert das formale Protokoll
  `StateStore` mit `load`, `save`, `load_model`, `peek_model`, `names`, `locked()`
  und `directory`.
- **Öffentlicher Sperrkontext:** `store.locked()` ersetzt alle direkten Zugriffe
  auf private Attribute (`store._thread_lock`) in Diensten und Tests.
- **Zentrale Zustandsnamen (`state_names.py`):** Erzeugt und filtert Schlüssel
  für Mails (`mail-`), Durchläufe (`mail-run-`), Entwürfe (`draft-`),
  Vorschläge (`proposal-`), Push-Abonnements (`push-subscriptions`) und
  VAPID-Schlüssel an genau einer Stelle im Code.

---

## 3. Typisierte Domänenmodelle

Zuvor als unstrukturierte Wörterbücher geführte Datenstrukturen sind als
Pydantic-Modelle typisiert (`src/mailhelp/domain/prepared.py`):

- **`PreparedMail` / `MailHeaders`:** Strukturierte Repräsentation aufbereiteter
  Mails mit Absender, Betreff, Datum und Nachrichtenkennung.
- **`PreparedAttachment` / `ImagePreview`:** Typisierte Metadaten für Anhänge und
  Rastervorschaubilder.
- Die Modelle nutzen `extra="allow"`, um vollständige Abwärtskompatibilität zu
  gespeicherten Altzuständen aus früheren Versionen (1.1 bis 2.0) zu garantieren.

---

## 4. Fehlerbehandlung und Schnittstellenverträge

- **Gemeinsame Ausnahmehierarchie für externe Dienste (`external/contracts.py`):**
  - `ExternalServiceError`: Gemeinsame Basisklasse.
  - `ExternalUnavailable` (erbt von `RetryableError`): Temporäre
    Dienstausfälle und Timeouts.
  - `ExternalRefused` (erbt von `PermanentError`): Dauerhaft abgelehnte
    Anmeldedaten oder ungültige Anfragen (Basis für `AuthenticationError` und
    `CalendarAccessError`).
  - `ExternalUncertain` (erbt von `UncertainWriteError`): Unklares
    Schreibresultat, das vor einem Neuversuch zwingend abgeglichen werden muss.
- **`log_and_continue` (`logging.py`):** Einheitlicher Helfer an äußeren
  Prozessgrenzen, der Fehler protokolliert (ohne Geheimnisse oder vertrauliche
  Inhalte) und den Hauptprozess sicher weiterlaufen lässt.
- **Gemeinsames Hilfsmodul `formatting.py`:** Zentralisiert die Anzeige
  lokaler Zeitstempel (`%d.%m.%Y, %H:%M Uhr`) über alle Web- und Review-Module.
- **Einheitliche Bilderkennung:** Bildvorschau in `attachments.py` und OCR in
  `vision.py` verwenden dieselbe Funktion `is_image(filename, content_type)`.

---

## 5. Testsuite und Qualitätssicherung

Die Testsuite wurde fundamental modernisiert und restrukturiert:

- **Fachliche Verzeichnisstruktur (`tests/`):**
  - `unit/`: Reine Komponenten- und Parser-Tests.
  - `services/`: Fachdienste (Orchestrator, Mailbox-Lauf, Entwürfe, Push, Briefing, Retention).
  - `telegram/`: Dialog-, Callback- und Revisionsabläufe.
  - `web/`: Authentifizierung, Routen, Formulare, Einstellungen, Status.
  - `external/`: Kalender-, Todoist-, OAuth- und LLM-Adapter.
  - `upgrade/`: Upgrade-Suiten mit synthetischen Altzuständen aller Versionen
    (1.1 bis 2.0), Schemasnapshots und Migrationsprüfungen.
  - `e2e/`: Durchgängige Gesamtabläufe.
  - `fakes/`: Wiederverwendbare, protokollkonforme Test-Doubles ohne
    Querabhängigkeiten zwischen Testmodulen.
- **Eigenschaftsbasierte Tests (`hypothesis`):** Systematische Grenzfallprüfung
  für MIME-Parser, Datums-/Zeitparser, iCal-Serialisierung und Web-Push-Validierung.
- **Stabile Browsertests:** Automatische Coverage-Erfassung über DevTools-Hooks
  vor Seitenwechseln und konfigurierbare Undo-Frist (`data-undo-ms`).
- **Verbindliche Abdeckung:** Sämtlicher eigener Anwendungscode hält 100 % Zeilen-
  und 100 % Branch-Abdeckung ein.
- **Statische Analyse:** Konfiguration von `ruff` und strikter Typprüfung (`mypy`)
  für den Systemkern.
