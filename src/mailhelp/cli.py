"""Kommandozeileneinstieg und kontrollierter Signal-Shutdown."""
from __future__ import annotations

import argparse
import json
import shutil
import signal
import sys
from collections.abc import Callable, Set
from contextlib import ExitStack
from pathlib import Path

from .application import build_application, build_logger
from .config import LOCAL_NUM_CTX, Settings, load_all
from .decision_test import run_decision_test
from .decisions import load_relevance_prompts
from .learning import LearningMode
from .ollama import LocalLlm, parse_address
from .paths import runtime_path
from .storage import JsonStore

CLEAR_CONFIRMATION = "ALLE DATEN LOESCHEN"
CONFIGURATION_FILES = ("config.yaml", "prompts.yaml", "topics.yaml", "irrelevant_topics.yaml")


class _SignalShutdown:
    """Route signals to a running service or abort the current one-shot mode."""

    def __init__(self) -> None:
        self.stop: Callable[[], None] | None = None

    def __call__(self, _signum: int, _frame: object) -> None:
        if self.stop is None:
            raise KeyboardInterrupt
        self.stop()


def _default_config_directory() -> Path:
    """Prefer a complete configuration in cwd, then an editable checkout root."""
    working_directory = Path.cwd()
    if all((working_directory / name).is_file() for name in CONFIGURATION_FILES):
        return working_directory

    checkout_directory = Path(__file__).resolve().parents[2]
    if all((checkout_directory / name).is_file() for name in CONFIGURATION_FILES):
        return checkout_directory
    return working_directory


def _ollama_address(value: str) -> tuple[str, int]:
    try:
        return parse_address(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("muss mindestens 1 sein")
    return parsed


def _remove_directory_contents(directory: Path, *, keep: Set[str] = frozenset()) -> None:
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


def clear_runtime_data(settings: Settings, log_directory: Path | None = None,
                       base_directory: Path = Path(".")) -> None:
    """Delete all state namespaces, decision-test reports and logs while holding state locks.

    Decision-test reports contain complete raw mails and model contents, so they
    are runtime data like the state itself.
    """
    data_root = runtime_path(settings.data_directory, base_directory)
    reports = data_root / "decision-tests"
    logs = runtime_path(log_directory if log_directory is not None else settings.logging.directory,
                        base_directory)
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
    if reports.exists() and not reports.is_symlink():
        shutil.rmtree(reports)
    elif reports.is_symlink():
        reports.unlink()
    if data_root.exists() and not any(data_root.iterdir()):
        data_root.rmdir()
    if logs_contain_state:
        _remove_directory_contents(logs)
    if logs.exists() and not any(logs.iterdir()):
        logs.rmdir()


def main() -> int:
    """Run the CLI and turn Ctrl+C into a quiet, consistent process exit."""
    try:
        return _main()
    except KeyboardInterrupt:
        print("\nBeenden angefordert.")
        return 130


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mailhelp E-Mail-Assistent")
    parser.add_argument(
        "--config-directory", type=Path, default=_default_config_directory(),
        help=("Verzeichnis mit config.yaml, prompts.yaml, topics.yaml und "
              "irrelevant_topics.yaml"),
    )
    parser.add_argument(
        "--log-directory", type=Path,
        help="Logverzeichnis aus config.yaml für diesen Aufruf überschreiben",
    )
    parser.add_argument("--check", action="store_true", help="Konfiguration validieren und beenden")
    parser.add_argument("--pair", action="store_true", help="Lokalen Einmalcode zur Webanmeldung anzeigen")
    parser.add_argument(
        "--check-access", action="store_true",
        help="Zugänge prüfen, Telegram-Testnachricht senden und beenden",
    )
    parser.add_argument(
        "--show-imap-credentials", action="store_true",
        help=("bei --check-access den tatsächlich verwendeten IMAP-Benutzernamen "
              "und das Passwort im Terminal ausgeben"),
    )
    parser.add_argument(
        "--microsoft-login", action="store_true",
        help=("bei Microsoft (Outlook-Kalender, Microsoft To Do) per Gerätecode anmelden und den "
              "Refresh-Token in microsoft-token.json neben .env speichern"),
    )
    parser.add_argument(
        "--max-mails", type=_positive_int, metavar="ANZAHL",
        help="höchstens ANZAHL Mails in einem einzelnen Abrufdurchlauf bearbeiten und beenden",
    )
    parser.add_argument(
        "--ignore-historical-start", action="store_true",
        help=("konfiguriertes imap.historical_start und den gespeicherten "
              "historischen Startpunkt für diesen Abruf aufheben"),
    )
    parser.add_argument(
        "--learn", type=_positive_int, metavar="ANZAHL",
        help="ANZAHL Mails frei klassifizieren und Themen interaktiv im Terminal lernen",
    )
    parser.add_argument(
        "--clear", action="store_true",
        help="alle Zustandsdaten, Decision-Test-Berichte und Logs nach ausdrücklicher Bestätigung löschen",
    )
    parser.add_argument(
        "--yes", action="store_true",
        help="Bestätigungsabfrage für --clear überspringen",
    )
    parser.add_argument(
        "--ollama", type=_ollama_address, metavar="HOST:PORT",
        help=("EXPERIMENTELL: alle LLM-Schritte statt über OpenRouter über den lokalen "
              "Ollama-Server HOST:PORT ausführen (IPv6 als [::1]:11434)"),
    )
    parser.add_argument(
        "--ollama-model", metavar="NAME",
        help="Ollama-Modell für --ollama; überschreibt ollama.model aus prompts.yaml",
    )
    parser.add_argument(
        "--decision-test", type=_positive_int, metavar="ANZAHL",
        help="ANZAHL Mails über Standardpfad und Ollama vergleichen; nur relevante Mails weiter analysieren",
    )
    parser.add_argument(
        "--decision-test-file", type=Path, metavar="DATEI",
        help="neue JSON-Testdatei für --decision-test (relativ zu --config-directory)",
    )
    parser.add_argument(
        "--decision-test-laya", type=_ollama_address, metavar="HOST:PORT",
        help=("EXPERIMENTELL: Relevanzprüfung des Ollama-Pfads im --decision-test mit dem "
              "Entscheidungsmodell Laya auf diesem Ollama-Server (/v1/systemone)"),
    )
    parser.add_argument(
        "--decision-test-laya-model", metavar="NAME",
        help="Laya-Modell für --decision-test-laya; überschreibt model aus laya_prompts.yaml",
    )
    parser.add_argument(
        "--decision-test-relevance-only", action="store_true",
        help="im --decision-test ausschließlich die Relevanzprüfung beider Pfade vergleichen",
    )
    parser.add_argument(
        "--mailbox", type=int, metavar="NUMMER",
        help="Postfach (imap.mailboxes.id) für --learn und --decision-test; "
             "bei mehreren aktivierten Postfächern erforderlich",
    )
    return parser


def _check_decision_test_options(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.decision_test_file is not None and args.decision_test is None:
        parser.error("--decision-test-file ist nur zusammen mit --decision-test zulässig")
    if args.decision_test is None and (args.decision_test_laya is not None
                                       or args.decision_test_relevance_only):
        parser.error("--decision-test-laya und --decision-test-relevance-only "
                     "sind nur zusammen mit --decision-test zulässig")
    if args.decision_test_laya_model is not None and args.decision_test_laya is None:
        parser.error("--decision-test-laya-model ist nur zusammen mit --decision-test-laya zulässig")
    if args.decision_test is not None and any((
        args.check, args.check_access, args.show_imap_credentials, args.max_mails is not None,
        args.learn is not None, args.clear, args.yes, args.log_directory is not None,
    )):
        parser.error("--decision-test ist nicht mit anderen Modi, --max-mails oder --log-directory kombinierbar")
    if args.decision_test is not None and args.ollama is None:
        parser.error("--decision-test benötigt --ollama HOST:PORT")


def _check_mode_options(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.yes and not args.clear:
        parser.error("--yes ist nur zusammen mit --clear zulässig")
    if args.show_imap_credentials and not args.check_access:
        parser.error("--show-imap-credentials ist nur zusammen mit --check-access zulässig")


def _selected_mailbox(parser: argparse.ArgumentParser, args: argparse.Namespace, settings):
    """The one mailbox --learn and --decision-test read; never guessed among several (3.1)."""
    reads_one = args.learn is not None or args.decision_test is not None
    if args.mailbox is None and not reads_one:
        return None
    if not reads_one:
        parser.error("--mailbox ist nur zusammen mit --learn oder --decision-test zulässig")
    enabled = settings.imap.enabled_mailboxes()
    if args.mailbox is None:
        if len(enabled) > 1:
            parser.error("Mehrere Postfächer aktiviert: --mailbox NUMMER angeben")
        return enabled[0]
    selected = next((mailbox for mailbox in enabled if mailbox.id == args.mailbox), None)
    if selected is None:
        parser.error(f"--mailbox {args.mailbox}: kein aktiviertes Postfach mit dieser Nummer")
    return selected


def _local_llm(parser: argparse.ArgumentParser, args: argparse.Namespace, prompts) -> LocalLlm | None:
    local_llm = None
    if args.ollama_model is not None and args.ollama is None:
        parser.error("--ollama-model ist nur zusammen mit --ollama zulässig")
    if args.ollama is not None:
        model = args.ollama_model or (prompts.ollama.model if prompts.ollama else None)
        if not model:
            parser.error("--ollama benötigt ein Modell: --ollama-model NAME oder ollama.model in prompts.yaml")
        host, port = args.ollama
        local_llm = LocalLlm(host, port, model=model,
                             num_ctx=prompts.ollama.num_ctx if prompts.ollama else LOCAL_NUM_CTX,
                             num_thread=prompts.ollama.num_thread if prompts.ollama else None,
                             think=prompts.ollama.think if prompts.ollama else None)
    return local_llm


def _clear(args: argparse.Namespace, settings) -> int:
    if not args.yes:
        answer = input(
            "ACHTUNG: Alle Zustandsdaten, Decision-Test-Berichte und Logs werden "
            "unwiderruflich gelöscht.\n"
            f"Zum Fortfahren exakt {CLEAR_CONFIRMATION!r} eingeben: "
        )
        if answer != CLEAR_CONFIRMATION:
            print("Löschen abgebrochen.")
            return 1
    clear_runtime_data(settings, args.log_directory, args.config_directory)
    print("Alle Zustandsdaten, Decision-Test-Berichte und Logs wurden gelöscht.")
    return 0


def _microsoft_login(settings, secrets, directory: Path) -> int:
    """Device-code sign-in; the terminal shows only the code and address, never a token."""
    from .external.contracts import OAuthTokenError
    from .external.providers import microsoft_tokens
    if not secrets.microsoft_client_id.get_secret_value():
        print("MICROSOFT_CLIENT_ID fehlt in .env oder der Prozessumgebung.", file=sys.stderr)
        return 1
    tokens = microsoft_tokens(settings, secrets, directory, settings.timeouts.microsoft.timeout_seconds)
    try:
        tokens.device_login(print)
    except OAuthTokenError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1
    finally:
        tokens.close()
    return 0


def _log_start(logger, args: argparse.Namespace, local_llm: LocalLlm | None) -> None:
    logger.event("INFO", "application", "application_started", parameters={
        "config_directory": str(args.config_directory),
        "log_directory": str(args.log_directory) if args.log_directory is not None else None,
        "check": args.check,
        "check_access": args.check_access,
        "show_imap_credentials": args.show_imap_credentials,
        "max_mails": args.max_mails,
        "ignore_historical_start": args.ignore_historical_start,
        "learn": args.learn,
        "clear": args.clear,
        "ollama": local_llm.base_url if local_llm else None,
        "ollama_model": local_llm.model if local_llm else None,
    })


def _show_imap_credentials(secrets) -> None:
    # JSON quoting makes control characters visible instead of allowing a
    # secret loaded from the environment to manipulate the terminal.
    print("ACHTUNG: IMAP-Zugangsdaten werden nur in diesem Terminal ausgegeben.")
    for number, credentials in sorted(secrets.imap.items()):
        prefix = "" if len(secrets.imap) == 1 else f"Postfach {number} – "
        print(f"{prefix}IMAP-Benutzername: {json.dumps(credentials.username, ensure_ascii=False)}")
        print(f"{prefix}IMAP-Passwort: {json.dumps(credentials.password.get_secret_value(), ensure_ascii=False)}")


def _run(args: argparse.Namespace, settings, secrets, topics, irrelevant_topics, prompts, fingerprint,
         logger, local_llm: LocalLlm | None, shutdown: _SignalShutdown, mailbox=None) -> int:
    with build_application(
        settings, secrets, topics, prompts, fingerprint,
        base_directory=args.config_directory,
        access_diagnostics=args.check_access, logger=logger,
        local_llm=local_llm, use_jev_relevance=args.learn is None,
    ) as application:
        if args.check_access:
            results = application.check_access()
            for name, error in results.items():
                print(f"{'OK' if error is None else 'FEHLER'}: {name}" + (f" – {error}" if error else ""))
            return 1 if any(error is not None for error in results.values()) else 0
        if args.learn is not None:
            reader = next(source.reader for source in application.sources if source.mailbox.id == mailbox.id)
            LearningMode(
                reader, application.analyzer, mailbox.folders,
                settings.limits, topics, args.config_directory / "topics.yaml",
                irrelevant_topics, args.config_directory / "irrelevant_topics.yaml",
                application.sender_store,
                timezone=settings.timezone,
                parallel_llm_calls=settings.learning.parallel_llm_calls,
                global_newest_first=getattr(settings.imap, "global_newest_first", False),
                config_path=args.config_directory / "config.yaml",
                folders_path=("imap.folders" if settings.imap.legacy_format else
                              f"imap.mailboxes.{settings.imap.configured_mailboxes().index(mailbox)}.folders"),
            ).run(args.learn)
            return 0
        shutdown.stop = application.stop
        if args.ignore_historical_start:
            fatal_error = application.run(
                max_mails=args.max_mails,
                ignore_historical_start=True,
            )
        else:
            fatal_error = application.run(max_mails=args.max_mails)
        if fatal_error is not None:
            print(f"FATALER FEHLER: {fatal_error}", file=sys.stderr)
            return 1
    return 0


def _main() -> int:
    parser = _parser()
    args = parser.parse_args()
    _check_decision_test_options(parser, args)
    shutdown = _SignalShutdown()
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    if args.pair:
        from .local_pairing import request_local_code
        request_local_code(args.config_directory)
        return 0
    settings, secrets, topics, irrelevant_topics, prompts, fingerprint = load_all(args.config_directory)
    if args.microsoft_login:
        return _microsoft_login(settings, secrets, args.config_directory)
    _check_mode_options(parser, args)
    mailbox = _selected_mailbox(parser, args, settings)
    local_llm = _local_llm(parser, args, prompts)
    if args.decision_test is not None:
        assert local_llm is not None  # _check_mode_options requires --ollama for decision tests
        return run_decision_test(
            settings, secrets, topics, prompts, args.decision_test, args.config_directory,
            args.decision_test_file, local_llm=local_llm,
            ignore_historical_start=args.ignore_historical_start,
            laya=args.decision_test_laya, laya_model=args.decision_test_laya_model,
            relevance_only=args.decision_test_relevance_only, irrelevant_topics=irrelevant_topics,
            mailbox=mailbox,
        )
    if args.clear:
        return _clear(args, settings)
    logger = build_logger(settings, secrets, base_directory=args.config_directory,
                          log_directory=args.log_directory)
    _log_start(logger, args, local_llm)
    if args.check:
        if local_llm is None:
            load_relevance_prompts(args.config_directory)
        print("Konfiguration ist gültig.")
        return 0
    if args.show_imap_credentials:
        _show_imap_credentials(secrets)
    return _run(args, settings, secrets, topics, irrelevant_topics, prompts, fingerprint,
                logger, local_llm, shutdown, mailbox)
