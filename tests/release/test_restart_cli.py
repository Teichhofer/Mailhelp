"""A restart replaces only Mailhelp, after resources close, preserving all CLI arguments."""
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from mailhelp import cli
from mailhelp.lifecycle import Lifecycle


@pytest.mark.parametrize("restart", [False, True])
def test_run_returns_restart_only_after_clean_shutdown(monkeypatch, restart):
    events = []
    lifecycle = Lifecycle(lambda: events.append("stop"), lambda actor: True)
    if restart:
        lifecycle.request(lifecycle.process, "a" * 32, "actor", restart=True)()

    class App:
        def stop(self):
            events.append("signal-stop")

        def confirm_access_in_background(self):
            events.append("access")

        def run(self, **kwargs):
            assert kwargs == {"max_mails": None}
            events.append("run")
            lifecycle.finished()

    application = App()
    application.lifecycle = lifecycle

    @contextmanager
    def build(*args, **kwargs):
        events.append("open")
        yield application
        events.append("closed")

    monkeypatch.setattr(cli, "build_application", build)
    args = SimpleNamespace(config_directory=Path("synthetic-config"), check_access=False, learn=None,
                           ignore_historical_start=False, max_mails=None)
    result = cli._run(args, None, None, [], [], None, "fingerprint", None, None, cli._SignalShutdown())
    assert result == (cli.RESTART_EXIT_CODE if restart else 0)
    assert events[-1] == "closed"


def test_main_executes_same_interpreter_and_arguments(monkeypatch):
    arguments = ["mailhelp.exe", "--config-directory", "C:/Configuration with spaces", "--ollama", "localhost:11434"]
    monkeypatch.setattr(sys, "argv", arguments)
    monkeypatch.setattr(cli, "_main", lambda: cli.RESTART_EXIT_CODE)

    def replace(executable, argv):
        assert executable == sys.executable
        assert argv == [sys.executable, "-c", "from mailhelp.cli import main; raise SystemExit(main())", *arguments[1:]]
        raise SystemExit(0)  # Successful exec never returns to the old process.

    monkeypatch.setattr(cli.os, "execv", replace)
    with pytest.raises(SystemExit) as raised:
        cli.main()
    assert raised.value.code == 0


def test_failed_process_restart_is_reported_once(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_main", lambda: cli.RESTART_EXIT_CODE)
    calls = []

    def unavailable(*args):
        calls.append(args)
        raise OSError("synthetic executable unavailable")

    monkeypatch.setattr(cli.os, "execv", unavailable)
    assert cli.main() == 1 and len(calls) == 1
    assert "Neustart fehlgeschlagen" in capsys.readouterr().err
