# Dokumentation

Geprüft für Mailhelp 8.1

Hier stehen die Dokumente, die den aktuellen Stand beschreiben. Abgeschlossene Pläne,
Release-Berichte, Konzepte und frühere Prüfberichte liegen im [Archiv](archiv/); sie beschreiben
den Stand ihrer Version und werden nicht mehr nachgeführt.

## Einrichten und bedienen

| Dokument | Inhalt |
| :--- | :--- |
| [Ersteinrichtung](Ersteinrichtung.md) | Installieren, koppeln, Assistent, Verbindungen prüfen, erster Testfall |
| [Konten verwalten](Konten-verwalten.md) | Weitere Postfächer und IServ, Regeln und Ziele je Postfach, ändern und entfernen |
| [Kalender und Aufgaben verbinden](Ziele-einrichten.md) | Google, Microsoft, CalDAV und Todoist als Ziele; Zielprofile je Postfach |
| [Google über den OAuth Playground](Google-OAuth-Playground.md) | Google-Kalender ohne eigenes Anmeldefenster einrichten |
| [Alltagsbedienung](Bedienung.md) | Offene Entscheidungen, Rückfragen, Abgleich, Verlauf, Lernmodus, Telefon, Web-Push |
| [Einstellungen der Weboberfläche](Web-Einstellungen.md) | Jede Einstellung mit Bedeutung, Standardwert und Grenzen |

## Betreiben

| Dokument | Inhalt |
| :--- | :--- |
| [Betrieb und Update](Betrieb.md) | Starten und beenden, Neuladen, Sicherung, Update, Aufbewahrung, Rückkehr zur Vorversion |
| [Fehler beheben](Fehlerbehebung.md) | Meldungen, Ursachen und Abhilfe |
| [Einrichtung und Qualitätsprüfung](Einrichtung-und-Qualitaetspruefung.md) | Aktualisierung, Tailscale, IServ, Google OAuth, Docker, Prüfung der Erkennungsqualität |
| [Projektwebsite](GitHub-Pages.md) | Aufbau und Veröffentlichung von `website/` |

Serveränderungen werden nach erfolgreicher Prüfung gemäß [AGENTS.md](../AGENTS.md)
in der Betriebsdokumentation nachgeführt. Das in [Planung 8.0](Planung-8.0.md)
geforderte zusammengeführte [Serverhandbuch](Serverhandbuch.md) liegt vor;
seine Grenzen und der tatsächlich geprüfte Serverstand stehen im Dokument.
Geheimnisse und private Schlüssel werden getrennt gesichert und nicht in Git gespeichert.

## Aufbau und Regeln

| Dokument | Inhalt |
| :--- | :--- |
| [Architektur](Architektur.md) | Pakete und Schichten, Weg einer Mail, Bestätigungsweg, Zustände, Altformate |
| [Zustandsregeln](Zustandsregeln-3.6.md) | Regeln für Prüfbefehle, Schreibausführung und Merge mit ihren Testnachweisen |
| [Entkopplung von Bedienung und Abruf](Entkopplung-Web-und-Abruf.md) | Gemeinsame Ressourcen, Sperren und Antwortzeiten |
| [Prüfung der Dokumentation 7.0](Pruefung-Dokumentation-7.0.md) | Prüfprotokoll aller lebenden Dokumente und Inventur aller Einstellungen (von `devtools/inventory.py` geschrieben) |

## Laufende Arbeit

| Dokument | Inhalt |
| :--- | :--- |
| [Planung 7.0](Planung-7.0.md) | Umbau des Codes und Prüfung der Dokumentation |
| [Release 7.0](Release-7.0.md) | Stand und Nachweise der Patches von 7.0 |
| [Lernmodus reparieren](Planung-Lernen.md) | Offener Plan zum Lernmodus in der Weboberfläche |
| [Planung 7.1](Planung-7.1.md), [Release 7.1](Release-7.1.md) | Demo-Modus mit vorbereiteten Beispieldaten |
| [Planung 7.2](Planung-7.2.md), [Release 7.2](Release-7.2.md) | Notion und Google Tasks als Aufgabenziele |
| [Planung 7.3](Planung-7.3.md), [Release 7.3](Release-7.3.md) | Verwaltung fehlgeschlagener Mails |
| [Planung 7.4](Planung-7.4.md), [Release 7.4](Release-7.4.md) | Mehrtägige Termine und Datumsbereiche |
| [Planung 7.5](Planung-7.5.md), [Release 7.5](Release-7.5.md) | Mehrsprachigkeit und englische Lokalisierung |
| [Planung 7.6](Planung-7.6.md), [Release 7.6](Release-7.6.md) | Klärungsfreie Demo-Vorschläge und Flow-Optimierung |
| [Planung 7.7](Planung-7.7.md), [Release 7.7](Release-7.7.md) | Vorfilter-Regeln und VIP-Absender |

| [Planung 7.8](Planung-7.8.md), [Release 7.8](Release-7.8.md) | Vollständige Lokalisierung und englische Demo |
| [Planung 7.9](Planung-7.9.md), [Release 7.9](Release-7.9.md) | Kalender-Zugangsdaten ergänzen und Anmeldeprobleme sichtbar machen |
| [Planung 8.0](Planung-8.0.md), [Release 8.0](Release-8.0.md) | Zentraler Google-Zugang, Ersteinrichtung und Serverhandbuch mit Konfigurationsvorlagen |
| [Planung 8.1](Planung-8.1.md), [Release 8.1](Release-8.1.md) | Anbietervorlagen und Postfach-OAuth2; Fehlerbehebung für Datumsergänzung bei bekannter Uhrzeit und Wiederaufnahme pausierter Rückfragen |
| [Planung 8.2](Planung-8.2.md), [Release 8.2](Release-8.2.md) | Geführtes Self-Service-Onboarding und zentrale Ziel-OAuths (Microsoft & Notion) |
| [Planung 8.3](Planung-8.3.md) | Vollständige Bereinigung der Sprachausgabe (DE/EN) nach Live-Prüfung auf Produktiv- und Demo-Server |
| [Planung 8.4](Planung-8.4.md), [Release 8.4](Release-8.4.md) | Automatische Erinnerungen für neue Kalendereinträge, standardmäßig fünf Minuten vor Beginn |
| [Planung 8.5](Planung-8.5.md), [Release 8.5](Release-8.5.md) | Übersichtliche Einstellungen: Bereiche nach Aufgaben, Abschnittsformulare mit gemeinsamer Prüfung, verständliche Werte |
| [Planung 8.6](Planung-8.6.md), [Release 8.6](Release-8.6.md) | Stabile Python-3.12-CI für Ubuntu 26.04, saubere Workflow-Artefakte und aktualisierte Docker-Basisimages |
| [Planung 8.7](Planung-8.7.md), [Release 8.7](Release-8.7.md) | Kundenmodus mit Rollen und Verbrauch in Punkten (abgeschlossen mit 8.7.15, noch keine Kundenfreischaltung) |
| [Planung 8.7 – Lernen in Punkten](Planung-8.7-Lernen.md) | Lernfunktionen in Punkten, Kundeninstanz `kunde`, Bewertung Kurs 1 / Aufschlag 900 % |
| [Planung 8.8](Planung-8.8.md), [Release 8.8](Release-8.8.md) | Gehostete OAuth-Routen im Kundenmodus vervollständigen und Demo-Modus per Deny-by-Default an den Kundenmodus angleichen (in Umsetzung, AP1–AP3 mit 8.8.1–8.8.3) |

Außerhalb dieses Ordners: [README](../README.md) (Einstieg), [Spezifikation](../Mailhelp-Projektspezifikation.md),
[Änderungen](../CHANGELOG.md), [Datenschutz](../DATENSCHUTZ.md),
[Nutzungsbedingungen](../NUTZUNGSBEDINGUNGEN.md).
