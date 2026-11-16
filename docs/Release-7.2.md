# Mailhelp 7.2 – Notion und Google Tasks als Aufgabenziele

Geprüft für Mailhelp 7.2.

Umsetzung von [Planung 7.2](Planung-7.2.md). Zwischenstand: Google Tasks ist ab 7.2.1 als
Aufgabenziel nutzbar; Notion folgt. Der Plan ist erst mit der Abnahme in 7.2.5 erfüllt.

## 7.2.1 – Google Tasks, Fähigkeit „Entfernen“, Anmelderechte (P1, P2)

**Bestandsaufnahme nach 7.1 (P1).** Aufgabenziele sind `TargetWriter` mit `check_access`,
`reconcile`, `prepare`, Lesevertrag (`account_binding`, `expected_facts`, `read_entry`) und
`fetch_active_tasks`. Das Lesemodell `TodoistTaskResponse` wird schon von Microsoft To Do und CalDAV
als neutrales Aufgabenmodell genutzt; es bleibt, ein Umbenennen brächte nur Umbau ohne Wirkung.
Die Konfiguration bleibt abwärtskompatibel: Neue Felder haben Standardwerte, bestehende Dateien
laden unverändert, und die Analyse-Fingerabdrücke aller früheren Versionen bleiben gleich
(`google_tasks_list` und `timeouts.google_tasks` zählen nicht zur Analyse).

**Fähigkeit statt Anbietername.** `TargetWriter.supports_remove` sagt, ob „Wieder entfernen“
angeboten wird. Web, Telegram und der Befehl selbst fragen nur diese Fähigkeit ab. Nur Kalender und
Todoist entfernen sicher. Google Tasks bietet keine Bedingung, die ein Löschen gegen eine Änderung
nach dem letzten Lesen schützt. **Fehlerkorrektur:** Bei Microsoft To Do, CalDAV-Aufgaben und
Apple Erinnerungen wurde „Wieder entfernen“ bisher angezeigt, und der Befehl scheiterte intern mit
`NotImplementedError`. Jetzt fehlt die Aktion, und ein direkter Befehl wird mit Hinweis abgelehnt
(Regressionstests in `tests/external/test_providers.py`, `tests/review/test_remove_created.py`,
`tests/web/test_remove_created_web.py`, `tests/release/test_deployment_edges.py`).

**Google Tasks (P2)** (`external/google_tasks.py`):

- Ziel `targets.task_provider: google_tasks` mit `targets.google_tasks_list` (Listen-ID oder
  `@default`), ebenso in Zielprofilen. Zeitlimits unter `timeouts.google_tasks`.
- Anlage mit Titel, Notizen und Status „offen“. Der Vorgangsschlüssel `[mailhelp:…]` steht in den
  Notizen. Die Kontobindung ist die tatsächliche Listen-ID, nie der Alias `@default`.
- Datum: Google speichert nur einen Tag. Mailhelp schreibt den bestätigten Tag in der
  konfigurierten Zeitzone, eine Zeitumstellung verschiebt ihn nicht. Eine genaue Frist steht
  zusätzlich lesbar im Text. Ohne Frist bleibt das Datum leer, es gibt kein erfundenes „heute“.
- Längen: Titel (höchstens 500) und Beschreibung (höchstens 4 000) eines Vorschlags liegen mit
  Fristzeile und Schlüssel sicher unter Googles Grenzen (1 024 und 8 192). Gekürzt wird nie; ein
  Test hält das fest.
- Abgleich: alle Seiten der Liste einschließlich erledigter, ausgeblendeter und gelöschter
  Aufgaben. Ein doppelt gefundener Schlüssel oder eine zu lange Liste (mehr als 100 Seiten) bleiben
  unklar; es folgt kein zweiter POST. Ein unklarer POST (Zeitüberschreitung, 5xx) wird nie blind
  wiederholt.
- Fehler nach strukturiertem Grund, nie nach Meldungstext: API nicht aktiviert, fehlendes Recht,
  Liste fehlt, Anmeldung abgelehnt. Links übernimmt Mailhelp nur als `https`-Adresse unter
  `google.com`.
- Dublettenprüfung und Tagesübersicht lesen offene Aufgaben über Seiten; ein Lesefehler ist mit
  `strict` nie eine leere Liste.

**Anmelderechte.** Eine Google-Anmeldung dient Kalender und Google Tasks eines Profils gemeinsam.
Sie fordert genau die Rechte an, die das Profil nutzt (`google_scopes`): Kalender, Google Tasks
(`https://www.googleapis.com/auth/tasks`) oder beides. Mit `include_granted_scopes` behält eine neue
Anmeldung früher erteilte Rechte. Die Rechte gehören zur Bindung der Web-Anmeldung; ändert sich das
Ziel währenddessen, wird die Anmeldung abgelehnt. `mailhelp --google-auth` lehnt ein Profil ohne
Google-Ziel ab, statt Rechte anzufordern, die nichts nutzt.

**Offen für die nächsten Patches** (Stand 7.2.1). Notion (7.2.3, 7.2.4); Abnahme mit echtem Testkonto (7.2.5).

Prüfung 7.2.1: 5 579 Python-Tests mit 100 % Zeilen- und Branch-Abdeckung (ein Dokumentationszitat
danach korrigiert, die betroffenen Prüfungen bestehen). Browser 928 bestanden; die Auswahl des
Aufgabendienstes zeigt jetzt fünf Einträge (Test nennt sie namentlich). Einmal scheiterte unter Last
`test_charts_zoom_and_show_details_with_pointer_keyboard_and_touch[desktop]`; er bestand danach
dreimal einzeln.

## 7.2.2 – Google-Tasks-Listenauswahl und Fristdarstellung

Die Ersteinrichtung und die Zielprofilverwaltung verlinken die authentifizierte Auswahl unter
`/auth/google/aufgabenlisten?profile=…`. Sie liest alle Seiten mit den gespeicherten Zugangsdaten
des jeweiligen Profils. Fehlende Leserechte, ungültige Antworten, wiederholte Seitentokens oder
mehr als 20 Seiten führen zu einem Fehler. Eine unvollständige Auswahl wird verworfen.

Die Auswahl speichert einen Einrichtungsentwurf mit Sitzung, CSRF, Zugangsdatenrevision,
Entwurfsversion und Idempotenzschlüssel. Beim Speichern wird die Verfügbarkeit der Liste erneut
gelesen. Webkarten und Telegram zeigen vor der Bestätigung den Hinweis zur Datumsgenauigkeit.

Automatisierte Prüfungen laufen mit simulierten Google-Antworten und synthetischen Zugangsdaten.
Prüfung 7.2.2: 5 593 Python-Tests mit 100 % Zeilen- und Branch-Abdeckung; Browser 935 bestanden
ohne Fehler.

## 7.2.3 – Notion mit interner Verbindung (P3)

**API-Vertrag** am 16. November 2026 gegen developers.notion.com geprüft: `Notion-Version`
`2026-03-11` (fest gesetzt), Anlage mit `parent.data_source_id` über `POST /v1/pages`, Abfrage über
`POST /v1/data_sources/{id}/query` mit `start_cursor`, `has_more` und `request_status`, Fehler mit
strukturiertem `code`. Eine Zusage zu Idempotenz oder atomaren Änderungsbedingungen gibt es nicht;
Mailhelp nimmt keine an.

**Konfiguration.** `task_provider: notion` mit `notion_data_source_id`, `notion_properties`
(Eigenschafts-IDs für Titel, Beschreibung, Frist, Quelle, Vorgang und optional Status),
`notion_open_status` und `notion_done_statuses`; ebenso je Zielprofil. Geheimnis `NOTION_TOKEN`
einer internen Verbindung (weitere Profile `NOTION_<n>_TOKEN`). Zeitlimits `timeouts.notion`. Alle
neuen Felder zählen nicht zur Analyse; die Fingerabdrücke früherer Versionen bleiben gleich.

**Adapter** (`external/notion.py`):

- Eigenschaften über IDs; ein umbenanntes Feld passt weiter. Fehlende Eigenschaft, falscher Typ
  oder fehlende Statusoption sperren neue Anlagen mit konkreter Meldung. Das Schema wird bei
  **Zugriffe prüfen** und erneut direkt vor jeder Anlage gelesen.
- Eine Seite je Aufgabe in einem Aufruf: Titel, Beschreibung (in Stücken zu 2 000 Zeichen),
  Vorgangsschlüssel, Frist (Datum oder Zeitpunkt mit Versatz), Quelle nur als `https`-Link, Status
  „offen“ (Status, Auswahl oder Kontrollkästchen aus).
- Abgleich nach Vorgangsschlüssel in offenen und archivierten Seiten über alle Ergebnisseiten.
  Doppelter Treffer, unvollständige Abfrage oder mehr als 100 Ergebnisseiten bleiben unklar. Die
  Antwort 529 (überlastet) gilt wie 503: Lesen wird wiederholt, eine Anlage bleibt unklar und wird
  nie blind wiederholt.
- Lesen zur Prüfung: Eine Seite im Papierkorb gilt als entfernt; erledigt nach Statusoption oder
  Kontrollkästchen. Offene Aufgaben für Dublettenprüfung und Tagesübersicht ohne erledigte und
  gelöschte Seiten. Ohne Statusfeld sind erledigte Seiten nicht erkennbar (`limitation`).
- Links nur als `https`-Adresse unter `notion.so`. Kein Entfernen (`supports_remove` falsch).

**Offen.** Auswahl von Datenquelle und Eigenschaften in der Oberfläche, Notion-OAuth mit
Token-Erneuerung und Hinweis auf das fehlende Statusfeld in der Vorschau (7.2.4); Demo und
Abnahme mit echtem Testkonto (7.2.5). Bis dahin wird Notion über `config.yaml` eingerichtet.

Prüfung 7.2.3: 5 622 Python-Tests mit 100 % Zeilen- und Branch-Abdeckung (danach drei nicht
bedienbare Begriffe in der Anleitung entfettet; die betroffenen Prüfungen bestehen). Browser 932
bestanden. Zwei Polling-Tests nach abgelaufener Sitzung
(`test_an_expired_session_while_a_card_polls_returns_to_sign_in`,
`test_expired_status_poll_redirects_without_reposting`) und ein Push-Test scheiterten gelegentlich mit
einem Zeitlimit beim Seitenaufruf. Dasselbe tritt auf dem Stand 7.2.2 ohne die Notion-Änderungen
auf (einer von vier Läufen); es ist ein bestehendes, lastabhängiges Testverhalten und bleibt als
offener Punkt vermerkt.

## 7.2.4 – Notion-Datenquelle und Eigenschaften in der Oberfläche

- **Einstellungen → Zielprofile** verlinkt je Profil **Notion-Datenquelle auswählen** und
  **Notion-Eigenschaften zuordnen** (`/notion/datenquelle`, `/notion/zuordnung`).
- Die Datenquellenliste kommt aus der Notion-Suche über alle Seiten (höchstens 20); eine
  unvollständige oder fehlerhafte Liste wird abgelehnt, nicht teilweise angeboten. Ohne Token oder
  Freigabe erklärt die Seite, was zu prüfen ist.
- Die Zuordnung bietet je Feld nur Eigenschaften des passenden Typs und die Optionen vorhandener
  Status- und Auswahlfelder. Beim Speichern liest Mailhelp das Schema neu und prüft mit derselben
  Regel wie vor jeder Anlage (`check_mapping`): IDs vorhanden, Typen passend, Optionen gehören zum
  gewählten Statusfeld. Ohne Statusfeld werden Statusoptionen verworfen.
- Gespeichert wird ein Einstellungsentwurf (Sitzung, CSRF, Entwurfsversion, Idempotenzschlüssel);
  übernommen wird er wie jede Einstellungsänderung. In Notion wird nichts angelegt oder geändert.
- Notion erscheint in der Auswahl des Aufgabendienstes unter Einstellungen. Die Ersteinrichtung
  bietet Notion nicht an, weil dort keine Zuordnung möglich ist.

**Offen.** Notion-OAuth mit rotierenden Tokens (7.2.5); Demo, Hinweise und Abnahme mit echtem
Testkonto (7.2.6).

Prüfung 7.2.4: 5 632 Python-Tests mit 100 % Zeilen- und Branch-Abdeckung. Browser 930 bestanden;
die Auswahl des Aufgabendienstes nennt jetzt Notion als sechsten Eintrag (Test angepasst, besteht).
Unter Last scheiterten der bekannte Polling-Test nach abgelaufener Sitzung und der Zeittest der
Live-Suche; beide bestanden danach zweimal einzeln.

## 7.2.5 – Notion-OAuth mit rotierenden Tokens (P4)

- Öffentliche Notion-Verbindung als Alternative zum festen Token: `NOTION_CLIENT_ID`,
  `NOTION_CLIENT_SECRET` und `web.notion_redirect_uri` (HTTPS oder localhost, Pfad
  `/auth/notion/callback`). **Notion verbinden** unter Zielprofile startet die Anmeldung
  (`/auth/notion/start`) mit an Sitzung, Profil und Zugangsdatenrevision gebundenem Auftrag; die
  Rückkehr (`/auth/notion/callback`) tauscht den Code genau einmal. Fehlt beim Rücksprung die
  Sitzung, schließt erst ein Klick im ursprünglichen Browser ab.
- Der Grant (Zugriffs- und Refresh-Token, Arbeitsbereich, Bot) liegt in `notion-token.json`
  (`notion-token-<n>.json`) neben `.env`, nur für den Eigentümer lesbar, nie in `.env`, im
  Auftragszustand oder in Logs. Notion rotiert den Refresh-Token bei jeder Erneuerung; das neue Paar
  wird sofort gespeichert.
- Erneuert wird erst, nachdem Notion einen Zugriff abgelehnt hat. Vorher liest Mailhelp die Datei
  neu: Hat ein anderer Ablauf das Paar inzwischen rotiert, wird dieses genommen statt einen
  verbrauchten Refresh-Token zu senden. Eine Erneuerung für einen anderen Arbeitsbereich oder Bot
  wird abgelehnt. Fehlerantworten werden nie verkettet, damit kein Token in Meldungen gelangt.
- Ohne festes Token nutzen Schreibziel und Auswahlseiten die Anmeldung. Fehlt beides, nennt
  **Zugriffe prüfen** den Weg; beim Start wird für Notion kein Geheimnis mehr zwingend verlangt.
- Der gespeicherte Auftragszustand (`OAuthJobs`) kennt den zusätzlichen Anbieterwert `notion`;
  bestehende Dateien laden unverändert (Schema-Snapshot neu geschrieben).

Prüfung 7.2.5: Der erste Lauf fand eine nicht abgedeckte Zeile (Erneuerung nach Ablehnung mit
OAuth-Anmeldung); mit dem ergänzten Test 5 649 Python-Tests und 100 % Zeilen- und Branch-Abdeckung.
Browser 931 bestanden; die bekannten Polling-Tests nach abgelaufener Sitzung und ein Push-Test
scheiterten unter Last und bestanden danach zweimal einzeln.

## 7.2.6 – Browserprüfung, Korrekturen und Abnahme (P5)

- **Fehlerkorrektur:** Nach einer Auswahl (Google-Kalender, Google-Tasks-Liste, Notion) leitete
  die eingerichtete Anwendung auf `/einrichtung/start` weiter. Diese Adresse gibt es nur in der
  Ersteinrichtung; man landete auf einer 404-Seite. Jetzt führt die Auswahl im Betrieb zum Entwurf
  unter `/einrichtung`, in der Ersteinrichtung weiter zu `/einrichtung/start`; ebenso der Verweis
  „Zur Einrichtung“ der Anmeldestatusseite. Regressionstests in
  `tests/profiles/test_browser_accounts.py`, `tests/profiles/test_notion_selection.py` und
  `tests/web/test_initial_web.py`.
- **Browserprüfung Notion** (`ui_tests/test_ui_notion.py`): Datenquelle wählen, Eigenschaften
  zuordnen und als Entwurf speichern auf Desktop, Telefon und schmaler Ansicht in Chrome und auf
  einem iPhone-Profil in WebKit; nur passende Eigenschaftstypen werden angeboten, ein manipulierter
  Wert wird vom Server abgelehnt; Barrierefreiheitsprüfung der Zuordnungsseite.
- **Wacklige Browsertests behoben:** Die Polling-Tests nach abgelaufener Sitzung warteten beim
  Seitenaufruf auf `DOMContentLoaded` bzw. `load`, obwohl die Seite sofort zu `/anmelden`
  weiterleitet; unter Last kam die Weiterleitung zuerst, und der Aufruf lief in sein Zeitlimit.
  Sie warten jetzt nur auf die Antwort (`commit`) und dann auf die Weiterleitung. Der Push-Test
  wartete nach dem dritten Klick auf einen Text, der schon vom vorherigen Klick dastand; er wartet
  jetzt auf die Wirkung des Klicks. Die Anwendung war in keinem Fall betroffen.

### Abnahme 7.2

| Schritt | Nachweis | Ergebnis |
| :--- | :--- | :--- |
| P1 | Verträge, Fähigkeiten, neutrales Lesemodell, Konfiguration ohne Migration | erfüllt (7.2.1) |
| P2 | Google Tasks: Adapter, Rechte, Listenwahl, Datum, Aufträge, Abgleich | erfüllt (7.2.1, 7.2.2) |
| P3 | Notion: Adapter, interne Verbindung, Datenquelle, Zuordnung, Anlage, Abgleich | erfüllt (7.2.3, 7.2.4) |
| P4 | Notion-OAuth mit Erneuerung und Arbeitsbereichsbindung; Web, Telegram, Meldungen | erfüllt (7.2.5) |
| P5 | Übersichten, Dublettenprüfung, Demo, Migration, Dokumentation, Abnahme | erfüllt bis auf die reale Abnahme |

**Abweichungen und offene Punkte.**

1. *Reale Abnahme je Anbieter* (Plan 10): Es gibt kein freigegebenes Testkonto für Google Tasks
   oder Notion. Alle Prüfungen laufen gegen simulierte Dienste nach den am 16. November 2026
   abgeglichenen Unterlagen. Vor dem produktiven Einsatz ist je Anbieter eine Anlage mit einem
   eigenen Testziel und versionsbezogener Freigabe nötig; das ist ausdrücklich nicht erledigt.
2. *Hinweis auf fehlendes Notion-Statusfeld in der Vorschau:* Die Einschränkung steht auf der
   Zuordnungsseite, in der Anleitung und im Adapter (`limitation`), aber nicht auf jeder Karte, weil
   die Karte die Zuordnung des Profils nicht kennt.
3. *Notion in der Ersteinrichtung:* Dort ist keine Zuordnung möglich; Notion wird nach der
   Ersteinrichtung unter Zielprofile eingerichtet.
4. *Demo:* Die Demo baut keine Schreibziele und bietet keine Anbieterwahl; Google Tasks und Notion
   sind dort weder erreichbar noch nötig. Die Netzwerkfalle aus 7.1.5 gilt unverändert.
5. *Rückkehr zu 7.1:* Vorher Aufgabendienst auf einen bisherigen Anbieter stellen und offene oder
   unklare Google-Tasks- bzw. Notion-Aufträge klären. 7.1 kennt die Werte `google_tasks` und
   `notion` nicht und startet mit ihnen nicht; `notion-token.json` bleibt unberührt liegen.

Prüfung 7.2.6: 5 650 Python-Tests mit 100 % Zeilen- und Branch-Abdeckung. Browser 941 bestanden;
die drei behobenen Tests bestanden im Gesamtlauf. Einmal scheiterte unter Last nur der
Zeitmesstest der Live-Suche (300 ms in 95 % von 100 Suchen); er bestand danach einzeln.
