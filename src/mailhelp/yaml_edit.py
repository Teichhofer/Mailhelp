"""Change scalar settings in a block-style YAML file without losing comments.

Rewriting ``config.yaml`` with ``yaml.safe_dump`` would drop every comment the
user or the example file put there.  Instead only the value of each changed key
is replaced on its own line (an inline comment stays), and a missing key is
added at the end of its section.  The caller verifies that the edited text
parses to exactly the validated candidate; otherwise nothing is written.
"""

from __future__ import annotations

import re
from typing import Any

import yaml

_KEY = re.compile(r"^(?P<indent> *)(?P<key>[A-Za-z0-9_]+):(?P<rest>.*)$")


class YamlEditError(ValueError):
    """The file cannot be changed safely at this place."""


def render(value: Any) -> str:
    """A YAML scalar for one line (numbers, booleans, null, dates and plain strings)."""
    if isinstance(value, (dict, list)):
        raise YamlEditError("Nur einzelne Werte können geändert werden")
    # Never wrapped; line breaks are escaped in double quotes, so a text stays on its own line.
    style = '"' if isinstance(value, str) and "\n" in value else None
    flow = yaml.safe_dump([value], default_flow_style=True, default_style=style, allow_unicode=True,
                          width=10**6).strip()
    return flow[1:-1]


def _split_comment(rest: str) -> tuple[str, str]:
    """Separate a value from a trailing ``# comment`` outside of quotes."""
    quote = None
    for index, char in enumerate(rest):
        if quote:
            if char == quote:
                quote = None
        elif char in "'\"":
            quote = char
        elif char == "#" and (index == 0 or rest[index - 1] in " \t"):
            return rest[:index], rest[index:]
    return rest, ""


def _paths(lines: list[str]) -> list[tuple[int, str, int]]:
    """(line index, dotted path, indent) of every block mapping key."""
    result, stack = [], []
    for index, line in enumerate(lines):
        if not line.strip() or line.lstrip().startswith(("#", "-")):
            continue
        match = _KEY.match(line)
        if match is None:
            continue
        indent = len(match["indent"])
        while stack and stack[-1][0] >= indent:
            stack.pop()
        stack.append((indent, match["key"]))
        result.append((index, ".".join(key for _, key in stack), indent))
    return result


def set_scalars(text: str, changes: dict[str, Any]) -> str:
    """Return *text* with every dotted key in *changes* set to its new scalar value."""
    lines = text.splitlines()
    for dotted, value in changes.items():
        rendered = render(value)
        paths = _paths(lines)
        found = next(((index, indent) for index, path, indent in paths if path == dotted), None)
        if found is not None:
            index, indent = found
            match = _KEY.match(lines[index])
            assert match is not None
            current, comment = _split_comment(match["rest"])
            if not current.strip() and any(path.startswith(dotted + ".") for _, path, _ in paths):
                raise YamlEditError(f"{dotted} ist ein Abschnitt, kein einzelner Wert")
            # Keep the original gap before an inline comment (at least one space).
            gap = (current[len(current.rstrip()):] or " ") if comment else ""
            lines[index] = f"{' ' * indent}{match['key']}: {rendered}{gap}{comment}"
            continue
        lines = _insert(lines, paths, dotted.split("."), rendered)
    return "\n".join(lines) + "\n"


def _insert(lines: list[str], paths: list[tuple[int, str, int]], parts: list[str],
            rendered: str) -> list[str]:
    """Add a missing key at the end of its deepest existing section."""
    for depth in range(len(parts) - 1, 0, -1):
        parent = ".".join(parts[:depth])
        found = next(((index, indent) for index, path, indent in paths if path == parent), None)
        if found is None:
            continue
        index, indent = found
        children = [ind for _, path, ind in paths if path.startswith(parent + ".")]
        child_indent = min(children, default=indent + 2)
        # The section ends with its last line that is indented deeper than its key.
        end = index
        for position in range(index + 1, len(lines)):
            line = lines[position]
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if len(line) - len(line.lstrip()) <= indent:
                break
            end = position
        block = _block(parts[depth:], rendered, child_indent)
        return lines[:end + 1] + block + lines[end + 1:]
    return lines + _block(parts, rendered, 0)


def _block(parts: list[str], rendered: str, indent: int) -> list[str]:
    block = [f"{' ' * (indent + 2 * level)}{part}:" for level, part in enumerate(parts[:-1])]
    block.append(f"{' ' * (indent + 2 * (len(parts) - 1))}{parts[-1]}: {rendered}")
    return block


__all__ = ["YamlEditError", "render", "set_list", "set_scalars"]


def set_list(text: str, dotted: str, items: list[Any]) -> str:
    """Replace the block sequence under *dotted* (``key:`` followed by ``- item`` lines)."""
    lines = text.splitlines()
    found = next(((index, indent) for index, path, indent in _paths(lines) if path == dotted), None)
    if found is None:
        raise YamlEditError(f"{dotted} fehlt in der Datei")
    index, indent = found
    match = _KEY.match(lines[index])
    assert match is not None
    current, comment = _split_comment(match["rest"])
    if current.strip():
        # An inline list ([a, b]) stays inline.
        if not current.strip().startswith("["):
            raise YamlEditError(f"{dotted} ist keine Liste")
        flow = yaml.safe_dump(list(items), default_flow_style=True, allow_unicode=True, width=10**6).strip()
        gap = (current[len(current.rstrip()):] or " ") if comment else ""
        lines[index] = f"{' ' * indent}{match['key']}: {flow}{gap}{comment}"
        return "\n".join(lines) + "\n"
    end, item_indent = index, indent + 2
    for position in range(index + 1, len(lines)):
        stripped = lines[position].lstrip()
        if stripped.startswith("- ") and len(lines[position]) - len(stripped) >= indent:
            item_indent, end = len(lines[position]) - len(stripped), position
        elif stripped and not stripped.startswith("#"):
            break
    existing = yaml.safe_load("\n".join(lines[index:end + 1]))[match["key"]] or []
    if items[:len(existing)] == existing:
        # Only new entries are appended; comments between existing entries stay.
        added = [f"{' ' * item_indent}- {render(item)}" for item in items[len(existing):]]
        return "\n".join([*lines[:end + 1], *added, *lines[end + 1:]]) + "\n"
    rendered = [f"{' ' * item_indent}- {render(item)}" for item in items]
    return "\n".join([*lines[:index + 1], *rendered, *lines[end + 1:]]) + "\n"
