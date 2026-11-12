# UI-Prüfung Mailhelp 5.7.5

Stand: 11. November 2026. Referenz: Commit `d2abcb4` (Release 5.7.5).

## Ergebnis

Die Weboberfläche hat eine solide Grundlage: getrennte Lernwege, ausdrückliche Bestätigungen, verständliche Themenfelder und strukturierte Vergleiche. Der größte Verbesserungsbedarf liegt bei der Verlässlichkeit der angezeigten Entscheidung und bei der Informationsdichte auf kleinen Bildschirmen.

Zwei funktionale UI-Probleme wurden reproduziert: Die Kostenschätzung erhält die sichtbaren Eingaben nicht, und der Regelvergleich zeigt manuelle Änderungen nicht an. Diese sollten vor rein gestalterischen Änderungen behoben werden. Die Untersuchung weist weder einen tatsächlichen Kostenüberlauf noch einen unautorisierten externen Schreibzugriff nach.

Während der Prüfung entstanden parallel Änderungen für 5.7.6 in Quellcode und Tests. Diese wurden nicht verändert oder als abgeschlossen bewertet. Die unten genannten Vergleichs- und Eingabeprobleme betreffen auch die zum Prüfzeitpunkt eingesehenen Funktionen; spätere Änderungen benötigen eine erneute Prüfung.

## Umfang und Nachweise

- Quellcodeprüfung der Webabläufe, Formulare, Statusdarstellung und Bestätigungen.
- Visuelle Prüfung vorhandener Release-Screenshots: Aktionsübersicht, Einstellungen, Status, Themenkatalog, Themeneditor, Lernübersicht, Regellernen und Zuordnung verwandter Vorschläge.
- Neue Browsermessungen mit synthetischen Daten bei 1366 × 900, 390 × 844 und 320 × 640 Pixeln. Sieben gezielte Beobachtungsprüfungen liefen erfolgreich durch; sie dokumentieren ausdrücklich auch die gefundenen Probleme.
- Ein bestehender schmaler Aktionsübersichts-Test wurde zusätzlich erfolgreich ausgeführt.
- Keine echten Mails, kostenpflichtigen Modellaufrufe oder externen Schreibaktionen für diese Prüfung.

Die vorhandene [Release-Abnahme](Release-5.7.md) dokumentiert 4745 bestandene Python-Tests, 100 % Zeilen- und Branch-Abdeckung sowie 489 bestandene Browserprüfungen. Diese vollständigen Suiten wurden für das Audit nicht nochmals ausgeführt. Hohe Coverage und axe-Prüfungen ersetzen keine Prüfung der Verständlichkeit und inhaltlichen Richtigkeit einer UI.

Lokale, nicht eingecheckte Prüfnachweise liegen unter `.test-tmp/ui-audit57/`: `estimate.json`, `forms-*.json`, `layout-*.json` und `cards-*.png`; das Beobachtungsskript wird als `probes.py` aufbewahrt. Laufprotokolle: `.test-tmp/ui-audit57.log` und `.test-tmp/ui-audit-baseline.log`. Release-Screenshots liegen unter `.test-tmp/ui-screens/`.

## Priorisierte Befunde

P1 = vor der nächsten UI-Freigabe beheben. P2 = im nächsten UI-Arbeitspaket verbessern. P3 = nachrangige Vereinfachung. „Reproduziert“ bezeichnet eigene Laufzeitbeobachtungen; „Inspektion“ bezeichnet Quellcode- oder Screenshotbefunde, keine nachgewiesene Laufzeitstörung.

| ID | Priorität | Bereich | Befund und empfohlene Änderung | Nachweis |
| --- | --- | --- | --- | --- |
| UI-01 | P1 | Regellernen | Der Vergleich bleibt beim ursprünglichen Modellvorschlag, obwohl der Benutzer Felder bearbeitet. Vor der Übernahme den tatsächlich bearbeiteten Stand einschließlich YAML vergleichen. | Reproduziert, alle drei Größen; `forms-*.json` |
| UI-02 | P1 | Kostenschätzung | Nach der Schätzung springen sichtbare Werte auf Standardwerte zurück; die verborgene Auswahl enthält weiterhin die ursprünglichen Werte. Alle Eingaben konsistent erhalten. | Reproduziert; `estimate.json` |
| UI-03 | P2 | Formularfehler | Englische Validierungsdetails, fehlende programmatische Zuordnung zum Feld und kein gezielter Fehlerfokus. Deutsche Meldungen, verknüpfte Hilfe/Fehler und Fokusführung ergänzen. | Reproduziert, alle drei Größen; `forms-*.json` |
| UI-04 | P2 | Themenkatalog mobil | Die erste Themenzeile liegt unterhalb des ersten sichtbaren Bildschirms. Kopfbereich verkürzen und Suche samt Ergebnissen nach oben holen. | Reproduziert; `layout-mobile.json`, `layout-narrow.json` |
| UI-05 | P2 | Vorschlagskarten mobil | Einzelne Karten sind höher als der Bildschirm. Titel, Termin, Status und Hauptaktion kompakt halten; weitere Details aufklappbar anbieten. | Reproduziert; `layout-*.json`, `cards-*.png` |
| UI-06 | P2 | Regelprüfung | Ein umfangreicher neuer Analyseauftrag steht oberhalb der bereits zu prüfenden Ergebnisse. Den offenen Prüfentwurf priorisieren und eine erneute kostenpflichtige Analyse nachgeordnet anbieten. | Screenshot-/Quellcodeinspektion |
| UI-07 | P2 | Einstellungen bestätigen | Technischer Schlüssel und neuer Wert statt eines verständlichen Alt-Neu-Vergleichs; pauschale Warnung zu mehreren unbeteiligten Risiken. Anzeigename, bisherigen Wert und konkret eintretende Wirkung zeigen. | Quellcodeinspektion |
| UI-08 | P2 | Statusseite | Sehr lange Folge technischer Werte; Webverbindung und Integrationszustand sind leicht zu verwechseln. Oben Handlungsbedarf, letzte erfolgreiche Vorgänge und nächste Schritte zusammenfassen. | Screenshotinspektion |
| UI-09 | P2 | Lernübersicht | Große Karten, wenig präziser Erstzustand und keine automatische Aktualisierung auf dieser Übersicht. Kompaktere Karten, „Noch kein Lauf“ und begrenzte Statusaktualisierung vorsehen. | Screenshot-/Quellcodeinspektion |
| UI-10 | P2 | Lernlauf vorbereiten | Ordnernamen werden von Hand eingegeben, Preisannahmen ebenfalls. Postfachbezogene Ordnerauswahl und nachvollziehbare Preisannahmen erleichtern die Vorbereitung. | Quellcode/Release-Dokumentation |
| UI-11 | P3 | Themeneditor/Einstellungen | Große Abstände und wiederholte Navigation verlängern einfache Bearbeitungen. Feldgruppen verdichten und grundlegende von fortgeschrittenen Einstellungen unterscheiden. | Screenshotinspektion |
| UI-12 | P3 | Zuordnen/Verwerfen | Fachbegriffe und ähnlich gewichtete Alternativen machen Folgen einer Entscheidung schwerer erfassbar. Die konkrete Wirkung an den betroffenen Vorschlägen beschreiben. | Screenshotinspektion |

## Details und Abnahmekriterien

### UI-01: Vergleich muss den tatsächlich übernommenen Stand zeigen

Im Test wurde der Ausschluss auf „Manueller Ausschluss“ geändert. Der Vergleich zeigte weiterhin „Unverbindliche Werbung“ aus dem Modellvorschlag. Der Benutzer kann dadurch einen anderen Stand beurteilen als den, den er anschließend übernehmen lässt.

Ursache: In [rule_learning_site.py](../src/mailhelp/web/rule_learning_site.py) wird `compare(old, proposal.proposed.model_dump(...))` mit dem ursprünglichen Vorschlag gebildet. Die Eingabefelder und `choices()` berücksichtigen dagegen bearbeitete Werte. Ein bereits vorhandener Vergleich ist deshalb keine abschließende Vorschau der eigenen Bearbeitung.

Empfehlung: „Änderungen prüfen“ erzeugt einen validierten Prüfstand aus allen ausgewählten und bearbeiteten Vorschlägen. Der anschließende Vergleich und die ausdrückliche Bestätigung beziehen sich auf genau diesen Stand. Eine weitere Bearbeitung macht dessen Bestätigung ungültig. YAML und Formular müssen denselben wirksamen Stand zeigen.

Abnahme: Ein Regressionstest ändert Feldtext und separat YAML; der endgültige Vergleich zeigt jeweils diese Änderung und die gespeicherte strukturierte Konfiguration stimmt mit dem bestätigten Prüfstand überein. Versions-, Sitzungs-, CSRF- und Idempotenzprüfungen bleiben erhalten.

### UI-02: Eingaben und Kostenschätzung widersprechen sich

Aufruf mit sieben Mails aus `Archive`, Preisannahme 0,75 USD/Million Tokens und Budget 9 USD: Die vorbereitete Auswahl enthält diese Werte korrekt. Das sichtbare Formular zeigt anschließend 20 Mails, `INBOX` und leere Preis-/Budgetfelder. Es wurde kein Modellaufruf ausgeführt. Der Befund betrifft die verlässliche Anzeige, nicht einen nachgewiesenen falschen Auftrag.

In [learning_site.py](../src/mailhelp/web/learning_site.py) wird das Formular mit festen Standardwerten aufgebaut, bevor die Schätzparameter verarbeitet werden.

Abnahme: Nach erfolgreicher und fehlgeschlagener Schätzung bleiben Postfach, Ordner, Anzahl, Preis und Budget erhalten. Angezeigte Werte, Kostengrundlage und bestätigbare Auswahl stimmen überein. Das Schätzen selbst startet keinen kostenpflichtigen Lauf.

### UI-03: Fehler auffindbar und verständlich machen

Ein leeres Beschreibungsfeld liefert „Beschreibung: String should have at least 1 character“. `aria-invalid` ist gesetzt; `aria-describedby` und `aria-errormessage` fehlen. Der Fokus steht nach der Antwort auf `BODY`, nicht beim Fehler oder einer Fehlerzusammenfassung.

In [topic_editor.py](../src/mailhelp/web/topic_editor.py) existieren sichtbare Hilfen und Fehlermeldungen, aber ohne die dafür erforderliche Feldzuordnung. Eine `role="alert"`-Ausgabe existiert bereits.

Abnahme: Kurze deutsche Fehlermeldungen; Hilfen und Fehler besitzen IDs und sind dem Feld zugeordnet. Eine verlinkte Fehlerzusammenfassung oder der erste fehlerhafte Eingang erhält nachvollziehbar den Fokus. Eingegebene Werte bleiben erhalten. Zusätzlich mit Tastatur und Screenreader prüfen; aus dieser Messung allein folgt noch kein vollständiges WCAG-Urteil.

### UI-04 und UI-05: Mobile Informationsdichte verringern

Bei 390 × 844 beginnt die erste Themenzeile erst bei ungefähr 900 Pixeln, bei 320 × 640 bei ungefähr 972 Pixeln. Auf dem schmalsten Bildschirm liegt bereits die Suche fast unter dem ersten sichtbaren Bereich. Einzelne getestete Vorschlagskarten sind dort ungefähr 605 bis 793 Pixel hoch.

Empfehlung: Den Hinweis zum Regellernen verkürzen oder einklappen, Suche und Filter gemeinsam kompakt anordnen. Die Vorschlagskarte benötigt zunächst Titel, Datum/Frist, verständlichen Status und Hauptaktion. Belege und Zusatzdetails bleiben gezielt erreichbar. Bei großen Katalogen sind Ergebnisanzahl und schrittweises Nachladen oder Seitennavigation sinnvoll; Suchfilter müssen erhalten bleiben.

Abnahme: Auf 390 × 844 sind nach der Navigation Suche und erste Ergebnisse ohne lange Einleitung erreichbar. Karten lassen sich rasch vergleichen. Auch bei 320 Pixeln, langen deutschen Texten und Tastaturbedienung bleiben alle Aktionen erreichbar.

Ein zunächst aus langen Gesamtscreenshots vermutetes Verdecken der Kartentitel wurde in den neuen Sichtbarkeits-/Treffertests nicht reproduziert: Die geprüften Titel waren in allen drei Größen sichtbar und anklickbar. Dies wird ausdrücklich nicht als bestätigter Fehler geführt; die Messung deckt nicht jede Scrollposition ab.

### UI-06 bis UI-10: Entscheidungen und nächste Schritte priorisieren

- **Regelprüfung:** Zuerst Auswahl, wirksame Änderungen und Übernahme anbieten. „Neue Analyse starten“ als separate, aufklappbare Aufgabe darstellen. Unveränderte Felder müssen nicht standardmäßig sämtliche Vergleichsinhalte wiederholen.
- **Einstellungen:** [settings_confirmation()](../src/mailhelp/web/settings_pages.py) sollte wie der Themeneditor einen lesbaren Alt-Neu-Vergleich zeigen. Nur relevante Warnungen einblenden und klar sagen, ob die Änderung sofort, nach Neuladen oder nach Neustart wirkt.
- **Status:** Eine obere Zusammenfassung „Alles bereit“ oder „Handlungsbedarf“ mit überprüfbaren Fakten versehen. „Browser verbunden“ separat von Kalender-, Mail- und Aufgabenanbindung anzeigen. Technische Zähler unter Details belassen; „unbekannt“ mit nächstem Prüfschritt erklären.
- **Lernübersicht:** [learning_overview.py](../src/mailhelp/web/learning_overview.py) verwendet bei fehlendem Startzeitpunkt „Datum früherer Läufe nicht verfügbar“, auch im leeren Zustand. Zwischen „Noch kein Lauf“ und tatsächlich unbekannter Historie unterscheiden. Die Übersicht bindet derzeit keine periodische Statusaktualisierung ein. Aktualisierung darf ausschließlich Status lesen, keinen Lauf starten.
- **Ordner und Kosten:** Ordner abhängig vom gewählten Postfach als Auswahl anbieten. Ohne JavaScript ist ein ausdrücklicher Schritt „Ordner laden“ möglich. Modell und Preisquelle beziehungsweise manuelle Preisannahme erkennbar machen; keine vermeintlich aktuellen Preise erfinden. Vor kostenpflichtiger Analyse bleibt eine ausdrückliche Freigabe erforderlich.

### UI-11 und UI-12: Weniger Wiederholung, konkretere Sprache

Den Themeneditor als zusammengehörige Gruppen aus Bezeichnung, Eingabe, Hilfe und Fehler gestalten. Große Klickflächen erhalten, ohne jedes Feld durch große Leerflächen zu trennen. Technische IDs und YAML nachrangig anbieten. In Einstellungen wiederholte Navigationslisten reduzieren und häufige Aufgaben unmittelbar zugänglich machen.

Bei Zuordnungen knapp erklären, welcher konkrete Eintrag ergänzt wird und was als eigener Vorschlag erhalten bleibt. Bei „Verwerfen“, „Schon erledigt“ und „Irrelevant“ erläutern, welche Bedeutung die Entscheidung für Bearbeitung und Lernen hat. Die erforderliche ausdrückliche, versionsbezogene Bestätigung externer Aktionen bleibt unverändert.

## Empfohlene Reihenfolge

1. **Korrektheit:** UI-01 und UI-02 jeweils mit vor dem Fix fehlschlagendem Regressionstest beheben; anschließend UI-03.
2. **Mobile Kernabläufe:** Themen finden, Vorschlag beurteilen, Regeländerung prüfen und bestätigen; UI-04 bis UI-06 gemeinsam gestalten und auf allen drei Größen prüfen.
3. **Orientierung:** Einstellungen, Status, Lernübersicht und Lernlaufvorbereitung verbessern; danach Abstände und Begriffe vereinheitlichen.

Bei einer Umsetzung müssen die bestehenden verbindlichen 100 % Zeilen- und Branch-Abdeckung, Browserprüfungen, Autorisierungsprüfungen und Versions-/Dokumentationsregeln weiterhin erfüllt werden. Das Audit selbst verändert keinen Anwendungscode und stellt keine Fehlerbehebung dar.

## Grenzen und noch offene Abnahme

Dies ist eine umfassende Prüfung der zentralen Weboberflächen mit gezielten Laufzeitproben, kein vollständiger Sicherheits-, Penetrations- oder Produktivbetriebsaudit. Echte Mailkonten, Telegram-Bedienung und externe Kalender-/Todoist-Schreibabläufe wurden hier nicht im Livebetrieb geprüft.

Die mobilen Laufzeitproben verwenden emulierte Browsergrößen; echte iPhone-/Safari-Bedienung, VoiceOver/NVDA und eine vollständige Prüfung bei 200/400 % Zoom stehen aus. Dunkeldarstellung und sämtliche Übergänge wurden nicht frisch vollständig visuell abgenommen. Die Release-Dokumentation enthält außerdem keine vollständige verlinkte Vorher-Nachher-Bildserie der UI-Überarbeitung.

Die dokumentierte Gesamtabnahme von 5.7 nennt Windows; eine erneute vollständige Linux-Abnahme dieser Version ist damit nicht belegt. Die Release-Dokumentation führt den realen kostenpflichtigen Hilfschat-Test ausdrücklich als offen. Diese offenen Nachweise sind von den hier reproduzierten UI-Fehlern zu unterscheiden.
