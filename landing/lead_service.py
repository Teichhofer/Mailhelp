"""Small, dependency-free interest form service. Static pages are served by nginx."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import tempfile
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

VERSION = "1.0.0"
CONSENT_VERSION = "2026-11-15-v1"
CONSENT = {
    "de": ("Ich möchte per E-Mail zum Start von Inboxstride kontaktiert werden. "
           "Ich kann meine Einwilligung jederzeit widerrufen."),
    "en": "I would like to be contacted by email when Inboxstride launches. I can withdraw my consent at any time.",
}
MESSAGES = {
    "de": {"success": "Danke! Dein Interesse ist vorgemerkt.",
           "invalid": "Bitte gib eine gültige E-Mail-Adresse ein und bestätige deine Einwilligung.",
           "error": "Das hat gerade nicht geklappt. Bitte versuche es später erneut.", "back": "Zurück zur Anmeldung"},
    "en": {"success": "Thank you! Your interest has been registered.",
           "invalid": "Please enter a valid email address and confirm your consent.",
           "error": "Something went wrong. Please try again later.", "back": "Back to the form"},
}


DOMAIN = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+"


def normalize_email(value: str) -> str:
    value = value.strip()
    local, separator, domain = value.rpartition("@")
    domain = domain.encode("idna").decode("ascii").lower()
    if (not separator or len(local + "@" + domain) > 254 or len(local) > 64
            or not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+", local)
            or local.startswith(".") or local.endswith(".") or ".." in local
            or not re.fullmatch(DOMAIN, domain)):
        raise ValueError("invalid_email")
    return local.casefold() + "@" + domain


class LeadStore:
    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def add(self, email: str, language: str) -> None:
        target = self.directory / (hashlib.sha256(email.encode()).hexdigest() + ".json")
        with self.lock:
            if target.exists():
                return
            record = {"email": email, "created_at": datetime.now(UTC).isoformat(), "language": language,
                      "consent_version": CONSENT_VERSION, "consent_text": CONSENT[language],
                      "purpose": "inboxstride_launch_contact", "address_verified": False}
            descriptor, name = tempfile.mkstemp(prefix=".pending-", dir=self.directory)
            pending = Path(name)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    json.dump(record, stream, ensure_ascii=False, indent=2)
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(pending, target)
            finally:
                pending.unlink(missing_ok=True)

    def records(self) -> list[tuple[Path, dict]]:
        result = []
        for path in sorted(self.directory.glob("*.json")):
            if path.is_symlink():
                raise ValueError("invalid_record")
            record = json.loads(path.read_text(encoding="utf-8"))
            expected = hashlib.sha256(normalize_email(record["email"]).encode()).hexdigest() + ".json"
            if path.name != expected:
                raise ValueError("invalid_record")
            result.append((path, record))
        return result

    def prune(self, days: int, now: datetime) -> int:
        cutoff = now - timedelta(days=days)
        with self.lock:
            expired = [path for path, record in self.records() if datetime.fromisoformat(record["created_at"]) < cutoff]
            for path in expired:
                path.unlink(missing_ok=True)
        return len(expired)

    def remove(self, email: str) -> None:
        target = self.directory / (hashlib.sha256(email.encode()).hexdigest() + ".json")
        with self.lock:
            target.unlink(missing_ok=True)


class LeadServer(ThreadingHTTPServer):
    def __init__(self, address, store: LeadStore, origins: set[str]):
        self.store, self.origins = store, origins
        self.next_cleanup = datetime.now(UTC)
        super().__init__(address, LeadHandler)

    def service_actions(self):
        now = datetime.now(UTC)
        if now >= self.next_cleanup:
            self.next_cleanup = now + timedelta(days=1)
            try:
                self.store.prune(365, now)
            except (OSError, ValueError):
                print("cleanup_failed", flush=True)


class LeadHandler(BaseHTTPRequestHandler):
    server: LeadServer

    def log_message(self, format, *args):
        """Request bodies, addresses, cookies and client IPs never enter logs."""

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def respond(self, status: int, key: str, language: str = "de", json_only: bool = False):
        message = MESSAGES[language][key]
        wants_json = json_only or "application/json" in self.headers.get("Accept", "")
        if status == 200 and not wants_json:
            self.send_response(303)
            self.send_header("Location", "/en/thanks/" if language == "en" else "/danke/")
            body = b""
        else:
            self.send_response(status)
            if wants_json:
                body = json.dumps({"ok": status == 200, "message": message}, ensure_ascii=False).encode()
                self.send_header("Content-Type", "application/json; charset=utf-8")
            else:
                back = "/en/#interest" if language == "en" else "/#interesse"
                body = (f'<!doctype html><html lang="{language}"><meta charset="utf-8">'
                        '<meta name="viewport" content="width=device-width,initial-scale=1">'
                        '<link rel="stylesheet" href="/assets/site.css"><title>Inboxstride</title>'
                        f'<main class="legal"><h1>{html.escape(message)}</h1>'
                        f'<a href="{back}">{MESSAGES[language]["back"]}</a></main></html>').encode()
                self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self.respond(200, "success", json_only=True)
        else:
            self.respond(404, "error")

    def do_POST(self):
        if self.path != "/api/interest":
            self.respond(404, "error")
            return
        if self.headers.get("Origin") not in self.server.origins:
            self.respond(403, "error")
            return
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/x-www-form-urlencoded":
            self.respond(415, "invalid")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4096:
                self.respond(413, "invalid")
                return
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError("incomplete_body")
            fields = parse_qs(raw.decode("utf-8"), max_num_fields=8, keep_blank_values=True, errors="strict")
            if any(len(values) != 1 for values in fields.values()):
                raise ValueError("duplicate_field")
        except (ValueError, OSError):
            self.respond(400, "invalid")
            return
        language = "en" if fields.get("lang") == ["en"] else "de"
        if fields.get("website", [""])[0]:
            self.respond(200, "success", language)
            return
        try:
            email = normalize_email(fields.get("email", [""])[0])
            if fields.get("consent") != ["yes"]:
                raise ValueError("consent_required")
        except ValueError:
            self.respond(400, "invalid", language)
            return
        try:
            self.server.store.add(email, language)
        except OSError:
            self.respond(503, "error", language)
            return
        self.respond(200, "success", language)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["serve", "export", "prune", "delete"])
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8877)
    parser.add_argument("--email", help="Address to delete with the delete command")
    parser.add_argument("--allow-origin", action="append", default=["https://inboxstride.de", "https://www.inboxstride.de"])
    args = parser.parse_args(argv)
    store = LeadStore(args.data_dir)
    if args.command == "export":
        for _path, record in store.records():
            print(json.dumps(record, ensure_ascii=False))
    elif args.command == "prune":
        print(json.dumps({"expired_records_removed": store.prune(365, datetime.now(UTC))}))
    elif args.command == "delete":
        if not args.email:
            parser.error("delete requires --email")
        store.remove(normalize_email(args.email))
        print(json.dumps({"deleted": True}))
    else:
        with LeadServer(("127.0.0.1", args.port), store, set(args.allow_origin)) as server:
            server.serve_forever(poll_interval=1)


if __name__ == "__main__":
    main()
