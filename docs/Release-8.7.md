# Mailhelp 8.7 – Umsetzung und Freigabestand

Stand: 26. November 2026. Version 8.7.6. Grundlage: [Planung 8.7](Planung-8.7.md) und
[Lernen in Punkten](Planung-8.7-Lernen.md).

> **Noch keine Kundenfreischaltung.** 8.7.1 liefert Rollen, zentrale Rechteprüfung und die
> Verbrauchserfassung in Punkten. Die rechtegerechten Kundenansichten aller Einstellungs- und
> Kostenseiten (AP4) fehlen noch. Kundenseiten, die noch nicht umgestellt sind, sperrt die zentrale
> Prüfung für Kundensitzungen vollständig. Laut Plan §9 darf erst nach Abschluss von AP4–AP6 eine
> Instanz für Kunden freigeschaltet werden. Seit 8.7.4 sind die Lernwege in Punkten umgestellt und für
> Kundensitzungen freigegeben; Berichte und Einstellungsseiten folgen.

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
| 3, 14 (übrige Seiten), 15, 17, 19, 20 | – | Offen (AP4–AP6) |

## Auslieferung

Nur die Betreiber-Testinstanz `kunde` läuft mit 8.7.4 (seit 26.11.2026). Produktion und Demo laufen
weiter mit 8.5.4 ohne Kundenmodus. Ohne `operator.yaml` und ohne
Bewertungsstand verhält sich 8.7.1 wie 8.6.3; das Sitzungsformat einer selbst betriebenen Instanz ist
unverändert, eine Rückkehr bleibt möglich.
