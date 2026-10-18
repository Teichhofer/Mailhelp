"""One authenticated IServ activation, isolated from unrelated configuration drafts."""
from __future__ import annotations

from .config import Settings
from .connection_activation import ConnectionActivation


class IServActivation(ConnectionActivation):
    prefix, patch_key, area = "iserv-activation", "iserv.accounts", "iserv"

    def merged(self, saved, item):
        accounts = [account for account in saved.iserv.accounts if account.id != item.id] + [item]
        cfg = Settings.model_validate({**saved.model_dump(), "iserv": {"accounts": accounts}})
        # Only connections to mailboxes already available in this process can be hot-loaded.
        Settings.model_validate({**self.configuration.active.model_dump(), "iserv": cfg.iserv.model_dump()})
        return cfg

    def entries(self, cfg):
        return cfg.iserv.model_dump(mode="json")["accounts"]

    def credentials(self, keys):
        return keys.iserv

    def probe(self, cfg, item, keys):
        from .iserv import IServReader
        reader = IServReader(item, keys.iserv[item.id], cfg.timezone, cfg.limits.max_mail_bytes,
                             max_attachment_bytes=cfg.limits.max_attachment_bytes)
        try:
            reader.check_access()
        finally:
            reader.close()

    def request(self, cfg, keys):
        self.runtime.app.iserv_runtime.request(cfg, keys)
