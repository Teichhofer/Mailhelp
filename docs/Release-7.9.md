# Mailhelp 7.9 – Kalender-Zugangsdaten ergänzen und Anmeldeprobleme sichtbar machen

**Stand:** 18. November 2026. **Status:** 7.9.1 umgesetzt (Konferenzlink für bestehende Termine);
der Warnhinweis bei Anmeldeproblemen folgt mit 7.9.2. Der zentrale Google-OAuth-Callback
(Abschnitt 4.6) gehört laut [Planung 7.9](Planung-7.9.md) zu [Planung 8.0](Planung-8.0.md).

## 7.9.1 – Konferenzlink für bestehende Kalendertermine

### Behobene Ursache

Ein bestätigter Online-Termin ohne Einwahllink wurde von einer späteren Mail mit dem Link bei
gleichen Zeiten als Duplikat abgeschlossen (`duplicate_found_calendar`, `already_exists`). Der Link
erreichte den Kalender nie. Alle vier Stellen aus Abschnitt 2 des Plans sind gemeinsam korrigiert:

| Stelle | Änderung |
| --- | --- |
| `precheck.py::_check_calendar` | Vor `already_exists` wird der Konferenzlink verglichen; ein fehlender Link bindet den Termin als Ziel mit `CalendarSupplement`. Auch ein Treffer im ActionLedger liest den angelegten Termin und vergleicht. |
| `calendar_target.py::_targeted` | Eine ausdrückliche Änderung ohne Zeit- oder Ortsänderung gilt nur als erledigt, wenn auch der Link übereinstimmt. |
| `external/calendar.py::_change_body` | Schreibt die bestätigte Ergänzung; eine reine Ergänzung nur in die Beschreibung, ohne Zeiten, Titel oder Ort. |
| `_calendar_merge_body` | Nutzt denselben deduplizierenden Abschnitt `[Mailhelp-Videolink]` wie Änderung und Neuanlage. |

### Verhalten

- Gemeinsamer deterministischer Vergleich (`domain/conference.py`): nur HTTPS-Links bekannter
  Konferenzanbieter, Vergleich von Beschreibung, Ort und nativen Feldern (Google `hangoutLink`,
  `conferenceData`, Outlook `onlineMeeting.joinUrl`). Meeting-ID, Passcode und Query bleiben unverändert.
- Gespeicherte Änderung `Proposal.calendar_supplement` mit Feld, Operation, bisherigem und neuem
  Wert, Ziel-ID, Zielprofil, Anbieter und Quellmail. Sie ist durch die Modellvalidierung an
  `target_event_id` gebunden und wird bei der Bestätigung erneut geprüft; eine Abweichung erzeugt
  eine neue Version.
- Konflikt mit einem anderen Konferenzlink: Feldkonflikt „Videolink“ mit Kalender- und Mailwert.
  Die Auswahl des neuen Links bleibt bei der erneuten Prüfung erhalten; die Auswahl des alten Links
  führt zu `already_exists`.
- Vor dem Schreiben wird der Zieltermin neu gelesen: vorhandener Link → Abschluss ohne Schreibzugriff;
  inzwischen anderer Link oder anderes Ziel → fehlgeschlagener Schreibzugriff ohne Überschreiben.
- Web und Telegram zeigen „Bestehenden Termin aktualisieren: Videolink ergänzen/ersetzen“ mit
  altem (durchgestrichen) und neuem Wert, auf Deutsch und Englisch.
- Altbestand: `already_exists`-Termine mit Link bieten **Mit Kalender erneut abgleichen**. Das
  erzeugt höchstens eine neue, separat zu bestätigende Version; Neustart und Wiederholung werden über
  Version und Idempotenzschlüssel erkannt. Beim Upgrade wird nichts automatisch neu bewertet.

**Bekannte Grenze:** Liegt der bisherige Link nur in einem nativen Konferenzfeld (z. B. Google Meet
im Termin), ergänzt eine bestätigte Ersetzung den neuen Link in der Beschreibung; das native Feld
selbst ändert Mailhelp nicht.

### Regressionsnachweis

`tests/services/test_video_link_supplement.py` wurde vor dem Fix geschrieben und am unveränderten
Code ausgeführt: 6 von 6 Fällen schlugen fehl (Vorschlag mit Link wurde `already_exists` bzw. das
Feld für die Ergänzung fehlte). Nach dem Fix bestehen sie zusammen mit 25 weiteren Fällen der
Datei und `tests/web/test_video_link_web.py` (Neubewertung, Versionsbindung, Wiederanlauf,
Telegram, Englisch).

Weitere Korrektur: Die Demo-Bestandsprüfung verglich gespeicherte Vorschläge roh mit der
Modellausgabe; ein neues Feld mit Standardwert hätte freigegebene Bestände ungültig gemacht. Sie
vergleicht jetzt beide Seiten nach der Validierung.

### Prüfung 7.9.1

`python -m devtools.check full --workers 12`: 100 % Zeilen- und Branch-Abdeckung; ein
Dokumentationstest wertete `CONFERENCE_HOSTS` in der Spezifikation als Umgebungsvariable. Nach
der Umformulierung besteht `tests/release/test_documentation_checks.py` (109 Tests). Die
Browsersuite meldet 975 bestandene, 234 übersprungene und zwei fehlgeschlagene Zeitmessungen
(Diagramm-Hover, Live-Suche unter 300 ms), die einzeln unverändert bestehen (4 bestanden,
2 übersprungen); der Diagrammfall trat bereits unter 7.7.6 so auf.
