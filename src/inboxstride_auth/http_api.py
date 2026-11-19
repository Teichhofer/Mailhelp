"""Public callback and internal mTLS API of the central OAuth service (Planung 8.0, sections 3, 4, 7).

``handle`` is a pure function of the request; the servers below only translate sockets. The
public side offers Google's callback and a content-free health answer, nothing else. The internal
side requires a client certificate; its fingerprint names the instance, and every request is
limited to that instance. Neither side writes codes, tokens or query strings to any log.
"""
from __future__ import annotations

import json
import ssl
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .service import AuthService, Refused

MAX_BODY = 16384
SECURITY = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'",
            "X-Frame-Options": "DENY"}
_PAGE = ("<!doctype html><html lang=\"de\"><meta charset=\"utf-8\"><title>Inboxstride</title>"
         "<body style=\"font-family:sans-serif;max-width:32rem;margin:3rem auto\"><h1>{title}</h1><p>{text}</p>")


@dataclass
class Answer:
    status: int
    body: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)


def _json(status: int, data: dict[str, Any]) -> Answer:
    return Answer(status, json.dumps(data).encode("utf-8"), {"Content-Type": "application/json"})


def _page(status: int, title: str, text: str) -> Answer:
    return Answer(status, _PAGE.format(title=title, text=text).encode("utf-8"),
                  {"Content-Type": "text/html; charset=utf-8"})


def public(service: AuthService, method: str, target: str, log: Callable[[str, dict[str, Any]], None]) -> Answer:
    """Google's return and the health check; any other path does not exist."""
    parts = urlsplit(target)
    if method == "GET" and parts.path == "/health":
        return _json(200, {"status": "ok"})
    if method != "GET" or parts.path != "/auth/google/callback":
        return _page(404, "Nicht gefunden", "Diese Adresse gibt es nicht.")
    query = parse_qs(parts.query, keep_blank_values=True, max_num_fields=10)
    if any(len(values) != 1 for values in query.values()) or "state" not in query:
        log("callback_refused", {"reason": "parameters"})
        return _page(400, "Anmeldung nicht möglich", "Die Rückmeldung von Google ist unvollständig.")
    try:
        redirect = service.callback(query["state"][0], query.get("code", [None])[0], query.get("error", [None])[0])
    except Refused as exc:
        log("callback_refused", {"reason": exc.code})
        return _page(400, "Anmeldung nicht mehr gültig",
                     "Bitte in deiner Inboxstride-Instanz erneut „Mit Google verbinden“ wählen.")
    log("callback_completed", {})
    return Answer(303, b"", {"Location": redirect})


_ROUTES = {"/intern/start", "/intern/redeem", "/intern/activate", "/intern/token", "/intern/disconnect",
           "/intern/connection"}


def internal(service: AuthService, method: str, path: str, body: bytes, peer: str | None,
             log: Callable[[str, dict[str, Any]], None]) -> Answer:
    """The instance named by the client certificate acts for itself only."""
    instance = next((item for item in service.state.read().instances.values()
                     if peer is not None and item.certificate == peer and item.enabled), None)
    if instance is None:
        log("internal_refused", {"reason": "certificate"})
        return _json(403, {"error": "unknown_certificate"})
    if method != "POST" or path not in _ROUTES:
        return _json(404, {"error": "not_found"})
    if len(body) > MAX_BODY:
        return _json(413, {"error": "too_large"})
    try:
        data = json.loads(body or b"{}")
        if not isinstance(data, dict):
            raise ValueError("object")
        answer = _call(service, instance.id, path, data)
    except Refused as exc:
        log("internal_refused", {"instance": instance.id, "route": path, "reason": exc.code})
        return _json(409, {"error": exc.code})
    except (ValueError, KeyError, TypeError):
        return _json(400, {"error": "invalid_request"})
    log("internal_completed", {"instance": instance.id, "route": path})
    return _json(200, answer)


def _call(service: AuthService, instance: str, path: str, data: dict[str, Any]) -> dict[str, Any]:
    if path == "/intern/start":
        job, url = service.start(instance, str(data["session"]), str(data["target"]), data["operation"],
                                 str(data["key"]))
        return {"job": job.id, "version": job.version, "url": url}
    if path == "/intern/redeem":
        job = service.redeem(instance, str(data["session"]), str(data["receipt"]))
        return {"job": job.id, "version": job.version, "connection": job.candidate, "target": job.target,
                "operation": job.operation}
    if path == "/intern/activate":
        connection = service.activate(instance, str(data["session"]), str(data["job"]), int(data["version"]))
        return {"connection": connection.id, "generation": connection.generation, "target": connection.target}
    if path == "/intern/token":
        token, valid = service.access_token(instance, str(data["connection"]))
        return {"access_token": token, "expires_in": valid}
    if path == "/intern/disconnect":
        service.disconnect(instance, str(data["connection"]))
        return {"status": "disconnected"}
    known = service.state.read().connections.get(str(data["connection"]))
    if known is None or known.instance != instance:
        raise Refused("unknown_connection")
    return {"status": known.status, "generation": known.generation, "target": known.target}


def server_context(certificate: str, key: str, ca: str) -> ssl.SSLContext:
    """TLS 1.2+ with a mandatory client certificate signed by the Inboxstride CA."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certificate, key)
    context.load_verify_locations(ca)
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def serve(service: AuthService, address: tuple[str, int], log: Callable[[str, dict[str, Any]], None],
          context: ssl.SSLContext | None = None) -> ThreadingHTTPServer:
    """A started server: public without *context*, internal (mTLS) with it."""
    from .ca import der_fingerprint

    class Handler(BaseHTTPRequestHandler):
        server_version = "Inboxstride"
        sys_version = ""

        def _send(self, answer: Answer) -> None:
            self.send_response(answer.status)
            for name, value in {**SECURITY, **answer.headers, "Content-Length": str(len(answer.body))}.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(answer.body)

        def do_GET(self) -> None:  # noqa: N802 - http.server naming
            if context is not None:
                self._send(_json(404, {"error": "not_found"}))
                return
            self._send(public(service, "GET", self.path, log))

        def do_POST(self) -> None:  # noqa: N802 - http.server naming
            if context is None:
                self._send(public(service, "POST", self.path, log))
                return
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(min(length, MAX_BODY + 1))
            peer = self.connection.getpeercert(binary_form=True)  # type: ignore[attr-defined]
            self._send(internal(service, "POST", urlsplit(self.path).path, body,
                                der_fingerprint(peer) if peer else None, log))

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            """Request lines contain OAuth codes and states; they are never written."""

    httpd = ThreadingHTTPServer(address, Handler)
    if context is not None:
        httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
    threading.Thread(target=httpd.serve_forever, name="inboxstride-auth", daemon=True).start()
    return httpd


__all__ = ["MAX_BODY", "SECURITY", "Answer", "internal", "public", "serve", "server_context"]
