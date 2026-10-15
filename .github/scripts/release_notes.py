"""Release notes of one version: its CHANGELOG.md section and, if present, the release guide.

Usage: python .github/scripts/release_notes.py v3.1.0 > release-notes.md
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPOSITORY = "https://github.com/Teichhofer/Mailhelp"


def release_notes(tag: str, root: Path = ROOT) -> str:
    """The changelog section of *tag*; a missing section is an error, never empty notes."""
    version = tag.removeprefix("v")
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(rf"^## {re.escape(version)} .*?(?=^## |\Z)", changelog, re.M | re.S)
    if match is None:
        raise ValueError(f"CHANGELOG.md enthält keinen Abschnitt für {version}")
    # Relative links would point nowhere on the release page; they refer to the tagged files.
    notes = match.group(0).rstrip().replace("](docs/", f"]({REPOSITORY}/blob/{tag}/docs/") + "\n"
    guide = Path("docs") / f"Release-{'.'.join(version.split('.')[:2])}.md"
    if (root / guide).is_file():
        path = guide.as_posix()
        notes += f"\nEinrichtung, Upgrade und Rückkehr: [{path}]({REPOSITORY}/blob/{tag}/{path})\n"
    return notes


if __name__ == "__main__":
    # UTF-8 regardless of the console encoding (umlauts on Windows).
    sys.stdout.buffer.write(release_notes(sys.argv[1]).encode("utf-8"))
