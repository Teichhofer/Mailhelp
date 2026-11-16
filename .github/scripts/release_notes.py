"""Release notes of one version: its CHANGELOG.md section and, if present, the release guide.

Usage: python .github/scripts/release_notes.py v3.1.0 > release-notes.md
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPOSITORY = "https://github.com/Teichhofer/Mailhelp"
# 7.0.14 moved finished plans and reports to docs/archiv/; older tags still hold them in docs/.
ARCHIVE_SINCE = (7, 0, 14)


def _number(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", version)[:3])


def release_notes(tag: str, root: Path = ROOT) -> str:
    """The changelog section of *tag*; a missing section is an error, never empty notes."""
    version = tag.removeprefix("v")
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(rf"^## {re.escape(version)} .*?(?=^## |\Z)", changelog, re.M | re.S)
    if match is None:
        raise ValueError(f"CHANGELOG.md enthält keinen Abschnitt für {version}")
    notes = match.group(0).rstrip()
    archived = _number(version) >= ARCHIVE_SINCE
    if not archived:
        # Links name the files as they lie in the tagged tree.
        notes = notes.replace("docs/archiv/", "docs/")
    # Relative links would point nowhere on the release page; they refer to the tagged files.
    notes = notes.replace("](docs/", f"]({REPOSITORY}/blob/{tag}/docs/") + "\n"
    name = f"Release-{'.'.join(version.split('.')[:2])}.md"
    for folder in ("docs", "docs/archiv"):
        if (root / folder / name).is_file():
            path = f"{folder if archived else 'docs'}/{name}"
            notes += f"\nEinrichtung, Upgrade und Rückkehr: [{path}]({REPOSITORY}/blob/{tag}/{path})\n"
            break
    return notes


if __name__ == "__main__":
    # UTF-8 regardless of the console encoding (umlauts on Windows).
    sys.stdout.buffer.write(release_notes(sys.argv[1]).encode("utf-8"))
