"""7.0: size and structure figures of the application code, before and after the refactoring.

``python -m devtools.code_metrics --output quality-reports/refactoring-7.0-vorher.json`` writes the
figures. They are read from the source with :mod:`ast`; nothing is imported or executed.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "mailhelp"


def _functions(tree: ast.AST) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _parameters(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    arguments = node.args
    return len(arguments.posonlyargs) + len(arguments.args) + len(arguments.kwonlyargs)


def _lines(node: ast.AST) -> int:
    return int(getattr(node, "end_lineno", 0)) - int(getattr(node, "lineno", 0)) + 1


def _area(module: str) -> str:
    """Top-level area of a module: its subpackage, or the module itself at the top level."""
    return module.split(".")[1] if module.count(".") >= 1 else module


def _module_name(path: Path, package: Path) -> str:
    parts = path.relative_to(package.parent).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _imported(node: ast.Import | ast.ImportFrom, module: str, is_package: bool) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if node.level == 0:
        return [node.module or ""]
    base = module.split(".")
    base = base[: len(base) - node.level + (1 if is_package else 0)]
    if node.module:
        return [".".join([*base, node.module])]
    return [".".join([*base, alias.name]) for alias in node.names]


def measure(package: Path = PACKAGE) -> dict[str, Any]:
    functions: list[dict[str, Any]] = []
    classes: list[dict[str, Any]] = []
    late_imports: Counter[str] = Counter()
    edges: Counter[tuple[str, str]] = Counter()
    files = lines = 0
    for path in sorted(package.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        files += 1
        lines += len(source.splitlines())
        name = _module_name(path, package)
        where = str(path.relative_to(package.parent.parent)).replace("\\", "/")
        for function in _functions(tree):
            functions.append({"file": where, "name": function.name, "lines": _lines(function),
                              "parameters": _parameters(function)})
            late_imports[where] += sum(isinstance(inner, (ast.Import, ast.ImportFrom))
                                       for inner in ast.walk(function))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                methods = [child for child in node.body if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))]
                classes.append({"file": where, "name": node.name, "lines": _lines(node), "methods": len(methods)})
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for target in _imported(node, name, path.name == "__init__.py"):
                    if target.startswith("mailhelp.") and _area(target) != _area(name):
                        edges[(_area(name), _area(target))] += 1
    functions.sort(key=lambda item: (-item["lines"], item["file"], item["name"]))
    classes.sort(key=lambda item: (-item["lines"], item["file"], item["name"]))
    return {
        "files": files, "lines": lines, "functions": len(functions),
        "functions_over_60_lines": sum(item["lines"] > 60 for item in functions),
        "functions_over_80_lines": sum(item["lines"] > 80 for item in functions),
        "functions_over_100_lines": sum(item["lines"] > 100 for item in functions),
        "functions_over_10_parameters": sum(item["parameters"] > 10 for item in functions),
        "longest_functions": functions[:15],
        "most_parameters": sorted(functions, key=lambda item: (-item["parameters"], item["file"]))[:15],
        "largest_classes": classes[:10],
        "late_imports": sum(late_imports.values()),
        "late_imports_by_file": dict(sorted(late_imports.items(), key=lambda item: (-item[1], item[0]))[:15]),
        "imports_between_areas": {f"{source} -> {target}": count for (source, target), count in sorted(edges.items())},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Kennzahlen des Anwendungscodes")
    parser.add_argument("--output", type=Path, help="JSON-Datei; ohne Angabe auf die Standardausgabe")
    args = parser.parse_args(argv)
    text = json.dumps(measure(), ensure_ascii=False, indent=2) + "\n"
    if args.output is None:
        sys.stdout.write(text)
    else:
        args.output.write_text(text, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
