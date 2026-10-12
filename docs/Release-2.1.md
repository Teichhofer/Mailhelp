# Mailhelp 2.1 – Aufräumen und bessere Tests

Mailhelp 2.1.0 ist ein reines Qualitäts- und Refactoring-Release. Es bringt keine
neuen Endnutzerfunktionen, sondern konsolidiert die Architektur nach fünf
Funktionsreleases und erhöht die Aussagekraft der Testsuite erheblich.

Alle Nutzerabläufe, Web-Routen, CLI-Optionen, Konfigurationsschlüssel, JSON-Schemas
und externen API-Verträge bleiben unverändert kompatibel.

Grundlage: [Planung-2.1.md](Planung-2.1.md) und [Architektur-2.1.md](Architektur-2.1.md).

---

## Wesentliche Verbesserungen

### 1. Statische Codeanalyse und Typprüfung
- Konfiguration von `ruff` (Pyflakes, isort, pyupgrade, bugbear, Linienbegrenzung auf 120 Zeichen).
- Strikte Typprüfung (`mypy --strict`) für den gesamten Domänen- und Dienstekern (`domain/`, `external/contracts.py`, `drafts.py`, `webpush.py`, `briefing.py`, `attachments.py`).
- Vollständige Typsicherheit für Vorbereitung, Entwürfe und Web-Push.
- Einheitlich `from __future__ import annotations` über alle Module hinweg.

### 2. Speicher-Protokoll und zentrale Zustandsverwaltung
- Einführung des `StateStore`-Protokolls (`typing.Protocol`) mit `load`, `save`, `load_model`, `peek_model`, `names`, `locked()` und `directory`.
- Beseitigung aller `hasattr`/`getattr`-Weichen auf dem Zustandsspeicher.
- Zentrales Modul `state_names.py` für die einheitliche Bildung aller Zustandsschlüssel (`mail-`, `mail-run-`, `draft-`, `proposal-`, `push-subscriptions`, `web-vapid`).

### 3. Typisierte Datenmodelle
- Einführung von `PreparedMail`, `MailHeaders`, `PreparedAttachment` und `ImagePreview` zur Ablösung unstrukturierter Dictionaries.
- Vollständige Lesekompatibilität für gespeicherte Altzustände aus Versionen 1.1 bis 2.0 (`extra="allow"`).

### 4. Modularisierung großer Komponenten
- Zerlegung großer Funktionen (alle ≤ 80 Zeilen) und Klassen (alle ≤ 20 Methoden).
- Aufteilung der Web-Verwaltung von `MailhelpSite` in spezialisierte Einheiten:
  - `LoginSite` für Koppelung, Sitzungen und Geräteverwaltung.
  - `ReviewSite` für offene Entscheidungen, Mails und Vorschläge.
  - `ArchiveSite` für Verlauf, Archiv und Einstellungen.
  - `MailhelpSite` als verbindender Router.
- Fabrikarchitektur (`composition.py`) für den sauberen Aufbau der Anwendungsdienste.
- HTML-Generierung ohne nachträgliche String-Ersetzung (`page.replace("</main>", ...)`).

### 5. Robuste Fehlerbehandlung
- Einheitliche Ausnahmehierarchie für externe Dienste (`ExternalServiceError`, `ExternalUnavailable`, `ExternalRefused`, `ExternalUncertain`) in `external/contracts.py`.
- Neuer Hilfsdienst `log_and_continue` für das sichere Protokollieren von Fehlern an Prozessgrenzen.
- Zentralisiertes Formatierungsmodul `formatting.py` (`%d.%m.%Y, %H:%M Uhr`).
- Einheitliche Bilderkennung für OCR und Bildvorschau (`is_image` aus `vision.py`).

### 6. Strukturierte und aussagekräftige Tests
- Fachliche Neuordnung des Testverzeichnisses (`tests/unit`, `services`, `telegram`, `web`, `external`, `upgrade`, `e2e`, `fakes`, `scenarios`).
- Gemeinsame, protokollkonforme Test-Doubles in `tests/fakes/` ohne Modul-Querabhängigkeiten.
- Upgrade-Testsuiten (`tests/upgrade/`) mit synthetischen Altzuständen aller bisherigen Versionen (1.1 bis 2.0).
- Eigenschaftsbasierte Tests mit `hypothesis` für Parser und Validierungsfunktionen.
- Stabilisierung der Browser-Testsuite mit automatischem Coverage-Sammeln vor Navigationen über DevTools-Hooks.
- 100 % Zeilen- und 100 % Branch-Abdeckung für sämtlichen eigenen Anwendungscode verbindlich beibehalten.
