"""8.8.3 (Planung 8.8 AP3): notices shown at the top of every signed-in page.

The session guard fills :data:`PAGE_BANNERS` once per request; :func:`render_banners` puts them at the
start of ``main``. A banner's link goes through the same frame filter as every other link, so a customer
never sees a link to an operator route. Later uses: quota hints, maintenance, expiring connections.
"""

from __future__ import annotations

import html
from contextvars import ContextVar
from dataclasses import dataclass


def e(value: str) -> str:
    return html.escape(value, quote=True)


@dataclass(frozen=True)
class SystemBanner:
    id: str
    severity: str  # "info", "warn" or "error"
    text: str
    action_href: str = ""
    action_label: str = ""


PAGE_BANNERS: ContextVar[tuple[SystemBanner, ...]] = ContextVar("page_banners", default=())


def render_banners(banners: tuple[SystemBanner, ...]) -> str:
    """Trusted markup of the given banners; texts and links are escaped."""
    parts = []
    for banner in banners:
        role = "alert" if banner.severity == "error" else "status"
        action = (f' <a class="button small" href="{e(banner.action_href)}">{e(banner.action_label)}</a>'
                  if banner.action_href else "")
        parts.append(f'<p class="notice notice-{e(banner.severity)} system-banner" role="{role}" '
                     f'data-banner="{e(banner.id)}">{e(banner.text)}{action}</p>')
    return "".join(parts)


__all__ = ["PAGE_BANNERS", "SystemBanner", "render_banners"]
