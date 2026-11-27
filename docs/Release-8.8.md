# Mailhelp 8.8 – Umsetzung und Freigabestand

Stand: 27. November 2026. Version 8.8.5. Grundlage: [Planung 8.8](Planung-8.8.md).

> **In Umsetzung.** AP1–AP4 sind mit 8.8.1–8.8.4 umgesetzt, AP5/AP6 bis auf Beispiel-Verbrauch und Themenansicht mit 8.8.5; AP7–AP8 sind offen. Nicht ausgeliefert: `kunde` läuft mit
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

Noch offen in AP5: deterministischer Beispiel-Verbrauch unter `/verbrauch` und eine schreibfreie Themenansicht (bisher 503, jetzt 403).

## Offen

Rest von AP5 (siehe oben); AP7 Paritäts- und Link-Crawler-Tests für den Kundenmodus (für die Demo mit 8.8.5
vorhanden); AP8 Abschluss.
