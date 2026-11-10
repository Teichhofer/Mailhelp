"""5.3 (H1): the inventory of every setting and command-line option, generated from the code.

``python -m devtools.inventory`` rewrites the generated section of
``docs/Pruefung-Dokumentation-5.3.md``; ``--check`` fails when it is outdated. The table is the
coverage matrix of the documentation review: one row per setting with type, default, limits,
how it is changed and whether the settings reference documents it.
"""
from __future__ import annotations

import argparse
import sys
import types
import typing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs" / "Pruefung-Dokumentation-5.3.md"
REFERENCE = ROOT / "docs" / "Web-Einstellungen.md"
START, END = "<!-- inventar:start -->", "<!-- inventar:end -->"
LIMITS = {"ge": "≥", "gt": ">", "le": "≤", "lt": "<", "min_length": "Länge ≥", "max_length": "Länge ≤"}


@dataclass(frozen=True)
class Row:
    key: str
    kind: str
    default: str
    limits: str
    path: str
    documented: bool


def _models(annotation: Any) -> list[type[BaseModel]]:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    return [model for argument in typing.get_args(annotation) for model in _models(argument)]


def _kind(annotation: Any) -> str:
    """A readable type: constraints and wrappers are left out, choices are listed."""
    origin, arguments = typing.get_origin(annotation), typing.get_args(annotation)
    if origin is typing.Annotated:
        return _kind(arguments[0])
    if origin is typing.Literal:
        return "Auswahl: " + ", ".join(str(item) for item in arguments)
    if origin in (typing.Union, types.UnionType):
        return " oder ".join(_kind(item) for item in arguments if item is not type(None)) + (
            " (optional)" if type(None) in arguments else "")
    if origin is not None:
        return f"{getattr(origin, '__name__', str(origin))}[{', '.join(_kind(item) for item in arguments)}]"
    return getattr(annotation, "__name__", str(annotation))


def _resolved(annotation: Any, model: type[BaseModel]) -> Any:
    """A forward reference such as ``"MailboxRetention | None"`` evaluated in the model's module."""
    if isinstance(annotation, typing.ForwardRef):
        return eval(annotation.__forward_arg__, vars(sys.modules[model.__module__]))  # noqa: S307 - own code
    return annotation


def _is_list(annotation: Any) -> bool:
    if typing.get_origin(annotation) is list:
        return True
    return any(_is_list(item) for item in typing.get_args(annotation))


def _default(field: FieldInfo) -> str:
    if field.default_factory is not None:
        value: Any = field.default_factory()  # type: ignore[call-arg]
    elif field.default is PydanticUndefined:
        return "Pflicht"
    else:
        value = field.default
    text = "–" if value is None else repr(value)
    return text if len(text) <= 40 else text[:39] + "…"


def _limits(field: FieldInfo) -> str:
    found = []
    for item in field.metadata:
        for name, sign in LIMITS.items():
            value = getattr(item, name, None)
            if value is not None:
                found.append(f"{sign} {value}")
    return ", ".join(found)


def _path(key: str, web: set[str], setup: set[str]) -> str:
    plain = key.replace("[]", "")
    if plain in web or key in web:
        return "Weboberfläche"
    if plain in setup or key in setup:
        return "Einrichtung"
    return "Datei"


def settings_rows(reference: str) -> list[Row]:
    from mailhelp.config import Settings
    from mailhelp.configuration import SETTINGS_FIELDS, SETUP_FIELDS
    rows: list[Row] = []

    def walk(model: type[BaseModel], prefix: str, seen: frozenset[type[BaseModel]]) -> None:
        for name, field in model.model_fields.items():
            key = prefix + name
            annotation = _resolved(field.annotation, model)
            inner = [item for item in _models(annotation) if item not in seen]
            if inner:
                nested = _is_list(annotation)
                for item in inner:
                    walk(item, key + ("[]." if nested else "."), seen | {item})
                continue
            rows.append(Row(key, _kind(annotation), _default(field), _limits(field),
                            _path(key, SETTINGS_FIELDS, SETUP_FIELDS), f"`{key}`" in reference))

    walk(Settings, "", frozenset({Settings}))
    return sorted(rows, key=lambda row: row.key)


def cli_rows() -> list[tuple[str, str]]:
    from mailhelp.cli import _parser
    return sorted((", ".join(action.option_strings), (action.help or "").replace("|", "∣"))
                  for action in _parser()._actions if action.option_strings and action.dest != "help")


def render(reference: str) -> str:
    rows = settings_rows(reference)
    documented = sum(row.documented for row in rows)
    lines = [START, "", f"Erzeugt mit `python -m devtools.inventory`: **{len(rows)} Einstellungen**, davon "
             f"**{documented}** mit eigenem Eintrag in [Web-Einstellungen](Web-Einstellungen.md).", "",
             "| Schlüssel | Typ | Standard | Grenzen | Bedienweg | Referenz |", "| --- | --- | --- | --- | --- | --- |"]
    lines += [f"| `{row.key}` | {row.kind} | {row.default} | {row.limits} | {row.path} | "
              f"{'ja' if row.documented else '**fehlt**'} |" for row in rows]
    options = cli_rows()
    lines += ["", f"**{len(options)} Kommandozeilenoptionen** (`mailhelp --help`):", "",
              "| Option | Bedeutung laut Hilfe |", "| --- | --- |"]
    lines += [f"| `{option}` | {text} |" for option, text in options]
    return "\n".join([*lines, "", END])


def updated(document: str, reference: str) -> str:
    head, _, rest = document.partition(START)
    _, _, tail = rest.partition(END)
    return head + render(reference) + tail


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inventur der Einstellungen und Optionen")
    parser.add_argument("--check", action="store_true", help="nur prüfen, ob der Bericht aktuell ist")
    args = parser.parse_args(argv)
    document = REPORT.read_text(encoding="utf-8")
    fresh = updated(document, REFERENCE.read_text(encoding="utf-8"))
    if args.check:
        if fresh != document:
            print("Inventur veraltet: python -m devtools.inventory ausführen", file=sys.stderr)
            return 1
        return 0
    REPORT.write_bytes(fresh.encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
