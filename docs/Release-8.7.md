# Mailhelp 8.7 – Umsetzung und Freigabestand

Stand: 27. November 2026. Version 8.7.16. Grundlage: [Planung 8.7](Planung-8.7.md) und
[Lernen in Punkten](Planung-8.7-Lernen.md).

> **Plan abgeschlossen, noch keine Kundenfreischaltung.** AP1–AP7 sind umgesetzt (8.7.1–8.7.15), alle
> Abnahmeszenarien aus Plan §10 sind automatisiert mit synthetischen Daten bestanden. Auf Entscheidung des
> Betreibers vom 27.11.2026 entfallen alle Schritte, die eine manuelle Eingabe erfordern (siehe „Entfallen“).
> Abnahme 3 ist deshalb automatisiert geprüft. Dabei fiel ein Fehler auf, den 8.7.15 behebt. Eine Instanz wird
> erst freigeschaltet, wenn der Betreiber das ausdrücklich veranlasst (Plan §8).

## Umgesetzt in 8.7.1

| Arbeitspaket | Umsetzung |
| --- | --- |
| AP1 Inventur | 131 Routen der Weboberfläche plus optionale Seiten (OAuth, Nachanalyse, Onboarding) erfasst. Kundenwege stehen ausdrücklich in `web/permissions.py`, alle übrigen sind für Kunden gesperrt (Standardsperre, auch für künftige Routen). Einstellungsfelder für Kunden stehen in `CUSTOMER_FIELDS` (`config/configuration.py`). |
| AP2 Modus und Rollen | `operator.yaml` (`customer_mode`, `instance`) liest nur der Start; Mailhelp schreibt diese Datei nie. Jede Sitzung trägt im Kundenmodus serverseitig Rolle und Instanz. Codes über Browser, Telegram `/web`, Passwort und `mailhelp --pair` ergeben Kundenrechte, nur `mailhelp --pair --operator` am Host ergibt eine Betreibersitzung. Bei der Aktivierung werden rollenlose Sitzungen und Codes widerrufen. Kunden sehen und beenden nur Kundengeräte; `/web_abmelden` per Telegram beendet nur Kundensitzungen. Zentrale Prüfung in `MailhelpSite.signed_in` vor jedem Formular; Einstellungsänderungen werden beim Ausführen und vor dem Schreiben erneut geprüft und bei einem gesperrten Feld vollständig abgelehnt. Neustart, Beenden, Zugangsdaten und Dienst-Neuladen verlangen beim Ausführen Betreiberrechte. |
| AP3 Punkte und Speicherung | `usage/points.py` rechnet mit `Decimal` in 34 Stellen und rundet nur in der Anzeige (kaufmännisch, „< 0,01 Punkte“). `usage/ledger.py` führt den Verbrauchsbestand `usage/attempts.jsonl` im Zustandsverzeichnis: Jeder OpenRouter-Versuch wird vor dem Senden mit seinem Bewertungsstand gebunden und genau einmal abgeschlossen. Wiederholungen und Fallbacks sind eigene Versuche; fehlende oder ungültige Kosten bleiben ungeklärt, ein abgewiesener Verbindungsaufbau gilt als nicht gesendet. Eine durch Absturz abgebrochene Zeile wird nach `attempts.jsonl.torn` verschoben. `mailhelp --set-valuation USD_JE_EUR AUFSCHLAG_PROZENT` legt am Host nach Anzeige von Alt/Neu und Beispiel einen neuen, unveränderlichen Bewertungsstand an. Ohne Bewertungsstand wird nichts erfasst. Lokale Modelle (Ollama) werden nie erfasst. |
| AP4 Kundenansichten | Begonnen: Seite `/verbrauch` mit heute, laufendem Monat und Zeitraum sowie Aufteilung nach Schritt und Tag, nur in Punkten. Offen: rechtegerechte Einstellungsseiten, Punkte statt Geldwerten in Lernen, Berichten, Hilfschat und Diagrammen, rollenabhängige Suche und Hilfe. Bis dahin sind Lernen (`/lernen`, `/themen/lernen`) und Berichte (`/berichte`) für Kundensitzungen gesperrt, weil sie noch Budgets und Schätzungen in Geld zeigen. |
| AP5–AP7 | Offen, außer Dokumentation dieses Stands. |

## Umgesetzt in 8.7.2

| Thema | Umsetzung |
| --- | --- |
| Bugfix Bewertungsstand | `mailhelp --set-valuation` funktioniert vor der Ersteinrichtung (bisher Abbruch ohne `config.yaml`) und schreibt nach `data/production`, wo Ersteinrichtung und Dienst lesen |
| Planung | [Lernen in Punkten und Kundeninstanz `kunde`](Planung-8.7-Lernen.md); Bewertung der Instanz `kunde`: 1 USD je EUR, Aufschlag 900 % (Faktor 10) |
| Vorlage | `ops/server/kunde.compose.example.yaml`; `operator.yaml` schreibgeschützt eingebunden |

## Umgesetzt in 8.7.3

Kundeninstanz `kunde` (Plan [Lernen in Punkten](Planung-8.7-Lernen.md) §6) auf dem Server mit
8.7.2 eingerichtet und geprüft, Einzelheiten in [Betrieb](Betrieb.md). Sie läuft im
Ersteinrichtungsmodus; die Ersteinrichtung mit dem Betreiber-OpenRouter-Schlüssel nimmt der
Betreiber vor. Keine Kundenfreischaltung.

## Umgesetzt in 8.7.4 – Lernen in Punkten

Umsetzung von [Lernen in Punkten](Planung-8.7-Lernen.md) §4:

| Thema | Umsetzung |
| --- | --- |
| Preisannahme | `learning_usd_per_million_tokens` in `operator.yaml` (positiv, höchstens 10000, nur beim Start gelesen). Ohne Wert oder ohne Bewertungsstand: „Lernen aus dem Postfach ist vom Betreiber noch nicht eingerichtet“, kein Start |
| Umrechnung | `usage/budget.py`: Punktegrenze → USD-Grenze `Punkte / 1000 × Kurs / (1 + Aufschlag/100)`, abgerundet auf 10⁻¹² USD und als Gleitkommazahl nie darüber; Schätzung in Punkten über dieselbe Formel wie der Verbrauch. Die genannte Mindestgrenze ist genau der Wert, den die Startprüfung annimmt (gegebenenfalls ein Punkt mehr für die Abrundung) |
| Kundenansicht `/lernen/postfach` | Feld „Punktegrenze für diesen Lauf“ (1–10.000.000); geschätzter Verbrauch und ungünstigster Fall in Punkten; reserviert und tatsächlich verbraucht in Punkten mit Zahl der noch nicht bewertbaren Aufrufe; keine Modell-, Preis-, Token- oder USD-Angaben, auch nicht im versteckten Feld; kein Link auf „Konfiguration neu laden“ |
| Start | Das versteckte Feld enthält nur Postfach, Ordner, Anzahl, Punkte und Bewertungsrevision. Der Server rechnet die USD-Grenze selbst; eingeschleuste Geldfelder, Zahlen statt Text, ungültige Punkte und eine inzwischen geänderte Bewertung („Bewertung geändert, bitte Schätzung prüfen“) lehnen den Start vollständig ab |
| Zustand | `web-learning.json` unverändert (Rückkehr auf 8.7.3 möglich); Punktegrenze und Revision in `web-learning-points.json`, an die Generation des Laufs gebunden und bei jedem Start ersetzt |
| Verbrauch | Aufrufe eines Lernlaufs werden als `learning.<Schritt>` erfasst (gleiches Zeilenformat von `attempts.jsonl`); `/verbrauch` fasst sie als „Aus dem Postfach lernen“ zusammen und nennt „Aus Entscheidungen lernen“ und „Hilfschat“ |
| Übernahme | Bei Kundensitzungen nur Kundenfelder in `config.yaml` (Abrufordner des gewählten Postfachs), sonst vollständige Ablehnung; die neuen Themen werden wie beim Speichern unter „Themen“ übernommen |
| Weitere Seiten | `/lernen`, `/lernen/entscheidungen` und das Hilfschat-Formular sprechen für Kunden von Punkten statt Kosten; ein fehlender Schritt `decision_rule_learning` heißt für Kunden „vom Betreiber noch nicht eingerichtet“ ohne Verweis auf `prompts.yaml` |
| Rechte | Für Kunden freigegeben: `/lernen`, `/lernen/postfach`, `/lernen/entscheidungen`, `/themen/lernen` (GET/POST), `/api/lernen`, `/api/lernen/uebersicht`, `/lernen/vorschlaege`, `/lernen/absender-hinweis` (GET) und deren Aktionen |

Betreiber sehen weiterhin das USD-Formular und zusätzlich reservierte und verbrauchte Punkte. Selbst
betriebene Instanzen sind unverändert. Am 26.11.2026 auf `kunde` ausgeliefert (8.7.5, siehe unten).

Protokolle, Logging-Einstellungen, Rotation und Aufbewahrung sind unverändert. Der Verbrauchsbestand ist
eine eigene Datei und wird nicht aus Logs aufgebaut.

## Umgesetzt in 8.7.5 – Auslieferung auf `kunde`, Arbeitspakete

| Thema | Umsetzung |
| --- | --- |
| Preisrahmen | Aus den Produktionslogs 13.–25.11.2026 (293 bewertete Aufrufe von `deepseek/deepseek-v4.1-flash`): Eingabe höchstens 0,30, Ausgabe höchstens 1,20 USD je Mio. Tokens, Mischpreis 0,30. Festgelegt `learning_usd_per_million_tokens: "1.2"`, damit kein Lauf seine Punktegrenze überschreitet ([Planung](Planung-8.7-Lernen.md) §4.5) |
| Auslieferung | `kunde` am 26.11.2026 auf `mailhelp-production:8.7.4-4e86ee4` mit Hostpaket-Update und Sicherung; weiterhin im Ersteinrichtungsmodus ([Betrieb](Betrieb.md)) |
| Arbeitspakete | Offene Punkte als AP4a (Navigation und Links nach Rolle), AP4b (Kostenhinweise und Berichte in Punkten), AP4c (Hilfe und Suche nach Rolle), AP5, AP6 und Prüfstabilität ([Planung](Planung-8.7-Lernen.md) §8) |

## Umgesetzt in 8.7.6 – AP4a Navigation und Links nach Rolle

| Thema | Umsetzung |
| --- | --- |
| Navigation | Kundensitzungen sehen nur Offen, Mails, Verlauf, Verbrauch, Einstellungen, Lernen und Geräte (Seitenleiste, Tab-Leiste, „Mehr“); Status, Auswertung, Berichte und Vorschlagsabgleich entfallen. Betreiber sehen die bisherige Navigation |
| Links in Seiten | Der Seitenrahmen entfernt für Kundensitzungen jeden lokalen Link auf einen für Kunden gesperrten Weg samt verwaister Trenner (z. B. Zugangsdaten, IServ-Konten, Diagnose, Einrichtung, Notion-Datenquelle); Sprache und Anmeldung bleiben |
| Einstellungen | `/einstellungen` zeigt Kunden eine Übersicht ihrer Bereiche, unabhängig von `bereich` und `suche`; Bereiche, Suche und Zugangsdaten des Betreibers bleiben gesperrt (`/api/einstellungen/suche` weiterhin 403) |
| Bugfix Lernformular | Die Eingabetaste in einem Feld zeigt die Schätzung statt „Ordner laden“ (verborgener Standardknopf, in Chrome und WebKit geprüft); Regressionstest `tests/web/test_learning_setup_enter.py` und Browsertest mit Eingabetaste im Feld |
| Prüfung | `tests/web/test_customer_links.py` folgt allen Links der erreichbaren Kundenseiten und meldet jeden Link und jedes Formularziel, das Kunden nicht nutzen dürfen |

Nicht ausgeliefert; `kunde` läuft mit 8.7.4.

## Umgesetzt in 8.7.7 – AP4b Kostenhinweise in Punkten, Notion-Schritte

| Thema | Umsetzung |
| --- | --- |
| Berichte | `/berichte` mit Neuanlage, Bericht, Aktionen, Mail-Korrektur und xlsx-Export für Kunden freigegeben. Schätzung aus denselben Messwerten wie für Betreiber, für Kunden in Punkten (`activity/costs.py: measure`, `consumption.report_estimate_text`); lokale Stromkosten und Geldwerte erscheinen nie. Startknopf „Bericht starten (verbraucht Punkte)“; ausgeschaltete Berichte nennen den Betreiber statt `prompts.yaml`. Der xlsx-Export enthielt schon keine Geldwerte |
| Nachanalyse | Kunden lesen „Höchstens N KI-Aufrufe, die Punkte verbrauchen“ und den Verweis auf „Verbrauch“ statt „kostenpflichtige Modellaufrufe“ und „Auswertung“ |
| Notion | Betreiberentscheidung 26.11.2026: `/notion/datenquelle` und `/notion/zuordnung` (GET/POST) sind Kundenwege; der Entwurf ändert nur das gewählte Zielprofil, danach führt die Seite Kunden zu „Zielprofile“ statt zu `/einrichtung` |
| Verbrauch | Beide Berichtsschritte erscheinen als eine Zeile „Tätigkeitsberichte“ |
| Prüfung | `tests/web/test_customer_links.py` sucht auf allen erreichbaren Kundenseiten (ohne Produktdokumentation, AP4c) nach `USD`, `EUR`, `€`, `Cent`, „Kosten“, „kostenpflichtig“ und `usd_`; `tests/web/test_customer_points_pages.py` prüft Berichtsschätzung und Nachanalyse |

Nicht ausgeliefert; `kunde` läuft mit 8.7.4.

## Umgesetzt in 8.7.8 – AP4c Hilfe und Suche nach Rolle

| Thema | Umsetzung |
| --- | --- |
| Hilfe | Kundensitzungen sehen im Hilfeindex und auf den Abschnittsseiten nur die 32 in `helpdocs/roles.py` freigegebenen Abschnitte (Bedienung, Lernen in der Kundeninstanz, eigene Postfächer und Ziele, Benachrichtigungen, Briefings, Fehlerbehebung ohne Hostzugriff); alle anderen, auch künftige, antworten mit 404. Betreiber sehen alle Abschnitte |
| Hilfschat | Kundenaufträge beziehen nur freigegebene Abschnitte als Quellen; die Rolle wird beim Ausführen geprüft. Unter Antworten nennt der Chat Kunden keine Einstellungsbereiche |
| Texte | „Lernen in einer Kundeninstanz“ spricht nicht mehr von Preisen und Kosten; die Lernübersicht „verbraucht nichts“ statt „kostet nichts“ |
| Suche und Kanäle | Die Einstellungssuche bleibt Betreibern vorbehalten (403). Telegram-, Push- und Briefingtexte enthalten keine Geldwerte (geprüft) |
| Prüfung | `tests/unit/test_help_roles.py` prüft jeden freigegebenen Abschnitt in Deutsch und Englisch auf Geld-, Server-, Prompt-, Geheimnis- und Hostbefehlsbegriffe; `tests/web/test_customer_help.py` Index, Abschnitte und Chatquellen nach Rolle; die Geldbegriffsprüfung der Kundenseiten schließt die Hilfe ein |

Nicht ausgeliefert; `kunde` läuft mit 8.7.4.

## Umgesetzt in 8.7.9 – AP5 Einrichtungsprüfung und Trennung der Instanzen

| Thema | Umsetzung |
| --- | --- |
| Einrichtungsprüfung | `mailhelp --check-instance` am Host, auch vor der Ersteinrichtung: Kundenmodus, Bewertungsstand, Preisannahme für Lernläufe, Ersteinrichtung und Betreiberzugang je mit OK oder FEHLT samt nächstem Schritt, Kundensitzungen als HINWEIS; Exitcode 0/1/2; liest nur, gibt keine Geheimnisse aus |
| Trennung | Zwei Instanzen mit eigenem Zustand: vertauschte Sitzungscookies, fremde Kopplungscodes, fremde Mail- und Vorschlagsreferenzen und das Abmelden aller Kunden wirken nur in der eigenen Instanz (`tests/web/test_instance_isolation.py`) |
| Kundenhinweise | Fehlende Betreiberschritte erscheinen Kunden als verständliche Hinweise: Verbrauch ohne Bewertungsstand, Lernen ohne Preisannahme, ausgeschaltete Berichte |

Offen beim Betreiber: Ersteinrichtung von `kunde` mit eigenem OpenRouter-Schlüssel, Betreiber- und Kundenkopplung, synthetisches Postfach; danach AP6.

## Umgesetzt in 8.7.10 – Auslieferung von 8.7.9 auf `kunde`, AP6 (automatisierter Teil)

| Thema | Umsetzung |
| --- | --- |
| Auslieferung | `kunde` läuft seit 26.11.2026 mit `mailhelp-production:8.7.9-d15df13`; `--check-instance` am Server: Kundenmodus, Bewertungsstand und Preisannahme OK, Ersteinrichtung und Betreiberzugang fehlen; Trennung von Produktion und Demo (Netz, Mounts, Port, Benutzer) geprüft ([Betrieb](Betrieb.md)) |
| Abnahme 15 | Rechnungsbeträge in Euro und Dollar einer Mail bleiben in der Kundensitzung unverändert sichtbar |
| Abnahme 17 | Verbrauchssummen bleiben nach Entfernen der Logs gleich; der Bestand liegt im Zustandsverzeichnis, nicht in den Logs |
| Abnahme 19 | Nach einem Neustart über denselben Zustand behalten Kunden- und Betreibersitzung ihre Rolle; der Verbrauch ist vollständig. Eine Wiederherstellungsprobe ist nicht Teil dieses Releases (Betreiberentscheidung zu 8.0); Rückkehr je Update dokumentiert |
| Abnahme 20 | 2,5 Mio. Punkte Verbrauch: keine Sperre, keine Guthaben- oder Zahlungsaufforderung, alle Kundenseiten erreichbar |
| Checkliste | Schritte nach der Ersteinrichtung (Abnahme 3, Lernlauf mit Kostenabgleich) in [Betrieb](Betrieb.md) |

Tests: `tests/web/test_customer_acceptance.py`.

## Umgesetzt in 8.7.11 – Prüfstabilität

| Thema | Umsetzung |
| --- | --- |
| Dateien und Verzeichnisse unter Windows | Kurz gesperrte Dateien oder Verzeichnisse (Virenscanner, Indexer, Leser) brachen Demo-Start (503), Demo-Export und das Speichern von Zustandsdateien und Prüfberichten mit WinError 5 ab; jetzt begrenzte Wiederholung (8 Versuche, etwa 1,3 s), danach die ursprüngliche Meldung. Regressionstests in `tests/unit/test_replace_path.py` und `tests/release/test_demo_dataset.py` |
| Live-Suche | Antwortzeit im Browser gemessen (Eingabe bis angezeigte Treffer); Grenze unverändert 300 ms für 95 von 100 Suchen |
| JavaScript-Abdeckung | `settings.js` wieder vollständig abgedeckt: wirkungslose Prüfung versteckter Felder entfernt, Speicherleiste bis zurück auf 0 Änderungen getestet |
| CI | Fehlgeschlagene Tests und Abdeckung als öffentliche Annotationen (`tests/release/test_ci_workflows.py`) |
| AP6 | Ersteinrichtung, Abnahme 3 und Lernlauf auf Wunsch des Betreibers zurückgestellt |

## Umgesetzt in 8.7.12 – CI auf Linux

| Thema | Umsetzung |
| --- | --- |
| Cache-Schlüssel | Statische Web-Dateien mit LF auf jedem System (`.gitattributes`); dieselben Schlüssel unter Windows, Linux und im Docker-Image; Golden-Seiten nur im Schlüssel angepasst |
| Browsertests | Kontexte standardmäßig deutsch und Europe/Berlin; Linux-CI mit Roboto |
| Tabellenlinks | Betreff im Tätigkeitsbericht und Mail in der Stufenansicht mit eigener Tippfläche von mindestens 44 px (`cell-link`) |
| Ersteinrichtung | Eine vor dem Skript eingegebene Zeitzone wird nicht mehr durch die Browser-Zeitzone ersetzt |
| Abdeckung | Zweig ohne `chmod` im Geheimnisspeicher auf jeder Plattform getestet |
| Lasttest | `test_load_store_lock` getrennt und seriell |

## Umgesetzt in 8.7.13 – hängende Linux-Browsersuite

| Thema | Umsetzung |
| --- | --- |
| Aufräumen nach Tests | Abdeckung nur von einer Seite, die binnen 5 s antwortet (`Page.settle`); vorher wartete die DevTools-Abfrage ohne Zeitlimit auf einen stummen Renderer, und der CI-Job lief bis zur Abbruchgrenze von sechs Stunden |
| Asynchrone Wartebedingungen | `wait_until` statt `wait_for_function`, das ein Promise auch bei `false` als erfüllt zählt; betroffen waren Hilfefenster- und Service-Worker-Tests. Eine Quelltextprüfung verhindert neue Fälle |
| Service Worker | test78 nutzt je Sprache einen frischen Kontext; der Wechsel des laufenden Workers blockierte Chrome unter Playwright gelegentlich |
| Hilfefenster bei gesperrtem Speicher | Der Test wartet auf die Navigation der Suche, bevor er die neue Seite prüft |
| CI | Browserschritt mit `timeout-minutes: 45` |

Tests: `ui_tests/test_ui_harness_bounds.py`, `tests/release/test_ci_workflows.py`. Offen: Der Lasttest
`test_load_store_lock` überschreitet auf dem GitHub-Windows-Runner seine Grenze (Accept bis 353 ms bei erlaubtem
Median unter 100 ms); lokal hält er sie. Die Grenze bleibt unverändert, bis der Betreiber entscheidet.

## Umgesetzt in 8.7.14 – Lastgrenze auf GitHub-Runnern

| Thema | Umsetzung |
| --- | --- |
| Lasttest `test_load_store_lock` | Auf Wunsch des Betreibers eigene Grenze nur bei `GITHUB_ACTIONS=true`: Median unter 1000 ms, höchstens 2000 ms. Lokal und auf jedem anderen Rechner bleibt sie bei Median unter 100 ms und höchstens 300 ms. Beide Grenzen liegen weit unter der Sperrdauer von 5000 ms. Damit erkennt der Test weiterhin jede Annahme, die auf die Speichersperre wartet |

Test: `test_the_accept_budget_is_strict_locally_and_looser_only_on_hosted_runners`.

## Umgesetzt in 8.7.15 – Abnahme 3: Kunden übernehmen eigene Postfachentwürfe

| Thema | Umsetzung |
| --- | --- |
| Befund | Ein Kunde konnte Postfach-, Benachrichtigungs- und Zielentwürfe speichern, aber nie übernehmen: Die Vorschau schickte die Übernahme an `/einrichtung/uebernehmen` (für Kunden 403). Jedes `imap.`-Feld, auch eine Ruhezeit, verlangte eine IMAP-Diagnose auf `/diagnose`, die Kunden nicht öffnen dürfen. Die Rechteprüfung lehnte die ganze Liste `imap.mailboxes` ab, weil sie kein Kundenfeld ist |
| Übernahme | `POST /einstellungen/postfaecher/uebernehmen` mit demselben Ablauf wie `/einrichtung/uebernehmen` (Bestätigung, CSRF, Version, Dateistand, Idempotenz, Ausführung erst im Hauptablauf) |
| Rechte | `imap.mailboxes` zählt nach den tatsächlich geänderten Blattfeldern; Kunden dürfen nur `CUSTOMER_FIELDS` ändern und eigene Postfächer hinzufügen oder entfernen. Ein Entwurf des Betreibers mit Betreiberfeldern bleibt für Kunden gesperrt (bei der Ausführung abgelehnt, Entwurf bleibt erhalten) |
| Diagnose | Nur Verbindungsfelder verlangen eine Diagnose, Postfachregeln und Bezeichnung nicht. Fehlende Prüfungen eigener Verbindungen startet die Vorschau selbst (`/einstellungen/postfaecher/pruefen`, nur `imap`, `calendar`, `todoist`, `calendar:<n>`, `tasks:<n>`; lesend, kein LLM-Test) |

Tests: `tests/web/test_customer_acceptance_3.py` (Regressionstest schlägt mit 8.7.14 fehl).

Prüfung am 27.11.2026 (lokal, Windows 11, 12 Threads): `python -m devtools.check full --workers 12` mit 6.664
bestandenen Tests und 100 % Zeilen- und Branch-Abdeckung. Rot blieb nur
`tests/evaluation/test_prompt_gate.py`, und zwar wegen der noch nicht versionierten Promptentwürfe für 8.9 in
`prompts.yaml`, die nicht zu 8.7.15 gehören. Lasttests einzeln bestanden (4), ruff und mypy ohne Befund. Browsersuite
`python -m pytest ui_tests -n 6 --dist worksteal --no-cov`: 1.013 bestanden, 234 übersprungen, JavaScript-Abdeckung
100 %. Das Kriterium der Prüfstabilität („zwei Vollprüfungen und eine Browsersuite hintereinander ohne Wiederholung
grün“) ist damit nicht formal belegt. Die erste Vollprüfung scheiterte an einer verschobenen Hilfekennung in
`docs/Betrieb.md` (behoben), die zweite am fremden Promptentwurf. Keine Wiederholung eines Tests war nötig.

## Entfallen (Betreiberentscheidung 27.11.2026)

Folgende Schritte erfordern eine manuelle Eingabe des Betreibers und entfallen für den Abschluss von 8.7. Sie sind
nicht als bestanden zu lesen:

| Schritt | Ersatz |
| --- | --- |
| Ersteinrichtung von `kunde` mit eigenem OpenRouter-Schlüssel, Betreiber- und Kundenkopplung, synthetisches Postfach (AP5) | Einrichtungsprüfung und Trennung automatisiert (8.7.9, `tests/web/test_instance_isolation.py`); `kunde` bleibt im Ersteinrichtungsmodus |
| Abnahme 3 vor Ort auf `kunde` (AP6) | Automatisiert in der Kundensitzung (8.7.15) |
| Echter Lernlauf in Punkten mit Kostenabgleich gegen OpenRouter (AP6) | Lernen in Punkten automatisiert mit simuliertem Anbieter (`tests/services/test_learning_points.py`); Preisannahme aus Produktionslogs ([Plan](Planung-8.7-Lernen.md) §4.5) |

## Prüfung

| Nr. (Plan §10) | Szenario | Ergebnis |
| --- | --- | --- |
| 1 | Kundenkopplung, manipulierte Felder `role`/`geraet`/URL | Nur Kundenrechte (`tests/web/test_customer_mode.py`) |
| 2 | Betreiberzugang über `--pair --operator` | Betreibersitzung; Kundenmodus bleibt aktiv |
| 4 | Betreiberseiten, Zugangsdaten, Einrichtung, Diagnose, Suche per GET/POST/API | 403 vor dem Lesen des Formulars, kein Schlüssel in der Antwort |
| 5 | Erlaubtes und gesperrtes Feld zusammen, `metrics.usd_per_eur` | Vollständig abgelehnt, Datei unverändert |
| 6 | Stopanforderung einer Kundensitzung, Befehl nach Widerruf | Abgewiesen |
| 7 | Geräteverwaltung durch Kunden | Betreibersitzungen weder sichtbar noch beendbar |
| 8 | 0,01 USD, 1,25 USD/EUR, 25 % / 0 % | 10 / 8 Punkte (`tests/usage/test_usage_points.py`) |
| 9 | Bewertungsänderung während eines laufenden Versuchs | Alter Versuch behält Stand 1 (`tests/usage`) |
| 10 | 125.000 Kleinstbeträge, Sommerzeit, Monatsgrenze | Genau 10 Punkte; jeder Versuch genau einem Tag zugeordnet |
| 11 | Nullkosten, fehlende und ungültige Kosten | Null bleibt null; fehlend/ungültig ungeklärt |
| 12 | Wiederholungen, Fallbacks, doppelte Zeilen | Jeder Versuch zählt einmal |
| 13 | Abgebrochener Schreibvorgang, Neustart | Keine erfundenen Kosten, später nachgewiesenes Ergebnis einmal ergänzt |
| 16 | Sitzung einer anderen Instanz | Wird nicht angenommen |
| 18 | Aktivierung auf bestehender Instanz | Rollenlose Sitzungen und Codes widerrufen; kein rückwirkender Verbrauch |
| 14 (Lernen) | Geldbegriffe, `usd_`, Tokens, Modellnamen in HTML, versteckten Feldern und JSON von `/lernen*`, `/api/lernen*` | Keine Treffer für Kundensitzungen (`tests/services/test_learning_points.py`) |
| – | Lernen: Manipulation, Bewertungswechsel, Wiederholung, Anhalten vor der Grenze, Neustart, Übernahme | Wie Plan Lernen in Punkten §5 (`tests/services/test_learning_points.py`, `tests/usage/test_usage_budget.py`) |
| – | Links und Formulare aller erreichbaren Kundenseiten | Nur für Kunden erlaubte Ziele (`tests/web/test_customer_links.py`) |
| 14 (Seiten außer Hilfe) | Geldbegriffe auf allen erreichbaren Kundenseiten, Berichte, Nachanalyse | Keine Treffer (`tests/web/test_customer_links.py`, `tests/web/test_customer_points_pages.py`) |
| 14 (Hilfe) | Freigegebene Hilfeabschnitte DE/EN, Hilfeindex, Chatquellen | Keine Geldbegriffe; Betreiberabschnitte 404 (`tests/unit/test_help_roles.py`, `tests/web/test_customer_help.py`) |
| 16 (zwei Instanzen) | Vertauschte Cookies, Codes und Referenzen zwischen zwei Instanzen mit eigenem Zustand | Nur in der eigenen Instanz wirksam (`tests/web/test_instance_isolation.py`) |
| 15, 17, 19, 20 | Siehe 8.7.10 | Bestanden (`tests/web/test_customer_acceptance.py`) |
| 3 | Eigene Postfächer, Ziele, Themen, Benachrichtigungen in einer Kundensitzung | Nur nach Bestätigung übernommen, Wiederholung ohne Doppelwirkung, Prüfung eigener Verbindungen ohne Betreiberweg (`tests/web/test_customer_acceptance_3.py`, 8.7.15); vor Ort auf `kunde` entfallen |

## Auslieferung

Nur die Betreiber-Testinstanz `kunde` läuft mit 8.7.15 (`mailhelp-production:8.7.15-e63cb15`, seit 27.11.2026,
ausgeliefert mit 8.7.16; Nachweis in [Betrieb](Betrieb.md)), weiter im Ersteinrichtungsmodus. Produktion und Demo laufen
weiter mit 8.5.4 ohne Kundenmodus. Ohne `operator.yaml` und ohne
Bewertungsstand verhält sich 8.7.1 wie 8.6.3; das Sitzungsformat einer selbst betriebenen Instanz ist
unverändert, eine Rückkehr bleibt möglich.
