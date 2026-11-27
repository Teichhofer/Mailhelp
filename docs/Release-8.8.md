# Mailhelp 8.8 – Umsetzung und Freigabestand

Stand: 27. November 2026. Version 8.8.6. Grundlage: [Planung 8.8](Planung-8.8.md).

> **In Umsetzung.** AP1–AP7 sind mit 8.8.1–8.8.6 umgesetzt; AP8 (Abschluss) ist offen. Nicht ausgeliefert: `kunde` läuft mit
> 8.7.15, Produktion und Demo laufen mit 8.5.4.

## Umgesetzt in 8.8.1 – AP1 Gehostete OAuth-Routen im Kundenmodus

| Punkt | Umsetzung |
| --- | --- |
| Routen | `CUSTOMER_ROUTES` (`web/permissions.py`) nennt die gehosteten Schritte für Google, Microsoft, Notion und Postfächer sowie `GET /auth/status/<64 Hex>` einzeln. Trennen ist nur als POST erlaubt. `/einrichtung`, `/einrichtung/start` und `/einrichtung/speichern` bleiben gesperrt |
| Rückweg | `MailhelpSite.setup_return`: Betreiber und Selbstbetrieb kommen wie bisher zur Einrichtung, Kunden auf `/einstellungen/zielprofile`, wo sie den Entwurf bestätigt übernehmen (8.7.15). In der Ersteinrichtung (`InitialSite`) bleibt der Weg unverändert |
| Sicherheitsfix | `ConnectionActivation` übernimmt `restricted` des Konfigurationsdienstes und prüft `permitted`, bevor `.env` geschrieben wird. Bis 8.7.16 konnte eine Kundensitzung über eine Postfachaktivierung Betreiberfelder eines Postfachs ändern |
| Felder | Für Kunden zusätzlich änderbar: `imap.mailboxes.<n>.auth_method` und `.oauth_connection` (`MAILBOX_SIGN_IN_FIELDS`) |
| Tests | `tests/web/test_customer_oauth.py`: vollständiger Google-Ablauf als Kunde, Microsoft- und Notion-Schritte, Postfach-OAuth-Routen, Konsistenztest aller registrierten Anmelderouten, Postfachanmeldung mit echter Konfigurationstransaktion, abgelehnte Betreiberfelder ohne Änderung an `.env`. Sechs der sieben Tests scheitern mit 8.7.16 |

Die Handler prüfen weiterhin Sitzung, CSRF, Entwurfsversion und Idempotenz. `hosted_auth` muss eingerichtet sein,
sonst antworten sie mit 503. Die Anmeldung schreibt nichts in Kalender oder Aufgabenlisten.

## Umgesetzt in 8.8.2 – AP2 Kunden-Unterseite `/einstellungen/allgemein`

| Punkt | Umsetzung |
| --- | --- |
| Befund | Die Werte waren seit 8.7 Kundenfelder, ihr einziges Formular lief aber über die Betreiberroute `/einstellungen/speichern` (403) |
| Seite | `GET/POST /einstellungen/allgemein`, erster Bereich der Kundenübersicht; ein Abschnittsformular mit `GENERAL_FIELDS` (Sprache, Zeitzone, persönliche Angaben, Termindauern, Kalendererinnerung Profil 1, Entwürfe, Briefings, Inhalte des Tagesüberblicks) |
| Ablauf | Prüfseite mit bisherigem/neuem Wert und „Wirkt“ (sofort/nach Neustart), dann „Änderungen ausdrücklich speichern“; CSRF, Dateistand, Idempotenzschlüssel und Sprach-Cookie wie bei den Betreiberabschnitten; Rückweg auf die Seite |
| Rechte | Andere Felder, Zurücksetzen fremder Felder und Einzelfeldformulare: 403 vor jedem Befehl; vor dem Schreiben prüft `ConfigurationService.permitted` erneut |
| Tests | `tests/web/test_customer_general.py` (alle vier scheitern mit 8.8.1); Hilfeabschnitt `bedienung/eigene-werte-in-einer-kundeninstanz` in der Kundenhilfe |

## Umgesetzt in 8.8.3 – AP3 Banner-System und Neustart-Hinweis

| Punkt | Umsetzung |
| --- | --- |
| Baustein | `web/banners.py`: `SystemBanner(id, severity, text, action_href, action_label)`, `PAGE_BANNERS`, `render_banners` (escaped, `role="alert"` bei Fehlern, sonst `status`). `MailhelpSite.banners()` befüllt je Anfrage; `layout()` setzt die Banner an den Anfang von `main`; der Linkfilter für Kunden gilt auch für Banner |
| Neustart-Hinweis | Sichtbar, solange `ConfigurationService.restart_pending()` gilt, Mailhelp läuft und ein Lifecycle vorhanden ist: `config.yaml` weicht vom laufenden Stand ab. Abschnitte, die schon beim Start abwichen, zählen nicht. Zwischengespeichert nach Dateistand und laufendem Stand, eine Dateiabfrage je Anfrage; Lasttests unverändert bestanden |
| Neustart für Kunden | `/einstellungen/neustarten` in `CUSTOMER_ROUTES`; `Lifecycle(…, authorize_restart=components.authorize)`; vor der Ausführung wird die Sitzung erneut geprüft. Beenden bleibt `authorize_operator` (403 und `StopRefused`) |
| Tests | `tests/web/test_restart_banner.py`: Hinweis auf sechs Seiten mit Link, Neustart ohne und mit Bestätigung, kein Hinweis während des Neustarts und danach, sofort wirksame Werte, Beenden gesperrt, abgemeldete Sitzung vor der Ausführung, Start-Abweichungen, unlesbare und fehlende Datei, Escaping |

## Umgesetzt in 8.8.4 – AP4 Lesende Kunden-Verbindungsprüfung

| Punkt | Umsetzung |
| --- | --- |
| Aktion | `POST /einstellungen/verbindungen/pruefen` (`web/own_checks.py`), Knopf auf Postfach- und Zielprofilseite, Rückweg nur auf diese beiden Seiten |
| Umfang | Nur `imap`, `calendar`, `todoist`, `calendar:<n>`, `tasks:<n>` über `DiagnosticsService.run` (lesend, `check_access`); kein LLM-Test, keine Nachrichten, kein Dateisystem |
| Drosselung | Ein Durchlauf zur Zeit, 15 s Wartezeit je Sitzung (429 mit `Retry-After`), 30 s Gesamtlimit; jede Prüfung behält ihr eigenes Zeitlimit (Zeitüberschreitung: „vorübergehend nicht erreichbar“) |
| Anzeige | Nur Zustand und nächster Schritt; keine Anbieter-, Token-, Pfad- oder Geheimnisnamen. Gilt jetzt auch für die Prüfknöpfe eines Postfachentwurfs (Bugfix: sie zeigten den `.env`-Hinweis der Diagnose) |
| Demo | `/einstellungen/allgemein` und `/einstellungen/verbindungen/*` in `BLOCKED` |
| Tests | `tests/web/test_own_checks.py`: Kundenablauf ohne Interna, Entwurfsknöpfe, Doppelklick und laufender Durchlauf, Gesamtlimit und hängende Prüfung, Rückweg, ungültiger Schlüssel, abgelaufene Sitzung, fehlende Laufzeit, alle Zustände, Demo-Sperre |

## Umgesetzt in 8.8.5 – AP5/AP6 Demo mit Kundenoberfläche (Teil 1)

| Punkt | Umsetzung |
| --- | --- |
| Rolle | `create_demo` schaltet die Demo-Anmeldung in den Kundenmodus (`DEMO_INSTANCE = "demo"`); Besucher sind `customer`, `CUSTOMER_VIEW` und die Routenprüfung des Kundenmodus gelten unverändert. Alte Besuchersitzungen ohne Rolle enden beim ersten Start |
| Routen | `demo_may(method, path)` = `customer_may` minus `BLOCKED`/`BLOCKED_POST` (Konten/OAuth, `/einstellungen/*`, Benachrichtigungen, Geräte, Hilfe, Berichte, Themen, Absenderregeln, Entwürfe, Nachanalyse, Lernläufe). Einheitliche 403-Seite im Kundenrahmen, ohne Betreiberlinks |
| Links | `filter_links` (neu, `customer_links` nutzt sie) mit `demo_may_link` auf jeder Demo-Antwort; Infokarten in der Einstellungsübersicht (`MailhelpSite.offered`); kein Hilfe-Chat in der Demo |
| Tests | `tests/web/test_demo_customer_view.py`, erweiterte Sperrliste in `test_demo_site.py`; Browser-Demotests unverändert grün |
| Betrieb | Rauchprüfungen der Demo nutzen ab 8.8.5 Kundenrouten (`docs/Betrieb.md`, Demo-Instanz) |

## Umgesetzt in 8.8.6 – AP5 Beispiel-Verbrauch

`/verbrauch` zeigt in der Demo `SAMPLE_USAGE` (`web/usage_site.py`): neun feste Einträge über drei Tage, in Punkten,
gleiche Werte in Deutsch und Englisch, ohne Ledger, Preise oder Wechselkurse; ein Hinweis kennzeichnet die Werte als
Beispiel. Bisher stand dort „Die Verbrauchserfassung ist für diese Instanz noch nicht eingerichtet.“

**Abweichung vom Plan:** Themen bleiben in der Demo eine Infokarte statt einer Ansicht. Die Demo hat keine eigenen
Themendateien (die Seite antwortete schon vorher mit 503), und die mitgelieferten Standardthemen gibt es nur auf Deutsch;
eine englische Demo zeigte sonst deutsche Themennamen.

## Umgesetzt in 8.8.6 – AP7 Paritäts- und Link-Crawler (Kundenmodus)

`tests/web/test_customer_crawl.py` startet in einer Kundensitzung auf Start-, Einstellungs-, Postfach-, Zielprofil-,
Verbrauchs-, Lern-, Themen- und Hilfeseite und folgt jedem lokalen Link (Deutsch und Englisch, über 150 Seiten). Kein
Link führt auf 403 oder 404, jedes Formular zielt auf eine Kundenroute, und keine Seite enthält Preise, Wechselkurse,
Aufschläge, `.env`-Hinweise oder Schlüsselnamen. Befund und Fix: `/hilfe/google-playground` (Betreiberanleitung mit
`.env`-Einträgen) ist keine Kundenroute mehr. Den Demo-Crawler und die Teilmengenprüfung `DEMO ⊆ CUSTOMER` enthält
`tests/web/test_demo_customer_view.py`.

## Offen

AP8 Abschluss: Hilfeseiten (Web-Einstellungen, Ziele einrichten) gegenprüfen, Vollprüfung und Browsersuite ohne
Fehler hintereinander, Status der Planung auf „abgeschlossen“. Keine Auslieferung ohne ausdrückliche Freigabe.
