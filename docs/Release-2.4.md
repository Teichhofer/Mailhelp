# Offene Entscheidungen und Standarddauern – Bedienung und Upgrade

> Historischer Versionsstand: Dieses Dokument beschreibt die genannte Version oder
> deren damaligen Plan. Ursprüngliche Ziele und Prüfergebnisse sind kein Nachweis
> des heutigen Umfangs. Aktueller Betrieb: [README](../README.md),
> [Release 3.3](Release-3.3.md) und [Projektspezifikation](../Mailhelp-Projektspezifikation.md).

Die Planung 2.4 ist auf `beta` umgesetzt: 2.3.2 enthält die Implementierung,
2.3.3 die Abschlussdokumentation. Die Patchnummern folgen den Entwicklungsregeln.
Ein Release 2.4.0 oder ein Tag wird dadurch nicht veröffentlicht.

## Bedienung

Neue Mails werden auch mit offenen Entscheidungen abgeglichen. Eindeutige
Ergänzungen landen im bestehenden Vorschlag; seine Ansicht zeigt alle Quellen.
Unklare Zuordnungen oder Konflikte benötigen eine Entscheidung über Web oder
Telegram. Alte Vorschlagslinks führen zum kanonischen Vorschlag. Veraltete
Bestätigungen führen nach einer Änderung nicht zur Anlage.

Unter `/abgleich` zuerst die Vorschau prüfen, dann die gewünschte lokale Änderung
übernehmen: Vorschläge zuordnen, getrennt behalten, Dauerannahmen aktualisieren,
einen fehlgeschlagenen externen Leseabgleich wiederholen oder fehlende Einzelakten
aus gespeicherten Mailbefunden wiederherstellen. Die Vorschau bindet den jeweiligen
Bestand und die Version. Bestätigte oder bereits ausgeführte Vorgänge werden durch
die Wiederherstellung nicht neu angelegt. Ein bestätigter Altbefund erhält einen
unklaren Schreibstatus und wird ausschließlich abgeglichen.

Beispiel: Eine spätere Mail ergänzt den Teams-Link zu einem offenen Austausch.
Bei eindeutiger Zuordnung bleibt eine Entscheidung mit zusätzlicher Quelle.
Eine Rückmeldeaufgabe bleibt eine eigene Aufgabe und verweist auf die Sitzung.
Bereits im Kalender vorhandene Sitzungen erscheinen als vorhandene Termine.

## Standarddauern

In Einrichtung und Einstellungen stehen zwei Werte, entsprechend in `config.yaml`:

```yaml
event_defaults:
  video_duration_minutes: 60
  in_person_duration_minutes: 180
```

Belegte Videokonferenz um 16 Uhr ohne Ende: angenommene Endzeit 17 Uhr.
Belegter Präsenztermin um 10 Uhr ohne Ende: angenommene Endzeit 13 Uhr.
Eine ausdrücklich angegebene Dauer von 90 Minuten bleibt 90 Minuten. Unklare
Teilnahmeart erhält keine Standarddauer. Jede Annahme bleibt sichtbar.
Änderungen der Einstellungen gelten für neue Normalisierungen; bestehende
Annahmen lassen sich über die gebundene Vorschau aktualisieren.

## Upgrade, Aufbewahrung und Rollback

1. Dienst anhalten und eine vollständige Kopie von Konfiguration, Geheimnissen und
   Zustandsverzeichnis erstellen. Geheimnisse bleiben außerhalb des Repositorys.
2. Paket oder Docker-Image aktualisieren, Konfiguration mit `--check` prüfen und
   Dienst starten. Fehlende neue Einstellungen erhalten ihre Standardwerte.
3. `/abgleich` authentifiziert öffnen und Bestandsvorschläge prüfen. Bestehende
   reale Vorschläge werden nicht im Hintergrund zusammengeführt oder neu angelegt.
4. Für einen Rollback Dienst stoppen und vorherige Programmversion zusammen mit
   dem gesicherten Zustand verwenden. Ältere geschlossene Schemas können neue
   Zustandsfelder nicht lesen.

Quellen enthalten Referenzen, Betreffe, Nachrichtenzeiten und gehashte
Gesprächsanker. Vergleichscaches speichern strukturierte Ergebnisse; laufende
Journale enthalten notwendige Revisionen. Abgeschlossene Journale behalten nur
Referenzen. Ungeklärte Zusatzquellen bleiben bis zur Entscheidung vor
Inhaltsbereinigung geschützt. Die [Datenschutzhinweise](../DATENSCHUTZ.md) beschreiben
den begrenzten Kandidatenkontext für den optionalen KI-Vergleich.

Technische Details: [Architektur](Architektur-2.4.md), fachliche Untersuchung und
Abnahmebedingungen: [Planung](Planung-2.4.md).
