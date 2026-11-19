# Inboxstride: Forenwünsche und Funktionsabgleich

Recherchestand: 15. November 2026. Geprüfte technische Basis: lokaler Mailhelp-Quellstand **7.0.8**. Das ist ein Codeabgleich, keine vollständige Geräte- oder Anbieterabnahme. Inboxstride ist als gehostetes Angebot noch nicht öffentlich gestartet. Eine vorhandene Funktion in der technischen Basis bedeutet daher nicht, dass sie bereits als buchbarer Inboxstride-Service geliefert wird.

## Methode und Grenzen

Qualitative, gezielte Suche in öffentlichen Diskussionen zu E-Mail-Aufgaben, Postfachorganisation und Kalenderplanung. Fünf ausgewählte Threads wurden inhaltlich gelesen. Berücksichtigt wurden konkrete Probleme und Wünsche von Fragestellern sowie nachvollziehbare Nutzerkommentare. Anbieterantworten, Werbelinks und spätere Empfehlungs-/Referral-Beiträge wurden nicht als unabhängige Nachfrage gewertet. Beim Workflow-Thread S3 stützen wir uns insbesondere auf Kommentare, nicht auf die möglicherweise werbliche Produktnennung im Ausgangsbeitrag.

Die Auswahl ist englischsprachig und nicht repräsentativ. Sie belegt Bedürfnisse einzelner Nutzer, keine Marktanteile, Häufigkeitsrangfolge oder Zahlungsbereitschaft für Inboxstride. Die unten vorgeschlagenen Prioritäten sind unsere Einschätzung. Es wurden keine erfundenen Kundenstimmen oder Zahlen auf die Landingpage übernommen.

## Quellen

- **S1 — r/ProductivityApps, „Recommendations?“:** [Thread](https://www.reddit.com/r/ProductivityApps/comments/1tzmrpp/recommendations/). Ausgangsfrage: mehrere Postfächer, Mail-zu-Aufgabe, Zusammenfassungen, Fristen/Dringlichkeit, Aufräumen, Kalender und täglicher Überblick. Der Fragesteller kritisiert außerdem Kontextfehler, eine schwache mobile Nutzung und fehlende Zusammenarbeit. Spätere Referral-Empfehlungen werden nicht ausgewertet.
- **S2 — r/SaaS, „Looking for a tool to manage my email-tasks“:** [Thread](https://www.reddit.com/r/SaaS/comments/1gv887y/looking_for_a_tool_to_manage_my_emailtasks/). Ausgangsproblem: Aufgaben in eingehenden Mails suchen, manuell nach Notion übertragen und bei versendeten Mails das Nachfassen vergessen. Ein Nutzer beschreibt manuell gepflegte Erinnerungen für ausstehende Antworten.
- **S3 — r/productivity, „What's your current email + task management setup?“:** [Thread](https://www.reddit.com/r/productivity/comments/1n3ekwv/whats_your_current_email_task_management_setup/). Nutzerkommentare beschreiben Verwaltungsaufwand durch komplexe Werkzeuge, den Wunsch nach verbundenen Spezialwerkzeugen und Google Tasks als vorhandenen Bestandteil des persönlichen Workflows. Andere nutzen mehrere Google- und Microsoft-Konten.
- **S4 — Hacker News, „Show HN: Inbox Zero – open-source email assistant“, 29.–31. Dezember 2023:** [Diskussion](https://news.ycombinator.com/item?id=38809770). Nutzer wünschen ausdrückliche Freigaben und bearbeitbare Antwortentwürfe. Weitere Kommentare verlangen klare Anbietergrenzen, offene Mailprotokolle und Transparenz bei KI-Datenverarbeitung; manche akzeptieren ausschließlich lokale Verarbeitung. Das sind unterschiedliche Anforderungen, keine einheitliche Position aller Teilnehmer.
- **S5 — r/productivity, „Looking for automatic start-date scheduler“:** [Thread](https://www.reddit.com/r/productivity/comments/190ytia/looking_for_automatic_startdate_scheduler/). Der Fragesteller möchte die geschätzte Arbeitsdauer eines Projekts vor dessen Frist automatisch in freie Kalenderzeiten verteilen lassen.

## Was die technische Basis bereits abdeckt

| Nutzerbedarf | Befund im Code | Konkrete Positionierung der Landingpage |
| --- | --- | --- |
| Weniger manuelles Übertragen (S1, S2) | Aufgaben- und Terminvorschläge mit anschließender bestätigter Anlage; `domain/`, `proposals/`, `review/`, `external/` | „Aufgaben statt Copy & Paste“, Beispiel „Bitte bis Freitag anmelden“ |
| Lange Mails schneller erfassen (S1) | Strukturierte Analyse/Zusammenfassungen; `processing/`, `domain/` | Klarer Überblick statt unspezifischer KI-Versprechen |
| Fristen samt Kontext erkennen (S1, S2) | Zeitinformationen und Vorschläge, Quellenbezüge sowie Original-Mail-Links; `domain/deep_links.py`, `proposals/` | „Die Frist sehen. Den Kontext behalten.“ Kein Versprechen, jede Frist fehlerfrei zu erkennen |
| Mehrere Postfächer zusammenführen (S1, S3) | Bis zu zehn konfigurierte Postfächer; `config/models.py`, `MAX_MAILBOXES` | Ein Überblick, Herkunft der Nachricht bleibt erhalten. Keine Zusage einer bestimmten Anzahl pro künftigen Tarif |
| Den Tag überblicken (S1) | `notifications/briefing.py`: tägliche Zusammenfassung von Terminen, Aufgaben und offenen Vorschlägen, Zustellung über konfigurierte Kanäle | „Mit einem Tagesüberblick starten.“ Keine Gleichsetzung mit automatischer Arbeitsplanung |
| Kontrolle behalten (S4) | Versionierte Freigaben und Schutz vor doppelten externen Anlagen; `review/`, `external/confirmed.py` | Explizite Freigabe; Bearbeiten allein legt keinen Eintrag an |
| Bestehende Werkzeuge weiter nutzen (S3, S4) | Kalender: Google, Outlook, CalDAV. Aufgaben: Todoist, Microsoft To Do, CalDAV, Apple Erinnerungen; `config/models.py`, `external/` | Konkrete Entwicklungsanbindungen im FAQ; Startauswahl und Voraussetzungen bleiben ausdrücklich offen |
| Smartphone nutzen (S1) | Responsive Weboberfläche/PWA, `web/static/` | Mobile Prüfung und Freigabe. Keine Behauptung einer fehlerfreien Geräteabnahme oder vollständiger Offline-Nutzung |
| Antwortentwürfe statt autonomer Antworten (S4) | `notifications/drafts.py`, `mailbox/draft_writer.py`: bearbeitbare Antwortentwürfe sind bereits vorhanden | Kein fehlendes Feature; im Seitenfokus bleiben Aufgaben und Termine |

Alle Codepfade in dieser Tabelle sind relativ zu `../Mailhelp/src/mailhelp/`. Für Anbieterzugriff können zusätzliche Voraussetzungen, Berechtigungen oder lokale Brücken gelten. Insbesondere Apple Erinnerungen ist keine pauschale Zusage einer direkt vom Linux-Host verfügbaren Anbindung. Deshalb nennt das FAQ Entwicklungsanbindungen und kündigt den tatsächlichen Startumfang separat an.

## Gewünscht, aber technisch noch nicht abgedeckt

| Wunsch | Quelle | Bestehende Grenze / fehlender Teil | Einschätzung |
| --- | --- | --- | --- |
| Ausstehende Antworten automatisch nachverfolgen | S2 | Kein erkennbarer Versand-/Antwortstatus-Workflow, der gesendete Mails überwacht, ohne Antwort erinnert und Erinnerungen bei Eingang der Antwort beendet. Antwortentwürfe und allgemeine Aufgaben ersetzen das nicht. | Hoch: eng am Kernproblem |
| Intelligente Prioritäten über alle Aufgaben hinweg | S1 | Fristen, Aufgaben und Übersichten sind vorhanden. Eine übergreifende dynamische Rangfolge nach Dringlichkeit, Wichtigkeit und Aufwand ist nicht als eigener Planungsworkflow implementiert. | Hoch: vorab mit Nutzern prüfen |
| Postfach aufräumen: archivieren, sortieren, snoozen, Newsletter abbestellen | S1, S3 | Interne Bearbeitungszustände, Filter und das Weglegen einer Vorschlagskarte sind keine Archivierung oder Verschiebung im eigentlichen Mailpostfach. Kein entsprechender vollständiger Postfach-Aufräumworkflow gefunden. | Mittel: eigene Freigabe- und Wiederherstellungsregeln nötig |
| Notion und Google Tasks direkt anbinden | S2, S3 | Keine nativen Adapter in der Anbieterübersicht; vorhandene Google-Kalender-Unterstützung bedeutet keine Google-Tasks-Unterstützung. | Mittel: nach Zielgruppe priorisieren |
| Aufgaben automatisch als Arbeitsblöcke im Kalender verteilen und umplanen | S5 | Kalenderanlagen und Terminabgleich sind vorhanden; kein Scheduler für Dauer, freie Zeitfenster, Aufteilung und Umplanung bis zur Deadline. | Später: deutlich größerer Umfang |
| Gemeinsames Team-Postfach mit Zuweisung und Zusammenarbeit | S1 | Mehrere Postfächer und mehrere gekoppelte Geräte ergeben noch keinen Team-Workflow mit persönlichen Rollen, Zuständigkeiten und gemeinsamer Bearbeitung. Kein entsprechendes vollständiges Produktmerkmal gefunden. | Später: Zielgruppe und Rechte zuerst klären |

Die Negativbefunde beziehen sich auf die aktuellen Konfigurationsmodelle, Anbieteradapter und Arbeitsabläufe im gelesenen Quellstand. Einzelne Wörter wie `follow_up` wurden nicht als Funktionsnachweis gewertet: `proposals/proposal_merge.py::_follow_up_fields` ergänzt beispielsweise Vorschlagsfelder und verfolgt keine ausstehenden Mailantworten.

## Gewünscht, aber für den gehosteten Service noch offen

- **Belastbare Datenschutz- und Verarbeitungsangaben (S4):** Konkrete Betreiber-/Unterauftragnehmerkette für die Mailanalyse, Modellanbieter, Speicherfristen und Zugriffsberechtigungen des künftigen Angebots müssen festgelegt und veröffentlicht werden. Die Datenschutzerklärung der Vormerkseite beschreibt bisher die Interessentenerfassung, nicht einen angeschlossenen Postfachdienst. Keine Behauptung „kein KI-Training“, „alles bleibt auf dem Gerät“ oder „ausschließlich EU“, solange diese Zusagen nicht belegt sind. Die technische Basis hat konfigurierbare Aufbewahrung und ein experimentelles lokales Modellbackend; das ist kein bereits zugesagter reiner Offline-SaaS-Tarif.
- **Einfacher Einstieg ohne technischen Betrieb (S3, S4):** Die Landingpage sammelt Interesse; buchbares Selfservice-Onboarding, verbindliche Preise, Limits und ein öffentlich nutzbarer Testzugang sind noch nicht bereitgestellt. Das sind notwendige Schritte zur Erfüllung des gehosteten Angebots. Eine bestimmte Preisgrenze oder kostenlose Testdauer lässt sich aus dieser Auswahl nicht ableiten.

## Umsetzung auf der Landingpage

Deutsch und Englisch erhalten die gleichen Aussagen: konkrete E-Mail-zu-Aufgabe-Beispiele, weniger Suchen und Übertragen, vier neue Alltagsvorteile (Postfächer, Tagesüberblick, Quellenkontext, Freigaben) sowie FAQ zu Anbindungen, Smartphone und Datenverarbeitung. Die Seite kennzeichnet das Angebot weiter als in Vorbereitung. Fehlende Funktionen aus der Wunschliste werden nicht als verfügbar beworben. Öffentliche Texte nennen ausschließlich Inboxstride und Funktionen.

Die Recherche erzeugt keine zusätzlichen Tracker, externen Skripte oder Laufzeitdienste. Quellen und interne Produktbewertung bleiben in diesem Entwicklungsdokument; es wird nicht im öffentlichen Webverzeichnis ausgeliefert.
