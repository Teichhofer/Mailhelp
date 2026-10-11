"""Minimal HTTP request/response model with the mandatory security checks.

The routing core works on plain values, so every rule can be tested in-process
without sockets.  ``server.py`` only translates between these values and the
standard library's HTTP server.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import parse_qs

MAX_BODY_BYTES = 16 * 1024
ALLOWED_METHODS = frozenset({"GET", "POST"})
# No inline scripts or styles; everything is served by Mailhelp itself.
CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'self'", "script-src 'self'", "style-src 'self'", "img-src 'self'",
    "connect-src 'self'", "manifest-src 'self'", "worker-src 'self'", "font-src 'self'",
    "object-src 'none'", "base-uri 'none'", "form-action 'self'", "frame-ancestors 'none'",
])
SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
}
STATUS_TEXT = {
    200: "OK", 202: "Accepted", 303: "See Other", 400: "Bad Request", 403: "Forbidden",
    404: "Not Found", 405: "Method Not Allowed", 409: "Conflict", 411: "Length Required",
    413: "Content Too Large", 415: "Unsupported Media Type", 421: "Misdirected Request",
    422: "Unprocessable Content", 429: "Too Many Requests", 500: "Internal Server Error",
    503: "Service Unavailable",
}


@dataclass(frozen=True)
class Request:
    method: str
    path: str
    headers: dict[str, str] = field(default_factory=dict)
    query: str = ""
    body: bytes = b""

    def header(self, name: str) -> str | None:
        return self.headers.get(name.lower())

    @property
    def host(self) -> str:
        return (self.header("host") or "").strip().lower()

    def cookies(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for part in (self.header("cookie") or "").split(";"):
            name, separator, value = part.strip().partition("=")
            if separator and name and name not in result:
                result[name] = value
        return result

    def form(self) -> dict[str, str]:
        """URL-encoded form fields; a repeated field keeps its first value."""
        values = parse_qs(self.body.decode("utf-8", errors="strict"), keep_blank_values=True,
                          strict_parsing=False, max_num_fields=20)
        return {name: items[0] for name, items in values.items()}

    def wants_json(self) -> bool:
        return "application/json" in (self.header("accept") or "")


@dataclass
class Response:
    status: int
    body: bytes = b""
    content_type: str = "text/plain; charset=utf-8"
    headers: dict[str, str] = field(default_factory=dict)
    cookies: list[str] = field(default_factory=list)
    # Static application files may be revalidated; data is never stored.
    cache: str = "no-store"
    after_send: Callable[[], None] | None = None

    @classmethod
    def text(cls, status: int, text: str) -> "Response":
        return cls(status, text.encode("utf-8"))

    @classmethod
    def html(cls, status: int, html: str) -> "Response":
        return cls(status, html.encode("utf-8"), "text/html; charset=utf-8")

    @classmethod
    def json(cls, status: int, value: Any) -> "Response":
        return cls(status, json.dumps(value, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    @classmethod
    def redirect(cls, location: str) -> "Response":
        if not location.startswith("/") or location.startswith("//"):
            raise ValueError("Nur interne Weiterleitungen sind erlaubt")
        return cls(303, headers={"Location": location})

    def all_headers(self) -> list[tuple[str, str]]:
        headers = [("Content-Type", self.content_type), ("Content-Length", str(len(self.body))),
                   ("Cache-Control", self.cache), *SECURITY_HEADERS.items(), *self.headers.items()]
        headers += [("Set-Cookie", cookie) for cookie in self.cookies]
        return headers


def rejected(request: Request, allowed_hosts: frozenset[str],
             lan_port: int | None = None) -> Response | None:
    """Checks that precede every route; None if the request may proceed.

    With *lan_port*, the PC's private IP addresses with that port are accepted too.
    """
    from .network import lan_host

    if request.host not in allowed_hosts and not (
            lan_port is not None and lan_host(request.host, lan_port)):
        # DNS rebinding: a foreign name resolving to 127.0.0.1 is refused.
        return Response.text(421, "Unbekannter Host.")
    if request.method not in ALLOWED_METHODS:
        response = Response.text(405, "Methode nicht erlaubt.")
        response.headers["Allow"] = "GET, POST"
        return response
    if (not request.path.startswith("/") or "\\" in request.path or "//" in request.path
            or any(part in {".", ".."} for part in request.path.split("/"))):
        return Response.text(400, "Ungültiger Pfad.")
    return None


__all__ = ["ALLOWED_METHODS", "CONTENT_SECURITY_POLICY", "MAX_BODY_BYTES", "Request",
           "Response", "SECURITY_HEADERS", "STATUS_TEXT", "rejected"]
