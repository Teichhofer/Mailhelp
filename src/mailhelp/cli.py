"""Kommandozeileneinstieg und kontrollierter Signal-Shutdown."""
from __future__ import annotations
import argparse, signal
from pathlib import Path
from .application import build_application, build_logger
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
        "--check-access", action="store_true",
        help="Zugangsdaten und Zielzugriffe nur lesend prüfen und beenden",
    )
    parser.add_argument(
        "--max-mails", type=_positive_int, metavar="ANZAHL",
        help="höchstens ANZAHL Mails in einem einzelnen Abrufdurchlauf bearbeiten und beenden",
    )
    args = parser.parse_args(); settings, secrets, topics, prompts, fingerprint = load_all(args.config_directory)
    logger = build_logger(settings, secrets)
    logger.event("INFO", "application", "application_started", parameters={
        "config_directory": str(args.config_directory),
        "check": args.check,
        "check_access": args.check_access,
        "max_mails": args.max_mails,
    })
    if args.check: print("Konfiguration ist gültig."); return 0
    with build_application(
        settings, secrets, topics, prompts, fingerprint,
        access_diagnostics=args.check_access, logger=logger,
    ) as application:
        if args.check_access:
            results = application.check_access()
            for name, error in results.items():
                print(f"{'OK' if error is None else 'FEHLER'}: {name}" + (f" – {error}" if error else ""))
            return 1 if any(error is not None for error in results.values()) else 0
        def stop(_signum: int, _frame: object) -> None: application.stop()
        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGTERM, stop)
        application.run(max_mails=args.max_mails)
    return 0
