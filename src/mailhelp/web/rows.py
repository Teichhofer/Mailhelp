"""6.2.7: one entry of a dense list – used by mails, history and reconciliation."""
from __future__ import annotations

from .pages import e


def row(href: str, title: str, meta: str, badges: str, detail: str = "") -> str:
    """Title link, one meta line and badges; *badges* and *detail* are trusted markup."""
    return (f'<li class="row-item"><div class="row-main"><a class="row-title" href="{e(href)}">{e(title)}</a>'
            f'<span class="row-meta">{e(meta)}</span></div><div class="row-badges">{badges}</div>{detail}</li>')


__all__ = ["row"]
