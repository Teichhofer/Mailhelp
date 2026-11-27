"""7.1 (D1): the demo mode – a web instance on prepared example data, chosen only by ``--demo``.

The mode is fixed for the lifetime of the process. It never connects a mailbox, Telegram, a model or
a real calendar or task list, and it never opens a production directory: the runtime directory must
be empty on the first start and then carries its own marker file.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import time
from collections.abc import Callable, Mapping
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from threading import Event, RLock, Thread
from typing import Any, NoReturn

from ..config import WebSettings
from ..domain.proposal import Proposal
from ..external.roles import CALENDAR_SLOT, TASK_SLOT
from ..i18n import Locale, current, stored, tr
from ..logging import JsonlLogger
from ..persistence.storage import JsonStore, atomic_replace
from ..review.inbox import CommandInbox
from ..review.views import ReviewViews
from ..runtime.demo_answers import DemoRevisions
from ..runtime.demo_dataset import DemoDatasetError, packaged
from ..runtime.demo_visitors import MAX_VISITORS, DemoVisitors
from ..runtime.standalone import DisabledTelegram
from ..telegram import TelegramDialogController
from ..telegram.receiver import TelegramInbox
from ..web.app import WebApp
from ..web.auth import WebAuth
from ..web.demo_site import DEMO_INSTANCE, SESSION_SECONDS, DemoHooks, DemoSite, VisitorApp, demo_may_link
from ..web.http import Request, Response
from ..web.server import WebServer
from ..web.site import MailhelpSite
from ..web.usage_site import SAMPLE_USAGE
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
    app: VisitorApp
    resources: ExitStack
    active: bool = True


class DemoRuntimes:
    """One runtime per visitor area, created on first use and closed with the instance."""

    def __init__(
        self,
        visitors: DemoVisitors,
        auth: WebAuth,
        settings: WebSettings,
        logger: Any,
        revisions: DemoRevisions,
        asset_source: WebApp | None = None,
    ) -> None:
        self.visitors, self.auth, self.settings, self.logger = visitors, auth, settings, logger
        self.asset_source = asset_source
        self.revisions = revisions
        self.default_locale = current()
        self.runtimes: dict[Path, VisitorRuntime] = {}
        self.lock = RLock()

    def _authorized(self, actor: str) -> bool:
        return actor.startswith("web:") and self.auth.active(actor.removeprefix("web:"))

    def _build(self, area: Path) -> VisitorRuntime:
        resources = ExitStack()
        with resources:
            store = resources.enter_context(JsonStore(area))
            commands = CommandInbox(store)
            # With an inbox poll_once never waits for Telegram; the demo has no Telegram at all.
            target = DemoTarget()
            source = area / ".demo" if (area / ".demo").is_dir() else self.visitors.dataset
            revisions = DemoRevisions.load(source)
            dialog = TelegramDialogController(
                store,
                DisabledTelegram(),
                0,
                0,
                self.logger,
                {CALENDAR_SLOT: target, TASK_SLOT: target},
                True,
                TIMEZONE,
                revisions,
                inbox=TelegramInbox(store),
                commands=commands,
            )
            dialog.review.web_authorizer = self._authorized
            app = WebApp(self.settings.allowed_hosts, asset_source=self.asset_source)
            app.default_locale = self.default_locale
            site = MailhelpSite(
                app,
                self.auth,
                self.settings,
                TIMEZONE,
                self.logger,
                ReviewViews(store, TIMEZONE, test_mode=True),
                commands,
            )
            # HTTP responses release the lifecycle lock before the local worker takes the command.
            site.settle_seconds = 0
            site.offered = demo_may_link  # 8.8.5: closed areas are info cards on the settings overview
            site.usage.sample = SAMPLE_USAGE  # 8.8.6: example usage in points, never a ledger or a price
            dialog.poll_once()

            def serve(request: Request) -> Response:
                with self.lock:
                    session = self.auth.authenticate(request.cookies().get("mh_session"))
                    entry = self.visitors.entry(session.id) if session is not None else None
                    if not runtime.active or session is None or entry is None or self.visitors.area(session.id) != area:
                        return Response.text(409, tr("Die Demo wurde neu gestartet. Bitte die Seite neu laden."))
                    if request.method == "POST":
                        try:
                            generation = request.form().get("demo_generation", "1")
                        except (UnicodeDecodeError, ValueError):
                            return Response.text(400, tr("Ungültige Formulardaten."))
                        if generation != str(entry.generation):
                            return Response.text(409, tr("Die Demo wurde neu gestartet. Bitte die Seite neu laden."))
                    response = app(request)
                    if response.content_type.startswith("text/html"):
                        hidden = f'<input type="hidden" name="demo_generation" value="{entry.generation}">'
                        response.body = re.sub(
                            r'(<form\b[^>]*method="post"[^>]*>)',
                            lambda match: match[0] + hidden,
                            response.body.decode("utf-8"),
                        ).encode("utf-8")
                    return response

            runtime = VisitorRuntime(store, commands, dialog, serve, resources.pop_all())
            return runtime

    def app(self, session_id: str) -> VisitorApp | None:
        with self.lock:
            area = self.visitors.area(session_id)
            if area is None:
                return None
            runtime = self.runtimes.get(area)
            if runtime is None:
                runtime = self.runtimes[area] = self._build(area)
        return runtime.app

    def work(self) -> None:
        """Execute queued web actions of every visitor, like the main thread of a normal instance."""
        with self.lock:
            for runtime in self.runtimes.values():
                if runtime.commands.queued():
                    runtime.dialog.poll_once()
                else:
                    runtime.commands.refresh()

    def _drop(self, areas: set[Path]) -> None:
        with self.lock:
            dropped = [self.runtimes.pop(area) for area in areas if area in self.runtimes]
            for runtime in dropped:
                runtime.active = False
        for runtime in dropped:
            runtime.resources.close()

    def reset(self, session_id: str, key: str, locale: Locale = Locale.DE, generation: int | None = None) -> None:
        """A fresh copy for this visitor; its open store is closed before the area is replaced."""
        with self.lock:
            area = self.visitors.area(session_id)
            try:
                fresh = self.visitors.reset(session_id, key, locale, generation=generation, retain_old=True)
            except DemoDatasetError as exc:
                raise RuntimeError("Demo dataset unavailable") from exc
            if area is not None and fresh != area:
                self._drop({area})
                shutil.rmtree(area, ignore_errors=True)

    def prepared(self, session_id: str) -> dict[tuple[str, str, int], str]:
        area = self.visitors.area(session_id)
        if area is not None:
            source = area / ".demo" if (area / ".demo").is_dir() else self.visitors.dataset
            return DemoRevisions.load(source).prepared()
        return self.revisions.prepared()

    def cleanup(self) -> int:
        """Remove the areas of ended or expired sessions and close their runtimes."""
        with self.lock:
            sessions = self.auth.sessions()
            for session in sessions:
                if self.visitors.entry(session.id) is None:
                    self.auth.revoke(session.id)
            active = {session.id for session in self.auth.sessions()}
            stale = {area for area in self.runtimes if not any(
                self.visitors.area(session_id) == area for session_id in active)}
            self._drop(stale)
            return self.visitors.cleanup(active)

    def close(self) -> None:
        self._drop(set(self.runtimes))


def create_demo(directory: Path, store: JsonStore, settings: WebSettings, secret: str,
                logger: Any, *, trust_proxy: bool = False) -> tuple[WebServer, DemoRuntimes]:
    auth = WebAuth(store, secret, 1, lambda text: None)
    # 8.8.5: visitors use the customer interface (customer navigation and routes, deny by default);
    # sessions of an earlier demo start without a role are ended once.
    auth.enter_customer_mode(DEMO_INSTANCE)
    auth.session_lifetime = timedelta(seconds=SESSION_SECONDS)
    auth.max_sessions = MAX_VISITORS
    visitors = DemoVisitors(store, directory / "data" / "visitors", packaged())
    # Load answers only from the chosen area: an unused damaged corpus cannot disable the other language.
    revisions = DemoRevisions([])
    public = WebApp(settings.allowed_hosts)
    public.default_locale = current()
    runtimes = DemoRuntimes(visitors, auth, settings, logger, revisions, public)

    def start(session_id: str, key: str, locale: Locale) -> None:
        with runtimes.lock:
            try:
                visitors.start(session_id, key, locale)
            except DemoDatasetError as exc:
                raise RuntimeError("Demo dataset unavailable") from exc

    def dataset_locale(session_id: str) -> Locale | None:
        entry = visitors.entry(session_id)
        return entry.dataset_locale if entry is not None else None

    def generation(session_id: str) -> int:
        entry = visitors.entry(session_id)
        return entry.generation if entry is not None else 1

    hooks = DemoHooks(start, runtimes.app, visitors.full, runtimes.reset, dataset_locale, runtimes.prepared, generation)
    site = DemoSite(public, auth, logger, hooks, revisions.prepared(), trust_proxy=trust_proxy)
    site.lock = runtimes.lock
    return WebServer(settings.host, settings.port, site, logger), runtimes


def run_demo(directory: Path, shutdown: Any, *, emit: Callable[[str], None] = console,
             environ: Mapping[str, str] = os.environ) -> int:
    try:
        prepare_directory(directory)
    except DemoDirectoryError as exc:
        emit(tr("Demo nicht gestartet: {reason}", reason=stored(str(exc))))
        return 2
    settings = demo_settings(environ)
    stopped = Event()
    shutdown.stop = stopped.set
    with JsonStore(directory / "data" / "demo") as store:
        logger = JsonlLogger(directory / "logs", console_enabled=False)
        server, runtimes = create_demo(directory, store, settings, demo_secret(directory), logger,
                                       trust_proxy=environ.get("MAILHELP_DEMO_TRUST_PROXY") == "1")
        worker = Thread(target=_work, args=(runtimes, stopped), name="demo-actions", daemon=True)
        server.start()
        worker.start()
        try:
            emit(tr("Mailhelp-Demo: http://localhost:{port}/anmelden", port=settings.port))
            stopped.wait()
        finally:
            server.stop()
            worker.join(timeout=5)
            runtimes.close()
    return 0


CLEANUP_SECONDS = 60.0


def _work(runtimes: DemoRuntimes, stopped: Event, clock: Callable[[], float] = time.monotonic) -> None:
    last_cleanup = clock()
    while not stopped.wait(0.1):
        runtimes.work()
        if clock() - last_cleanup >= CLEANUP_SECONDS:
            last_cleanup = clock()
            runtimes.cleanup()
