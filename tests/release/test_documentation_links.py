"""7.0.14 (K2): relative links between the documents resolve, also after the move into docs/archiv."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LINK = re.compile(r"\]\(([^)\s]+)\)")
# Archived documents describe their version; links from them into the code may name files that have
# moved since. Links between documents and to images must keep working everywhere.
DOCUMENT = re.compile(r"\.(md|png)$")


def _documents() -> list[Path]:
    names = subprocess.run(["git", "ls-files", "*.md"], cwd=ROOT, capture_output=True, text=True,
                           check=True).stdout.split()
    return [ROOT / name for name in names]


def _broken(path: Path) -> list[str]:
    archived = ROOT / "docs" / "archiv" in path.parents
    result = []
    for target in LINK.findall(path.read_text(encoding="utf-8")):
        file = target.split("#", 1)[0]
        if re.match(r"[a-z]+:", target) or not re.search(r"[./]", file):
            continue  # web links, anchors and text in brackets such as an emoji
        if archived and not DOCUMENT.search(file):
            continue
        if not (path.parent / file).exists():
            result.append(target)
    return result


def test_every_relative_link_of_a_document_resolves():
    broken = {path.relative_to(ROOT).as_posix(): links for path in _documents() if (links := _broken(path))}
    assert broken == {}


def test_a_broken_link_is_found_and_archived_code_links_are_tolerated(tmp_path, monkeypatch):
    archive = tmp_path / "docs" / "archiv"
    archive.mkdir(parents=True)
    (tmp_path / "docs" / "Living.md").write_text("[a](archiv/Old.md) [b](Missing.md) [c](../src/gone.py) [d](📧)",
                                                encoding="utf-8")
    (archive / "Old.md").write_text("[e](../Living.md) [f](../../src/gone.py) [g](Gone.md#x) [h](https://x.y)",
                                   encoding="utf-8")
    monkeypatch.setitem(globals(), "ROOT", tmp_path)
    assert _broken(tmp_path / "docs" / "Living.md") == ["Missing.md", "../src/gone.py"]
    assert _broken(archive / "Old.md") == ["Gone.md#x"]


def test_the_archive_holds_the_finished_plans_and_reports():
    docs = ROOT / "docs"
    assert not list(docs.glob("Release-[1-6]*.md")) and not list(docs.glob("Planung-[1-6]*.md"))
    assert (docs / "archiv" / "Release-6.9.md").is_file() and (docs / "archiv" / "Planung-3.6.md").is_file()
    index = (docs / "README.md").read_text(encoding="utf-8")
    living = {path.name for path in docs.glob("*.md")} - {"README.md"}
    assert {name for name in living if f"]({name})" not in index} <= {"Planung-7.1.md", "Planung-7.2.md"}
