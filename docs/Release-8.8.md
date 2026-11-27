# Mailhelp 8.8 – Umsetzung und Freigabestand

Stand: 27. November 2026. Version 8.8.2. Grundlage: [Planung 8.8](Planung-8.8.md).

> **In Umsetzung.** AP1 und AP2 sind mit 8.8.1 und 8.8.2 umgesetzt; AP3–AP8 sind offen. Nicht ausgeliefert: `kunde` läuft mit
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

Der seitenübergreifende Neustart-Hinweis folgt mit AP3.

## Offen

AP3 Banner-System und Neustart für Kunden, AP4 Verbindungsprüfung (die lesende
Prüfung aus 8.7.15 auf der Postfachseite deckt einen Teil ab), AP5–AP6 Demo nach Deny-by-Default, AP7 Paritäts- und
Link-Crawler-Tests, AP8 Abschluss.
