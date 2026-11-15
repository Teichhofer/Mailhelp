# Mailhelp 6.9 – Karten am Finger und aktuelle Übersicht

## Veröffentlichung

6.9.1 bündelt die Arbeitspakete D1 bis D7 aus [Planung 6.9](Planung-6.9.md).
Die dort vorgeschlagenen Zwischenpatches werden nicht einzeln veröffentlicht.
Umgesetzt sind W1 bis W12 und U2 bis U6. U1 (kompaktere Karten) bleibt ausgeschlossen.
Ausgangspunkt ist die veröffentlichte und installierte Version 6.8.2, Commit 6d52f39.

6.9.2 ergänzt die abschließende Freigabeprüfung. Der Scrolltest unterdrückt die
separat geprüfte Einführung, damit deren zeitgesteuerter Hintergrund nicht als
Wischbewegung gewertet wird. Die neue Testsuite ist formatiert.

## Verhalten

Eine angenommene Geste folgt in beiden Achsen ohne Bremse, mit begrenzter Neigung
um den Griffpunkt. Hohe Karten drehen weniger. Der Browser entscheidet anhand von
pan-y, wann Scrollen die Geste abbricht. Die Karte beginnt erst, wenn die Bewegung
nicht steiler als 45° ist, also an der gemessenen Grenze; vorher bewegt sie sich nicht. Stift und Finger bleiben auf Ansichten unter
1024 px beschränkt; Maus, Eingaben, Textauswahl, Randgesten und seitlich scrollbare
Inhalte behalten ihre Bedienung.

Auslösen ist über die bisherige Strecke oder begrenzten Schwung möglich: mindestens
die halbe Schwelle und 0,9 px/ms waagerecht in Verschiebungsrichtung, gemessen aus den
letzten 100 ms. Die Darstellung wird höchstens einmal pro Animationsbild aktualisiert.
Gesperrte Aktionen erhalten ein Gummiband, ein Schloss und den bestehenden Grund.

Ausgelöste Karten fliegen zu einem 56 px hohen Ergebnisstreifen. Erst danach wird
genau das vorhandene Formular einmal gesendet. Sitzung, CSRF, Version und
Idempotenzschlüssel bleiben unverändert. Ablehnungen bringen die bedienbare Karte
zurück; unklare Antworten behalten die Statusprüfung, ohne erneutes Senden.
Die verborgene Karte bleibt für die Ergebniszuordnung im DOM. Reduzierte Bewegung
verwendet direktes Folgen ohne Neigung und kurze Rückkehr beziehungsweise Überblenden.

Auf dem Telefon stehen Titel und Absender/Zeit vor den Aktionen, Status und Fristen
darunter. Die Titel kommen weiterhin aus dem gespeicherten Vorschlag; bei gültigen
Testdaten fehlt kein Titel. Lange Titel werden auf zwei Zeilen begrenzt und maskiert.
Zähler, Tab-Abzeichen und leerer Zustand werden aus derselben frischen Übersicht
übernommen; gesetzte Filter bleiben erhalten. Filterchips zeigen verborgenes
rechtes Ende durch einen Verlauf. Die Relevanzerklärung ist aufklappbar.

Die Aktionsleiste klebt in der Liste auf dem Telefon nicht mehr am unteren Rand
(bisher seit 2.0): Unter dem nun oben stehenden Titel würde sie ihn beim Hereinscrollen
verdecken. Sie steht direkt unter Titel und Absender; die Prüfung aus 6.2.8 (erste
Entscheidung im oberen Fensterbereich) besteht weiter.

Die einmalige Einführung wartet 600 ms Ruhe und eine vollständig sichtbare Karte
mit beiden Entscheidungsrichtungen ab. Sie bewegt die Karte höchstens 110 px oder
ein Drittel ihrer Breite und zurück, ohne Formular oder Klick. Die kurze Zeile ersetzt
den Erklärungskasten. Schließen oder der erste erfolgreiche Wisch speichern weiterhin
mailhelp-swipe-hint; frühere Bestätigungen werden übernommen. Bei gesperrtem Speicher
erfolgt die Vorführung höchstens einmal je Seite. Reduzierte Bewegung, Desktop und
veraltete Seite erhalten keine Vorführung.

## Browsermessung

Automatisiert geprüft wird der tatsächlich installierte **Chrome 157.0.8103.78**
mit nativen Touch-Ereignissen über CDP, Telefonfenster und iPhone-Geräteparametern.
Das ist eine Chrome-Messung; die iPhone-Kennung emuliert kein Safari.

| Winkel nach rechts oben | Beobachtung im getesteten Chrome |
| --- | --- |
| 20° | Karte folgt und entscheidet |
| 35° | Karte folgt und entscheidet |
| 40° | Karte folgt in beiden Achsen; Regression auf 6.8.2 scheitert |
| 44° | Karte folgt und entscheidet |
| 45°, 46°, 50°, 55°, 60° | natives pointercancel, Scrollen, keine Entscheidung |

Zusätzlich prüfen Tests den transformierten Griffpunkt mit maximal 2 px Abweichung,
fehlende Bremse und unveränderte Dokumentbreite während und nach der Bewegung.
Screenshots für halben Weg, Schwelle, Flug und Einführung liegen in der lokalen
Testsammlung für helles und dunkles Farbschema.

## Zusätzliche abgesicherte Fälle

Eine Aktualisierung des Bestands darf eine laufende Geste oder einen akzeptierten
Flug nicht verwerfen, bevor dessen Formular gesendet wurde. Der scheiternde Test
auf dem Zwischenstand belegt die Lücke; die Aktualisierung wartet jetzt bis zum
Ergebnis. Wiederholte Gesten während des Flugs senden keine zweite Anfrage.

Die CDP-Messung zählt UTF-16-Codeeinheiten. Der bisherige Leser verwendete direkt
Python-Zeichenpositionen und konnte nach Emojis danebenliegen. Ein Regressionstest
belegt die Verschiebung; die neue Messung rechnet die Positionen korrekt um und
behält Windows-Zeilenenden bei. Abdeckung wird ohne Ausschlüsse gemessen.

Bei der Abschlussprüfung fiel auf, dass die aufklappbare Erklärung „Was bedeuten diese
Entscheidungen?“ auf dem Telefon auch auf jeder Vorschlagskarte der Liste erschien und
Karten um rund 60 px höher machte (Browsertest `test_cards58…[narrow]`: 828 statt höchstens
793 px). Gewollt war das nur für die Relevanzkarte (U5). Die Vorschlagserklärung steht
wieder nur in der Detailansicht; der Browsertest scheiterte vor der Korrektur und besteht danach.

Die zweite vollständige Browserprüfung zeigte einen zeitabhängigen Fehler: Bei einem steilen
Wisch (etwa 56°) begann die Karte schon nach 10 px seitlich zu folgen, bevor Chrome das Scrollen
übernahm, und federte dann zurück; beim Scrollen war das als kurzes Zucken sichtbar. Ein neuer
Regressionstest mit synthetischen Zeigerereignissen scheitert ohne Korrektur zuverlässig. Die
Karte startet jetzt erst bei einer Bewegung, die nicht steiler als 45° ist; die Winkelmessung
oben bleibt unverändert gültig.

## Prüfstand und Geräteabnahme

Abschlussprüfung am 15. November 2026: 5 297 Python-Tests mit 100 % Zeilen- und
Branch-Abdeckung und bestandene Lasttests sind der Freigabemaßstab.
Die vollständige Browsersuite bestand 897 Tests bei 214 gerätebedingt übersprungenen
Fällen; ein Scrolltest wurde durch die unabhängig laufende Einführung beeinflusst.
Nach Trennung der Prüfungen bestanden beide Scrollvarianten und drei genaue
Schwunggrenzen (5 bestanden, 10 gerätebedingt übersprungen). Die zusammengeführte,
unveränderten Skriptdateien zugeordnete reale CDP-Messung deckt 100 % der Blöcke
von app.js, sw.js, setup.js, topics.js und learning.js ab. Ruff und mypy melden Befunde nur in Dateien, die 6.9 nicht
verändert; sie bestanden schon in 6.8.2 und sind nicht Teil dieser Version. Automatisierte Tests verwenden ausschließlich
synthetische Daten und simulierte externe Dienste. Vorher-Nachweise für den
40°-Wisch, die Bremse und veraltete Zähler liegen vor.

Die reale Abnahme auf iPhone (Safari und installierte Web-App) und Android Chrome
ist **offen**. Insbesondere die jeweils zehn schrägen Wischgesten, zwanzig Scrollgänge,
Randgeste, Fokus auf dem Griffpunkt und Schwungquote können nicht durch die
Chrome-Emulation als bestanden gelten. Sie wird erst nach Betreiber-Rückmeldung
ergänzt. Die Bedienung ohne JavaScript bleibt vollständig erhalten.
