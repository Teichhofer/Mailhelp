"""Standard-library HTTP server in a daemon thread.

The server translates sockets into :class:`~mailhelp.web.http.Request` values
and back; routing, authorization and rendering live in the web application.
A failing start (e.g. a port already in use) is reported to the caller and
never stops the mail processing.
"""

from __future__ import annotations

import socket
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Callable, Protocol

from .http import MAX_BODY_BYTES, STATUS_TEXT, Request, Response


class EventLogger(Protocol):
    def event(self, level: str, module: str, event: str, **fields: object) -> None: ...


Handler = Callable[[Request], Response]


class WebServerError(RuntimeError):
    """The web interface could not be started."""


# On Windows SO_REUSEADDR lets a second process bind the same port and
# silently share it; there an exclusive bind is used instead.
_EXCLUSIVE_BIND = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    exclusive_bind: int | None = _EXCLUSIVE_BIND
    allow_reuse_address = _EXCLUSIVE_BIND is None

    def __init__(self, address: tuple[str, int], handler: Handler, logger: EventLogger):
        self.app, self.logger = handler, logger
        super().__init__(address, _RequestHandler)

    def handle_error(self, request: object, client_address: object) -> None:
        """A browser closing a connection early is normal; log it without a traceback."""
        self.logger.event("DEBUG", "web", "connection_error",
                          error_class=type(sys.exc_info()[1]).__name__)

    def server_bind(self) -> None:
        if self.exclusive_bind is not None:
            self.socket.setsockopt(socket.SOL_SOCKET, self.exclusive_bind, 1)
        super().server_bind()


class _RequestHandler(BaseHTTPRequestHandler):
    server: _Server
    protocol_version = "HTTP/1.1"
    # A stalled client must not hold a thread forever.
    timeout = 15

    def do_GET(self) -> None:
        self._dispatch()

    def do_POST(self) -> None:
        self._dispatch()

    def do_PUT(self) -> None:
        self._dispatch()

    def do_DELETE(self) -> None:
        self._dispatch()

    def do_HEAD(self) -> None:
        self._dispatch()

    def do_OPTIONS(self) -> None:
        self._dispatch()

    def log_message(self, format: str, *args: object) -> None:
        """Silenced: requests are logged by the application without query strings."""

    def _dispatch(self) -> None:
        started = time.perf_counter()
        path, _, query = self.path.partition("?")
        headers = {name.lower(): value for name, value in self.headers.items()}
        response = self._read_body(headers)
        if response is None:
            body = self.rfile.read(int(headers.get("content-length") or 0))
            request = Request(self.command, path, headers, query, body)
            try:
                response = self.server.app(request)
            except Exception as exc:
                self.server.logger.event("ERROR", "web", "request_failed", method=self.command,
                                         error_class=type(exc).__name__)
                response = Response.text(500, "Interner Fehler.")
        self._send(response)
        self.server.logger.event("INFO", "web", "request", method=self.command,
                                 path=path[:200], status=response.status,
                                 duration_ms=round((time.perf_counter() - started) * 1000))

    def _read_body(self, headers: dict[str, str]) -> Response | None:
        """Refuse missing or oversized bodies before reading anything."""
        raw = headers.get("content-length")
        if raw is None:
            if self.command == "POST":
                return Response.text(411, "Content-Length fehlt.")
            return None
        if not raw.isdigit():
            return Response.text(400, "Ungültige Content-Length.")
        if int(raw) > MAX_BODY_BYTES:
            self.close_connection = True
            return Response.text(413, "Anfrage zu groß.")
        return None

    def _send(self, response: Response) -> None:
        self.send_response_only(response.status, STATUS_TEXT.get(response.status))
        for name, value in response.all_headers():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(response.body)


class WebServer:
    """Owns the listening socket and its thread."""

    def __init__(self, host: str, port: int, handler: Handler, logger: EventLogger):
        self.host, self.port, self.handler, self.logger = host, port, handler, logger
        self._server: _Server | None = None
        self._thread: Thread | None = None

    @property
    def address(self) -> tuple[str, int]:
        assert self._server is not None
        host, port = self._server.server_address[:2]
        return str(host), int(port)

    def start(self) -> None:
        try:
            self._server = _Server((self.host, self.port), self.handler, self.logger)
        except OSError as exc:
            raise WebServerError(
                f"Weboberfläche konnte nicht auf {self.host}:{self.port} starten "
                "(Port belegt oder Adresse nicht verfügbar)") from exc
        self._thread = Thread(target=self._server.serve_forever, name="web-server", daemon=True)
        self._thread.start()
        self.logger.event("INFO", "web", "server_started", host=self.host, port=self.address[1])

    def stop(self) -> None:
        server, self._server = self._server, None
        if server is None:
            return
        server.shutdown()
        server.server_close()
        assert self._thread is not None
        self._thread.join(timeout=5)
        self.logger.event("INFO", "web", "server_stopped")


__all__ = ["WebServer", "WebServerError"]
