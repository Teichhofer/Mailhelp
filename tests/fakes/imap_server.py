"""A tiny synthetic IMAP server on 127.0.0.1 for setup checks against real sockets (6.1.3).

It speaks just enough IMAP4rev1 for ImapReader: greeting, CAPABILITY, STARTTLS (refused),
LOGIN, LIST, EXAMINE and LOGOUT. Mode "silent" accepts connections but never greets.
"""
from __future__ import annotations

import socketserver
import threading
from dataclasses import dataclass, field

FOLDERS = ('(\\HasNoChildren) "/" INBOX', '(\\HasNoChildren \\Drafts) "/" "Entw&APw-rfe"')


@dataclass
class Behaviour:
    username: str = "user@example.test"
    password: str = "richtig"
    starttls: str = "refuse"   # "refuse": offered but answered with NO; "absent": not offered
    silent: bool = False
    commands: list[str] = field(default_factory=list)


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        behaviour: Behaviour = self.server.behaviour  # type: ignore[attr-defined]
        if behaviour.silent:
            self.rfile.readline()  # waits until the client gives up
            return
        self._send("* OK synthetic IMAP ready")
        while line := self.rfile.readline():
            tag, _, rest = line.decode("utf-8", "replace").strip().partition(" ")
            command, _, arguments = rest.partition(" ")
            command = command.upper()
            behaviour.commands.append(command)
            if command == "CAPABILITY":
                extra = " STARTTLS" if behaviour.starttls == "refuse" else ""
                self._send(f"* CAPABILITY IMAP4rev1{extra}")
                self._send(f"{tag} OK done")
            elif command == "STARTTLS":
                self._send(f"{tag} NO not now")
            elif command == "LOGIN":
                user, _, password = arguments.partition(" ")
                accepted = (user.strip('"'), password.strip('"')) == (behaviour.username, behaviour.password)
                self._send(f"{tag} OK logged in" if accepted else f"{tag} NO [AUTHENTICATIONFAILED] no")
            elif command == "LIST":
                for item in FOLDERS:
                    self._send(f"* LIST {item}")
                self._send(f"{tag} OK done")
            elif command in {"EXAMINE", "SELECT"}:
                if arguments.strip('"') == "INBOX":
                    self._send("* 0 EXISTS")
                    self._send("* OK [UIDVALIDITY 1] ok")
                    self._send(f"{tag} OK [READ-ONLY] done")
                else:
                    self._send(f"{tag} NO no such mailbox")
            elif command == "LOGOUT":
                self._send("* BYE bye")
                self._send(f"{tag} OK done")
                return
            else:
                self._send(f"{tag} BAD unknown")

    def _send(self, text: str) -> None:
        self.wfile.write(text.encode("utf-8") + b"\r\n")


class SyntheticImapServer:
    def __init__(self, behaviour: Behaviour | None = None):
        self.behaviour = behaviour or Behaviour()
        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Handler)
        self.server.daemon_threads = True
        self.server.behaviour = self.behaviour  # type: ignore[attr-defined]
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> SyntheticImapServer:
        self.thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.server.shutdown()
        self.server.server_close()


def closed_port() -> int:
    """A local port with nothing listening."""
    import socket
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]
