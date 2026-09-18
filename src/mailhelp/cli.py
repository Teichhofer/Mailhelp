"""Kommandozeileneinstieg und kontrollierter Signal-Shutdown."""
from __future__ import annotations
import argparse, signal
from pathlib import Path
from .application import build_application
from .config import load_all


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("muss mindestens 1 sein")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description="Mailhelp E-Mail-Assistent")
    parser.add_argument("--config-directory", type=Path, default=Path("."))
    parser.add_argument("--check", action="store_true", help="Konfiguration validieren und beenden")
    parser.add_argument(
        "--max-mails", type=_positive_int, metavar="ANZAHL",
        help="höchstens ANZAHL Mails in einem einzelnen Abrufdurchlauf bearbeiten und beenden",
    )
    args = parser.parse_args(); settings, secrets, topics, prompts, fingerprint = load_all(args.config_directory)
    if args.check: print("Konfiguration ist gültig."); return 0
    with build_application(settings, secrets, topics, prompts, fingerprint) as application:
        def stop(_signum: int, _frame: object) -> None: application.stop()
        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGTERM, stop)
        application.run(max_mails=args.max_mails)
    return 0
