# Mailhelp 5.4 – Hilfschat als dauerhaft geöffnetes Fenster in den Einstellungen

**Zielversion:** 5.4.0, Umsetzung in Patchversionen 5.4.x

**Stand:** 10. November 2026

**Status:** Abgeschlossen mit 5.4.1 (11. November 2026).

**Umsetzung:** F1–F7 wurden als gemeinsamer Arbeitsstand 5.4.0 umgesetzt und mit 5.4.1
abgenommen, ohne die ursprünglich vorgesehenen einzelnen Patchcommits. Nachweise und Grenzen:
[Release 5.4](Release-5.4.md).

**Ausgangsstand:** 5.3.13 laut `pyproject.toml`

**Vorgänger:** [Planung 5.3](Planung-5.3.md), [Release 5.3](Release-5.3.md)

**Grundlage:** [Entwicklungsregeln](../AGENTS.md), [Projektspezifikation](../Mailhelp-Projektspezifikation.md)

## 1. Ziel

Der Hilfschat öffnet sich als kleines Fenster **vor der Einstellungsseite**. Das
Chatsymbol und „Dazu fragen“ öffnen dieses Fenster direkt am aktuellen Arbeitsort.
Es findet dabei kein Wechsel auf die separate Chatseite statt.

Das Fenster bleibt geöffnet, bis die Person es ausdrücklich mit **„Hilfschat
schließen“** schließt. Währenddessen kann sie weiter nach Einstellungen suchen,
Bereiche wechseln, Werte bearbeiten, Änderungen bestätigen und speichern. Verlauf,
noch nicht abgesendete Frage und laufende Antwort bleiben dabei erhalten.

Beispiel: Die Person fragt nach dem Abrufintervall, liest die Erklärung und sucht
anschließend nach „Abruf“. Sie öffnet den Treffer, ändert den Wert, bestätigt und
speichert. Das Chatfenster ist auf jeder beteiligten Seite weiterhin geöffnet und
zeigt dasselbe Gespräch. Erst die Schließen-Schaltfläche blendet es aus.

5.4 überarbeitet Darstellung und Einbettung des vorhandenen Hilfschats. LLM-Anbindung,
Dokumentationsauswahl, Quellenprüfung und der erklärende Funktionsumfang aus 5.3 werden
weiterverwendet. Die Umsetzung neuer Schreibwerkzeuge für den Chat gehört nicht zum Umfang.

## 2. Tatsächlicher Ausgangspunkt

| Baustein | Verhalten in 5.3.13 | Änderung in 5.4 |
| --- | --- | --- |
| [Chatsymbol im Layout](../src/mailhelp/web/pages.py) | `_help_button()` erzeugt einen Link auf `/hilfe`; sichtbar auf `/einstellungen`, Unterseiten und `/themen`. | Öffnet ein Fenster innerhalb der aktuellen Einstellungsseite. |
| „Dazu fragen“ | Einstellungs- und Suchtreffer verweisen auf `/hilfe` mit Feldbezug. | Öffnet denselben eingebetteten Chat und setzt den Feldbezug. |
| [Chatdarstellung und Routen](../src/mailhelp/web/help_site.py) | Eigene HTML-Seite; Frage senden und Leeren leiten auf `/hilfe#chat` weiter. | Gemeinsame Fensterdarstellung; Antworten und Fehler bleiben im Fenster. |
| [Statusabfrage](../src/mailhelp/web/static/app.js) | Polling liest den Auftragsstatus; bei Abschluss wird `location.reload()` ausgeführt. | Nur Chatinhalt aktualisieren; kein Neuladen der Einstellungsseite nach einer Antwort. |
| Einstellungen | Formularaktionen können vollständige Seitenwechsel, Bestätigungsseiten und Fehlerseiten erzeugen. | Fensterzustand auch über diese Wechsel hinweg wiederherstellen. |
| [Vorhandene Browsertests](../ui_tests/test_ui_help_button_5312.py) | Erwarten nach Klick den Seitenwechsel auf `/hilfe`. | Neue Erwartung: aktuelle Einstellungsadresse bleibt beim Öffnen bestehen; Fenster sichtbar. |

Ein reiner Austausch des Links gegen einen schwebenden Container genügt nicht:
Vollständige Formularantworten ersetzen das Dokument. Daher gehören die Wiederherstellung
des Fensters und die unabhängige Aktualisierung des Gesprächs ausdrücklich zur Umsetzung.

## 3. Fenster und Bedienung

### 3.1 Öffnen und Darstellung

- Das vorhandene Chatsymbol unten rechts öffnet genau ein Chatfenster. Ein erneuter
  Öffnungsaufruf fokussiert dieses Fenster, statt ein zweites anzulegen oder es zu schließen.
- „Dazu fragen“ verwendet dasselbe Fenster und denselben Verlauf. Die ausgewählte
  Einstellung erscheint als sichtbarer Bezug. Eine bereits eingegebene Frage wird
  weder überschrieben noch automatisch abgesendet.
- Desktop: schwebendes Fenster unten rechts, vorgesehene Breite etwa 380 Pixel,
  Höhe bis etwa 520 Pixel. Die Größe passt sich an den verfügbaren Bildschirm an.
- Smartphone/Tablet: dasselbe Fenster mit begrenzter Breite und Höhe, oberhalb der
  unteren Navigation und mit Berücksichtigung der Bildschirmtastatur und Safe Areas.
  Die Einstellungsseite bleibt teilweise sichtbar und bedienbar. Kein eigener Seitenaufruf.
- Der Fensterkopf enthält Titel und eine eindeutig beschriftete Schließen-Schaltfläche.
  Darunter stehen Verlauf, Antwortstatus, Quellen, Feldbezug und Frageeingabe.
- Das Fenster ist nicht modal: kein abgedunkelter Hintergrund, keine Sperre der
  Einstellungsseite und kein im Chat gefangener Tastaturfokus.
- Überdeckte Einstellungen müssen erreichbar bleiben. Das Fenster erhält eine per
  Kopfzeile verschiebbare Position innerhalb des sichtbaren Bereichs; dieselbe
  Positionsänderung ist über benannte Tastaturbedienelemente möglich. Nach einer
  Größenänderung wird die Position wieder in den sichtbaren Bereich begrenzt.
- Verbindliche Bestätigungs- und Sicherheitsdialoge stehen über dem Chat. Sie schließen
  ihn nicht; nach ihrer Bearbeitung ist das Fenster wieder am bisherigen Ort sichtbar.

### 3.2 Was das Fenster nicht schließt

Folgende Aktionen ändern den Öffnungszustand nicht:

1. Suchbegriff eingeben, leeren oder Suche absenden.
2. Suchergebnis öffnen oder Einstellungsbereich wechseln.
3. Einstellungsblock auf- oder zuklappen und Formularwerte bearbeiten.
4. Änderung prüfen, bestätigen, speichern oder eine Validierungsfehlermeldung erhalten.
5. Zwischen Einstellungen, Postfächern, Zielprofilen, Themen und anderen zugehörigen
   Verwaltungsseiten navigieren.
6. Eine Chatfrage senden, auf die Antwort warten oder einen Chatfehler erhalten.
7. Auf Quellen oder Einstellungsverweise im Chat klicken.
8. Browserseite neu laden sowie innerhalb der Einstellungen „Zurück“/„Vorwärts“ verwenden.
9. Außerhalb des Fensters klicken, die Seite scrollen oder Escape in einem Formular drücken.

Es gibt keinen Timer und kein automatisches Minimieren nach einer Antwort. Escape
schließt lediglich passende untergeordnete Menüs oder Feldhilfen; das Chatfenster wird
damit nicht versehentlich geschlossen.

### 3.3 Schließen, Leeren und Wiederöffnen

- **Schließen** blendet nur das Fenster aus. Verlauf, Eingabeentwurf und Auftrag
  bleiben innerhalb der geltenden Aufbewahrung erhalten. Ein laufender LLM-Aufruf
  wird dadurch nicht erneut gestartet oder als zuverlässig abgebrochen dargestellt.
- **Chat leeren** bleibt eine separate Aktion. Sie verwirft den Gesprächsinhalt nach
  dem vorhandenen Versionsvertrag und hält das Fenster geöffnet. Auch der lokale
  Eingabeentwurf wird entfernt; verspätete alte Ergebnisse erscheinen nicht wieder.
- **Wiederöffnen** stellt das vorhandene Gespräch und den erhaltenen Entwurf wieder her.
  Ein inzwischen fertiggestellter Auftrag wird gelesen, nicht nochmals abgesendet.
- Nach ausdrücklichem Schließen bleibt das Fenster bei Suche, Speichern, Neuladen und
  Navigation geschlossen. Es öffnet sich erst durch Chatsymbol, „Dazu fragen“ oder
  einen ausdrücklich aufgerufenen alten Chatlink erneut.

Abmeldung, widerrufene/abgelaufene Sitzung und Ablauf der Aufbewahrung sind technische
Grenzen: Private Inhalte dürfen dann nicht weiter sichtbar sein. Diese Fälle werden
als Anmeldung beziehungsweise abgelaufener Verlauf erklärt, nicht als Bedienaktion
„Chat schließen“ ausgegeben.

## 4. Zustände über Seitenwechsel hinweg

### 4.1 Oberfläche und Gespräch auseinanderhalten

| Zustand | Zuständigkeit | Wiederherstellung |
| --- | --- | --- |
| Fenster offen/geschlossen und Position | Oberfläche des aktuellen Browser-Tabs | Nach Suchnavigation, Formularantwort, Neuladen und History-Wechsel |
| Nicht abgesendete Frage und ausgewählter öffentlicher Feldbezug | Oberfläche des aktuellen Tabs | Ohne automatischen Modellaufruf oder Übertragung des Entwurfs an die KI |
| Verlauf, Chatversion und laufende Aufträge | Vorhandener authentifizierter Chatdienst | Frischer Abruf nach gültiger Sitzungsprüfung |
| CSRF, Berechtigungen und aktuelle Formularversionen | Server | Immer neu beziehen/prüfen, niemals aus altem Browserzustand als gültig annehmen |

Der vorhandene Dienst bindet Gespräche an die Websitzung. Diese Bindung bleibt bestehen;
es entsteht kein zweiter Chatdienst nur für das Fenster. Zwei Tabs behalten ihren eigenen
Öffnungszustand und Entwurf, sehen aber den serverseitig gemeinsamen Sitzungsverlauf.
Parallele Fragen beziehungsweise Leeren aus einem anderen Tab verwenden die vorhandenen
Versions-/Konfliktregeln und werden verständlich abgeglichen.

### 4.2 Speichervertrag im Browser

Für den JavaScript-Betrieb wird `sessionStorage` verwendet: ein eng begrenzter,
versionsgekennzeichneter Eintrag pro Tab und aktueller Websitzung für Öffnungszustand,
Position, Feldbezug und Eingabeentwurf. Kein `localStorage`, keine Chattexte in URLs,
keine Authentifizierungstoken und keine vollständige Kopie des Gesprächsverlaufs.

Der Server stellt eine nicht authentifizierende Oberflächenkennung für die aktuelle
Sitzung bereit. Gespeicherter Zustand wird nur mit dieser Kennung und gültiger Sitzung
wiederhergestellt. Ablaufzeit entspricht höchstens der vorhandenen Chat-Aufbewahrung;
beim Ablauf oder Sitzungswechsel werden Einträge verworfen. Die dokumentierten Grenzen
für Fragentext gelten auch für den lokalen Entwurf. `sessionStorage` ist keine
Geheimnisablage; der bestehende Hinweis, keine Zugangsdaten einzugeben, gilt weiterhin.

Bei Abmeldung werden lokale Chatdaten entfernt. Wiederherstellung aus dem Browsercache
prüft die aktuelle Sitzung, bevor Gesprächsinhalte erneut sichtbar werden. Widerrufene
Sitzungen löschen die lokale Kopie bei der nächsten Prüfung; bei einem Verbindungsfehler
werden keine neuen Gesprächsdaten ohne Autorisierung ausgeliefert.

Ist Browserspeicher blockiert, funktioniert das Fenster im aktuellen Dokument weiter.
Für Navigation wird ein serverseitiger Zustand verwendet, der über geschützte Aktionen
vor dem Seitenwechsel gesichert wird. Scheitert diese Sicherung, wird der drohende Verlust
eines nicht gesendeten Entwurfs benannt und die Navigation kann abgebrochen werden.
Ein stiller Rückfall auf „Fenster nach jedem Speichern geschlossen“ ist nicht zulässig.

### 4.3 Vollständige HTML-Antworten

Die gemeinsame Seitenschale bindet das Fenster auf sämtlichen relevanten
Einstellungsseiten ein. Dazu gehören auch Bestätigungs-, Ergebnis- und Fehlerantworten
von Einstellungsaktionen, nicht nur erfolgreiche GET-Aufrufe mit `/einstellungen…`.
Der Geltungsbereich wird über eine explizite Routenzuordnung beschrieben. Beispielsweise
gehören auch Themenaktionen unter `/themen/speichern` und zugehörige Rücksprünge dazu.

Beim Dokumentstart wird der Öffnungszustand vor dem ersten sichtbaren Aufbau angewendet.
Ein zuvor offenes Fenster darf nicht erst nach einer langen Statusabfrage wieder aufgehen.
Sein Inhalt kann anschließend einen Ladezustand zeigen. Browsercache-/History-Ereignisse
werden ebenso berücksichtigt; Ereignisbehandler und Polling werden nicht doppelt registriert.

Beim Verlassen der Einstellungsverwaltung bleibt die Öffnungsentscheidung gespeichert.
Auf fachfremden Seiten muss kein Fenster erscheinen. Bei Rückkehr in die Einstellungen
ist es wieder offen, sofern es nicht ausdrücklich geschlossen wurde und die Sitzung gilt.

## 5. Fragen und Antworten im Fenster

1. Öffnen lädt ausschließlich den bisherigen Gesprächsstand. Kein kostenpflichtiger
   LLM-Aufruf ohne ausdrücklich gesendete Frage.
2. Die Frage wird im Hintergrund über die vorhandene geschützte Chataktion gesendet.
   Der Server antwortet für diesen Aufruf mit strukturiertem Auftrag beziehungsweise
   Fehler statt einer Weiterleitung auf `/hilfe#chat`.
3. Während die Person Einstellungen bearbeitet, läuft die bestehende Verarbeitung weiter.
4. Die Statusabfrage erhält bei Abschluss die sichere Antwortdarstellung beziehungsweise
   löst einen separaten Abruf des aktuellen Gesprächs aus. Aktualisiert wird nur das Fenster.
5. Bei einem vollständigen Seitenwechsel wird der vorhandene Auftrag wiedergefunden
   und gelesen. Der Browser sendet die alte Frage nicht automatisch erneut.

`location.reload()` nach einer Chatantwort entfällt im eingebetteten Betrieb. Sonst
könnten gerade bearbeitete Einstellungswerte verloren gehen. Auch Chat leeren, Quellen
nachladen und Fehlerbehandlung dürfen die Einstellungsformulare nicht ersetzen.

Die Aktualisierung des Verlaufs erhält Fokus, Cursor und Eingabeentwurf. Wer eine ältere
Antwort liest, wird nicht ungefragt ans Ende gescrollt; neue Antworten werden dezent
angekündigt. Statusabfragen werden bei ausgeblendetem Tab gedrosselt beziehungsweise
pausiert und bei Rückkehr ohne doppelten Auftrag fortgesetzt.

## 6. Links, alte Chatadresse und Betrieb ohne JavaScript

- Chatsymbol, Hilfeeinstieg, „Dazu fragen“ und passende Live-Suchtreffer öffnen das Fenster.
  Die aktuelle Adresse und bereits bearbeitete Einstellungsfelder bleiben beim Öffnen erhalten.
- Einstellungsverweise aus Antworten führen zur zugehörigen Einstellung und halten den
  Chat offen. Der neue Feldbezug wird angezeigt; der vorhandene Entwurf bleibt erhalten.
- Dokumentationsquellen werden im Fenster in einem eigenen Lesebereich mit „Zurück zum
  Gespräch“ angezeigt. Das schließt oder leert den Chat nicht. Ein optional ausdrücklich
  gewählter Link kann die Dokumentation in einem neuen Tab öffnen.
- Alte Aufrufe von `/hilfe` einschließlich Feldbezug führen zur Einstellungsübersicht
  mit geöffnetem Fenster. Es wird dadurch keine Frage gesendet. Rücksprungziele kommen
  ausschließlich aus zugelassenen lokalen Routen; keine offenen Weiterleitungen.
- Ohne JavaScript wird der Chat ebenfalls als Fenster in der gemeinsamen Seitenschale
  gerendert. Öffnen, Schließen, Frage senden und „Antwort prüfen“ verwenden geschützte
  Formulare und kehren in denselben Einstellungsbereich zurück. Der serverseitige
  Öffnungszustand bleibt bei Such-/Speicheraktionen erhalten.
- Im Formularbetrieb erfolgt kein automatisches Neuladen der ganzen Seite wegen einer
  Chatantwort. Ein ausdrückliches „Antwort prüfen“ ersetzt dieses Verhalten. Nicht
  abgesendete Texte lassen sich ohne JavaScript nur nach einer ausdrücklichen lokalen
  Entwurfsspeicherung über Seitenwechsel erhalten; diese Grenze wird klar dokumentiert.
  Die vollständige automatische Entwurfserhaltung gilt für den JavaScript-Betrieb.

## 7. Sicherheit und bestehende Verträge

Alle Gesprächs-, Auftrags- und Zustandsrouten bleiben authentifiziert. Schreibende
Chataktionen prüfen CSRF, aktuelle Sitzung, Chatversion und Idempotenzschlüssel.
Browserzustand autorisiert keinen Zugriff; er steuert nur Darstellung und Entwurf.
Der Server prüft die Sitzung vor einem Modellaufruf weiterhin erneut.

Der Chat ändert keine Konfiguration und führt keine externen Aktionen aus. Das Bearbeiten
oder Speichern einer Einstellung im Hintergrund autorisiert keine Google-Kalender- oder
Todoist-Anlage. Bestehende ausdrückliche, versionsbezogene Freigaben bleiben erforderlich.

Antworten und Fehlermeldungen bleiben nicht vertrauenswürdige Eingaben. Sichere
Textdarstellung, geprüfte Quellenkennungen und serverseitig erzeugte Einstellungslinks
gelten ebenso im Fenster und in dessen Dokumentationsansicht.

Chatdaten erscheinen nicht in Service-Worker-/Offline-Caches. Inhaltslogs bleiben
ausdrücklich zuschaltbar; der neue Browserentwurf wird weder als Einstellungswert noch
als automatisches Ereignisprotokoll gespeichert. Vorhandene Limits, LLM-Modelle und
Promptparameter bleiben maßgeblich. Neue Anwendungsoptionen gehören bei Bedarf in
`config.yaml`; für diese Oberflächenänderung sind zunächst keine neuen Schalter vorgesehen.

## 8. Umsetzungsschritte

Die Patchfolge ist geplant und wird vor der Umsetzung mit dem dann aktuellen
Versionsstand abgeglichen. Jeder Schritt enthält passende Tests; jeder Commit auf
`main` oder `beta` pflegt Version in `pyproject.toml` und `src/mailhelp/__init__.py`,
Changelog und README gemäß Entwicklungsregeln. Dieser Plan selbst veröffentlicht keine Version.

| Schritt | Geplanter Patch | Inhalt und Ergebnis |
| --- | --- | --- |
| F1 | 5.4.0 | Alle Einstellungs-, Bestätigungs-, Fehler- und Rücksprungrouten erfassen; Fenster-/Zustandsvertrag festlegen; Regressionstests für den bisherigen Seitenwechsel und das Verlieren des Fensters erstellen. |
| F2 | 5.4.1 | Gemeinsame Chatdarstellung aus `help_site.py` lösen; sichere Zustands-/Antwortabfragen und strukturierte Ergebnisse für Frage/Leeren ergänzen; bestehenden Chatdienst weiterverwenden. |
| F3 | 5.4.2 | Nicht modales Fenster samt Chatsymbol, „Dazu fragen“, Größenanpassung, Positionierung, Schließen und zugänglicher Tastaturbedienung integrieren. |
| F4 | 5.4.3 | Öffnungszustand, Position, Eingabeentwurf und Feldbezug über Suche, Bereichswechsel, Bestätigung, Speichern, Fehlerseiten und Browsernavigation erhalten; Speicher-Ausfallweg prüfen. |
| F5 | 5.4.4 | Fragen senden, Antworten/Fehler und Quellen innerhalb des Fensters aktualisieren; Vollseiten-Reload aus dem Chatpfad entfernen; Wiederanbindung laufender Aufträge, mehrere Tabs und Leeren prüfen. |
| F6 | 5.4.5 | Alte `/hilfe`-Links auf eingebetteten Chat umstellen; Dokumentationsansicht, Formularbetrieb ohne JavaScript, Rücksprungvalidierung und Sitzungsablauf vervollständigen. |
| F7 | 5.4.6 | Vollständige Browser-, Sicherheits- und Wiederholungstests; Abnahme unter Windows 11 und Linux/Docker sowie Paketbetrieb; Dokumentation und Releasebericht aktualisieren. |

F2 folgt F1, F3 folgt F2, F4 folgt F3, F5 folgt F2–F4, F6 folgt F4/F5 und F7 folgt F6.
Geschätzter Aufwand: **8–12 Entwicklungstage**, einschließlich Tests und Dokumentation;
der genaue Aufwand hängt insbesondere vom Umfang der bestehenden Formularrücksprünge ab.

## 9. Verbindliche Abnahmefälle

| Fall | Erwartetes Ergebnis |
| --- | --- |
| Chatsymbol auf einer Einstellungsseite anklicken | Kleines Fenster vor der Seite; gleiche Einstellungsadresse; kein zusätzlicher Tab oder Seitenwechsel |
| „Dazu fragen“ bei geschlossenem beziehungsweise offenem Fenster | Ein Fenster mit richtigem Feldbezug; vorhandener Verlauf und Entwurf bleiben erhalten |
| Suche tippen, löschen und über Enter absenden | Fenster bleibt offen; Live-Ergebnisse und vollständige Suchseite funktionieren |
| Treffer öffnen, Bereich wechseln und Blöcke aufklappen | Fenster bleibt offen und behält Position und Gespräch |
| Wert bearbeiten und anschließend Antwort empfangen | Einstellungsformular, Wert, Cursor und Fokus bleiben erhalten; kein Vollseiten-Reload |
| Änderung bestätigen und speichern | Auf Vorschau, Bestätigung und Ergebnis bleibt der Chat offen; keine Freigabe wird durch den Chat ersetzt |
| Ungültiger Wert, Konflikt oder Speicherausfall | Fehlermeldung erreichbar; Fenster und Entwurf bleiben erhalten |
| Chatfrage läuft während Seitenwechsel | Derselbe Auftrag wird weiter angezeigt; kein zweiter Modellaufruf |
| Chatfenster schließen, dann suchen/speichern/neuladen | Bleibt geschlossen, bis ausdrücklich erneut geöffnet |
| Chat schließen und später wieder öffnen | Bisheriger Verlauf und Entwurf beziehungsweise fertiggestellte Antwort sichtbar |
| Außerhalb klicken, scrollen, Escape drücken | Fenster bleibt offen; andere Bedienelemente funktionieren |
| „Chat leeren“ während eines Auftrags | Fenster bleibt offen; alte Inhalte und Entwurf entfernt; spätes altes Ergebnis wird nicht angehängt |
| Quelle oder Einstellungsverweis öffnen | Quelle im Fenster beziehungsweise passende Einstellung im Hintergrund; Gespräch bleibt erhalten |
| Browser neu laden, Zurück/Vorwärts und History-Cache | Richtiger Öffnungszustand; keine doppelten Handler, Poller oder Frageaufträge |
| Zwei Tabs derselben Sitzung | Unabhängige Fenster/Entwürfe; gemeinsamer Verlauf korrekt; Konflikte bei Leeren oder parallelen Fragen abgeglichen |
| Kleines Display, Zoom, Bildschirmtastatur, Fenster verschieben | Kopfzeile, Schließen, Fragefeld und untere Navigation erreichbar; verdeckte Einstellung zugänglich |
| Fremde Sitzung, widerrufene Anmeldung, alte Formularversion, falscher CSRF | Kein fremder Verlauf oder unberechtigter Modellaufruf; lokale Inhalte bei Sitzungswechsel verworfen |
| Browserzustand manipuliert, Speicher blockiert oder Netzwerk unterbrochen | Sichere begrenzte Wiederherstellung beziehungsweise erklärter Ausfallweg; kein fremder Zugriff oder offener Redirect |
| Direkter alter Link `/hilfe?einstellung=…` | Einstellungsübersicht mit eingebettetem Fenster und geprüftem Bezug; keine separate Chatseite |
| JavaScript deaktiviert | Fenster bleibt bei Suche/Speichern serverseitig offen; Frage und Statusprüfung per Formular; dokumentierte Entwurfsgrenze |

Der erste Browser-Regressionstest reproduziert vor dem Fix den Wechsel auf `/hilfe`.
Weitere Regressionen prüfen das Verlieren des Fensters nach einer echten
Bestätigungs-/Speichersequenz und den bisherigen Seiten-Reload nach Antwortabschluss.
Die alten Browsererwartungen für den Seitenwechsel werden durch diese fachlichen
Verhaltensprüfungen ersetzt, nicht einfach entfernt.

Tests verwenden simulierte LLM-/Anbieterdienste und synthetische Konfigurationen.
Für sämtliche Änderungen am eigenen Anwendungscode gelten **100 % Zeilen- und
100 % Branch-Abdeckung** mit automatischem Scheitern bei Unterschreitung; keine
zusätzlichen Coverage-Ausschlüsse oder wirkungslosen Tests. Browsertests ergänzen
die Codeabdeckung um die sichtbaren Abläufe, Fokus und Erhaltung von Formulareingaben.

## 10. Dokumentation und Abschluss

Bei Umsetzung werden mindestens README, Projektspezifikation, Einstellungsreferenz,
Bedienungsanleitung und passende Fehlerhilfe an den Fensterablauf angepasst.
Paketressourcen der Hilfedokumentation werden reproduzierbar aktualisiert, damit der
Chat nicht weiterhin den überholten Wechsel auf eine separate Chatseite erklärt.

`docs/Release-5.4.md` dokumentiert umgesetzte Schritte, Plattform-/Paketprüfungen,
Browsernachweise und ausdrücklich verbleibende Grenzen. Die historischen Berichte
für 5.3 bleiben als damaliger Iststand erhalten.

**Abgeschlossen ist 5.4, wenn eine Person den Chat öffnen, eine Einstellung suchen,
bearbeiten, bestätigen und speichern kann, während derselbe Chat geöffnet bleibt,
und ihn anschließend ausdrücklich schließen kann.**
