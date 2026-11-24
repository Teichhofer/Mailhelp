# Mailhelp 8.6 – Stabile Python-3.12-CI für Ubuntu 26.04 und saubere Workflow-Artefakte

**Stand:** 24. November 2026. **Status:** Umgesetzt in 8.6.1; Stand und Nachweise in
[Release 8.6](Release-8.6.md).

**Zielversion:** 8.6, erste Auslieferung 8.6.1; weitere Commits mit
fortlaufenden Patchversionen gemäß [Entwicklungsregeln](../AGENTS.md).

**Grundlagen:** [Entwicklungsregeln](../AGENTS.md),
[Spezifikation](../Mailhelp-Projektspezifikation.md),
[Serverhandbuch](Serverhandbuch.md),
[Betrieb](Betrieb.md).

## 1. Ausgangslage und Fehleranalyse

Am 23. November 2026 schlug der wöchentliche GitHub-Actions-Lauf
**Mutation audit** (`.github/workflows/mutation.yml`) bereits in Schritt 3
(`actions/setup-python@v6`) fehl:

```text
The version '3.12.10' with architecture 'x64' was not found for Ubuntu 26.04.
The list of all available versions can be found here:
https://raw.githubusercontent.com/actions/python-versions/main/versions-manifest.json
```

Als Folgefehler meldete Schritt 7 (`actions/upload-artifact@v6` mit `if: always()`):

```text
No files were found with the provided path:
mutants/mutmut-cicd-stats.json mutants/**/*.meta. No artifacts will be uploaded
```

### Ursachen
1. **Runner-Wechsel auf Ubuntu 26.04**: GitHub hat `ubuntu-latest` von Ubuntu 24.04
   auf Ubuntu 26.04 umgestellt. In `actions/python-versions` existieren für
   Ubuntu 26.04 keine vorkompilierten Binaries für das ältere Patch-Release
   **Python `3.12.10`**, sondern nur für aktuelle `3.12.x`-Patchversionen.
2. **Breite Betroffenheit im Repository**: Dieselbe harte Festlegung
   `python-version: '3.12.10'` auf `ubuntu-latest` steht an sieben Stellen in vier
   Workflow-Dateien:
   - `.github/workflows/ci.yml` (`tests`, `static-analysis`, `ui-tests`, `package-smoke`)
   - `.github/workflows/mutation.yml` (`mutation`)
   - `.github/workflows/release.yml` (`publish`)
   - `.github/workflows/weekly.yml` (`dependency-audit`)
3. **Veraltetes Basisimage in Dockerfiles**: Auch `Dockerfile` und
   `ops/auth/Dockerfile` pinnen noch `FROM python:3.12.10-slim` statt der
   aktuellen gepatchten `3.12.x`-Patchversion.
4. **Irreführender Artefakt-Folgefehler**: In `mutation.yml` (und analog in
   `ci.yml` für `ui-screenshots`) läuft `actions/upload-artifact@v6` mit
   `if: always()`, ohne `if-no-files-found: ignore` oder vorherige Existenzprüfung.
   Bricht der Job vor dem Testlauf ab, entsteht eine verwirrende Sekundärmeldung.

## 2. Ziel und Abnahme

- Alle GitHub-Actions-Workflows (`CI`, `Mutation audit`, `Release`, `Weekly`)
  laufen auf `ubuntu-latest` (Ubuntu 26.04) und `windows-latest` wieder stabil
  und reproduzierbar mit Python `3.12.x` durch.
- Kein Workflow auf `ubuntu-latest` schlägt bei zukünftigen Ubuntu-Runner-Updates
  wegen einer veralteten exakten `3.12.x`-Patchversion fehl.
- Ein früher Job-Abbruch vor dem Test- oder Mutationslauf erzeugt keinen
  irreführenden Artefakt-Folgefehler.
- Die Docker-Basisimages (`Dockerfile` und `ops/auth/Dockerfile`) verwenden ein
  aktuelles gepatchtes `python:3.12.x-slim`-Image (kompatibel zu
  `requires-python = ">=3.12,<3.13"` in `pyproject.toml`).
- Ein automatisierter Regressionstest verhindert künftig, dass in
  GitHub-Workflows erneut eine harte Python-Patchversion auf `ubuntu-latest`
  eingetragen wird.

## 3. Abgrenzung

Nicht Bestandteil von Version 8.6 sind:

- ein Upgrade auf Python 3.13 oder 3.14 (`requires-python = ">=3.12,<3.13"` bleibt unverändert)
- eine Lockerung der festgeschriebenen Abhängigkeiten in `requirements.lock`,
  `requirements-lint.lock` oder `requirements-mutation.lock`
- Änderungen an der Anwendungslogik von Mailhelp oder `inboxstride-auth`
- automatische Änderungen an laufenden Produktionscontainern ohne gesonderte
  Deployment-Freigabe

## 4. Arbeitspakete

### AP1 – GitHub-Actions-Workflows auf `python-version: '3.12'` umstellen
In allen vier Workflow-Dateien wird `python-version: '3.12.10'` durch
`python-version: '3.12'` ersetzt:
- `.github/workflows/ci.yml` (Jobs `tests`, `static-analysis`, `ui-tests`, `package-smoke`)
- `.github/workflows/mutation.yml` (Job `mutation`)
- `.github/workflows/release.yml` (Job `publish`)
- `.github/workflows/weekly.yml` (Job `dependency-audit`)

Damit wählt `actions/setup-python@v6` auf `ubuntu-latest` (Ubuntu 26.04) und
`windows-latest` automatisch die aktuellste verfügbare `3.12.x`-Patchversion.
Die in `pyproject.toml` definierte Grenze `>=3.12,<3.13` bleibt unverändert
wirksam.

### AP2 – Artefakt-Upload bei frühem Job-Abbruch absichern
- In `.github/workflows/mutation.yml` (`mutation-results`) und
  `.github/workflows/ci.yml` (`ui-screenshots`) wird bei
  `actions/upload-artifact@v6` explizit `if-no-files-found: ignore` ergänzt
  (oder der Schritt nur ausgeführt, wenn der vorherige Test-/Mutationsschritt
  überhaupt erreicht wurde).
- Ziel: Bei regulärem Lauf oder Testfehlschlag werden Artefakte wie bisher
  hochgeladen; bei einem Abbruch im Setup-Schritt erscheint keine falsche
  Folgewarnung.

### AP3 – Docker-Basisimages auf aktuelle Python-3.12-Patchversion prüfen und anheben
- `Dockerfile` und `ops/auth/Dockerfile` von `python:3.12.10-slim` auf die
  aktuelle stabile `python:3.12.x-slim`-Patchversion (oder `python:3.12-slim`
  mit dokumentiertem Digest/Stand beim Build) aktualisieren, damit auch im
  Container aktuelle Python-3.12- und Debian-Sicherheitsfixes enthalten sind.
- Sicherstellen, dass `requirements.lock` sowie der gesamte `container-smoke`-Job
  mit dem aktualisierten Basisimage ohne Fehler durchlaufen.

### AP4 – Regressionstest für Workflow-Konfiguration
- Neuer Regressionstest in `tests/release/` (z. B.
  `tests/release/test_ci_workflows.py`):
  - parst alle `.github/workflows/*.yml` mit PyYAML,
  - prüft, dass jeder `actions/setup-python`-Schritt auf `ubuntu-latest` (oder
    in einer Matrix mit `ubuntu-latest`) den Minor-Kanal `'3.12'` statt einer
    festen Patchversion `'3.12.<n>'` verwendet,
  - prüft, dass `actions/upload-artifact`-Schritte mit `if: always()` das Feld
    `if-no-files-found: ignore` setzen.
- Der Test schlägt vor der Umsetzung von AP1/AP2 nachweislich fehl und besteht
  nach dem Fix.

### AP5 – Dokumentation, Versionsstand und Verifikation
- `pyproject.toml` und `src/mailhelp/__init__.py` auf `8.6.1` anheben,
  `CHANGELOG.md`, `README.md`, `docs/README.md` sowie `docs/Release-8.6.md`
  aktualisieren und den gebündelten Hilfe-Index (`devtools.help_index`) neu bauen.
- Vollständige lokale Python-Prüfung ausführen:
  `python -m devtools.check full --workers 12` (100 % Zeilen- und Branch-Abdeckung).
- Nach Commit/Push die GitHub-Actions-Läufe verifizieren:
  - `CI` (alle Jobs auf `ubuntu-latest` und `windows-latest`, inkl. `container-smoke`)
  - `Mutation audit` (manuell über `workflow_dispatch` anstoßen)
  - `Weekly` (`dependency-audit`, manuell über `workflow_dispatch` prüfen)

## 5. Abnahmeszenarien

| Nr. | Szenario | Erwartung |
| --- | --- | --- |
| 1 | Regressionstest vor AP1/AP2 | Schlägt wegen `'3.12.10'` auf `ubuntu-latest` und fehlendem `if-no-files-found: ignore` fehl |
| 2 | Regressionstest nach AP1/AP2 | Besteht für alle Dateien unter `.github/workflows/*.yml` |
| 3 | Lokale Vollprüfung (`devtools.check full --workers 12`) | Besteht mit 100 % Zeilen- und Branch-Abdeckung |
| 4 | GitHub Actions `CI` auf `ubuntu-latest` (Ubuntu 26.04) & `windows-latest` | `setup-python` installiert `3.12.x`, alle Jobs inkl. `ui-tests` und `container-smoke` grün |
| 5 | GitHub Actions `Mutation audit` (`workflow_dispatch`) | `setup-python` erfolgreich, `mutmut` läuft an und lädt `mutation-results` hoch |
| 6 | GitHub Actions `Weekly` (`dependency-audit`) | `setup-python` und `pip-audit` laufen auf Ubuntu 26.04 erfolgreich durch |
| 7 | Docker-Build (`Dockerfile` & `ops/auth/Dockerfile`) | Baut sauber mit aktualisiertem Python-3.12-Basisimage und besteht `--check` / `container-smoke` |

## 6. Rückkehrverfahren

Sollte das aktualisierte Python-`3.12.x`-Patchrelease wider Erwarten eine
Inkompatibilität in einer gepinnten Abhängigkeit zeigen, können die Workflows
vorübergehend explizit auf `runs-on: ubuntu-24.04` zurückgestellt werden, bis
`requirements.lock` angepasst ist. Produktive Container werden erst nach
erfolgreichem `CI`- und `container-smoke`-Lauf sowie ausdrücklicher
Deployment-Freigabe aktualisiert.
