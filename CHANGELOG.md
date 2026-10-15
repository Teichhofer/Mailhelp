# Änderungen

## 3.4.1 – beta: Dokumentation für IServ, Zugangsdaten und Einstellungen vervollständigt

- Neue [Release-Anleitung 3.4](docs/Release-3.4.md) mit Einrichtung der IServ-Elternbriefe über
  die Weboberfläche und über Dateien, der Zugangsdatenseite, den neuen Einstellungen und den
  Änderungen seit 3.3.2; im Quellarchiv enthalten und in der README verlinkt.
- Einrichtungsanleitung um einen Abschnitt zu IServ-Elternbriefen und die Zugangsdaten im Web
  ergänzt; Web-Einstellungen beschreiben die Seiten IServ-Konten und Zugangsdaten.
- Hilfetext zum Kalenderdienst nennt die Zugangsdatenseite; Planung 4.0 vermerkt die vorgezogene
  Zugangsdatenverwaltung.
- Projektwebsite: IServ-Elternbriefe, Zugangsdaten im Web und weitere Einstellungen auf Start-,
  Einrichtungs-, Konfigurations- und Datenschutzseite.

## 3.4.0 – beta: Quellen, Zugangsdaten und Einstellungen im Web (Planung 3.4)

Abschluss von Planung 3.4 (Phasen 1–3 in 3.3.10–3.3.12):

- Postfächer und IServ-Konten lassen sich vollständig über die Weboberfläche anlegen,
  ändern, deaktivieren und entfernen – als geprüfter Entwurf mit Diagnose und ausdrücklicher
  Übernahme.
- Zugangsdaten werden unter Einstellungen → Zugangsdaten nur schreibend gepflegt; gespeicherte
  Werte erscheinen nie in der Oberfläche oder in Protokollen.
- Alle für den Betrieb relevanten Einstellungen sind im Web änderbar; ausgenommen bleiben nur
  Werte, deren Fehlbedienung den Zugang zur Weboberfläche oder die Datenablage gefährdet.
- Gesamtabnahme: 2478 Tests mit 100 % Abdeckung, 167 Browsertests, ruff und mypy ohne Befund.

## 3.3.12 – beta: Weitere Einstellungen in der Weboberfläche (Planung 3.4, Phase 3)

- Unter Einstellungen sind 29 weitere Werte änderbar, jeweils mit Hilfetext: Stapelgröße und
  Reihenfolge des Mailabrufs, Telegram-Benutzer, -Chat und Fragen nacheinander, Antwortentwürfe,
  Bildauswertung, Inhalte des Tagesüberblicks, Tätigkeitsberichte, parallele Aufrufe im
  Lernmodus, Aufbewahrung von Tätigkeitsberichten, Sitzungsdauer, Zugriff im eigenen Netzwerk
  sowie Schalter und Stufen der Protokollierung.
- Die Einrichtung bietet je Postfach die Startgrenze `historical_start` an.
- Bewusst weiterhin nur in `config.yaml`: Datenverzeichnis, Logpfade, Adresse, Port und
  zugelassene Hostnamen der Weboberfläche sowie die Parser-Sicherheitsgrenzen.

## 3.3.11 – beta: Zugangsdaten in der Weboberfläche (Planung 3.4, Phase 2)

- Neu: Einstellungen → Zugangsdaten (`/einstellungen/zugangsdaten`) listet alle Zugangsdaten,
  die die Konfiguration benötigt – je Postfach, je IServ-Konto, OpenRouter, Telegram und die
  Zielanbieter je Zielprofil – und erlaubt, sie einzutragen oder zu ersetzen.
- Nur schreibend: gespeicherte Werte werden nie angezeigt. Speichern braucht eine gültige,
  vor dem Schreiben erneut geprüfte Sitzung, CSRF-Schutz, Idempotenzschlüssel, ausdrückliche
  Bestätigung und den unveränderten Stand von `.env`; nur die betroffene Zeile wird ersetzt.
- Protokolle nennen nur den Namen; neue Werte werden sofort maskiert. `MAILHELP_WEB_SECRET`
  bleibt ausgenommen, weil eine Änderung alle Sitzungen beenden würde.

## 3.3.10 – beta: IServ-Konten in der Weboberfläche (Planung 3.4, Phase 1)

- Neu: Unter Einstellungen → IServ-Konten (`/einstellungen/iserv`) lassen sich IServ-Konten
  hinzufügen, ändern, aktivieren, deaktivieren und entfernen. Jede Änderung ist ein Entwurf,
  der geprüft und erst nach aktueller Diagnose und ausdrücklicher Übernahme in `config.yaml`
  geschrieben wird.
- Fehler behoben: Nach dem Übernehmen eines Einrichtungsentwurfs (etwa eines neuen Postfachs)
  blieb der Entwurf auf dem alten Dateistand stehen; die Postfachseite brach danach ab und
  weitere Änderungen waren blockiert. Übernommene Entwürfe werden jetzt geleert.
- Neue Planung 3.4: Quellen, Zugangsdaten und Einstellungen vollständig im Web.

## 3.3.9 – beta: Diagramme in der Auswertung

- Die Auswertungsseite zeigt für die gewählten Filter Diagramme: KI-Aufrufe je Tag
  (erfolgreich und fehlgeschlagen), gemeldete Cloudkosten je Tag, die Verteilung der
  Aufrufdauer, die summierte Dauer je Verarbeitungsschritt und die Kosten je Modell.
  Bei „Heute“ gilt die Einteilung je Stunde in der konfigurierten Zeitzone.
- Die Diagramme sind serverseitiges SVG ohne Skripte, passen sich hellem und dunklem
  Design an und bieten ihre Werte zusätzlich als aufklappbare Tabelle für Screenreader.

## 3.3.8 – beta: IServ in Einrichtung und Diagnose

- Fehler behoben: Die Zugangsdatenübersicht der Einrichtung nannte die IServ-Zugangsdaten
  nicht. Sie zeigt jetzt je aktivem IServ-Konto `ISERV_<id>_USERNAME/ISERV_<id>_PASSWORD`
  als vorhanden oder fehlend; neu in `.env` eingetragene Werte erscheinen ohne Neustart.
- Die Diagnose hat eine eigene IServ-Prüfung: Anmeldung und Öffnen der Briefübersicht,
  ohne Briefe zu lesen. Eine abgelehnte Anmeldung wird als Zugangsdatenproblem gemeldet.

## 3.3.7 – beta: IServ-Elternbriefe als Quelle

- Neu: Elternbriefe aus dem IServ-Elternbriefmodul werden wie Mails verarbeitet.
  Mailhelp meldet sich mit dem Elternkonto an der IServ-Weboberfläche an, liest neue
  Briefe samt Anhängen und behandelt sie immer als relevant, ohne Modellaufruf und
  ohne Absenderfilter. Zielprofil und Standards folgen dem angegebenen Postfach.
- Konfiguration unter `iserv.accounts`, Zugangsdaten als `ISERV_<id>_USERNAME` und
  `ISERV_<id>_PASSWORD`; der Abschnitt ändert den Analyse-Fingerprint nicht.
- Abruf nur innerhalb der HTTPS-Adresse der Schule, Größengrenzen wie bei Mails,
  keine URLs oder Zugangsdaten in Logs. Unvollständige Briefe werden nach Fehlern
  wiederaufgenommen; Statusseite, `--check-access` und Startprüfung kennen IServ.
- Für Elternbriefe gibt es keine Antwortentwürfe; Mailhelp verändert in IServ nichts.
  Zwei-Faktor-Anmeldung und mehrseitige Übersichten werden noch nicht unterstützt.

## 3.3.6 – beta: Weboberfläche bleibt nach einem Code-Wechsel konsistent

- Fehler behoben: Der Webserver las Stylesheet, Skript, Service Worker und Offline-Seite
  bei jeder Anfrage von der Platte. Wechselte bei laufendem Dienst der Codestand im
  Installationsverzeichnis (Update, Branch-Wechsel einer editierbaren Installation),
  kombinierte ein Neuladen neue Seiten mit altem CSS, und das Layout zerfiel.
  Diese Dateien werden jetzt einmal beim Start geladen und passen bis zum Neustart
  zur laufenden Version.

## 3.3.5 – beta: Verständliche Meldung bei bereits laufender Instanz

- Fehler behoben: Ein zweiter Start mit demselben Datenverzeichnis endete mit einem
  Python-Traceback. Mailhelp meldet jetzt in einer klaren Zeile, dass bereits eine
  Instanz läuft, nennt das Verzeichnis und erklärt, wie die laufende Instanz beendet
  wird; der Exit-Code ist 1. Die Sperre selbst ist unverändert.

## 3.3.4 – beta: IMAP-Abruffehler und sichere UID-Grenzen

- Aktuelle Fehler beim Lesen eines Haupt- oder zusätzlichen Ordners erscheinen auf
  der Statusseite, auch wenn der Durchlauf keine Mail für die Analyse laden konnte.
  Hinweise bleiben je Postfach und Ordner erhalten, bis dieser wieder erfolgreich
  gelesen wird. Provider-Fehlertexte und Zugangsdaten werden nicht im Web angezeigt.
- Regressionstests für leere Durchläufe mit Ordnerfehlern, Status-Aktualisierung,
  erneute Fehler, isolierte Postfächer, erfolgreiche Wiederholung und sichere Darstellung.
- Lokale Ordnernamen und der Entwurfsordner anhand der lesenden IMAP-Liste korrigiert;
  Anleitung und Beispiel weisen auf anbieterspezifische Namen hin.
- Absturz bei Checkpoints behoben: Die IMAP-Suche kann bei `UID Start+1:*` die
  höchste vorhandene UID erneut liefern. Treffer an oder unter der gespeicherten
  Startgrenze werden vor dem Abruf ausgeschlossen. Der Abschluss alter
  Warteschlangeneinträge und separater Wiederaufnahmen verändert diese Grenze nicht.
  Regressionstests prüfen Wiederholungen, neue Mails und dauerhaft lesbare
  Checkpoints nach Neustarts.

## 3.3.3 – beta: Dienststatus sofort nach dem Start

- Fehler behoben: Ein Mailabruf ohne neue Mail ließ das IMAP-Postfach auf der Statusseite
  „unbekannt“, weil der Abruf seit 3.1 über `discover_since` läuft und dessen Ereignis nicht
  als Kontakt zählte. Ebenso zählt jede erfolgreiche Telegram-Abfrage, auch ohne Nachricht.
- Beim Dienststart prüft Mailhelp im Hintergrund lesend OpenRouter bzw. Ollama, Telegram
  (ohne Testnachricht) und die Ziele der aktiven Zielprofile. Die Statusseite zeigt diese
  Dienste damit sofort als erreichbar; die Mailverarbeitung wartet nicht auf die Prüfung.
  Fehlschläge werden nur als Warnung protokolliert.

## 3.3.2 – beta: Dokumentation geprüft und aktualisiert

- README, Changelog, Projektspezifikation, Einrichtungsanleitung, Datenschutzerklärung,
  Nutzungsbedingungen und Projektwebsite auf den Stand 3.3 gebracht: optionale
  Telegram-Nutzung, lokale Webkopplung, mehrere Postfächer und Zielprofile,
  Google-Desktop-OAuth mit Profilnummer, aktivierte Inhaltslogs im Beispiel.
- Neue [Release-Anleitung 3.3](docs/Release-3.3.md) (im Quellarchiv enthalten) und
  [Prüfbericht zur Dokumentation](docs/Pruefung-Dokumentation.md).
- 35 ältere Pläne, Konzepte und Release-Dokumente sind als historisch gekennzeichnet;
  Planung 3.3 trennt umgesetzte Phasen von offenen Architekturzielen.
- Keine Änderung am Anwendungsverhalten.

## 3.3.1 – beta: Entwicklungsregel für README-Aktualisierung

- Entwicklungsregeln in `AGENTS.md` um die Vorgabe ergänzt, bei jeder neuen Version auch die Datei `README.md` zu aktualisieren.
- Weboberfläche mit gruppierter Desktop-Seitenleiste, kompakter Handy-Navigation,
  klarerer Seitenhierarchie, aufklappbaren Vorschlagsbelegen und Einstellungs-Bereichslinks.
  Der Shell-Cache wird beim Update erneuert. Das Facelift wurde zunächst als 3.3.2
  committet; der folgende Versionskorrektur-Commit führt denselben Funktionsstand als 3.3.1.

## 3.3.0 – beta: Technische Konsolidierung (Planung 3.3)

Abschluss von Planung 3.3 (Phasen 1–4 in 3.2.4–3.2.7). Verhalten, CLI, Telegram-Befehle und Web-Routen sind unverändert.

- Strikte Typprüfung zusätzlich für Persistenz, Normalisierung, Zusammenführung, Vorprüfung, Evaluation,
  Konfiguration, Laufschleife, Dienstkoordination, Telegram und Review; `mailhelp.telegram` exportiert eine
  ausdrückliche Namensliste.
- `writer_for`, `retarget`, `profile_references` und `TelegramCommands` sind vollständig annotiert. Die Abbruchlogik
  liest die Dialogreferenz über `TelegramDialogState.reference()`.
- Gesamtabnahme: 2360 Tests mit 100 % Zeilen- und Branch-Abdeckung, 146 Browsertests, ruff und mypy ohne Befund.
- Noch offen sind die Strictness für `mailhelp.web.*` und die Bündelung der Wurzelmodule in Unterpakete
  (siehe Planung 3.3, Abschnitt 5).

## 3.2.7 – beta: Planung 3.3, Phase 4 – Parser und Konfiguration konsolidiert

- `config.py` ist das Paket `mailhelp.config`: Modelle und Validierungsregeln in `config/models.py`,
  Datei- und Umgebungszugriff in `config/loader.py`; alle bisherigen Namen bleiben über `mailhelp.config` importierbar.
- Deutsche Monats- und Wochentagsnamen, Jahreserkennung und Wochentagsprüfung liegen einmalig in
  `mailhelp.german_dates`; die Datumsnormalisierung nutzt sie mit unveränderten Mustern und ist in benannte
  Schritte zerlegt (numerisch, ausgeschrieben, ohne Jahr).
- Telegram-Receiver, Weboberfläche, Erlebnis- und Benachrichtigungslaufzeit starten und stoppen über den neuen
  `ServiceCoordinator`; `Application` führt `lifecycle`, `configuration` und `profile_writers` typisiert statt als `Any`/`object`.
- Verhalten unverändert; der Empfangsoffset wird weiterhin nur für Dialoge mit Telegram-Eingang gelesen (eigener Test).

## 3.2.6 – beta: Planung 3.3, Phase 3 – Weboberfläche entflochten

- `ArchiveSite` ist in fünf Seitenklassen zerlegt (Mailarchiv, Verlauf/Auswertung, Vorschlagsbearbeitung,
  Einstellungen/Themen, Beenden); der verbleibende Knoten hält nur noch gemeinsam genutzte Dienste.
- HTML-Erzeugung und Routing sind getrennt: `archive_pages`, `settings_pages`, `reconciliation_pages`,
  `sender_pages`; gemeinsame Formularbausteine (`post_form`, `field`, `select`) in `web/forms.py`.
- Routen, Seiten und Formulare unverändert; 146 Browsertests und 100 % JavaScript-Abdeckung bestätigt.

## 3.2.5 – beta: Planung 3.3, Phase 2 – Komplexitätsabbau

- Die verschachteltsten Funktionen sind in benannte Schritte zerlegt, ohne Verhaltensänderung:
  `merge_facts` (McCabe 29 → 6), `validate_consistency` (26 → 2, Prüfreihenfolge unverändert),
  Telegram-`overview` (21 → 8) und Schreib-`execute` (19 → 9), Vorschlagskarte (17 → 2),
  Metrikbeobachtung (17 → 2), IMAP-Ermittlung (17 → 3) und Abgleichvorschau (16 → 3).
- ruff prüft die McCabe-Komplexität dauerhaft (`C90`, höchstens 15 je Funktion).
- Zusätzlicher Test: unsichere Quellen behalten ihre offenen Zeitfragen.

## 3.2.4 – beta: Planung 3.3, Phase 1 – Typprüfung und Entkopplung von Telegram

- `mypy --check-untyped-defs` meldet keine Befunde mehr (vorher 18) und ist über `check_untyped_defs`
  dauerhaft Teil der CI-Typprüfung. Dafür u. a. ein `LlmCompleter`-Protokoll für die Evaluation und
  eindeutige Variablen in der Postfachseite.
- Die deterministische Zeitauflösung liegt als `mailhelp.temporal_answers` außerhalb des Telegram-Pakets;
  `analysis` und `mail_questions` importieren sie ohne späten Import. Die Revisionsfehler liegen in
  `mailhelp.domain.revision_errors`; der Importkreis Analyse ↔ Telegram ist aufgelöst.
- `ActionLedger` und `ProposalRepository` liegen in `mailhelp.persistence.ledger` bzw.
  `mailhelp.persistence.proposals`. Ein Architekturtest begrenzt Telegram-Importe außerhalb des Pakets auf
  Anwendung, Komposition, Orchestrator und Prüfdienst.
- Testsuite ohne Warnungen (Pydantic-Serialisierung, Assertion-Rewrite der gemeinsamen Fakes).
- Verhalten unverändert.

## 3.2.3 – beta: Planung 3.3 aktualisiert, Fehler in Antwortentwürfen behoben

- **Fehler behoben:** Ein Betreff mit Zeilenumbrüchen gelangte unverändert in die `Subject`-Kopfzeile
  eines Antwortentwurfs; mit `\r\n` scheiterte das Speichern. Der Betreff wird jetzt auf eine Zeile
  normalisiert (eingeschleuste Kopfzeilen bleiben ausgeschlossen). Eine Antwortadresse ohne Teil vor oder
  nach dem `@` (z. B. `@0`) wird abgelehnt statt als leerer Empfänger übernommen. Gefunden vom
  Eigenschaftstest `test_reply_drafts_never_carry_injected_headers`; Regressionstest
  `test_draft_subject_stays_one_line_and_recipients_need_both_address_parts` scheiterte vor der Korrektur.
- [Planung 3.3](docs/Planung-3.3.md) (technische Konsolidierung, Nachfolger der früheren Planung 2.5) mit
  gemessenen Ausgangswerten: 18 mypy-Befunde unter `--check-untyped-defs`, 8 Funktionen über
  McCabe-Komplexität 15. Planung 4.0 in das Repository aufgenommen.

## 3.2.2 – Überarbeitete README

- README als Produkt- und Betriebsdokumentation neu strukturiert: Funktionen, Installation,
  Konfiguration, Betrieb, Datenschutz und Qualitätssicherung übersichtlich zusammengefasst.
- Direkte Verweise auf Planungs- und Konzeptdokumente entfernt. Weiterführende Anleitungen
  sind nach Anliegen geordnet; Links und dokumentierte Schemaversion wurden geprüft.

## 3.2.1 – Einstellungen je Postfach

- Sparsame Postfachüberschreibungen mit globaler Vererbung für persönliche Angaben, Antwortentwürfe,
  Ruhezeiten/Kategoriekanäle, Tagesüberblick, Berichtsordner, kürzere Volltextaufbewahrung und Termindauern.
- Zielprofile 2–99 mit getrennten Geheimnissen und Adaptern; nur OAuth-App-Zugangsdaten dürfen gemeinsam
  genutzt werden. Google-Browseranmeldung und Microsoft-Gerätecode unterstützen `--profile`.
- Vorschläge Schema 3 binden ihr Profil dauerhaft. Lesender Vorabgleich und Wiederanlauf nach unklarem
  Schreibergebnis verwenden dieses Profil. Zielumstellen in Web/Telegram erzeugt eine neue unbestätigte
  Version; Profilfehler beeinträchtigen andere Profile nicht.
- Themen und ausgeschlossene Themen unterstützen `mailboxes`. Filter Schema 2 kombiniert globale und
  lokale Sperren mit lokalen `allow`-Ausnahmen; Schema 1 wird erst beim Schreiben mit Sicherung migriert.
  Lernen schlägt das Ursprungspostfach vor; Decision-Test und Berichte verwenden die wirksamen Filter.
- Fünf Postfach-Tabs, Profilverwaltung mit Verweisprüfung, versionierte Einrichtungsentwürfe und Vorschau
  betroffener laufender Mails. Profilgebundene Diagnosen und Anzeige in Telegram und Web.
- Postfachbezogene Benachrichtigungsrichtlinien und Tagesabschnitte erhalten Versandmarker beim Upgrade.
  Bereits eingereihte Abschnitte werden verworfen, wenn ihr Postfach inzwischen ausgeschlossen wurde.
- Sämtliche Ziele sind aus dem Analyse-Fingerprint entfernt. Beim Upgrade werden die bisherigen
  Fingerprints und Themenrichtlinien bis 3.1 als gleichwertig registriert; laufende Mails und gebundene
  Vorschlagsziele bleiben erhalten. Details zu Upgrade/Backup/Rollback stehen in
  [Release 3.2](docs/Release-3.2.md).
- Regression: CalDAV-URLs mit eingebetteten Benutzernamen werden abgewiesen. Kleine YAML-Feldänderungen
  behalten Kommentare; Mischentwürfe mit Listen und Benachrichtigungsregeln werden sicher bearbeitet.
  Die Einstellungs-Vorschau berücksichtigt registrierte Alt-Hashes und hält bei reinen Zieländerungen
  keine laufenden Mails zurück.
  Themenbeschränkungen halten auch bei migrierten 3.1-Mails nur Postfächer mit veränderten wirksamen
  Themen zurück.

## 3.1.3 – beta: Telefonansicht, Release-Texte und CI-Actions

- **Fehler behoben:** Auf Telefonen bricht die Navigation auf mehrere Zeilen um; als klebende Kopfleiste
  verdeckte sie einen großen Teil des Bildschirms, und Schaltflächen wie „Relevant“ rutschten beim
  Scrollen darunter. Der Browsertest `test_details_show_the_complete_mail[mobile]` scheiterte deshalb
  in der CI zufällig. Unter 720 px Breite scrollt die Kopfleiste jetzt mit der Seite. Regressionstest
  `test_phone_header_scrolls_away_and_never_covers_actions` scheiterte vor der Korrektur.
- **Fehler behoben:** Jedes GitHub-Release erhielt den Text von Release 1.0. Der Release-Workflow
  erzeugt den Text jetzt aus dem Changelog-Abschnitt der getaggten Version mit absoluten Links und dem
  Verweis auf `docs/Release-X.Y.md`; fehlt der Abschnitt, scheitert die Veröffentlichung. Tests in
  `tests/release/test_release_notes.py`.
- GitHub-Actions auf Node.js 24 umgestellt: `actions/checkout@v6`, `actions/setup-python@v6`,
  `actions/upload-artifact@v6`.

## 3.1.2 – beta: Lernmodus und Decision-Test über alle Postfächer

- `--mailbox alle` (auch `all`) wählt für `--learn` und `--decision-test` alle aktivierten Postfächer:
  `N` begrenzt die neuesten Mails über alle Postfächer zusammen (Reihenfolge wie beim Abruf; ohne
  globale Sortierung Postfach für Postfach). `--mailbox <n>` wählt weiterhin ein einzelnes Postfach;
  bei mehreren aktivierten Postfächern bleibt eine der beiden Angaben Pflicht.
- Der Decision-Test vergleicht identische Rohmails aus mehreren Postfächern nur einmal; der Bericht nennt
  `mailboxes` und bei mehreren Postfächern `historical_start` je Postfach.
- Der Lernmodus ergänzt neue Ordner im Eintrag des jeweiligen Postfachs.
- Spezifikation, Release-Anleitung 3.1, Planung 3.1 und `config.example.yaml` angepasst; neue Tests für
  Auswahl, Reihenfolge, Duplikate und CLI.

## 3.1.1 – Übernahme von beta nach main

- Den committierten beta-Stand mit offenem Vorschlagsabgleich, Standarddauern,
  Einrichtung, Diagnose, Benachrichtigungen und mehreren Postfächern für main vorbereiten.
- Patchversion in Paketmetadaten und Anwendung gemäß den Commit-Regeln erhöhen.
- Die Übernahme erfolgt nach erfolgreicher vollständiger GitHub-CI einschließlich
  Coverage-, Browser-, Paket- und Containerprüfungen.

## 3.1.0 – beta: Mehrere Postfächer

Planung: [docs/Planung-3.1.md](docs/Planung-3.1.md); Einrichtung, Upgrade und Rückkehr:
[docs/Release-3.1.md](docs/Release-3.1.md). Umgesetzt schrittweise in 3.0.1 bis 3.0.5 (Einträge unten).

- Bis zu zehn IMAP-Postfächer (`imap.mailboxes`, Zugangsdaten `IMAP_<n>_USERNAME`/`IMAP_<n>_PASSWORD`);
  das bisherige Format bleibt als Postfach 1 gültig.
- Gemeinsamer Abruf mit globaler Auswahl und gemeinsamem Kontingent, Fehler je Postfach isoliert,
  postfachübergreifende Duplikaterkennung, laufende Mails überstehen Upgrade und Umstellung.
- Entwürfe und Tätigkeitsberichte im jeweiligen Postfach; `--mailbox` für Lernmodus und Decision-Test.
- Postfach-Labels und -Filter in Weboberfläche und Telegram; Diagnose aller Postfächer.
- Release-Anleitung 3.1, Datenschutzhinweis und README ergänzt. Der Release-Tag `v3.1.0` wird erst nach
  erfolgreicher CI-Matrix (Linux, Docker, Paketinstallation) gesetzt.

## 3.0.5 – beta: Planung 3.1, Phase 5 – Weboberfläche, Telegram, bis zu 10 Postfächer

- Bis zu 10 Postfächer; zwei aktivierte Postfächer mit demselben Server, Port und Benutzer werden beim
  Start abgelehnt.
- Maildetail und Archivliste nennen das Postfach, das Archiv filtert nach `postfach=<n>`; Telegram-Karten
  zeigen `✉️ [Label] Absender · Betreff`. Mit einem Postfach bleibt die Darstellung unverändert.
- Diagnose `imap` prüft alle aktivierten Postfächer des Entwurfs; Ordnerauswahl im Einrichtungsschritt je
  Postfach; Anzeigename und Aktivierung sind dort bearbeitbar.
- Verschoben nach 3.2: Postfächer im Web hinzufügen/entfernen, Labels in Entscheidungsübersicht und
  Tagesüberblick, Telegram `/status` je Postfach.
- Abnahme: 2223 Python-Tests mit 100 % Zeilen- und Branch-Abdeckung, 134 Browsertests.

## 3.0.4 – beta: Planung 3.1, Phase 4 – postfachbezogene Funktionen

- Antwortentwürfe gehen nur in den Entwurfsordner des Ursprungspostfachs (eigene Verbindung und
  Absender); ein nicht mehr eingerichtetes Postfach wird abgelehnt, der Text bleibt erhalten.
- Tätigkeitsberichte gehören zu einem Postfach: Auswahl ohne JavaScript, Ordnervorschläge und -prüfung je
  Postfach, Zählen und Lesen nur dort. Schema-Snapshot `ActivityReport` um `mailbox` (Standard 1) ergänzt;
  ältere Berichte bleiben ohne Migration lesbar.
- `--learn` und `--decision-test` lesen genau ein Postfach; bei mehreren aktivierten Postfächern ist
  `--mailbox <n>` Pflicht. Der Lernmodus liest mit dem Reader dieses Postfachs.

## 3.0.3 – beta: Planung 3.1, Phase 3 – Duplikate über Postfächer hinweg

- Der Duplikatindex vergleicht mit den Einträgen aller Postfächer: Dieselbe Mail in zwei konfigurierten
  Postfächern wird nur einmal analysiert und verweist auf die zuerst verarbeitete Mail. Wiederverwendete
  Message-IDs mit anderem Inhalt bleiben auch postfachübergreifend `ambiguous`. Regressionstest
  `test_the_same_message_in_a_second_mailbox_is_skipped` scheiterte vor der Änderung.
- Sortierung offener Vorschläge geprüft: durch die Mail-ID als zweites Kriterium auch bei gleicher UID in
  zwei Postfächern eindeutig; unverändert.

## 3.0.2 – beta: Planung 3.1, Phase 2 – Laufzeitkern für mehrere Postfächer

- Ein Reader je aktiviertem Postfach (`MailboxSource`); ein nicht erreichbares Postfach hält die
  anderen nicht auf. Ordnerfehler werden mit Postfachnummer protokolliert.
- Gemeinsame Auswahl über alle Postfächer nach Empfangszeitpunkt mit gemeinsamem `batch_size`/`--max-mails`;
  ein dauerhafter Run je Postfach, Bearbeitung in Konfigurationsreihenfolge; unfertige Runs werden vor
  jeder neuen Suche fortgesetzt.
- Wiederaufnahme liest über das Postfach der gespeicherten `account_id`; Zustände entfernter oder
  deaktivierter Postfächer bleiben liegen (`mailbox_unavailable`, einmal je Prozess protokolliert).
  Abgeschlossene Wiederaufnahmen schreiben Run und Checkpoint ihres eigenen Kontos fort.
- `--check-access` und Laufzusammenfassung je Postfach. Die Konfiguration bleibt bis Phase 4 auf ein
  Postfach begrenzt.

## 3.0.1 – beta: Planung 3.1, Phase 1 – Postfächer im Konfigurationsvertrag

- `imap.mailboxes` mit stabiler Nummer `id`, Anzeigename `label` und `enabled`; das bisherige Format
  bleibt gültig und gilt als Postfach 1. Beide Schreibweisen zusammen werden abgelehnt.
  Bis Phase 2 wird genau ein Postfach unterstützt.
- Zugangsdaten je Postfach als `IMAP_<id>_USERNAME`/`IMAP_<id>_PASSWORD`; Postfach 1 startet weiterhin
  mit `IMAP_USERNAME`/`IMAP_PASSWORD`. Logs und Vergleichsberichte maskieren jedes IMAP-Passwort.
- `imap` ist nicht mehr Teil des Analyse-Fingerprints. Fingerprints und Themenrichtlinien bis 3.0
  werden für Postfach 1 exakt rekonstruiert und als gleichwertig registriert; laufende Mails werden
  durch das Upgrade oder die Umstellung auf `imap.mailboxes` nicht zurückgehalten (gegen 3.0.0
  nachgerechnet, Regressionstest mit unabhängig nachgebautem 3.0-Algorithmus).
- Kommentarerhaltende YAML-Bearbeitung versteht Listeneinträge (`imap.mailboxes.0.host`), auch beim
  Ergänzen fehlender Schlüssel. Einrichtungsschritt „Postfach“ und Lernmodus arbeiten mit beiden Formaten;
  der Assistent zeigt im Altformat wieder die wirksamen Standardwerte (z. B. `Drafts`, `ssl`).
- Gemeinsame Verbindungsargumente für alle IMAP-Leser (Betrieb, Entwürfe, Berichte, Decision-Test).
- Spezifikation, `config.example.yaml` und `.env.example` ergänzt; neue Tests für Formate, Grenzen,
  Geheimnisnamen, Fingerprint-Gleichwertigkeit, YAML-Listenpfade und den Assistenten.

## 2.3.3 – beta: Abschlussdokumentation zur Planung 2.4

- Umsetzung, Bedienung und Upgrade des offenen Vorschlagsabgleichs sowie der
  Standarddauern in Spezifikation, README und Betriebsanleitung dokumentiert.
- Wiederherstellung fehlender Akten erhält die ursprüngliche Version und den
  Idempotenzschlüssel; bestätigte Altbefunde werden ausschließlich abgeglichen.
- Technische Datenschutzhinweise für Quellen, Vergleichscache und Merge-Journal ergänzt.
- Paketprüfung wählt ausdrücklich die aktuelle Version, auch wenn ältere Builds
  im Distributionsverzeichnis liegen.
- Browserprüfung wartet nach der Gerätenavigation auf die sichtbare Sitzung,
  statt den noch laufenden Dokumentwechsel als Fehler zu werten.

## 2.3.2 – beta: Umsetzung der Planung 2.4

- Termine und Aufgaben werden vor Benachrichtigung auch gegen offene Entscheidungen
  abgeglichen. Kanonische IDs, versionierte Quellen und nicht ausführbare Aliasakten
  verhindern mehrere offene Vorschläge für denselben Vorgang.
- Neue Fakten ergänzen bestehende Vorschläge; ältere Mails ändern konkrete Absprachen
  nicht zurück. Manuelle Werte bleiben geschützt, Widersprüche und mehrere mögliche
  Treffer erfordern Klärung. Ungeprüfte Zusätze lassen sich in Web und Telegram
  zuordnen oder getrennt behalten, ohne externe Anlage.
- Standarddauern für belegte Videokonferenzen (60 Minuten) und Präsenztermine
  (180 Minuten), einstellbar in Einrichtung und Einstellungen. Explizite Zeiten und
  Dauern haben Vorrang; Annahmen sind sichtbar und werden als verstrichene Minuten berechnet.
- Bereits vorhandene Termine werden unabhängig von der Telegram-Zustellung gespeichert.
  Rückmeldeaufgaben zeigen die verknüpfte Sitzung. Fehlende Altakten und Dauerannahmen
  werden unter `/abgleich` nur nach ausdrücklich übernommener Vorschau aktualisiert.
- Wiederaufnehmbares Merge-Journal, versions- und policygebundener Vergleichscache,
  separate Normalisierungspolicy und erneute Sitzungs-/Zielprüfung vor einer Anlage.
  Fehlgeschlagene externe Abgleiche sperren die Anlage und können erneut geprüft werden.
- Synthetische Regressionen für die beobachteten Doppelvorschläge, fehlende Endzeiten
  und die nicht sichtbare bereits vorhandene Beiratssitzung; zusätzliche Konflikt-,
  Wiederanlauf-, Autorisierungs- und Browserprüfungen. Spezifikation und Beispiele ergänzt.

Die beta-Patchnummer folgt `AGENTS.md`; die fachliche Zielversion des Plans bleibt 2.4.
Dieser Commit erstellt keinen Release und keinen Tag.

## 3.0.0 – beta: Einrichtung, Diagnose und Benachrichtigungen

Planung: [docs/Planung-3.0.md](docs/Planung-3.0.md), Betrieb und Upgrade: [docs/Release-3.0.md](docs/Release-3.0.md).
Abnahme auf diesem Stand unter Windows 11: 2173 Python-Tests mit 100 % Zeilen- und Branch-Abdeckung,
134 Browsertests mit 100 % JavaScript-Abdeckung, ruff und mypy ohne Befund. Der Release-Tag `v3.0.0`
wird erst nach erfolgreicher CI-Matrix (Linux, Docker, Paketinstallation) gesetzt.

- Neue Planungen: mehrere Postfächer ([docs/Planung-3.1.md](docs/Planung-3.1.md), Geheimnisse
  `IMAP_<n>_USERNAME`/`IMAP_<n>_PASSWORD`) und Einstellungen je Postfach
  ([docs/Planung-3.2.md](docs/Planung-3.2.md)). Beide gehören nicht zu 3.0.

- Einrichtung unter `/einrichtung`: wiederaufnehmbare Entwürfe, Dateihash und Entwurfsversion,
  getrennte bestätigte Übernahme über die vorhandene, erneut autorisierte Kommando-Warteschlange.
- Unabhängige Diagnosen unter `/diagnose`, sichere Fehlercodes und bereinigter JSON-Export.
  Lesende IMAP-, Kalender- und Todoist-Prüfungen; separate Aktionen für Testnachrichten und synthetische LLM-Tests.
- Lokaler Erstzugang mit `mailhelp --pair`; ohne Telegram erzeugen Webanfragen und Dienststart keine Codes mehr.
- Gemeinsame persistente Benachrichtigungswarteschlange, Kategorie- und Kanalwahl,
  lokale Ruhezeiten einschließlich Zeitumstellung, Bündelung, begrenzter Backoff und sichtbare unklare Zustellungen.
  Pro Push-Gerät gelten Sitzung und Abonnementrevision; Web-Push bleibt neutral.
- Upgrade erhält vorhandene Inhaltsfreigaben und berücksichtigt alte Zustellmarker.
  Neue Profile beginnen mit neutralen Telegram-Hinweisen. Operative Profile ändern keine Analyse-Fingerprints.
- Synthetische Autorisierungs-, Zustell-, Neustart-, Upgrade- und Datenschutztests; neue Schema-Snapshots.
  Die Versionsfreigabe erfolgt nach Abschluss der Plattformmatrix; es wurde kein Release veröffentlicht.
- In der Abnahme abgesichert: unterbrochene alte Outbox-Zustellungen bleiben unklar, eine volle
  Queue wird weiter entleert, endgültige Fehler belegen keine ausstehenden Plätze und Migrationsdaten
  enthalten keine Kopien alter Mailtexte. Die Regressionstests scheiterten vor den jeweiligen Korrekturen.
- Ungültige Unicode-Werte in Kopplungssignaturen und CSRF-Tokens werden mit HTTP 403
  abgewiesen; Regressionstests belegen beide zuvor ausgelösten Serverfehler.

## 2.3.1 – Beta (Branch `beta`), Tätigkeitsberichte in fester Reihenfolge

- **Fehler behoben:** Zwei kurz nacheinander angelegte Tätigkeitsberichte konnten unter Windows denselben
  Anlagezeitpunkt erhalten (Uhrauflösung etwa 15 ms); die Bearbeitungsreihenfolge hing dann von den
  zufälligen Dateinamen ab, und der spätere Bericht konnte vor dem früheren gezählt werden. Berichte tragen
  jetzt eine fortlaufende Nummer (`sequence`, ältere Dateien 0) als zweites Sortierkriterium, danach die
  Kennung. Der Anlagezeitpunkt kommt aus der Uhr des Dienstes.
- Regressionstest `test_reports_created_in_the_same_clock_tick_stay_fifo` friert die Uhr ein und lässt das
  Dateisystem beide Reihenfolgen liefern; er scheiterte vor der Korrektur zuverlässig. Damit ist auch der
  gelegentlich fehlschlagende `test_report_counting_is_fifo` stabil. Schema-Snapshot `ActivityReport`
  um das optionale Feld ergänzt; alte Berichtsdateien bleiben ohne Migration lesbar.

## 2.3.0 – Beta (Branch `beta`), weitere Kalender- und Aufgabendienste, Volltextsuche, Originaldokumente

Planung: [docs/Planung-2.3.md](docs/Planung-2.3.md).

- **Kalender:** zusätzlich CalDAV (Nextcloud, iCloud, mailbox.org, Radicale …) und Outlook /
  Microsoft 365 (`targets.calendar_provider`). Duplikatprüfung, Ergänzung, Zeitänderung und Absage
  laufen für alle Kalender über denselben Ablauf (`TargetWriter`, `CalendarOperations`).
- **Aufgaben:** zusätzlich Microsoft To Do, CalDAV-Aufgabenlisten (VTODO) und Apple Erinnerungen über
  iCloud-CalDAV (`targets.task_provider`). Auf die neuen iCloud-Erinnerungen aktualisierte Listen sind
  über CalDAV nicht erreichbar; die Zugriffsprüfung meldet das.
- **Idempotenz je Anbieter:** CalDAV über einen aus dem Schlüssel abgeleiteten Ressourcennamen mit
  `If-None-Match: *`; Outlook über eine erweiterte Eigenschaft und `transactionId`; To Do über
  `linkedResources.externalId`. Unklare Ergebnisse werden wie bisher nur abgeglichen.
- **Microsoft-Anmeldung:** `mailhelp --microsoft-login` (Gerätecode); rotierte Refresh-Tokens werden in
  `microsoft-token.json` neben `.env` gespeichert.
- **Geheimnisse** werden nur noch für die gewählten Anbieter verlangt; neue Variablen `CALDAV_*`, `MICROSOFT_*`.
- **Volltextsuche** unter `/mails` über Mailtext, Anhangnamen und Anhangtext mit Fundstelle, UND-Verknüpfung,
  Phrasen und Umlaut-Gleichwertigkeit; Auswahl „nur Absender, Betreff und Zusammenfassung“.
- **Originaldokumente** (PDF, Office, OpenDocument, Text, Bilder) neu verarbeiteter Mails zum Herunterladen;
  Allowlist mit Signaturprüfung, Prüfsumme, Download-only-Header, Aufbewahrung wie Mailinhalte
  (`attachments.*`).
- Web-Einstellungen und Einrichtungsschritt „Analyse und Ziele“ bieten Anbieter und Ziele an; neue Zeitlimits
  `timeouts.caldav` und `timeouts.microsoft`. Bestehende Konfigurationen behalten ihren Analyse-Fingerprint.
- Anbieterneutrale Texte: „Als Aufgabe anlegen“, „Angelegt als Aufgabe“, „Aufgabe öffnen“,
  „Terminänderung gegenüber dem Kalender“.
- Tests mit simuliertem CalDAV-Server und simuliertem Microsoft Graph; 100 % Zeilen- und Branch-Abdeckung.

## 2.2.6 – Beta (Branch `beta`), Split-View ohne Flackern

- **Split-View:** Neue Daten ersetzen Liste und Detailbereich ohne Neuladen der Seite; kein Flackern
  mehr, Auswahl und Scrollposition bleiben. Ein laufender Rückgängig-Countdown wird nicht gestört.
  Der in Telegram aktuelle Vorgang ist in der Liste nicht mehr zusätzlich umrandet, nur noch die
  Auswahl. Regressionstests in `ui_tests/test_ui_v20.py` scheiterten vor der Korrektur.
- **Versionierung:** Auch jeder Commit in `beta` erhöht die Patch-Version (AGENTS.md, Spezifikation).
- WSL-Browserabnahme: Der Fehlerpfad der Hintergrundaktualisierung wird vor einer weiteren
  Navigation vermessen, damit seine ausgeführten JavaScript-Blöcke im Coverage-Gate erhalten bleiben.

## 2.2.5 – Beta (Branch `beta`), Entscheidungen aus Planung 2.1 und Testinfrastruktur

- **Web-Push je Gerät (Planung 2.1, 5.3):** Die Idempotenzschlüssel der An- und Abmeldung werden je Gerät begrenzt (500); ein aktives Gerät verdrängt nicht mehr die Schlüssel eines anderen. Test `test_push_operations_are_bounded_per_device`.
- **Tagesüberblick nach spätem Start (Planung 2.1, 5.1):** Entschieden, kein Zeitfenster – der Überblick wird auch nach einem Start lange nach der eingestellten Uhrzeit noch am selben Tag gesendet. Festgehalten mit `test_briefing_is_still_sent_after_a_late_start`.
- **`composition.py` (A4):** Der Aufbau der Anwendung (Logger, Metriken, IMAP, LLM, Telegram, Analyzer, Dialog, Orchestrator, Weboberfläche) liegt in eigenen Fabriken in `composition.py`; `application.py` enthält nur noch die Polling-Schleife und exportiert `build_application` weiter.
- **Tests ohne Querimporte (T1/T2):** Activity-Tests nutzen die gemeinsamen Fakes; ein Architekturtest verbietet Importe aus anderen `test_*`-Modulen.
- **Browsertests (T7):**
  - `axe-core` (WCAG 2.1 A/AA) läuft bei jedem Seiten-Audit, ohne Befund auf allen Seiten; ein Test belegt, dass axe Verstöße tatsächlich meldet.
  - Seitenobjekte `Overview`, `DetailPane`, `SettingsPage` in `ui_tests/pages.py`.
  - Der Test der echten 5-Sekunden-Rückgängig-Frist lud wegen einer Weiterleitung die verkürzte Testfrist und prüfte die 5 Sekunden nicht; er lädt die Seite jetzt selbst und stellt sicher, dass nach 3 Sekunden noch nichts gesendet ist.

## 2.2.4 – Beta (Branch `beta`), statische Prüfung: mypy fehlerfrei und verbindlich

- **mypy (Planung 2.1, A1):** Von 339 Fehlern auf 0, unter Windows und Linux (`--platform linux`). Der CI-Job `static-analysis` bricht jetzt bei jedem ruff- oder mypy-Befund ab (kein `continue-on-error` mehr).
  - `JsonStore.load_model`/`peek_model` liefern mit Default nie `None` (Overloads); `logger.metrics`, Metrics-Vergleich, Orchestrator-Themenpolitik und Review-Konfiguration sind typisiert.
  - Protokolle passen zu ihren Implementierungen: `Completer` mit den tatsächlichen Schlüsselwortparametern, `Decider` für Jev-Entscheidungen, `RelevanceHandler` mit `telegram_offset`, eine gemeinsame `EventLogger`-Definition.
  - pydantic-Plugin für mypy: Konstruktoren nehmen wie zur Laufzeit Strings für Enum-, Literal- und URL-Felder an.
  - `DisabledTelegram` erfüllt den Transportvertrag vollständig (`started_chats`, `answer_callback`).
  - `TelegramDialogState.reference()` liefert Mail, Vorschlag und Version eines offenen Dialogs typisiert.
  - Abweichende Typstubs von `imaplib` (bytes-Ordnernamen, `None` als Zeichensatz) und plattformabhängige Stubs von `fcntl`/`msvcrt` sind an je einer Stelle gekapselt.
- **Klassengröße (A4):** Minutenanteil und harte Aufrufgrenze eines Tätigkeitsberichts liegen in `activity.budget.ReportCalls`; `ActivityRunner` hat damit 19 statt 21 Methoden. Keine Klasse über 20 Methoden, keine Funktion über 80 Zeilen.
- **Bugfix – Telegram-Zeitantworten:** Eine unmögliche Uhrzeit oder ein unmögliches Datum („30“, „heute 25 Uhr“, „31.02.2026“) löste im deterministischen Zeitparser einen `ValueError` aus, statt wie jede freie Antwort an die Interpretation zu gehen. Gefunden durch den Eigenschaftstest; Regressionstest `test_impossible_times_and_dates_are_no_deterministic_answer`.
- **Bugfix – Rückfrage ohne validiertes Datum:** Widersprach eine Antwort auf die Frage nach dem Terminende einem Termin ohne validierte Datumsfakten (etwa aus einer Kalendereinladung), stürzte die Antwortverarbeitung mit `None + 1 Tag` ab, statt nachzufragen. Regressionstest `test_contradictory_end_without_validated_date_gets_a_question`.

## 2.2.3 – Beta (Branch `beta`), statische Prüfung: ruff fehlerfrei

Keine Verhaltensänderung.

- **ruff (Planung 2.1, A1):** Von 236 Befunden auf 0. Zu lange Zeilen von Hand im Stil des Codes umbrochen (Texte als implizit verkettete Literale, sodass Seiten und Meldungen byte-gleich bleiben; der Renderer-Vertragstest bestätigt das). Closures binden ihre Schleifenwerte ausdrücklich; Tests erwarten konkrete Ausnahmen (`ValidationError`, `RetryableError`, `PermanentError`, `UncertainWriteError`) statt `Exception`.
- **Konfiguration:** UP038 ist in ruff selbst veraltet und wird ignoriert; die Kompatibilitätsfassaden `models.py` und `domain/__init__.py` dürfen wie `telegram/_core.py` per Stern importieren.
- Protokollmethoden mit mehrzeiliger Signatur tragen einen Docstring statt `...`.

## 2.2.2 – Beta (Branch `beta`), Anforderungsprüfung 2.2

Behebt die Befunde aus [Pruefung-2.2.md](docs/Pruefung-2.2.md); jede Korrektur hat einen Regressionstest.

- **Korrekturen während der Analyse:** Eine laufende Terminsuche überschrieb danach gespeicherte Nutzerentscheidungen und von Hand ergänzte Termine. Ergebnisse werden jetzt mit dem aktuellen Stand zusammengeführt (`test_live_corrections_survive_the_in_flight_event_analysis`).
- **Harte KI-Grenze:** `max_llm_calls` wurde nur vor jeder Mail geprüft; Relevanz plus Terminsuche, Reparaturversuche und nachgeforderte Terminsuchen konnten sie überschreiten. Die Grenze gilt jetzt vor jedem Provideraufruf (`test_call_limit_stops_between_steps_and_resume_does_not_repeat_relevance`, `test_model_repair_also_consumes_the_hard_call_budget`, `test_requested_extraction_cannot_bypass_the_call_limit`).
- **Zählfehler und UIDVALIDITY:** Ein nicht erreichbares Postfach ließ einen Bericht endlos zählen; jetzt „fehlgeschlagen“ nach drei Versuchen. Eine geänderte UIDVALIDITY ließ den Bericht scheitern; jetzt wird der Ordner neu aufgelistet und Ergebnisse werden über die Message-ID wiederverwendet.
- **Gesendet-Ordner:** Ein ausdrücklich gewählter Gesendet-Ordner prüfte den Absender statt der Empfänger gegen die Ignorierliste.
- **Datumsprüfung:** Ein Modelldatum, das dem Belegzitat widerspricht (Zitat „20. Januar“, Datum 21.01.), wurde übernommen; jetzt verworfen (`test_model_date_must_agree_with_its_quote`).
- **Reihenfolge und Sitzung:** Wartende Berichte in Anlagereihenfolge; vor jedem KI-Aufruf wird die auslösende Sitzung erneut geprüft; Löschen verlangt einen Idempotenzschlüssel; die Ignorierliste wird beim kostenpflichtigen Start gesichert; nur Ordner aus der Serverliste.
- **Neu (Planung 2.2):** Filter, hervorgehobene Belege, Kostenschätzung aus Messwerten, „Mit anderem Thema neu bewerten“, Fortschritt über `/api/stand?bericht=<id>` (ungültige IDs: 404, Regressionstest `test_progress_signal_rejects_malformed_report_ids`).
- **Schema-Verträge:** `ActivityReport` und `ReportMail` sind Teil der Persistenzgrenze und der Schema-Snapshots.
- **Browsertests:** Die JavaScript-Abdeckung las CRLF-Dateien mit verschobenen Offsets und meldete fälschlich Lücken; Messung jetzt auf den ausgelieferten Bytes, auch vor Reload, Zurück und dem Schließen eigener Kontexte.
- **Paket:** Doku 2.1 und 2.2 im sdist.

## 2.2.1 – Beta (Branch `beta`)

- **Bugfix – Ordnervorschlag im Tätigkeitsbericht:** Konfigurierte Ordner, die der Server nicht kennt (z. B. `Trash` und `Sent`, wenn das Postfach `Papierkorb` und `Gesendet` nutzt), wurden vorgeschlagen, weil ihre Rolle unbekannt war, und beim Zählen als „nicht lesbar“ gemeldet. Vorgeschlagen werden jetzt nur vom Server gelistete Ordner; Regressionstest `test_suggested_folders_exist_on_the_server`. Gefunden beim ersten echten Bericht.
- **Bugfix – KI-Fehler im Tätigkeitsbericht:** Eine unbrauchbare KI-Antwort (z. B. Tokenlimit bei der Terminsuche) brach den Hintergrundschritt ab; die Schleife hätte dieselbe kostenpflichtige Anfrage alle fünf Sekunden wiederholt. Unbrauchbare Antworten werden jetzt an der Mail vermerkt (`failed_step`) und nicht wiederholt, die Seite bittet um eigene Entscheidung bzw. Termine von Hand; ein dreimal nicht erreichbarer KI-Dienst pausiert den Bericht, eine fehlschlagende Terminsuche auf Anfrage wird verworfen. Regressionstests `test_unusable_model_answers_are_recorded_once_and_never_retried`, `test_an_unreachable_model_pauses_the_report_after_repeated_failures`, `test_a_failing_requested_extraction_is_dropped_not_repeated`.
- **Prompts:** `max_tokens` für `activity_relevance` (2000) und `activity_events` (8000) angehoben; 2000 reichten dem konfigurierten Modell bei langen Mails nicht. Beim Upgrade die beiden Werte in der eigenen `prompts.yaml` übernehmen.

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
