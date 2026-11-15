"""7.0: every stored state reads and writes back unchanged, before and after the refactoring.

``python -m devtools.state_roundtrip <state directory>`` copies the directory into a temporary folder,
validates each file with its model (migrations apply in memory only) and serializes it exactly like
the store would. The report contains only counts and SHA-256 digests, never content; the same
digest before and after a change proves identical reading and writing of the whole inventory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from mailhelp.domain.proposal import Proposal
from mailhelp.persistence.archive import AnalysisSnapshot, HistorySnapshot
from mailhelp.persistence.schemas import (
    ActionLedger,
    ActivityReport,
    DuplicateIndex,
    ImapCheckpoint,
    IrrelevantSenders,
    MailRunState,
    MailState,
    NotificationQueue,
    ProposalClarificationState,
    ProposalMatchCache,
    ProposalMergeJournal,
    ProposalRelation,
    SetupState,
    TelegramDialogState,
    TelegramOffset,
    TelegramOutboxState,
    WriteVerification,
)
from mailhelp.persistence.storage import CorruptState, JsonStore
from mailhelp.review.inbox import CommandInboxState

# Longest prefix first: "mail-run-" files are no mails.
_MODELS: dict[str, type[BaseModel]] = {
    "mail-": MailState, "mail-run-": MailRunState, "proposal-": Proposal, "history-": HistorySnapshot,
    "analysis-": AnalysisSnapshot, "imap-": ImapCheckpoint, "clarification-": ProposalClarificationState,
    "reconciliation-cache-": ProposalMatchCache, "reconciliation-relation-": ProposalRelation,
    "reconciliation-merge-": ProposalMergeJournal, "write-verification-": WriteVerification,
    "activity-report-": ActivityReport,
}
PREFIXES: dict[str, type[BaseModel]] = dict(sorted(_MODELS.items(), key=lambda item: -len(item[0])))
NAMES: dict[str, type[BaseModel]] = {
    "action-ledger": ActionLedger, "command-inbox": CommandInboxState, "duplicate-index": DuplicateIndex,
    "irrelevant-senders": IrrelevantSenders, "telegram-dialog": TelegramDialogState,
    "telegram-offset": TelegramOffset, "telegram-outbox": TelegramOutboxState,
    "notification-queue": NotificationQueue, "setup-state": SetupState,
}


def model_for(name: str) -> tuple[str, type[BaseModel] | None]:
    if name in NAMES:
        return name, NAMES[name]
    for prefix, model in PREFIXES.items():
        if name.startswith(prefix):
            return prefix.rstrip("-"), model
    return "unmodelled", None


def serialized(value: Any) -> bytes:
    """Exactly the bytes :meth:`JsonStore.save` writes."""
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def check(directory: Path) -> dict[str, Any]:
    kinds: dict[str, dict[str, int]] = defaultdict(lambda: {"files": 0, "identical": 0, "rewritten": 0, "invalid": 0})
    digests: list[str] = []
    with tempfile.TemporaryDirectory() as scratch:
        copy = Path(scratch) / "state"
        shutil.copytree(directory, copy, ignore=shutil.ignore_patterns(".lock", "*.tmp"))
        with JsonStore(copy) as store:
            for path in sorted(copy.glob("*.json")):
                name = path.stem
                kind, model = model_for(name)
                original = path.read_bytes()
                counts = kinds[kind]
                counts["files"] += 1
                if model is None:
                    output = original
                else:
                    try:
                        loaded = store.peek_model(name, model)
                    except (CorruptState, ValueError):
                        loaded = None
                    if loaded is None:
                        counts["invalid"] += 1
                        output = original
                    else:
                        output = serialized(loaded.model_dump(mode="json"))
                        counts["identical" if output == original else "rewritten"] += 1
                digests.append(name + ":" + hashlib.sha256(output).hexdigest())
    return {"kinds": dict(sorted(kinds.items())),
            "digest": hashlib.sha256("\n".join(digests).encode("utf-8")).hexdigest()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rundlauf aller gespeicherten Zustände")
    parser.add_argument("directory", type=Path, help="Zustandsverzeichnis, z. B. data/production")
    parser.add_argument("--output", type=Path, help="JSON-Bericht; ohne Angabe auf die Standardausgabe")
    args = parser.parse_args(argv)
    if not args.directory.is_dir():
        print(f"Verzeichnis nicht gefunden: {args.directory}", file=sys.stderr)
        return 2
    text = json.dumps(check(args.directory), ensure_ascii=False, indent=2) + "\n"
    if args.output is None:
        sys.stdout.write(text)
    else:
        args.output.write_text(text, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
