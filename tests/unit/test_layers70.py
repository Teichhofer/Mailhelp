"""7.0 (R3): imports follow the layers of the application; every exception is named with its reason.

A module may import from its own layer and from lower layers. Function-level imports count as well:
they are dependencies too. The test fails on a new import against the direction and on an exception
that is no longer needed.
"""
from __future__ import annotations

import ast
from pathlib import Path

import mailhelp

PACKAGE = Path(mailhelp.__file__).parent
LAYERS = (
    ("mailhelp", "domain", "text", "state_names", "paths", "formatting", "log_reduction"),
    ("logging", "persistence", "support"),
    ("config",),
    ("external", "llm"),
    ("mailbox", "proposals"),
    ("processing", "review", "rule_learning", "notifications", "activity"),
    ("runtime",),
    ("telegram", "web", "helpdocs"),
    ("app",),
    ("cli",),
)
LEVEL = {area: index for index, areas in enumerate(LAYERS) for area in areas}
# Modules whose package mixes layers: their own layer, with the reason.
MODULE_LEVELS = {
    # Evaluation, decision test, learning and the decision clients run the analysis; the provider
    # adapters of the same package stay low.
    "mailhelp.llm.decision_test": 5, "mailhelp.llm.evaluation": 5, "mailhelp.llm.learning": 5,
    "mailhelp.llm.decisions": 5, "mailhelp.llm.laya": 5,
    # Catalogue of every stored schema for the checking tools; no application module imports it.
    "mailhelp.persistence.schemas": 8,
}
CONFIG_RULES = "Validierung der Einstellungen nutzt die Fachregel dieses Bereichs"
EDITING = "Konfigurationsänderungen laufen als bestätigte Befehle mit demselben Ergebnisformat"
MAIL_RUN = "Der Abruf übergibt jede Mail der Verarbeitung und wertet deren Ergebnis aus"
EXCEPTIONS = {
    ("mailhelp.config.configuration", "mailhelp.llm.learning"): "Themenänderungen schreiben das Lernformat",
    ("mailhelp.config.configuration", "mailhelp.mailbox.sender_filter"): "Absenderliste wird über den Filter gespeichert",
    ("mailhelp.config.configuration", "mailhelp.proposals.profile_usage"): "Zielprofile nur löschen, wenn unbenutzt",
    ("mailhelp.config.configuration", "mailhelp.review.commands"): EDITING,
    ("mailhelp.config.configuration", "mailhelp.review.results"): EDITING,
    ("mailhelp.config.configuration", "mailhelp.runtime.setup"): "Einrichtungsstand nach Änderungen fortschreiben",
    ("mailhelp.config.loader", "mailhelp.llm.fingerprints"): "Konfigurationsfingerabdruck beim Laden",
    ("mailhelp.config.loader", "mailhelp.mailbox.imap"): CONFIG_RULES,
    ("mailhelp.config.loader", "mailhelp.mailbox.mailbox_settings"): CONFIG_RULES,
    ("mailhelp.config.loader", "mailhelp.proposals.target_profiles"): "Geheimnisse der Zielprofile laden",
    ("mailhelp.config.models", "mailhelp.llm.ollama"): CONFIG_RULES,
    ("mailhelp.config.models", "mailhelp.mailbox.mailbox_settings"): CONFIG_RULES,
    ("mailhelp.config.models", "mailhelp.proposals.target_profiles"): CONFIG_RULES,
    ("mailhelp.mailbox.connection_activation", "mailhelp.review.results"): EDITING,
    ("mailhelp.mailbox.iserv", "mailhelp.processing.orchestrator"): MAIL_RUN,
    ("mailhelp.mailbox.mailbox_activation", "mailhelp.runtime.experience"): "neues Postfach mit dem laufenden Leser prüfen",
    ("mailhelp.mailbox.mailbox_run", "mailhelp.processing.orchestrator"): MAIL_RUN,
    ("mailhelp.mailbox.mailbox_run", "mailhelp.processing.retry"): MAIL_RUN,
    ("mailhelp.processing.analysis", "mailhelp.helpdocs"): "Hilfeantworten werden wie Analyseantworten geprüft",
    ("mailhelp.processing.orchestrator", "mailhelp.telegram.formatting"): "Mailzeile der Fehlermeldung",
    ("mailhelp.processing.orchestrator", "mailhelp.web.factory"): "Link zur Mail in Meldungen",
    ("mailhelp.review.service", "mailhelp.telegram.callbacks"): "Telegram-Entscheidungen sind Prüfbefehle",
    ("mailhelp.review.service", "mailhelp.telegram.commands"): "Telegram-Entscheidungen sind Prüfbefehle",
}


def _module(path: Path) -> tuple[str, bool]:
    parts = path.relative_to(PACKAGE.parent).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts), parts[-1] == "__init__"


def _level(module: str) -> int:
    for name, level in MODULE_LEVELS.items():
        if module == name or module.startswith(name + "."):
            return level
    parts = module.split(".")
    return LEVEL[parts[1] if len(parts) > 1 else "mailhelp"]


def _targets(node: ast.Import | ast.ImportFrom, module: str, is_package: bool, known: set[str]) -> list[str]:
    if isinstance(node, ast.Import):
        names = [alias.name for alias in node.names]
    else:
        base = node.module or ""
        if node.level:
            parts = module.split(".")
            parts = parts[: len(parts) - node.level + (1 if is_package else 0)]
            base = ".".join([*parts, node.module] if node.module else parts)
        names = [f"{base}.{alias.name}" if f"{base}.{alias.name}" in known else base for alias in node.names]
    result = []
    for name in names:
        while name.startswith("mailhelp") and name not in known:
            name = name.rsplit(".", 1)[0]
        if name.startswith("mailhelp"):
            result.append(name)
    return result


def violations() -> set[tuple[str, str]]:
    paths = sorted(PACKAGE.rglob("*.py"))
    known = {_module(path)[0] for path in paths}
    found = set()
    for path in paths:
        module, is_package = _module(path)
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for target in _targets(node, module, is_package, known):
                    if _level(target) > _level(module):
                        found.add((module, target))
    return found


def test_every_area_has_a_layer():
    areas = {path.relative_to(PACKAGE).parts[0].removesuffix(".py") for path in PACKAGE.iterdir()
             if path.suffix == ".py" or (path.is_dir() and (path / "__init__.py").exists())}
    assert areas - {"__init__"} <= set(LEVEL)


def test_imports_follow_the_layers_except_the_named_cases():
    assert violations() == set(EXCEPTIONS)
    assert all(reason for reason in EXCEPTIONS.values())


# 7.0 (R4): imports inside functions are the exception. Each one names its reason on the line above.
LATE_IMPORT_LIMIT = 25


def late_imports() -> list[tuple[str, int, str]]:
    found = []
    for path in sorted(PACKAGE.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines()
        for function in ast.walk(ast.parse(source)):
            if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for node in ast.walk(function):
                    if isinstance(node, (ast.Import, ast.ImportFrom)):
                        found.append((path.relative_to(PACKAGE).as_posix(), node.lineno, lines[node.lineno - 2].strip()))
    return found


def test_late_imports_stay_few_and_each_names_its_reason():
    found = late_imports()
    assert len(found) <= LATE_IMPORT_LIMIT
    assert [item for item in found if not item[2].startswith("# Late: ")] == []
