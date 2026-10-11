"""Web application: routing behind the mandatory request checks."""

from __future__ import annotations

import re
from typing import Callable

from .http import Request, Response, rejected

Route = Callable[..., Response]


class WebApp:
    """Dispatch checked requests to exactly matching routes."""

    def __init__(self, allowed_hosts: list[str]):
        self.allowed_hosts = frozenset(allowed_hosts)
        self._routes: list[tuple[str, re.Pattern[str], Route]] = []
        self.route("GET", "/health", self.health)

    def route(self, method: str, pattern: str, handler: Route) -> None:
        self._routes.append((method, re.compile(pattern), handler))

    def __call__(self, request: Request) -> Response:
        rejection = rejected(request, self.allowed_hosts)
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
            return handler(request, **match.groupdict())
        if path_known:
            response = Response.text(405, "Methode nicht erlaubt.")
            response.headers["Allow"] = ", ".join(sorted(
                method for method, pattern, _ in self._routes if pattern.fullmatch(request.path)))
            return response
        return Response.text(404, "Nicht gefunden.")

    @staticmethod
    def health(_request: Request) -> Response:
        """Liveness only: no data, no authentication."""
        return Response.json(200, {"status": "ok"})


__all__ = ["WebApp"]
