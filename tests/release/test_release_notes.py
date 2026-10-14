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


def test_a_version_without_changelog_section_fails(tmp_path):
    (tmp_path / "CHANGELOG.md").write_text("# Änderungen\n\n## 1.0.0 – erste\n", encoding="utf-8")
    with pytest.raises(ValueError, match="keinen Abschnitt für 1.0.1"):
        release_notes.release_notes("v1.0.1", tmp_path)
    assert release_notes.release_notes("v1.0.0", tmp_path) == "## 1.0.0 – erste\n"


def test_the_script_writes_utf_8():
    output = subprocess.run([sys.executable, str(SCRIPT), "v3.1.0"], capture_output=True, check=True).stdout
    assert output.decode("utf-8").startswith("## 3.1.0 – beta: Mehrere Postfächer")
