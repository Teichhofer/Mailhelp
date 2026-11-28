# Promptverfeinerung am 26.11.2026

Fortsetzung der [Anwesenheitsprüfung](event-arrival-2026-11-26.md), ausdrücklich
vom Nutzer beauftragt. Geändert wurden ausschließlich die Systemprompts für
Aktionsrouter, Aufgaben- und Terminextraktion sowie ihre identische Paketvorlage.
Modelle, Parameter, Provider, Anwendungscode, Bewertungsschwellen, eingefrorene
Korpora und Baselines wurden dafür nicht verändert. Keine Produktivbereitstellung.

## Inhalt der letzten Fassung

- Eine bestätigte Belegung der eigenen verwalteten Unterkunft oder des eigenen
  Stellplatzes gehört zum eigenen Kalender, auch wenn die Gäste andere Personen
  sind. Datumsbezogene Belegungszeiträume ohne Uhrzeiten sind ganztägig;
  Stornierungen bleiben Absagen. Datumsgrenzen werden nicht umgerechnet.
- Konkret benannte Ressourcen bleiben wörtlich im Ortsfeld erhalten. Fehlende
  Adressen werden nicht erfunden. Eine Veranstaltung mit bloßem Datum bleibt
  ohne Ganztagsevidenz klärungsbedürftig.
- Eine Kalendervormerkung ist keine zusätzliche Aufgabe. Gesonderte Anmeldung,
  Vorbereitung oder Rückmeldung bleiben eigene Handlungen.
- Ein Bericht über die Arbeit anderer mit ausdrücklich fehlendem Eigenauftrag
  erzeugt keine Aktion. Eigener Absender allein beweist keine eigene Notiz:
  Eine bereits versandte Bitte an einen anderen Empfänger wird kein Selbstauftrag.
  Echte eigene Teilnahmenotizen bleiben erhalten.
- Eine fremde Rückmeldung im Kontext einer eigenen Einladung soll, wenn erkannt,
  mit fremder Zuständigkeit erhalten bleiben. Sie wird nicht zum eigenen Auftrag.
  Konkrete unverbindliche Ideen bleiben unsicher; bloße Themen erzeugen keinen Auftrag.
- Die frühere Anwesenheitsregel bleibt erhalten. Sie ändert weder Zuständigkeiten
  noch die Zeitart einer ganztägigen Belegung. Eine Rückfrage wegen fehlender früherer
  Uhrzeit setzt voraus, dass frühere Anwesenheit tatsächlich verlangt wird.

## Vorgehen und Budget

Nach den bereits verbrauchten 349 von 600 zusätzlich genehmigten Aufrufen standen
251 für diese Fortsetzung zur Verfügung. Die drei Läufe waren hart begrenzt und
nutzten ausschließlich synthetische Daten:

| Lauf | Fälle | Aufrufe |
| --- | ---: | ---: |
| Vollständiger v4-Korpus, erste Verfeinerung | 46 | 175 |
| Vier Ankunftskontrollen und sechs zusätzliche synthetische Fälle | 10 | 41 |
| Letzte Fassung: Ressourcen, Sicherheitsfälle, eigene Notiz, Ankommen | 9 | 32 |
| Diese Fortsetzung insgesamt | 65 | 248 |

Gemeldete Kosten dieser Fortsetzung: **0,155045 USD**. Insgesamt sind damit
**597/600 zusätzlich genehmigte Aufrufe** verwendet. Einschließlich der ersten
39 Aufrufe: **636 Aufrufe und 0,392999 USD**. Keine weiteren Modellaufrufe.

Die erste Verfeinerung wurde nach dem vollständigen Lauf verworfen: Die zu breite
Regel für fremde Aufgaben erzeugte Kandidaten in `42_foreign_responsibility` und
`43_sent_request_to_others`. Außerdem fehlte bei zwei Buchungen das Ortsfeld.
Die Gesamtprüfung dieser Fassung scheiterte. Ihre Antworten und Fehlbewertungen
bleiben unter `prompt-refinement-v4-2026-11-26.json`, `*-answers-*` und `*-metrics-*`
unverändert erhalten. Diese Ergebnisse werden nicht als Abnahme der letzten
Fassung dargestellt. Die zehn Kontrollen dieser Zwischenfassung stehen in
`prompt-refinement-controls-2026-11-26.json`: Aufgaben und Termine jeweils 10/10;
vier Zusammenfassungsvergleiche weichen ab.

Anschließend wurden nur Ortsfelderhalt und die Sicherheitsausnahmen präzisiert.
Die letzte Fassung wurde mit neun Fällen erneut geprüft. Sechs Fälle wurden samt
Erwartungen unverändert aus v4 übernommen; hinzu kommen zwei unveränderte
Ankunftsfälle und eine neue benannte Campingressource. Weder v4 noch dessen
Erwartungen oder akzeptierte Alternativen wurden verändert.

## Ergebnis der letzten Fassung

`prompt-refinement-final-controls-2026-11-26.json` enthält die echten Rohantworten:

| Stufe | Bestanden |
| --- | ---: |
| Relevanz | 9/9 |
| Zusammenfassung | 6/9 |
| Aktionsrouter | 9/9 |
| Aufgabenextraktion | 9/9 |
| Terminextraktion | 9/9 |

Keine technischen Fehler oder unlesbaren Antworten. Buchungsbestätigung und
Stornierung bestehen nun vollständig mit eigenem Kalenderbezug, ganztägiger
Zeitart und erhaltenem Ort. Die neue Ressource bleibt als `Campingstellplatz R9`
im Ortsfeld. Die beiden erneut geprüften Sicherheitsfälle erzeugen tatsächlich
keine Aufgaben und keine Termine. Die eigene Teilnahmenotiz bleibt ein Event.
Ankommen 13:40 statt Begrüßung 14:00 und freiwilliger Kaffee vor Beginn 10:00
werden weiterhin korrekt unterschieden. Diese Felder wurden zusätzlich gelesen.

Grenze des Erfolgswerts: Bei `16_invitation_feedback_other` liefert das Modell
erneut keinen fremden Aufgabenkandidaten. Die unveränderten v4-Alternativen lassen
dies zu, deshalb besteht der Stufenvergleich; das belegt keine zuverlässige
Erkennung aller fremden Rückmeldungen. Diese Einschränkung wird nicht verdeckt.

Die drei fehlgeschlagenen Zusammenfassungsvergleiche betreffen zusätzliche
Uhrzeiten beziehungsweise eine fremde Freitagsfrist. Die unveränderte
Zusammenfassungsanweisung verlangt ausdrücklich auch Zeitangaben und fremde
Fristen; die Erwartungsnormalisierung verwirft beziehungsweise erwartet diese
teilweise anders. Der Bericht bleibt deshalb insgesamt nicht bestanden.
Diese Inhalte wurden nicht entfernt, um einen grünen Lauf zu erzielen.

**Keine vollständige Freigabe:** Die letzte Fassung wurde nicht noch einmal auf
allen 46 v4-Fällen gemessen; das verbleibende Budget wurde nicht überschritten.
Eine erfolgreiche Gesamtprüfung wird daher nicht behauptet. Beide Baselines
bleiben unverändert, das Prompt-Gate sperrt den lokalen Entwurf weiterhin.

## Regressionen und lokale Prüfung

Die ersten elf neuen Beispieltests scheiterten vor der Verfeinerung. Zwei weitere
Tests für das Ortsfeld und vier für die Sicherheitsausnahmen scheiterten jeweils
vor dem entsprechenden Fix. Die Beispiele sind synthetisch, schemakonform und
gegen beide Promptkopien geprüft; ein eigener unabhängiger Verarbeitungsvertrag
prüft zusätzlich die Korpora. Simulierte Antworten belegen keine Modellqualität.
Die sechs v4-Fälle des letzten Kontrollkorpus werden auf unveränderte Inhalte und
Erwartungen geprüft.

Die abschließende gezielte Suite prüft Promptbeispiele, Normalisierung, Analyse,
Dokumentation und Baselines: **173 bestanden, ein erwarteter Fehler** des
unveränderten Prompt-Gates (27,18 Sekunden). Laufprotokolle in `.test-tmp/`:
`refinement-red.log`, `refinement-location-red.log`, `refinement-exclusion-red.log`
und `refinement-final-check.log`. Diese lokalen Protokolle sind nicht in Git.

Die vollständigen Python- und Browserprüfungen der vorangegangenen Arbeitsphase
sind im ersten Prüfbericht mit ihren Fehlern dokumentiert. Sie werden durch diese
gezielte Nachprüfung nicht als grün dargestellt. In dieser Fortsetzung wurde kein
Anwendungscode geändert; parallele Änderungen anderer Arbeiten blieben unangetastet.

Maschinenlesbare Budget-, Fingerabdruck- und Ergebnisprüfung:
`prompt-refinement-summary-2026-11-26.json`. Der letzte Modellfingerabdruck stimmt
mit dem aktuellen Prompt überein; die Paketvorlage ist identisch. Alle Änderungen
und Berichte sind lokal, noch nicht committed oder gepusht. Keine Server- oder
Kalenderänderungen.

Nachtrag: Die später ausdrücklich angeforderten Gesamtprüfungen einschließlich
vollständiger Modellevaluation der letzten Fassung stehen im
[Restprüfbericht](remaining-tests-2026-11-26.md). Die obigen Aussagen beschreiben
den Abschlussstand der vorherigen Verfeinerungsphase.
