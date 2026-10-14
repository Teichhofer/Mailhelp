"""Read-only integration probes and explicitly requested synthetic test messages."""
from __future__ import annotations

import tempfile
from pathlib import Path

from .config import LEGACY_IMAP_SECRETS
from .diagnostics import DiagnosticsService
from .experience import _reader
from .external.providers import build_writers
from .setup import SetupService
from .storage import atomic_replace


class SetupRuntime:
    def __init__(self, app, site, secrets, target_probe=None):
        self.app, self.site, self.secrets = app, site, secrets
        self.target_probe = target_probe or self._check_target
        self.setup = SetupService(app.configuration)
        self.diagnostics = DiagnosticsService(app.store, site.auth.active, {
            "imap": self.imap, "calendar": self.calendar, "todoist": self.todoist,
            "llm": self.llm, "filesystem": self.filesystem, "telegram": self.telegram,
            "web_push": self.push, "telegram_test": self.telegram_test,
            "push_test": self.push_test, "llm_test": self.llm_test}, revision=self.setup.fingerprint)

    def secret_status(self):
        """Presence of the secrets the configured providers need; never their values."""
        draft = self.setup.draft_settings()
        targets = draft.targets
        status = {}
        for mailbox in draft.imap.enabled_mailboxes():
            names = LEGACY_IMAP_SECRETS if draft.imap.legacy_format else mailbox.secret_names
            status["/".join(names)] = ("vorhanden" if self.secrets is not None and mailbox.id in self.secrets.imap
                                       else "fehlt")
        names = ["openrouter_api_key", "telegram_bot_token"]
        names += ["todoist_token"] if targets.task_provider == "todoist" else []
        names += ["google_oauth_refresh_token"] if targets.calendar_provider == "google" else []
        names += ["caldav_username", "caldav_password"] if targets.uses_caldav else []
        names += ["microsoft_client_id"] if targets.uses_microsoft else []
        return {**status, **{name: "vorhanden" if self.secrets is not None and
                             getattr(self.secrets, name).get_secret_value() else "fehlt" for name in names}}

    def imap(self, actor):
        """Every enabled mailbox of the draft; one failing mailbox fails the check (3.1)."""
        cfg = self.setup.draft_settings()
        listed = {}
        try:
            for mailbox in cfg.imap.enabled_mailboxes():
                if self.secrets is None or mailbox.id not in self.secrets.imap:
                    # Credentials of a newly added mailbox are read at the next start.
                    return "failed", "auth"
                with _reader(cfg, self.secrets, mailbox) as reader:
                    folders = listed[str(mailbox.id)] = [item.name for item in reader.list_folders()]
                    required = [*mailbox.folders, mailbox.drafts_folder]
                    if not set(required) <= set(folders):
                        return "failed", "configuration"
                    reader.check_access(required)
        finally:
            # The folder choices of the setup step, also when a later mailbox fails.
            self.app.store.save("setup-folders", {"schema_version": 1, "mailboxes": listed,
                                                  "folders": next(iter(listed.values()), [])})
        return "limited", "draft_readonly"

    def calendar(self, actor):
        self.target_probe("google_calendar", self.setup.draft_settings())
        return "ready", ""

    def todoist(self, actor):
        self.target_probe("todoist", self.setup.draft_settings())
        return "ready", ""

    def _check_target(self, service, cfg):
        """Read-only access check of the configured calendar or task target."""
        writers = build_writers(cfg, self.secrets, self.app.configuration.directory, timeout_cap=10)
        try:
            (writers.calendar if service == "google_calendar" else writers.tasks).check_access()
        finally:
            writers.close()

    def llm(self, actor):
        for step in self.app.analyzer.prompts.prompts:
            self.app.analyzer.prompts.resolved_routes(step)
        return "ready", ""

    def filesystem(self, actor):
        with tempfile.TemporaryDirectory(prefix="diagnostic-", dir=self.app.store.directory) as folder:
            path = Path(folder) / "synthetic.json"
            atomic_replace(path, '{"synthetic": true}\n')
            if path.read_text(encoding="utf-8") != '{"synthetic": true}\n':
                return "failed", "service"
        return "ready", ""

    def telegram(self, actor):
        if not self.app.settings.telegram.enabled:
            return "disabled", ""
        self.app.telegram.check_access()
        return "ready", ""

    def push(self, actor):
        if not self.app.settings.push.enabled:
            return "disabled", ""
        if self.site.experience.push is None or not any(
                device.startswith(actor + ":") for device in self.site.experience.push.destinations()):
            return "limited", "browser"
        return "ready", ""

    def telegram_test(self, actor):
        if not self.app.settings.telegram.enabled:
            return "disabled", ""
        self.app.telegram.send(self.app.settings.telegram.chat_id, "Mailhelp: neutrale Testnachricht.")
        return "ready", ""

    def push_test(self, actor):
        push = self.site.experience.push
        if not self.app.settings.push.enabled or push is None:
            return "disabled", ""
        device = next((device for device in push.destinations() if device.startswith(actor + ":")), None)
        if device is None:
            return "limited", "browser"
        push.deliver(device, "test")
        return "ready", ""

    def llm_test(self, actor):
        prompts = self.app.analyzer.prompts
        if "diagnostic_test" not in prompts.prompts:
            return "disabled", "configuration"
        routes, system, _ = prompts.resolved_routes("diagnostic_test")
        route = routes[0]
        self.app.openrouter.complete(route.model, route.parameters, system, {"synthetic": True},
                                     stage="diagnostic_test")
        return "ready", ""
