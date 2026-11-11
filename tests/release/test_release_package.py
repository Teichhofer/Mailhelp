"""Verify real distribution contents and configuration away from a checkout."""
import os
import shutil
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

import pytest

import mailhelp
from mailhelp.config import load_all
from mailhelp.llm.decisions import load_relevance_prompts

ROOT = Path(__file__).parents[2]


def test_package_resources_and_fresh_configuration(tmp_path):
    package = Path(mailhelp.__file__).parent
    assert (package / "assets/logo.png").read_bytes().startswith(b"\x89PNG")
    assert (package / "web/static/icon-192.png").read_bytes().startswith(b"\x89PNG")
    for name in ("topics.yaml", "irrelevant_topics.yaml", "decisions_prompts.yaml"):
        assert (package / "defaults" / name).is_file()
    for name in ("initial-config.yaml", "prompts.yaml", "google-oauth-playground.md"):
        assert (package / "defaults" / name).is_file()
    assert (package / "web/static/setup.js").is_file()
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
    assert "Jeder Commit in `main` und `beta` erhöht die Versionsnummer" in agents_rules
    if os.environ.get("MAILHELP_INSTALLED_WHEEL"):
        assert ROOT / "src" not in package.parents


def test_built_artifacts_exclude_private_runtime_files():
    dist = ROOT / "dist"
    wheels, sources = list(dist.glob("*.whl")), list(dist.glob("*.tar.gz"))
    if not wheels or not sources:
        if os.environ.get("MAILHELP_INSTALLED_WHEEL"):
            pytest.fail("Release artifacts must exist in the package smoke job")
        pytest.skip("Artifact build is verified in package-smoke on both target platforms")
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    wheel = dist / f"mailhelp-{version}-py3-none-any.whl"
    source = dist / f"mailhelp-{version}.tar.gz"
    assert wheel.is_file() and source.is_file(), "Build artifacts for the current version must exist"
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        for module in ("web/help_window.py", "helpdocs/sections.json", "helpdocs/manifest.json", "helpdocs/__init__.py",
                       "rule_learning/models.py", "rule_learning/mining.py", "rule_learning/service.py",
                       "rule_learning/validation.py", "web/rule_learning_site.py",
                       "domain/event_series.py", "review/series.py", "review/series_offers.py", "web/series_site.py",
                       "telegram/series.py", "proposals/revision_protection.py", "defaults/prompts.yaml",
                       "proposals/event_defaults.py", "proposals/proposal_matching.py", "proposals/proposal_merge.py", "proposals/proposal_reconciliation.py",
                       "domain/proposal_sources.py", "domain/reconciliation.py", "web/reconciliation_site.py",
                       "mailbox/connection_activation.py", "mailbox/connection_runtime.py", "mailbox/mailbox_activation.py",
                       "mailbox/mailbox_runtime.py", "web/mailbox_add_site.py",
                       "mailbox/mailbox_settings.py", "mailbox/mailbox_briefing.py", "proposals/target_profiles.py", "proposals/profile_binding.py",
                       "proposals/profile_usage.py", "runtime/google_login.py", "web/mailbox_site.py", "notifications/notification_runtime.py",
                       "llm/fingerprints.py", "runtime/composition.py", "processing/orchestrator.py",
                       "web/pages.py", "web/review_pages.py", "web/settings_pages.py",
                       "web/status_pages.py", "web/site.py", "runtime/metrics.py", "mailbox/imap.py", "mailbox/mailbox_run.py",
                       "runtime/credentials.py", "web/credential_pages.py", "web/settings_site.py",
                       "notifications/briefing_scheduler.py", "notifications/briefing_aggregate.py",
                       "notifications/briefing_template.py", "notifications/briefing_drafts.py",
                       "notifications/briefing_identity.py",
                       "mailbox/draft_writer.py", "web/static/app.css", "web/static/sw.js"):
            assert archive.read("mailhelp/" + module) == (ROOT / "src/mailhelp" / module).read_bytes()
        assert "mailhelp/assets/logo.png" in names
        assert {"mailhelp/web/static/app.js", "mailhelp/web/static/sw.js",
                "mailhelp/web/static/manifest.webmanifest"} <= set(names)
        assert "mailhelp/defaults/decisions_prompts.yaml" in names
        assert "mailhelp/notifications/draft_preview.py" in names
        assert {"mailhelp/mailbox/mailbox_run.py", "mailhelp/web/status_pages.py",
                "mailhelp/mailbox/iserv_activation.py", "mailhelp/mailbox/iserv_runtime.py",
                "mailhelp/external/oauth.py", "mailhelp/external/calendar.py",
                "mailhelp/external/todoist.py", "mailhelp/external/ical.py",
                "mailhelp/external/transport.py", "mailhelp/external/http_writer.py",
                "mailhelp/external/confirmed.py", "mailhelp/external/contracts.py",
                "mailhelp/telegram/answer_interpretation.py",
                "mailhelp/telegram/revision_recovery.py",
                "mailhelp/telegram/revision_successor.py",
                "mailhelp/telegram/revision_contracts.py",
                "mailhelp/notifications/webpush.py", "mailhelp/notifications/drafts.py", "mailhelp/notifications/briefing.py",
                "mailhelp/processing/attachments.py", "mailhelp/runtime/experience.py", "mailhelp/runtime/standalone.py",
                "mailhelp/web/experience.py", "mailhelp/web/filters.py"} <= set(names)
        assert not any(name.endswith(".env") for name in names)
    with tarfile.open(source) as archive:
        names = {name.split("/", 1)[-1] for name in archive.getnames()}
        assert {"config.example.yaml", ".env.example", "prompts.yaml", "requirements.lock",
                "docs/Release-1.0.md", "docs/Release-1.1.md", "docs/Release-1.2.md",
                "docs/Release-1.6.md", "docs/Architektur-1.6.md", "docs/Planung-1.6.md",
                "docs/Release-2.0.md", "docs/Planung-2.0.md", "docs/Release-3.5.md", "docs/Planung-3.5.md",
                "docs/Planung-2.4.md", "docs/Architektur-2.4.md", "docs/Release-2.4.md",
                "docs/Konzept-2.0-Redesign-und-Web-Push.md",
                "src/mailhelp/assets/logo.png"} <= names
        assert "config.yaml" not in names and ".env" not in names
        assert {"docs/Planung-4.1.md", "docs/Qualitaet-4.1.md", "requirements-mutation.lock"} <= names
        assert {"docs/Planung-4.2.md", "docs/Release-4.2.md"} <= names
        assert {"docs/Planung-4.3.md", "docs/Release-4.3.md"} <= names
        assert {"docs/Planung-4.4.md", "docs/Release-4.4.md"} <= names
        assert {"docs/Planung-4.8.md", "docs/Release-4.8.md"} <= names
        assert {"docs/Planung-4.9.md", "docs/Release-4.9.md"} <= names
        assert {"docs/Planung-5.0.md", "docs/Release-5.0.md"} <= names
        assert {"docs/Planung-5.1.md", "docs/Release-5.1.md"} <= names
        assert {"docs/Planung-5.2.md", "docs/Release-5.2.md"} <= names
        assert {"docs/Planung-5.3.md", "docs/Release-5.3.md", "docs/Pruefung-Dokumentation-5.3.md",
                "docs/Ersteinrichtung.md", "docs/Betrieb.md"} <= names
        assert {"docs/Planung-5.4.md", "docs/Release-5.4.md"} <= names
        assert not any(name.startswith(("data/", "logs/", "quality-reports/")) for name in names)


def test_the_wheel_serves_help_and_search_outside_the_checkout(tmp_path):
    """5.3: the packaged help works from an installed wheel without the repository or its docs."""
    import subprocess

    from mailhelp import __version__
    wheel = Path(__file__).resolve().parents[2] / "dist" / f"mailhelp-{__version__}-py3-none-any.whl"
    assert wheel.is_file(), "Build artifacts for the current version must exist"
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(tmp_path / "wheel")
    script = ("import mailhelp, mailhelp.helpdocs as h, mailhelp.web.settings_search as s; "
              "b = h.load(); print(mailhelp.__file__); print(len(b.sections), b.select('Abrufintervall')[0].id, "
              "len(s.search('Zeitzone')), s.search('web.port')[0].key)")
    # This separately installed package is an isolation check. Inheriting pytest-cov would
    # record a second copy whose temporary source files are gone at reporting time.
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(("COV_CORE_", "COVERAGE_"))}
    result = subprocess.run([sys.executable, "-c", script], cwd=tmp_path, capture_output=True, text=True, check=True,
                            env={**environment, "PYTHONPATH": str(tmp_path / "wheel")})
    location, summary = result.stdout.strip().splitlines()
    assert Path(location).resolve().is_relative_to((tmp_path / "wheel").resolve())
    count, first, found, file_key = summary.split()
    assert int(count) > 50 and first == "web-einstellungen/mailabruf-und-betrieb" and int(found) >= 1
    assert file_key == "web.port"
