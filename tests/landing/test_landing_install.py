"""7.9.7: the landing page installation (devtools/landing_install.py) against a temporary tree.

System commands are recorded, never executed; the health check and the Mailhelp container are simulated.
"""
import datetime
import hashlib
import io
import json
import os
import runpy
import tarfile
import urllib.error
from pathlib import Path

import pytest

from devtools import landing_install
from devtools.landing_install import InstallError, System, install, main

STARTED = "2026-11-19T14:19:08Z 0"


def release_archive(tmp_path, release_id="20261119-test", extra=None):
    """A minimal synthetic release with the files the installation uses."""
    files = {"lead_service.py": b"print('form')\n", "public/index.html": b"<h1>Hallo</h1>\n",
             "ops/inboxstride.service": b"[Service]\n", "ops/nginx-http.conf": b"server { listen 80; }\n",
             "ops/nginx-https.conf": b"server { listen 443 ssl; }\n"}
    archive = tmp_path / "release.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        for info in extra or []:
            tar.addfile(info)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "release_id": release_id, "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "file_digests": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}))
    return archive, manifest


def switch(link, current):
    """os.replace where the platform allows it; Windows cannot replace a directory link in place."""
    if os.name == "nt" and current.is_symlink():
        current.unlink()
    os.replace(link, current)


class Host:
    """Records commands; ``states`` are the successive answers of docker inspect."""

    def __init__(self, tmp_path, *, ready_after=0, states=(STARTED, STARTED), user=True):
        self.commands, self.said, self.slept = [], [], []
        self.states, self.ready_after, self.user = list(states), ready_after, user
        self.system = System(root=tmp_path / "opt/inboxstride", etc=tmp_path / "etc", sbin=tmp_path / "sbin",
                             run=self.commands.append, output=self.output, user_exists=lambda name: self.user,
                             healthy=self.healthy, sleep=self.slept.append,
                             now=lambda: datetime.datetime(2026, 11, 19, 15, 0, tzinfo=datetime.UTC),
                             say=self.said.append, replace=switch)

    def output(self, command):
        self.commands.append(command)
        return self.states.pop(0) if command[:2] == ["docker", "inspect"] else "ActiveState=active"

    def healthy(self):
        self.ready_after -= 1
        return self.ready_after < 0


def test_a_release_is_installed_switched_and_published(tmp_path):
    archive, manifest = release_archive(tmp_path)
    host = Host(tmp_path, ready_after=2, user=False)
    old = host.system.root / "releases/old"
    old.mkdir(parents=True)
    (host.system.root / "current").symlink_to(old)
    for site in host.system.site_files[:2]:
        site.parent.mkdir(parents=True, exist_ok=True)
        site.write_text("alt")
    assert install(archive, manifest, host.system) == "20261119-test"
    release = host.system.root / "releases/20261119-test"
    assert (host.system.root / "current").resolve() == release.resolve()
    assert (release / "public/index.html").read_bytes() == b"<h1>Hallo</h1>\n"
    backup = host.system.root / "backups/pre-20261119T150000Z"
    record = json.loads((backup / "deployment.json").read_text())
    assert record["previous_release"] == str(old.resolve()) and record["mailhelp_before"] == STARTED
    assert (backup / "inboxstride-http").read_text() == "alt"
    assert host.system.site_files[2].read_bytes() == b"[Service]\n"
    assert host.system.site_files[1].read_bytes() == b"server { listen 443 ssl; }\n"
    enabled = host.system.etc / "nginx/sites-enabled/inboxstride-https"
    assert enabled.resolve() == host.system.site_files[1].resolve()
    assert "renew --cert-name inboxstride.de" in (host.system.sbin / "renew-inboxstride").read_text()
    assert (host.system.etc / "cron.d/inboxstride-cert-renew").read_text().startswith("27 */6 * * * root")
    assert host.commands[1][0] == "useradd" and host.slept == [1, 1]
    certbot = next(command for command in host.commands if "certonly" in command)
    assert "--keep-until-expiring" in certbot and landing_install.CERTBOT in certbot
    assert host.said[:3] == ["FORM_SERVICE_READY", "HTTP_CHALLENGE_READY", "HTTPS_INSTALLED 20261119-test"]
    assert host.said[-1] == "ActiveState=active"


def test_a_repeated_installation_keeps_the_release_user_and_site_links(tmp_path):
    archive, manifest = release_archive(tmp_path)
    install(archive, manifest, Host(tmp_path).system)
    host = Host(tmp_path)
    host.system.now = lambda: datetime.datetime(2026, 11, 19, 16, 0, tzinfo=datetime.UTC)
    assert install(archive, manifest, host.system) == "20261119-test"
    assert not any(command[0] == "useradd" for command in host.commands)
    record = json.loads((host.system.root / "backups/pre-20261119T160000Z/deployment.json").read_text())
    assert record["previous_release"].endswith("20261119-test")


@pytest.mark.parametrize("change", ["archive", "release_id", "file", "symlink", "escape"])
def test_unsafe_or_changed_releases_are_refused_before_anything_is_switched(tmp_path, change):
    extra = []
    if change == "symlink":
        link = tarfile.TarInfo("public/link")
        link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
        extra = [link]
    elif change == "escape":
        extra = [tarfile.TarInfo("../outside.txt")]
    archive, manifest = release_archive(tmp_path, "../ausbruch" if change == "release_id" else "20261119-test",
                                        extra)
    data = json.loads(manifest.read_text())
    if change == "archive":
        data["archive_sha256"] = "0" * 64
    elif change == "file":
        data["file_digests"]["public/index.html"] = "0" * 64
    manifest.write_text(json.dumps(data))
    host = Host(tmp_path)
    with pytest.raises(InstallError):
        install(archive, manifest, host.system)
    assert not (host.system.root / "current").exists() and host.said == []


def test_a_form_service_that_never_answers_stops_before_nginx(tmp_path):
    archive, manifest = release_archive(tmp_path)
    host = Host(tmp_path, ready_after=landing_install.HEALTH_ATTEMPTS)
    with pytest.raises(InstallError, match="nicht bereit"):
        install(archive, manifest, host.system)
    assert len(host.slept) == landing_install.HEALTH_ATTEMPTS
    assert not any(command[0] == "nginx" for command in host.commands)


def test_a_changed_mailhelp_container_fails_the_installation(tmp_path):
    archive, manifest = release_archive(tmp_path)
    host = Host(tmp_path, states=(STARTED, "2026-11-19T15:00:01Z 1"))
    with pytest.raises(InstallError, match="Mailhelp-Container"):
        install(archive, manifest, host.system)


def test_the_default_system_calls_the_real_commands(monkeypatch):
    calls = []
    monkeypatch.setattr(landing_install.subprocess, "run",
                        lambda command, **options: calls.append((command, options)) or type("R", (), {
                            "returncode": 0 if command[-1] == "inboxstride" else 1})())
    monkeypatch.setattr(landing_install.subprocess, "check_output", lambda command, **options: " aktiv \n")
    system = System()
    system.run(["nginx", "-t"])
    assert calls[0] == (["nginx", "-t"], {"check": True})
    assert system.output(["systemctl", "show"]) == "aktiv"
    assert system.user_exists("inboxstride") and not system.user_exists("fremd")
    assert system.now().tzinfo is datetime.UTC and system.root == Path("/opt/inboxstride")
    assert system.replace is os.replace  # the atomic switch on the server


def test_the_health_check_reads_the_local_form_service(monkeypatch, capsys):
    class Answer:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    seen = []
    monkeypatch.setattr(landing_install.urllib.request, "urlopen",
                        lambda request, timeout: seen.append((request.full_url, timeout)) or Answer())
    assert System().healthy() and seen == [(landing_install.HEALTH_URL, 2)]

    def refused(request, timeout):
        raise urllib.error.URLError("refused")
    monkeypatch.setattr(landing_install.urllib.request, "urlopen", refused)
    assert not System().healthy()
    System().say("BEREIT")
    assert capsys.readouterr().out == "BEREIT\n"


def test_main_takes_archive_and_manifest(tmp_path, monkeypatch):
    archive, manifest = release_archive(tmp_path)
    host = Host(tmp_path)
    assert main([str(archive), str(manifest)], host.system) == 0
    monkeypatch.setattr("sys.argv", ["landing_install", str(archive), str(manifest)])
    monkeypatch.setattr(landing_install, "System", lambda: host.system)
    host.states = [STARTED, STARTED]
    host.system.now = lambda: datetime.datetime(2026, 11, 19, 15, 1, tzinfo=datetime.UTC)  # a new backup name
    assert main() == 0
    # As a script it reads the manifest first: a missing file stops it before anything is written.
    monkeypatch.setattr("sys.argv", ["landing_install", str(archive), str(tmp_path / "fehlt.json")])
    with pytest.raises(FileNotFoundError):
        runpy.run_path(landing_install.__file__, run_name="__main__")
