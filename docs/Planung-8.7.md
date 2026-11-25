# Mailhelp 8.7 – Kundenmodus und Verbrauch in Punkten

**Stand:** 24. November 2026. **Status:** In Umsetzung; AP1–AP3 und Teile von AP4 in 8.7.1 ([Release 8.7](Release-8.7.md)).

**Zielversion:** 8.7, erste Auslieferung 8.7.1; weitere Umsetzungsschritte mit fortlaufenden Patchversionen gemäß den [Entwicklungsregeln](../AGENTS.md).

**Ablage:** Der Plan wurde außerhalb des Repositorys vorbereitet und am 25. November 2026 unverändert in
`docs/Planung-8.7.md` übernommen (AP7). Dieser Plan autorisiert keine Produktivumstellung.

## 1. Verbindliche Produktentscheidungen

Die folgenden Entscheidungen wurden vom Betreiber für Version 8.7 getroffen:

| Thema | Entscheidung |
| --- | --- |
| Kundentrennung | Eigene Instanz und eigene Subdomain je Kunde, mit getrennten Daten und Zugängen |
| Freischaltung | Manuell durch den Betreiber |
| Kundenrechte | Postfächer, Kalender-/Aufgabenziele, Themen und Benachrichtigungen verwalten; KI-Konfiguration, Betreiberschlüssel und Betrieb bleiben beim Betreiber |
| Betreiberzugriff | Jederzeit möglich, ohne jeweils eine Kundenfreigabe anzufordern |
| Protokollierung | Bisherige Einstellungen, Inhalte, Rotation und Aufbewahrung bleiben zunächst unverändert |
| OpenRouter-Schlüssel | Kein Zugriff über die Kundenoberfläche oder deren Schnittstellen; weder lesen noch ersetzen, löschen oder auf ein anderes Ziel umlenken |
| Verbrauch | Kunden sehen ausschließlich Punkte für den von Mailhelp ausgewiesenen Systemverbrauch |
| Punktwert | 1 Punkt entspricht 0,1 Cent; 1.000 Punkte entsprechen 1 Euro |
| Berechnungsbasis | Tatsächlich gemeldete Anbieter-Kosten, mit konfigurierbarem Aufschlag |
| Guthaben | Zunächst nur Verbrauchsanzeige: kein Guthaben, keine Aufladung, keine Abschaltung wegen eines Punktestands |

Die folgenden technischen Festlegungen konkretisieren diese Entscheidungen: prozentualer Aufschlag je Instanz, vom Betreiber gepflegter USD/EUR-Kurs, unveränderliche historische Bewertungsstände und getrennte Kunden-/Betreibersitzungen. Ein konkreter Wechselkurs und Aufschlagsprozentsatz werden erst bei der Instanzeinrichtung festgelegt; Beispielwerte in diesem Plan sind keine Preiseinstellung.

## 2. Ausgangslage und Anschluss an bestehende Versionen

Lesend geprüft am 24. November 2026:

- Produktion und Demo verwenden `mailhelp-production:8.5.4-1ea1c98`.
- Der Dokumentationssnapshot unter `/opt/mailhelp/server-docs` nennt Quellcommit `b2cfa4e` und enthält Planung und Releasebericht für 8.6.1. Version 8.6 ([Planung](Planung-8.6.md), [Release](Release-8.6.md)) behandelt CI, Python-Basisimages und Workflow-Artefakte, keinen Kundenmodus.
- Version 8.5 ([Planung](Planung-8.5.md)) bündelt Einstellungen in Abschnittsformularen und verwendet gemeinsame Prüfseiten. Kundenrechte müssen deshalb einzelne Felder innerhalb dieser Formulare begrenzen; ein bloßes Sperren ganzer Seiten genügt nicht.
- `web/auth.py` verwaltet Kopplung und Sitzungen. Die Rollenbindung ist dort sowie im gespeicherten Sitzungsmodell zu ergänzen.
- `web/settings_site.py`, `web/secrets_site.py`, `web/credential_pages.py` und die zugehörigen Laufzeitdienste besitzen Wege zum Speichern von Zugangsdaten. Diese dürfen im Kundenmodus keine Betreiberschlüssel bearbeiten.
- `web/calls_page.py` und `web/charts.py` geben Dollarwerte aus; die Auswertung verwendet außerdem Euroanzeigen und `usd_per_eur`. Weitere Kostenanzeigen und Schätzungen existieren unter anderem in Lernen, Nachanalyse und Berichten.
- Vor Umsetzung ist der aktuelle Hauptbranch erneut zu prüfen. Die genannten Dateipfade sind überprüfte Anknüpfungspunkte, keine vollständige Liste aller betroffenen Komponenten.

Die bisherigen Schutzregeln der [Spezifikation](../Mailhelp-Projektspezifikation.md) bleiben verbindlich: externe Kalender-/Aufgabenaktionen verlangen eine ausdrückliche, versionsbezogene Bestätigung; Sitzung, CSRF, Revision und Idempotenz werden auch bei der Ausführung geprüft.

## 3. Ziel aus Kundensicht

1. Der Betreiber schaltet eine Instanz frei und stellt den ersten Kundenzugang bereit. Die Einrichtung verlangt keinen OpenRouter-Schlüssel vom Kunden.
2. Der Kunde verbindet seine Postfächer und Ziele und passt Themen und Benachrichtigungen an.
3. Der Kunde sieht die eigenen Mails, Vorschläge, Entscheidungen und Verbindungsprobleme. Er kann Vorschläge bearbeiten und ausdrücklich freigeben.
4. Unter „Verbrauch“ sieht er Punkte für heute, den laufenden Monat und einen gewählten Zeitraum, einschließlich der Zuordnung zu unterstützten Verarbeitungsschritten.
5. Zusätzliche KI-Funktionen zeigen eine Punktschätzung, soweit eine belastbare Schätzung vorliegt. Schätzungen bleiben von tatsächlichem Verbrauch getrennt.
6. Technische Betreiberfunktionen, OpenRouter-Zugangsdaten und Geldbeträge der Systemkosten erscheinen in seiner Oberfläche nicht.
7. Der Kunde wird bei Freischaltung verständlich über den jederzeit möglichen Betreiberzugriff und die unveränderte Inhaltsprotokollierung informiert. Das ist keine zusätzliche Freigabe pro Supportfall.

## 4. Instanzmodus, Identität und Rechte

### 4.1 Modus und Sitzungsrollen

- Bestehender Selbstbetrieb bleibt möglich. Ein expliziter, ausschließlich über die vertrauenswürdige Betreiberkonfiguration aktivierbarer Modus schaltet die Instanz in den Kundenbetrieb.
- Ein Kundenzugang darf diesen Modus weder in einem Formular noch über Konfigurationsimport, Befehlswarteschlange oder direkte Anfragen abschalten.
- Im Kundenmodus erhält jede authentifizierte Sitzung serverseitig die Rolle `customer` oder `operator`. Instanz und Rolle sind Bestandteil der gespeicherten Sitzungsidentität.
- Kundenpasswort, normale Kundengerätekopplung und kundenseitige Telegram-Kopplung erzeugen ausschließlich Kundenrechte. Rolle und Instanz dürfen nicht aus Formularfeldern, URL-Parametern oder Gerätebezeichnungen übernommen werden.
- Der Betreiber erhält eine getrennte, am Host autorisierte Kopplungsmöglichkeit, beispielsweise ein CLI-Kommando mit expliziter Betreiberrolle. Kein öffentlich erreichbarer Rollenwechsel und kein über Kunden-Telegram ausgegebener Betreiber-Code.
- Aktivierung des Kundenmodus widerruft vorhandene rollenlose Sitzungen und ausstehende Kopplungen der betroffenen Instanz. Bestehende Sitzungen werden nicht stillschweigend zu Betreibersitzungen.
- Betreiberzugriff ist jederzeit möglich, bleibt aber authentifiziert, instanzgebunden und widerrufbar. Ein Kundenpasswort ist dafür nicht erforderlich und wird dem Betreiber nicht im Klartext angezeigt.
- Kunden dürfen eigene Kundengeräte verwalten, aber keine Betreibersitzung erzeugen oder widerrufen. Der Betreiber kann Kundengeräte und eigene Betreibersitzungen verwalten.

### 4.2 Rechteübersicht

| Funktion | Kunde | Betreiber |
| --- | --- | --- |
| Eigene Mails, Vorschläge und fachlicher Entscheidungsverlauf | Lesen und bedienen | Lesen und bedienen |
| Kalender-/Aufgabenaktionen | Nur nach konkreter Bestätigung | Ebenfalls nur nach konkreter Bestätigung |
| Eigene Postfächer und Zielverbindungen | Verbinden, prüfen, ändern, trennen | Verwalten |
| Eigene Postfachpasswörter | Nur zweckgebunden neu eingeben/ersetzen, keine Klartextausgabe | Verwalten, keine Klartextausgabe über die Weboberfläche |
| Eigene OAuth-Verbindungen | Vorhandene Verbindungsabläufe nutzen | Verwalten |
| API-/Bot-Tokens und allgemeine Secret-Verwaltung | Keine generischen Secret-Formulare; benötigte Tokens richtet zunächst der Betreiber ein | Verwalten, weiterhin ohne Klartextausgabe |
| Themen, Absenderregeln, Benachrichtigungen | Im erlaubten Umfang bearbeiten | Verwalten |
| Lernfunktionen | Vorhandene Fachfunktionen mit Betreiber-KI und Punktehinweisen nutzen | Zusätzlich Modelle, Prompts und technische Parameter verwalten |
| Sprache, Zeitzone und persönliche Präferenzen | Eigene Werte bearbeiten | Verwalten |
| OpenRouter-Key, KI-Endpunkte, Modell-/Promptkonfiguration | Kein Zugriff und keine Änderung | Verwalten |
| Punkteverbrauch | Eigenen Verbrauch lesen | Verbrauch und interne Geldwerte lesen |
| Wechselkurs, Aufschlag und Bewertungsstände | Nicht ändern; Darstellung nur in Punkten | Festlegen und revisionsgeprüft ändern |
| Raw-Logs, LLM-Rohdaten, Systemdiagnose, Konfigurations-/Backup-Export | Kein Zugriff | Bestehender Zugriff |
| Logging-/Aufbewahrungsparameter, Neustart, Beenden, Updates, Serverkonfiguration | Kein Zugriff | Bestehender Zugriff |
| Kundenmodus, Rollen und Freischaltung | Kein Zugriff | Ausschließlich vertrauenswürdiger Betreiberweg |

Die bestehende generische Zugangsdatenverwaltung bleibt Betreiberfunktion. Kundenseitige Postfach- und OAuth-Formulare verwenden eng begrenzte, verbindungsspezifische Eingaben und dürfen keine beliebigen Umgebungsvariablennamen annehmen. Änderungen an gemeinsamen Zielprofilen einer Kundeninstanz bleiben auf diese Instanz begrenzt.

### 4.3 Durchsetzung und Schutz des Schlüssels

- Zentrale Berechtigungsprüfung mit explizit erlaubten Aktionen und Feldern. Nicht erfasste administrative Funktionen sind im Kundenmodus standardmäßig gesperrt.
- Prüfung vor Lesen sensibler Daten, vor Erzeugung eines Änderungsentwurfs, auf der Prüfseite, beim Einreihen und unmittelbar vor Ausführung eines asynchronen Befehls.
- Gemischte Einstellungsänderungen mit einem gesperrten Feld werden vollständig abgelehnt. Kein teilweises Speichern und keine spätere Ausführung durch einen privilegierten Hintergrunddienst.
- Kein OpenRouter-Key in HTML, JSON, versteckten Feldern, JavaScript-Daten, URLs, Fehlermeldungen, Downloads oder Kundendiagnosen. Auch Ersetzen, Löschen und generische `.env`-Schreibwege sind gesperrt.
- Kunden können weder den KI-Endpunkt noch Proxy-, Header-, Secret-Referenz- oder Zielkonfiguration so ändern, dass Betreiberschlüssel an ein fremdes Ziel gesendet werden.
- Kundenantworten erhalten eigene reduzierte Datenmodelle. Vollständige Betreiberobjekte werden nicht erst im Browser ausgeblendet.
- Suchkatalog, Hilfetexte, Hilfschat-Kontext, Dokumentationsauswahl und alte Direktlinks beachten die Rolle. Der Hilfschat erhält keine Geheimnisse und kann keine Rechte vergeben.
- Telegram, Web-Push, technische Detailansichten und mögliche Downloads unterliegen derselben Zuordnung. Ein alternativer Kanal darf keine Betreiberrechte vermitteln.
- Betreibersitzungen verwenden getrennte Ansichten; privilegierte Antworten dürfen nicht über gemeinsam genutzte Caches, Service Worker oder gespeicherte Hilfschat-Inhalte in eine Kundensitzung gelangen.

## 5. Punkteberechnung

### 5.1 Einheit und Formel

Intern bleibt die tatsächliche Kostenangabe in der vom Anbieter gemeldeten Währung erhalten. Für den vorgesehenen OpenRouter-Pfad sind dies USD.

Bezeichnungen:

- `cost_usd`: tatsächlich gemeldete Kosten des einzelnen Anbieteraufrufs.
- `usd_per_eur`: US-Dollar je Euro, entsprechend der Richtung der bestehenden Einstellung; positiver endlicher Dezimalwert.
- `markup_percent`: Aufschlag auf die umgerechneten Kosten in Prozent; endlicher Dezimalwert ab null, je Kundeninstanz konfigurierbar.

```text
Basis in EUR = cost_usd / usd_per_eur
Bewerteter Verbrauch in EUR = Basis in EUR × (1 + markup_percent / 100)
Punkte = Bewerteter Verbrauch in EUR × 1.000
```

Beispiel ausschließlich zur Abnahme: 0,01 USD bei `usd_per_eur = 1,25` und 25 Prozent Aufschlag ergeben 10 Punkte. Ohne Aufschlag wären es 8 Punkte. Aufschlag bedeutet Aufschlag auf den Einkauf, nicht die kaufmännische Marge am Endbetrag.

Der feste Punktwert wird nicht vom Kunden oder über einen wechselnden Umrechnungskurs verändert. Der USD/EUR-Kurs betrifft nur den USD-Einkauf. Konfigurationswerte und die Geldrechnung verwenden `Decimal`, keine binären Gleitkommazahlen.

### 5.2 Bewertungsstände und Rundung

- Der Betreiber legt pro Instanz einen versionierten Bewertungsstand mit Kurs, Aufschlag und Gültigkeitsbeginn fest. Der erste Stand muss vor Aktivierung der Verbrauchserfassung ausdrücklich konfiguriert sein; keine stillschweigende Übernahme der Beispielwerte.
- Der Bewertungsstand wird vor jedem tatsächlichen Anbieteraufruf dauerhaft an dessen Versuch gebunden. Eine Änderung während einer laufenden Anfrage bewertet diesen Versuch nicht nachträglich neu.
- Eine Betreiberänderung zeigt Alt/Neu, Zeitpunkt und ein Punktebeispiel und erfordert die vorhandene gesicherte Bestätigung. Sie wirkt nur auf danach beginnende Versuche. Ein neuer Retry nach dem Wechsel bindet den dann gültigen Stand.
- Je Verbrauchseintrag bleiben Originalkosten, Kurs, Aufschlag, Bewertungsrevision und hochpräzise Punkte erhalten. Bereits erfasster Verbrauch wird bei Kurs-/Aufschlagsänderungen nicht neu berechnet.
- Festgelegter Rechenkontext: mindestens 28 Dezimalstellen, keine Rundung auf ganze Punkte je Aufruf. Summen werden aus den gespeicherten hochpräzisen Werten gebildet.
- Anzeige: zwei Nachkommastellen, kaufmännische Rundung (`ROUND_HALF_UP`). Positive Beträge unter 0,01 Punkt erscheinen als „< 0,01 Punkte“, nicht als kostenlos. Die Anzeige enthält bei Bedarf den Hinweis „Einzelwerte gerundet“.
- Monat und Tag richten sich nach der Instanzzeitzone; Ereignisse speichern absolute UTC-Zeitpunkte. Sommerzeit und spätere Zeitzonenänderungen dürfen keinen Verbrauch doppelt erfassen.

### 5.3 Tatsächlicher Verbrauch, Schätzungen und fehlende Angaben

- Alle dem Kunden dienenden KI-Aufrufe zählen: normale Verarbeitung, Rückfragen, Nachanalyse, Lernläufe, Hilfschat und unterstützte KI-Berichte. Von diesen Vorgängen verursachte Provider-Retries und Fallbacks zählen jeweils mit ihren tatsächlich gemeldeten Kosten, auch bei fachlich unbrauchbarem Ergebnis.
- Betreiberinterne Tests und Wartungsaufrufe außerhalb des Kundenauftrags zählen nicht zum Kundenverbrauch. Ihr Zweck muss serverseitig gesetzt sein und darf nicht vom Kunden zur Umgehung der Erfassung gewählt werden.
- Fehlende Kostenangaben bedeuten „Verbrauch noch nicht bestimmbar“, niemals null. Anzeige und Aggregation nennen die Zahl nicht bewertbarer Aufrufe und kennzeichnen eine bekannte Teilsumme als unvollständig.
- Tatsächlich gemeldete Nullkosten bleiben null. Ungültige, negative oder nicht endliche Kostenwerte werden als Klärungsfall behandelt, nicht still in Null oder negative Punkte umgewandelt.
- Tokenanzahlen und Preislisten liefern höchstens ausdrücklich bezeichnete Schätzungen. Sie ersetzen keine gemeldeten Istkosten und werden nicht als tatsächlicher Verbrauch gebucht.
- Vorhandene manuelle Lernbudgets werden in der Kundenansicht in Punkten dargestellt und serverseitig anhand des gebundenen Bewertungsstands in die vorhandenen Grenzen übersetzt. Sie sind Ausführungsgrenzen für diesen Lauf, kein Kontoguthaben. Technische Anbieter-/Tokenlimits bleiben wirksam und beim Betreiber.
- Für den Kundenmodus ist zunächst der OpenRouter-Kostenpfad abgenommen. Lokale Modell-/Stromkostenschätzungen erscheinen dort nicht als Geldwert oder tatsächlicher Punkteverbrauch. Andere Anbieter benötigen eine explizit unterstützte Kostenquelle und Währungsumrechnung.

## 6. Dauerhafte Verbrauchserfassung und unveränderte Protokolle

- Die vorhandenen Logs werden nicht umgeschrieben, umgerechnet, reduziert oder anders aufbewahrt. Insbesondere bleiben bestehende USD-Angaben in Betreiberlogs bestehen. Die Änderung ihrer Zugänglichkeit ist eine Berechtigungsänderung, keine Änderung der Protokollierung.
- Die Punkteanzeige erhält einen separaten, versionierten Verbrauchsbestand aus lesbaren JSON-/JSONL-Daten. Rotierende Diagnoselogs sind keine dauerhafte Grundlage für Verbrauchssummen.
- Je Anbieter-Versuch werden eine vor dem Aufruf persistierte interne Versuch-ID, gegebenenfalls Provider-ID, Instanz, Vorgang, Zweck, Beginn/Ergebniszeitpunkt, Kostenstatus, Bewertungsrevision, Originalkosten und Punkte gespeichert. Keine Mailvolltexte, Prompts oder Schlüssel in diesem Bestand.
- Wiederholte Zustellung desselben Ergebnisses, doppelte Logereignisse oder Neustarts verbuchen denselben Versuch höchstens einmal. Ein tatsächlich neuer Provider-Versuch erhält eine neue ID.
- Nach Prozessabbruch bei unklarem Provider-Ergebnis bleibt der Versuch sichtbar ungeklärt. Fehlende Kosten nicht erfinden und keinen kostenpflichtigen Aufruf nur für die Wiederherstellung der Anzeige wiederholen. Später nachgewiesene Ergebnisse werden idempotent ergänzt.
- Atomare Speicherung und Konfliktprüfung verhindern verlorene Änderungen. Zwischen Versuchsergebnis und Buchung unterbrochene Vorgänge werden beim Neustart abgeglichen. Eine nachgewiesene Korrektur bleibt nachvollziehbar und erzeugt keine zweite Belastung.
- Kunden dürfen diesen Bestand nicht verändern, exportierte interne Felder überschreiben oder über Log-/Archivbereinigung zurücksetzen. Sicherung, Wiederherstellung und Kontolöschung berücksichtigen ihn.
- Erfassung beginnt pro Instanz mit einem sichtbaren Startzeitpunkt. Keine automatische rückwirkende Bepreisung alter Logs mit dem neuen Aufschlag. Ein optionaler späterer Import benötigt ein gesondertes Verfahren mit Herkunfts- und Bewertungsnachweis.
- Für 8.7 bleibt der Verbrauchsbestand bis zur Beendigung beziehungsweise Löschung der Kundeninstanz erhalten; die Beendigung berücksichtigt die bestehenden kundenspezifischen Löschregeln einschließlich Backups. Eine eigenständige Abrechnungs-/Buchhaltungsaufbewahrung wird damit nicht eingeführt.

## 7. Kundenoberfläche und Ausgabekanäle

### 7.1 Verbrauchsansicht

- Einstieg „Verbrauch“ mit heute, laufendem Monat und Zeitraumwahl, stets mit Einheit „Punkte“.
- Verlauf nach Tag und Verarbeitungsschritt; Details mit Zeitpunkt, verständlichem Vorgang, Status und Punkten. Fachlicher Mailbezug nur innerhalb derselben Instanz.
- Bei unvollständigen Kosten: bekannte Punkte plus Zahl der noch ungeklärten Aufrufe. Keine irreführende vollständige Gesamtsumme.
- Kunden sehen keine Einkaufskosten, Wechselkurse, Aufschlagskonfiguration oder Roh-Providerantworten. Betreiber sehen weiterhin die bisherige technische Auswertung und zusätzlich Punkte/Bewertungsstand.
- Keine Anzeige „Restguthaben“, „Aufladen“ oder „Zahlung erforderlich“. Punkteverbrauch beendet keine KI-Verarbeitung; vorhandene technische Grenzen bleiben bestehen.

### 7.2 Vollständige Umstellung der Systemkosten

Die Inventur muss mindestens Übersicht, Auswertung, Aufruflisten, Diagrammachsen, Tooltips, barrierefreie Tabellen/ARIA-Texte, Lernschätzungen und Lernbudgets, Nachanalyse, Berichte, Hilfschat, Hinweise, Fehlermeldungen, Telegram, Web-Push, Druckansichten, Downloads und DE/EN-Texte erfassen.

- Kunden sehen dort für Systemkosten weder Euro noch Dollar, USD/EUR, Cent oder verdeckte Rohgeldwerte in HTML/JSON. Alte Geld-Detailparameter liefern eine berechtigungsgerechte Punkteansicht oder eine verständliche Ablehnung.
- Kostenhinweise lauten beispielsweise „Dieser Lauf verbraucht Punkte“ und „Geschätzter Verbrauch“. Unbekannte Werte werden als unbekannt bezeichnet.
- Die Ausgabe wird über eine gemeinsame rollenabhängige Präsentation vereinheitlicht, nicht über das Ersetzen einzelner Währungssymbole.
- Beträge aus Originalmails, Rechnungen, Aufgaben oder Kalenderbeschreibungen bleiben unverändert sichtbar. Die Vorgabe betrifft Mailhelps Systemverbrauch und darf fachliche Inhalte nicht verfälschen.
- Protokolle bleiben intern unverändert; Kunden erhalten daraus nur berechtigte fachliche Ansichten, keine Rohdateien mit Geldwerten oder technischen Geheimnissen.

## 8. Freischaltung, Betrieb und Einführung

1. Betreiber legt getrennte Instanz, Datenverzeichnis, Subdomain, Secrets und Auth-Instanzidentität an. Keine gemeinsame Kunden-Runtime oder übernommene Kundensitzungen.
2. Betreiber aktiviert Kundenmodus, setzt Bewertungsstand und richtet benötigte Betreiberschlüssel ein. Fehlende Konfiguration wird vor Freischaltung verständlich gemeldet.
3. Betreiber erzeugt den ersten Kundenzugang und prüft die reduzierte Oberfläche. Weitere Kundenkopplungen bleiben Kundenkopplungen.
4. Betreiber informiert über Supportzugriff, Punkteverbrauch und die vorerst unveränderte Protokollierung. Die Hinweise sind Bestandteil der Kundenunterlagen und Einrichtung.
5. Mit synthetischen Daten vollständigen Durchlauf und Isolation zweier Instanzen prüfen; danach persönlich betreuten Pilot starten.
6. Vor Produktivumstellung konsistente Sicherung einschließlich Rollen, Bewertungsständen und Verbrauchsbestand erstellen. Das bestehende dokumentierte Deploymentverfahren ([Serverhandbuch](Serverhandbuch.md)) einschließlich vorgeschriebener Hostpaketprüfung beachten.

Rückkehrverfahren: Kundenmodus bei einem Fehler nicht als Umgehung deaktivieren. Ein Rückwechsel auf eine Version ohne Rollen-/Verbrauchsschutz verlangt zuvor die Sperre des Kundenzugangs auf einer vorgelagerten Ebene. Datenstände erhalten, unklare Anbieteraufrufe abgleichen, Punktesummen nicht erneut aus alten Logs aufbauen. Wiederherstellung darf keine erneute Kalender-/Aufgabenanlage und keine doppelte Verbrauchsbuchung auslösen.

## 9. Arbeitspakete und Reihenfolge

| Paket | Inhalt | Fertig, wenn |
| --- | --- | --- |
| AP1 – Inventur und Rechte | Sämtliche Routen, Feldnamen, Befehle, Secrets, Kanäle, Downloads und Kostenansichten erfassen; Rollen-/Feldmatrix und Migrationsschema festlegen | Jeder Kundenweg ist einer expliziten Berechtigung zugeordnet; Geld-/Secret-Ausgaben sind vollständig erfasst |
| AP2 – Modus und Rollen | Betreiberkonfiguration, rollenbezogene Kopplung, Sitzung, Geräteverwaltung, zentrale Prüfungen und Hintergrundausführung | Direkte und verzögerte Kundenanfragen können keine Betreiberfunktion ausführen |
| AP3 – Punkte und Speicherung | Dezimalrechnung, versionierte Bewertung, Versuch-IDs, dauerhafter Bestand, Neustart-/Korrekturpfad | Istverbrauch wird genau einmal nach seinem gebundenen Stand bewertet; fehlende Angaben bleiben sichtbar |
| AP4 – Kundenansichten | Rechtegerechte Einstellungen, Secret-Schutz, Suche/Hilfe sowie Punktedarstellung über alle Kanäle | Keine Betreiberschlüssel oder Rohgeldwerte des Systemverbrauchs in Kundenantworten |
| AP5 – Freischaltung und Support | Manueller Ablauf, getrennte Betreiberkopplung, Einrichtungsprüfung, Kundenhinweise, Sicherung und Rückkehr | Zwei synthetische Kundeninstanzen vollständig getrennt bedienbar; Betreiberzugriff jederzeit möglich |
| AP6 – Abnahme | Fach-, Sicherheits-, Berechnungs-, Wiederanlauf- und Browsertests | Abnahmeszenarien bestanden; erforderliche Vollprüfungen ohne neue Befunde |
| AP7 – Dokumentation und Release | Hauptrepository, Spezifikation, Beispiele, Serverhandbuch, DE/EN-Hilfe, Index, README, CHANGELOG, Releasebericht, Serverkopie | Geplanter und tatsächlich ausgelieferter Stand sauber unterschieden und nachvollziehbar gesichert |

Die Pakete sind keine vorab fest zugesagten Einzelversionen. Erste nutzbare Auslieferung erst mit vollständiger Rechteprüfung und konsistenter Verbrauchsanzeige; keine Zwischenversion mit nur ausgeblendeten Schaltflächen für Kunden freischalten.

## 10. Verbindliche Abnahme

| Nr. | Szenario | Erwartung |
| --- | --- | --- |
| 1 | Kundenanmeldung und normale Kopplung | Ausschließlich Kundenrechte; kein Rollenwechsel durch manipulierte Eingaben |
| 2 | Betreiberzugang ohne Kundenzustimmung | Separat authentifiziert möglich; Kundenmodus bleibt aktiv |
| 3 | Eigene Postfächer, Ziele, Themen und Benachrichtigungen | Bestehende Vorschau-/Bestätigungsabläufe funktionieren |
| 4 | OpenRouter-Key per GET/POST, generischem Secret-Namen, Import, Diagnose oder Download | Kein Wert und keine Veränderung; auch kein Löschen oder Leiten an fremde KI-Endpunkte |
| 5 | Erlaubtes und gesperrtes Feld in einem Abschnittsformular | Gesamte Änderung abgelehnt, keine Teilübernahme |
| 6 | Gespeicherter Betreiberbefehl nach Sitzungswiderruf; Kundenbefehl für Betreiberaktion | Ausführung abgewiesen; keine privilegierte Fortsetzung |
| 7 | Kundengeräte, Telegram-Kopplung und alternative Kanäle | Keine Betreiberrolle und keine Verwaltung fremder/betreibergebundener Sitzungen |
| 8 | 0,01 USD, Kurs 1,25 USD/EUR, Aufschlag 25 Prozent | Genau 10 Punkte; mit Aufschlag 0 Prozent genau 8 Punkte |
| 9 | Kurs/Aufschlag geändert, während eine Anfrage läuft | Alter Versuch behält alten Stand; danach beginnende Versuche verwenden neuen Stand |
| 10 | Viele sehr kleine Verbräuche, Rundung, Monatsgrenze und Sommerzeit | Präzise Gesamtsumme; reine Anzeigerundung; keine doppelte Zuordnung |
| 11 | Echte Nullkosten, fehlende Kosten, ungültige Werte | Null bleibt null; fehlend/ungültig als unvollständig, nicht kostenlos |
| 12 | Retry/Fallback und wiederholtes Ergebnis desselben Versuchs | Neue kostenpflichtige Versuche zählen; dasselbe Ergebnis genau einmal |
| 13 | Prozessabbruch vor/nach Anbieterantwort und vor/nach Speicherung | Keine erfundene Kostenangabe, keine Doppelbuchung, ungeklärte Versuche sichtbar |
| 14 | Auswertung, Diagramm, Aufrufdetail, Lernbudget, Hilfschat, Exporte und DE/EN | Systemverbrauch nur in Punkten, auch in versteckten Feldern und barrierefreien Texten |
| 15 | Originalmail mit Rechnungsbetrag in Euro oder Dollar | Fachlicher Betrag bleibt unverändert sichtbar |
| 16 | Zwei Kundeninstanzen und vertauschte Cookies/Referenzen | Kein fremder Inhalt, kein fremder Verbrauch und kein fremder Secret-Zugriff |
| 17 | Logrotation/-bereinigung und unveränderte Logging-Konfiguration | Logs bleiben wie konfiguriert; dauerhafte Verbrauchssummen bleiben erhalten |
| 18 | Aktivierung auf bestehender Instanz | Rollenlose Sitzungen/Kopplungen widerrufen; kein rückwirkend erfundener Punkteverbrauch |
| 19 | Sicherung/Wiederherstellung und Rückkehr zur Altversion | Rollen und Verbrauch konsistent; bei Altversion Kundenzugang zuerst gesperrt |
| 20 | Hoher Punkteverbrauch ohne Guthabenfunktion | Keine neue guthabenabhängige Abschaltung oder Zahlungsaufforderung |

Für die Implementierung gelten die Projektvorgaben: sinnvolle Erfolgs-/Fehler-/Wiederholungs- und Autorisierungstests, 100 Prozent Zeilen- und Branch-Abdeckung des eigenen Codes, vollständige Python-Prüfung mit `python -m devtools.check full --workers 12`, danach die Browsersuite mit `python -m pytest ui_tests -n 6 --dist worksteal --no-cov`; Python- und Browserprüfung nicht parallel. Ruff und mypy ohne neue Befunde. Desktop, Smartphone, Tastaturbedienung und Bedienung ohne JavaScript abnehmen. Externe Dienste in automatisierten Tests simulieren; echte Konten nicht für Sicherheitsfälle verwenden.

## 11. Abgrenzung und Abschluss

8.7 führt keine Selbstregistrierung, Zahlungsabwicklung, Rechnungsstellung, Punktepakete, Guthabenverwaltung, neue Logging-Vorgaben oder gemeinsame Mehrkunden-Runtime ein. Ein Tarif kann später auf dem Verbrauch aufbauen, benötigt aber eine eigene Planung.

Vor der ersten Kundenfreischaltung müssen ein gültiger Wechselkurs und der gewünschte Aufschlag gesetzt sein. Das sind Betreiberwerte, keine noch offene Architekturfrage. Für die Planung werden keine realen Schlüssel benötigt.

Vor Implementierung den aktuellen Branchstand und neue beziehungsweise geänderte Routen erneut inventarisieren. Der Releasebericht dokumentiert danach tatsächliche Umsetzung, Prüfergebnisse, Abweichungen und den ausgelieferten Versionsstand.
