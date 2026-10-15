# Offene Vorschläge und Termindauern – Umsetzung 2.4

> Historischer Versionsstand: Dieses Dokument beschreibt die genannte Version oder
> deren damaligen Plan. Ursprüngliche Ziele und Prüfergebnisse sind kein Nachweis
> des heutigen Umfangs. Aktueller Betrieb: [README](../README.md),
> [Release 3.3](Release-3.3.md) und [Projektspezifikation](../Mailhelp-Projektspezifikation.md).

Die fachliche Erweiterung wird auf `beta` mit der nach `AGENTS.md` erhöhten
Patchversionen 2.3.2 (Implementierung) und 2.3.3 (Abschlussdokumentation) entwickelt.
Ein Release oder Tag wird damit nicht erstellt.
Die ursprüngliche [Planung](Planung-2.4.md) beschreibt die fachlichen Entscheidungen
und die Untersuchung der drei beobachteten Fälle.

## Abgleich und Quellen

`MailPipeline` normalisiert die Rohextraktion, prüft bestehende externe Einträge
lesend und übergibt jeden eigenen Kandidaten an `ProposalReconciliationService`.
Dieser liest ausschließlich aktuelle, schema-validierte Vorschlagsakten;
Versionssnapshots und Aliasakten sind keine neuen offenen Kandidaten. Die Suche
ist ein neu aufgebauter Cache über die JSON-Akten, keine zusätzliche Datenbank.

Art, Ziel und bekannter Anbieter müssen passen. Betreff und gehashte Message-ID-,
References- und In-Reply-To-Anker liefern Gesprächskontext. Konkrete Termine
unterschiedlicher Tage bleiben getrennt; Änderungen und vorbereitende Anfragen
werden gesondert geprüft. Titelähnlichkeit allein erlaubt keinen automatischen Merge.
Bei Aufgaben bleibt die konkrete Aktion maßgeblich, nicht nur der zugehörige Termin.

Der optionale Prompt `open_proposal_match` erhält begrenzte Vorschlagsfelder,
keine zusätzliche Volltextkopie. Das Ergebnis nennt einen Index und eine Beziehung.
Ungültige Ergebnisse, mehrere Treffer, fehlende Prüfung oder laufende/unklare
Schreibaktionen sperren eine Neuanlage. Die Grenze
`proposal_reconciliation.max_semantic_candidates` beträgt standardmäßig acht.
Cache-Schlüssel enthalten Eingang, Kandidatenrevisionen und Promptpolicy;
der Cache speichert nur Aufrufreferenz und begrenztes Prüfergebnis.

Ein kanonischer Vorschlag behält seine ID. Eine Ergänzung erhöht seine Version
und löscht frühere ausdrückliche Sonderfreigaben. Der eingehende Vorschlag wird
eine nicht ausführbare Aliasakte (`merged`). Alte GET-Links führen zum aktuellen
kanonischen Vorschlag; alte POST-Befehle und Telegram-Schaltflächen bleiben veraltet.
Die Quellen enthalten Referenzen, Nachrichtenzeit, Betreff und gehashte Anker.

Ältere Nachrichten setzen konkrete Zeiten nicht zurück. Ein jüngerer belegter
Änderungsvorschlag kann ungeschützte Fakten ersetzen. Ein ausdrückliches Ende
ersetzt eine passende Standardannahme. Geschützte manuelle Werte, widersprüchliche
Intervalle und ungesicherte Zuordnungen erzeugen prüfbare Fragen. Werte aus
Altakten ohne Herkunftskennzeichnung werden vorsichtig erhalten. Unbekannte
Anbieterbindungen verlangen bei einem Merge eine ausdrückliche lokale Zuordnung.

Ungeprüfte Zusätze werden mit Referenz gehalten. Web und Telegram bieten
Zuordnen/Separat-Behalten an, gebunden an Quell- und Zielversion. Mehrere blockierte
Treffer können einzeln als verschieden markiert werden. Die neue Version muss
anschließend getrennt bestätigt werden; diese lokalen Aktionen schreiben nichts
in Kalender oder Aufgabenverwaltung.

## Dauerannahmen

`event_defaults.video_duration_minutes` ist 60,
`event_defaults.in_person_duration_minutes` ist 180 (je 1–1440 Minuten).
Die Anwendung ergänzt nur ein fehlendes Ende bei eindeutigem Beginn und belegter
Video- oder Präsenzteilnahme. Ein extrahierter Videolink belegt die Videoteilnahme;
unbekannte oder hybride Teilnahme bleibt eine Rückfrage. Signaturanschriften
werden nicht zur Festlegung eines Präsenztermins herangezogen.

Explizites Ende, explizite Dauer, Obergrenzen, unklare Ortszeiten und Ganztagsangaben
werden nicht durch Standards ersetzt. Die Berechnung erfolgt über UTC, sodass
Zeitumstellungen und Mitternacht die verstrichenen Minuten nicht verändern.
`end_origin` und `default_duration_minutes` kennzeichnen die Annahme in Karte,
Webvorschau und externem Beschreibungstext. Manuell geänderte Enden erhalten
die Herkunft `manual` und sind vor automatischem Überschreiben geschützt.

Die Policy mit Normalisierungsversion, angewandten Einstellungen und Matchingpolicy
wird pro Mail vor Verarbeitung gespeichert. Neue Einstellungen verändern keine
bestehenden Vorschläge. `/abgleich` zeigt eine ausdrücklich übernehmbare Vorschau
für fehlende Enden und geänderte Standardannahmen. Der Befehl bindet Vorschlagsversion
und Hash der aktuell gezeigten Einstellungen. Eine ausdrückliche Endzeit wird
dadurch nicht neu berechnet.

## Journal, Schreibgrenze und Aufbewahrung

Ein Merge schreibt zuerst ein schema-validiertes Journal mit beiden Versionen,
Policy und beabsichtigten Revisionen. Unter dem Store-Lock folgen kanonische Akte
und Alias. Erst dann wird das Journal abgeschlossen und sein Inhaltsanteil gelöscht.
Eine Wiederaufnahme prüft Versionen, Status und schon geschriebene Revisionen,
bevor sie fehlende Schritte idempotent beendet. Änderungen am Bestand blockieren
den Auftrag statt neue Fakten zu überschreiben. Reviewaktionen und Wiederaufnahme
externer Schreibaktionen beenden zunächst ausstehende Journale.

LLM- und externe lesende Abgleiche liegen außerhalb des globalen Store-Locks.
Nach der Prüfung wird der Kandidatenbestand unter Lock erneut verglichen.
Benachrichtigungen zeigen die aktuelle kanonische Revision; unklare Zustellresultate
werden nicht automatisch wiederholt. Ungeprüfte Zusatzquellen bleiben vor der
Inhaltsbereinigung geschützt. Abgeschlossene Journale enthalten nur Referenzen.

Der externe Schreibpfad verlangt weiterhin eine ausdrückliche versionsbezogene
Bestätigung. Webbefehle benötigen Sitzung, CSRF und Idempotenz; die Sitzung wird
nach lesendem Vorabgleich erneut geprüft. Ziel und bekannter Anbieter müssen bei
Ausführung zum Writer passen. Fehlgeschlagene Dublettenprüfungen werden nicht als
leerer Kalender behandelt: Der Vorschlag bleibt gesperrt und kann erneut geprüft
werden. Bereits unklare Schreibresultate werden weiterhin ausschließlich abgeglichen.

## Sichtbarkeit vorhandener Termine und Upgrade

Ein `already_exists`-Befund wird gespeichert, auch wenn keine neue Telegramkarte
versendet wird. Eine eindeutig zu einer Sitzung gehörende Rückmeldeaufgabe bekommt
eine bidirektional angezeigte Beziehung. Dadurch verschwindet die schon erkannte
Beiratssitzung nicht hinter ihrer Rückmeldeaufgabe.

`/abgleich` ist zunächst lesend. Fehlende Einzelakten aus gespeicherten Mailbefunden
werden nur mit gebundenem Befundhash und Version wiederhergestellt. Geschlossene
Befunde werden nicht geöffnet. Die ursprüngliche Vorschlagsversion und damit der
Idempotenzschlüssel bleiben erhalten. Ein eingebetteter `confirmed`-Befund wird
als `uncertain` wiederhergestellt, weil die Projektion keinen Nachweis einer noch
ausstehenden Anlage liefert. Er wird ausschließlich mit dem Anbieter abgeglichen;
die Wiederherstellung erteilt keine neue Schreibfreigabe.
Es werden weder reale Bestandsdaten automatisch
zusammengeführt noch externe Termine neu angelegt.

Bestehende Proposal-/MailState-Schemas bleiben mit additiven Standardfeldern lesbar.
Neue Journale, Beziehungen und Vergleichscaches besitzen eigene Schema-Versionen.
Vor dem ersten produktiven Start vollständige Zustandskopie erstellen: Ältere
Programmversionen mit geschlossenen Schemas lesen die neuen Felder nicht; ein
Rollback benötigt den Zustand vor dem Upgrade. Die vorhandenen Rohanalyse-Fingerprints
bleiben unverändert; die Normalisierungs- und Matchingpolicy wird getrennt geführt.

Tests verwenden simulierte Dienste und synthetische Einladungen. Die verbindlichen
Gates prüfen 100 % Zeilen- und Branch-Abdeckung, Schema-Kompatibilität,
Autorisierung, Wiederanläufe, Windows/WSL, Docker, Paketinstallation und die
Weboberfläche einschließlich JavaScript-Abdeckung und Nutzung ohne JavaScript.
