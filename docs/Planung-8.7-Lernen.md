# Mailhelp 8.7 – Lernen in Punkten und Kundeninstanz `kunde`

**Stand:** 27. November 2026. **Status:** Abgeschlossen mit 8.7.15. Kundeninstanz `kunde` seit 8.7.3 eingerichtet (§6), Lernen in Punkten (§4) mit 8.7.4, AP4a–AP4c mit 8.7.6–8.7.8, AP5 (Code) mit 8.7.9, AP6 automatisiert mit 8.7.10 und 8.7.15, Prüfstabilität mit 8.7.11–8.7.14. Ersteinrichtung, Abnahme vor Ort und echter Lernlauf auf `kunde` entfallen auf Entscheidung des Betreibers vom 27.11.2026. Ergänzt [Planung 8.7](Planung-8.7.md) (AP4 Lernen,
AP5–AP7) um die Betreiberentscheidungen vom 25. November 2026. Der Hauptplan bleibt unverändert
verbindlich; dieser Plan autorisiert keine Kundenfreischaltung vor Abschluss von AP4–AP6.

## 1. Entscheidungen des Betreibers (25.11.2026)

| Thema | Entscheidung |
| --- | --- |
| Lernfunktionen | Werden für Kunden auf Punkte umgestellt und danach wieder freigegeben |
| Instanz für AP5–AP7 | Neuer, eigener Container, erreichbar über `kunde.inboxstride.de` |
| Umrechnungskurs | `usd_per_eur = 1` |
| Aufschlag | Faktor 10 auf den Einkauf, also `markup_percent = 900` (1 + 900/100 = 10) |
| Notion-Ziele (26.11.2026) | Kunden dürfen für ihre eigenen Zielprofile „Datenquelle wählen“ (`/notion/datenquelle`) und „Eigenschaften zuordnen“ (`/notion/zuordnung`) aufrufen, GET und POST; umgesetzt mit AP4b (8.7.7) |

Folge für die Punkte: 0,01 USD gemeldete Kosten ergeben 0,01 EUR × 10 × 1.000 = **100 Punkte**;
1 USD ergibt 10.000 Punkte. Der Bewertungsstand wird am Host mit
`mailhelp --set-valuation 1 900` angelegt (Bestätigung `BEWERTUNG`). Diese Werte gelten nur für die
Instanz `kunde`. Produktion (`stefan`) und Demo bleiben ohne Kundenmodus und ohne Bewertungsstand.

## 2. Ausgangslage Lernen (Inventur 25.11.2026)

| Weg | Heutige Geld-/Betreiberanteile |
| --- | --- |
| `/lernen` (Übersicht) | Hinweis „Kostenpflichtig“, keine Beträge; Hinweis auf `prompts.yaml` bei fehlendem Schritt |
| `/lernen/postfach` GET | Eingaben „Preisobergrenze USD je Million Tokens“ und „Budget USD“; Schätzung und ungünstigster Fall in Tokens und USD; „Reserviert: … USD“; Liste der konfigurierten Modelle |
| `/lernen/postfach` POST `start` | Verstecktes Feld `selection` enthält `budget_usd` und `usd_per_million_tokens` (Rohgeldwerte im HTML) |
| `/lernen/postfach` nach Abschluss | Link auf `/dienst/neu-laden` (Betreiberfunktion) |
| `runtime/learning_jobs.py` | `LearningSelection.budget_usd`, `usd_per_million_tokens` (float); Startprüfung in USD |
| `runtime/learning_worker.py` | Reservierung je Aufruf in Tokens, Abbruchgrenze `budget_usd` |
| `/lernen/entscheidungen` | Keine Beträge; Texte „kostenpflichtige Analyse“, „höhere Kosten“ |
| `/lernen/vorschlaege`, `/lernen/absender-hinweis*`, `/lernen/hinweis-ausblenden` | Keine Beträge, keine KI-Aufrufe |
| `/themen/lernen` | Altlink auf `/lernen/entscheidungen` |
| `/verbrauch` | Lernschritte erscheinen nur als „Weitere KI-Schritte“ |
| Hilfe DE/EN | Lernabschnitte beschreiben USD-Budget und Preisannahme |

Tatsächlicher Verbrauch der Lernläufe wird bereits seit 8.7.1 im Verbrauchsbestand erfasst, weil alle
OpenRouter-Aufrufe über den gemessenen Client laufen. Es fehlt die Darstellung, die Budgetgrenze in
Punkten und die Rechteprüfung.

## 3. Zielbild

1. Kunden sehen in allen Lernwegen ausschließlich Punkte: Punktegrenze, geschätzter Verbrauch,
   ungünstigster Fall, reservierter und tatsächlicher Verbrauch. Keine USD-, EUR-, Cent-, Preis- oder
   Modellangaben, auch nicht in versteckten Feldern, `title`-Attributen, ARIA-Texten oder JSON.
2. Die Punktegrenze ist eine **Ausführungsgrenze für diesen Lauf**, kein Guthaben (Plan §5.3).
   Der Lauf hält vor dem Aufruf an, der die Grenze überschreiten würde – wie heute beim USD-Budget.
3. Schätzung und Istverbrauch bleiben getrennt beschriftet („Geschätzter Verbrauch“ / „Tatsächlich
   verbraucht“). Ungeklärte Aufrufe werden gezählt, nie als null dargestellt.
4. Betreiber sehen weiterhin das bisherige Formular in USD und zusätzlich die Punkteangaben.
5. Selbst betriebene Instanzen ohne Kundenmodus bleiben unverändert (USD-Formular, gleiches
   Zustandsformat von `web-learning.json`).

## 4. Umsetzung

### 4.1 Preisannahme und Umrechnung (serverseitig)

- Neue Betreibereinstellung `learning_usd_per_million_tokens` in `operator.yaml` (positiver Dezimalwert,
  nur vom Start gelesen, nie von Mailhelp geschrieben). Kunden geben keinen Preis mehr ein.
  Fehlt der Wert oder der Bewertungsstand, zeigt die Kundenansicht „Lernen aus dem Postfach ist vom
  Betreiber noch nicht eingerichtet“ und bietet keinen Start an.
- Neues Modul `usage/budget.py` (Schicht 1, `Decimal`, Kontext aus `usage/points.py`):
  - `points_to_usd(points, valuation)` = `points / 1000 × usd_per_eur / (1 + markup/100)`,
    abgerundet auf 10⁻¹² USD, damit die Grenze nie über dem gewählten Punktewert liegt.
  - `usd_to_points(usd, valuation)` = `points()` aus 8.7.1 (eine Formel, keine zweite Rechnung).
  - `tokens_to_points(tokens, usd_per_million, valuation)` für Schätzungen.
- Die Kundenansicht bindet beim Anzeigen der Schätzung den aktuellen Bewertungsstand (Revision) in das
  Formular. Beim Start wird der Stand erneut gelesen; ist inzwischen eine neue Revision gültig, wird der
  Start abgelehnt und die Schätzung neu angezeigt („Bewertung geändert, bitte Schätzung prüfen“).

### 4.2 Zustand und Rückwärtsverträglichkeit

- `LearningSelection` behält `budget_usd` und `usd_per_million_tokens` als interne Grenzwerte; der
  Worker rechnet unverändert in USD/Tokens. Damit bleiben Worker, Wiederanlauf und Neustartpfad gleich.
- Die Kundenangaben (Punktegrenze als Dezimaltext, Bewertungsrevision) werden **nicht** in
  `web-learning.json` gespeichert, weil `extra="forbid"` eine Rückkehr auf 8.7.1 sonst unmöglich macht.
  Sie liegen in einem eigenen Eintrag `web-learning-points` (Generation, Punktegrenze, Revision) im
  selben Store und werden beim Generationswechsel ersetzt.
- Das versteckte Formularfeld enthält für Kunden nur `mailbox`, `folders`, `count`, `points`
  und `revision`; der Server rechnet die USD-Grenze beim Start selbst. Ein vom Kunden
  eingeschleustes `budget_usd` oder `usd_per_million_tokens` führt zur vollständigen Ablehnung.
- Idempotenzschlüssel, Version, CSRF und Sitzungsprüfung beim Start und vor jedem Aufruf bleiben
  unverändert (Worker prüft `active(actor)` bereits je Aufruf).

### 4.3 Ansichten

- Gemeinsame rollenabhängige Präsentation `web/consumption.py`: `estimate_text(...)`,
  `reserved_text(...)`, `actual_text(...)`. Für Betreiber USD plus Punkte, für Kunden nur Punkte.
  Keine Einzelersetzung von Währungssymbolen (Plan §7.2).
- `/lernen/postfach` für Kunden:
  - Abschnitt 3 heißt „Punktegrenze“, Feld „Punktegrenze für diesen Lauf“ (1–10.000.000, Schritt 1).
  - Schätzung: „Geschätzter Verbrauch: etwa X Punkte; ungünstigster Fall: höchstens Y Punkte.“
  - Zu niedrige Grenze: „Die Punktegrenze reicht für die Schätzung nicht aus. Bitte mindestens X Punkte
    angeben.“
  - Laufend: „Reserviert: X Punkte der Punktegrenze.“ plus „Tatsächlich verbraucht: Y Punkte“
    (aus dem Verbrauchsbestand: Lernschritte ab Startzeitpunkt, Zweck `customer`), bei ungeklärten
    Aufrufen „… davon N Aufrufe noch nicht bewertbar“.
  - Modellliste und Hinweis auf Modellpreise entfallen; Tokenangaben entfallen.
  - Nach Abschluss kein Link auf `/dienst/neu-laden`. Die Übernahme lädt die Konfiguration wie das
    Speichern von Themen über den vorhandenen Konfigurationsdienst neu; die Seite meldet das Ergebnis.
- `/lernen` und `/lernen/entscheidungen`: Hinweis „Verbraucht Punkte“ statt „Kostenpflichtig“,
  „Mehr Belege, mehr Punkte“ statt „höhere Kosten“. Fehlender Schritt `decision_rule_learning` lautet für
  Kunden „vom Betreiber noch nicht eingerichtet“ ohne Verweis auf `prompts.yaml`.
- `/verbrauch`: Bezeichnungen für `learning_classification`, `learning_abstraction`,
  `decision_rule_learning`, Nachanalyse und Hilfschat in `STAGE_LABELS` ergänzen.
- DE/EN: alle neuen Texte im EN-Katalog; Hilfeabschnitte „Aus dem Postfach lernen“ und „Aus
  Entscheidungen lernen“ erhalten eine Kundenfassung in Punkten (rollenabhängige Hilfe aus AP4).

### 4.4 Rechte

- `web/permissions.py` gibt für Kunden frei: `GET /lernen`, `GET /api/lernen/uebersicht`,
  `GET POST /lernen/postfach`, `GET /api/lernen`, `GET POST /lernen/entscheidungen`,
  `GET /lernen/vorschlaege`, `GET /lernen/absender-hinweis`, `POST /lernen/absender-hinweis/*`,
  `POST /lernen/hinweis-ausblenden`, `GET POST /themen/lernen`.
- Der Lernlauf übernimmt Themen, Ausschlussthemen, Absenderregeln und Abrufordner. Die Übernahme prüft
  vor dem Schreiben mit `ConfigurationService.permitted`, dass nur Kundenfelder betroffen sind
  (`topics.yaml`, `irrelevant_topics.yaml`, `irrelevant-senders.json`, Ordner der eigenen Postfächer);
  Abweichungen werden vollständig abgelehnt.
- Freigegeben wird erst, wenn alle Tests aus §5 bestehen. Bis dahin bleibt die Sperre aus 8.7.1.

### 4.5 Preisrahmen aus den Produktionslogs (26.11.2026)

Grundlage: `/opt/mailhelp/runtime/logs/llm/requests.jsonl*` der Produktion vom 13. bis 25.11.2026,
293 Antworten mit gemeldeten Kosten (`reported_cost`, `token_usage.cost_details`), zusammen
1,15 Mio. Eingabe- und 0,38 Mio. Ausgabetokens für 0,46 USD. Lernläufe kamen im Zeitraum nicht vor.
Alle Lernschritte (`relevance`, `learning_classification`, `learning_abstraction`) nutzen das
Standardmodell `deepseek/deepseek-v4.1-flash`.

| Größe (deepseek-v4.1-flash) | Min. | Median | Max. |
| --- | --- | --- | --- |
| Eingabe ohne Cache, USD je Mio. Tokens | 0,05 | 0,13 | 0,30 |
| Ausgabe (inkl. Reasoning), USD je Mio. Tokens | 0,42 | 0,65 | 1,20 |
| Mischpreis je Aufruf, alle Schritte | 0,02 | – | 0,99 |
| Mischpreis `relevance` (Median / 90 % / Max.) | – | 0,28 / 0,37 | 0,47 |
| Mischpreis `summary` (ähnlich `learning_classification`) | – | 0,33 / 0,54 | 0,85 |
| Mischpreis über alle Aufrufe | | 0,30 | |

Die Lerngrenze rechnet gemeldete Gesamttokens × Preisannahme. Nur eine Annahme mindestens in Höhe
des teuersten Tokenpreises garantiert, dass der tatsächliche Verbrauch die Punktegrenze nie
übersteigt. **Festlegung für `kunde`: `learning_usd_per_million_tokens: "1.2"`** (höchster gemessener
Ausgabepreis). Folge: Schätzung und Reservierung liegen typischerweise etwa beim Vierfachen des
tatsächlichen Verbrauchs (Mischpreis 0,30); angezeigt und abgerechnet wird der tatsächliche Verbrauch.
Beispiel 100 Mails: Schätzung 100 × 4 × 5.000 = 2 Mio. Tokens → 2,40 USD → 24.000 Punkte; erwarteter
Istverbrauch etwa 0,60 USD → 6.000 Punkte. Ein knapperer Wert (0,6 = 90-%-Wert der ausgabelastigen
Schritte) würde die Schätzung halbieren, kann die Grenze bei ausgabelastigen Aufrufen aber um bis zu
das Doppelte überschreiten und ist deshalb verworfen. Bei einem Modellwechsel der Lernschritte ist der
Wert neu festzulegen (z. B. `google/gemini-3.5-flash-lite`: Ausgabe 2,50 USD je Mio. Tokens).

## 5. Tests

| Bereich | Fälle |
| --- | --- |
| Rechnung (`tests/usage`) | 100 Punkte bei Kurs 1/Aufschlag 900 % ↔ 0,01 USD; Rundung der Grenze nach unten; Grenzwerte 1 und 10.000.000 Punkte; ungültige Eingaben (0, negativ, NaN, Text) |
| Kundenansicht | Keine Treffer für `USD`, `EUR`, `€`, `Cent`, `usd_`, Preis-/Modellnamen im HTML, in versteckten Feldern und im JSON von `/lernen*`, `/api/lernen*` (Abnahme 14) |
| Manipulation | Eingeschleuste USD-Felder, fremde Revision, abgelaufene Sitzung, wiederholter Idempotenzschlüssel |
| Bewertungswechsel | Neue Revision zwischen Schätzung und Start → Ablehnung; laufender Lauf behält seine Grenze |
| Lauf | Anhalten vor Überschreitung der Punktegrenze; Fortsetzen; Neustart; Istverbrauch inklusive ungeklärter Aufrufe |
| Betreiber/Selbstbetrieb | USD-Formular unverändert; `web-learning.json` byte-gleiches Format ohne Kundenmodus |
| Übernahme | Nur Kundenfelder; gemischte Änderung vollständig abgelehnt; Konfiguration neu geladen ohne Betreiberlink |
| Browser (`ui_tests`) | Kundensitzung: Lernübersicht, Schätzung, Start, Pause, Prüfung, Übernahme; Smartphone und Tastatur |

Pflichtprüfungen wie im Hauptplan: 100 % Zeilen-/Branch-Abdeckung, `python -m devtools.check full
--workers 12`, danach Browsersuite `-n 6`, nie gleichzeitig; Ruff und mypy ohne Befunde.

## 6. Kundeninstanz `kunde` für AP5–AP7

### 6.1 Aufbau

| Bestandteil | Festlegung |
| --- | --- |
| Hostname | `kunde.inboxstride.de` (A-Eintrag zeigt bereits auf den Server, geprüft 25.11.2026) |
| Verzeichnis | `/opt/mailhelp-kunde/` mit `compose.yaml`, `runtime/` (UID/GID 65532, 0700) |
| Compose-Projekt | `mailhelp-kunde`, eigener Container, eigenes Bridge-Netz `mailhelp-kunde` |
| Port | `127.0.0.1:8766` → Container `8765`; nur nginx erreicht ihn |
| Image | Jeweils geprüfte 8.7.x-Version; Produktion und Demo werden dabei nicht umgestellt |
| Modus | `operator.yaml` mit `customer_mode: true`, `instance: kunde`, seit 8.7.4 `learning_usd_per_million_tokens: "1.2"` (§4.5) |
| Bewertung | Revision 1: `usd_per_eur = 1`, `markup_percent = 900` |
| Geheimnisse | Eigene `runtime/.env`; OpenRouter-Schlüssel des Betreibers wird vom Betreiber selbst über die Ersteinrichtung eingetragen, nicht aus der Produktion kopiert |
| Anmeldedienst | Zunächst ohne `inboxstride-auth`-Netz; Google-Anbindung erst nach `register kunde` und eigenem mTLS-Zertifikat |
| Grenzen | `mem_limit 512m`, `cpus 0.5`, `pids_limit 256`, `no-new-privileges`, `cap_drop ALL` |
| TLS/nginx | Sites `mailhelp-kunde-http`/`-https` nach Demo-Vorbild, Zertifikat per certbot-Webroot, Erneuerung `renew-mailhelp-kunde` |
| Sicherung | `/opt/mailhelp-kunde` in die tägliche Dropbox-Sicherung aufnehmen (enthält Rollen, Bewertungsstände, `usage/attempts.jsonl`) |

### 6.2 Ablauf

1. Release des geprüften Commits bauen (`mailhelp-production:<Version>-<Commit>`), Hostpakete gemäß
   Serverhandbuch aktualisieren, Reboot-Bedarf prüfen.
2. Verzeichnis, `operator.yaml` und Compose anlegen, `docker compose config --quiet` prüfen.
3. Bewertungsstand mit `docker compose run --rm … --set-valuation 1 900` anlegen (vor dem ersten
   KI-Aufruf, damit kein Aufruf unbewertet bleibt).
4. Container starten (Ersteinrichtungsmodus). nginx-HTTP-Site für ACME, Zertifikat ausstellen,
   HTTPS-Site aktivieren, `nginx -t`, reload; Prüfung mit `Host: kunde.inboxstride.de`.
5. Der Betreiber schließt die Ersteinrichtung mit dem Code aus `docker logs` ab und trägt dabei den
   OpenRouter-Schlüssel ein. Nach dem Neustart ist der Kundenmodus aktiv; rollenlose Sitzungen der
   Einrichtung werden widerrufen.
6. Betreiberzugang per `docker exec … mailhelp --pair --operator`; erster Kundenzugang per
   `mailhelp --pair` (Kundenrolle).
7. Synthetischer Durchlauf (AP5/AP6): Postfach, Ziele, Themen, Benachrichtigungen, Verbrauch,
   Lernen; Isolationsprüfung gegen die Demo als zweite Instanz (vertauschte Cookies/Referenzen).
8. Serverhandbuch, Betrieb, Vorlage `ops/server/kunde.compose.example.yaml`, nginx-Vorlage,
   Backup-Konfigurationsvorlage und `/opt/mailhelp/server-docs` nachführen (AP7).

Rückkehr: Container `mailhelp-kunde` stoppen und nginx-Site deaktivieren; Produktion, Demo und Auth sind
nicht berührt. Daten in `/opt/mailhelp-kunde/runtime` bleiben erhalten. Eine Rückkehr auf eine Version
ohne Rollenschutz ist nur mit zuvor gesperrter nginx-Site zulässig (Plan §8).

### 6.3 Grenzen

- Die Instanz ist bis zum Abschluss von AP4–AP6 eine Betreiber-Testinstanz mit synthetischen Daten,
  keine Freischaltung für einen echten Kunden.
- Speicher und Platte des Servers sind knapp (25.11.2026: rund 3 GB frei, 1,8 GB RAM). Vor dem Bau
  alte, nicht mehr als Rückkehrpunkt benötigte Images nur nach Rückfrage entfernen.

## 7. Reihenfolge

| Schritt | Inhalt |
| --- | --- |
| 8.7.2 | Dieser Plan; Bugfix: `--set-valuation` funktioniert schon vor der Ersteinrichtung (vorher Abbruch ohne `config.yaml`); Compose-Vorlage `ops/server/kunde.compose.example.yaml` |
| 8.7.3 | Kundeninstanz `kunde` mit 8.7.2 im Ersteinrichtungsmodus, Bewertungsstand, nginx/TLS, Sicherung; Serverhandbuch und Betrieb nach erfolgreicher Prüfung |
| 8.7.4 | Lernen in Punkten (§4) mit Tests, Freigabe der Lernwege für Kunden |
| 8.7.5 | Auslieferung von 8.7.4 auf `kunde` mit Preisannahme 1,2 (§4.5); Arbeitspakete §8 |
| 8.7.6 ff. | Arbeitspakete AP4a–AP6 aus §8 in dieser Reihenfolge |

## 8. Weitere Arbeitspakete (Stand 26.11.2026)

Aus den nach 8.7.4 offenen Punkten. Jedes Paket ist eine eigene Patch-Version mit Tests,
Vollprüfung, Browsersuite und Dokumentation; Auslieferung auf `kunde` jeweils nach Freigabe des
Betreibers. Produktion und Demo bleiben bis AP6 unverändert.

| Paket | Version | Inhalt | Fertig, wenn |
| --- | --- | --- | --- |
| AP4a – Navigation und Links nach Rolle (umgesetzt in 8.7.6) | 8.7.6 | Navigation (Seitenleiste, Tab-Leiste, „Mehr“) zeigt Kunden nur Ziele, die `customer_may("GET", …)` erlaubt (heute sichtbar, aber 403: Status, Auswertung, Berichte, Einstellungen, Vorschlagsabgleich); „Verbrauch“ in der Navigation für Kunden. Eigene Einstiegsseite `/einstellungen` für Kunden nur mit ihren Bereichen (Postfächer, Zielprofile, Absender, Benachrichtigungen, Themen, Web-Passwort, Geräte). Links innerhalb erlaubter Seiten auf Betreiberwege (`/diagnose`, `/einstellungen/zugangsdaten`, `/einstellungen/iserv`, `/einrichtung`, `/dienst/neu-laden`, `/einstellungen/neustarten`, `/auswertung…`) für Kunden ausblenden oder ersetzen. Bugfix: Enter in einem Feld des Lernformulars löst „Schätzung anzeigen“ aus statt „Ordner laden“ (Regressionstest) | Automatischer Linkprüfer: jede für Kunden erlaubte Seite in einer Kundensitzung abrufen, jeder interne Link und jedes Formularziel ist für Kunden erlaubt; Navigation für Betreiber unverändert; Smartphone und Tastatur |
| AP4b – Kostenhinweise in Punkten (umgesetzt in 8.7.7) | 8.7.7 | Nachanalyse (`/mail/…/nachanalyse`: „kostenpflichtige Modellaufrufe“, Verweis auf die Auswertung), Tätigkeitsberichte (`/berichte`: „kostenpflichtig starten“, Kostenschätzung `activity/costs.py` in USD/EUR Strom, xlsx-Export) und übrige Texte „Kosten“/„kostenpflichtig“ in Kundenwegen rollenabhängig auf „Verbraucht Punkte“ bzw. Schätzung in Punkten umstellen; danach `/berichte` für Kunden freigeben (Rechte-Matrix: nur eigene Postfächer) Notion-Schritte für Kunden (Entscheidung §1): `/notion/datenquelle` und `/notion/zuordnung` (GET/POST) freigeben; der Entwurf ändert nur `targets.*`/`target_profiles` des gewählten Profils; nach dem Speichern führt die Seite Kunden zu „Zielprofile“ statt zur Betreiberseite `/einrichtung`; Links darauf erscheinen wieder für Kunden | Prüfung aller Kundenantworten (HTML, JSON, xlsx) ohne `USD`, `EUR`, `€`, `Cent`, `kostenpflichtig`, Modell- und Preisangaben (Abnahme 14 vollständig); Notion-Auswahl und -Zuordnung in einer Kundensitzung mit simuliertem Notion-Dienst bis zum gespeicherten Entwurf, fremdes Profil und Betreiberfelder abgelehnt |
| AP4c – Hilfe und Suche nach Rolle (umgesetzt in 8.7.8) | 8.7.8 | Hilfe DE/EN mit Kundenfassung (keine Betreiberabschnitte zu Servern, Zugangsdaten, Prompts, Kosten in USD); Suche und Hilfschat-Kontext nur aus für Kunden freigegebenen Abschnitten; Telegram-/Push-/Briefing-Texte ohne Geldwerte | Hilfeindex je Rolle; Hilfschat zitiert für Kunden keine Betreiberabschnitte; Kanaltexte geprüft |
| AP5 – Einrichtungsprüfung und Kundenbetrieb (Code in 8.7.9; Ersteinrichtung, Kopplung und synthetisches Postfach entfallen, Betreiberentscheidung 27.11.2026) | 8.7.9 | Betreiber schließt die Ersteinrichtung von `kunde` ab (eigener OpenRouter-Schlüssel), Betreiber- und Kundenkopplung, synthetisches Postfach; Einrichtungsprüfung zeigt Kunden fehlende Betreiberschritte (Preisannahme, Bewertungsstand) verständlich; Kundenhinweise; zweite Instanz für Isolationsprüfung (vertauschte Cookies, Referenzen, Codes); Sicherung und Rückkehr von `kunde` dokumentiert | Zwei Instanzen getrennt bedienbar; Betreiberzugriff jederzeit möglich |
| AP6 – Abnahme (automatisiert: 15, 17, 19, 20 in 8.7.10, 3 in 8.7.15; Abnahme vor Ort und echter Lernlauf auf `kunde` entfallen) | 8.7.10 | Abnahmeszenarien aus [Planung 8.7](Planung-8.7.md) §10 auf `kunde` mit synthetischen Daten, darunter ein echter Lernlauf in Punkten (Abgleich Istverbrauch gegen OpenRouter-Kosten und Preisannahme §4.5) | Alle Abnahmepunkte bestanden; Ergebnis in Release 8.7 |
| Querschnitt – Prüfstabilität (8.7.11: Demo-Start und -Export unter Windows, Live-Suche im Browser gemessen, CI-Annotationen; 8.7.12: Ursachen der roten CI-Jobs behoben – CRLF in statischen Dateien, Systemsprache der Browsertests, Linux-Schrift, Linux-Abdeckung, paralleler Lasttest; 8.7.13: hängende Linux-Browsersuite – unbegrenzte Abdeckungsabfrage, als wahr gezählte asynchrone Wartebedingungen, Service-Worker-Wechsel, Zeitlimit des CI-Schritts; 8.7.14: eigene Lastgrenze auf GitHub-Runnern) | parallel | Zeitabhängige Tests, die nur unter Last scheitern (e2e-Durchlauf, `demo_visitors` mit fehlender Abdeckung von `demo_visitors.py:114`, Themeneditor schmal, Live-Suche 300 ms), deterministisch machen; Ursache der roten CI-Jobs `tests`/`ui-tests` klären (Logs benötigen `gh auth login`) | Zwei Vollprüfungen und eine Browsersuite hintereinander ohne Wiederholung grün |

AP7 (Dokumentation, Serverhandbuch, Serverkopie) läuft in jedem Paket mit.
