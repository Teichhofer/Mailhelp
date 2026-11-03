# Paketstruktur – Bündelung der Wurzelmodule

**Stand:** 3. November 2026 (Version 3.6.10)  
**Zweck:** Zielstruktur für [Planung 3.6](Planung-3.6.md), Schritt 0.10; Grundlage ist der in
[Planung 3.3](Planung-3.3.md), Abschnitt 5, zurückgestellte Punkt.  
**Status:** Festgelegt; umgesetzt: `mailbox` (3.6.11), `processing` (3.6.12), `proposals` (3.6.13); offen: 0.10d–0.10f

---

## 1. Ausgangslage

Im Paket `mailhelp` liegen 78 Module direkt im Wurzelverzeichnis neben den bereits
gebündelten Paketen `activity`, `config`, `domain`, `external`, `persistence`, `review`,
`telegram` und `web`. Die Zuständigkeiten sind dadurch nur an Namenspräfixen erkennbar
(`mailbox_*`, `proposal_*`, `notification_*`).

## 2. Regeln

1. **Keine Verhaltensänderung.** Ein Umzug verschiebt Module und passt Importe an; Logik,
   Ereignisnamen, Zustandsnamen (`state_names.py`) und gespeicherte Formate bleiben gleich.
   Gespeicherte Zustände enthalten keine Modulpfade.
2. **Keine dauerhaften Alias-Module.** Jeder Schritt passt alle Importe seiner Gruppe in
   `src`, `tests` und `ui_tests` an, ebenso Monkeypatch-Pfade in Tests (`"mailhelp.x.Name"`),
   die mypy-Liste in `pyproject.toml`, Einstiegspunkte und Dokumentationsverweise.
3. **Feste Einstiegspunkte bleiben.** `mailhelp.cli` (Konsolenbefehl `mailhelp`, Neustart per
   `-c "from mailhelp.cli import main"`, Docker) und `mailhelp.models` (öffentliche Fassade der
   Fachmodelle) bleiben im Wurzelpaket.
4. **Ein Zielpaket je Schritt**, jeweils mit grüner Suite (100 % Abdeckung), Browsertests,
   `ruff` und `mypy`; Architekturtests werden auf die neuen Pfade umgestellt, nicht gelockert.
5. Verschoben wird mit `git mv`, damit der Verlauf je Datei erhalten bleibt.

## 3. Zielstruktur

| Zielpaket | Zuständigkeit | Module (heute im Wurzelpaket) | Schritt |
| :--- | :--- | :--- | :--- |
| `mailhelp.mailbox` | Abruf, Postfächer, IServ, Aktivierung im Betrieb | `imap`, `mime`, `mailbox_run`, `mailbox_settings`, `mailbox_activation`, `mailbox_runtime`, `mailbox_briefing`, `connection_activation`, `connection_runtime`, `iserv`, `iserv_activation`, `iserv_runtime`, `sender_filter` | 0.10a |
| `mailhelp.processing` | Verarbeitung einer Mail | `orchestrator`, `mail_pipeline`, `mail_duplicates`, `mail_questions`, `mail_recheck`, `analysis`, `attachment_extractor`, `attachments`, `calendar_parser`, `vision` | 0.10b |
| `mailhelp.proposals` | Vorschläge, Abgleich, Ziele | `proposal_builder`, `proposal_matching`, `proposal_merge`, `proposal_reconciliation`, `action_normalization`, `event_defaults`, `precheck`, `profile_binding`, `profile_usage`, `target_profiles`, `integrations` | 0.10c |
| `mailhelp.llm` | Sprachmodelle, Entscheidungsprompts, Lernen, Bewertung | `adapter`, `openrouter`, `ollama`, `decisions`, `laya`, `learning`, `evaluation`, `decision_test`, `fingerprints` | 0.10d |
| `mailhelp.notifications` | Benachrichtigungen, Push, Tagesüberblick, Antwortentwürfe | `notifications`, `notification_config`, `notification_context`, `notification_runtime`, `webpush`, `briefing`, `drafts` | 0.10e |
| `mailhelp.runtime` | Betrieb, Lebenszyklus, Einrichtung, Wartung | `application`, `composition`, `service_coordinator`, `operator_thread`, `lifecycle`, `retention`, `metrics`, `diagnostics`, `setup`, `setup_runtime`, `standalone`, `experience`, `local_pairing`, `credentials`, `env_file`, `yaml_edit`, `google_login` | 0.10f |
| Wurzelpaket (bleibt) | Einstieg und gemeinsame Grundlagen | `__init__`, `cli`, `models`, `configuration`, `state_names`, `storage`, `logging`, `paths`, `formatting`, `german_dates`, `temporal_answers` | – |

Die Reihenfolge folgt den Abhängigkeiten von unten nach oben: Abruf und Verarbeitung werden
von Vorschlägen, Sprachmodellen und Betrieb genutzt, nicht umgekehrt. `mailhelp-evaluate`
wird in 0.10d auf `mailhelp.llm.evaluation:main` umgestellt.

## 4. Prüfung je Schritt

- `git grep` findet keinen alten Modulpfad (`mailhelp.<altes_modul>`, `from .<altes_modul>`,
  `"mailhelp.<altes_modul>.`) mehr.
- Ein frisch gebautes Wheel enthält die neuen Pfade; der Paket-Test (`tests/release`) prüft
  die Liste der Module, die Wheel und Quellbaum identisch enthalten müssen.
- Der Docker-Start (`compose.smoke.yaml`) in der CI bleibt grün.
