"""Names of the per-item JSON state files.

This module is the only place that knows how a state name is built.  The
patterns are part of the stored data: changing one would hide existing state
after an upgrade, so they stay byte-identical across releases.
"""
from __future__ import annotations

from typing import Protocol

MAIL_PREFIX = "mail-"
MAIL_RUN_PREFIX = "mail-run-"
PROPOSAL_PREFIX = "proposal-"
CLARIFICATION_PREFIX = "clarification-"
DRAFT_PREFIX = "draft-"


class NamedStore(Protocol):
    def names(self, prefix: str = "") -> list[str]: ...


def mail(mail_id: str) -> str:
    return f"{MAIL_PREFIX}{mail_id}"


def mail_run(account_id: str) -> str:
    return f"{MAIL_RUN_PREFIX}{account_id}"


def draft(mail_id: str) -> str:
    return f"{DRAFT_PREFIX}{mail_id}"


def proposal(mail_id: str, proposal_id: str, version: int | str | None = None) -> str:
    """The current proposal, or with *version* its immutable snapshot."""
    name = f"{PROPOSAL_PREFIX}{mail_id}-{proposal_id}"
    return name if version is None else f"{name}-v{version}"


def proposals_of(mail_id: str) -> str:
    """Prefix of every current proposal and snapshot of one mail."""
    return f"{PROPOSAL_PREFIX}{mail_id}-"


def clarification(mail_id: str, proposal_id: str, version: int | str) -> str:
    return f"{CLARIFICATION_PREFIX}{mail_id}-{proposal_id}-v{version}"


def is_mail_state(name: str) -> bool:
    """``mail-<id>`` but not the ``mail-run-<account>`` queue that shares the prefix."""
    return name.startswith(MAIL_PREFIX) and not name.startswith(MAIL_RUN_PREFIX)


def mail_state_names(store: NamedStore) -> list[str]:
    """Return only per-mail state names, excluding the ``mail-run-*`` queue."""
    return [name for name in store.names(MAIL_PREFIX) if is_mail_state(name)]
