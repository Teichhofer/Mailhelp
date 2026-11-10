"""5.3 (H7): the local reader of the packaged help sections, also without the help chat."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..helpdocs import HelpBase, HelpUnavailable, load
from .auth import WebSession
from .http import Request, Response
from .pages import e, layout, notice

if TYPE_CHECKING:
    from .site import MailhelpSite


class HelpSite:
    def __init__(self, site: MailhelpSite):
        self.site = site
        self._base: HelpBase | None = None
        # The help chat (H9); without it the documentation stays readable.
        self.chat: Any = None
        site.app.route("GET", "/hilfe/dokumentation", site.signed_in(self.index))
        site.app.route("GET", r"/hilfe/dokumentation/(?P<section>[a-z0-9-]{1,80}/[a-z0-9-]{1,160})",
                       site.signed_in(self.section))

    def base(self) -> HelpBase:
        """The packaged help, loaded once; an unusable resource raises HelpUnavailable."""
        if self._base is None:
            self._base = load()
        return self._base

    def _unavailable(self) -> Response:
        return Response.html(503, layout("Hilfe", '<h1>Hilfe</h1>' + notice(
            "Die mitgelieferte Dokumentation ist nicht verfügbar oder gehört zu einer anderen Version. "
            "Einstellungen und Suche funktionieren weiterhin.", "warn")))

    def index(self, request: Request, session: WebSession) -> Response:
        try:
            base = self.base()
        except HelpUnavailable:
            return self._unavailable()
        groups: dict[str, list[str]] = {}
        for item in base.sections:
            label = " › ".join(item.path[1:]) or item.title
            groups.setdefault(item.path[0], []).append(
                f'<li><a href="/hilfe/dokumentation/{e(item.id)}">{e(label)}</a></li>')
        body = "".join(f"<section><h2>{e(title)}</h2><ul>{''.join(links)}</ul></section>"
                       for title, links in groups.items())
        return Response.html(200, layout("Hilfe", f'<h1>Hilfe und Dokumentation</h1>{body}'))

    def section(self, request: Request, session: WebSession, section: str) -> Response:
        try:
            base = self.base()
        except HelpUnavailable:
            return self._unavailable()
        item = base.get(section)
        if item is None:
            return Response.html(404, layout("Hilfe", "<h1>Hilfe</h1>" + notice(
                "Diesen Abschnitt gibt es nicht.", "warn")))
        trail = " › ".join(item.path)
        return Response.html(200, layout(item.title, (
            f'<p class="eyebrow">{e(trail)}</p><h1>{e(item.title)}</h1>'
            f'<pre class="help-text">{e(item.text)}</pre>'
            f'<p class="meta">Quelle: {e(item.source)} · <a href="/hilfe/dokumentation">Alle Abschnitte</a></p>')))
