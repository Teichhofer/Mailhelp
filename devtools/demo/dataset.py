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
import uuid
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
from mailhelp.review.commands import CommandKind, CommandSource, ReviewCommand

from .mails import MAILS, ZONE, DemoMail, message

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
# Prepared answers (Planung 7.1, 6.2): the demo replays what the real answer path produced for them.
ANSWERS = {
    "07-vorspiel-ohne-uhrzeit": ("Um 16:00 Uhr, Dauer etwa eine Stunde.",),
    "03-workshop-material": ("Samstag, 21. November, von 10:00 bis 13:00 Uhr.",),
    "04-adventsbasar": ("Ja, ich backe einen Kuchen und melde ihn über das Formular an.",),
}
REVISION_METHODS = ("interpret_telegram_answer", "clarify_telegram_answer", "revise_proposal")

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


def process(directory: Path, application: Application = build_application
            ) -> tuple[Path, str, list[dict[str, Any]]]:
    """Process every mail, then answer the prepared questions through the dialog.

    Returns the store directory as it was before any answer, the analysis fingerprint and the recorded
    calls of the revision service, which the demo replays for exactly these answers.
    """
    settings, secrets, topics, _irrelevant, prompts, fingerprint = load_all(directory, environ={})
    with application(settings, secrets, topics, prompts, fingerprint, directory) as app:
        app.orchestrator.precheck.writers = {}
        for mail in fetched(app.sources[0].reader.account_id):
            app.orchestrator.process(mail)
        base = directory / "basis"
        shutil.copytree(app.store.directory, base, ignore=shutil.ignore_patterns(".lock"))
        recorded = answer(app)
        return base, app.orchestrator.config_fingerprint, recorded


def _recording(analyzer: Any, recorded: list[dict[str, Any]]) -> None:
    for name in REVISION_METHODS:
        method = getattr(analyzer, name)

        def call(*args: Any, _name: str = name, _method: Callable[..., Any] = method, **kwargs: Any) -> Any:
            call_id, result = _method(*args, **kwargs)
            subject = args[0] if _name != "clarify_telegram_answer" else None
            recorded.append({"method": _name,
                             "proposal": None if subject is None else [subject.source_mail_id, subject.id,
                                                                       subject.version],
                             "arguments": [arg for arg in args if isinstance(arg, str)],
                             "result": result.model_dump(mode="json")})
            return call_id, result
        setattr(analyzer, name, call)


def answer(app: Any) -> list[dict[str, Any]]:
    """Send each prepared answer as a web command and let the real dialog run until it settles."""
    recorded: list[dict[str, Any]] = []
    _recording(app.analyzer, recorded)
    app.dialog.review.web_authorizer = lambda actor: True
    names = {message_id(mail): mail.name for mail in MAILS}
    for state in app.store.directory.glob("mail-*.json"):
        data = json.loads(state.read_text(encoding="utf-8"))
        name = names.get(((data.get("mail") or {}).get("headers") or {}).get("message_id", ""))
        for text in ANSWERS.get(name or "", ()):
            for item in data.get("proposals", []):
                if item["status"] == "needs_clarification":
                    _submit(app, data["id"], item, text)
    return recorded


def _submit(app: Any, mail_id: str, item: dict[str, Any], text: str) -> None:
    current = app.dialog.repository.load_current(mail_id, item["id"])
    command = ReviewCommand(kind=CommandKind.ANSWER, source=CommandSource.WEB, actor="web:demo-erzeugung",
                            mail_id=mail_id, proposal_id=item["id"], version=current.version,
                            idempotency_key=uuid.uuid4().hex, text=text)
    app.dialog.commands.submit(command)
    for _ in range(6):
        app.dialog.poll_once()


def message_id(mail: DemoMail) -> str:
    return f"<{mail.name}@demo.mailhelp.example>"


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def export(store: Path, output: Path, fingerprint: str, commit: str, model: str,
           answers: list[dict[str, Any]]) -> dict[str, Any]:
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
    recorded = (json.dumps(answers, indent=1, ensure_ascii=False) + "\n").encode("utf-8")
    (staging / "answers.json").write_bytes(recorded)
    manifest = {"dataset": DATASET, "schema_version": SCHEMA_VERSION, "reference_time": REFERENCE_TIME,
                "timezone": "Europe/Berlin", "source_commit": commit, "analysis_fingerprint": fingerprint,
                "model": model, "mails": mails, "files": files, "answers": _digest(recorded)}
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
        store, fingerprint, answers = process(directory, application)
        model = yaml.safe_load((directory / "prompts.yaml").read_text(encoding="utf-8"))["defaults"]["model"]
        manifest = export(store, args.output, fingerprint, source_commit(), model, answers)
    print(f"Demo-Bestand geschrieben: {len(manifest['mails'])} Mails, {len(manifest['files'])} Zustandsdateien "
          f"in {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
