# Prüfung der Dokumentation 5.3

**Grundlage:** [Planung 5.3](Planung-5.3.md), Abschnitt 9
**Prüfstand:** Mailhelp 5.3.0 (nach Abschluss von 5.0 bis 5.2, Commit-Folge ab `51d7c62`)
**Status:** H1 Bestandsaufnahme, H2 Einstellungsreferenz vollständig (5.3.1), H5/H6 Anleitungen
(5.3.4, 5.3.5). Offen für die Releaseabnahme: Docker-Wege.

Dieser Bericht ist der Nachweis der Dokumentationsprüfung von 5.3. Der erzeugte Teil unten
listet jede Einstellung und jede Kommandozeilenoption so, wie der Code sie tatsächlich kennt;
er wird mit `python -m devtools.inventory` neu erzeugt, und ein Test schlägt fehl, wenn er
veraltet ist. Ältere Prüfberichte ([Pruefung-Dokumentation](Pruefung-Dokumentation.md), 3.3.1)
sind kein Nachweis für 5.3.

## 1. Abgleich des Ausgangsstands

| Baustein | Stand 5.3.0 |
| --- | --- |
| Versionen 5.0, 5.1, 5.2 | abgeschlossen mit Release-Berichten [5.0](Release-5.0.md), [5.1](Release-5.1.md), [5.2](Release-5.2.md) |
| Einstellungsreferenz | [Web-Einstellungen](Web-Einstellungen.md) nennt im Kopf 4.8.6; Inhalte werden in H2 geprüft |
| Feldhilfen | `web/setting_help.py`, gekoppelt an `SETTINGS_FIELDS` (Test `test_setting_help`) |
| Suche | Formularsuche `GET /einstellungen?suche=`; Live-Suche fehlt |
| Hilfschat | fehlt |
| Bekannte Regressionen | keine offenen; zeitkritische Browsertests unter Last sind im Release-Bericht 5.2 benannt |

## 2. Festgelegte Verträge (H1)

**Suchkatalog** (`web/settings_search.py`, ab H3): Ein Eintrag hat `id` (stabil, z. B.
`setting:poll_interval_seconds` oder `page:mailbox-add`), optional `key`, `label`, `area`,
`group`, `summary`, `help`, `synonyms`, `href` mit Feldanker, `doc_id`, `path`
(`Weboberfläche`, `Einrichtung`, `Datei`) und eine Sichtbarkeitsbedingung. Allgemeine
Feldtexte kommen ausschließlich aus `SETTING_HELP`; Sonderseiten haben eigene Einträge.
Normalisierung: Leerraum, Großschreibung, `ä/ae`, `ö/oe`, `ü/ue`, `ß/ss`. Rang: exakter
Schlüssel oder Bezeichnung, dann Wortanfang, dann Teiltreffer, dann Hilfetext; bei Gleichstand
alphabetisch. Formular- und Live-Suche nutzen dieselbe Funktion.

**Such-API** (ab H4): `GET /api/einstellungen/suche?suche=…` nur mit gültiger Sitzung,
`Cache-Control: no-store`, Antwort
`{"query": str, "total": int, "results": [{"id", "label", "area", "summary", "key", "href", "path"}]}`
mit höchstens zehn Treffern; keine Formularwerte, Token oder Zugangsdaten.

**Hilfebestand** (ab H7): Paketressource `mailhelp/help/` mit `manifest.json`
(`app_version`, `revision` = SHA-256 über die Abschnitte, Quellenliste) und `sections.json`
(`id`, `title`, `path`, `text`, `terms`, `setting_ids`). Erzeugt reproduzierbar aus einer
ausdrücklichen Freigabeliste; ein Buildtest vergleicht mit den Quelldokumenten. Lokaler Leser
`/hilfe/dokumentation/<id>`.

**Modell und Antwort** (ab H8): optionaler Prompt-Schritt `settings_help` in `prompts.yaml`
mit validierter Routenreferenz `model_route: action_router`; Antwortschema
`{"answer": str ≤ 4000, "source_ids": ≤ 6, "setting_ids": ≤ 10, "needs_clarification": bool}`.
Quellen nur aus dem übergebenen Kontext, Einstellungen nur aus dem Katalog.

**Chatzustand** (ab H9): `help-chat-<Sitzungs-Hash>.json` mit `schema_version`, `version`,
höchstens zehn Frage-Antwort-Paaren und Aufträgen (`queued`, `running`, `completed`, `failed`,
`interrupted`, `cancelled`) mit Idempotenzschlüssel-Hash und Dokumentationsrevision; keine
Cookies oder Token; Löschung spätestens 24 Stunden nach der letzten Aktivität.

**Worker:** ein gemeinsamer Pool mit **zwei** Threads und einer Warteschlange von **acht**
Aufträgen für alle Sitzungen; je Chat höchstens ein laufender Auftrag. Eine volle Warteschlange
wird mit einer verständlichen Meldung abgewiesen, ohne Modellaufruf.

**Abnahmefälle:** Planung 5.3, Abschnitte 13 und 14, ohne Abweichung.

## 3. Befunde und Korrekturen der Einstellungsreferenz (H2)

| Befund | Art | Korrektur und Nachweis |
| --- | --- | --- |
| 117 von 229 Einstellungen ohne eigenen Eintrag (Postfächer, IServ, Zielprofile, Benachrichtigungen, Grenzen, Protokolle, Pfade, Webserver, KI-Anbindung, Nachanalyse, Nachprüfung) | fehlt | Abschnitt „Vollständige Referenz weiterer Einstellungen (5.3)“ in [Web-Einstellungen](Web-Einstellungen.md); Test `test_every_setting_has_its_own_entry_in_the_reference` |
| Aufbewahrungshilfen: „Offene Vorgänge bleiben **geschätzt**“ statt „geschützt“ (fünf Einträge und Feldhilfe) | falsch | korrigiert; Regressionstest `test_open_cases_are_named_protected_not_estimated_in_every_retention_help` |
| `limits.max_attachment_bytes` ohne Wertebereich | unvollständig | 1024–100000000 Bytes ergänzt; Test `test_every_numeric_limit_in_the_code_is_named_in_the_reference` |
| `retention.full_mail_days`, `retention.history_days`, `limits.max_llm_payload_bytes` ohne Standard; `attachments.max_original_bytes` nur als „25 MB“ | unvollständig | Standards 30, 90, 500000 und 26214400 Bytes (25 MiB) ergänzt; Test `test_every_numeric_default_in_the_code_is_named_in_the_reference` |
| Tabellenkopf „Postfach-Briefings (4.9)“ mit beschädigten Umlauten | Darstellung | repariert |
| Kopf der Referenz nannte 4.8.6 | veraltet | Stand 5.3.1 mit Verweis auf diesen Bericht |
| Bedienweg der Postfach-, IServ- und Zielprofilfelder als „Datei“ eingestuft | Inventur | Inventur unterscheidet Postfach-, IServ- und Zielprofilseite |

Codefehler wurden in H2 nicht gefunden. Grenzen und Standards aller Zahlenfelder werden jetzt
automatisch mit dem Code abgeglichen; die Verständlichkeitsprüfung folgt in H6.

### Laufzeit der Live-Suche (H4)

Gemessen mit `ui_tests/test_ui_settings_live_search_53.py` (Chromium, Desktop-Ansicht, Windows 11,
Python 3.12.10, vollständiger Katalog, lokaler Testserver): 100 Suchläufe mit kurzen und
mehrteiligen Begriffen, gemessen ab der Eingabe bis zur sichtbaren Trefferliste einschließlich der
150-ms-Verzögerung. **100 von 100** innerhalb von 300 ms; Median 217,8 ms, 95. Perzentil 240,9 ms.
Abnahmewert (mindestens 95 %) erfüllt.

### Nachvollzug der Anleitungen (H5)

| Anleitung | Schritt | System | Nachweis | Beobachtet |
| --- | --- | --- | --- | --- |
| [Ersteinrichtung](Ersteinrichtung.md) | leeres Verzeichnis bis „Einrichtung abgeschlossen“ (Koppeln, fünf Schritte, Prüfungen, Speichern und starten) | Windows 11, Chromium, synthetische Dienste | `ui_tests/test_ui_initial_setup.py` (auch ohne JavaScript und mobil) | Überschriften, Felder und Schaltflächen wie beschrieben |
| Ersteinrichtung | Docker-Weg (`compose.setup.yaml`) | Linux/Docker | **nicht nachvollzogen** – Docker auf dem Prüfrechner nicht verfügbar | offen |
| [Konten verwalten](Konten-verwalten.md) | zweites Postfach in bestehender Installation hinzufügen und aktivieren | Windows 11, Chromium | `ui_tests/test_ui_settings35.py` | Prüfung, Speichern und Ergänzen wie beschrieben |
| Konten verwalten | IServ-Konto anlegen und aktivieren | Windows 11 | `tests/web/test_iserv_web.py`, `tests/web/test_iserv_activation.py` | wie beschrieben |
| Konten verwalten | Zielprofil anlegen, zuordnen, entfernen | Windows 11 | `tests/profiles/test_web.py`, `test_profile_completion.py`, `test_profile_review.py` | wie beschrieben |
| beide | jede fett genannte Bedienbezeichnung existiert, jeder Link und Anker löst auf | – | `tests/release/test_guides.py` | bestanden |

### Weitere Anleitungen und Verständlichkeit (H6)

Neu: [Ziele einrichten](Ziele-einrichten.md), [Bedienung](Bedienung.md),
[Fehlerbehebung](Fehlerbehebung.md), [Betrieb](Betrieb.md). Jede Anleitung nennt Ziel,
Voraussetzungen, Schritte mit tatsächlichen Bezeichnungen, erwartetes Ergebnis und Fehlerhilfe;
`tests/release/test_guides.py` prüft alle sechs Anleitungen auf existierende Bedienbezeichnungen,
Links und Anker. Beim Schreiben gefundene und korrigierte Fehler: Die Ersteinrichtung nannte eine
Schaltfläche „Bestätigen“, die es in der Weboberfläche nicht gibt (richtig: „Als Aufgabe anlegen“
bzw. „Im Kalender anlegen“); „Lesende Selbsttest“ statt „Lesender Selbsttest“.

Verständlichkeit: Die 117 neuen Referenzzeilen folgen dem Standard aus Planung 9.3 (Wirkung,
Werte mit Einheit und Grenzen, Standard, Bedienweg und Übernahme); für alle Zahlenfelder sind
Grenzen und Standard automatisch abgeglichen. Die übrigen 112 Feldhilfen aus 3.x/4.x wurden auf
diese Pflichtangaben geprüft und dort korrigiert, wo sie fehlten (siehe H2); eine sprachliche
Neufassung jeder einzelnen Feldhilfe wurde nicht vorgenommen. Beispiele: `config.example.yaml`
wird durch die vorhandenen Tests der ausgelieferten Konfiguration validiert; die Anleitungen
enthalten nur synthetische Werte und Platzhalter.

| Anleitung | Nachweis | System |
| --- | --- | --- |
| Ziele einrichten | `tests/external/*` (alle sieben Anbieter mit echtem Transport), `tests/profiles/*` | Windows 11 |
| Bedienung | `ui_tests/test_ui_review.py`, `test_ui_split_view_50.py`, `test_ui_verification_52.py`, `test_ui_reanalysis.py` | Windows 11, Chromium |
| Fehlerbehebung | Fehlerpfade in `tests/services/*`, `tests/external/test_verification_matrix.py` | Windows 11 |
| Betrieb | `tests/release/test_initial_cli.py`, `tests/services/test_write_verification_upgrade.py` | Windows 11; Linux/Docker offen |

## 4. Funktionen der Weboberfläche

Jede Seite der Weboberfläche mit ihrer Aufgabe und dem Ort ihrer Dokumentation; ein Test
vergleicht die Liste mit den registrierten Seiten.
Technische Endpunkte (`/api/…`, `/static/…`, `/health`, Manifest, Service-Worker) sind
Teil der genannten Seiten und haben keine eigene Bedienung.

| Seite | Funktion | Dokumentation |
| --- | --- | --- |
| `/` | Offen: zu entscheidende Vorschläge und Fragen | README, [Bedienung](Bedienung.md) |
| `/offen` | Offene Vorschläge (Kurzform) | [Bedienung](Bedienung.md) |
| `/vorschlag/…` | Vorschlag mit Beleg, Prüfstand, Bearbeiten, Versionen | README 5.1/5.2, [Bedienung](Bedienung.md) |
| `/serie/…` | Termine einer Serie gemeinsam bestätigen | [Bedienung](Bedienung.md) |
| `/aktion/…` | Fortschritt einer Aktion | [Bedienung](Bedienung.md) |
| `/mails` | Mailarchiv | [Bedienung](Bedienung.md) |
| `/mail/…` | Mail mit Verarbeitungsweg, Anhängen und Originalen | README 5.1, [Bedienung](Bedienung.md) |
| `/abgleich` | Vorschlagsabgleich | README 5.0, [Bedienung](Bedienung.md) |
| `/verlauf` | Verlauf und Revisionen | [Bedienung](Bedienung.md) |
| `/berichte` | Tätigkeitsberichte, Export | Web-Einstellungen (activity_report) |
| `/berichte/neu` | Neuen Tätigkeitsbericht starten | Web-Einstellungen (activity_report) |
| `/auswertung` | Auswertung und Kennzahlen | [Bedienung](Bedienung.md) |
| `/briefing` | Tagesüberblick | [Bedienung](Bedienung.md) |
| `/themen` | Themenpflege | Web-Einstellungen |
| `/status` | Status, Dienste, Neuladen | Web-Einstellungen, [Betrieb](Betrieb.md) |
| `/diagnose` | Diagnose und Diagnosebericht | [Fehlerbehebung](Fehlerbehebung.md) |
| `/diagnose/bericht` | Diagnosebericht herunterladen | [Fehlerbehebung](Fehlerbehebung.md) |
| `/benachrichtigungen` | Benachrichtigungen dieses Geräts | Web-Einstellungen (notifications) |
| `/geraete` | Gekoppelte Geräte | Web-Einstellungen (web) |
| `/einrichtung` | Ersteinrichtung | [Ersteinrichtung](Ersteinrichtung.md) |
| `/anmelden` | Anmeldung, Geräte koppeln | [Ersteinrichtung](Ersteinrichtung.md) |
| `/einstellungen` | Einstellungsbereiche und Suche | Web-Einstellungen |
| `/einstellungen/postfaecher` | Postfächer anlegen, prüfen, ändern | [Konten verwalten](Konten-verwalten.md) |
| `/einstellungen/iserv` | IServ-Konten | [Konten verwalten](Konten-verwalten.md) |
| `/einstellungen/zielprofile` | Zielprofile | [Ziele einrichten](Ziele-einrichten.md) |
| `/einstellungen/zugangsdaten` | Zugangsdaten und OAuth | [Ziele einrichten](Ziele-einrichten.md) |
| `/einstellungen/benachrichtigungen` | Benachrichtigungsregeln | Web-Einstellungen (notifications) |
| `/einstellungen/ignorierte-absender` | Ignorierte Absender | Web-Einstellungen |
| `/einstellungen/web-passwort` | Web-Passwort | Web-Einstellungen |
| `/einstellungen/neustarten` | Neustart | [Betrieb](Betrieb.md) |
| `/einstellungen/beenden` | Beenden | [Betrieb](Betrieb.md) |

## 5. Inventur der Einstellungen und Optionen

<!-- inventar:start -->

Erzeugt mit `python -m devtools.inventory`: **230 Einstellungen**, davon **230** mit eigenem Eintrag in [Web-Einstellungen](Web-Einstellungen.md).

| Schlüssel | Typ | Standard | Grenzen | Bedienweg | Referenz |
| --- | --- | --- | --- | --- | --- |
| `activity_report.enabled` | bool | False |  | Weboberfläche | ja |
| `activity_report.export_mails_without_events` | bool | True |  | Weboberfläche | ja |
| `activity_report.max_fulltext_chars` | int | 30000 | ≥ 1000, ≤ 32000 | Weboberfläche | ja |
| `activity_report.max_llm_calls` | int | 3000 | ≥ 1, ≤ 50000 | Weboberfläche | ja |
| `activity_report.max_mails` | int | 2000 | ≥ 1, ≤ 20000 | Weboberfläche | ja |
| `activity_report.max_share_of_llm_budget` | float | 0.5 | > 0, ≤ 1 | Weboberfläche | ja |
| `attachments.max_original_bytes` | int | 26214400 | ≥ 1024, ≤ 104857600 | Weboberfläche | ja |
| `attachments.max_total_bytes` | int | 52428800 | ≥ 1024, ≤ 524288000 | Weboberfläche | ja |
| `attachments.store_originals` | bool | True |  | Weboberfläche | ja |
| `auto_draft` | bool | False |  | Weboberfläche | ja |
| `briefings.enabled` | bool | False |  | Weboberfläche | ja |
| `briefings.mailbox` | int oder Auswahl: default | 'default' |  | Weboberfläche | ja |
| `briefings.skip_empty` | bool | True |  | Weboberfläche | ja |
| `briefings.times` | list[str] | ['07:00', '13:00', '18:00'] | Länge ≤ 1440 | Weboberfläche | ja |
| `daily_briefing.enabled` | bool | False |  | Einrichtung | ja |
| `daily_briefing.include_calendar` | bool | True |  | Weboberfläche | ja |
| `daily_briefing.include_open` | bool | True |  | Weboberfläche | ja |
| `daily_briefing.include_tasks` | bool | True |  | Weboberfläche | ja |
| `daily_briefing.time` | str | '07:30' |  | Einrichtung | ja |
| `data_directory` | Path | Pflicht |  | Datei | ja |
| `drafts.enabled` | bool | True |  | Weboberfläche | ja |
| `drafts.folder` | str (optional) | – |  | Weboberfläche | ja |
| `event_defaults.in_person_duration_minutes` | int | 180 | ≥ 1, ≤ 1440 | Weboberfläche | ja |
| `event_defaults.video_duration_minutes` | int | 60 | ≥ 1, ≤ 1440 | Weboberfläche | ja |
| `imap.batch_size` | int | 25 | ≥ 1, ≤ 1000 | Weboberfläche | ja |
| `imap.connection_mode` | Auswahl: ssl, starttls, plain (optional) | – |  | Einrichtung | ja |
| `imap.drafts_folder` | str (optional) | – |  | Einrichtung | ja |
| `imap.folders` | list[str] (optional) | – | Länge ≥ 1, Länge ≤ 100 | Einrichtung | ja |
| `imap.global_newest_first` | bool | False |  | Weboberfläche | ja |
| `imap.historical_start` | datetime (optional) | – |  | Einrichtung | ja |
| `imap.host` | str (optional) | – | Länge ≥ 1, Länge ≤ 253 | Einrichtung | ja |
| `imap.mailboxes[].activity_report_folder` | str (optional) | – |  | Postfachseite | ja |
| `imap.mailboxes[].auto_draft` | bool (optional) | – |  | Postfachseite | ja |
| `imap.mailboxes[].connection_mode` | Auswahl: ssl, starttls, plain | 'ssl' |  | Postfachseite | ja |
| `imap.mailboxes[].daily_briefing` | bool | True |  | Postfachseite | ja |
| `imap.mailboxes[].drafts_folder` | str | 'Drafts' | Länge ≥ 1, Länge ≤ 500 | Postfachseite | ja |
| `imap.mailboxes[].enabled` | bool | True |  | Datei | ja |
| `imap.mailboxes[].event_defaults.in_person_duration_minutes` | int (optional) | – | ≥ 1, ≤ 1440 | Postfachseite | ja |
| `imap.mailboxes[].event_defaults.video_duration_minutes` | int (optional) | – | ≥ 1, ≤ 1440 | Postfachseite | ja |
| `imap.mailboxes[].folders` | list[str] | Pflicht | Länge ≥ 1, Länge ≤ 100 | Postfachseite | ja |
| `imap.mailboxes[].historical_start` | datetime (optional) | – |  | Postfachseite | ja |
| `imap.mailboxes[].host` | str | Pflicht | Länge ≥ 1, Länge ≤ 253 | Postfachseite | ja |
| `imap.mailboxes[].id` | int | Pflicht | ≥ 1, ≤ 99 | Postfachseite | ja |
| `imap.mailboxes[].label` | str | 'Postfach' | Länge ≥ 1, Länge ≤ 40 | Postfachseite | ja |
| `imap.mailboxes[].mail_client` | Auswahl: auto, apple_mail, gmail_web, outlook_web, none | 'auto' |  | Postfachseite | ja |
| `imap.mailboxes[].notifications.categories.action_results` | list[Auswahl: telegram, web_push] (optional) | – | Länge ≤ 2 | Postfachseite | ja |
| `imap.mailboxes[].notifications.categories.daily_briefing` | list[Auswahl: telegram, web_push] (optional) | – | Länge ≤ 2 | Postfachseite | ja |
| `imap.mailboxes[].notifications.categories.decisions` | list[Auswahl: telegram, web_push] (optional) | – | Länge ≤ 2 | Postfachseite | ja |
| `imap.mailboxes[].notifications.categories.system_errors` | list[Auswahl: telegram, web_push] (optional) | – | Länge ≤ 2 | Postfachseite | ja |
| `imap.mailboxes[].notifications.quiet_hours.allow_system_errors` | bool (optional) | – |  | Postfachseite | ja |
| `imap.mailboxes[].notifications.quiet_hours.enabled` | bool (optional) | – |  | Postfachseite | ja |
| `imap.mailboxes[].notifications.quiet_hours.end` | str (optional) | – |  | Postfachseite | ja |
| `imap.mailboxes[].notifications.quiet_hours.start` | str (optional) | – |  | Postfachseite | ja |
| `imap.mailboxes[].own_addresses` | list[str] | [] | Länge ≤ 20 | Datei | ja |
| `imap.mailboxes[].personal_info` | str (optional) | – | Länge ≤ 2000 | Postfachseite | ja |
| `imap.mailboxes[].port` | int | Pflicht | ≥ 1, ≤ 65535 | Postfachseite | ja |
| `imap.mailboxes[].primary_folder` | str | 'INBOX' |  | Postfachseite | ja |
| `imap.mailboxes[].retention.full_mail_days` | int oder Auswahl: disabled, unlimited | Pflicht |  | Postfachseite | ja |
| `imap.mailboxes[].smart_reply` | bool (optional) | – |  | Postfachseite | ja |
| `imap.mailboxes[].target_profile` | int | 1 | ≥ 1, ≤ 99 | Postfachseite | ja |
| `imap.port` | int (optional) | – | ≥ 1, ≤ 65535 | Einrichtung | ja |
| `imap.primary_folder` | str (optional) | – |  | Einrichtung | ja |
| `iserv.accounts[].enabled` | bool | True |  | IServ-Seite | ja |
| `iserv.accounts[].historical_start` | datetime (optional) | – |  | IServ-Seite | ja |
| `iserv.accounts[].id` | int | Pflicht | ≥ 1, ≤ 10 | IServ-Seite | ja |
| `iserv.accounts[].label` | str | 'Elternbriefe' | Länge ≥ 1, Länge ≤ 40 | IServ-Seite | ja |
| `iserv.accounts[].mailbox` | int | 1 | ≥ 1, ≤ 99 | IServ-Seite | ja |
| `iserv.accounts[].server` | str | Pflicht | Länge ≥ 1, Länge ≤ 253 | IServ-Seite | ja |
| `learning.decision_llm_content` | bool | False |  | Weboberfläche | ja |
| `learning.parallel_llm_calls` | int | 4 | ≥ 1, ≤ 100 | Weboberfläche | ja |
| `limits.llm_calls_per_minute` | int | Pflicht | ≥ 1, ≤ 600 | Weboberfläche | ja |
| `limits.max_attachment_bytes` | int | 5000000 | ≥ 1024, ≤ 100000000 | Weboberfläche | ja |
| `limits.max_decoded_text_bytes` | int | 1000000 | ≥ 1, ≤ 100000000 | Datei | ja |
| `limits.max_display_header_characters` | int | 500 | ≥ 1, ≤ 10000 | Datei | ja |
| `limits.max_header_bytes` | int | 64000 | ≥ 256, ≤ 1000000 | Datei | ja |
| `limits.max_html_characters` | int | 1000000 | ≥ 1, ≤ 100000000 | Datei | ja |
| `limits.max_html_depth` | int | 100 | ≥ 1, ≤ 10000 | Datei | ja |
| `limits.max_html_tags` | int | 20000 | ≥ 1, ≤ 1000000 | Datei | ja |
| `limits.max_llm_payload_bytes` | int | 500000 | ≥ 1, ≤ 100000000 | Weboberfläche | ja |
| `limits.max_mail_bytes` | int | Pflicht | ≥ 1024, ≤ 100000000 | Weboberfläche | ja |
| `limits.max_mime_parts` | int | 100 | ≥ 1, ≤ 10000 | Datei | ja |
| `llm.ollama_address` | str | 'localhost:11434' |  | Datei | ja |
| `llm.provider` | Auswahl: openrouter, ollama | 'openrouter' |  | Datei | ja |
| `logging.console.enabled` | bool | True |  | Weboberfläche | ja |
| `logging.console.format` | Auswahl: text, jsonl | 'text' |  | Datei | ja |
| `logging.console.level` | str | 'INFO' |  | Weboberfläche | ja |
| `logging.directory` | Path | Pflicht |  | Datei | ja |
| `logging.file.backup_count` | int | Pflicht | ≥ 0 | Datei | ja |
| `logging.file.enabled` | bool | True |  | Weboberfläche | ja |
| `logging.file.filename` | Path | Pflicht |  | Datei | ja |
| `logging.file.format` | Auswahl: text, jsonl | 'jsonl' |  | Datei | ja |
| `logging.file.level` | str | 'INFO' |  | Weboberfläche | ja |
| `logging.file.max_bytes` | int | Pflicht | > 0 | Datei | ja |
| `logging.file.retention_days` | int | Pflicht | > 0, ≤ 3650 | Datei | ja |
| `logging.llm.backup_count` | int | Pflicht | ≥ 0 | Datei | ja |
| `logging.llm.enabled` | bool | True |  | Weboberfläche | ja |
| `logging.llm.filename` | Path | Pflicht |  | Datei | ja |
| `logging.llm.format` | Auswahl: text, jsonl | 'jsonl' |  | Datei | ja |
| `logging.llm.include_requests` | bool | False |  | Weboberfläche | ja |
| `logging.llm.include_responses` | bool | False |  | Weboberfläche | ja |
| `logging.llm.level` | str | 'INFO' |  | Weboberfläche | ja |
| `logging.llm.max_bytes` | int | Pflicht | > 0 | Datei | ja |
| `logging.llm.retention_days` | int | Pflicht | > 0, ≤ 3650 | Datei | ja |
| `logging.modules` | dict[str, str] | {} |  | Datei | ja |
| `logging.telegram.backup_count` | int | 5 | ≥ 0 | Datei | ja |
| `logging.telegram.enabled` | bool | True |  | Weboberfläche | ja |
| `logging.telegram.filename` | Path | WindowsPath('telegram/messages.jsonl') |  | Datei | ja |
| `logging.telegram.format` | Auswahl: text, jsonl | 'jsonl' |  | Datei | ja |
| `logging.telegram.level` | str | 'INFO' |  | Weboberfläche | ja |
| `logging.telegram.max_bytes` | int | 10000000 | > 0 | Datei | ja |
| `logging.telegram.retention_days` | int | 30 | > 0, ≤ 3650 | Datei | ja |
| `metrics.electricity_eur_per_kwh` | float | 0.3 | ≥ 0, ≤ 100 | Weboberfläche | ja |
| `metrics.enabled` | bool | True |  | Weboberfläche | ja |
| `metrics.exchange_rate_date` | date (optional) | – |  | Weboberfläche | ja |
| `metrics.ollama_power_watts` | float | 300 | ≥ 0, ≤ 100000 | Weboberfläche | ja |
| `metrics.retention_days` | int | 90 | ≥ 1, ≤ 3650 | Weboberfläche | ja |
| `metrics.usd_per_eur` | float (optional) | 1.1 | > 0 | Weboberfläche | ja |
| `notifications.batching.enabled` | bool | False |  | Einrichtung | ja |
| `notifications.batching.window_seconds` | int | 300 | ≥ 1, ≤ 86400 | Einrichtung | ja |
| `notifications.categories.action_results` | list[Auswahl: telegram, web_push] | [] | Länge ≤ 2 | Einrichtung | ja |
| `notifications.categories.daily_briefing` | list[Auswahl: telegram, web_push] | [] | Länge ≤ 2 | Einrichtung | ja |
| `notifications.categories.decisions` | list[Auswahl: telegram, web_push] | [] | Länge ≤ 2 | Einrichtung | ja |
| `notifications.categories.system_errors` | list[Auswahl: telegram, web_push] | [] | Länge ≤ 2 | Einrichtung | ja |
| `notifications.delivery.history_days` | int | 30 | ≥ 1, ≤ 3650 | Einrichtung | ja |
| `notifications.delivery.initial_backoff_seconds` | int | 30 | ≥ 1, ≤ 86400 | Einrichtung | ja |
| `notifications.delivery.max_attempts` | int | 3 | ≥ 1, ≤ 10 | Einrichtung | ja |
| `notifications.delivery.max_backoff_seconds` | int | 900 | ≥ 1, ≤ 86400 | Einrichtung | ja |
| `notifications.delivery.max_pending` | int | 1000 | ≥ 1, ≤ 100000 | Einrichtung | ja |
| `notifications.quiet_hours.allow_system_errors` | bool | False |  | Einrichtung | ja |
| `notifications.quiet_hours.enabled` | bool | False |  | Einrichtung | ja |
| `notifications.quiet_hours.end` | str | '07:30' |  | Einrichtung | ja |
| `notifications.quiet_hours.start` | str | '22:00' |  | Einrichtung | ja |
| `notifications.telegram_content` | Auswahl: neutral, summary | 'neutral' |  | Einrichtung | ja |
| `personal_info` | str | '' | Länge ≤ 2000 | Weboberfläche | ja |
| `poll_interval_seconds` | int | Pflicht | ≥ 5, ≤ 86400 | Weboberfläche | ja |
| `proposal_reconciliation.max_semantic_candidates` | int | 8 | ≥ 1, ≤ 50 | Weboberfläche | ja |
| `push.enabled` | bool | False |  | Einrichtung | ja |
| `push.subject` | str | 'mailto:admin@example.invalid' |  | Datei | ja |
| `reanalysis.enabled` | bool | True |  | Datei | ja |
| `reanalysis.max_attempts` | int | 2 | ≥ 1, ≤ 5 | Datei | ja |
| `reanalysis.max_jobs_per_day` | int | 20 | ≥ 1, ≤ 500 | Datei | ja |
| `reanalysis.max_llm_calls_per_job` | int | 5 | ≥ 1, ≤ 10 | Datei | ja |
| `retention.activity_report_days` | int oder Auswahl: disabled, unlimited | 365 |  | Weboberfläche | ja |
| `retention.analysis_days` | int oder Auswahl: disabled, unlimited (optional) | – |  | Weboberfläche | ja |
| `retention.cleanup_interval_minutes` | int | 60 | ≥ 0, ≤ 1440 | Weboberfläche | ja |
| `retention.debug_llm_days` | int oder Auswahl: disabled, unlimited | 'disabled' |  | Weboberfläche | ja |
| `retention.decision_learning_days` | int oder Auswahl: disabled, unlimited | 'unlimited' |  | Weboberfläche | ja |
| `retention.full_mail_days` | int oder Auswahl: disabled, unlimited | 30 |  | Weboberfläche | ja |
| `retention.history_days` | int oder Auswahl: disabled, unlimited | 90 |  | Weboberfläche | ja |
| `retries.interpretation_attempts` | int | 3 | ≥ 1, ≤ 20 | Weboberfläche | ja |
| `retries.interpretation_backoff_seconds` | int | 60 | ≥ 1, ≤ 86400 | Weboberfläche | ja |
| `retries.json_repair` | int | Pflicht | ≥ 0, ≤ 10 | Datei | ja |
| `retries.provider_retry` | int | Pflicht | ≥ 0, ≤ 10 | Datei | ja |
| `retries.revision_attempts` | int | 3 | ≥ 1, ≤ 20 | Weboberfläche | ja |
| `retries.revision_backoff_seconds` | int | 60 | ≥ 1, ≤ 86400 | Weboberfläche | ja |
| `retries.schema_repair` | int | Pflicht | ≥ 0, ≤ 10 | Datei | ja |
| `smart_reply` | bool | False |  | Weboberfläche | ja |
| `target_profiles[].caldav_calendar_url` | str | '' | Länge ≤ 2000 | Zielprofilseite | ja |
| `target_profiles[].caldav_task_url` | str | '' | Länge ≤ 2000 | Zielprofilseite | ja |
| `target_profiles[].calendar_provider` | Auswahl: google, caldav, outlook | 'google' |  | Zielprofilseite | ja |
| `target_profiles[].google_calendar` | str | '' | Länge ≤ 500 | Zielprofilseite | ja |
| `target_profiles[].id` | int | Pflicht | ≥ 2, ≤ 99 | Zielprofilseite | ja |
| `target_profiles[].label` | str | Pflicht | Länge ≥ 1, Länge ≤ 40 | Zielprofilseite | ja |
| `target_profiles[].microsoft_tenant` | str | 'common' |  | Zielprofilseite | ja |
| `target_profiles[].microsoft_todo_list` | str | 'default' | Länge ≥ 1, Länge ≤ 500 | Zielprofilseite | ja |
| `target_profiles[].outlook_calendar` | str | 'default' | Länge ≥ 1, Länge ≤ 500 | Zielprofilseite | ja |
| `target_profiles[].task_provider` | Auswahl: todoist, microsoft_todo, caldav, apple_reminders | 'todoist' |  | Zielprofilseite | ja |
| `target_profiles[].todoist_project` | str | '' | Länge ≤ 500 | Zielprofilseite | ja |
| `targets.caldav_calendar_url` | str | '' | Länge ≤ 2000 | Weboberfläche | ja |
| `targets.caldav_task_url` | str | '' | Länge ≤ 2000 | Weboberfläche | ja |
| `targets.calendar_provider` | Auswahl: google, caldav, outlook | 'google' |  | Weboberfläche | ja |
| `targets.google_calendar` | str | '' | Länge ≤ 500 | Weboberfläche | ja |
| `targets.microsoft_tenant` | str | 'common' |  | Weboberfläche | ja |
| `targets.microsoft_todo_list` | str | 'default' | Länge ≥ 1, Länge ≤ 500 | Weboberfläche | ja |
| `targets.outlook_calendar` | str | 'default' | Länge ≥ 1, Länge ≤ 500 | Weboberfläche | ja |
| `targets.task_provider` | Auswahl: todoist, microsoft_todo, caldav, apple_reminders | 'todoist' |  | Weboberfläche | ja |
| `targets.todoist_project` | str | '' | Länge ≤ 500 | Weboberfläche | ja |
| `telegram.chat_id` | int | 1 |  | Weboberfläche | ja |
| `telegram.enabled` | bool | True |  | Einrichtung | ja |
| `telegram.sequential_questions` | bool | True |  | Weboberfläche | ja |
| `telegram.user_id` | int | 1 | > 0 | Weboberfläche | ja |
| `test_mode` | bool | False |  | Weboberfläche | ja |
| `timeouts.caldav.initial_backoff_seconds` | float | Pflicht | ≥ 0, ≤ 30 | Weboberfläche | ja |
| `timeouts.caldav.max_backoff_seconds` | float | Pflicht | ≥ 0, ≤ 60 | Weboberfläche | ja |
| `timeouts.caldav.retries` | int | Pflicht | ≥ 0, ≤ 10 | Weboberfläche | ja |
| `timeouts.caldav.timeout_seconds` | float | Pflicht | ≥ 1, ≤ 300 | Weboberfläche | ja |
| `timeouts.google_calendar.initial_backoff_seconds` | float | Pflicht | ≥ 0, ≤ 30 | Weboberfläche | ja |
| `timeouts.google_calendar.max_backoff_seconds` | float | Pflicht | ≥ 0, ≤ 60 | Weboberfläche | ja |
| `timeouts.google_calendar.retries` | int | Pflicht | ≥ 0, ≤ 10 | Weboberfläche | ja |
| `timeouts.google_calendar.timeout_seconds` | float | Pflicht | ≥ 1, ≤ 300 | Weboberfläche | ja |
| `timeouts.imap.initial_backoff_seconds` | float | Pflicht | ≥ 0, ≤ 30 | Weboberfläche | ja |
| `timeouts.imap.max_backoff_seconds` | float | Pflicht | ≥ 0, ≤ 60 | Weboberfläche | ja |
| `timeouts.imap.retries` | int | Pflicht | ≥ 0, ≤ 10 | Weboberfläche | ja |
| `timeouts.imap.timeout_seconds` | float | Pflicht | ≥ 1, ≤ 300 | Weboberfläche | ja |
| `timeouts.microsoft.initial_backoff_seconds` | float | Pflicht | ≥ 0, ≤ 30 | Weboberfläche | ja |
| `timeouts.microsoft.max_backoff_seconds` | float | Pflicht | ≥ 0, ≤ 60 | Weboberfläche | ja |
| `timeouts.microsoft.retries` | int | Pflicht | ≥ 0, ≤ 10 | Weboberfläche | ja |
| `timeouts.microsoft.timeout_seconds` | float | Pflicht | ≥ 1, ≤ 300 | Weboberfläche | ja |
| `timeouts.ollama.initial_backoff_seconds` | float | Pflicht | ≥ 0, ≤ 30 | Weboberfläche | ja |
| `timeouts.ollama.max_backoff_seconds` | float | Pflicht | ≥ 0, ≤ 60 | Weboberfläche | ja |
| `timeouts.ollama.retries` | int | Pflicht | ≥ 0, ≤ 10 | Weboberfläche | ja |
| `timeouts.ollama.timeout_seconds` | float | Pflicht | ≥ 1, ≤ 1800 | Weboberfläche | ja |
| `timeouts.openrouter.initial_backoff_seconds` | float | Pflicht | ≥ 0, ≤ 30 | Weboberfläche | ja |
| `timeouts.openrouter.max_backoff_seconds` | float | Pflicht | ≥ 0, ≤ 60 | Weboberfläche | ja |
| `timeouts.openrouter.retries` | int | Pflicht | ≥ 0, ≤ 10 | Weboberfläche | ja |
| `timeouts.openrouter.timeout_seconds` | float | Pflicht | ≥ 1, ≤ 300 | Weboberfläche | ja |
| `timeouts.telegram.initial_backoff_seconds` | float | Pflicht | ≥ 0, ≤ 30 | Weboberfläche | ja |
| `timeouts.telegram.max_backoff_seconds` | float | Pflicht | ≥ 0, ≤ 60 | Weboberfläche | ja |
| `timeouts.telegram.retries` | int | Pflicht | ≥ 0, ≤ 10 | Weboberfläche | ja |
| `timeouts.telegram.timeout_seconds` | float | Pflicht | ≥ 1, ≤ 300 | Weboberfläche | ja |
| `timeouts.telegram_poll_seconds` | int | Pflicht | ≥ 1, ≤ 50 | Datei | ja |
| `timeouts.todoist.initial_backoff_seconds` | float | Pflicht | ≥ 0, ≤ 30 | Weboberfläche | ja |
| `timeouts.todoist.max_backoff_seconds` | float | Pflicht | ≥ 0, ≤ 60 | Weboberfläche | ja |
| `timeouts.todoist.retries` | int | Pflicht | ≥ 0, ≤ 10 | Weboberfläche | ja |
| `timeouts.todoist.timeout_seconds` | float | Pflicht | ≥ 1, ≤ 300 | Weboberfläche | ja |
| `timezone` | str | Pflicht |  | Weboberfläche | ja |
| `vision.enabled` | bool | True |  | Weboberfläche | ja |
| `vision.max_edge_pixels` | int | 1600 | ≥ 512, ≤ 4096 | Weboberfläche | ja |
| `vision.max_image_bytes` | int | 5000000 | ≥ 10240, ≤ 50000000 | Weboberfläche | ja |
| `vision.max_images_per_mail` | int | 3 | ≥ 1, ≤ 10 | Weboberfläche | ja |
| `web.allowed_hosts` | list[str] | ['127.0.0.1:8765', 'localhost:8765'] | Länge ≥ 1, Länge ≤ 20 | Datei | ja |
| `web.enabled` | bool | False |  | Datei | ja |
| `web.google_redirect_uri` | str | 'http://localhost:8765/auth/google/call… |  | Datei | ja |
| `web.host` | str | '127.0.0.1' |  | Datei | ja |
| `web.lan_access` | bool | False |  | Weboberfläche | ja |
| `web.port` | int | 8765 | ≥ 1, ≤ 65535 | Datei | ja |
| `web.session_days` | int | 30 | ≥ 1, ≤ 365 | Weboberfläche | ja |
| `write_verification.max_attempts` | int | 5 | ≥ 1, ≤ 10 | Datei | ja |
| `write_verification.max_elapsed_seconds` | int | 300 | ≥ 10, ≤ 86400 | Datei | ja |
| `write_verification.retry_delays_seconds` | list[int] | [1, 5, 15, 60] | Länge ≤ 9 | Datei | ja |

**24 Kommandozeilenoptionen** (`mailhelp --help`):

| Option | Bedeutung laut Hilfe |
| --- | --- |
| `--check` | Konfiguration validieren und beenden |
| `--check-access` | Zugänge prüfen, Telegram-Testnachricht senden und beenden |
| `--clear` | alle Zustandsdaten, Decision-Test-Berichte und Logs nach ausdrücklicher Bestätigung löschen |
| `--config-directory` | Verzeichnis mit config.yaml, prompts.yaml, topics.yaml und irrelevant_topics.yaml |
| `--decision-test` | ANZAHL Mails über Standardpfad und Ollama vergleichen; nur relevante Mails weiter analysieren |
| `--decision-test-file` | neue JSON-Testdatei für --decision-test (relativ zu --config-directory) |
| `--decision-test-laya` | EXPERIMENTELL: Relevanzprüfung des Ollama-Pfads im --decision-test mit dem Entscheidungsmodell Laya auf diesem Ollama-Server (/v1/systemone) |
| `--decision-test-laya-model` | Laya-Modell für --decision-test-laya; überschreibt model aus laya_prompts.yaml |
| `--decision-test-relevance-only` | im --decision-test ausschließlich die Relevanzprüfung beider Pfade vergleichen |
| `--google-auth` | Google-Anmeldung im lokalen Browser |
| `--ignore-historical-start` | konfiguriertes imap.historical_start und den gespeicherten historischen Startpunkt für diesen Abruf aufheben |
| `--learn` | ANZAHL Mails frei klassifizieren und Themen interaktiv im Terminal lernen |
| `--log-directory` | Logverzeichnis aus config.yaml für diesen Aufruf überschreiben |
| `--mailbox` | Postfach (imap.mailboxes.id) oder alle aktivierten Postfächer für --learn und --decision-test; bei mehreren aktivierten Postfächern erforderlich |
| `--max-mails` | höchstens ANZAHL Mails in einem einzelnen Abrufdurchlauf bearbeiten und beenden |
| `--microsoft-login` | bei Microsoft (Outlook-Kalender, Microsoft To Do) per Gerätecode anmelden und den Refresh-Token in microsoft-token.json neben .env speichern |
| `--ollama` | EXPERIMENTELL: alle LLM-Schritte statt über OpenRouter über den lokalen Ollama-Server HOST:PORT ausführen (IPv6 als [::1]:11434) |
| `--ollama-model` | Ollama-Modell für --ollama; überschreibt ollama.model aus prompts.yaml |
| `--pair` | Lokalen Einmalcode zur Webanmeldung anzeigen |
| `--prepare-rollback` | 5.2: vor der Rückkehr zu einer Version vor 5.2.0 alle Einträge „wird geprüft“ auf „angelegt“ umstellen; nur bei beendetem Dienst |
| `--profile` | Zielprofil (1–99) für die OAuth-Einrichtung |
| `--reset-web-password` | Am Host Web-Passwort zurücksetzen und alle Websitzungen abmelden |
| `--show-imap-credentials` | bei --check-access den tatsächlich verwendeten IMAP-Benutzernamen und das Passwort im Terminal ausgeben |
| `--yes` | Bestätigungsabfrage für --clear überspringen |

<!-- inventar:end -->
