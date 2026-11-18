# Mailhelp 7.9 – Kalender-Zugangsdaten ergänzen und Anmeldeprobleme sichtbar machen

**Zielversion:** 7.9, erste Auslieferung 7.9.1; weitere Commits mit fortlaufender Patchversion.

**Stand:** 18. November 2026.

**Status:** Umgesetzt in 7.9.1 (Abschnitte 4.1–4.4) und 7.9.2 (Abschnitt 4.5), siehe
[Release 7.9](Release-7.9.md); Abschnitt 4.6 folgt mit 8.0.
Dieses Dokument autorisiert weder eine Implementierung noch eine
Bereitstellung oder einen externen Schreibzugriff.

**Grundlagen:** [Entwicklungsregeln](../AGENTS.md),
[Spezifikation](../Mailhelp-Projektspezifikation.md), [Planung 7.8](Planung-7.8.md).
Vor Umsetzung den dann aktuellen Quellstand und den Abschluss von 7.8 prüfen.

## 1. Ziel und Abnahmebeispiel

Ein Kalender enthält einen bestätigten Online-Termin ohne Einwahllink. Eine spätere
Mail liefert die Zugangsdaten bei unveränderten Terminzeiten. Mailhelp erkennt den
bestehenden Termin und bietet „Videokonferenz-Link ergänzen“ als Aktualisierung an.
Die Vorschau nennt Zieltermin, Datum, Uhrzeit, Quelle und die konkret ergänzten Daten.
Erst die ausdrückliche Bestätigung dieser Vorschlagsversion erlaubt die Änderung.

Nach Bestätigung enthält derselbe Kalendertermin den Link genau einmal. Titel,
Zeiten, eigene Notizen, Teilnehmer und weitere nicht bestätigte Felder bleiben erhalten.
Ein zusätzlicher Termin entsteht nicht. Erneuter Mailabruf oder Neustart verursacht
weder einen zweiten Schreibzugriff noch eine erneute Ergänzung desselben Links.

Anmelde- und Authentifizierungsprobleme verbundener Dienste erscheinen unmittelbar
nach ihrer Erkennung als gut sichtbare Warnung in der Mailübersicht. Betroffene
Nutzer müssen dafür weder die Statusseite öffnen noch einen fehlgeschlagenen
Kalenderschreibzugriff auslösen.

## 2. Nachgewiesene Ursache

Untersucht wurde die Mail „Anmeldebestätigung und Einwahllink“ vom 16.11.2026 auf
dem Produktivserver unter 7.7.6. Sie wurde vollständig verarbeitet; der Webex-Link
war im gespeicherten Terminvorschlag vorhanden. Der Kalenderabgleich protokollierte
anschließend `duplicate_found_calendar` und setzte den Vorschlag auf `already_exists`.

Die lokale Beweissicherung liegt unter `tmp/server-analysis-20261118/` und ist von
Git ausgeschlossen. Produktive Mailinhalte, Zugangsdaten und Logs gehören nicht in Tests
oder versionierte Dokumentation. Tests verwenden einen eigenständigen synthetischen Fall.

Vier Stellen müssen gemeinsam korrigiert werden:

1. `proposals/precheck.py::_check_calendar` erkennt beim selben Termin Zeitänderungen
   und explizit klassifizierte Änderungen/Stornierungen. Ein als `new` extrahierter
   Zugangsdaten-Nachtrag mit gleichen Zeiten wird unmittelbar als Duplikat beendet.
2. `proposals/calendar_target.py::_targeted` kann auch explizite Änderungen ohne
   Zeit- oder Ortsänderung als bereits erledigt einstufen. Der Videolink fehlt im Vergleich.
3. `external/calendar.py::_change_body` übernimmt derzeit Zeiten, Ort und einen
   Änderungsvermerk, aber keinen Videolink. Eine reine Umklassifizierung reicht nicht.
4. Der vorhandene Ergänzungspfad `_calendar_merge_body` kennt zwar `video_link`,
   wird durch den abschließenden Vorab-Dublettenentscheid in diesem Fall nicht erreicht.

Die damalige Einstufung der älteren Einladung vom 15.10. als irrelevant ist ein
separater Vorgang und nicht Ursache dieses Fehlers. Ein Promptwechsel allein behebt
den Fehler nicht zuverlässig.

## 3. Fachliche Entscheidungsregeln

Nach Feststellung der Terminidentität erfolgt ein deterministischer Inhaltsvergleich.
Eine Modellentscheidung über Identität ersetzt weder Feldvergleich noch Autorisierung.

| Situation | Ergebnis |
| --- | --- |
| Derselbe Termin, kein Link im Kalender, gültiger Link aus der Mail | Aktualisierung zur Ergänzung anbieten |
| Derselbe Link bereits vorhanden | `already_exists`, keine Änderung und keine neue Bestätigung |
| Kalender enthält einen anderen Konferenz-Link | Konflikt mit Alt-/Neu-Vorschau; ausdrückliche Auswahl erforderlich |
| Mehrere passende Termine | Zielauswahl; kein automatisches erstes Suchergebnis verwenden |
| Kein passender Termin | Bestehenden Ablauf für neue Termine verwenden; keinen Update-Erfolg behaupten |
| Neue Zeit und neuer Link | Beide Änderungen gemeinsam anzeigen und versionsbezogen bestätigen |
| Explizit als `change` klassifizierter reiner Linknachtrag | Derselbe Ergänzungsablauf; nicht als unverändert abschließen |
| Nur Anmeldung, Veranstalterseite oder allgemeine Website verlinkt | Keine Ergänzung als Konferenz-Zugang |
| Leerer, ungültiger oder widersprüchlicher Zugang | Keine schreibbare Ergänzung; bei Bedarf konkrete Rückfrage |
| Stornierung | Bestehenden Stornierungsablauf erhalten; keine Zugangsdaten ergänzen |

Der Linkvergleich berücksichtigt die vorhandene Beschreibung und die vom Provider
bereitgestellten Konferenzfelder. Vor Umsetzung die Abbildung in `CalendarOverlapEvent`
und allen unterstützten Kalenderadaptern prüfen und erforderlichenfalls erweitern.
Nur technisch sichere Normalisierung verwenden: Host-/Schemakleinschreibung und
Formatierungsunterschiede dürfen berücksichtigt werden; Meeting-IDs, Passcodes und
Queryparameter dürfen nicht entfernt oder verändert werden. Links nicht zum Vergleich aufrufen.

7.9 behebt gezielt Konferenz-Zugangsdaten. Allgemeine Unterschiede in automatisch
generierten Beschreibungen oder Titeln dürfen keine endlosen Update-Vorschläge erzeugen.
Separate Passcodes nur übernehmen, wenn das bestehende Extraktionsmodell sie ausdrücklich
belegt und die Vorschau sie als bestätigte Änderung darstellt; keine neue Extraktion aus
beliebigen Textfragmenten im Rahmen dieses Fixes.

## 4. Umsetzung

### 4.1 Einheitlicher Vergleich und gespeicherte Änderung

- Einen gemeinsamen Vergleich für Vorabprüfung, explizite Zielzuordnung und erneute
  Prüfung vor Ausführung einführen. Identität, Zeitänderungen und Zugangsdaten getrennt auswerten.
- Ein strukturiertes Änderungsobjekt mit Feld, bisherigem Wert, vorgeschlagenem Wert,
  Operation, Ziel-ID, Zielprofil/-provider und Quellbezug dauerhaft im Vorschlag speichern.
  Falls neue Persistenzfelder nötig sind, Schema, Legacy-Defaults und Upgrade-Tests ergänzen.
- Die bestätigte Nutzlast sowie die relevante Ausgangslage des Zieltermins dauerhaft binden.
  Ein bloßer Anzeigetext in `time_changes` genügt nicht als Ausführungsauftrag.
- Bestehende Bestätigungen bei jeder fachlichen Revision ungültig machen; Version erhöhen.
  Die ursprüngliche Extraktionsklassifikation darf nicht allein über Ergänzbarkeit entscheiden.
- Treffer im lokalen ActionLedger dürfen die Inhaltsprüfung nicht vorzeitig umgehen.
  Bereits angelegt bedeutet nicht, dass später gelieferte Zugangsdaten bereits vorhanden sind.

### 4.2 Kalenderabgleich

- In `precheck.py` vor `ALREADY_EXISTS` prüfen, ob bestätigungsfähige neue Daten vorliegen.
  Für einen eindeutigen Treffer den vorhandenen Termin als Update-Ziel binden.
- In `calendar_target.py` denselben Inhaltsvergleich für explizite Änderungen verwenden.
- Mehrdeutige Treffer vollständig berücksichtigen und die vorhandene Zielauswahl nutzen.
- Relevante Ergänzungen bleiben `pending_confirmation`; Konflikte bleiben
  `needs_clarification`. Nur nachgewiesen identische Inhalte werden `already_exists`.
- Lokalen Vorschlagsabgleich und externe Kalenderprüfung so verbinden, dass parallele
  Mails mit demselben Link nicht mehrere unabhängig schreibbare Ergänzungen erzeugen.

### 4.3 Vorschau, Bestätigung und Schreiben

- Web und Telegram zeigen „Bestehenden Termin aktualisieren“, das Ziel und die konkrete
  Ergänzung beziehungsweise den Linkkonflikt. Texte auf Deutsch und Englisch ergänzen.
- Vorhandene Schreib- und Ergänzungspfade auf eine gemeinsame, bestätigte Feldänderung
  ausrichten. `_change_body` und `_calendar_merge_body` dürfen keinen unterschiedlichen
  fachlichen Stand erzeugen. Vorhandene Notizen erhalten und markierte Ergänzungen deduplizieren.
- Ein reiner Linknachtrag schreibt ausschließlich die dafür benötigten Felder und
  vorhandene Idempotenz-/Nachweismetadaten. Keine unbeabsichtigte Zeit-, Orts- oder Titeländerung.
- Unmittelbar vor Ausführung Sitzung erneut prüfen, Zieltermin neu lesen und bestätigte
  Änderung mit dessen relevantem Stand vergleichen. Web: CSRF, Version und Idempotenzschlüssel;
  Telegram: gültige versionsbezogene Bestätigung über den bestehenden Autorisierungspfad.
- Ist der bestätigte Link inzwischen vorhanden, ohne weiteren Schreibzugriff abschließen.
  Bei relevantem Konflikt eine neue Revision zur Bestätigung erzeugen. Unabhängig geänderte
  Notizen beim Aufbau der Nutzlast aus dem frisch gelesenen Termin bewahren.
- Providerseitige Versionsbedingungen, soweit vorhanden, nutzen. Änderungen zwischen
  Lesen und Schreiben dürfen nicht still überschrieben werden; fehlende Bedingungen
  und das dafür gewählte Erhaltungsverfahren pro Adapter ausdrücklich dokumentieren und testen.
- Gelöschte, unlesbare oder nicht unterstützte Ziele nicht neu anlegen. Serienregeln
  erhalten; ein Einzeltermin darf nicht unbeabsichtigt eine ganze Serie verändern.
- Unklare Schreibresultate vor Wiederholung abgleichen. Neustart verwendet denselben
  dauerhaften Auftrag und Idempotenzschlüssel. Nachprüfung verifiziert Ziel-ID und tatsächlichen Link.

### 4.4 Diagnose und vorhandene Fehlfälle

- Inhaltsfreie JSONL-Ereignisse für Ergänzung erkannt, identisch, Konflikt und
  Aktualisierung nachgeprüft ergänzen. IDs, Versionen und Feldnamen genügen;
  vollständige Einwahllinks oder Passcodes nicht in allgemeine Logs schreiben.
- Falsch abgeschlossene Altvorschläge nicht beim Upgrade automatisch bestätigen oder schreiben.
- Eine ausdrücklich ausgelöste Neubewertung vorhandener `already_exists`-Vorschläge
  anhand des erhaltenen Videolinks und des aktuellen Kalenderstands ermöglichen.
  Den bestehenden Reanalyse-/Revisionsablauf zuerst auf Wiederverwendbarkeit prüfen.
- Fehlen gespeicherte Analyseinhalte, keine LLM-Ergebnisse erfinden. Erhaltene strukturierte
  Felder können für einen reinen Kalendervergleich ausreichen; andernfalls Originalmail
  ausdrücklich neu analysieren oder den fehlenden Inhalt verständlich melden.
- Historische Termine nicht ungefragt erneut anbieten. Der konkrete Produktivfall vom
  18.11. wird nur auf ausdrücklichen Wunsch neu bewertet und bleibt bestätigungspflichtig.

### 4.5 Warnhinweis bei Anmelde- und Authentifizierungsproblemen

**Auslöser:** Die Serverprüfung am 18.11.2026 meldete `token_refresh_denied` und
`access_check_failed` für Google Kalender. Solche Probleme müssen im normalen
Arbeitsablauf sofort erkennbar sein. Ein fehlgeschlagener Refresh ist nachgewiesen;
die genaue Ursache, etwa Ablauf oder Widerruf, ist damit noch nicht bestimmt.

#### Sichtbarkeit und Inhalt

- In der Mailübersicht einen dauerhaft sichtbaren Warnbereich oberhalb der Mailliste
  und unterhalb der Navigation vorsehen, auch bei leerer Liste oder aktiven Filtern.
  Alle Varianten der Mailübersicht einschließlich mobiler/PWA-Darstellung berücksichtigen.
- Der Bereich nennt Dienst und betroffenes Postfach beziehungsweise Zielprofil,
  Auswirkung, Zeitpunkt der letzten fehlgeschlagenen Prüfung und eine konkrete
  Abhilfe mit Link zur passenden Einrichtungs-/Verbindungsseite.
- Beispiel: „Google Kalender: Anmeldung fehlgeschlagen. Kalenderabgleich und
  Kalenderänderungen sind derzeit nicht möglich. Verbindung prüfen.“ Keine
  pauschale Behauptung „Token abgelaufen“, wenn nur ein Authentifizierungsfehler vorliegt.
- Mehrere betroffene Verbindungen gemeinsam anzeigen, pro Verbindung genau einen
  aktuellen Hinweis. Gesunde Verbindungen dürfen durch Fehler anderer Profile
  weder als defekt erscheinen noch blockiert werden.
- Warnungen bleiben bis zur nachgewiesenen Behebung sichtbar. Navigation, Filterwechsel,
  Seitenneuladen und Serverneustart dürfen sie nicht verbergen. Keine nur kurz
  eingeblendeten Toasts oder dauerhafte Unterdrückung durch Wegklicken.
- Auf bereits geöffneter Mailübersicht neue Fehler und deren Behebung über vorhandene
  Aktualisierungsmechanismen anzeigen, spätestens 30 Sekunden nach Speicherung des
  Status bei aktiver, verbundener Seite. Ohne JavaScript Anzeige beim nächsten Aufruf;
  nach Rückkehr einer getrennten Verbindung Status erneut laden.
- Barrierefrei mit aussagekräftigem Text, Symbol und geeignetem Live-Bereich; nicht
  allein über Farbe vermitteln und unveränderte Warnungen nicht wiederholt ansagen.
  Deutsche und englische Texte sowie Tastaturbedienung gehören zur Abnahme.

#### Erkennung und dauerhafter Status

- Bestehende Verbindungs-/Zugriffsprüfungen zuerst inventarisieren und als gemeinsame
  Statusquelle verwenden. Fehler nicht durch Auslesen von JSONL-Logs in der Webanfrage erkennen.
- Anmeldefehler aus Startprüfung, laufendem Abruf, Token-Erneuerung und bestätigten
  Aktionen erfassen: insbesondere Google Kalender, weitere konfigurierte Kalender,
  IMAP/IServ, Todoist und andere aktivierte Dienste mit Authentifizierung.
  Nur tatsächlich verwendete Verbindungen berücksichtigen; absichtlich deaktivierte
  oder noch gar nicht eingerichtete optionale Dienste erzeugen keine Störungswarnung.
- Abgelaufene oder widerrufene Zugänge, ungültige Client-Zugangsdaten, fehlende
  erforderliche Berechtigungen und ungültige Anmeldung nachvollziehbar unterscheiden,
  soweit der Dienst dies verlässlich meldet. HTTP 403 nicht pauschal als Tokenablauf
  werten; Timeout, Netzwerkfehler und Rate Limits sind eigene Fehlerarten.
- Der reguläre Ablauf „Access-Token abgelaufen → Refresh erfolgreich“ erzeugt keine Warnung.
  Ein noch ungeprüfter Zugang gilt nicht als nachweislich gesund.
- Status pro Dienst/Verbindung als lesbares JSON speichern: Zustand, sicherer Fehlercode,
  betroffene Funktion, erstmalig/zuletzt erkannt, letzte erfolgreiche Prüfung und
  Konfigurationsrevision. Keine Tokens, Passwörter, vollständigen Providerantworten
  oder Zugangsdaten in Status, Warntexten oder allgemeinen Logs ablegen.
- Statusänderungen geordnet anwenden: Ein verspätetes Ergebnis einer älteren Prüfung
  oder Konfiguration darf einen neueren Fehler nicht löschen beziehungsweise einen
  reparierten Zugang nicht erneut als defekt markieren. Upgrade mit bisher fehlendem
  Status, parallele Prüfungen und beschädigte Statusdateien ausdrücklich behandeln.
- Bestehende Start- und Laufzeitprüfungen anbinden; für sonst unbenutzte, aber aktive
  Verbindungen eine wiederkehrende rein lesende Prüfung vorsehen. Standardintervall
  15 Minuten, bei Fehlern begrenzte Wiederholung mit Backoff und Beachtung von Rate Limits.
  Vorhandene geeignete Intervalle wiederverwenden; neue Einstellungen nur in `config.yaml`
  und Konfigurationsbeispielen dokumentieren. Kein Netzaufruf pro Seitenrendering.

#### Wiederherstellung und Autorisierung

- „Verbindung prüfen“ führt zur bestehenden passenden Einrichtungsseite. Ein erneuter
  Login benötigt die dort vorgesehenen Schritte; die Warnung selbst führt keine
  Anmeldung, Konfigurationsänderung oder externe Schreibaktion aus.
- Bearbeiten oder Speichern neuer Zugangsdaten löscht den Fehler nicht als Erfolg.
  Erst eine erfolgreiche aktuelle Prüfung der betroffenen Funktion entfernt den Hinweis.
  Bei mehreren Fehlern nur den tatsächlich behobenen Verbindungsstatus zurücksetzen.
- Ausschließlich lesende Zugriffsprüfungen verwenden, keine Probe-Termine oder -Aufgaben.
  Während einer Störung keine unklaren Schreibresultate blind wiederholen. Wiederherstellung
  erteilt keine neue Schreibberechtigung und überspringt keine Versions-/Sitzungsprüfung.
- Warnbereich und Status-Endpunkte nur im authentifizierten Bereich anbieten;
  keine Kontodetails auf der Loginseite oder in öffentlichen Health-Antworten veröffentlichen.
  Eine abgelaufene Web-Sitzung führt weiterhin zur Anmeldung, ohne Verbindungsdetails preiszugeben.

### 4.6 Zentraler Google-OAuth-Callback: Umsetzung in 8.0

Die am 18.11.2026 festgelegte gemeinsame Callback-Adresse
`https://auth.inboxstride.de/auth/google/callback` bleibt die Architekturentscheidung
für gehostete Nutzerinstanzen. Die Umsetzung erfolgt in Version 8.0, einschließlich
Ersteinrichtung, Kontowechsel und zentraler Token-Erneuerung.

Maßgeblich ist [Planung 8.0](Planung-8.0.md). Sie konkretisiert und ersetzt die
bisher hier skizzierte Tokenübergabe: Der zentrale Dienst verwaltet Refresh-Tokens
und das gemeinsame Client-Secret; Nutzerinstanzen erhalten kurzlebige Access-Tokens
über eine authentifizierte interne Schnittstelle. Eine reine Redirect-Änderung
oder ein statischer Proxy auf Stefans Instanz ist keine Mehrnutzerlösung.

Die Kalenderergänzungen und Warnhinweise aus 7.9 bleiben davon unabhängig.
Der zentrale Dienst ist keine Voraussetzung für ihre Auslieferung.

## 5. Tests und Fehlernachweis

Zuerst synthetische Regressionstests schreiben und am unveränderten Ausgangscode rot
nachweisen. Danach Fix implementieren und dieselben Tests grün nachweisen. Keine echten
Mails, persönlichen URLs oder produktiven Dienste verwenden.

| Bereich | Verbindliche Fälle |
| --- | --- |
| Vorabprüfung | Gleiche Zeiten + fehlender Link + `new` ergibt Update; dasselbe mit `change`; Ledger-Treffer überspringt Ergänzung nicht |
| Zielprüfung | Bereits identischer Link, anderer Link, kein Ziel, mehrere Treffer, gelöschtes Ziel, Such-/Lesefehler |
| Datenvergleich | Beschreibung und native Konferenzfelder; erhaltene Queryparameter; Anmeldelink ist kein Einwahllink; ungültige Eingabe |
| Schreibnutzlast | Link wird tatsächlich gespeichert; bestehende Notizen, Titel, Zeiten, Teilnehmer und fremde Felder bleiben erhalten |
| Kombinationen | Zeitänderung mit Link; reine Ortsänderung; Stornierung; unterstützte Einzeltermine und abgelehnte Serienfälle |
| Autorisierung | Bearbeiten/Speichern und GET lösen keinen Schreibzugriff aus; fehlende/abgelaufene Sitzung, falsches CSRF, alte Version und widerrufene Bestätigung scheitern |
| Wiederholung | Zweiter Abruf, doppelte Bestätigung, parallele Mails, Neustart vor/nach Schreiben und identischer Link erzeugen keine Duplikate |
| Konkurrenz | Ziel zwischen Vorschau und Schreiben geändert, Link inzwischen vorhanden, anderer Link inzwischen vorhanden, konkurrierende Notizänderung |
| Unklares Ergebnis | Timeout vor/nach erfolgreichem Schreiben; Abgleich vor Wiederholung; Nachprüfung erkennt fehlenden/falschen Link |
| Altbestand | Neubewertung von `already_exists`, entfernte Analysedaten, alte Schemafassung, keine automatische Kalenderänderung |
| Oberfläche | Web und Telegram zeigen Ergänzung/Konflikt sowie korrekte Version; deutsche und englische Texte; Vorschlag bleibt sichtbar |
| Provider | Google Kalender und alle unterstützten Kalenderadapter erhalten die bestätigte Ergänzung korrekt; eingeschränkte Fähigkeiten scheitern verständlich |
| Authentifizierungswarnung | Abgelehnter Google-Refresh erscheint oberhalb der Mailübersicht; erfolgreiche automatische Erneuerung bleibt ohne Warnung; Fehler aus Startprüfung und Laufzeit erreichen dieselbe Statusquelle |
| Warnungsumfang | Mehrere Dienste/Profile, deaktivierte optionale Dienste, fehlende Berechtigungen, Netzwerkfehler/Rate Limits und ungeprüfter Zugang werden korrekt unterschieden |
| Warnungsdauer | Filter, leere Liste, Reload und Neustart erhalten Fehler; bloßes Speichern entfernt sie nicht; erfolgreiche aktuelle Prüfung entfernt nur die behobene Warnung |
| Warnung und Konkurrenz | Alte Prüfergebnisse und alte Konfigurationsrevisionen überschreiben keinen neueren Status; fehlende/defekte Statusdatei und Upgrade werden behandelt |
| Warnung und Oberfläche | Sichtbar auf Desktop/Mobil/PWA, Deutsch/Englisch, barrierefrei; aktive Seite aktualisiert binnen 30 Sekunden, Wiederverbindung und Betrieb ohne JavaScript funktionieren |
| Warnung und Sicherheit | Keine Geheimnisse im Status oder HTML; öffentlicher/abgelaufener Zugriff erhält keine Details; rein lesende Prüfung; Wiederanmeldung autorisiert keinen Kalender-/Todoist-Schreibzugriff |

Vorhandene Tests insbesondere in `tests/services/test_precheck.py`,
`tests/services/test_calendar_target.py`, `tests/services/test_calendar_duplicates.py`,
den externen Schreibtests sowie Web-, Telegram-, Upgrade- und Browsersuites erweitern.
Ein durchgängiger synthetischer Test prüft Mail → Vorschlag → Bestätigung →
simulierter Kalender → Nachprüfung und anschließende Wiederholung.

Verbindliche Abschlussprüfungen, nacheinander ausführen:

```powershell
python -m devtools.check full --workers 12
python -m pytest ui_tests -n 6 --dist worksteal --no-cov
```

100 % Zeilen- und 100 % Branch-Abdeckung für eigenen Anwendungscode bleiben
verbindlich; die Prüfung muss bei Unterschreitung eines Werts scheitern. Keine
Coverage-Ausnahmen oder wirkungslosen Tests. Python- und Browsersuite nie gleichzeitig.

## 6. Arbeitspakete und Freigabekriterien

1. Ausgangsstand prüfen, Zustandsmodell und alle Kalenderadapter inventarisieren;
   synthetischen Fehlerfall vor dem Fix reproduzieren.
2. Gemeinsamen Vergleich, persistierte Änderung, Versionsbindung und gegebenenfalls
   Schema-Upgrade implementieren; Vorabprüfung und Zielprüfung daran anbinden.
3. Bestätigungsvorschau und Schreibpfade einschließlich Wiederanlauf, Konkurrenz,
   Idempotenz und Nachprüfung durchgängig umsetzen.
4. Explizite Altfall-Neubewertung, dauerhaften Verbindungsstatus und Warnbereich in
   der Mailübersicht einschließlich Aktualisierung und Diagnose ergänzen; alle Testfälle abdecken.
5. Spezifikation, `README.md`, `CHANGELOG.md`, Bedienung und Hilfe einschließlich
   englischer Texte aktualisieren. Konfigurationsbeispiele beschreiben den neuen
   Ablauf; keine neue Pflichtkonfiguration. Falls Prompts angepasst werden, nur in
   `prompts.yaml` und zugehörigen Paketdefaults, Modelle/LLM-Parameter ebenfalls dort.
6. Beide vollständigen Prüfungen bestehen lassen; Zahlen, Coverage sowie roten/grünen
   Regressionsnachweis in `docs/Release-7.9.md` dokumentieren.
7. Erste Implementierung als 7.9.1 veröffentlichungsfähig vorbereiten. Bei jedem Commit
   auf `main` oder `beta` die geltende Patchversionsregel anwenden; `pyproject.toml`
   und `src/mailhelp/__init__.py` synchron halten, Changelog und README mitführen.

Abnahme: Der synthetische Ausgangsfall erzeugt einen bestätigungspflichtigen
Aktualisierungsvorschlag und ergänzt nach Bestätigung den bestehenden Kalendertermin
genau einmal. Der neue Link wird nachgelesen; unabhängige Inhalte bleiben erhalten.
Identische Zugangsdaten bleiben Duplikate. Alle Fehler-, Autorisierungs-, Konflikt-
und Neustartfälle sowie beide vollständigen Prüfungen bestehen.

Zusätzliche Abnahme: Ein simuliert abgelehnter Google-Refresh erzeugt ohne weiteren
Kalenderschreibversuch einen sichtbaren Warnhinweis in der Mailübersicht. Er bleibt
bei Navigation und Neustart erhalten und verschwindet erst nach erfolgreicher
aktueller Zugriffsprüfung. Bereits geöffnete aktive Übersichten werden innerhalb
von 30 Sekunden nach Statusänderung aktualisiert. Die Prüfung verändert keine externen Daten.

Bereitstellung und eine eventuelle Korrektur produktiver Alttermine sind getrennte
Folgeschritte. Dieser Plan enthält keinen Auftrag zum Deployment oder Kalender-Schreiben.
