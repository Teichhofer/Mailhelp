"""Release notes come from the changelog section of the tagged version (release.yml)."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github" / "scripts" / "release_notes.py"
spec = importlib.util.spec_from_file_location("release_notes", SCRIPT)
release_notes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_notes)


def test_the_current_version_has_release_notes():
    """Regression: every release so far published the text of release 1.0."""
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    notes = release_notes.release_notes(f"v{version}")
    assert notes.startswith(f"## {version} ")
    assert "\n## " not in notes


def test_notes_link_the_tagged_documents_and_the_release_guide():
    notes = release_notes.release_notes("v3.1.0")
    blob = "https://github.com/Teichhofer/Mailhelp/blob/v3.1.0/docs/"
    assert notes.startswith("## 3.1.0 – beta: Mehrere Postfächer") and "## 3.0.5" not in notes
    assert f"]({blob}Planung-3.1.md)" in notes and "](docs/" not in notes
    assert notes.endswith(f"Einrichtung, Upgrade und Rückkehr: [docs/Release-3.1.md]({blob}Release-3.1.md)\n")
    # Versions without a release guide have only their changelog section.
    assert "Einrichtung, Upgrade und Rückkehr: [docs/Release-2.3" not in release_notes.release_notes("v2.3.1")


def test_regression_archived_documents_are_linked_where_the_tag_holds_them(tmp_path):
    """7.0.14 moved plans and reports to docs/archiv/; a 3.1 tag still has them in docs/."""
    (tmp_path / "docs" / "archiv").mkdir(parents=True)
    (tmp_path / "docs" / "archiv" / "Release-3.1.md").write_text("old", encoding="utf-8")
    (tmp_path / "docs" / "Release-7.0.md").write_text("new", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(
        "# Änderungen\n\n## 7.0.14 – neu\n\nSiehe [docs/archiv/Planung-6.9.md](docs/archiv/Planung-6.9.md).\n\n"
        "## 3.1.0 – alt\n\nPlanung: [docs/archiv/Planung-3.1.md](docs/archiv/Planung-3.1.md)\n", encoding="utf-8")
    old = release_notes.release_notes("v3.1.0", tmp_path)
    blob = "https://github.com/Teichhofer/Mailhelp/blob/v3.1.0/docs/"
    assert old == (f"## 3.1.0 – alt\n\nPlanung: [docs/Planung-3.1.md]({blob}Planung-3.1.md)\n"
                   f"\nEinrichtung, Upgrade und Rückkehr: [docs/Release-3.1.md]({blob}Release-3.1.md)\n")
    new = release_notes.release_notes("v7.0.14", tmp_path)
    blob = "https://github.com/Teichhofer/Mailhelp/blob/v7.0.14/docs/"
    assert new == (f"## 7.0.14 – neu\n\nSiehe [docs/archiv/Planung-6.9.md]({blob}archiv/Planung-6.9.md).\n"
                   f"\nEinrichtung, Upgrade und Rückkehr: [docs/Release-7.0.md]({blob}Release-7.0.md)\n")


def test_a_version_without_changelog_section_fails(tmp_path):
    (tmp_path / "CHANGELOG.md").write_text("# Änderungen\n\n## 1.0.0 – erste\n", encoding="utf-8")
    with pytest.raises(ValueError, match="keinen Abschnitt für 1.0.1"):
        release_notes.release_notes("v1.0.1", tmp_path)
    assert release_notes.release_notes("v1.0.0", tmp_path) == "## 1.0.0 – erste\n"


@pytest.mark.process
def test_the_script_writes_utf_8():
    output = subprocess.run([sys.executable, str(SCRIPT), "v3.1.0"], capture_output=True, check=True).stdout
    assert output.decode("utf-8").startswith("## 3.1.0 – beta: Mehrere Postfächer")
