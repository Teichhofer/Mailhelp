"""Web application: routing behind the mandatory request checks."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from importlib.resources import files
from urllib.parse import parse_qs, urlsplit

from ..i18n import COOKIE, Locale, negotiate, tr, use_locale
from .http import Request, Response, cookie, rejected
from .pages import ASSET_URLS, PAGE_SCRIPTS

Route = Callable[..., Response]

# Application files served from the package; nothing else is readable.
STATIC_FILES = {
    "app.css": "text/css; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "open-list.js": "text/javascript; charset=utf-8",
    "dialogs.js": "text/javascript; charset=utf-8",
    "push.js": "text/javascript; charset=utf-8",
    "settings.js": "text/javascript; charset=utf-8",
    "help.js": "text/javascript; charset=utf-8",
    "setup.js": "text/javascript; charset=utf-8",
    "topics.js": "text/javascript; charset=utf-8",
    "learning.js": "text/javascript; charset=utf-8",
    "icon-192.png": "image/png",
    "icon-512.png": "image/png",
    "icon-maskable-512.png": "image/png",
}
# Served at the root: the service worker needs the root scope; none contains data.
ROOT_FILES = {
    "manifest.webmanifest": "application/manifest+json; charset=utf-8",
    "manifest-en.webmanifest": "application/manifest+json; charset=utf-8",
    "sw.js": "text/javascript; charset=utf-8",
    "offline.html": "text/html; charset=utf-8",
    "offline-en.html": "text/html; charset=utf-8",
}
# The files the service worker caches (SHELL in sw.js) and the placeholder for their version.
SHELL_FILES = ("offline.html", "offline-en.html", "app.css", "icon-192.png", "icon-512.png")
SHELL_VERSION = b"__SHELL_VERSION__"


def static_file(name: str) -> bytes:
    return files("mailhelp.web").joinpath("static", name).read_bytes()


class WebApp:
    """Dispatch checked requests to exactly matching routes."""

    def __init__(
        self, allowed_hosts: list[str], lan_port: int | None = None, *, asset_source: WebApp | None = None
    ) -> None:
        self.allowed_hosts, self.lan_port = frozenset(allowed_hosts), lan_port
        self.assets: dict[str, bytes]
        self.asset_urls: dict[str, str]
        # Read once at start: the pages come from the code loaded in this process, so
        # stylesheet and scripts must too, even if the files on disk change meanwhile
        # (update, branch switch of an editable install).
        if asset_source is not None:
            self.assets, self.asset_urls = asset_source.assets, asset_source.asset_urls
        else:
            self.assets = {name: static_file(name) for name in (*STATIC_FILES, *ROOT_FILES)}
            self.asset_urls = {name: f"/static/{name}?v={hashlib.sha256(self.assets[name]).hexdigest()[:16]}"
                               for name in ("app.css", *PAGE_SCRIPTS)}
            # Without a new cache name a cache-first worker kept serving an outdated stylesheet forever.
            version = hashlib.sha256(b"\0".join(self.assets[name] for name in SHELL_FILES)).hexdigest()[:16]
            self.assets["sw.js"] = self.assets["sw.js"].replace(SHELL_VERSION, version.encode())
        self._routes: list[tuple[str, re.Pattern[str], Route]] = []
        # 7.5: the configured language; 8.3.2: configured instances prefer it over Accept-Language.
        self.default_locale = Locale.DE
        self.prefer_configured_locale = False
        self.route("GET", "/health", self.health)
        self.route("GET", "/sprache", self.language)
        self.route("GET", r"/(?P<language>de|en)/", self.language)
        self.route("GET", r"/static/(?P<name>[a-z0-9.-]+)", self.static)
        self.route("GET", r"/(?P<name>manifest(?:-en)?\.webmanifest|sw\.js|offline(?:-en)?\.html)", self.root_file)

    def route(self, method: str, pattern: str, handler: Route) -> None:
        self._routes.append((method, re.compile(pattern), handler))

    def __call__(self, request: Request) -> Response:
        accept = None if self.prefer_configured_locale else request.header("accept-language")
        locale = negotiate(request.cookies().get(COOKIE), accept, self.default_locale)
        with use_locale(locale):
            return self.dispatch(request)

    def dispatch(self, request: Request) -> Response:
        rejection = rejected(request, self.allowed_hosts, self.lan_port)
        if rejection is not None:
            return rejection
        path_known = False
        for method, pattern, handler in self._routes:
            match = pattern.fullmatch(request.path)
            if match is None:
                continue
            if method != request.method:
                path_known = True
                continue
            token = ASSET_URLS.set(self.asset_urls)
            try:
                return handler(request, **match.groupdict())
            finally:
                ASSET_URLS.reset(token)
        if path_known:
            response = Response.text(405, tr("Methode nicht erlaubt."))
            response.headers["Allow"] = ", ".join(sorted(
                method for method, pattern, _ in self._routes if pattern.fullmatch(request.path)))
            return response
        return Response.text(404, tr("Nicht gefunden."))

    @staticmethod
    def language(request: Request, language: str | None = None) -> Response:
        """7.5: remember the chosen language in a cookie and return to the page it was chosen on."""
        try:
            if language is None:
                [language_choice] = parse_qs(
                    request.query, max_num_fields=1, keep_blank_values=True, strict_parsing=True
                ).get("wert", [])
            else:
                language_choice = language
            chosen = Locale(language_choice)
        except ValueError:
            chosen = None
        if chosen is None:
            return Response.text(400, tr("Ungültige Sprachwahl."))
        referer = urlsplit(request.header("referer") or "")
        local = language is None and referer.netloc == request.host and referer.path.startswith("/")
        back = referer.path if local else "/"
        target = back + (f"?{referer.query}" if referer.query and local else "")
        response = Response.redirect(target if not target.startswith("//") else "/")
        response.cookies.append(cookie(request, COOKIE, chosen.value, 31536000, http_only=False, same_site="Lax"))
        return response

    @staticmethod
    def health(_request: Request) -> Response:
        """Liveness only: no data, no authentication."""
        return Response.json(200, {"status": "ok"})

    def static(self, _request: Request, name: str) -> Response:
        if name not in STATIC_FILES:
            return Response.text(404, tr("Nicht gefunden."))
        return Response(200, self.assets[name], STATIC_FILES[name], cache="no-cache")

    def root_file(self, _request: Request, name: str) -> Response:
        return Response(200, self.assets[name], ROOT_FILES[name], cache="no-cache")


__all__ = ["ROOT_FILES", "SHELL_FILES", "STATIC_FILES", "WebApp", "static_file"]
