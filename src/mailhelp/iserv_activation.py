"""One authenticated IServ activation, isolated from unrelated configuration drafts."""
from __future__ import annotations

import hashlib
import json
import re

from .config import ImapCredentials, Settings, read_yaml
from .configuration import AdminCommand, AdminKind, ConfigurationConflict, ConfigurationService, file_hash
from .env_file import EnvFileConflict, set_values, validate
from .env_file import file_hash as env_hash
from .review.results import ResultStatus


class IServActivation:
    def __init__(self, runtime):
        self.runtime = runtime
        original = runtime.app.configuration
        # Persist using the ordinary journal, but install adapters and settings only in the mail loop.
        self.configuration = ConfigurationService(original.directory, original.store, original.active,
                                                   original.authorize, lambda settings: None)
        self.store = runtime.app.store

    def _current(self, actor, version, revision, env_revision):
        if not self.configuration.authorize(actor):
            raise PermissionError("Sitzung abgelaufen")
        state = self.runtime.setup.state()
        if (state.version != version or file_hash(self.configuration.directory / "config.yaml") != revision
                or state.base_hash and state.base_hash != revision):
            raise ConfigurationConflict("Konfiguration oder Entwurf geändert; Seite neu laden.")
        if env_hash(self.configuration.directory / ".env") != env_revision:
            raise EnvFileConflict("Zugangsdaten geändert; Seite neu laden.")
        if state.kind != "settings":
            raise ConfigurationConflict("Anderen Entwurf zuerst übernehmen oder verwerfen.")
        return state

    def activate(self, actor, version, key, revision, env_revision, account, username, password):
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", key):
            raise ValueError("Idempotenzschlüssel fehlt")
        signature = hashlib.sha256(json.dumps([actor, version, revision, env_revision,
            account.model_dump(mode="json")], sort_keys=True).encode()).hexdigest()
        name = f"iserv-activation-{key}"
        with self.store.locked():
            if self._repeated(name, signature, actor):
                return
            self._current(actor, version, revision, env_revision)
        cfg = Settings.model_validate(read_yaml(self.configuration.directory / "config.yaml"))
        accounts = [item for item in cfg.iserv.accounts if item.id != account.id] + [account]
        cfg = Settings.model_validate({**cfg.model_dump(), "iserv": {"accounts": accounts}})
        # Only connections to mailboxes already available in this process can be hot-loaded.
        Settings.model_validate({**self.configuration.active.model_dump(), "iserv": cfg.iserv.model_dump()})
        keys = self.runtime.credentials(cfg)
        if keys is None:
            raise ValueError("Zugangsdaten nicht verfügbar")
        previous = keys.iserv.get(account.id)
        user = username or (previous.username if previous else "")
        secret = password or (previous.password.get_secret_value() if previous else "")
        values = dict(zip(account.secret_names, (user, secret), strict=True))
        for field, value in values.items():
            validate(field, value)
        # Process variables keep precedence; do not silently test a value the service cannot use.
        import os
        if any(field in os.environ and os.environ[field] != value for field, value in values.items()):
            raise ValueError("Prozessumgebung überschreibt die Zugangsdaten")
        keys.iserv[account.id] = ImapCredentials(username=user, password=secret)
        self.runtime.app.logger.secrets = (*getattr(self.runtime.app.logger, "secrets", ()), user, secret)
        from .iserv import IServReader
        reader = IServReader(account, keys.iserv[account.id], cfg.timezone, cfg.limits.max_mail_bytes,
                             max_attachment_bytes=cfg.limits.max_attachment_bytes)
        try:
            reader.check_access()
        finally:
            reader.close()
        with self.store.locked():
            if self._repeated(name, signature, actor):
                return
            state = self._current(actor, version, revision, env_revision)
            patch = {"iserv.accounts": cfg.iserv.model_dump(mode="json")["accounts"]}
            command = AdminCommand(kind=AdminKind.SETUP, actor=actor, idempotency_key=key,
                                   expected_hash=revision, patch=patch, acknowledged=True)
            content = self.configuration.render(command, self.configuration.candidate(command))
            self.store.save(name, {"signature": signature,
                                  "candidate_hash": hashlib.sha256(content.encode()).hexdigest(), "status": "prepared"})
            # Recheck authorization immediately before the credential/configuration writes.
            self._current(actor, version, revision, env_revision)
            set_values(self.configuration.directory / ".env", values, env_revision)
            result = self.configuration.execute(command)
            if result.status != ResultStatus.DONE:
                raise ConfigurationConflict("Konto nicht aktiviert; Seite neu laden und erneut prüfen.")
            self._rebase(state, cfg, account)
            self.runtime.app.iserv_runtime.request(cfg, keys)
            self.store.save(name, {"signature": signature, "status": "done"})
            self.runtime.app.logger.event("INFO", "iserv", "activation_requested", account=account.id)

    def _repeated(self, name, signature, actor):
        operation = self.store.load(name, {})
        if not operation:
            return False
        if not self.configuration.authorize(actor):
            raise PermissionError("Sitzung abgelaufen")
        if operation["signature"] != signature:
            raise ConfigurationConflict("Idempotenzschlüssel bereits verwendet.")
        if operation["status"] != "done":
            raise ConfigurationConflict("Aktivierung unterbrochen; Seite neu laden und gespeicherten Stand prüfen.")
        return True

    def _rebase(self, state, cfg, account):
        if state.patch:
            pending = dict(state.patch)
            if "iserv.accounts" in pending:
                pending["iserv.accounts"] = [item for item in pending["iserv.accounts"] if item["id"] != account.id]
                pending["iserv.accounts"].append(account.model_dump(mode="json"))
                if pending["iserv.accounts"] == cfg.iserv.model_dump(mode="json")["accounts"]:
                    del pending["iserv.accounts"]
            state.patch = pending
            state.base_hash = file_hash(self.configuration.directory / "config.yaml") if pending else ""
            state.version += 1
            self.runtime.setup._save(state)
