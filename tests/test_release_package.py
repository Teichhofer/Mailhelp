"""Verify real distribution contents and configuration away from a checkout."""
import os
from pathlib import Path
import shutil
import tarfile
import tomllib
import zipfile

import pytest
import mailhelp
from mailhelp.config import load_all
from mailhelp.decisions import load_relevance_prompts

ROOT = Path(__file__).parents[1]


def test_package_resources_and_fresh_configuration(tmp_path):
    package = Path(mailhelp.__file__).parent
    assert (package / "assets/logo.png").read_bytes().startswith(b"\x89PNG")
    assert (package / "web/static/icon-192.png").read_bytes().startswith(b"\x89PNG")
    for name in ("topics.yaml", "irrelevant_topics.yaml", "decisions_prompts.yaml"):
        assert (package / "defaults" / name).is_file()
    for source, target in (("config.example.yaml", "config.yaml"), ("prompts.yaml", "prompts.yaml")):
        shutil.copyfile(ROOT / source, tmp_path / target)
    keys = ("IMAP_USERNAME IMAP_PASSWORD OPENROUTER_API_KEY TELEGRAM_BOT_TOKEN "
            "TODOIST_TOKEN TODOIST_CLIENT_ID TODOIST_CLIENT_SECRET GOOGLE_OAUTH_CLIENT_ID "
            "GOOGLE_OAUTH_CLIENT_SECRET GOOGLE_OAUTH_REFRESH_TOKEN").split()
    settings, _, topics, _, prompts, fingerprint = load_all(tmp_path, {key: "synthetic" for key in keys})
    assert topics and prompts.prompts and len(fingerprint) == 64
    assert load_relevance_prompts(tmp_path).model
    assert settings.targets.google_calendar
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    assert mailhelp.__version__ == version
    parts = mailhelp.__version__.split(".")
    assert len(parts) == 3 and all(p.isdigit() for p in parts)
    agents_rules = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "Jeder Commit in `main` erhöht die Versionsnummer" in agents_rules
    if os.environ.get("MAILHELP_INSTALLED_WHEEL"):
        assert ROOT / "src" not in package.parents


def test_built_artifacts_exclude_private_runtime_files():
    dist = ROOT / "dist"
    wheels, sources = list(dist.glob("*.whl")), list(dist.glob("*.tar.gz"))
    if not wheels or not sources:
        if os.environ.get("MAILHELP_INSTALLED_WHEEL"):
            pytest.fail("Release artifacts must exist in the package smoke job")
        pytest.skip("Artifact build is verified in package-smoke on both target platforms")
    with zipfile.ZipFile(wheels[-1]) as archive:
        names = archive.namelist()
        assert "mailhelp/assets/logo.png" in names
        assert {"mailhelp/web/static/app.js", "mailhelp/web/static/sw.js",
                "mailhelp/web/static/manifest.webmanifest"} <= set(names)
        assert "mailhelp/defaults/decisions_prompts.yaml" in names
        assert not any(name.endswith(".env") for name in names)
    with tarfile.open(sources[-1]) as archive:
        names = {name.split("/", 1)[-1] for name in archive.getnames()}
        assert {"config.example.yaml", ".env.example", "prompts.yaml", "requirements.lock",
                "docs/Release-1.0.md", "docs/Release-1.1.md", "docs/Release-1.2.md",
                "src/mailhelp/assets/logo.png"} <= names
        assert "config.yaml" not in names and ".env" not in names
        assert not any(name.startswith(("data/", "logs/", "quality-reports/")) for name in names)
