"""5.3 (H7): the reviewed documentation as a versioned package resource for the help chat.

``python -m devtools.help_index`` splits every released source document into sections by its
headings and writes ``src/mailhelp/helpdocs/sections.json`` with ``manifest.json``; ``--check``
fails when the packaged resource no longer matches the sources. Only the documents listed in
``SOURCES`` are used: no plans, release reports, changelog or private files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src" / "mailhelp" / "helpdocs"
# The released help sources, in this order; every other document is never a chat source.
SOURCES = ("docs/Web-Einstellungen.md", "docs/Ersteinrichtung.md", "docs/Konten-verwalten.md",
           "docs/Ziele-einrichten.md", "docs/Bedienung.md", "docs/Fehlerbehebung.md", "docs/Betrieb.md")
MAX_SECTION = 6000


def slug(heading: str) -> str:
    """An ASCII section id from a heading: umlauts folded, punctuation removed."""
    text = heading.strip().casefold()
    for umlaut, plain in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        text = text.replace(umlaut, plain)
    text = re.sub(r"[^a-z0-9\- ]", "", text)
    return re.sub(r"-+", "-", text.replace(" ", "-")).strip("-")


def _chunks(lines: list[str]) -> list[str]:
    """A long section split at paragraph or table-row boundaries, each at most MAX_SECTION bytes."""
    parts, current = [], ""
    for line in lines:
        if current and len((current + line + "\n").encode("utf-8")) > MAX_SECTION:
            parts.append(current.rstrip())
            current = ""
        current += line + "\n"
    parts.append(current.rstrip())
    return parts


def sections(path: str, text: str, keys: frozenset[str] = frozenset()) -> list[dict[str, object]]:
    stem = Path(path).stem.casefold()
    found: list[dict[str, object]] = []
    trail: list[str] = []
    body: list[str] = []
    title = ""

    def flush() -> None:
        content = [line for line in body if line.strip()]
        if not content:
            return
        first = body.index(content[0])
        last = len(body) - body[::-1].index(content[-1])
        for number, chunk in enumerate(_chunks(body[first:last]), start=1):
            identity = f"{stem}/{slug(title) or 'einleitung'}" + (f"-{number}" if number > 1 else "")
            named = set(re.findall(r"`([a-z_][a-z0-9_.\[\]]*)`", chunk)) & keys
            found.append({"id": identity, "title": title, "path": list(trail), "source": path, "text": chunk,
                          "setting_ids": sorted(named)})

    for line in text.splitlines():
        heading = re.match(r"^(#{1,3}) (.+)$", line)
        if heading:
            flush()
            level, title = len(heading.group(1)), heading.group(2).strip()
            trail = trail[:level - 1] + [title]
            body = []
            continue
        body.append(line)
    flush()
    return found


def build(root: Path = ROOT) -> tuple[list[dict[str, object]], dict[str, object]]:
    from devtools.inventory import settings_rows
    from mailhelp import __version__
    keys = frozenset(row.key for row in settings_rows(""))
    entries: list[dict[str, object]] = []
    sources = []
    for path in SOURCES:
        text = (root / path).read_text(encoding="utf-8")
        entries += sections(path, text, keys)
        sources.append({"path": path, "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()})
    payload = json.dumps(entries, ensure_ascii=False, sort_keys=True, indent=1)
    manifest = {"schema_version": 1, "app_version": __version__, "sources": sources,
                "revision": hashlib.sha256(payload.encode("utf-8")).hexdigest(), "sections": len(entries)}
    return entries, manifest


def render(root: Path = ROOT) -> dict[str, str]:
    entries, manifest = build(root)
    return {"sections.json": json.dumps(entries, ensure_ascii=False, sort_keys=True, indent=1) + "\n",
            "manifest.json": json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=1) + "\n",
            "settings.json": json.dumps(search_entries(root, entries), ensure_ascii=False, sort_keys=True, indent=1)
            + "\n"}


def search_entries(root: Path, entries: list[dict[str, object]]) -> list[dict[str, str]]:
    """Public metadata from the reviewed reference, also usable without the help reader."""
    from devtools.inventory import settings_rows
    from mailhelp.configuration import SETTINGS_FIELDS
    from mailhelp.web.settings_search import _summary

    reference = (root / SOURCES[0]).read_text(encoding="utf-8")
    found = []
    for row in settings_rows(reference):
        if row.key in SETTINGS_FIELDS:
            continue
        section, line = next((item, line) for item in entries if item["source"] == SOURCES[0]
                             for line in str(item["text"]).splitlines()
                             if line.startswith("|") and f"`{row.key}`" in line)
        description = line.strip("| ").split(" | ")[1]
        found.append({"id": f"setting:{row.key}", "key": row.key, "label": row.key,
                      "area": "Weitere Einstellungen", "path": row.path,
                      "summary": _summary(f"{row.path}: {description}"), "help": description,
                      "href": f"/hilfe/dokumentation/{section['id']}"})
    return found


def main(argv: list[str] | None = None, target: Path = TARGET) -> int:
    parser = argparse.ArgumentParser(description="Hilfebestand aus der freigegebenen Dokumentation erzeugen")
    parser.add_argument("--check", action="store_true", help="nur prüfen, ob der Bestand aktuell ist")
    args = parser.parse_args(argv)
    files = render()
    if args.check:
        stale = [name for name, text in files.items()
                 if not (target / name).exists() or (target / name).read_text(encoding="utf-8") != text]
        if stale:
            print("Hilfebestand veraltet: python -m devtools.help_index ausführen", file=sys.stderr)
            return 1
        return 0
    target.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (target / name).write_bytes(text.encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
