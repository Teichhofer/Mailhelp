"""Read-only integration probes and explicitly requested synthetic test messages."""
from __future__ import annotations

import os
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
            "push_test": self.push_test, "llm_test": self.llm_test, "iserv": self.iserv},
            revision=self.setup.fingerprint)

    def update_profile_checks(self):
        from .mailbox_settings import target_profiles
        configured = target_profiles(self.setup.draft_settings())
        for name in list(self.diagnostics.checks):
            if name.startswith(("calendar:", "tasks:")):
                del self.diagnostics.checks[name]
        for number in configured:
            if self.setup.draft_settings().target_profiles:
                self.diagnostics.checks[f"calendar:{number}"] = lambda actor, number=number: self.profile_check(
                    number, "calendar"
                )
                self.diagnostics.checks[f"tasks:{number}"] = lambda actor, number=number: self.profile_check(
                    number, "tasks"
                )

    def credentials(self, cfg):
        from pydantic import SecretStr

        from .config import ImapCredentials, _dotenv, imap_secret_values, iserv_secret_values
        from .target_profiles import load_profile_secrets
        if self.secrets is None:
            return None
        env = {**_dotenv(self.app.configuration.directory / ".env"), **os.environ}
        seed = {name.upper(): value.get_secret_value() for name, value in self.secrets if isinstance(value, SecretStr)}
        env = {**seed, **env}
        profiles, _missing = load_profile_secrets(cfg, env)
        profiles = {
            number: {name: SecretStr(value) for name, value in values.items()} for number, values in profiles.items()
        }
        for number, previous in self.secrets.profiles.items():
            profiles[number] = {**previous, **profiles.get(number, {})}
        values, _missing = imap_secret_values(cfg.imap, env)
        imap = {
            **self.secrets.imap,
            **{number: ImapCredentials.model_validate(value) for number, value in values.items()},
        }
        found, _missing = iserv_secret_values(cfg.iserv, env)
        iserv = {
            **self.secrets.iserv,
            **{number: ImapCredentials.model_validate(value) for number, value in found.items()},
        }
        result = self.secrets.model_copy(update={"profiles": profiles, "imap": imap, "iserv": iserv})
        if hasattr(self.app.logger, "secrets"):
            self.app.logger.secrets = (*self.app.logger.secrets, *result.known_values())
        return result

    def profile_check(self, number, role):
        from .mailbox_settings import target_profiles
        cfg = self.setup.draft_settings()
        cfg = cfg.model_copy(update={"targets": target_profiles(cfg)[number]})
        secrets = self.credentials(self.setup.draft_settings())
        if secrets is None:
            return "failed", "auth"
        writers = build_writers(cfg, secrets.for_profile(number), self.app.configuration.directory,
                                timeout_cap=10, profile_id=number)
        try:
            (writers.calendar if role == "calendar" else writers.tasks).check_access()
        finally:
            writers.close()
        return "ready", ""

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
        status.update({name: "vorhanden" if self.secrets is not None and
                       getattr(self.secrets, name).get_secret_value() else "fehlt" for name in names})
        if draft.iserv.enabled_accounts():
            # Read from .env now, so newly added IServ credentials show without a restart.
            found = self.credentials(draft)
            for account in draft.iserv.enabled_accounts():
                status["/".join(account.secret_names)] = (
                    "vorhanden" if found is not None and account.id in found.iserv else "fehlt")
        if draft.target_profiles:
            from .config import provider_secret_names
            from .mailbox_settings import active_profiles
            from .target_profiles import secret_name
            credentials = self.credentials(draft)
            for number, target in active_profiles(draft).items():
                for name in provider_secret_names(target):
                    value = credentials.for_profile(number) if credentials is not None else None
                    key = name if number == 1 else secret_name(name, number)
                    status[key] = "vorhanden" if value and getattr(value, name.lower()).get_secret_value() else "fehlt"
        return status

    def environment(self):
        """.env merged with the process environment, which takes precedence (as at start)."""
        from .config import _dotenv
        return {**_dotenv(self.app.configuration.directory / ".env"), **os.environ}

    def secret_fields(self):
        """(group, name) of every credential the draft configuration uses; never their values (3.3.11)."""
        from .config import imap_secret_names, provider_secret_names
        from .mailbox_settings import active_profiles
        from .target_profiles import secret_name
        draft, env = self.setup.draft_settings(), self.environment()
        fields = [(f"Postfach {mailbox.id} ({mailbox.label})", name)
                  for mailbox in draft.imap.configured_mailboxes()
                  for name in imap_secret_names(mailbox, env, draft.imap.legacy_format)]
        fields += [(f"IServ-Konto {account.id} ({account.label})", name)
                   for account in draft.iserv.accounts for name in account.secret_names]
        fields.append(("KI-Anbieter", "OPENROUTER_API_KEY"))
        if draft.telegram.enabled:
            fields.append(("Telegram", "TELEGRAM_BOT_TOKEN"))
        for number, targets in active_profiles(draft).items():
            group = "Kalender und Aufgaben" if number == 1 else f"Zielprofil {number}"
            fields += [(group, name if number == 1 else secret_name(name, number))
                       for name in provider_secret_names(targets)]
        return fields

    def imap(self, actor):
        """Every enabled mailbox of the draft; one failing mailbox fails the check (3.1)."""
        cfg = self.setup.draft_settings()
        credentials = self.credentials(cfg)
        listed = {}
        try:
            for mailbox in cfg.imap.enabled_mailboxes():
                if credentials is None or mailbox.id not in credentials.imap:
                    # Credentials of a newly added mailbox are read at the next start.
                    return "failed", "auth"
                with _reader(cfg, credentials, mailbox) as reader:
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

    def iserv(self, actor):
        """Sign in to every enabled IServ account of the draft and open its letter overview."""
        from .iserv import IServReader, IServSignInError
        cfg = self.setup.draft_settings()
        accounts = cfg.iserv.enabled_accounts()
        if not accounts:
            return "disabled", ""
        credentials = self.credentials(cfg)
        for account in accounts:
            if credentials is None or account.id not in credentials.iserv:
                return "failed", "auth"
            reader = IServReader(account, credentials.iserv[account.id], cfg.timezone, cfg.limits.max_mail_bytes)
            try:
                reader.check_access()
            except IServSignInError:
                return "failed", "auth"
            finally:
                reader.close()
        return "ready", ""

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
