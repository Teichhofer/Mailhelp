"""Add an IMAP mailbox from one authenticated form: check, save and start it without restart (3.5)."""
from __future__ import annotations

from typing import Any

from ..config import ImapCredentials, MailboxSettings, Secrets, Settings, imap_secret_names
from .connection_activation import ActivationProblem, ConnectionActivation
from .imap import FolderNotReadable, account_id

# Folder names come from the server; only this many are listed in a message.
SHOWN_FOLDERS = 30


class MailboxActivation(ConnectionActivation[MailboxSettings]):
    prefix, patch_key, area = "mailbox-activation", "imap.mailboxes", "imap"

    def merged(self, saved: Settings, item: MailboxSettings) -> Settings:
        if saved.imap.mailbox(item.id) is not None:
            raise ActivationProblem(f"Postfach {item.id} ist bereits eingerichtet.")
        boxes = [box.model_dump(mode="json") for box in saved.imap.configured_mailboxes()]
        imap = {"batch_size": saved.imap.batch_size, "global_newest_first": saved.imap.global_newest_first,
                "mailboxes": [*boxes, item.model_dump(mode="json")]}
        return Settings.model_validate({**saved.model_dump(), "imap": imap})

    def entries(self, cfg: Settings) -> list[dict[str, Any]]:
        return [box.model_dump(mode="json") for box in cfg.imap.configured_mailboxes()]

    def credentials(self, keys: Secrets) -> dict[int, ImapCredentials]:
        return keys.imap

    def probe(self, cfg: Settings, item: MailboxSettings, keys: Secrets) -> None:
        # Late: against the layer direction, named in tests/unit/test_layers.py.
        from ..runtime.experience import _reader
        own = account_id(item.host, item.port, keys.imap[item.id].username)
        environment = self.runtime.environment()
        for other in cfg.imap.configured_mailboxes():
            user_name, _password_name = imap_secret_names(other, environment, cfg.imap.legacy_format)
            username = keys.imap[other.id].username if other.id in keys.imap else environment.get(user_name, "")
            if (other.id != item.id and username
                    and account_id(other.host, other.port, username) == own):
                raise ActivationProblem(f"Dieses Konto ist bereits als Postfach {other.id} eingerichtet.")
        required = list(dict.fromkeys([*item.folders, item.drafts_folder]))
        try:
            with _reader(cfg, keys, item) as reader:
                folders = [folder.name for folder in reader.list_folders()]
                missing = [folder for folder in required if folder not in folders]
                if missing:
                    shown = ", ".join(folders[:SHOWN_FOLDERS]) + (" …" if len(folders) > SHOWN_FOLDERS else "")
                    raise ActivationProblem(f"Ordner nicht gefunden: {', '.join(missing)}. "
                                            f"Vorhandene Ordner: {shown or 'keine'}.")
                reader.check_access(required)
        except ActivationProblem:
            raise
        except FolderNotReadable as exc:
            raise ActivationProblem(f"Ordner nicht lesbar: {exc.folder}.") from None
        except OSError:
            raise ActivationProblem("Server nicht erreichbar: IMAP-Server, Port und Verbindungsart prüfen.") from None
        except Exception:
            # Server answers are not shown; they are untrusted and may echo the entered user name.
            raise ActivationProblem("Anmeldung abgelehnt: Benutzername (oft die vollständige E-Mail-Adresse) "
                                    "und Passwort oder App-Passwort prüfen; IMAP muss beim Anbieter "
                                    "freigeschaltet sein.") from None

    def request(self, cfg: Settings, keys: Secrets) -> None:
        self.runtime.app.mailbox_runtime.request(cfg, keys)


class ReconnectActivation(MailboxActivation):
    """Replace one mailbox while preserving unrelated entries and policies."""
    def merged(self, saved: Settings, item: MailboxSettings) -> Settings:
        if saved.imap.mailbox(item.id) is None:
            return super().merged(saved, item)
        entries = [item.model_dump(mode="json") if box.id == item.id else box.model_dump(mode="json")
                   for box in saved.imap.configured_mailboxes()]
        imap = {"batch_size": saved.imap.batch_size, "global_newest_first": saved.imap.global_newest_first,
                "mailboxes": entries}
        return Settings.model_validate({**saved.model_dump(), "imap": imap})


__all__ = ["MailboxActivation", "ReconnectActivation"]
