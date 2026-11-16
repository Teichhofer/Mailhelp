"""7.1 (D1): the demo mode – a web instance on prepared example data, chosen only by ``--demo``.

The mode is fixed for the lifetime of the process. It never connects a mailbox, Telegram, a model or
a real calendar or task list, and it never opens a production directory: the runtime directory must
be empty on the first start and then carries its own marker file.
"""
from __future__ import annotations

import json
import os
import secrets
from collections.abc import Callable, Mapping
from pathlib import Path
from threading import Event
from typing import Any

from ..config import WebSettings
from ..logging import JsonlLogger
from ..persistence.storage import JsonStore, atomic_replace
from ..web.app import WebApp
from ..web.demo_site import DemoSite
from ..web.server import WebServer
from .bootstrap import console

MARKER = "mailhelp-demo.json"
MARKER_CONTENT = {"kind": "mailhelp-demo", "schema_version": 1}
SECRET = "demo-secret"


class DemoDirectoryError(ValueError):
    """The runtime directory belongs to a normal installation or is not a valid demo directory."""


def is_demo_directory(directory: Path) -> bool:
    return (directory / MARKER).is_file()


def prepare_directory(directory: Path) -> None:
    """Accept an empty directory (and mark it) or an existing demo directory; refuse anything else."""
    directory.mkdir(parents=True, exist_ok=True)
    marker = directory / MARKER
    if marker.exists():
        try:
            content = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise DemoDirectoryError(f"Die Demo-Markierung {marker} ist nicht lesbar.") from exc
        if content != MARKER_CONTENT:
            raise DemoDirectoryError(f"Die Demo-Markierung {marker} gehört zu keiner bekannten Demo-Version.")
        return
    if any(directory.iterdir()):
        raise DemoDirectoryError(
            f"{directory} enthält bereits Dateien, etwa eine normale Mailhelp-Installation. "
            "Für die Demo ein eigenes, leeres Laufzeitverzeichnis angeben.")
    atomic_replace(marker, json.dumps(MARKER_CONTENT) + "\n")


def demo_secret(directory: Path) -> str:
    """The web secret of this demo directory: created once, readable only by the owner where possible."""
    path = directory / SECRET
    if path.exists():
        secret = path.read_text(encoding="utf-8").strip()
        if len(secret) >= 32:
            return secret
    secret = secrets.token_urlsafe(48)
    atomic_replace(path, secret + "\n")
    os.chmod(path, 0o600)
    return secret


def demo_settings(environ: Mapping[str, str]) -> WebSettings:
    port = int(environ.get("MAILHELP_DEMO_PORT", "8765"))
    host = environ.get("MAILHELP_DEMO_HOST", "127.0.0.1")
    extra = [name for name in environ.get("MAILHELP_DEMO_ALLOWED_HOSTS", "").split(",") if name]
    return WebSettings(enabled=True, host=host, port=port, lan_access=False,
                       allowed_hosts=[f"localhost:{port}", f"127.0.0.1:{port}", *extra])


def create_demo(store: JsonStore, settings: WebSettings, secret: str, logger: Any) -> WebServer:
    app = WebApp(settings.allowed_hosts)
    DemoSite(app, store, secret, logger)
    return WebServer(settings.host, settings.port, app, logger)


def run_demo(directory: Path, shutdown: Any, *, emit: Callable[[str], None] = console,
             environ: Mapping[str, str] = os.environ) -> int:
    try:
        prepare_directory(directory)
    except DemoDirectoryError as exc:
        emit(f"Demo nicht gestartet: {exc}")
        return 2
    settings = demo_settings(environ)
    stopped = Event()
    shutdown.stop = stopped.set
    with JsonStore(directory / "data" / "demo") as store:
        logger = JsonlLogger(directory / "logs", console_enabled=False)
        server = create_demo(store, settings, demo_secret(directory), logger)
        server.start()
        try:
            emit(f"Mailhelp-Demo: http://localhost:{settings.port}/anmelden")
            stopped.wait()
        finally:
            server.stop()
    return 0
