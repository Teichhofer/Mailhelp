"""CLI path parsing remains native and does not hard-code either separator style."""
from pathlib import Path, PurePosixPath, PureWindowsPath
from contextlib import contextmanager
import sys

import pytest

from mailhelp.cli import _positive_int, main


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
    logger = CaptureLogger()
    monkeypatch.setattr("mailhelp.cli.load_all", lambda directory: captured.append(directory) or (None, None, [], None, "fingerprint"))
    monkeypatch.setattr("mailhelp.cli.build_logger", lambda *_args: logger)
    monkeypatch.setattr(sys, "argv", ["mailhelp", "--config-directory", spelling, "--check"])
    assert main() == 0
    assert captured == [Path(spelling)]
    assert capsys.readouterr().out == "Konfiguration ist gültig.\n"
    assert logger.events == [("INFO", "application", "application_started", {"parameters": {
        "config_directory": spelling, "check": True, "check_access": False, "max_mails": None,
    }})]


def test_cli_forwards_mail_limit_and_rejects_non_positive_values(monkeypatch):
    class App:
        def __init__(self): self.limit = None
        def run(self, max_mails=None): self.limit = max_mails

    application = App()
    logger = CaptureLogger()
    @contextmanager
    def builder(*_args, **_kwargs):
        yield application
    monkeypatch.setattr("mailhelp.cli.load_all", lambda _directory: (None, None, [], None, "fingerprint"))
    monkeypatch.setattr("mailhelp.cli.build_logger", lambda *_args: logger)
    monkeypatch.setattr("mailhelp.cli.build_application", builder)
    monkeypatch.setattr("mailhelp.cli.signal.signal", lambda *_args: None)
    monkeypatch.setattr(sys, "argv", ["mailhelp", "--max-mails", "10"])

    assert main() == 0
    assert application.limit == 10
    assert logger.events[-1][3]["parameters"] == {
        "config_directory": ".", "check": False, "check_access": False, "max_mails": 10,
    }
    assert _positive_int("1") == 1
    with pytest.raises(Exception, match="mindestens 1"):
        _positive_int("0")
