"""Kommandozeileneinstieg und kontrollierter Signal-Shutdown."""
from __future__ import annotations
import argparse, signal, shutil
from contextlib import ExitStack
from pathlib import Path
from .application import build_application, build_logger
from .config import Settings, load_all
from .learning import LearningMode
from .storage import JsonStore


CLEAR_CONFIRMATION = "ALLE DATEN LOESCHEN"


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("muss mindestens 1 sein")
    return parsed


def _remove_directory_contents(directory: Path, *, keep: set[str] = frozenset()) -> None:
    """Remove entries without following directory symlinks."""
    if not directory.exists():
        return
    for entry in directory.iterdir():
        if entry.name in keep:
            continue
        if entry.is_symlink() or entry.is_file():
            entry.unlink()
        else:
            shutil.rmtree(entry)


def clear_runtime_data(settings: Settings, log_directory: Path | None = None) -> None:
    """Delete all configured state namespaces and logs while holding state locks."""
    data_root = Path(settings.data_directory)
    logs = log_directory if log_directory is not None else Path(settings.logging.directory)
    namespaces = [data_root / "test", data_root / "production"]
    existing = [path for path in namespaces if path.exists()]
    logs_contain_state = any(logs == path or logs in path.parents for path in existing)
    with ExitStack() as stack:
        for path in existing:
            stack.enter_context(JsonStore(path))
        for path in existing:
            _remove_directory_contents(path, keep={".lock"})
        if not logs_contain_state:
            _remove_directory_contents(logs)
    for path in existing:
        (path / ".lock").unlink(missing_ok=True)
        path.rmdir()
    if data_root.exists() and not any(data_root.iterdir()):
        data_root.rmdir()
    if logs_contain_state:
        _remove_directory_contents(logs)
    if logs.exists() and not any(logs.iterdir()):
        logs.rmdir()


def main() -> int:
    parser = argparse.ArgumentParser(description="Mailhelp E-Mail-Assistent")
    parser.add_argument("--config-directory", type=Path, default=Path("."))
    parser.add_argument(
        "--log-directory", type=Path,
        help="Logverzeichnis aus config.yaml für diesen Aufruf überschreiben",
    )
    parser.add_argument("--check", action="store_true", help="Konfiguration validieren und beenden")
    parser.add_argument(
        "--check-access", action="store_true",
        help="Zugänge prüfen, Telegram-Testnachricht senden und beenden",
    )
    parser.add_argument(
        "--max-mails", type=_positive_int, metavar="ANZAHL",
        help="höchstens ANZAHL Mails in einem einzelnen Abrufdurchlauf bearbeiten und beenden",
    )
    parser.add_argument(
        "--learn", type=_positive_int, metavar="ANZAHL",
        help="ANZAHL Mails frei klassifizieren und Themen interaktiv im Terminal lernen",
    )
    parser.add_argument(
        "--clear", action="store_true",
        help="alle Zustandsdaten und Logs nach ausdrücklicher Bestätigung löschen",
    )
    parser.add_argument(
        "--yes", action="store_true",
        help="Bestätigungsabfrage für --clear überspringen",
    )
    args = parser.parse_args(); settings, secrets, topics, irrelevant_topics, prompts, fingerprint = load_all(args.config_directory)
    if args.yes and not args.clear:
        parser.error("--yes ist nur zusammen mit --clear zulässig")
    if args.clear:
        if not args.yes:
            answer = input(
                "ACHTUNG: Alle Zustandsdaten und Logs werden unwiderruflich gelöscht.\n"
                f"Zum Fortfahren exakt {CLEAR_CONFIRMATION!r} eingeben: "
            )
            if answer != CLEAR_CONFIRMATION:
                print("Löschen abgebrochen.")
                return 1
        clear_runtime_data(settings, args.log_directory)
        print("Alle Zustandsdaten und Logs wurden gelöscht.")
        return 0
    logger = build_logger(settings, secrets, log_directory=args.log_directory)
    logger.event("INFO", "application", "application_started", parameters={
        "config_directory": str(args.config_directory),
        "log_directory": str(args.log_directory) if args.log_directory is not None else None,
        "check": args.check,
        "check_access": args.check_access,
        "max_mails": args.max_mails,
        "learn": args.learn,
        "clear": args.clear,
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
        if args.learn is not None:
            LearningMode(
                application.imap, application.analyzer, settings.imap.folders,
                settings.limits, topics, args.config_directory / "topics.yaml",
                irrelevant_topics, args.config_directory / "irrelevant_topics.yaml",
                timezone=settings.timezone,
            ).run(args.learn)
            return 0
        def stop(_signum: int, _frame: object) -> None: application.stop()
        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGTERM, stop)
        application.run(max_mails=args.max_mails)
    return 0
