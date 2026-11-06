# Mutationsaudit 4.1.11

Abnahme am 6. November 2026 unter Ubuntu/WSL, Python 3.12.3, mutmut 3.8.0,
als unprivilegierter Benutzer. Befehl: `python -m devtools.check mutation`.
Alle 1.011 erzeugten Mutanten wurden ausgeführt: 1.001 getötet, zehn überlebt,
**99,01 %** insgesamt. Keine ungetesteten, übersprungenen, abgebrochenen,
verdächtigen oder durch Timeout beziehungsweise Segfault beendeten Mutanten.
Die Schranke beträgt mindestens 90 % insgesamt und in jedem der drei Kernbereiche.

| Kernbereich | Getötet / gesamt | Score |
| --- | ---: | ---: |
| `domain` | 503 / 506 | 99,41 % |
| `storage` | 352 / 355 | 99,15 % |
| `external.confirmed` | 146 / 150 | 97,33 % |

Der [vollständige JSON-Bericht](mutation-4.1.json) enthält Quelltext-Fingerprints,
Modulzahlen, Werkzeugversion und den vollständigen Diff jedes Überlebenden.
Der [frühere Ausgangsbericht](mutation-4.1-baseline.json) ist ausdrücklich ein
unvollständiger Zwischenstand mit anderer Testzuordnung und teilweise anderem
Quelltext. Er ist kein gültiger Vorher-Score für einen numerischen Vergleich.

## Einzelbewertung aller zehn Überlebenden

Die folgenden Namen sind mit dem jeweiligen Modulpräfix `mailhelp.domain.processing.`,
`mailhelp.domain.proposal.`, `mailhelp.external.confirmed.` oder `mailhelp.storage.`
im JSON-Bericht vollständig angegeben. Alle bleiben im Nenner des Scores;
die Bewertung erzeugt keine Ausschlüsse oder nachträglich als getötet gezählten Fälle.

| Modul | Mutant | Bewertung |
| --- | --- | --- |
| `domain.processing` | `xǁTelegramDialogStateǁreference__mutmut_1` | Äquivalent für validierte Zustände: `complete_reference` erlaubt ausschließlich drei gesetzte oder drei leere Referenzfelder. Die geänderte Verknüpfung liefert für diese beiden Fälle denselben Wahrheitswert. |
| `domain.processing` | `xǁTelegramDialogStateǁreference__mutmut_2` | Dieselbe Modellinvariante verhindert die Teilreferenz, die die geänderte Verknüpfung unterscheiden würde. |
| `domain.proposal` | `x__revision_interval__mutmut_40` | Redundante Zuweisung: `end` wurde unmittelbar aus `changes.get("end")` gelesen. Das erneute Schreiben desselben vorhandenen Werts ändert das Ergebnis nicht. |
| `external.confirmed` | `x_execute_confirmed__mutmut_27` | Der geänderte `getattr`-Fallback wird nicht verwendet: innerhalb des `TargetWriter`-Zweigs existiert `target_profile` bereits als geerbtes Klassenattribut. |
| `external.confirmed` | `x_execute_confirmed__mutmut_30` | Das Entfernen desselben unbenutzten Fallbacks ändert den Profilabgleich nicht. |
| `external.confirmed` | `x_execute_confirmed__mutmut_33` | Auch ein anderer Wert dieses unbenutzten Fallbacks ändert den Profilabgleich nicht. |
| `external.confirmed` | `x__with_external_result__mutmut_33` | Der frühere Guard weist `external_id is None` bereits zurück. Die spätere bedingte Umwandlung erreicht deshalb stets den `str`-Zweig. |
| `storage` | `xǁJsonStoreǁ__enter____mutmut_42` | `ascii` und `ASCII` sind derselbe Python-Codec; die Sperrmetadaten bleiben bytegleich. |
| `storage` | `xǁJsonStoreǁpeek__mutmut_4` | `False` und `None` aktivieren dieselbe ausschließlich über ihren Wahrheitswert geprüfte, schreibfreie Leseroute. |
| `storage` | `xǁJsonStoreǁsave__mutmut_27` | Der Standard-JSON-Encoder behandelt `ensure_ascii=False` und `None` beide als falsch; Unicode-Ausgabe und gespeicherte Bytes bleiben gleich. |

Die Bewertung gilt für die validierten Modelle und konkreten Verträge dieses
Quelltextstands. Geänderte Verträge erfordern einen neuen Lauf und eine neue Bewertung.

## Durch das Audit verschärfte Prüfungen

Die direkten Tests prüfen jetzt insbesondere genaue Versions- und Revisionsschritte,
Widerruf aller Sonderfreigaben, stabile Rückfragekennungen, Erhalt bestätigter
Terminanfänge, unvollständige Zeitfakten und Zeitzonen ohne UTC-Offset. Für externe
Aktionen prüfen sie Profilbindung, erneute Autorisierung, Persistieren vor dem
Schreiben und Wiederaufnahme unklarer Ergebnisse ohne doppelte Anlage.
Speichertests prüfen Unicode und LF unabhängig von OS-Standards, atomare Reihenfolge,
Aufräumen auch bei Abbruch, Sperren mit Dateideskriptor null sowie unveränderte Bytes
bei schreibfreiem Lesen beschädigter Akten und deren spätere Isolation.

Dabei wurde ein echter Fehler gefunden: Ungültiges UTF-8 umging die Behandlung
beschädigter JSON-Dateien. Derselbe Regressionstest scheiterte vor der Korrektur mit
`UnicodeDecodeError` und besteht danach mit dem vorgesehenen `CorruptState`-Verhalten.
