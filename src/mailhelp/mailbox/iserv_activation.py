"""One authenticated IServ activation, isolated from unrelated configuration drafts."""
from __future__ import annotations

from typing import Any

from ..config import ImapCredentials, IServAccountSettings, Secrets, Settings
from . import iserv as iserv_module
from .connection_activation import ConnectionActivation


class IServActivation(ConnectionActivation[IServAccountSettings]):
    prefix, patch_key, area = "iserv-activation", "iserv.accounts", "iserv"

    def merged(self, saved: Settings, item: IServAccountSettings) -> Settings:
        accounts = [account for account in saved.iserv.accounts if account.id != item.id] + [item]
        cfg = Settings.model_validate({**saved.model_dump(), "iserv": {"accounts": accounts}})
        # Only connections to mailboxes already available in this process can be hot-loaded.
        Settings.model_validate({**self.configuration.active.model_dump(), "iserv": cfg.iserv.model_dump()})
        return cfg

    def entries(self, cfg: Settings) -> list[dict[str, Any]]:
        return cfg.iserv.model_dump(mode="json")["accounts"]

    def credentials(self, keys: Secrets) -> dict[int, ImapCredentials]:
        return keys.iserv

    def probe(self, cfg: Settings, item: IServAccountSettings, keys: Secrets) -> None:
        reader = iserv_module.IServReader(item, keys.iserv[item.id], cfg.timezone, cfg.limits.max_mail_bytes,
                             max_attachment_bytes=cfg.limits.max_attachment_bytes)
        try:
            reader.check_access()
        finally:
            reader.close()

    def request(self, cfg: Settings, keys: Secrets) -> None:
        self.runtime.app.iserv_runtime.request(cfg, keys)
