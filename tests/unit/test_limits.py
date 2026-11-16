"""7.0 (R5): no function over 80 lines; at most 10 parameters, except the named entry points.

Functions are split along their tasks, not to meet a number. The exceptions keep their signature
because callers and tests construct them with keyword arguments; each names its reason. The test
fails on a new violation and on an exception that is no longer needed.
"""
from __future__ import annotations

import ast
from pathlib import Path

import mailhelp

PACKAGE = Path(mailhelp.__file__).parent
MAX_LINES = 80
MAX_PARAMETERS = 10
DEPENDENCIES = "Konstruktor, dem der Zusammenbau jede Abhängigkeit einzeln übergibt; Tests ersetzen sie einzeln"
PROVIDER_CALL = "Aufruf eines KI-Anbieters mit allen Parametern einer Stufe aus prompts.yaml"
ENTRY = "Einstiegspunkt, den Tests und der Zusammenbau mit Schlüsselwörtern aufrufen"
PARAMETER_EXCEPTIONS = {
    ("logging.py", "__init__"): "Jede Protokolleinstellung einzeln, damit config.yaml sie ohne Umweg setzt",
    ("llm/learning.py", "__init__"): DEPENDENCIES,
    ("processing/orchestrator.py", "__init__"): DEPENDENCIES,
    ("telegram/dialog.py", "__init__"): DEPENDENCIES,
    ("llm/decision_test.py", "__init__"): DEPENDENCIES,
    ("llm/openrouter.py", "__init__"): DEPENDENCIES,
    ("web/site.py", "__init__"): DEPENDENCIES,
    ("telegram/revisions.py", "__init__"): DEPENDENCIES,
    ("llm/openrouter.py", "complete"): PROVIDER_CALL,
    ("processing/analysis.py", "complete"): PROVIDER_CALL,
    ("llm/decision_test.py", "run_decision_test"): ENTRY,
    ("llm/decision_test.py", "_initial_report"): ENTRY,
    ("app/composition.py", "build_application"): ENTRY,
    ("cli.py", "_run"): ENTRY,
    ("helpdocs/chat.py", "__init__"): DEPENDENCIES,
    ("mailbox/imap.py", "__init__"): DEPENDENCIES,
    ("notifications/drafts.py", "__init__"): DEPENDENCIES,
    ("notifications/drafts.py", "_append"): "Schreibschritt mit Prüfpunkt je Wert; Tests unterbrechen ihn gezielt",
    ("web/review_pages.py", "overview_page"): ENTRY,
}


def _functions() -> list[tuple[str, str, int, int]]:
    found = []
    for path in sorted(PACKAGE.rglob("*.py")):
        where = path.relative_to(PACKAGE).as_posix()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                arguments = node.args
                parameters = len(arguments.posonlyargs) + len(arguments.args) + len(arguments.kwonlyargs)
                found.append((where, node.name, int(node.end_lineno or 0) - node.lineno + 1, parameters))
    return found


def test_no_function_is_longer_than_80_lines():
    assert [(where, name, lines) for where, name, lines, _ in _functions() if lines > MAX_LINES] == []


def test_long_parameter_lists_are_only_the_named_entry_points():
    over = {(where, name) for where, name, _, parameters in _functions() if parameters > MAX_PARAMETERS}
    assert over == set(PARAMETER_EXCEPTIONS)
    assert all(PARAMETER_EXCEPTIONS.values())
