"""Mailhelp pages and actions on top of the checked router.

Authentication and CSRF are enforced here for every page except the login
flow, ``/health`` and static files.  Review state is only read through the
read models; changes are submitted to the command inbox and executed by the
main thread.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from .. import __version__
from ..config import WebSettings
from ..configuration import AdminCommand, AdminKind, ConfigurationService
from ..models import ProposalStatus
from ..review.commands import CommandKind, CommandSource, ReviewCommand
from ..review.inbox import CommandConflict, CommandEntry, CommandInbox, CommandInboxFull
from ..review.views import Overview, ReviewViews, SystemStatus
from ..runtime.lifecycle import Lifecycle
from .actions import command_page, needs_choice, result_kind, stale_page
from .app import WebApp
from .auth import WebAuth, WebSession
from .http import Request, Response
from .login_site import PAIR_COOKIE, SESSION_COOKIE, LoginSite
from .pages import HELP_BUTTON, HELP_WINDOW, OPEN_DECISIONS, error_page, layout, notice, shows_help_button
from .review_site import ReviewSite
from .sender_site import LIST_PATH as SENDERS_PATH
from .sender_site import SenderSite
from .status_accounts import AccountInfo
from .status_pages import ServiceInfo, status_page

FORM_TYPE = "application/x-www-form-urlencoded"
# How long the progress page waits for a quick result before it shows "running".
SETTLE_SECONDS = 1.5


class EventLogger(Protocol):
    def event(self, level: str, module: str, event: str, **fields: object) -> None: ...


Handler = Callable[..., Response]
if TYPE_CHECKING:
    from ..notifications.notification_runtime import NotificationRuntime
    from ..runtime.metrics import MetricsRecorder
    from .reanalysis_site import ReanalysisSite


class MailhelpSite:
    """Register the Mailhelp routes on a :class:`WebApp`."""

    def __init__(self, app: WebApp, auth: WebAuth, settings: WebSettings,
                 configured_timezone: str, logger: EventLogger, views: ReviewViews,
                 commands: CommandInbox, *, link_base: Callable[[], str] | None = None,
                 llm_calls_per_minute: int | None = None,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC),
                 configuration: ConfigurationService | None = None, metrics: MetricsRecorder | None = None,
                 lifecycle: Lifecycle | None = None, models: list[tuple[str, str, str, str]] | None = None):
        self.app, self.auth, self.settings = app, auth, settings
        self.views, self.commands = views, commands
        self.lifecycle = lifecycle
        self.link_base = link_base or (lambda: f"http://127.0.0.1:{settings.port}")
        self.llm_calls_per_minute, self.clock = llm_calls_per_minute, clock
        # The web interface starts together with Mailhelp.
        self.started_at = clock()
        self.configured_timezone, self.logger = configured_timezone, logger
        self.local_hosts = {f"127.0.0.1:{settings.port}", f"localhost:{settings.port}"}
        self.login_pages = LoginSite(self)
        self.review = ReviewSite(self)
        from .series_site import SeriesSite
        self.series = SeriesSite(self)
        app.route("GET", "/offen", self.signed_in(self.review.home))
        app.route("GET", "/anmelden", self.login_pages.login)
        app.route("POST", "/anmelden/code", self.login_pages.request_code)
        app.route("POST", "/anmelden", self.login_pages.pair)
        app.route("POST", "/anmelden/passwort", self.login_pages.password)
        app.route("GET", "/einstellungen/web-passwort", self.signed_in(self.login_pages.password_settings))
        app.route("POST", "/einstellungen/web-passwort", self.signed_in(self.login_pages.save_password))
        app.route("POST", "/abmelden", self.signed_in(self.login_pages.logout))
        app.route("GET", "/geraete", self.signed_in(self.login_pages.devices))
        app.route("POST", r"/geraete/(?P<session_id>[a-f0-9]{16})/abmelden",
                  self.signed_in(self.login_pages.revoke))
        app.route("POST", "/geraete/alle-abmelden", self.signed_in(self.login_pages.revoke_all))
        app.route("GET", "/", self.signed_in(self.review.home))
        app.route("GET", r"/vorschlag/(?P<mail_id>[a-f0-9]{24})/(?P<proposal_id>[A-Za-z0-9_-]{1,64})",
                  self.signed_in(self.review.detail))
        app.route("GET", r"/mail/(?P<mail_id>[a-f0-9]{24})", self.signed_in(self.review.mail))
        app.route("GET", r"/mail/(?P<mail_id>[a-f0-9]{24})/anhang/(?P<index>[0-9]{1,5})",
                  self.signed_in(self.review.attachment))
        app.route("GET", r"/mail/(?P<mail_id>[a-f0-9]{24})/original/(?P<index>[0-9]{1,5})",
                  self.signed_in(self.review.original))
        app.route("GET", "/status", self.signed_in(self.status))
        app.route("GET", "/api/stand", self.signed_in(self.state))
        app.route("POST", "/aktion", self.signed_in(self.act))
        app.route("GET", r"/aktion/(?P<entry_id>[a-f0-9]{32})", self.signed_in(self.progress))
        app.route("GET", r"/api/aktion/(?P<entry_id>[a-f0-9]{32})", self.signed_in(self.command_status))
        app.route("POST", r"/aktion/(?P<entry_id>[a-f0-9]{32})/gesehen", self.signed_in(self.acknowledge))
        from .archive_site import ArchiveSite
        self.archive = ArchiveSite(self, configuration, metrics, lifecycle, models)
        self.senders = SenderSite(self)
        from .experience import ExperienceSite
        self.experience = ExperienceSite(self)
        from .activity_site import ActivitySite
        self.activity = ActivitySite(self)
        from .setup_site import SetupSite
        self.setup_page = SetupSite(self)
        from .mailbox_site import MailboxSite
        self.mailbox_page = MailboxSite(self)
        from .mailbox_add_site import MailboxAddSite
        self.mailbox_add = MailboxAddSite(self)
        from .iserv_site import IServSite
        self.iserv_page = IServSite(self)
        from .secrets_site import SecretsSite
        self.secrets_page = SecretsSite(self)
        from .reconciliation_site import ReconciliationSite
        self.reconciliation_page = ReconciliationSite(self)
        from .rule_learning_site import RuleLearningSite
        self.rule_learning = RuleLearningSite(self)
        self.notification_runtime: NotificationRuntime | None = None
        # 5.1.5: set by the runtime when re-analysis is available (web.reanalysis_site).
        self.reanalysis_page: ReanalysisSite | None = None
        self.commands.changed = self.refresh_overview
        self._overview_revision = -1
        self.refresh_overview()

    def refresh_overview(self, *, force: bool = False) -> None:
        """The operator publishes a complete read model before publishing results."""
        if force or self._overview_revision != self.views.store.revision:
            overview = self.views.overview()
            empty = self.experience.inbox_zero() if not overview.open and not overview.relevance else None
            self._overview = overview
            self._empty = empty
            self._overview_revision = self.views.store.revision

    def overview(self) -> Overview:
        return self._overview

    # --- helpers ------------------------------------------------------------------


    def _form(self, request: Request) -> dict[str, str] | Response:
        content_type = (request.header("content-type") or "").split(";")[0].strip().lower()
        if content_type != FORM_TYPE:
            return Response.text(415, "Nur Formulardaten werden angenommen.")
        try:
            return request.form(max_num_fields=200 if request.path == "/themen/lernen" else
                                120 if request.path.startswith("/serie/") else 20)
        except (UnicodeDecodeError, ValueError):
            return Response.text(400, "Ungültige Formulardaten.")

    @staticmethod
    def _forbidden() -> Response:
        return Response.html(403, error_page(
            "Sicherheitsprüfung fehlgeschlagen",
            "Die Anfrage konnte nicht bestätigt werden. Bitte die Seite neu laden und erneut versuchen."))

    def signed_in(self, handler: Handler) -> Handler:
        """Require a live session; a POST also requires its CSRF token."""
        def guarded(request: Request, **arguments: str) -> Response:
            fast = request.path in {"/", "/offen", "/aktion", "/api/stand"} or request.path.startswith("/api/aktion/")
            authenticate = self.auth.authenticate_fast if fast else self.auth.authenticate
            session = authenticate(request.cookies().get(SESSION_COOKIE))
            if session is None:
                if request.wants_json():
                    return Response.json(401, {"error": "nicht angemeldet"})
                if request.method == "GET":
                    return Response.redirect("/anmelden")
                return self._forbidden()
            if request.method == "POST":
                if (self.lifecycle is not None and self.lifecycle.state != "running"
                        and request.path not in {"/einstellungen/beenden", "/einstellungen/neustarten"}):
                    return self._reply(request, 503, "Mailhelp wird beendet; keine neuen Aktionen möglich.")
                form = self._form(request)
                if isinstance(form, Response):
                    return form
                if not self.auth.csrf_valid(session.id, form.get("csrf")):
                    self.logger.event("WARNING", "web", "csrf_rejected", path=request.path)
                    return self._forbidden()
                return self._counted(handler, request, session, form, **arguments)
            return self._counted(handler, request, session, **arguments)
        return guarded

    def _counted(self, handler: Handler, request: Request, *values: object, **arguments: str) -> Response:
        """The navigation shows the open decisions of the published overview (5.0.1).

        Settings pages also show the floating help chat button (5.3.12).
        """
        overview = self.overview()
        token = OPEN_DECISIONS.set(len(overview.open) + len(overview.relevance))
        button = HELP_BUTTON.set(shows_help_button(request.path))
        session = values[0]
        window = HELP_WINDOW.set((lambda: self.archive.help.window.frame(
            session, request.path, request.query))
            if shows_help_button(request.path) and isinstance(session, WebSession) else None)
        try:
            return handler(request, *values, **arguments)
        finally:
            HELP_BUTTON.reset(button)
            HELP_WINDOW.reset(window)
            OPEN_DECISIONS.reset(token)


    # --- pairing ------------------------------------------------------------------





    # --- sessions -----------------------------------------------------------------










    def status(self, request: Request, session: WebSession) -> Response:
        from .status_accounts import account_rows
        overview = self.views.overview()
        now = self.clock()
        info = ServiceInfo(
            version=__version__, test_mode=self.views.test_mode, started_at=self.started_at, now=now,
            address=self.link_base(), devices=len(self.auth.sessions()),
            llm_calls_per_minute=self.llm_calls_per_minute, commands=self.commands.counts(),
            command_latencies=self.commands.latencies(), acceptance_latencies=self.commands.acceptance_latencies())
        system = self.views.system(now)
        metrics = self.archive.metrics
        runtime = metrics.runtime() if metrics is not None else None
        accounts = self._status_accounts()
        monthly = None
        if metrics is not None:
            monthly = metrics.month_cost(now, self.configured_timezone)
        info = replace(info, runtime=runtime,
                       monthly_cost=monthly,
                       last_polls=tuple((account.label,
                           (runtime or {}).get("accounts", {}).get(account.key, {}).get(
                               "checked_at", "Noch nicht geprüft"))
                           for account in accounts if account.key.startswith("imap:") and account.enabled),
                       services=tuple(metrics.expected_services()) if metrics is not None else (),
                       accounts=tuple(account_rows(accounts, runtime or {}, ZoneInfo(self.configured_timezone))),
                       fingerprint=self._status_fingerprint(overview, system, runtime, accounts))
        return Response.html(200, status_page(overview.run, overview, self.configured_timezone, system, info))

    def _status_accounts(self) -> tuple[AccountInfo, ...]:
        from ..config import Settings, read_yaml
        from .status_accounts import configured_accounts
        configuration = self.archive.configuration
        if configuration is None:
            return ()
        running = configured_accounts(configuration.active)
        try:
            saved = configured_accounts(Settings.model_validate(read_yaml(configuration.directory / "config.yaml")))
        except (OSError, ValueError):
            return running
        previous = {account.key: account for account in running}
        return tuple(replace(account, pending_restart=previous.get(account.key) != account) for account in saved)

    @staticmethod
    def _status_fingerprint(overview: Overview, system: SystemStatus, runtime: dict[str, Any] | None,
                            accounts: tuple[AccountInfo, ...] = ()) -> str:
        """Changes when anything the status page shows changes (contact times excluded)."""
        parts = [overview.fingerprint, system.run_finished, system.run_total, system.mails_failed,
                 system.mails_waiting_relevance, sorted(system.analysis.items()),
                 sorted((str(key), value) for key, value in system.proposals.items()), accounts]
        if runtime is not None:
            parts += [runtime["stage"], runtime.get("mail_id"), runtime.get("next_poll"),
                      runtime.get("imap_errors", []),
                      sorted((key, value["status"]) for key, value in runtime.get("accounts", {}).items())]
        return hashlib.sha256(json.dumps(parts, default=str).encode("utf-8")).hexdigest()[:16]

    def act(self, request: Request, session: WebSession, form: dict[str, str]) -> Response:
        """Queue a version-bound command for the main thread; answer at once."""
        started = time.perf_counter()
        try:
            command = ReviewCommand(
                kind=CommandKind(form.get("kind", "")), source=CommandSource.WEB,
                actor=f"web:{session.id}", mail_id=form.get("mail_id", ""),
                proposal_id=form.get("proposal_id") or None,
                version=int(form.get("version", "")), idempotency_key=form.get("key", ""),
                text=form.get("text") or None, decision=form.get("decision") or None,
                candidate=int(form["candidate"]) if form.get("candidate") else None)
        except (ValueError, ValidationError):
            return self._reply(request, 422, "Die Aktion ist unvollständig oder ungültig.")
        stale = self._stale(command)
        try:
            existing = self.commands.existing(command)
        except CommandConflict:
            return self._reply(request, 422, "Diese Aktion wurde bereits mit anderen Angaben gesendet.")
        if stale is not None and existing is None:
            current = next((view for view in self._overview.open + self._overview.recent
                            if (view.mail_id, view.proposal_id) == (command.mail_id, command.proposal_id)), None)
            if request.wants_json():
                return Response.json(409, {"error": stale,
                                           "current_version": current.version if current else None})
            return Response.html(409, stale_page(stale, current))
        try:
            entry, new = self.commands.submit(command)
        except CommandConflict:
            return self._reply(request, 422, "Diese Aktion wurde bereits mit anderen Angaben gesendet.")
        except CommandInboxFull:
            return self._reply(request, 503, "Mailhelp ist gerade ausgelastet. Bitte gleich erneut versuchen.")
        except OSError:
            return self._reply(request, 503, "Die Aktion konnte nicht sicher gespeichert werden. "
                               "Bitte denselben Versuch erneut senden.")
        self.commands.note_acceptance(entry, (time.perf_counter() - started) * 1000, new)
        location = f"/aktion/{entry.id}"
        if request.wants_json():
            response = Response.json(202, {"id": entry.id, "status": entry.status.value,
                                           "status_url": location})
            response.headers["Location"] = location
            return response
        anchor = f"v-{command.mail_id}-{command.proposal_id}" if command.proposal_id else f"r-{command.mail_id}"
        return Response.redirect(f"/?aktion={entry.id}#{anchor}")

    def _stale(self, command: ReviewCommand) -> str | None:
        """Refuse an outdated version before it is queued (checked again when it runs)."""
        if command.kind == CommandKind.RECHECK_MAIL:
            return None
        if command.kind == CommandKind.RELEVANCE:
            current_relevance = next((view for view in self._overview.relevance
                                      if view.mail_id == command.mail_id), None)
            if current_relevance is not None and command.version < current_relevance.version:
                return "Diese Relevanzfrage ist bereits beantwortet oder veraltet."
            return None
        assert command.proposal_id is not None
        current = next((view for view in self._overview.open + self._overview.recent
                        if (view.mail_id, view.proposal_id) == (command.mail_id, command.proposal_id)), None)
        if command.kind == CommandKind.VERIFY_ENTRY:
            # 5.2: a recheck belongs to exactly the written, not yet verified version.
            if current is not None and (command.version != current.version
                                        or CommandKind.VERIFY_ENTRY not in current.actions):
                return "Dieser Eintrag wird bereits geprüft oder wurde inzwischen geändert."
            return None
        if (current is not None and (command.version < current.version
                or (command.version == current.version and current.status not in {ProposalStatus.PENDING_CONFIRMATION,
                                          ProposalStatus.NEEDS_CLARIFICATION}))):
            return "Dieser Vorschlag wurde inzwischen geändert oder entschieden."
        return None

    @staticmethod
    def _reply(request: Request, status: int, message: str) -> Response:
        if request.wants_json():
            return Response.json(status, {"error": message})
        return Response.html(status, error_page("Aktion nicht möglich", message))

    def progress(self, request: Request, session: WebSession, entry_id: str) -> Response:
        entry = self.commands.get(entry_id)
        if entry is None or entry.command.actor != f"web:{session.id}":
            return self._reply(request, 404, "Diese Aktion ist nicht (mehr) bekannt.")
        if request.wants_json():
            return Response.json(200, {
                "id": entry.id, "status": entry.status.value,
                "result": entry.result.model_dump(mode="json") if entry.result else None})
        entry = self._settled(entry)
        command = entry.command
        if isinstance(command, AdminCommand):
            if entry.result is None:
                return Response.html(
                    200, layout("Einstellungen werden gespeichert", "<h1>Wird verarbeitet</h1>", refresh=1)
                )
            if command.kind == AdminKind.SENDERS:
                # Back to where the change was made; that page shows the result.
                mail_id = command.patch.get("mail_id")
                target = f"/mail/{mail_id}" if mail_id else SENDERS_PATH
                return Response.redirect(f"{target}?ergebnis={entry.id}")
            return Response.html(
                200, layout("Ergebnis", notice(entry.result.message, result_kind(entry.result.status))
                            + '<a href="/einstellungen">Zurück</a>')
            )
        if entry.result is not None and command.kind == CommandKind.RECHECK_MAIL:
            return Response.redirect(f"/mail/{command.mail_id}?ergebnis={entry.id}")
        current = (self.views.proposal(command.mail_id, command.proposal_id)
                   if command.proposal_id else None)
        if entry.result is not None and not needs_choice(entry, current):
            # Done: back to the overview; the anchor selects the card that shows the result.
            from .command_cards import anchor
            return Response.redirect(f"/?ergebnis={entry.id}#{anchor(entry)}")
        return Response.html(200, command_page(entry, self.auth.csrf_token(session.id), current))

    def command_status(self, request: Request, session: WebSession, entry_id: str) -> Response:
        """Only the authenticated browser's durable command, without rebuilding views."""
        entry = self.commands.get(entry_id)
        from .command_cards import visible
        if entry is None or not visible(entry, f"web:{session.id}"):
            return Response.json(404, {"error": "Diese Aktion ist nicht (mehr) bekannt."})
        return Response.json(200, {"status": entry.status.value,
                                   "target": f"/aktion/{entry.id}" if entry.result is not None else None})

    def acknowledge(self, request: Request, session: WebSession, form: dict[str, str], entry_id: str) -> Response:
        from .command_cards import visible
        entry = self.commands.get(entry_id)
        if entry is None or entry.result is None or not visible(entry, f"web:{session.id}"):
            return self._reply(request, 404, "Diese abgeschlossene Aktion ist nicht bekannt.")
        self.commands.incoming.acknowledge(entry, f"web:{session.id}")
        return Response.redirect("/")

    def _settled(self, entry: CommandEntry) -> CommandEntry:
        """Wait briefly for a quick result so the page usually needs no reload."""
        deadline = time.monotonic() + SETTLE_SECONDS
        while entry.result is None and time.monotonic() < deadline:
            time.sleep(0.05)
            entry = self.commands.get(entry.id) or entry
        return entry

    def state(self, request: Request, session: WebSession) -> Response:
        """Fingerprint of the overview (or the status page); the page reloads when it changes."""
        report_id = parse_qs(request.query, max_num_fields=5).get("bericht")
        if report_id:
            return self.activity.state(report_id[0])
        overview = self.overview()
        if parse_qs(request.query, max_num_fields=5).get("seite") == ["status"]:
            metrics = self.archive.metrics
            return Response.json(200, {"fingerprint": self._status_fingerprint(
                overview, self.views.system(self.clock()),
                metrics.runtime() if metrics is not None else None, self._status_accounts())})
        return Response.json(200, {"fingerprint": overview.fingerprint})






__all__ = ["FORM_TYPE", "MailhelpSite", "PAIR_COOKIE", "SESSION_COOKIE"]
