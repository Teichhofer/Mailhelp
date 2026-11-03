"""A restart replaces only Mailhelp, after resources close, preserving all CLI arguments."""
import subprocess
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


CODE = "from mailhelp.cli import main; raise SystemExit(main())"
ARGUMENTS = ["mailhelp.exe", "--config-directory", "C:/Configuration with spaces", "--ollama", "localhost:11434"]


def test_main_executes_same_interpreter_and_arguments(monkeypatch):
    monkeypatch.setattr(sys, "argv", ARGUMENTS)
    monkeypatch.setattr(cli, "_WINDOWS", False)
    monkeypatch.setattr(cli, "_main", lambda: cli.RESTART_EXIT_CODE)

    def replace(executable, argv):
        assert executable == sys.executable
        assert argv == [sys.executable, "-c", CODE, *ARGUMENTS[1:]]
        raise SystemExit(0)  # Successful exec never returns to the old process.

    monkeypatch.setattr(cli.os, "execv", replace)
    with pytest.raises(SystemExit) as raised:
        cli.main()
    assert raised.value.code == 0


def test_failed_process_restart_is_reported_once(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_WINDOWS", False)
    monkeypatch.setattr(cli, "_main", lambda: cli.RESTART_EXIT_CODE)
    calls = []

    def unavailable(*args):
        calls.append(args)
        raise OSError("synthetic executable unavailable")

    monkeypatch.setattr(cli.os, "execv", unavailable)
    assert cli.main() == 1 and len(calls) == 1
    assert "Neustart fehlgeschlagen" in capsys.readouterr().err


class Child:
    """A started Mailhelp child; ``wait`` yields the given results or raises them."""

    def __init__(self, *results):
        self.results = list(results)

    def wait(self):
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def test_windows_restart_keeps_the_console_and_quotes_the_command(monkeypatch):
    # Regression: os.execv on Windows passed "-c from mailhelp.cli import ..." unquoted,
    # so the new process failed with "SyntaxError: invalid syntax" and Mailhelp stayed down.
    monkeypatch.setattr(sys, "argv", ARGUMENTS)
    monkeypatch.setattr(cli, "_WINDOWS", True)
    monkeypatch.delenv(cli.RESTART_CHILD, raising=False)
    monkeypatch.setattr(cli, "_main", lambda: cli.RESTART_EXIT_CODE)

    def no_exec(*args):
        raise AssertionError("os.execv is unusable on Windows")

    monkeypatch.setattr(cli.os, "execv", no_exec)
    started, children = [], [Child(cli.RESTART_EXIT_CODE), Child(KeyboardInterrupt(), 0)]

    def popen(command, env):
        started.append((command, env))
        return children.pop(0)

    monkeypatch.setattr(cli.subprocess, "Popen", popen)
    # A child that asks for a restart is started again; Ctrl+C waits for the child to end.
    assert cli.main() == 0 and len(started) == 2
    command, env = started[0]
    assert command == [sys.executable, "-c", CODE, *ARGUMENTS[1:]] and env[cli.RESTART_CHILD] == "1"
    assert f'"{CODE}"' in subprocess.list2cmdline(command)


def test_a_windows_child_hands_the_restart_back_to_its_supervisor(monkeypatch):
    monkeypatch.setattr(cli, "_WINDOWS", True)
    monkeypatch.setenv(cli.RESTART_CHILD, "1")
    monkeypatch.setattr(cli, "_main", lambda: cli.RESTART_EXIT_CODE)

    def no_child(*args, **kwargs):
        raise AssertionError("a child never starts another child")

    monkeypatch.setattr(cli.subprocess, "Popen", no_child)
    assert cli.main() == cli.RESTART_EXIT_CODE


def test_a_failed_windows_restart_is_reported(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_WINDOWS", True)
    monkeypatch.delenv(cli.RESTART_CHILD, raising=False)
    monkeypatch.setattr(cli, "_main", lambda: cli.RESTART_EXIT_CODE)

    def unavailable(command, env):
        raise OSError("synthetic executable unavailable")

    monkeypatch.setattr(cli.subprocess, "Popen", unavailable)
    assert cli.main() == 1
    assert "Neustart fehlgeschlagen" in capsys.readouterr().err
