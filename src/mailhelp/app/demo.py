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
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any, NoReturn

from ..config import WebSettings
from ..domain.proposal import Proposal
from ..external.roles import CALENDAR_SLOT, TASK_SLOT
from ..logging import JsonlLogger
from ..persistence.storage import JsonStore, atomic_replace
from ..review.inbox import CommandInbox
from ..review.views import ReviewViews
from ..runtime.demo_dataset import packaged
from ..runtime.demo_visitors import MAX_VISITORS, DemoVisitors
from ..runtime.standalone import DisabledTelegram
from ..telegram import TelegramDialogController
from ..telegram.receiver import TelegramInbox
from ..web.app import WebApp
from ..web.auth import WebAuth
from ..web.demo_site import SESSION_SECONDS, DemoSite, VisitorApp
from ..web.server import WebServer
from ..web.site import MailhelpSite
from .bootstrap import console

MARKER = "mailhelp-demo.json"
MARKER_CONTENT = {"kind": "mailhelp-demo", "schema_version": 1}
SECRET = "demo-secret"
TIMEZONE = "Europe/Berlin"


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


class DemoTarget:
    """The local calendar and task list of the demo: confirmations are simulated, nothing leaves the host.

    In the test mode the confirmed write never reaches a writer; a call here would be an error of the demo
    and is refused instead of silently pretending success.
    """

    def _refuse(self) -> NoReturn:
        raise RuntimeError("Die Demo schreibt nie in einen echten Kalender oder eine echte Aufgabenliste.")

    def reconcile(self, key: str) -> dict[str, Any] | None:
        self._refuse()

    def create(self, proposal: Proposal, key: str) -> dict[str, Any]:
        self._refuse()

    def remove(self, proposal: Proposal, key: str) -> dict[str, Any]:
        self._refuse()

    def reconcile_remove(self, proposal: Proposal, key: str) -> dict[str, Any] | None:
        self._refuse()


@dataclass
class VisitorRuntime:
    """The ordinary interface and dialog on one visitor's copy; writes are simulated (test mode)."""
    store: JsonStore
    commands: CommandInbox
    dialog: TelegramDialogController
    app: WebApp


class DemoRuntimes:
    """One runtime per visitor area, created on first use and closed with the instance."""

    def __init__(self, visitors: DemoVisitors, auth: WebAuth, settings: WebSettings, logger: Any) -> None:
        self.visitors, self.auth, self.settings, self.logger = visitors, auth, settings, logger
        self.runtimes: dict[Path, VisitorRuntime] = {}
        self.resources = ExitStack()
        self.lock = Lock()

    def _authorized(self, actor: str) -> bool:
        return actor.startswith("web:") and self.auth.active(actor.removeprefix("web:"))

    def _build(self, area: Path) -> VisitorRuntime:
        store = self.resources.enter_context(JsonStore(area))
        commands = CommandInbox(store)
        # With an inbox poll_once never waits for Telegram; the demo has no Telegram at all.
        target = DemoTarget()
        dialog = TelegramDialogController(store, DisabledTelegram(), 0, 0, self.logger,
                                          {CALENDAR_SLOT: target, TASK_SLOT: target}, True, TIMEZONE,
                                          inbox=TelegramInbox(store), commands=commands)
        dialog.review.web_authorizer = self._authorized
        app = WebApp(self.settings.allowed_hosts)
        MailhelpSite(app, self.auth, self.settings, TIMEZONE, self.logger,
                     ReviewViews(store, TIMEZONE, test_mode=True), commands)
        dialog.poll_once()
        return VisitorRuntime(store, commands, dialog, app)

    def app(self, session_id: str) -> VisitorApp | None:
        area = self.visitors.area(session_id)
        if area is None:
            return None
        with self.lock:
            runtime = self.runtimes.get(area)
            if runtime is None:
                runtime = self.runtimes[area] = self._build(area)
        return runtime.app

    def work(self) -> None:
        """Execute queued web actions of every visitor, like the main thread of a normal instance."""
        with self.lock:
            runtimes = list(self.runtimes.values())
        for runtime in runtimes:
            if runtime.commands.queued():
                runtime.dialog.poll_once()
            else:
                runtime.commands.refresh()

    def close(self) -> None:
        self.resources.close()


def create_demo(directory: Path, store: JsonStore, settings: WebSettings, secret: str,
                logger: Any) -> tuple[WebServer, DemoRuntimes]:
    auth = WebAuth(store, secret, 1, lambda text: None)
    auth.session_lifetime = timedelta(seconds=SESSION_SECONDS)
    auth.max_sessions = MAX_VISITORS
    visitors = DemoVisitors(store, directory / "data" / "visitors", packaged())
    runtimes = DemoRuntimes(visitors, auth, settings, logger)

    def start(session_id: str, key: str) -> None:
        visitors.start(session_id, key)

    site = DemoSite(WebApp(settings.allowed_hosts), auth, logger, start, runtimes.app, visitors.full)
    return WebServer(settings.host, settings.port, site, logger), runtimes


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
        server, runtimes = create_demo(directory, store, settings, demo_secret(directory), logger)
        worker = Thread(target=_work, args=(runtimes, stopped), name="demo-actions", daemon=True)
        server.start()
        worker.start()
        try:
            emit(f"Mailhelp-Demo: http://localhost:{settings.port}/anmelden")
            stopped.wait()
        finally:
            server.stop()
            worker.join(timeout=5)
            runtimes.close()
    return 0


def _work(runtimes: DemoRuntimes, stopped: Event) -> None:
    while not stopped.wait(0.1):
        runtimes.work()
