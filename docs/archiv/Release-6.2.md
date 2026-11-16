# Release 6.2 – Umsetzung und Abnahme

Status: Version 6.2 umgesetzt (6.2.1 bis 6.2.10) und mit 6.2.11 unter Windows 11 abgenommen,
14. November 2026. Plan: [Planung 6.2](Planung-6.2.md). Die Entscheidungen E1–E6 wurden ohne
Gegenvorschlag mit dem jeweiligen Vorschlag des Plans übernommen.

## Zuordnung der Planschritte

Während der Umsetzung wurde aus einer parallelen Arbeitssitzung die Version 6.2.5 („Domain für Weblinks
bevorzugen“) veröffentlicht. Die Planschritte ab D5 verschieben sich deshalb um eine Patchnummer:

| Planschritt | Inhalt | Version |
| :--- | :--- | :--- |
| D1 | Gestaltungsvariablen und Wächtertest | 6.2.1 |
| D2 | Seitenkopf, zwei Seitenbreiten, Kartenabstand, Titel (E2) | 6.2.2 |
| D3 | Übersetzungsstelle, lokale Zeiten, Mehrzahl, Anrede (E1) | 6.2.3 |
| D4 | Links zur Einstellung statt Konfigurationsschlüsseln | 6.2.4 |
| – | (nicht Teil des Plans) Domain für Weblinks bevorzugen | 6.2.5 |
| D5 | Gemeinsame Werkzeugleiste, Verlauf-Filter | 6.2.6 |
| D6 | Dichte Zeilenlisten, einheitliche Statusplakette (E6) | 6.2.7 |
| D7 | „Offen“ auf dem Telefon, Handyleiste (E3), Klärung B14 | 6.2.8 |
| D8 | Einstellungen zusammenlegen (E4), Status-Kopfzeile | 6.2.9 |
| D9 | Auswertung: Kacheln, Leerzustand, Abschnitte | 6.2.10 |
| D10 | Doku, Abnahme, Release | 6.2.11 |

## Ergebnis gegenüber der Bestandsaufnahme

| Befund | Vorher | Nachher |
| :--- | :--- | :--- |
| B1 Verlauf | ISO-Zeiten, `rejected`, sechs Freitextfelder | lokale Zeit, „Verworfen“, Auswahl- und Datumsfelder |
| B2 Offen (390 × 844) | erste Entscheidung bei rund 800 px | in den oberen 60 % des Fensters (Test) |
| B3 Seitenkopf | 8 von 72 Seiten | alle Kernseiten; Titel gleich Navigationseintrag |
| B4 Technische Sprache | „activity_report.enabled in config.yaml“ | Link „Einstellungen → Tätigkeitsberichte aktivieren“ |
| B5 Seitenbreite | fünf Breiten, teils mittig | zwei Breiten, gleiche linke Kante (Test) |
| B6 Karten | rund 45 px Leerraum oben | kein Abstand über dem ersten Element (Test) |
| B7 Listen (1920 × 1080) | etwa fünf Einträge | mindestens zwölf (Zeilenhöhe ≤ 72 px, Test) |
| B8 Einstellungen | 22 Kacheln mit Doppelungen | 18 Kacheln, keine Doppelungen |
| B9 Anrede, Mehrzahl | „Sie“ und „du“, „1 Vorschlägen“ | durchgehend „du“, Mehrzahl stimmt (Wächtertests) |
| B10 Hauptaktion | uneinheitlich | genau eine hervorgehobene Hauptaktion je Listenformular |
| B11 Auswertung | Nullen-Tabelle; ~14 Bildschirmhöhen auf dem Telefon | Kacheln, Leerzustand, Sprunglinks, Diagramme zugeklappt |
| B12 Handyleiste | Status statt Abgleich | Offen, Mails, Abgleich, Verlauf |
| B13 Gestaltung | 12 Eckenradien, ~20 Schriftgrößen fest im CSS | Variablen; Wächtertest gegen feste Werte |
| B14 Leerraum in der Detailkarte | vermutet | geklärt: haftende Entscheidungsleiste, kein Leerraum (Test) |

## Abweichungen und Präzisierungen

- **Schriftskala:** neun statt fünf Stufen; fünf hätten Überschriften und die schmale Seitenleiste
  sichtbar verändert. Abstandsvariablen gelten für Rahmen und neue Bausteine; der Wächtertest prüft
  Farben, Ecken, Schriftgrößen und Schatten, nicht jeden Einzelabstand.
- **Themenseite:** kein Zurück-Link im Kopf, damit die erste Themenzeile auch bei 320 px im ersten
  Bildschirm bleibt (vom Browsertest gefunden).
- **Zeilen auf dem Telefon:** drei kurze Zeilen (Titel, Absender und Zeit, Plaketten), bei langen
  Plaketten vier – nicht zwei wie geplant; zwei hätten Plaketten abgeschnitten.
- **„Offen“ auf dem Telefon:** Aktive Suche und Sortierung stehen in der Zusammenfassung von „Suchen und
  sortieren“, nicht als einzeln entfernbare Plaketten; „Zurücksetzen“ entfernt alles.
- **Einstellungen:** 18 statt rund 14 Kacheln; „Einrichtung“, „Konfiguration neu laden“ und die
  Inhaltskacheln haben eigene Zwecke. Keine Seite verliert ihre Adresse, Weiterleitungen sind nicht nötig.
- **Auswertung:** Sprungmarken zu Kennzahlen, Diagrammen, Ablauf und Tabelle statt „Kosten/Zeiten/Ablauf“,
  weil die Diagramme beides mischen.
- **Statusseite:** Der Hinweis zu „Verbunden“ steht als kurze Erklärung unter den Kennzahlen, nicht am
  Verbindungszeichen (dieses wird erst mit JavaScript eingeblendet).
- **Vorher-Nachher-Bilder:** statt eingecheckter Bilder die Messwerte oben; die Screenshots jedes
  Browserlaufs liegen unter `.test-tmp/ui-screens/`.
- **UI-07** (Einstellungen bestätigen) war seit 5.8 bereits umgesetzt; **UI-12** (Fachbegriffe bei
  Zuordnen/Verwerfen) ist nicht umgesetzt und wird in eine spätere Version verschoben.

## Bei der Umsetzung gefundene Fehler

| Fehler | Behebung | Regressionstest |
| :--- | :--- | :--- |
| „Aus Entscheidungen lernen“ hatte ohne verfügbare Lernfunktion keine Überschrift und keinen Weg zurück. | 6.2.2 | `test_service_unavailable_and_initial_page_have_no_model_side_effects` |
| Mehrzahlfehler („1 Vorschlägen“, „1 Änderungen“, „1 gespeicherte Mails“, „1 Durchläufe“), von Tests festgeschrieben. | `count_text` (6.2.3) | angepasste Tests in `test_rule_compare573.py`, `test_v618_stage_view.py` u. a. |
| Verlauf zeigte interne Werte und ISO-Zeiten. | 6.2.3 | `test_history_filters_paging_and_first_version`, `test_ui_language623.py` |
| Abgleich: „Ziel: Anbieter nicht gespeichert“ bei älteren Vorschlägen. | 6.2.4 | `test_the_target_names_the_profile_when_no_service_was_stored` |
| Leere Auswertung zeigte acht Kennzahlen voller Nullen. | 6.2.10 | `test_statistics_page_labels_rates_and_incomplete_capture` |

## Prüfergebnisse (Windows 11, Python 3.12)

- `ruff check src tests ui_tests devtools` und `mypy src/mailhelp`: ohne Befund.
- `pytest` mit Coverage (8 Worker, Endstand 6.2.11): 100 % Zeilen- und Branch-Abdeckung; 5107 bestanden,
  1 übersprungen. Die Lasttests `test_v42_load.py` und `test_v441_load.py` scheitern nur bei paralleler
  Ausführung mit 8 Workern und bestehen einzeln (bekannt seit 5.9).
- Browser-Suite (`pytest ui_tests -n 4 --dist worksteal --no-cov`) nach jedem Patch auf genau dem
  committeten Stand in einem eigenen Arbeitsverzeichnis:

  | Stand | Ergebnis |
  | :--- | :--- |
  | 6.2.1 | 637 bestanden |
  | 6.2.2 | 8 Fehlschläge: alter Titel „Kosten und Zeiten“ in zwei Tests, Themenzeile bei 320 px unter dem ersten Bildschirm – behoben in 6.2.3 |
  | 6.2.3 | 7 Fehlschläge: zwei Tests erwarteten die alte Mehrzahl, ein Zeitgrenzentest der Einstellungssuche unter Last – behoben bzw. einzeln bestanden in 6.2.4 |
  | 6.2.4 | 4 Fehlschläge unter gleichzeitiger Python-Gesamtprüfung; alle einzeln bestanden |
  | 6.2.6 | 653 bestanden |
  | 6.2.7 | 656 bestanden |
  | 6.2.8 | 665 bestanden |
  | 6.2.9 | 665 bestanden |
  | 6.2.10 | 671 bestanden |

  100 % JavaScript-Blockabdeckung über alle Worker; seit 6.2.4 laufen Browser- und Python-Prüfungen
  nicht mehr gleichzeitig, weil die zusätzliche Last zeitkritische Tests scheitern ließ.
- Einmalige Lastausfälle in der Python-Gesamtprüfung, jeweils einzeln bestanden:
  `test_hard_kill_matrix_reconciles_real_adapter_after_two_restarts[A4-todoist]` (6.2.4, mit fehlenden
  Abdeckungsdaten dieses Workers; Wiederholung 100 %), `test_parallel_submissions_and_processing_lose_nothing`
  (6.2.7).
- Paket gebaut (`python -m build` in einer eigenen Umgebung); Wheel-Prüfungen bestanden.

**Nicht ausgeführt:** Die Prüfung unter Linux/Docker. Auf dem Abnahmerechner ist Docker nicht
installiert; sie steht noch aus.

## Dokumentation

README, CHANGELOG, Projektspezifikation, Bedienung, Ersteinrichtung, Fehlerbehebung und der eingebaute
Hilfebestand wurden je Patch aktualisiert. Es gibt keine neuen Einstellungen; die Konfigurationsbeispiele
bleiben unverändert.
