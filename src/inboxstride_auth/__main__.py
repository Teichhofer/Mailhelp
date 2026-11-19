"""Operator commands of the central OAuth service: ``python -m inboxstride_auth <command>``.

Paths come from the environment, so no secret is ever part of a command line or a log:
``INBOXSTRIDE_AUTH_STATE`` (state directory), ``INBOXSTRIDE_AUTH_KEY`` (secret key file outside it),
``INBOXSTRIDE_AUTH_LOG`` (JSONL event log), ``INBOXSTRIDE_AUTH_PUBLIC`` / ``INBOXSTRIDE_AUTH_INTERNAL``
(``host:port``) and ``INBOXSTRIDE_AUTH_TLS_CERT`` / ``_TLS_KEY`` / ``_TLS_CA`` for the internal mTLS side.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .ca import create_ca, fingerprint, issue
from .google import Client, GoogleTokens
from .http_api import serve, server_context
from .models import AuthState, Instance
from .secret_store import SecretStore, create_key
from .service import AuthService, register_instance
from .state_file import StateFile


def _env(name: str, environ: dict[str, str]) -> str:
    value = environ.get(name, "")
    if not value:
        raise SystemExit(f"{name} fehlt")
    return value


def _address(value: str) -> tuple[str, int]:
    host, _, port = value.rpartition(":")
    return host, int(port)


def event_log(path: Path) -> Callable[[str, dict[str, Any]], None]:
    """Content-free JSONL events (state changes and safe reasons only)."""
    lock = threading.Lock()

    def write(event: str, context: dict[str, Any]) -> None:
        record = {"timestamp": datetime.now(UTC).isoformat(), "event": event, **context}
        with lock, path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    return write


def build(environ: dict[str, str]) -> AuthService:
    state_dir = Path(_env("INBOXSTRIDE_AUTH_STATE", environ))
    store = SecretStore(state_dir, Path(_env("INBOXSTRIDE_AUTH_KEY", environ)))
    client_id, client_secret = store.get("client:id"), store.get("client:secret")
    if not client_id or not client_secret:
        raise SystemExit("Google-Client fehlt; zuerst 'set-client' ausführen")
    return AuthService(StateFile(state_dir), store, GoogleTokens(Client(client_id, client_secret)))


def set_client(environ: dict[str, str], client_file: Path) -> int:
    """Take client id and secret from Google's JSON file; a new client invalidates open sign-ins."""
    data = json.loads(client_file.read_text(encoding="utf-8")).get("web", {})
    if not data.get("client_id") or not data.get("client_secret"):
        raise SystemExit("Datei enthält keinen Webanwendungsclient")
    state_dir = Path(_env("INBOXSTRIDE_AUTH_STATE", environ))
    store = SecretStore(state_dir, Path(_env("INBOXSTRIDE_AUTH_KEY", environ)))
    store.put("client:id", data["client_id"])
    store.put("client:secret", data["client_secret"])

    def change(state: AuthState) -> AuthState:
        return state.model_copy(update={"client_revision": state.client_revision + 1})
    return StateFile(state_dir).update(change).client_revision


def main(argv: Sequence[str] | None = None, environ: dict[str, str] | None = None,
         wait: Callable[[], object] | None = None) -> int:
    environ = dict(os.environ) if environ is None else environ
    parser = argparse.ArgumentParser(prog="python -m inboxstride_auth")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("create-key", help="Schlüsseldatei anlegen (INBOXSTRIDE_AUTH_KEY)")
    ca = commands.add_parser("ca-init", help="Interne CA anlegen")
    ca.add_argument("directory", type=Path)
    cert = commands.add_parser("issue", help="Server- oder Instanzzertifikat ausstellen")
    cert.add_argument("ca", type=Path)
    cert.add_argument("out", type=Path)
    cert.add_argument("name")
    cert.add_argument("--server", action="store_true")
    register = commands.add_parser("register", help="Instanz registrieren oder ersetzen")
    register.add_argument("id")
    register.add_argument("host")
    register.add_argument("certificate", type=Path)
    block = commands.add_parser("disable", help="Instanz sperren (widerruft ihr Zertifikat sofort)")
    block.add_argument("id")
    client = commands.add_parser("set-client", help="Google-Webanwendungsclient aus JSON übernehmen")
    client.add_argument("file", type=Path)
    commands.add_parser("sweep", help="Abgelaufene Aufträge beenden")
    commands.add_parser("serve", help="Öffentlichen Callback und interne mTLS-Schnittstelle starten")
    args = parser.parse_args(argv)
    if args.command == "create-key":
        create_key(Path(_env("INBOXSTRIDE_AUTH_KEY", environ)))
    elif args.command == "ca-init":
        print(create_ca(args.directory))
    elif args.command == "issue":
        print(issue(args.ca, args.out, args.name, server=args.server))
    elif args.command in {"register", "disable"}:
        states = StateFile(Path(_env("INBOXSTRIDE_AUTH_STATE", environ)))
        if args.command == "register":
            register_instance(states, Instance(id=args.id, host=args.host,
                                               certificate=fingerprint(args.certificate.read_bytes())))
        else:
            def disable(state: AuthState) -> AuthState:
                item = state.instances[args.id].model_copy(update={"enabled": False})
                return state.model_copy(update={"instances": {**state.instances, args.id: item}})
            states.update(disable)
    elif args.command == "set-client":
        print(f"Clientrevision {set_client(environ, args.file)}")
    elif args.command == "sweep":
        print(build(environ).sweep())
    else:
        service = build(environ)
        log = event_log(Path(_env("INBOXSTRIDE_AUTH_LOG", environ)))
        context = server_context(_env("INBOXSTRIDE_AUTH_TLS_CERT", environ), _env("INBOXSTRIDE_AUTH_TLS_KEY", environ),
                                 _env("INBOXSTRIDE_AUTH_TLS_CA", environ))
        servers = [serve(service, _address(_env("INBOXSTRIDE_AUTH_PUBLIC", environ)), log),
                   serve(service, _address(_env("INBOXSTRIDE_AUTH_INTERNAL", environ)), log, context)]
        log("service_started", {})
        try:
            (wait or threading.Event().wait)()
        finally:
            for server in servers:
                server.shutdown()
            log("service_stopped", {})
    return 0


if __name__ == "__main__":
    sys.exit(main())
