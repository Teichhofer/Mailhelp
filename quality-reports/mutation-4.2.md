# Mutationsaudit 4.2.0

6. November 2026, mutmut 3.8.0 unter Ubuntu/WSL als unprivilegierter Benutzer.
`python -m devtools.check mutation` besteht: **1.027 von 1.053 Mutanten getötet
(97,53 %)**. Alle erzeugten Mutanten wurden ausgeführt; keine ungetesteten,
übersprungenen, abgebrochenen, verdächtigen, durch Timeout oder Segfault beendeten Fälle.

| Kernbereich | Getötet / gesamt | Score |
| --- | ---: | ---: |
| `domain` | 501 / 506 | 99,01 % |
| `storage` | 380 / 397 | 95,72 % |
| `external.confirmed` | 146 / 150 | 97,33 % |

Die Schranke von 90 % gilt insgesamt und je Kernbereich. Die zusätzlichen
Sperrzeitprüfungen erfassen jetzt jeden instrumentierten Ablagezugriff unmittelbar.
Die Tests für `already_done` und seine versionsgenaue Wiederaufnahme ergänzen die
direkten Invarianten. Der Score bezieht sich auf die vom Werkzeug erzeugten Mutanten;
er ist kein Beweis für jeden denkbaren Fehler oder für echte Modellqualität.
Wegen des erweiterten Mutantensatzes ist er kein direkter Vorher-/Nachher-Vergleich
mit dem 4.1-Audit.

## Bewertung aller 26 Überlebenden

Der [JSON-Bericht](mutation-4.2.json) enthält jeden vollständigen Namen, seinen Diff,
die Einzelbewertung und Quelltext-Fingerprints. Alle Überlebenden bleiben im Nenner;
keiner wird durch die folgende Bewertung ausgenommen oder als getötet gezählt.
Einige Fälle bleiben ausdrücklich Testlücken in bestehenden Diagnose- und
Robustheitsverträgen; der geforderte Score wird trotzdem in jedem Kernbereich erreicht.

Die Kurzformen entsprechen den vollständigen Funktionsnamen im JSON-Bericht.

| Modul / Funktion | Mutanten | Bewertung |
| --- | --- | --- |
| `domain.processing.TelegramDialogState.reference` | 1, 2 | Für validierte Modelle äquivalent: Die drei Referenzfelder sind gemeinsam gesetzt oder gemeinsam leer. |
| `domain.proposal.Proposal._check_merge_and_defaults` | 12 | Verbleibende Validierungs-Testlücke: Unpassende Herkunft einer Standarddauer bei sonst vollständigem Terminintervall. Versionsbindung und Bestätigung bleiben unverändert. |
| `domain.proposal._revision_interval` | 40 | Erneutes Schreiben des schon aus `changes` gelesenen Endes ist redundant. |
| Dieselbe Funktion | 51 | Bei validierten Zeitfakten muss der reine Datumsbeginn bereits in `changes` stehen; die erneute Zuweisung ist redundant. |
| `external.confirmed.execute_confirmed` | 27, 30, 33 | Der geerbte `TargetWriter.target_profile` macht den geänderten beziehungsweise entfernten `getattr`-Fallback unerreichbar. |
| `external.confirmed._with_external_result` | 33 | Der vorherige ID-Guard hat `None` bereits abgelehnt. |
| `storage.atomic_replace` | 8, 10 | Nur der temporäre Dateinamenpräfix entfällt. Zielverzeichnis und atomarer Ersatz bleiben erhalten; das Namensdetail ist kein präzise geprüfter Funktionsvertrag. |
| Dieselbe Funktion | 31, 33 | Verbleibende Fehlerbereinigungs-Testlücke: Ist die temporäre Datei bereits verschwunden, kann FileNotFoundError den ursprünglichen Fehler ersetzen. |
| `storage.JsonStore.__enter__` | 42 | ASCII-Codec-Alias ohne Änderung der Bytes. |
| `storage.JsonStore.peek` | 10 | `False` und `None` wählen dieselbe schreibfreie Leseroute. |
| `storage.JsonStore._read` | 32 | UTF-8-Codec-Alias ohne Verhaltensänderung. |
| `storage.JsonStore.peek_model` | 4 | Weggelassenes explizites `None` entspricht dem Port-Default. |
| `storage.JsonStore._load_model` | 4 | Derselbe identische Default. |
| Dieselbe Funktion | 26 | Verbleibende Diagnose-Testlücke für Trennzeichen verschachtelter Schema-Schlüsselpfade. Ablehnung und Isolation bleiben erhalten. |
| Dieselbe Funktion | 33 | Zusätzliche lokale `input`-Fehlerdaten bleiben ungenutzt; nur `loc` gelangt in die Meldung. Es werden dadurch keine Eingaben protokolliert. |
| `storage.JsonStore.save` | 7 | Großgeschriebene Staging-Endung; fertige JSON-Akten und deren Inventur bleiben unverändert. Der genaue temporäre Name bei Abbruch ist nicht abgesichert. |
| Dieselbe Funktion | 14, 16, 18 | Verbleibende Robustheits-Testlücke für direkten `save` ohne vorheriges Betreten des Stores bei mehreren fehlenden Elternverzeichnissen. Der reguläre Start erzeugt sie in `__enter__`. |
| Dieselbe Funktion | 29 | UTF-8-Codec-Alias ohne Änderung der Bytes. |
| Dieselbe Funktion | 33 | `ensure_ascii=False` und `None` sind für diesen JSON-Encoder beide falsch. |

Die verbleibenden Lücken rechtfertigen keine Absenkung der Zeilen-/Branch-Schranke
und keine Ausnahmen von Autorisierung, Versionsbindung oder Schreibsicherheit.
