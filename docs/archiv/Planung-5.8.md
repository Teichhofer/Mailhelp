# Mailhelp 5.8 – Verlässliche Vorschauen und kompakte Bedienung

Stand: 11. November 2026. Grundlage: [UI-Prüfung 5.7.5](Pruefung-UI-5.7.5.md).
Ausgangsbasis ist der Arbeitsstand 5.7.6; vorhandene Änderungen bleiben erhalten.

**Status:** Mit Version 5.8.0 vollständig umgesetzt und automatisiert abgenommen.
S1–S6 abgeschlossen. Ergebnisse und verbleibende manuelle Prüfgrenzen:
[Release 5.8](Release-5.8.md).

## Ziel und Umfang

Alle zwölf Befunde der UI-Prüfung werden in den folgenden Arbeitspaketen behandelt.
Version 5.8.0 bündelt die Umsetzung und ihre Abnahme. Kostenpflichtige Modelltests,
echte externe Schreibaktionen und Änderungen an der Autorisierung gehören nicht zum Auftrag.
Bestehende Bestätigungen, Sitzungsschutz, CSRF, Versionsprüfung und Idempotenz bleiben verbindlich.

| Paket | Befunde | Umsetzung | Abnahme |
| --- | --- | --- | --- |
| S1 Verlässliche Regelvorschau | UI-01, UI-06 | Bearbeitete Felder/YAML serverseitig prüfen; eigenen beständigen Prüfstand anzeigen; erst diesen ausdrücklich übernehmen. Neue Analyse nach dem offenen Entwurf anbieten. | Regression vor Fix rot; Feld/YAML, Wiederholung, Neustart, veralteter/fremder Prüfstand, Dateiänderung und Autorisierung testen. |
| S2 Auswahl und Kosten | UI-02, UI-10 | Eingaben nach Schätzung und Fehlern erhalten; Ordner des ausgewählten Postfachs als Auswahl, mit lesendem GET-Schritt ohne JavaScript; aktive Modelle und manuelle Preisannahme kenntlich machen. | Sichtbare und bestätigte Auswahl identisch; unbekannte/weitere Ordner bleiben möglich; Schätzen/Ordnerladen ohne Modellaufruf. |
| S3 Formulare | UI-03, UI-11 | Deutsche Validierung, Fehlerzusammenfassung mit Fokus und Feldverknüpfungen; kompakte Feldgruppen und fortgeschrittene Angaben nachrangig. | Regression, Eingabeerhalt, Tastatur, axe, Desktop/Mobil/schmal. |
| S4 Mobile Kernabläufe | UI-04, UI-05 | Kompakter Themenkopf und Filter; wichtigste Kartendaten zuerst, Zusatzdetails aufklappbar, erreichbare Aktionen. | Erste Ergebnisse bei 390 × 844 sichtbar; lange Texte und 320 Pixel ohne horizontalen Überlauf oder verdeckte Aktionen. |
| S5 Orientierung und Entscheidungen | UI-07, UI-08, UI-09, UI-12 | Lesbarer Einstellungsvergleich mit konkreter Wirkung; Statuszusammenfassung; kompakte Lernübersicht mit korrektem Erstzustand und lesender Aktualisierung; Folgen von Zuordnung/Ablehnung erklären. | Erfolgs-/Fehler-/Leerzustände, unveränderte externe Bestätigung, keine Nebenwirkungen durch GET oder Aktualisierung. |
| S6 Dokumentation und Gesamtabnahme | alle | README, CHANGELOG, Spezifikation, Bedienung, Web-Einstellungen und Hilfebestand aktualisieren; Release-Nachweise und Bilder festhalten. | Ruff/Mypy/Inventur/Prompt-/Hilfebestandprüfung, komplette Python-Suite mit 100 % Zeilen- und Branch-Abdeckung, Browser-Suite inklusive verbindlicher JS-Coverage. |

## Gestaltungsregeln

- Zuerst wirksame Änderung, anschließend ausdrückliche Bestätigung; Bearbeiten allein speichert keine Themenregeln.
- Benutzertexte und Modellinhalte bleiben nicht vertrauenswürdig und werden escaped/validiert.
- Progressive Offenlegung erhält Belege und technische Details vollständig zugänglich.
- Ohne JavaScript bleiben Vorbereitung, Vorschau und Bestätigung bedienbar.
- Preise werden nicht als aktuell ausgegeben: Eine Preisobergrenze bleibt eine ausdrücklich benannte Benutzerannahme.
- Keine Coverage-Ausnahmen; jeder Bugfix bekommt einen reproduzierenden Regressionstest.

## Ausführungsnachweis

Der Fortschritt und konkrete Prüfresultate werden in [Release 5.8](Release-5.8.md) dokumentiert.
Offene reale Geräte-/Screenreader- oder Linux-Prüfungen werden dort ausdrücklich von bestandenen Prüfungen getrennt.
