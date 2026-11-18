"""7.0.15 (K5): statements of the living documents are checked against the code on every run.

(a) named configuration keys exist and every key of the model is in config.example.yaml,
(b) named command line options exist, (c) named environment variables are read somewhere,
(d) labels quoted in the guides occur in the interface, (e) named repository files exist.
(f) is tests/unit/test_helpdocs.py: the packaged help index is generated from the current guides.
"""
from __future__ import annotations

import re
import ast
import subprocess
from functools import cache
from pathlib import Path

import pytest
from pydantic import BaseModel

from mailhelp import cli
from mailhelp.config import Settings

ROOT = Path(__file__).resolve().parents[2]
GUIDES = tuple(f"docs/{name}.md" for name in (
    "Bedienung", "Betrieb", "Ersteinrichtung", "Fehlerbehebung", "Konten-verwalten", "Ziele-einrichten",
    "Web-Einstellungen", "Einrichtung-und-Qualitaetspruefung", "Google-OAuth-Playground"))
LIVING = ("README.md", "Mailhelp-Projektspezifikation.md", "DATENSCHUTZ.md", "NUTZUNGSBEDINGUNGEN.md",
          "AGENTS.md", *GUIDES, "docs/GitHub-Pages.md", "docs/Zustandsregeln-3.6.md",
          "docs/Entkopplung-Web-und-Abruf.md", "docs/Architektur.md", "docs/README.md")
# Dotted names that start like a setting but are log events, modules, files or host names.
NOT_KEYS = {"telegram.dialog.persist", "telegram.decisions", "llm.quality_metrics.gate", "llm.level",
            "imap.folders_listed", "imap.folder_list_failed", "imap.gmail.com", "imap.googlemail.com",
            "imap.example.org", "learning.js", "push.js"}
TRACKED_ROOTS = ("src/", "tests/", "ui_tests/", "docs/", "devtools/", "website/", ".github/")


def _text(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def _ticks(name: str) -> list[str]:
    return re.findall(r"`([^`\n]+)`", _text(name))


@cache
def _keys() -> frozenset[str]:
    def walk(model: type[BaseModel], prefix: str) -> set[str]:
        found = set()
        for name, info in model.model_fields.items():
            found.add(prefix + name)
            for outer in (info.annotation, *getattr(info.annotation, "__args__", ())):
                for inner in (outer, *getattr(outer, "__args__", ())):
                    if isinstance(inner, type) and issubclass(inner, BaseModel):
                        found |= walk(inner, prefix + name + ".")
        return found
    return frozenset(walk(Settings, ""))


@cache
def _code() -> str:
    """Interface and configuration texts; the help index is excluded because it repeats the guides."""
    names = subprocess.run(["git", "ls-files", "src", "*.yaml", ".env.example"], cwd=ROOT,
                           capture_output=True, text=True, check=True).stdout.split()
    return "\n".join((_text(name) + ("\n" + "\n".join(node.value for node in ast.walk(ast.parse(_text(name))) if isinstance(node, ast.Constant) and isinstance(node.value, str)) if name.endswith(".py") else "")) for name in names if name.endswith((".py", ".js", ".html", ".yaml", ".example"))
                     and "helpdocs/" not in name)


@pytest.mark.parametrize("document", LIVING)
def test_named_configuration_keys_exist(document):
    tops = {key.split(".")[0] for key in _keys()}
    unknown = [token for token in _ticks(document)
               if re.fullmatch(r"[a-z_]+(\.[a-z_0-9]+)+", token) and token.split(".")[0] in tops
               and token not in NOT_KEYS and re.sub(r"\.\d+", "", token) not in _keys()]
    assert unknown == []


def test_every_configuration_key_is_in_the_example_configuration():
    example = _text("config.example.yaml")
    leaves = {key for key in _keys() if not any(other.startswith(key + ".") for other in _keys())}
    missing = sorted(key for key in leaves
                     if not re.search(r"(^|\s|#\s?)" + re.escape(key.rsplit(".", 1)[-1]) + ":", example, re.M))
    assert missing == []


@pytest.mark.parametrize("document", LIVING)
def test_named_command_line_options_exist(document):
    options = {option for action in cli._parser()._actions for option in action.option_strings}
    commands = _ticks(document) + re.findall(r"^\s*((?:python -m )?mailhelp [^\n]+)$", _text(document), re.M)
    unknown = [option for command in commands if re.match(r"(python -m )?mailhelp(\.exe)? ", command)
               for option in re.findall(r"(?<!\S)(--[a-z][a-z-]*)", command) if option not in options]
    assert unknown == []


@pytest.mark.parametrize("document", LIVING)
def test_named_environment_variables_are_read(document):
    compose = "\n".join(_text(path.name) for path in ROOT.glob("compose*.yaml"))
    unknown = [variable for token in _ticks(document)
               for variable in re.findall(r"\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b", token)
               # Numbered secrets (IMAP_2_PASSWORD) follow the documented pattern IMAP_<n>_…
               if not re.search(r"_\d+_", variable) and variable not in _code() and variable not in compose]
    assert unknown == []


def test_every_example_variable_is_read():
    names = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", _text(".env.example"), re.M))
    unread = sorted(name for name in names if name not in _code() and not re.search(r"_\d+_", name))
    assert unread == []


# Quotes in the guides that are no label of the interface, or labels the code assembles.
NOT_LABELS = {
    "Testing": "Veröffentlichungsstatus in der Google-Konsole",
    "crypto.randomUUID is not a function": "Fehlermeldung des Browsers",
    "Weitere Ziele": "Verweis auf einen Abschnitt desselben Dokuments",
    "Intervall": "Beispiel eines Suchsynonyms",
    "Im laufenden Betrieb": "Begriff der Tabelle im Dokument selbst",
    "Stell das für mich um": "Beispiel einer Frage an den Hilfschat",
    "Beenden nicht ausgeführt": "f\"{action} nicht ausgeführt\" in web/lifecycle",
    "Neustart nicht ausgeführt": "f\"{action} nicht ausgeführt\" in web/lifecycle",
    "Bestätigt / Beim Anbieter": "zwei Spaltenköpfe der Vergleichstabelle",
    "Aus dem Postfach lernen öffnen": "f\"{title} öffnen\" in web/learning_overview",
    "Aus Entscheidungen lernen öffnen": "f\"{title} öffnen\" in web/learning_overview",
    "← Zurück zur Auswertung": "Pfeil aus web/pages.page_head(back=…)",
    "Mailhelp einrichten: Web-Zugang und Zeitzone": "Überschrift aus web/initial_pages.TITLES",
    "Läuft: … Mails geprüft, … Fehler": "Fortschritt mit Zahlen aus runtime/learning_jobs",
    "18:30 Uhr behalten": "Beispielwert; Knopf aus f\"{value} behalten\" in telegram/presenter",
    "20:30 Uhr übernehmen": "Beispielwert; Knopf aus f\"{value} übernehmen\" in telegram/presenter",
}


@pytest.mark.parametrize("document", GUIDES)
def test_labels_quoted_in_the_guides_occur_in_the_interface(document):
    """A placeholder "…" stands for a variable part; every fixed part must occur."""
    missing = []
    for label in re.findall(r"„([^“\n]{2,60})“", _text(document)):
        parts = [part.strip(" :?") for part in label.split("…") if part.strip(" :?")]
        if label not in NOT_LABELS and any(part not in _code() for part in parts):
            missing.append(label)
    assert missing == []


@pytest.mark.parametrize("document", (*LIVING, "config.example.yaml", ".env.example"))
def test_every_living_document_names_the_current_major_version(document):
    """K6: a document not reviewed for the current major version stands out at the next one."""
    import mailhelp
    major = mailhelp.__version__.split(".")[0]
    pattern = r"\*\*Version:\*\* (\d+)\." if document == "README.md" else r"Geprüft für Mailhelp (\d+)\.\d+"
    assert re.findall(pattern, _text(document))[:1] == [major]


@pytest.mark.parametrize("document", LIVING)
def test_named_repository_files_exist(document):
    tests = {path.name for folder in ("tests", "ui_tests") for path in (ROOT / folder).rglob("test_*.py")}
    missing = []
    for token in _ticks(document):
        if re.fullmatch(r"test_\w+\.py", token):
            missing += [] if token in tests else [token]
        elif token.startswith(TRACKED_ROOTS) and re.fullmatch(r"[\w./-]+", token) and not (ROOT / token).exists():
            missing.append(token)
    assert missing == []


def test_the_checks_find_outdated_statements(tmp_path, monkeypatch):
    (tmp_path / "Doc.md").write_text(
        "`imap.no_such_key` `imap.mailboxes` `mailhelp --no-such-option` `MAILHELP_NO_SUCH_VARIABLE` "
        "`test_no_such_file.py` `docs/No-Such.md` „Keine solche Schaltfläche“", encoding="utf-8")
    monkeypatch.setitem(globals(), "ROOT", tmp_path)
    monkeypatch.setitem(globals(), "_code", lambda: "")
    for check in (test_named_configuration_keys_exist, test_named_command_line_options_exist,
                  test_named_environment_variables_are_read, test_labels_quoted_in_the_guides_occur_in_the_interface,
                  test_named_repository_files_exist):
        with pytest.raises(AssertionError):
            check("Doc.md")
