"""Install a landing page release on the Inboxstride VPS (until 7.9.6: landing/ops/install_server.py).

Run as root with the release archive and its manifest::

    python3 -m devtools.landing_install inboxstride-<release>.tar.gz manifest.json

Steps as before: verify the archive, back up nginx/systemd files, unpack into a new release
directory, verify every file digest, switch ``current`` atomically, restart the form service and
wait for its health check, enable HTTP for the ACME challenge, obtain or keep the certificate,
enable HTTPS and install the renewal job. The Mailhelp container must stay untouched. Paths and
system commands are parameters so that tests run the installation against a temporary tree.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CERTBOT = "certbot/certbot:v5.10.0"
ACME_EMAIL = "inboxstride@email.de"
MAILHELP_CONTAINER = "mailhelp-update-mailhelp-1"
HEALTH_URL = "http://127.0.0.1:8877/health"
HEALTH_ATTEMPTS = 20
RENEW_SCRIPT = f"""#!/bin/sh
set -eu
PATH=/usr/sbin:/usr/bin:/sbin:/bin
docker run --rm -v /etc/letsencrypt:/etc/letsencrypt -v /var/www/mailhelp-acme:/webroot {CERTBOT} \
renew --cert-name inboxstride.de --quiet
nginx -t
systemctl reload nginx
"""


class InstallError(RuntimeError):
    """The installation stopped; files written so far are listed in the backup's deployment.json."""


def _run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def _output(command: list[str]) -> str:
    return subprocess.check_output(command, text=True).strip()


def _user_exists(name: str) -> bool:
    return subprocess.run(["id", "-u", name], capture_output=True).returncode == 0


def _healthy() -> bool:
    request = urllib.request.Request(HEALTH_URL, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            return bool(response.status == 200)
    except OSError:
        return False


@dataclass
class System:
    """Where the installation writes and how it calls the system; the defaults are the real VPS."""

    root: Path = Path("/opt/inboxstride")
    etc: Path = Path("/etc")
    sbin: Path = Path("/usr/local/sbin")
    run: Callable[[list[str]], None] = _run
    output: Callable[[list[str]], str] = _output
    user_exists: Callable[[str], bool] = _user_exists
    healthy: Callable[[], bool] = _healthy
    sleep: Callable[[float], None] = time.sleep
    # Atomic on Linux; Windows cannot replace a directory link, so tests there pass their own.
    replace: Callable[[Path, Path], None] = os.replace
    now: Callable[[], datetime.datetime] = field(default=lambda: datetime.datetime.now(datetime.UTC))
    say: Callable[[str], None] = field(default=lambda text: print(text, flush=True))

    @property
    def site_files(self) -> tuple[Path, Path, Path]:
        """nginx HTTP and HTTPS sites and the systemd unit, in this order."""
        return (self.etc / "nginx/sites-available/inboxstride-http",
                self.etc / "nginx/sites-available/inboxstride-https",
                self.etc / "systemd/system/inboxstride.service")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _mailhelp_state(system: System) -> str:
    return system.output(["docker", "inspect", "--format", "{{.State.StartedAt}} {{.RestartCount}}",
                          MAILHELP_CONTAINER])


def _prepare(archive: Path, manifest: dict[str, Any], system: System) -> tuple[Path, str]:
    """Check the archive, create the release path and back up the files the installation replaces."""
    if _sha256(archive) != manifest["archive_sha256"]:
        raise InstallError("Archiv passt nicht zum Manifest")
    releases = system.root / "releases"
    releases.mkdir(mode=0o755, parents=True, exist_ok=True)
    release = releases / manifest["release_id"]
    if release.resolve().parent != releases.resolve():
        raise InstallError("Ungültige Release-ID")
    backup = system.root / "backups" / ("pre-" + system.now().strftime("%Y%m%dT%H%M%SZ"))
    backup.mkdir(mode=0o700, parents=True)
    current = system.root / "current"
    before = _mailhelp_state(system)
    for path in system.site_files:
        if path.exists():
            shutil.copy2(path, backup / path.name)
    (backup / "deployment.json").write_text(json.dumps({
        "previous_release": str(current.resolve()) if current.exists() else None,
        "target_release": manifest["release_id"], "archive_sha256": manifest["archive_sha256"],
        "mailhelp_before": before}, indent=2))
    return release, before


def _unpack(archive: Path, manifest: dict[str, Any], release: Path) -> None:
    """Only plain files inside the release; an existing release is verified, not overwritten."""
    if not release.exists():
        with tarfile.open(archive) as tar:
            for item in tar.getmembers():
                if not item.isfile() or not (release / item.name).resolve().is_relative_to(release.resolve()):
                    raise InstallError(f"Unzulässiger Archiveintrag: {item.name}")
            release.mkdir(mode=0o755)
            tar.extractall(release, filter="data")
    for name, digest in manifest["file_digests"].items():
        if _sha256(release / name) != digest:
            raise InstallError(f"Prüfsumme weicht ab: {name}")
    for directory in [release, *[path for path in release.rglob("*") if path.is_dir()]]:
        directory.chmod(0o755)
    for path in release.rglob("*"):
        if path.is_file():
            path.chmod(0o644)


def _activate(release: Path, system: System) -> None:
    """Switch ``current`` atomically and start the form service from the new release."""
    if not system.user_exists("inboxstride"):
        system.run(["useradd", "--system", "--home-dir", "/var/lib/inboxstride", "--no-create-home",
                    "--shell", "/usr/sbin/nologin", "inboxstride"])
    link = system.root / (".current-" + uuid.uuid4().hex)
    link.symlink_to(release)
    system.replace(link, system.root / "current")
    unit = system.site_files[2]
    unit.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(release / "ops/inboxstride.service", unit)
    for command in (["systemctl", "daemon-reload"], ["systemctl", "enable", "inboxstride"],
                    ["systemctl", "restart", "inboxstride"]):
        system.run(command)
    for _attempt in range(HEALTH_ATTEMPTS):
        if system.healthy():
            break
        system.sleep(1)
    else:
        raise InstallError("Formulardienst wurde nicht bereit")
    system.say("FORM_SERVICE_READY")


def _enable_site(source: Path, available: Path, system: System) -> None:
    available.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, available)
    enabled = system.etc / "nginx/sites-enabled" / available.name
    enabled.parent.mkdir(parents=True, exist_ok=True)
    if not enabled.exists():
        enabled.symlink_to(available)
    system.run(["nginx", "-t"])
    system.run(["systemctl", "reload", "nginx"])


def _publish(release: Path, system: System) -> None:
    """HTTP for the ACME challenge, the certificate, then HTTPS and its renewal job."""
    http, https, _unit = system.site_files
    _enable_site(release / "ops/nginx-http.conf", http, system)
    system.say("HTTP_CHALLENGE_READY")
    system.run(["docker", "run", "--rm", "-v", "/etc/letsencrypt:/etc/letsencrypt", "-v",
                "/var/www/mailhelp-acme:/webroot", CERTBOT, "certonly", "--webroot", "-w", "/webroot",
                "--cert-name", "inboxstride.de", "-d", "inboxstride.de", "-d", "www.inboxstride.de",
                "--non-interactive", "--agree-tos", "--email", ACME_EMAIL, "--keep-until-expiring"])
    _enable_site(release / "ops/nginx-https.conf", https, system)
    renew = system.sbin / "renew-inboxstride"
    renew.parent.mkdir(parents=True, exist_ok=True)
    renew.write_text(RENEW_SCRIPT)
    renew.chmod(0o755)
    cron = system.etc / "cron.d/inboxstride-cert-renew"
    cron.parent.mkdir(parents=True, exist_ok=True)
    cron.write_text("27 */6 * * * root /usr/local/sbin/renew-inboxstride\n")


def install(archive: Path, manifest_path: Path, system: System) -> str:
    """Install the release; returns its id. Raises InstallError if the Mailhelp container changed."""
    manifest = json.loads(manifest_path.read_text())
    release, before = _prepare(archive, manifest, system)
    _unpack(archive, manifest, release)
    _activate(release, system)
    _publish(release, system)
    if _mailhelp_state(system) != before:
        raise InstallError("Mailhelp-Container hat sich während der Installation verändert")
    system.say(f"HTTPS_INSTALLED {manifest['release_id']}")
    system.say("MAILHELP_CONTAINER_UNCHANGED True")
    system.say(system.output(["systemctl", "show", "inboxstride", "-p", "MemoryCurrent", "-p", "CPUUsageNSec",
                              "-p", "NRestarts", "-p", "ActiveState"]))
    return str(manifest["release_id"])


def main(argv: Sequence[str] | None = None, system: System | None = None) -> int:
    archive, manifest = (sys.argv[1:] if argv is None else argv)
    install(Path(archive), Path(manifest), system or System())
    return 0


if __name__ == "__main__":
    sys.exit(main())
