# Mailhelp 5.3 – Live-Suche, Hilfschat und geprüfte Dokumentation

**Zielversion:** 5.3.0, Umsetzung in Patchversionen 5.3.x  
**Stand:** 9. November 2026  
**Status:** Abgeschlossen (5.3.0 bis 5.3.11). Abnahme, Nachweise und Grenzen: [Release 5.3](Release-5.3.md), [Prüfbericht](Pruefung-Dokumentation-5.3.md)  
**Grundlage:** [Entwicklungsregeln](../AGENTS.md), [Projektspezifikation](../Mailhelp-Projektspezifikation.md), [Qualitätsregeln 4.1](Qualitaet-4.1.md)  
**Vorgänger:** [Planung 5.2](Planung-5.2.md) – Aufgaben und Termine nach dem Eintragen überprüfen  
**Technischer Ausgangsstand:** Lokaler Arbeitsstand 5.0.7 laut `pyproject.toml` und README.
Die Umsetzungen von 5.0 bis 5.2 werden vor Beginn erneut abgeglichen. Geplante Funktionen
gelten erst nach ihrer tatsächlichen Umsetzung als dokumentierbarer Iststand.

## 1. Ziel und Umfang

Die Einstellungsseite soll beim Finden und Verstehen von Einstellungen helfen:

1. **Live-Suche:** Bereits beim Eintippen erscheinen passende Ergebnisse direkt unter
   dem Suchfeld, ohne Klick auf „Suchen“ und ohne vollständiges Neuladen der Seite.
2. **Hilfschat:** Ein Chat erklärt Einstellungen und führt durch Bedienabläufe. Er nutzt
   dieselbe aktive LLM-Anbindung wie die normalen Abfragen und erhält für jede Frage
   passende Ausschnitte aus der geprüften Mailhelp-Dokumentation.
3. **Dokumentationsprüfung:** Alle aktuellen Einstellungen und Funktionen werden mit
   dem Code abgeglichen. Erläuterungen, Beispiele und Anleitungen werden korrigiert,
   vervollständigt und auf Verständlichkeit geprüft.

Beispiel: Eine Person tippt „Abruf“ und sieht sofort „Abrufintervall“, den zugehörigen
Bereich und eine kurze Erklärung. Über „Dazu fragen“ fragt sie, ob 60 oder 300 Sekunden
sinnvoll sind. Der Chat erklärt den Unterschied anhand der Dokumentation und verlinkt
die Einstellung sowie den verwendeten Dokumentationsabschnitt.

Die vorhandenen Bearbeitungs- und Bestätigungsabläufe bleiben maßgeblich. Der Chat
erklärt und verlinkt; er verändert weder Einstellungen noch Konten oder externe Daten.
Eine umfassende neue Gestaltung aller Einstellungsformulare gehört nicht zum Umfang.

## 2. Geprüfter Ausgangspunkt

Die folgende Bestandsaufnahme ist eine gezielte Grundlage für die Planung, noch keine
vollständige Dokumentationsabnahme.

| Baustein | Beobachteter Stand | Konsequenz für 5.3 |
| --- | --- | --- |
| [Einstellungsrouten](../src/mailhelp/web/settings_site.py) | Authentifiziertes `GET /einstellungen`, Bereichsauswahl und Suchparameter `suche`; Suchtext wird auf 80 Zeichen begrenzt. | Bestehende Route als Formular-Rückfall erhalten; lesenden Suchendpunkt ergänzen. |
| [Suchdarstellung](../src/mailhelp/web/settings_pages.py) | `_found` sucht ohne Beachtung der Großschreibung nach allen eingegebenen Wörtern in Bezeichnung, Schlüssel, Gruppe und Bereich. Ergebnisse enthalten vollständige Einstellungsformulare. | Gemeinsame Suchlogik und kompakte Live-Treffer ergänzen; keine Formulare beim Tippen austauschen. |
| Umfang der Suche | Die Suche geht durch die allgemeinen Einstellungsgruppen. Verbindungen, Themenpflege und andere Sonderseiten sind als Kacheln erreichbar. | Auch diese Wege über öffentliche Bezeichnungen und kuratierte Suchbegriffe auffindbar machen. |
| [Feldhilfen](../src/mailhelp/web/setting_help.py) und [Referenz](Web-Einstellungen.md) | Gemeinsame Erläuterungen sind vorhanden; viele nennen Wertebereiche, Folgen und Beispiele. | Vorhandene Texte fachlich prüfen und weiterverwenden. |
| [Hilfetests](../tests/web/test_setting_help.py) | Prüfen unter anderem `SETTING_HELP == SETTINGS_FIELDS` und das Vorkommen derselben Texte in der Referenz. | Zusätzlich die fachliche Richtigkeit und die Abdeckung außerhalb von `SETTINGS_FIELDS` prüfen. |
| [LLM-Auflösung](../src/mailhelp/config/models.py) und [Analyse](../src/mailhelp/processing/analysis.py) | Defaults, schrittspezifische Routen, strukturierte Antworten und begrenzte Fehlerbehandlung sind vorhanden. | Chat als eigenen Prompt-Schritt in diese Infrastruktur integrieren. |
| [OpenRouter](../src/mailhelp/llm/openrouter.py) und [Ollama](../src/mailhelp/llm/ollama.py) | Bestehende Adapter berücksichtigen Budget, Wiederholungen und Protokollierung; Ollama verwendet den gemeinsamen Aufrufpfad mit eigenen Protokollanpassungen. | Keine unabhängige Chat-API oder zweite Zugangsdatenverwaltung aufbauen. |
| Dokumentationsstand | `Web-Einstellungen.md` nennt 4.8.6, `Einrichtung-und-Qualitaetspruefung.md` 4.1.11; [Pruefung-Dokumentation.md](Pruefung-Dokumentation.md) bezieht sich auf 3.3.1. | Versionsangaben und Inhalte erneut prüfen; ältere Prüfberichte sind kein Nachweis für 5.3. |
| [README-Navigation](../README.md#dokumentation) | Führt für manche aktuellen Aufgaben zu älteren Release-Anleitungen. | Aktuelle Aufgabenanleitungen als Einstieg anbieten; historische Berichte getrennt kennzeichnen. |

Ein älterer Versionskopf beweist für sich allein keinen fachlichen Fehler. Umgekehrt
beweist ein mit der Oberfläche identischer Hilfetext noch keine Übereinstimmung mit
Validierung, Laufzeitverhalten oder tatsächlicher Übernahme einer Einstellung.

## 3. Bedienkonzept der Einstellungsseite

- Das Suchfeld steht auf der Übersicht und den allgemeinen Einstellungsbereichsseiten
  gut sichtbar über dem Inhalt. Eine Suche aus einem Bereich durchsucht alle Einstellungen.
- Unter dem Feld steht ein eigener Ergebnisbereich. Ohne Suchtext bleibt er leer;
  Übersicht beziehungsweise geöffneter Bereich bleiben sichtbar.
- Treffer zeigen Bezeichnung, Bereich, kurze Wirkungserklärung und gegebenenfalls
  den technischen Schlüssel. Ein Klick öffnet die betreffende Einstellung.
- Ein sichtbarer Einstieg „Hilfe zu Einstellungen“ öffnet den Chat. „Dazu fragen“ an
  einer Einstellung oder einem Suchtreffer öffnet ihn mit dem öffentlichen Feldbezug.
- Desktop: einklappbarer Hilfebereich neben dem Inhalt, sofern ausreichend Platz besteht.
  Smartphone und Tablet: eigener aufklappbarer Bereich mit vollständig erreichbarem
  Eingabefeld und Schließen-Schaltfläche. Keine Überdeckung der Speicherbestätigung.
- Suchfeld, Treffer und Chat bleiben per Tastatur bedienbar. Schließen gibt den Fokus
  an den ursprünglichen Auslöser zurück; Eintippen aktiviert keine globalen Tastenkürzel.
- Ohne JavaScript bleiben normale Suche, Einstellungen und Quellen erreichbar.
  Der Chat bietet einen serverseitigen Formularablauf mit Statusseite und erneutem
  Laden des Ergebnisses; eine laufende LLM-Antwort blockiert keinen Webaufruf.

## 4. Live-Suche

### 4.1 Suchverhalten

1. Das `input`-Ereignis erfasst Tippen, Einfügen, Löschen und Leeren. Während einer
   Eingabekomposition wird kein unvollständiger Suchlauf gestartet.
2. Nach **150 ms ohne weitere Eingabe** beginnt die Suche, bereits ab einem sichtbaren
   Zeichen. Dieser Wert ist eine feste Oberflächenvorgabe, keine neue Kontoeinstellung.
3. Die Treffer erscheinen unmittelbar unter dem Suchfeld. Es gibt eine dezente
   Ladeanzeige, eine Trefferzahl und eine verständliche Anzeige bei null Treffern.
4. Eine neue Eingabe bricht den vorherigen Browserabruf ab. Zusätzlich verhindert eine
   laufende Anfragenummer, dass verspätete Antworten den neueren Suchstand überschreiben.
5. Leeren entfernt Treffer, Ladezustand und Fehlermeldung sofort. Abgebrochene Abrufe
   gelten nicht als Suchfehler. Bei einem echten Fehler bleibt die normale Suche nutzbar.
6. „Suchen“ beziehungsweise Enter führt weiterhin zur vollständigen Ergebnisseite
   mit `?suche=…`. Der Live-Modus erzeugt keinen Browser-Historieneintrag je Buchstabe.

Die Suche braucht **keinen LLM-Aufruf**. Sie verwendet ausschließlich öffentliche
Metadaten der Einstellungen, Hilfetexte und geprüfte Suchbegriffe. Passwörter, aktuelle
Konfigurationswerte, Mailinhalte und private Kontobezeichnungen werden nicht durchsucht.

### 4.2 Gemeinsamer Suchkatalog

Ein strukturierter Katalog verbindet Oberfläche, Suche und Dokumentationsreferenz:

| Information | Verwendung |
| --- | --- |
| Stabile Kennung und optionaler Konfigurationsschlüssel | Eindeutige Zuordnung; keine Suche über sichtbare Positionen |
| Bezeichnung, Bereich und Gruppe | Trefferanzeige und Navigation |
| Öffentliche Kurzbeschreibung und vollständige Hilfe | Erklärungen sowie zusätzliche Suchbegriffe |
| Kuratierte Synonyme | Beispielsweise „KI“/„LLM“, „Postfach“/„Konto“, „Abruf“/„Intervall“ |
| Zielroute und stabiler Feldanker | Direkter Sprung zum passenden Formular |
| Dokumentationskennung und Abschnitt | „Nachlesen“ und Bezug für den Hilfschat |
| Sichtbarkeit/Voraussetzungen | Nur tatsächlich verfügbare oder als bedingt gekennzeichnete Funktionen anbieten |

Die vorhandenen Listen und Hilfen werden eingebunden und schrittweise konsolidiert.
Ein zweiter, von `SETTINGS_FIELDS` unabhängiger Bestand allgemeiner Feldtexte soll
nicht entstehen. Sonderseiten erhalten eigene Katalogeinträge, etwa Postfach hinzufügen,
IServ, Zielprofile, Themen, ignorierte Absender, Zugangsdaten und Neuladen.
Die Referenz erfasst auch Einstellungen, die ausschließlich per Datei oder Assistent
änderbar sind; Treffer kennzeichnen diesen Bedienweg ausdrücklich.

Vergleichsregeln: Leerraum normalisieren, Großschreibung ignorieren, deutsche Umlaute
und ausgeschriebene Formen wie `ä`/`ae` gleich behandeln. Alle Suchwörter müssen nach
dieser Normalisierung in den Metadaten eines Treffers vorkommen. Reihenfolge:
exakter Schlüssel oder exakte Bezeichnung vor Wortanfang, danach sonstige Teiltreffer
und Hilfetexttreffer; stabile alphabetische Sortierung bei gleichem Rang.
Unscharfe Tippfehlerkorrektur ist für 5.3 nicht erforderlich.

Maximal zehn kompakte Treffer werden direkt angezeigt. Weitere Treffer sind über
„Alle Ergebnisse anzeigen“ erreichbar. Live- und Formularsuche verwenden dieselbe
Normalisierung, Bewertung und Gesamtmenge; nur Umfang und Darstellung unterscheiden sich.

### 4.3 Technische und zugängliche Umsetzung

- Vorgesehener Endpunkt: `GET /api/einstellungen/suche?suche=…`, nur für gültige
  Websitzungen. Maximal 80 Unicode-Zeichen nach derselben Regel wie die Formularsuche;
  Webserver-Limits begrenzen zusätzlich die gesamte Anfrage.
- Antwort enthält strukturierte Treffer, Gesamtzahl und normalisierten Suchbezug.
  Keine Formularwerte, CSRF-Token oder Zugangsdaten in der Suchantwort.
- Zielrouten entstehen ausschließlich serverseitig aus zugelassenen Einträgen.
  Neue stabile Feldanker öffnen bei Bedarf das zugehörige `details`-Element und
  machen die Einstellung auch nach einem direkten Seitenaufruf sichtbar.
- Darstellung über sichere Textknoten; keine Ausführung von Suchtext oder Modell-HTML.
  Treffer sind normale Links in einer beschrifteten Liste, kein unnötig komplexes Auswahlmenü.
- Eine zusammengefasste `aria-live="polite"`-Meldung nennt Trefferzahl beziehungsweise
  Fehler nach dem Suchlauf. Sie liest nicht jede gesamte Trefferliste erneut vor.
- Kein Fokuswechsel beim Tippen, keine Löschung bereits bearbeiteter Formulare.
  Tastatur, Touch, Hell-/Dunkelmodus und kleine Bildschirmbreiten werden geprüft.
- API-Antworten und authentifizierte Hilfeseiten erhalten `Cache-Control: no-store`;
  die PWA legt weder Suchantworten noch Chatdaten im Offline-Cache ab.

**Abnahmewert:** Auf einem im Prüfbericht benannten lokalen Referenzsystem mit
vollständigem Suchkatalog sind Treffer bei mindestens 95 % der Messungen innerhalb
von 300 ms nach der letzten Eingabe sichtbar, einschließlich der 150-ms-Verzögerung.
Gemessen werden mindestens 100 Suchläufe mit kurzen und mehrteiligen Begriffen.
Automatisierte Funktionstests warten auf Zustände statt auf starre Schlafzeiten.

## 5. Hilfschat und LLM-Anbindung

### 5.1 Inhalt und Grenzen

Der Chat beantwortet Fragen zur Bedienung, Bedeutung und Einrichtung, beispielsweise:

- „Was bewirkt das Abrufintervall, und wann sollte ich es erhöhen?“
- „Wie lege ich ein zweites Postfach an und ordne ihm einen anderen Kalender zu?“
- „Was ist der Unterschied zwischen Speichern, Aktivieren und Neuladen?“
- „Was wird an die KI übertragen, wenn ich Bildauswertung einschalte?“
- „Warum ist diese Änderung noch nicht aktiv?“ – zunächst eine allgemeine Erklärung
  der dokumentierten Zustände, keine behauptete Diagnose der konkreten Installation.

Antworten sind deutsch, beginnen mit einer direkten Erklärung und enthalten bei
Bedienfragen nummerierte Schritte. Verwendete Quellen erscheinen unter der Antwort
mit Titel, Abschnitt und Link. Fehlt eine belastbare Grundlage, benennt der Chat die
Lücke und bietet passende Dokumentationswege oder eine gezielte Rückfrage an.
Er erfindet weder Einstellungen noch aktuelle Werte, Bedienwege oder Prüfergebnisse.

Der Chat erhält keine Werkzeuge zum Ändern von Einstellungen, Verbinden von Konten,
Schreiben in Kalender/Aufgabenlisten oder Senden von Nachrichten. Links führen in
die bestehenden Oberflächen. Auch „Stelle das für mich um“ bleibt eine Anleitung.
Jeder Google-Kalender-/Todoist-Schreibzugriff benötigt weiterhin die ausdrückliche,
versionsbezogene Bestätigung über Telegram oder die authentifizierte Weboberfläche.

### 5.2 Bedeutung von „dasselbe LLM“

- Wiederverwendung des aktiven `Completer` und der vorhandenen Modellauflösung,
  Timeout-/Retry-Regeln, Budgetreservierung und Messung.
- Neuer Prompt-Schritt `settings_help` in `prompts.yaml`; Systemtext, Modellbezug,
  LLM-Parameter und gegebenenfalls Routen stehen ausschließlich dort.
- Standardfall: dasselbe Defaultmodell wie die Mailabfragen. Bei unterschiedlichen
  Modellen pro Schritt wird `action_router` als dokumentierter Referenzschritt für
  die effektive Modell-/Anbieterroutenfolge verwendet. Dafür ist eine explizite,
  validierte Routenreferenz vorzusehen, keine kopierte Modellzeichenkette.
- Der aktive Ollama-Modus und dessen Laufzeit-Modellwahl gelten auch für den Chat.
  Ein Wechsel der aktiven LLM-Konfiguration wirkt bei der nächsten neuen Chatfrage;
  ein laufender Aufruf bleibt an seinen beim Start erfassten Stand gebunden.
- Eigener Hilfeprompt und begrenzte Antwortlänge sind erlaubt; ein separates
  Chatmodell oder neue Chat-Zugangsdaten werden in 5.3 nicht eingeführt.
- Für alle Versuche einschließlich strukturierter Antwortkorrektur gelten dieselben
  vorhandenen Aufrufzähler. Es gibt keine parallele Chat-Budgetverwaltung, die das
  globale Minutenlimit umgeht. Chatfragen erhalten zusätzlich ein enges Sitzungslimit.

`PromptConfig` erlaubt momentan nur bekannte erforderliche und optionale Schritte.
`settings_help` sowie die Routenreferenz müssen ausdrücklich validiert und mit den
bestehenden Aufrufpfaden getestet werden. Antwortverarbeitung und Providerfehler
werden über den vorhandenen klassifizierten Aufrufpfad integriert.

### 5.3 Ablauf und Antwortvertrag

1. Die Person öffnet den Chat und sendet eine Frage ausdrücklich ab. Tippen, Suche
   und das Öffnen einer Feldhilfe lösen keinen Modellaufruf aus.
2. Der Server prüft Sitzung, CSRF, Chatversion, Idempotenzschlüssel, Textgrenzen,
   Aktivierungszustand und verfügbare Budgets.
3. Er ermittelt relevante Dokumentationsabschnitte anhand von Frage, begrenztem
   bisherigen Verlauf und optionaler öffentlicher Einstellungskennung.
4. Ein begrenzter Hintergrundauftrag prüft die Sitzung unmittelbar vor dem
   kostenpflichtigen Aufruf erneut und nutzt den aktiven LLM-Aufrufpfad.
5. Eine strukturierte Antwort wird validiert, sicher angezeigt und an die zum
   Auftrag gehörende Chatversion angehängt. Der Server löst Quellenkennungen auf.

Vorgesehener Antwortvertrag: `answer`, `source_ids`, `setting_ids` und `needs_clarification`.
Längen und Anzahl der Einträge sind begrenzt. Quellen müssen aus dem tatsächlich
übergebenen Kontext stammen, Einstellungskennungen aus dem freigegebenen Katalog.
Freie Modell-URLs werden nicht als Quellen übernommen. Unbekannte Kennungen ergeben
eine ungültige Antwort und höchstens die bestehenden begrenzten Korrekturversuche.
Bei fehlenden Quellen erfolgt eine lokale Hinweismeldung ohne LLM-Aufruf.

Der Quellenvertrag beweist die Herkunft der Abschnitte, nicht automatisch die
Richtigkeit jeder Modellbehauptung. Fachliche Antwortqualität wird separat geprüft.
Vorherige Modellantworten sind Gesprächsverlauf, keine neuen Dokumentationsbelege.

### 5.4 Ladezustände, Fehler und Wiederholung

Vorgesehene Zustände: `queued`, `running`, `completed`, `failed`, `interrupted`, `cancelled`.
Ein kurzer POST legt den Auftrag an; authentifizierte Statusabfragen liefern den Stand.
Serverseitige Formularbedienung verwendet dieselben Aufträge und Ansichten.

- Die Oberfläche zeigt „Antwort wird vorbereitet“ und danach Antwort, Quellen oder
  einen verständlichen Fehler mit nächstem Schritt. Es gibt kein vorgetäuschtes Streaming.
- Doppelklick und erneuter POST mit gleichem Schlüssel und identischem Inhalt liefern
  denselben Auftrag; anderer Inhalt mit gleichem Schlüssel ergibt einen Konflikt.
- Pro Chat läuft höchstens eine Frage. Neue Tabs und parallele Sitzungen werden
  zusätzlich durch einen begrenzten gemeinsamen Worker-Pool abgesichert.
- Ein Budgetlimit zeigt die früheste erneute Möglichkeit. 401/403, 429, Timeout,
  ungültige Antwort und ausgeschöpftes Korrekturbudget haben eigene sichere Meldungen.
- Browserabruf wiederholen bedeutet Status lesen, keinen neuen Modellaufruf starten.
  Ein bewusst neuer Versuch nach endgültigem Fehler erhält einen neuen Schlüssel.
- Nach einem Prozessabbruch werden offene Aufträge als unterbrochen ausgewiesen und
  nicht automatisch erneut kostenpflichtig gesendet. Ein providerseitig bereits
  bearbeiteter Aufruf kann trotzdem Kosten verursacht haben; diese Unsicherheit
  darf nicht durch eine behauptete erfolgreiche Antwort verdeckt werden.
- „Chat leeren“ verwirft den Verlauf und erhöht die Chatversion. Spätere Ergebnisse
  älterer Aufträge werden nicht mehr angehängt. Ein bereits gestarteter externer
  Aufruf kann dadurch nicht zuverlässig rückgängig gemacht werden.

LLM-Netzwerkaufrufe und Wartezeiten finden außerhalb von Zustands- und
Konfigurationssperren statt. Einstellungen, Freigaben und Mailverarbeitung bleiben
bedienbar. Es werden keine unbegrenzten Threads oder Warteschlangen erzeugt.

## 6. Relevante Dokumentation als Kontext

### 6.1 Freigegebene Quellen

Der Chat verwendet einen mit der Anwendung ausgelieferten, versionsgebundenen
Dokumentationsbestand. Geeignet sind die geprüfte Einstellungsreferenz und aktuelle
Benutzeranleitungen. Die Projektspezifikation dient als Prüfgrundlage; nur ausdrücklich
freigegebene, bedienrelevante Abschnitte daraus gelangen in den Hilfebestand.

Historische Releaseberichte, alte Qualitätsberichte, Planungsdokumente, Changelog,
beliebige Projektdateien und private Laufzeitdateien sind keine automatischen Chatquellen.
Auch diese Planung selbst ist kein Nachweis vorhandener Funktionen.
Keine `.env`, Token-Dateien, Logs, Mailakten oder komplette `config.yaml` im Index.

Jeder Abschnitt enthält stabile Quellenkennung, Titel, Überschriftenpfad, Inhalt,
Anwendungsversion, Dokumentationsrevision/Hash, Themenbegriffe und Einstellungsbezüge.
Die Indexerzeugung erfolgt reproduzierbar aus einer ausdrücklichen Quellenliste.
Inhalte werden nach Überschriften in sinnvolle Abschnitte zerlegt; zusammenhängende
Schrittfolgen bleiben soweit möglich vollständig.

### 6.2 Auswahl und Kontextbudget

- Lokale, deterministische Volltextsuche mit gewichteten Treffern für Titel,
  Einstellungskennungen, Synonyme und Abschnittstext; keine neue Embedding-API.
- Konkrete Feldbezüge erhalten Vorrang. Anschlussfragen wie „Und pro Postfach?“
  nutzen den begrenzten Verlauf und dessen letzte Feld-/Themenbezüge.
- Höchstens sechs Abschnitte werden übergeben; Dopplungen werden entfernt.
  Wichtige Voraussetzungen und Abhängigkeiten dürfen nicht kommentarlos abgeschnitten werden.
- Der geplante Dokumentationsrahmen von 24.000 UTF-8-Bytes ist eine zusätzliche
  Obergrenze. Vor jedem Aufruf wird die gesamte Nutzlast einschließlich Frage,
  Verlauf, Prompt, Antwortschema und Antwortreserve gegen die geltenden Grenzen
  geprüft. Bytezahl und Tokenbudget werden nicht gleichgesetzt.
- Ist der Kontext zu groß, entfallen zunächst ältere Gesprächsteile und nachrangige
  Abschnitte. Reicht auch das nicht, folgt eine verständliche Bitte zur Eingrenzung.
- Bei unklarer Suche wird nachgefragt. Ein Zusammenhang darf nicht durch einen
  beliebigen Abschnitt mit einem einzelnen gemeinsamen Wort behauptet werden.
- Index und Antwortauftrag tragen dieselbe Dokumentationsrevision. Ein späteres
  Update darf alte Antworten nicht mit neuen, inhaltlich anderen Quellen beschriften.

Ein lokaler, authentifizierter Dokumentationsleser macht die freigegebenen Abschnitte
auch ohne LLM erreichbar, beispielsweise unter `/hilfe/dokumentation/<kennung>`.
Damit funktionieren Quellenlinks in Windows-Installation, Wheel und Docker ohne
Repository-Checkout oder Abhängigkeit von einer externen Website.

### 6.3 Auslieferung und Ausfallverhalten

Die geprüften Quellen beziehungsweise ihr generierter Index werden als Paketressourcen
mit Versionsmanifest ausgeliefert. Ein Buildtest stellt sicher, dass ihr Inhalt dem
freigegebenen Quelldokument entspricht. Es gibt keine manuell abweichende zweite Kopie.
Wheel, Quellarchiv und Docker-Image werden außerhalb des Checkouts geprüft.

Fehlender, beschädigter oder nicht zur Anwendung passender Bestand deaktiviert die
Chatantwort mit klarer Meldung. Die lokale Einstellungsseite und die normale Suche
bleiben nutzbar. Ein Upgrade benötigt weder externe Indexdienste noch automatische
kostenpflichtige Aufrufe oder eine Durchsuchung privater Daten.

## 7. Sicherheit, Datenschutz und Speicherung

- Such-, Chat-, Status- und Dokumentationsrouten sind authentifiziert. Jeder Zugriff
  prüft die aktuelle Sitzung; Aufträge und Verlauf gehören ausschließlich ihrer
  Ursprungssitzung. Erratbare IDs geben keine fremden Chatdaten frei.
- Zustandsändernde Chataktionen benötigen CSRF, Versionsbezug und Idempotenzschlüssel.
  Ein abgemeldeter oder widerrufener Auftrag startet keinen weiteren Modellversuch.
  Nach Sitzungsablauf werden Ergebnisse nicht mehr ausgeliefert.
- Fragen, Dokumentationszitate und LLM-Ausgaben sind nicht vertrauenswürdige Daten.
  Der Systemprompt trennt Anweisungen und Quellen; zusätzlich verhindern fehlende
  Werkzeuge, validierte Kennungen und sichere Ausgabe konkrete Schreib- und HTML-Aktionen.
- Keine rohe HTML-Ausgabe. Formatierte Antworten nutzen nur eine eng begrenzte,
  sichere Darstellung; Quell- und Einstellungslinks erzeugt der Server selbst.
- Vor dem Absenden steht sichtbar: Frage, begrenzter Verlauf und passende öffentliche
  Dokumentation gehen an den aktiven KI-Anbieter. Keine Passwörter oder Tokens eingeben.
  Bekannte Geheimnisse werden vor Übertragung und Speicherung entfernt; dies ersetzt
  keine zuverlässige Erkennung beliebiger unbekannter Geheimnisse.
- Es werden keine aktuellen Einstellungswerte automatisch beigefügt. Der Feldbezug
  besteht nur aus Kennung, Bezeichnung und öffentlicher Dokumentation.
- Kurzlebiger Chat- und Auftragszustand liegt sitzungsgebunden in lesbarem JSON unter
  dem bestehenden Betriebsdatenverzeichnis, nicht in JSONL-Ereignislogs. Enthalten sind
  nur erforderlicher Verlauf, Version, Status, Quellenrevision und Auftragskennungen;
  keine Sitzungscookies oder Authentifizierungstoken.
- Aufbewahrung höchstens 24 Stunden seit letzter Aktivität, zusätzlich begrenzt durch
  das Sitzungsende. „Chat leeren“, Abmeldung/Widerruf und regelmäßige Bereinigung löschen
  Inhalte; beim Start wird überfälliger Zustand ebenfalls bereinigt.
- JSONL-Logs enthalten standardmäßig nur Ereigniscodes, Zeit, Aufruf-/Auftragskennung,
  Status und Messwerte. Fragen, Antworten und Quellenpayloads gelten als vollständige
  LLM-Inhalte und erscheinen nur bei ausdrücklich aktivierter Inhaltsprotokollierung.
  Die vorhandenen Inhaltslog-Schalter und Redaktionsregeln werden durchgängig geprüft.

Der vorhandene Trockenlauf simuliert nicht automatisch jede LLM-Anfrage. Der Hilfschat
verwendet den aktiven KI-Anbieter auch im Trockenlauf und weist auf denselben Kosten-
und Datenfluss hin. Automatisierte Tests verwenden ausschließlich simulierte Dienste.

## 8. Konfigurationsvertrag und Upgrade

Die folgenden Werte sind Planvorgaben und noch keine bestehenden Einstellungen:

```yaml
# config.yaml / config.example.yaml
help_chat:
  enabled: true
  max_question_chars: 4000
  max_context_bytes: 24000
  requests_per_minute_per_session: 6
```

| Einstellung | Bedeutung und Validierung | Übernahme |
| --- | --- | --- |
| `help_chat.enabled` | Chat anbieten; `false` verhindert neue Aufträge und weitere Aufrufversuche. Lokale Dokumentation bleibt lesbar. | Nächster sicherer Punkt; vor jedem Aufruf erneut prüfen |
| `help_chat.max_question_chars` | 100–8000 Zeichen; 4000 reichen für eine ausführliche Bedienfrage. Größere Eingaben werden erklärt abgewiesen, nicht still gekürzt. | Für neue Fragen |
| `help_chat.max_context_bytes` | 2000–48000 Bytes Dokumentationskontext; tatsächliche Grenzen von Nutzlast und Modell gelten zusätzlich. | Für neue Fragen |
| `help_chat.requests_per_minute_per_session` | 1–20 neue Fragen je Sitzung und rollierenden 60 Sekunden; Wiederholung desselben Auftrags verbraucht keinen zweiten Frageplatz. Globale LLM-Grenzen bleiben zusätzlich wirksam. | Vor Annahme neuer Fragen |

Die feste Obergrenze beträgt zehn vorherige Frage-Antwort-Paare, maximal sechs
Quellabschnitte und höchstens 24 Stunden Inhaltsaufbewahrung. Diese Grenzen sind
ebenfalls zu dokumentieren und zu testen; zusätzliche Schalter sind zunächst unnötig.
Ein global begrenzter Worker-Pool und eine begrenzte Warteschlange verhindern Last
durch viele Sitzungen; die konkreten Kapazitäten werden in Schritt H1 festgelegt.

Alle neuen Felder erhalten verständliche UI-Hilfe, Beispiele, Suchbezug und die passende
Einordnung in `SETTINGS_FIELDS`/`LIVE_FIELDS`. Fehlende Felder nutzen die dokumentierten
Defaults, ohne bestehende Konfigurationen umzuschreiben. Modell-/Promptangaben bleiben
in `prompts.yaml`, Themen in `topics.yaml`, Geheimnisse außerhalb des Codes.

Bei vorhandenen eigenen `prompts.yaml` wird `settings_help` nicht still in einen
individuell gepflegten Promptbestand eingefügt. Fehlt der optionale Schritt, bleibt
der übrige Betrieb kompatibel; der Chat zeigt einen konkreten Einrichtungshinweis.
Die Upgrade-Anleitung beschreibt das Übernehmen des Schritts und der validierten
Routenreferenz. Paketdefaults werden entsprechend ergänzt. Chatänderungen dürfen keine
unbemerkte Neuanalyse vorhandener Mails oder Entwertung bestehender Lernläufe auslösen;
Fingerprint- und Prompt-Gate-Auswirkungen sind ausdrücklich zu prüfen.

## 9. Vollständige Prüfung der Dokumentation

### 9.1 Inventur mit Abdeckungsmatrix

Ausgangspunkt ist der tatsächliche Code des späteren 5.3-Kandidaten, einschließlich
der bis dahin umgesetzten Funktionen aus 5.1 und 5.2. Ein neuer Prüfbericht
`docs/Pruefung-Dokumentation-5.3.md` nennt Version, Commit/Arbeitsstand, Prüfumfang,
Abweichungen, Korrekturen und verbleibende Grenzen.

Für **jede Einstellung und jede Benutzerfunktion** entsteht eine nachvollziehbare Zeile:

| Pflichtangabe | Zweck |
| --- | --- |
| Schlüssel/Funktionskennung und Bereich | Eindeutiger Bestand einschließlich globaler und postfachbezogener Varianten |
| Codefundstelle und Verhaltenstest | Nachweis des tatsächlichen Vertrags |
| Bedienweg oder Datei/CLI | Wo die Funktion verfügbar ist und wie man sie erreicht |
| Typ, Standard, Wertebereich, Einheit, Sonderwerte | Korrekte Eingabe und überprüfbare Beispiele |
| Voraussetzungen, Vererbung und Priorität | Globale Vorgabe, Postfachüberschreibung, Umgebungsvariablen oder Laufzeitoptionen |
| Aktivierung und Wirkung | Sofort, sicherer Verarbeitungspunkt, Neuladen, Neustart oder versionsbezogene Übernahme |
| Dokumentationsabschnitt und Beispiel/Anleitung | Auffindbare Hilfe für die konkrete Aufgabe |
| Prüfstatus und Befund | Korrekt, fehlt, veraltet, widersprüchlich oder unverständlich; mit Behebung und Nachprüfung |

Die Inventur umfasst Konfigurationsmodelle und Validatoren, `SETTINGS_FIELDS`,
`LIVE_FIELDS`, Einrichtungsformulare, Postfach- und IServ-Einstellungen, Zielprofile,
Benachrichtigungen, `.env.example`, CLI-Optionen, Promptoptionen sowie alle erreichbaren
Bedienfunktionen. Zugangsdaten werden über Namen und Bedeutung dokumentiert, nie über
echte Werte. Bewusst interne Felder werden mit Begründung abgegrenzt, nicht übergangen.

Technische Abdeckung ist zählbar: **100 % der inventarisierten öffentlichen Einstellungen
und Funktionen haben einen aktuellen, geprüften Dokumentationsbezug.** Für jeden
abgegrenzten internen Eintrag bleibt die Begründung sichtbar. Es darf keine offene
wesentliche fachliche Abweichung zur Releasefreigabe geben.

### 9.2 Fachlicher Abgleich

Für jeden Bereich werden Dokumentation, Validierung, Laufzeitverwendung, Oberfläche,
Tests und Beispiele gemeinsam gelesen. Besonderes Augenmerk gilt:

- Tatsächlichen Defaults gegenüber Werten in Beispielkonfigurationen. Ein gesetzter
  Beispielwert ist nicht automatisch der Standard der Anwendung.
- `null`, leeren Werten, `disabled`, `unlimited`, Datum/Zeit, Einheiten und zulässigen Grenzen.
- Globaler Vererbung und Postfachüberschreibungen; Priorität von `.env`, Prozessvariablen
  und vorhandenen Laufzeitoptionen.
- Gespeichertem gegenüber aktivem Stand; genauer Wirkung von Neuladen und Neustart.
- Entwürfen, automatischer Entwurfsablage, Briefings und dem Grundsatz „kein Mailversand“.
- Testmodus, echten LLM-Kosten und tatsächlichen Netzwerkzugriffen.
- Autorisierung, externen Schreibbestätigungen, Dublettenabgleich, Wiederholung,
  Nachprüfung von Eintragungen und Wiederherstellung nach Neustarts.
- Unterstützten Anbietern und ihren nachgewiesenen Einschränkungen.

Wenn Dokumentation und Code widersprechen, wird die beabsichtigte Regel anhand der
Spezifikation und vorhandener Abnahmen geklärt. Codefehler erhalten einen reproduzierenden
Regressionstest; sie werden nicht durch bloßes Umschreiben der Beschreibung verdeckt.
Anbieterspezifische OAuth-/Einrichtungsaussagen werden bei der Umsetzung anhand der
aktuellen offiziellen Anbieterunterlagen überprüft und mit Prüfdatum belegt.

### 9.3 Verständlichkeitsstandard für Feldhilfen

Jede Erläuterung beantwortet in dieser Reihenfolge:

1. **Was steuert diese Einstellung?** Ein einfacher Satz mit der sichtbaren Wirkung.
2. **Was ändert sich bei anderen Werten?** Praktische Folgen statt Wiederholung des Namens.
3. **Was darf eingegeben werden?** Einheit, relevante Grenzen, Standard und erlaubte Sonderwerte.
4. **Wann wird es wirksam?** Sofort, nächster sicherer Punkt, Neuladen oder Neustart.
5. **Welche Voraussetzung oder Wechselwirkung ist wichtig?** Insbesondere Vererbung,
   Kosten, Datenübertragung, Löschung oder erforderliche Freigaben.
6. **Welches Beispiel hilft?** Mindestens ein gültiger Alltagswert; bei Zahlen zwei
   Vergleichswerte, sofern deren Unterschied eine sinnvolle Entscheidung erklärt.

Beispiel für das Abrufintervall: „Legt fest, wie oft Mailhelp nach neuen Mails sucht.
60 Sekunden bedeutet ungefähr jede Minute, 300 ungefähr alle fünf Minuten. Ein kleinerer
Wert erkennt Mails früher und belastet den Mailserver stärker. Ein laufender Durchlauf
kann den nächsten Abruf verzögern.“ Grenzen, Default und Übernahmezeit werden am
tatsächlichen Implementierungsstand ergänzt, nicht aus dem Beispiel abgeleitet.

Kurze Feldhilfe und ausführlicher Referenzabschnitt dürfen unterschiedliche Tiefe
haben, aber keine widersprüchlichen Aussagen. Fachbegriffe werden beim ersten Auftreten
erklärt. Keine echten Konten oder Geheimnisse in Beispielen; synthetische Werte und
eindeutige Platzhalter verwenden. Schema- und Beispielvalidierung ergänzt die redaktionelle
Prüfung, ersetzt sie jedoch nicht.

## 10. Schritt-für-Schritt-Anleitungen

Aktuelle Benutzeraufgaben werden in eigenen, direkt verlinkten Anleitungen beschrieben.
Ältere Releases bleiben als Historie erhalten und werden nicht zum einzigen Einstieg
für heutige Bedienabläufe gemacht.

| Anleitung / vorgesehenes Dokument | Verbindlicher Inhalt und Erfolgsnachweis |
| --- | --- |
| **Ersteinrichtung** – `docs/Ersteinrichtung.md` | Voraussetzungen; Installation und Start unter Windows 11 und Linux/Docker; erster Terminal-Code; Browseranmeldung und Passwort; Zeitzone; erstes Postfach; KI-Anbindung; Ziele; optional Telegram; Verbindungen prüfen; gespeicherten/aktiven Stand erkennen; synthetischen Testfall durchlaufen und externe Aktion separat bestätigen. |
| **Weitere Konten** – `docs/Konten-verwalten.md` | Zweites IMAP-Postfach hinzufügen; Server/Port/TLS, Ordner, Startgrenze und Zugangsdaten erklären; prüfen und aktivieren; Zielprofil und Postfachregeln zuordnen; IServ-Konto ergänzen; weitere Kalender-/Aufgabenkonten verbinden; bestehende Konten ändern, deaktivieren oder entfernen; jeweilige Aktivierung und Fehlerkorrektur. |
| **Kalender und Aufgaben verbinden** – `docs/Ziele-einrichten.md` | Google Kalender/Todoist, Outlook/Microsoft To Do, CalDAV und Apple-Erinnerungen mit tatsächlichen Fähigkeiten und Einschränkungen; Konto versus Zielprofil versus Kalender-/Listen-ID; OAuth/App-Passwort; lesende Prüfung; sicherer Zielwechsel. |
| **Alltagsbedienung** – `docs/Bedienung.md` | Mails und Vorschläge finden, Belege lesen, bearbeiten, Rückfragen beantworten, bestätigen/verwerfen, Dubletten behandeln, vorhandene Nachanalyse und Nachprüfung; Statusmeldungen und Grenzen; Entwürfe, Themen und Briefings. |
| **Fehler beheben** – `docs/Fehlerbehebung.md` | Anmeldung fehlgeschlagen, Ordner fehlt, OAuth abgelaufen, Anbieter nicht erreichbar, KI-Budget erschöpft, Einstellung noch nicht aktiv, Chat ohne Quellen; sichere nächste Schritte, Diagnose und Wiederholung ohne Doppelaktionen. |
| **Einstellungen, Suche und Hilfschat** – Erweiterung von `docs/Web-Einstellungen.md` | Vollständige Feldreferenz, Live-Suche, Synonyme, Bedienweg, Hilfschat, Quellen, Datenschutz, Kosten, Aufbewahrung sowie Formularbetrieb ohne JavaScript. |
| **Betrieb und Update** – bestehende Betriebsanleitung und README | Sicherung, Aktualisierung, Neuladen/Neustart, Zustandsaufbewahrung, Promptupgrade, Hilfebestand im Paket und Rückkehr zur Vorversion. |

Jede Anleitung hat Ziel, Voraussetzungen, nummerierte Schritte mit tatsächlichen
Schaltflächennamen, erwartetes sichtbares Ergebnis und passende Fehlerhilfe. Unterschiede
zwischen Windows und Docker oder zwischen Anbietern sind ausdrücklich gekennzeichnet.
Screenshots werden nur ergänzend verwendet; die Textanleitung muss allein ausführbar sein.

Alle Schritte werden in einer frischen synthetischen Installation nachvollzogen.
Die zweite Kontoeinrichtung wird zusätzlich an einer bereits eingerichteten Instanz
geprüft. Ein Protokoll nennt Betriebssystem, Version, Schritt und beobachtetes Ergebnis.
Für jeden unterstützten Anbieter gibt es einen klaren Pfad oder eine ausdrückliche
dokumentierte Grenze, keine aus einem anderen Anbieter übernommene Erfolgserwartung.

## 11. Technische Arbeitspakete

Die Dateinamen neuer Module sind Vorschläge; endgültige Zuschnitte folgen der
bestehenden Paketstruktur. Kleine Funktionen, typisierte Verträge und getrennte
Zuständigkeiten sind wichtiger als die Zahl der Dateien.

| Bereich | Bestehende Anknüpfung | Geplante Ergänzung |
| --- | --- | --- |
| Suchkatalog und Suche | `web/settings_pages.py`, `web/setting_help.py`, `configuration.py` | Gemeinsame Metadaten und reine Suchfunktion, etwa `web/settings_search.py`; stabile Anker und Sonderseitenbezüge |
| Live-Oberfläche | `web/settings_site.py`, `web/static/app.js`, `web/static/app.css` | Authentifizierter JSON-Endpunkt, Ergebnisbereich, Entprellung, Abrufreihenfolge und sichere Links |
| Dokumentationsbestand | Markdown-Dokumente, Paketressourcen, Release-Pakettests | Freigabeliste, reproduzierbarer Abschnittsindex, Versionsmanifest, lokaler Leser |
| Kontextauswahl | Neuer klar abgegrenzter Hilfedienst | Gewichtete lokale Suche, Verlaufsauswahl, Nutzlastgrenzen und Quellenvertrag |
| LLM | `config/models.py`, `processing/analysis.py`, aktive Runtime-Komposition | Optionaler `settings_help`-Schritt, validierter Modellbezug, strukturiertes Antwortmodell und gemeinsames Budget |
| Chat und Aufträge | `web/auth.py`, vorhandene JSON-Persistenz und Runtime-Dienste | Geschützte Start-/Status-/Löschaktionen, Versionen, Idempotenz, begrenzter Worker und Bereinigung |
| Dokumentationsabnahme | `tests/web/test_setting_help.py`, `tests/release/test_documentation.py` | Vollständige Inventur, fachliche Vertragsfälle, Beispiel-/Link-/Paketprüfungen und Prüfbericht |

## 12. Umsetzungsfolge und Meilensteine

Die Patchfolge ist eine Planvorgabe. Jeder Schritt umfasst passende Tests und aktuelle
Dokumentation. S entspricht ungefähr einem, M ungefähr zwei bis drei Entwicklungstagen;
größere Befunde werden in weitere Schritte zerlegt. Fehlerkorrekturen können die
Nummerierung verschieben. Geschätzter Umfang: **24–35 Entwicklungstage**, abhängig von
den beim vollständigen Dokumentationsabgleich gefundenen Abweichungen.

| Schritt | Geplanter Patch | Ergebnis / fertig, wenn … | Größe | Abhängigkeit |
| --- | --- | --- | :---: | --- |
| H1 | 5.3.0 | Stand nach 5.2 abgeglichen; vollständige Einstellungs-/Funktionsinventur, API-/Modell-/Persistenzvertrag, Workergrenzen und Abnahmefälle festgelegt; vorhandene Regressionen erfasst. | M | Beginn |
| H2 | 5.3.1 | Fachliche Dokumentationslücken priorisiert; Feldhilfen, Default-/Grenzwert-/Vererbungsangaben und Referenz korrigiert; Codefehler getrennt mit Regressionen behoben. | M | H1 |
| H3 | 5.3.2 | Gemeinsamer Suchkatalog samt Synonymen, öffentlichen Sonderseiten und stabilen Sprungzielen vorhanden; Formularsuche nutzt denselben Vertrag. | M | H1, H2 |
| H4 | 5.3.3 | Live-Suchendpunkt und Oberfläche funktionieren ab dem ersten Zeichen; verspätete Antworten, Leeren, Fehler, Tastatur und Formular-Rückfall geprüft. | M | H3 |
| H5 | 5.3.4 | Ersteinrichtung und Kontenverwaltung als ausführbare aktuelle Anleitungen fertig; Windows-/Docker-Abweichungen sowie weitere Konten nachvollzogen. | M | H1, H2 |
| H6 | 5.3.5 | Ziele, Alltag, Fehlerbehebung und Betrieb abgeglichen; vollständige Inventur zugeordnet; redaktionelle Verständlichkeitsprüfung und Beispielvalidierung abgeschlossen. | M | H5 |
| H7 | 5.3.6 | Freigegebene Dokumentation als reproduzierbare Paketressource mit Manifest, lokalem Leser und deterministischer Kontextauswahl vorhanden; historische/private Quellen ausgeschlossen. | M | H2, H6 |
| H8 | 5.3.7 | `settings_help` über tatsächliche aktive LLM-Auflösung integriert; Modellreferenz, OpenRouter/Ollama, strukturierte Quellenantwort, Budgets, Promptupgrade und Fingerprints geprüft. | M | H7 |
| H9 | 5.3.8 | Sitzungsgebundener Chatdienst mit Auftragszustand, CSRF, Versionen, Idempotenz, Workerbegrenzung, Abbruch-/Neustartverhalten und Bereinigung abgenommen. | M | H8 |
| H10 | 5.3.9 | Sichtbarer Chat und „Dazu fragen“, Quellenlinks, Anschlussfragen, Lade-/Fehlerzustände sowie Formularbetrieb in Desktop und Mobilansicht integriert. | M | H4, H9 |
| H11 | 5.3.10 | Vollständige Sicherheits-, Fehler-, Prozess- und Browsermatrix bestanden; frische Installation, Upgrade, Paketbetrieb und Suchlaufzeiten nachgewiesen. | M | H10 |
| H12 | 5.3.11 | Dokumentationsprüfbericht und `docs/Release-5.3.md` fertig; README, Spezifikation, Beispiele und Hilfebestand konsistent; sämtliche Releasekriterien bestanden. | M | H11 |

Meilensteine: **M1** nach H4 = fertige Live-Suche; **M2** nach H7 = geprüfte und
auslieferbare Hilfebasis; **M3** nach H10 = vollständiger Chat; **M4** nach H12 = Releaseabnahme.
Der Chat wird erst mit geprüften Quellen aktiviert. Die Dokumentationsprüfung ist
ein eigenes Ergebnis der Version und keine bloße Vorbereitung des Prompts.

Bei jedem Commit in `main` oder `beta` werden Patchversion in `pyproject.toml` und
`src/mailhelp/__init__.py`, `CHANGELOG.md` und README entsprechend den Entwicklungsregeln
gepflegt. Die Reihe 5.3 wird erst bei Beginn ihrer tatsächlichen Umsetzung eröffnet;
dieser Plan erklärt den aktuellen Arbeitsstand nicht bereits zu Version 5.3.

## 13. Verbindliche Test- und Abnahmematrix

Automatisierte Tests verwenden ausschließlich synthetische Daten und simulierte
externe Dienste. Jeder Bugfix enthält einen Regressionstest mit nachgewiesenem
Fehlschlag vor und Erfolg nach der Korrektur.

| Bereich | Fälle | Erwartung |
| --- | --- | --- |
| Live-Eingabe | Ein Zeichen, mehrere Wörter, Einfügen, IME, schnelles Tippen, Löschen, leere Eingabe, 80-Zeichen-Grenze | Ohne Absenden passende Treffer; richtige Leer-/Grenzzustände; keine unnötigen Aufrufe |
| Suche | Bezeichnung, Schlüssel, Bereich, Hilfetext, Synonym, Umlaute, Großschreibung, null/viele Treffer | Deterministische Rangfolge; Übereinstimmung mit vollständiger Suche; keine privaten Werte |
| Suchrennen | Antwort A kommt nach Antwort B; Abbruch nach Leeren; Netzwerkfehler | Nur aktueller Suchstand sichtbar; keine alte Trefferliste oder endlose Ladeanzeige |
| Navigation | Geschlossener Einstellungsblock, Sonderseite, Browser zurück, Formular bereits bearbeitet | Passendes Ziel sichtbar; keine verlorenen Eingaben; kein History-Spam |
| Barrierefreiheit | Tastatur, Screenreader-Status, Touch, kleine Breite, Dunkelmodus, globale Tastenkürzel | Kein Fokusverlust; erreichbare Bedienelemente und verständliche Zustandsansagen |
| Kontextauswahl | Konkrete Einstellung, mehrdeutige Frage, Anschlussfrage, zu großes Budget, fehlende Quelle | Relevante begrenzte Abschnitte oder Rückfrage; niemals beliebiger Ersatzkontext |
| Quellenbestand | Historischer Plan, manipulierte Kennung, beschädigter/alter Index, Pfadtraversal | Kein fremder Inhalt oder Dateizugriff; klare sichere Fehlermeldung |
| Modellbindung | Default, schrittspezifische Routen, Ollama, Laufzeitwechsel, fehlender Hilfeprompt | Erwarteter aktiver Modellpfad; keine zweite Zugangsdaten- oder Budgetverwaltung |
| LLM-Fehler | 401/403/429/5xx, Timeout, leere Antwort, ungültiges JSON/Schema, fremde Quellen-ID | Begrenzte Fehlerbehandlung; keine falschen Quellen und keine erfundene Antwort |
| Last | Gleichzeitige Mails, Berichte und Chats; viele Sitzungen; volle Warteschlange | Gemeinsames LLM-Limit und Workergrenzen eingehalten; übrige Bedienung bleibt möglich |
| Autorisierung | Fehlende/abgelaufene/widerrufene Sitzung, falscher CSRF, fremder Auftrag/Verlauf | Keine Inhalte und kein neuer Modellaufruf; erneute Prüfung vor Ausführung |
| Wiederholung | Doppelklick, identischer Schlüssel, geänderter Inhalt, veraltete Chatversion | Ein Auftrag; Replay oder Konflikt; keine doppelte Anhängung |
| Neustart/Abbruch | Prozessende vor/während/nach Antwort, Chat während Aufruf leeren | Kein automatischer kostenpflichtiger Wiederholungsaufruf; konsistenter Endstand |
| Unvertrauenswürdige Inhalte | Promptinjektion, HTML/Skript, Modelllink, Bitte um direkte Änderung | Keine Codeausführung, fremden Quellenlinks, Konfigurations- oder Kalender-/Aufgabenschreibzugriffe |
| Datenschutz | Bekannte Geheimnisse im Text, normale Logs, explizite Inhaltslogs, Ablauf/Löschen | Redigierte Übertragung; Inhaltslogs nur explizit; termingerechte Löschung und keine PWA-Kopie |
| Dokumentation | Alle öffentlichen Felder/Funktionen, Grenzen, Defaults, Vererbung, Aktivierung | Vollständige Matrix; fachliche Belege statt bloßer Textgleichheit |
| Anleitungen | Ersteinrichtung, zweites Postfach, IServ, weiteres Ziel, Fehlerkorrektur | Schritte aus frischer beziehungsweise bestehender synthetischer Installation nachvollziehbar |
| Distribution | Windows 11, Linux/Docker, Wheel und Quellarchiv außerhalb des Checkouts | Suche, Quellen und Chatdefaults vollständig; kein Zugriff auf Repository oder private Dateien nötig |
| Ohne JavaScript | Formularsuche, Frage absenden, Statusseite aktualisieren, Quellen öffnen | Kernabläufe funktionieren; keine zweite Implementierung der Fachlogik |

Geplante Ergänzungen liegen bei den vorhandenen Web-/Release-Tests sowie in eigenen
Tests für Suchlogik, Retrieval, Chatdienst und Browserabläufe. Die vorhandenen
`test_settings_areas.py`, `test_setting_help.py` und `test_ui_settings35.py` werden
um neue Verhaltensfälle erweitert; ihre bisherigen Schutzfälle bleiben erhalten.

## 14. Fachliche Chatbewertung und Releasefreigabe

Neben simulierten Transport- und Vertragstests entsteht ein synthetischer Fragenkorpus
mit mindestens **40 Fällen**: mindestens zehn Einstellungserklärungen, zehn
Einrichtungs-/Kontenfragen, zehn Abhängigkeits-/Fehlerfragen und zehn Fälle zu fehlenden
Quellen, Mehrdeutigkeit oder Manipulationsversuchen. Erwartete Quellen, Kernaussagen
und verbotene Behauptungen sind je Fall festgelegt.

Deterministische Tests prüfen Kontextauswahl, Quellenzulassung, sichere Anzeige und
fehlende Schreibmöglichkeiten. Eine fachliche Bewertung tatsächlicher Modellantworten
wird separat mit Datum, Modell, Prompt-/Dokumentationsrevision und Aufrufbudget erfasst.
Sie benötigt für echte Anbieteraufrufe eine ausdrückliche Netzwerk-/Kostenfreigabe und
darf nicht durch perfekte Fake-Antworten als gemessene Qualität ausgegeben werden.

Für den bewerteten Stand gelten: mindestens 90 % fachlich richtige und verständliche
Antworten im dokumentierten Korpus, korrekte mitgegebene Quellen für jede gewertete
Sachantwort sowie keine kritischen erfundenen Bedienwege, Geheimnisoffenlegungen oder
vorgeblichen Schreibaktionen. Fehlerfälle führen zur Verbesserung und erneuten gezielten
Bewertung. Das Ergebnis ist an den geprüften Modellstand gebunden, keine Garantie für
beliebige spätere Modelle oder freie Fragen.

**Technische Releasekriterien:**

- Sämtlicher eigener Anwendungscode erreicht **100 % Zeilen- und 100 % Branch-Abdeckung**.
  Die automatische Prüfung scheitert bei Unterschreitung eines der beiden Werte;
  keine zusätzlichen Ausschlüsse oder wirkungslosen Tests. Frontendverhalten ist
  zusätzlich durch Browsertests nachgewiesen.
- Relevante gezielte Tests, vollständige Prüfung über `python -m devtools.check full`,
  Ruff, mypy, Prompt-Gate und die erforderlichen vollständigen Browserfälle bestehen.
  Der reine UI-Smoke-Lauf ersetzt die neuen Browserfälle nicht.
- Live-Suche erfüllt den benannten Laufzeitwert und erzeugt keine LLM-Aufrufe.
- Alle öffentlichen Einstellungen und Funktionen sind inventarisiert, fachlich
  abgeglichen und verständlich dokumentiert; alle Pflichtanleitungen sind nachvollzogen.
- Wheel, Quellarchiv und Docker liefern den passenden Hilfebestand; Upgrade und
  fehlender optionaler Prompt sind ohne Ausfall des übrigen Betriebs geprüft.
- Releasebericht nennt Plattformen, Testnachweise, Dokumentationsrevision,
  Modellbewertung, Kosten-/Datengrenzen und gegebenenfalls verbleibende Einschränkungen.

Version 5.3 ist erst abgeschlossen, wenn Live-Suche, Hilfschat und die vollständige
Dokumentationsprüfung gemeinsam diese Kriterien erfüllen.
