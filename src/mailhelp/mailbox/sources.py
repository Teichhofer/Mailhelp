"""Mail sources and their labels, shared by the assembly and the activation of new mailboxes (7.0, R3)."""
from __future__ import annotations

from collections.abc import Callable
from contextlib import ExitStack
from typing import Any

from .. import state_names
from ..config import Secrets, Settings
from ..domain.mail import MailState
from ..persistence.storage import JsonStore
from . import iserv
from .mailbox_run import MailboxSource


def mailbox_labels(store: JsonStore, sources: list[MailboxSource],
                    further: dict[str, str] | None = None) -> Callable[[Any], str]:
    """The label of the mailbox (or IServ account) a proposal's mail came from (3.1)."""
    labels = {source.account_id: source.mailbox.label for source in sources} | (further or {})

    def label(proposal: Any) -> str:
        mail = store.peek_model(state_names.mail(proposal.source_mail_id), MailState)
        return labels.get(mail.imap.account_id, "Entferntes Postfach") if mail is not None else ""
    return label


def build_iserv_sources(settings: Settings, secrets: Secrets, stack: ExitStack) -> list[Any]:
    """One reader per enabled IServ account (3.3.7); it signs in on first use, not here."""
    result = []
    for account in settings.iserv.enabled_accounts():
        # Looked up at call time: the module attribute is the replaceable reader.
        reader = iserv.IServReader(account, secrets.iserv[account.id], settings.timezone,
                                   settings.limits.max_mail_bytes,
                             max_attachment_bytes=settings.limits.max_attachment_bytes)
        stack.callback(reader.close)
        mailbox = settings.imap.mailbox(account.mailbox)
        assert mailbox is not None  # Settings validates that the mailbox is enabled
        result.append(iserv.IServSource(account, reader, account.historical_start or mailbox.historical_start))
    return result
