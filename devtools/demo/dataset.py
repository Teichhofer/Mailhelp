"""7.1 (D2): run the demo mails through the real processing path and export the prepared dataset.

``python -m devtools.demo.dataset --env PATH`` builds a throw-away Mailhelp configuration for the demo
persona, assembles the application exactly as ``mailhelp`` does (``build_application``), and feeds
the synthetic mails at the normal entry point (``Orchestrator.process``). Only the mailbox transport
is replaced; preparation, relevance, analysis, proposals and persistence run unchanged with the
configured models. Telegram and every write target stay disconnected, and the web server is never started: the run uses
the test mode and the duplicate check gets no target to compare with.

The result is written to ``src/mailhelp/defaults/demo/standard-v1``: the original messages, the
store files and a manifest with checksums, reference time, source commit and analysis fingerprint.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from mailhelp.app.composition import build_application
from mailhelp.config import load_all
from mailhelp.config.loader import _dotenv
from mailhelp.mailbox.imap import FetchedMail

from .mails import MAILS, ZONE, message

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "src" / "mailhelp" / "defaults" / "demo" / "standard-v1"
DATASET, SCHEMA_VERSION = "standard-v1", 1
REFERENCE_TIME = "2026-11-16T09:00:00+01:00"
PERSONA = ("Ich bin Alex Beispiel, Elternteil von Mia. Mia besucht die Klasse 4b der Grundschule am "
           "Lindenpark, spielt im TSV Beispielstadt und lernt Geige an der Musikschule Beispielstadt. "
           "Ich bin Mitglied im Förderverein der Schule und wohne im Lindenweg 5.")
TOPICS = [
    {"id": "schule", "name": "Schule und Klasse 4b", "enabled": True,
     "description": ("Nachrichten der Grundschule am Lindenpark, der Klassenleitung und des Sekretariats "
                     "zu Mias Klasse."),
     "examples": ["Elternabend", "Einverständniserklärung", "Ausflug", "Schulinformation"], "exclusions": []},
    {"id": "verein", "name": "Sportverein TSV", "enabled": True,
     "description": "Nachrichten des TSV Beispielstadt und seiner Jugendabteilung.",
     "examples": ["Training", "Workshop", "Material mitbringen"], "exclusions": ["Vereinswerbung Dritter"]},
    {"id": "musikschule", "name": "Musikschule", "enabled": True,
     "description": "Nachrichten der Musikschule Beispielstadt zu Mias Geigenunterricht.",
     "examples": ["Vorspiel", "Unterrichtstermin"], "exclusions": []},
    {"id": "foerderverein", "name": "Förderverein und Schulfeste", "enabled": True,
     "description": "Nachrichten des Fördervereins der Grundschule, etwa zu Basaren und Festen.",
     "examples": ["Adventsbasar", "Kuchenspende"], "exclusions": []},
]
# Placeholders for adapters the run builds but never uses (test mode, no target in the duplicate check).
PLACEHOLDERS = {
    "IMAP_USERNAME": "alex@familie-beispiel.example", "IMAP_PASSWORD": "demo-placeholder",
    "TODOIST_TOKEN": "demo-placeholder", "GOOGLE_OAUTH_CLIENT_ID": "demo-placeholder",
    "GOOGLE_OAUTH_CLIENT_SECRET": "demo-placeholder", "GOOGLE_OAUTH_REFRESH_TOKEN": "demo-placeholder",
    "MAILHELP_WEB_SECRET": "demo-placeholder-" + "x" * 32,
}
# Store files that belong to the run, not to the dataset.
RUN_FILES = ("llm-budget.json",)

Application = Callable[..., AbstractContextManager[Any]]


def configuration(directory: Path, api_key: str) -> None:
    """The demo persona as an ordinary Mailhelp configuration directory."""
    config = yaml.safe_load((ROOT / "config.example.yaml").read_text(encoding="utf-8"))
    config.update(test_mode=True, personal_info=PERSONA, data_directory="data", timezone="Europe/Berlin")
    config["telegram"]["enabled"] = False
    # Without Telegram the configuration requires the web interface; the run never starts its server.
    config["web"]["enabled"] = True
    config["imap"].update(host="imap.familie-beispiel.example", folders=["INBOX"], primary_folder="INBOX",
                          historical_start="2026-11-01T00:00:00+01:00")
    (directory / "config.yaml").write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
                                           encoding="utf-8")
    for name in ("prompts.yaml", "decisions_prompts.yaml"):
        shutil.copyfile(ROOT / name, directory / name)
    (directory / "topics.yaml").write_text(yaml.safe_dump({"topics": TOPICS}, allow_unicode=True, sort_keys=False),
                                           encoding="utf-8")
    (directory / "irrelevant_topics.yaml").write_text("topics: []\n", encoding="utf-8")
    shutil.copyfile(ROOT / "irrelevant-senders.example.json", directory / "irrelevant-senders.json")
    env = {**PLACEHOLDERS, "OPENROUTER_API_KEY": api_key}
    (directory / ".env").write_text("".join(f"{key}={value}\n" for key, value in env.items()), encoding="utf-8")


def fetched(account: str) -> Iterator[FetchedMail]:
    """The mails in the order they arrived, at the mailbox entry point."""
    ordered = sorted(MAILS, key=lambda mail: mail.sent)
    for uid, mail in enumerate(ordered, 1):
        received = datetime.strptime(mail.sent, "%Y-%m-%d %H:%M").replace(tzinfo=ZONE)
        yield FetchedMail("INBOX", 1, uid, message(mail), account, received)


def process(directory: Path, application: Application = build_application) -> tuple[Path, str]:
    """Process every mail; returns the store directory and the analysis fingerprint."""
    settings, secrets, topics, _irrelevant, prompts, fingerprint = load_all(directory, environ={})
    with application(settings, secrets, topics, prompts, fingerprint, directory) as app:
        app.orchestrator.precheck.writers = {}
        for mail in fetched(app.sources[0].reader.account_id):
            app.orchestrator.process(mail)
        return app.store.directory, app.orchestrator.config_fingerprint


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def export(store: Path, output: Path, fingerprint: str, commit: str, model: str) -> dict[str, Any]:
    """Write messages, store files and the manifest; an existing dataset is replaced as a whole."""
    staging = output.with_name(output.name + ".neu")
    shutil.rmtree(staging, ignore_errors=True)
    (staging / "mails").mkdir(parents=True)
    mails = []
    for mail in MAILS:
        raw = message(mail)
        (staging / "mails" / f"{mail.name}.eml").write_bytes(raw)
        mails.append({"name": mail.name, "message_id": f"<{mail.name}@demo.mailhelp.example>", "sha256": _digest(raw)})
    files = {}
    for path in sorted(store.rglob("*.json")):
        relative = path.relative_to(store).as_posix()
        if relative in RUN_FILES:
            continue
        target = staging / "state" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
        files[relative] = _digest(path.read_bytes())
    manifest = {"dataset": DATASET, "schema_version": SCHEMA_VERSION, "reference_time": REFERENCE_TIME,
                "timezone": "Europe/Berlin", "source_commit": commit, "analysis_fingerprint": fingerprint,
                "model": model, "mails": mails, "files": files}
    (staging / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    shutil.rmtree(output, ignore_errors=True)
    staging.rename(output)
    return manifest


def source_commit() -> str:
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                          check=True).stdout.strip()


def main(argv: list[str] | None = None, application: Application = build_application) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, required=True, help=".env mit OPENROUTER_API_KEY")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    api_key = _dotenv(args.env).get("OPENROUTER_API_KEY", "")
    if not api_key:
        print(f"OPENROUTER_API_KEY fehlt in {args.env}", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="mailhelp-demo-") as name:
        directory = Path(name)
        configuration(directory, api_key)
        store, fingerprint = process(directory, application)
        model = yaml.safe_load((directory / "prompts.yaml").read_text(encoding="utf-8"))["defaults"]["model"]
        manifest = export(store, args.output, fingerprint, source_commit(), model)
    print(f"Demo-Bestand geschrieben: {len(manifest['mails'])} Mails, {len(manifest['files'])} Zustandsdateien "
          f"in {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
