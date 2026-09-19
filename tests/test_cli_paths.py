"""CLI path parsing remains native and does not hard-code either separator style."""
from pathlib import Path, PurePosixPath, PureWindowsPath
from contextlib import contextmanager
from types import SimpleNamespace
import sys

import pytest

from mailhelp.cli import CLEAR_CONFIRMATION, _positive_int, clear_runtime_data, main


class CaptureLogger:
    def __init__(self):
        self.events = []

    def event(self, level, module, event, **context):
        self.events.append((level, module, event, context))


@pytest.mark.parametrize("spelling", [
    str(PurePosixPath("workspace/Mailhelp/config")),
    str(PureWindowsPath(r"C:\Mailhelp\config")),
])
def test_cli_forwards_posix_and_windows_path_spellings(monkeypatch, capsys, spelling):
    captured = []
    logger_arguments = []
    logger = CaptureLogger()
    monkeypatch.setattr("mailhelp.cli.load_all", lambda directory: captured.append(directory) or (None, None, [], [], None, "fingerprint"))
    monkeypatch.setattr(
        "mailhelp.cli.build_logger",
        lambda *_args, **kwargs: logger_arguments.append(kwargs) or logger,
    )
    log_directory = str(Path("writable") / "logs")
    monkeypatch.setattr(sys, "argv", [
        "mailhelp", "--config-directory", spelling, "--log-directory", log_directory, "--check",
    ])
    assert main() == 0
    assert captured == [Path(spelling)]
    assert logger_arguments == [{"log_directory": Path(log_directory)}]
    assert capsys.readouterr().out == "Konfiguration ist gültig.\n"
    assert logger.events == [("INFO", "application", "application_started", {"parameters": {
        "config_directory": spelling, "log_directory": log_directory,
        "check": True, "check_access": False, "max_mails": None, "learn": None,
        "clear": False,
    }})]


def test_cli_forwards_mail_limit_and_rejects_non_positive_values(monkeypatch):
    class App:
        def __init__(self): self.limit = None
        def run(self, max_mails=None): self.limit = max_mails

    application = App()
    logger = CaptureLogger()
    @contextmanager
    def builder(*_args, **kwargs):
        assert kwargs == {"access_diagnostics": False, "logger": logger}
        yield application
    monkeypatch.setattr("mailhelp.cli.load_all", lambda _directory: (None, None, [], [], None, "fingerprint"))
    monkeypatch.setattr("mailhelp.cli.build_logger", lambda *_args, **_kwargs: logger)
    monkeypatch.setattr("mailhelp.cli.build_application", builder)
    monkeypatch.setattr("mailhelp.cli.signal.signal", lambda *_args: None)
    monkeypatch.setattr(sys, "argv", ["mailhelp", "--max-mails", "10"])

    assert main() == 0
    assert application.limit == 10
    assert logger.events[-1][3]["parameters"] == {
        "config_directory": ".", "log_directory": None,
        "check": False, "check_access": False, "max_mails": 10, "learn": None,
        "clear": False,
    }
    assert _positive_int("1") == 1
    with pytest.raises(Exception, match="mindestens 1"):
        _positive_int("0")


def test_cli_runs_terminal_learning_mode(monkeypatch):
    application = SimpleNamespace(imap="imap", analyzer="analyzer")
    settings = SimpleNamespace(
        imap=SimpleNamespace(folders=["INBOX"]), limits="limits", timezone="Europe/Berlin")
    logger = CaptureLogger()
    captured = []

    @contextmanager
    def builder(*_args, **_kwargs):
        yield application

    class Learning:
        def __init__(self, *args, **kwargs):
            captured.append((args, kwargs))
        def run(self, count):
            captured.append(count)

    monkeypatch.setattr("mailhelp.cli.load_all", lambda _directory: (
        settings, object(), ["topic"], ["irrelevant"], object(), "fingerprint"))
    monkeypatch.setattr("mailhelp.cli.build_logger", lambda *_args, **_kwargs: logger)
    monkeypatch.setattr("mailhelp.cli.build_application", builder)
    monkeypatch.setattr("mailhelp.cli.LearningMode", Learning)
    monkeypatch.setattr(sys, "argv", ["mailhelp", "--config-directory", "cfg", "--learn", "3"])

    assert main() == 0
    assert captured == [(('imap', 'analyzer', ['INBOX'], 'limits', ['topic'],
                           Path('cfg/topics.yaml'), ['irrelevant'],
                           Path('cfg/irrelevant_topics.yaml')), {'timezone': 'Europe/Berlin'}), 3]


def test_clear_removes_both_state_namespaces_and_logs(tmp_path):
    data = tmp_path / "data"
    logs = tmp_path / "logs"
    for mode in ("test", "production"):
        directory = data / mode
        directory.mkdir(parents=True)
        (directory / "state.json").write_text("{}", encoding="utf-8")
        (directory / "nested").mkdir()
        (directory / "nested" / "old.json").write_text("{}", encoding="utf-8")
    (logs / "llm").mkdir(parents=True)
    (logs / "application.jsonl").write_text("log", encoding="utf-8")
    (logs / "llm" / "requests.jsonl").write_text("log", encoding="utf-8")
    settings = SimpleNamespace(
        data_directory=data, logging=SimpleNamespace(directory=logs))

    clear_runtime_data(settings)

    assert not data.exists()
    assert not logs.exists()


def test_clear_supports_log_directory_containing_state(tmp_path):
    combined = tmp_path / "runtime"
    state = combined / "test"
    state.mkdir(parents=True)
    (state / "state.json").write_text("{}", encoding="utf-8")
    (combined / "application.jsonl").write_text("log", encoding="utf-8")
    settings = SimpleNamespace(
        data_directory=combined, logging=SimpleNamespace(directory=combined))

    clear_runtime_data(settings)

    assert not combined.exists()


@pytest.mark.parametrize(("answer", "expected_code", "message"), [
    ("nein", 1, "Löschen abgebrochen."),
    (CLEAR_CONFIRMATION, 0, "Alle Zustandsdaten und Logs wurden gelöscht."),
])
def test_clear_requires_exact_confirmation(monkeypatch, capsys, tmp_path, answer,
                                           expected_code, message):
    settings = SimpleNamespace(
        data_directory=tmp_path / "data",
        logging=SimpleNamespace(directory=tmp_path / "logs"),
    )
    (settings.data_directory / "test").mkdir(parents=True)
    marker = settings.data_directory / "test" / "state.json"
    marker.write_text("{}", encoding="utf-8")
    called = []
    monkeypatch.setattr("mailhelp.cli.load_all", lambda _directory: (
        settings, object(), [], [], object(), "fingerprint"))
    monkeypatch.setattr("builtins.input", lambda prompt: called.append(prompt) or answer)
    monkeypatch.setattr(sys, "argv", ["mailhelp", "--clear"])

    assert main() == expected_code
    assert message in capsys.readouterr().out
    assert len(called) == 1
    assert marker.exists() is (expected_code != 0)


def test_clear_yes_is_noninteractive_and_override_selects_logs(monkeypatch, capsys, tmp_path):
    configured_logs = tmp_path / "configured-logs"
    override_logs = tmp_path / "override-logs"
    override_logs.mkdir()
    (override_logs / "old.jsonl").write_text("log", encoding="utf-8")
    settings = SimpleNamespace(
        data_directory=tmp_path / "missing-data",
        logging=SimpleNamespace(directory=configured_logs),
    )
    monkeypatch.setattr("mailhelp.cli.load_all", lambda _directory: (
        settings, object(), [], [], object(), "fingerprint"))
    monkeypatch.setattr("builtins.input", lambda _prompt: pytest.fail("unexpected prompt"))
    monkeypatch.setattr(sys, "argv", [
        "mailhelp", "--clear", "--yes", "--log-directory", str(override_logs),
    ])

    assert main() == 0
    assert not override_logs.exists()
    assert not configured_logs.exists()
    assert "wurden gelöscht" in capsys.readouterr().out


def test_yes_without_clear_is_rejected(monkeypatch):
    monkeypatch.setattr("mailhelp.cli.load_all", lambda _directory: (
        None, None, [], [], None, "fingerprint"))
    monkeypatch.setattr(sys, "argv", ["mailhelp", "--yes"])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
