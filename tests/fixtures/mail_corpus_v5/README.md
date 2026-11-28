# Qualitätskorpus Version 5 (8.9.1)

Referenzkorpus des [Bewertungsvertrags v5](../../../docs/Bewertungsvertrag-v5.md), eingefroren am
28.11.2026 vor dem ersten Modelllauf. Die Prüfsumme steht in `quality-reports/baseline-8.9.json`;
`tests/evaluation/test_corpus_v5.py` prüft sie. Eine Änderung ergibt eine neue Korpus- und
Vertragsversion, keine stille Korrektur.

- Die 46 Fälle aus [Korpus v4](../mail_corpus_v4/README.md) mit unveränderten Mails. `migration.changes`
  nennt je Fall jede geänderte Sollangabe mit Regel und Begründung; v4 selbst bleibt unverändert.
- 22 neue Kontrollfälle `K01` bis `K22` (`control: true`), mit anderen Namen, Daten und Formulierungen.
- Je Fall der Themenvertrag `topics` (`required`, `any_of`, `allowed`) und, wo vorab festgelegt, Aliase
  gleichbedeutender Titel unter `aliases`. Die Fälle mit Aliasen aus dem Audit vom 26.11.2026 sind
  `diagnostic: true`: Sie belegen den Prüfer, nicht die Qualität eines Modells.

Alle Adressen liegen unter `example.test`; es gibt keine persönlichen Mails und keine aufgerufenen Links.
