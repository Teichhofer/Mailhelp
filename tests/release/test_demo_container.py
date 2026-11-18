"""7.1 (D7): the demo container is separate from production and the wheel carries a valid dataset."""
from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from pathlib import Path

import yaml

from mailhelp import __version__

ROOT = Path(__file__).parents[2]


def _compose(name: str) -> dict:
    return yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))


def test_the_demo_service_starts_the_demo_in_an_own_volume_without_internet():
    compose = _compose("compose.demo.yaml")
    assert list(compose["services"]) == ["mailhelp-demo"]
    service = compose["services"]["mailhelp-demo"]
    assert service["command"] == ["--demo", "--config-directory", "/config"]
    # Own named volume only: no bind mount of production files, data or logs.
    assert service["volumes"] == ["demo-daten:/config"]
    assert "env_file" not in service and "ports" not in service
    environment = service["environment"]
    assert not [name for name in environment if not name.startswith("MAILHELP_DEMO_")]
    assert environment["MAILHELP_DEMO_HOST"] == "0.0.0.0" and environment["MAILHELP_DEMO_TRUST_PROXY"] == "1"
    assert service["networks"] == ["mailhelp-demo"]
    assert compose["networks"]["mailhelp-demo"]["internal"] is True


def test_the_demo_shares_nothing_with_the_production_service():
    production = _compose("compose.yaml")["services"]["mailhelp"]
    demo = _compose("compose.demo.yaml")
    assert "mailhelp" not in demo["services"]
    sources = {str(volume).split(":")[0] if isinstance(volume, str) else volume["source"]
               for volume in production["volumes"]}
    assert not sources & {str(volume).split(":")[0] for volume in demo["services"]["mailhelp-demo"]["volumes"]}
    assert "demo" not in str(production.get("command", ""))


def test_the_installed_wheel_carries_the_verified_demo_dataset(tmp_path):
    wheel = ROOT / "dist" / f"mailhelp-{__version__}-py3-none-any.whl"
    assert wheel.is_file(), "Build artifacts for the current version must exist"
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(tmp_path / "wheel")
    script = ("import mailhelp; from mailhelp.runtime import demo_dataset as d; from mailhelp.i18n import Locale; "
              "print(mailhelp.__file__); print(','.join(str(len(d.verify(d.packaged(locale)).mails)) for locale in Locale))")
    # A separately loaded copy is an isolation check; it must not feed the coverage of this run.
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(("COV_CORE_", "COVERAGE_"))}
    result = subprocess.run([sys.executable, "-c", script], cwd=tmp_path, capture_output=True, text=True,
                            check=True, env={**environment, "PYTHONPATH": str(tmp_path / "wheel")})
    location, count = result.stdout.strip().splitlines()
    assert Path(location).resolve().is_relative_to((tmp_path / "wheel").resolve())
    assert count == "30,30"
